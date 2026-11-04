"""Captcha detection + solver chain (E-35..E-39, E-48)."""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from adapters.base import CaptchaError, CaptchaTimeout
from obs.log import get_logger

log = get_logger("captcha")

CAPSOLVER_API = "https://api.capsolver.com"
TWOCAPTCHA_API = "https://2captcha.com"

RECAPTCHA_V2 = "recaptcha_v2"
RECAPTCHA_V3 = "recaptcha_v3"
ARKOSE = "arkose"
HCAPTCHA = "hcaptcha"

_SITEKEY_RE = re.compile(r"(?:[?&]k=|data-sitekey=[\"'])([A-Za-z0-9_\-]{20,})")


@dataclass(slots=True)
class CaptchaChallenge:
    kind: str
    sitekey: str | None
    page_url: str
    iframe_src: str | None = None


class Solver(Protocol):
    name: str

    async def solve(self, challenge: CaptchaChallenge, *, proxy: str | None = None) -> str: ...


class CapsolverSolver:
    name = "capsolver"

    def __init__(self, api_key: str, *, timeout_s: int = 90, poll_s: float = 3.0, client: httpx.AsyncClient | None = None):
        self.api_key = api_key
        self.timeout_s = timeout_s
        self.poll_s = poll_s
        self._client = client or httpx.AsyncClient(timeout=30)

    def _task_type(self, kind: str) -> str:
        return {
            RECAPTCHA_V2: "ReCaptchaV2TaskProxyLess",
            RECAPTCHA_V3: "ReCaptchaV3TaskProxyLess",
            ARKOSE: "FunCaptchaTaskProxyLess",
            HCAPTCHA: "HCaptchaTaskProxyLess",
        }.get(kind, "ReCaptchaV2TaskProxyLess")

    async def solve(self, challenge: CaptchaChallenge, *, proxy: str | None = None) -> str:
        task: dict[str, Any] = {"type": self._task_type(challenge.kind), "websiteURL": challenge.page_url}
        if challenge.sitekey:
            task["websiteKey"] = challenge.sitekey
        if challenge.kind == RECAPTCHA_V3:
            task["pageAction"] = "signup"
            task["minScore"] = 0.7
        if challenge.kind == ARKOSE and challenge.sitekey:
            task["websitePublicKey"] = challenge.sitekey
        payload = {"clientKey": self.api_key, "task": task}
        async with httpx.AsyncClient(timeout=30) as client:
            created = (await client.post(f"{CAPSOLVER_API}/createTask", json=payload)).json()
            if created.get("errorId"):
                raise CaptchaError(f"capsolver createTask: {created.get('errorDescription')}")
            task_id = created["taskId"]
            deadline = time.monotonic() + self.timeout_s
            while time.monotonic() < deadline:
                await asyncio.sleep(self.poll_s)
                result = (await client.post(f"{CAPSOLVER_API}/getTaskResult", json={"clientKey": self.api_key, "taskId": task_id})).json()
                if result.get("errorId"):
                    raise CaptchaError(f"capsolver getTaskResult: {result.get('errorDescription')}")
                if result.get("status") == "ready":
                    solution = result.get("solution") or {}
                    token = solution.get("gRecaptchaResponse") or solution.get("token") or solution.get("captchaToken")
                    if not token:
                        raise CaptchaError("capsolver returned no token")
                    return token
        raise CaptchaTimeout(f"capsolver timeout after {self.timeout_s}s")


class TwoCaptchaSolver:
    name = "2captcha"

    def __init__(self, api_key: str, *, timeout_s: int = 90, poll_s: float = 5.0):
        self.api_key = api_key
        self.timeout_s = timeout_s
        self.poll_s = poll_s

    async def solve(self, challenge: CaptchaChallenge, *, proxy: str | None = None) -> str:
        method = {
            RECAPTCHA_V2: "userrecaptcha",
            RECAPTCHA_V3: "userrecaptcha",
            HCAPTCHA: "hcaptcha",
            ARKOSE: "funcaptcha",
        }.get(challenge.kind, "userrecaptcha")
        params = {"key": self.api_key, "method": method, "pageurl": challenge.page_url, "json": 1}
        if challenge.kind == RECAPTCHA_V3:
            params.update({"version": "v3", "action": "signup", "min_score": 0.7})
        if challenge.sitekey:
            params["googlekey" if challenge.kind.startswith("recaptcha") else "publickey"] = challenge.sitekey
        async with httpx.AsyncClient(timeout=30) as client:
            created = (await client.post(f"{TWOCAPTCHA_API}/in.php", data=params)).json()
            if created.get("status") != 1:
                raise CaptchaError(f"2captcha in.php: {created.get('request')}")
            request_id = created["request"]
            deadline = time.monotonic() + self.timeout_s
            while time.monotonic() < deadline:
                await asyncio.sleep(self.poll_s)
                result = (
                    await client.get(
                        f"{TWOCAPTCHA_API}/res.php",
                        params={"key": self.api_key, "action": "get", "id": request_id, "json": 1},
                    )
                ).json()
                if result.get("status") == 1:
                    return result["request"]
                if result.get("request") not in ("CAPCHA_NOT_READY", "CAPTCHA_NOT_READY"):
                    raise CaptchaError(f"2captcha: {result.get('request')}")
        raise CaptchaTimeout("2captcha timeout")


class HumanInLoopSolver:
    """Last resort: park the browser and wait for a human to solve it (E-35/E-37)."""

    name = "human"

    def __init__(self, timeout_s: int = 600, artifact_writer=None):
        self.timeout_s = timeout_s
        self.artifact_writer = artifact_writer

    async def solve(self, challenge: CaptchaChallenge, *, proxy: str | None = None) -> str:
        if self.artifact_writer:
            await self.artifact_writer(challenge)
        raise CaptchaError("human-in-loop required", code="captcha_hitl")


class FakeSolver:
    name = "fake"

    def __init__(self, token: str = "fake-token", fail_times: int = 0, delay_s: float = 0.0):
        self.token = token
        self.fail_times = fail_times
        self.delay_s = delay_s
        self.calls = 0

    async def solve(self, challenge: CaptchaChallenge, *, proxy: str | None = None) -> str:
        self.calls += 1
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        if self.calls <= self.fail_times:
            raise CaptchaError("fake solver failure")
        return self.token


async def detect(page) -> CaptchaChallenge | None:
    url = page.url
    for frame in page.frames:
        src = frame.url or ""
        if "recaptcha" in src and ("api2/anchor" in src or "bframe" in src):
            sitekey = _sitekey(src)
            return CaptchaChallenge(RECAPTCHA_V2, sitekey, url, src)
        if "arkoselabs" in src or "funcaptcha" in src:
            return CaptchaChallenge(ARKOSE, _sitekey(src), url, src)
        if "hcaptcha" in src:
            return CaptchaChallenge(HCAPTCHA, _sitekey(src), url, src)
    try:
        html = await page.content()
    except Exception:  # noqa: BLE001
        return None
    if "recaptcha/api.js?render=" in html or "grecaptcha.execute" in html:
        return CaptchaChallenge(RECAPTCHA_V3, _sitekey(html), url)
    if "g-recaptcha" in html:
        return CaptchaChallenge(RECAPTCHA_V2, _sitekey(html), url)
    return None


def _sitekey(text: str) -> str | None:
    match = _SITEKEY_RE.search(text or "")
    return match.group(1) if match else None


async def inject_token(page, challenge: CaptchaChallenge, token: str) -> None:
    if challenge.kind in (RECAPTCHA_V2, RECAPTCHA_V3):
        await page.evaluate(
            """(token) => {
                const apply = (el) => { el.value = token; el.innerHTML = token; };
                document.querySelectorAll('textarea#g-recaptcha-response, input[name="g-recaptcha-response"]').forEach(apply);
                const cb = window.___grecaptcha_cfg && window.___grecaptcha_cfg.clients;
                if (window.___grecaptcha_callback) { try { window.___grecaptcha_callback(token); } catch (e) {} }
            }""",
            token,
        )
    elif challenge.kind == HCAPTCHA:
        await page.evaluate(
            """(token) => {
                document.querySelectorAll('[name="h-captcha-response"], textarea#h-captcha-response')
                    .forEach(el => { el.value = token; el.innerHTML = token; });
            }""",
            token,
        )
    elif challenge.kind == ARKOSE:
        await page.evaluate(
            """(token) => {
                document.querySelectorAll('input[name="fc-token"], input[name="arkose-token"]')
                    .forEach(el => el.value = token);
            }""",
            token,
        )


async def token_present(page) -> bool:
    return await page.evaluate(
        """() => {
            const nodes = document.querySelectorAll('textarea#g-recaptcha-response, input[name="g-recaptcha-response"], [name="h-captcha-response"]');
            return Array.from(nodes).some(n => n.value && n.value.length > 20);
        }"""
    )


class CaptchaChain:
    def __init__(self, solvers: list[Solver], *, attempts_per_solver: int = 1):
        self.solvers = solvers
        self.attempts_per_solver = attempts_per_solver

    async def solve(self, challenge: CaptchaChallenge, *, proxy: str | None = None, page=None) -> str:
        last_error: Exception | None = None
        for solver in self.solvers:
            for _ in range(self.attempts_per_solver):
                try:
                    token = await solver.solve(challenge, proxy=proxy)
                    if page is not None:
                        await inject_token(page, challenge, token)
                        if not await token_present(page):
                            raise CaptchaError(
                                f"token not present after {getattr(solver, 'name', type(solver).__name__)}"
                            )
                    return token
                except (CaptchaError, CaptchaTimeout) as exc:
                    last_error = exc
                    log.warning("solver_failed", solver=getattr(solver, "name", type(solver).__name__), kind=challenge.kind, error=str(exc)[:200])
        raise CaptchaError(f"all solvers failed: {last_error}")


def build_chain(cfg) -> CaptchaChain:
    solvers: list[Solver] = []
    for provider in cfg.providers:
        if provider == "capsolver" and cfg.capsolver_key:
            solvers.append(CapsolverSolver(cfg.capsolver_key, timeout_s=cfg.timeout_s, poll_s=cfg.poll_interval_s))
        elif provider == "2captcha" and cfg.two_captcha_key:
            solvers.append(TwoCaptchaSolver(cfg.two_captcha_key, timeout_s=cfg.timeout_s))
    if cfg.human_in_loop:
        solvers.append(HumanInLoopSolver())
    return CaptchaChain(solvers)
