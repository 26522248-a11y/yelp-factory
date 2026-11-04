"""Signup flow: NEW -> ACTIVE (section 6).

Every stage raises :class:`adapters.base.YFError` with the edge-case code so the machine,
the quarantine writer and the metrics all agree on the reason.
"""

from __future__ import annotations

import asyncio
import random
from pathlib import Path
import time
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from adapters.base import (
    BrowserAttachError,
    CaptchaError,
    GeoMismatch,
    GPMConflict,
    GPMSchemaDrift,
    GPMUnavailable,
    NoVerificationMail,
    ProfileDTO,
    ProxyDead,
    ProxyTooSlow,
    SelectorMiss,
    SMSError,
    YFError,
)
from adapters.browser import attach
from adapters.captcha import CaptchaChain, detect as detect_captcha
from adapters.gpm_ops import ensure_profile, profile_name
from adapters.proxy_probe import ProxyTarget, probe
from core.backoff import RetryPolicy
from core.checkpoints import persist_account_state
from core.state_machine import Stage, StageContext
from db.models import AccountState
from flows.pools import Persona, build_persona, generate_password, pick_zip
from human.mouse import human_click, read_pause
from human.scroll import scroll_page
from human.timing import idle, session_length_seconds
from human.typing import human_type
from obs.log import get_logger

log = get_logger("flows.signup")

SIGNUP_URL = "https://www.yelp.com/signup?locale=en_US"
HOME_URL = "https://www.yelp.com/?locale=en_US"
ALLOWED_HOSTS = {"www.yelp.com", "yelp.com"}


def _host(url: str) -> str:
    return urlparse(url).netloc.lower()


class SignupFlow:
    def __init__(
        self,
        *,
        settings,
        gpm,
        registry,
        email_provider,
        captcha_chain: CaptchaChain | None = None,
        sms_provider=None,
        artifacts=None,
    ):
        self.settings = settings
        self.gpm = gpm
        self.registry = registry
        self.email = email_provider
        self.captcha = captcha_chain
        self.sms = sms_provider
        self.artifacts = artifacts

    # ------------------------------------------------------------------ stages

    def stages(self) -> list[Stage]:
        return [
            Stage(AccountState.NEW, self._enter_new, retry=RetryPolicy(max_attempts=1)),
            Stage(AccountState.PROVISIONING, self._enter_provisioning, retry=RetryPolicy(max_attempts=3, base_s=5, max_s=30)),
            Stage(AccountState.PROXY_BOUND, self._enter_proxy_bound, retry=RetryPolicy(max_attempts=3)),
            Stage(AccountState.BROWSER_UP, self._enter_browser_up, retry=RetryPolicy(max_attempts=2)),
            Stage(AccountState.PREWARMED, self._enter_prewarmed, retry=RetryPolicy(max_attempts=2)),
            Stage(AccountState.FORM_FILLED, self._enter_form_filled, retry=RetryPolicy(max_attempts=3, base_s=2)),
            Stage(AccountState.CAPTCHA_SOLVED, self._enter_captcha, retry=RetryPolicy(max_attempts=2)),
            Stage(AccountState.SUBMITTED, self._enter_submitted, retry=RetryPolicy(max_attempts=2, has_side_effect=True)),
            # Reality (2026-11-04): Yelp shows the "complete your profile" form immediately after
            # submit, before the email confirmation, so ONBOARDED runs before EMAIL_PENDING.
            Stage(AccountState.ONBOARDED, self._enter_onboarded, retry=RetryPolicy(max_attempts=2)),
            Stage(AccountState.EMAIL_PENDING, self._enter_email_pending, retry=RetryPolicy(max_attempts=2, base_s=10)),
            Stage(AccountState.EMAIL_VERIFIED, self._enter_email_verified, retry=RetryPolicy(max_attempts=2)),
            Stage(AccountState.PHONE_PENDING, self._enter_phone_pending, retry=RetryPolicy(max_attempts=2, base_s=10)),
            Stage(AccountState.PHONE_VERIFIED, self._enter_phone_verified, retry=RetryPolicy(max_attempts=2)),
            Stage(AccountState.ACTIVE, self._enter_active, retry=RetryPolicy(max_attempts=1)),
        ]
    # ------------------------------------------------------------------ helpers

    def _page(self, ctx: StageContext):
        browser = ctx.data.get("browser")
        if browser is None:
            raise BrowserAttachError("browser not attached")
        return browser.page

    def _select(self, ctx: StageContext):
        return ctx.data.get("persona")

    async def _goto(self, ctx: StageContext, url: str) -> None:
        page = self._page(ctx)
        await page.goto(url, wait_until="domcontentloaded", timeout=45_000)

    async def _enforce_locale(self, ctx: StageContext) -> None:
        """E-41: a wrong locale/geo redirect breaks the whole form."""
        page = self._page(ctx)
        host = _host(page.url)
        if host and host not in ALLOWED_HOSTS:
            log.warning("locale_redirect", url=page.url)
            await page.goto(SIGNUP_URL, wait_until="domcontentloaded", timeout=45_000)
            if _host(page.url) not in ALLOWED_HOSTS:
                raise YFError(f"locale redirect to {page.url}", code="locale_redirect")

    async def _dismiss_overlays(self, ctx: StageContext) -> None:
        """E-40: cookie banner/modal intercepts clicks."""
        page = self._page(ctx)
        try:
            await self.registry.click(page, "cookie.accept", required=False, timeout_ms=2000)
        except Exception:  # noqa: BLE001
            pass
        await idle(page, 0.3, 0.9)

    async def _detect_blocked(self, ctx: StageContext) -> bool:
        page = self._page(ctx)
        try:
            content = (await page.content()).lower()
        except Exception:  # noqa: BLE001
            return False
        return "access denied" in content or "you have been blocked" in content or "request blocked" in content

    async def _inline_errors(self, ctx: StageContext) -> list[str]:
        page = self._page(ctx)
        element = await self.registry.find(page, "signup.inline_error", required=False, timeout_ms=1500)
        if element is None:
            return []
        try:
            texts = await element.all_inner_texts()
        except Exception:  # noqa: BLE001
            return []
        return [t.strip() for t in texts if t.strip()]

    @staticmethod
    def _classify_error(messages: list[str]) -> tuple[str, str] | None:
        blob = " ".join(messages).lower()
        if not blob:
            return None
        if "already registered" in blob or "already have an account" in blob:
            return "E-09", "email_taken"
        if "password" in blob:
            return "E-18", "password_rejected"
        if "name" in blob:
            return "E-19", "name_rejected"
        if "zip" in blob or "postal" in blob:
            return "E-32", "zip_invalid"
        if "email" in blob and ("domain" in blob or "not accepted" in blob or "invalid" in blob):
            return "E-34", "email_domain_blocked"
        return "E-31", "form_drift"

    # ------------------------------------------------------------------ stage bodies

    async def _enter_new(self, ctx: StageContext) -> dict[str, Any]:
        persona: Persona | None = ctx.data.get("persona")
        if persona is None:
            city = self.settings.target.cities[0]
            domain = self.settings.email.domains[0]
            persona = build_persona(city, domain)
            ctx.data["persona"] = persona
        return {"persona": persona}

    async def _enter_provisioning(self, ctx: StageContext) -> dict[str, Any]:
        settings = self.settings
        try:
            self.gpm.health()
        except Exception as exc:  # noqa: BLE001
            raise GPMUnavailable(f"GPM health check failed: {exc}") from exc

        persona: Persona = ctx.data["persona"]
        raw_proxy = ctx.data.get("raw_proxy") or settings.proxy.default_raw
        if not raw_proxy:
            raise ProxyDead("no proxy configured for the account")

        target = ProxyTarget(raw=raw_proxy, country=settings.target.country, city=persona.city)
        result = await probe(target, timeout_s=settings.proxy.probe_timeout_s)
        if not result.ok:
            if result.error and result.error.startswith("geo_country"):
                raise GeoMismatch(result.error, code="geo_mismatch")
            # Mobile exits rotate between cities (D-08); country is the enforceable boundary.
            log.warning("proxy_city_drift", expected=persona.city, observed=result.city, error=result.error)

        ctx.data["proxy"] = target
        ctx.data["proxy_probe"] = result

        from human.timing import CITY_TIMEZONES

        city_tz = CITY_TIMEZONES.get(persona.city, "America/New_York")
        create_kwargs = dict(
            raw_proxy=raw_proxy,
            browser_version=settings.gpm.browser_version,
            os_type=settings.gpm.os_type,
            browser_type=settings.gpm.browser_type,
            canvas_mode=1,
            webgl_image_mode=1,
            webgl_metadata_mode=1,
            audio_mode=1,
            font_mode=1,
            client_rect_mode=1,
            webrtc_mode=1,
            # Timezone must match the proxy geo exactly; GPM's IP lookup drifts on mobile
            # proxies (observed America/Chicago for a Florida exit), so pin it per city.
            timezone_base_on_ip=False,
            timezone=city_tz,
            is_language_base_on_ip=True,
        )
        try:
            profile, reused = ensure_profile(
                self.gpm,
                operation_id=f"reg:{ctx.account_id}",
                name=profile_name(str(ctx.account_id)),
                create_kwargs=create_kwargs,
            )
        except GPMConflict as exc:
            raise GPMConflict(str(exc), code="operation_conflict") from exc
        except GPMSchemaDrift:
            raise
        ctx.data["profile"] = profile
        ctx.data["profile_reused"] = reused
        ctx.data["fingerprint_applied"] = True
        self._persist_profile(ctx, profile, raw_proxy)
        persist_account_state(ctx.account_id, AccountState.PROVISIONING)
        return {"profile_id": profile.id}

    @staticmethod
    def _persist_profile(ctx: StageContext, profile: ProfileDTO, raw_proxy: str) -> None:
        """Keep the profiles table in sync so the reaper can find orphans (E-25)."""
        from db.models import Profile
        from db.session import session_scope

        try:
            with session_scope() as session:
                existing = session.query(Profile).filter_by(gpm_profile_id=profile.id).one_or_none()
                if existing is None:
                    row = Profile(
                        gpm_profile_id=profile.id,
                        name=profile.name,
                        status="active",
                        fingerprint_json={"browser": profile.browser_version, "proxy_set": bool(raw_proxy)},
                    )
                    session.add(row)
                    session.flush()
                    profile_row_id = row.id
                else:
                    existing.status = "active"
                    profile_row_id = existing.id
                from db.models import Account

                account = session.get(Account, ctx.account_id)
                if account is not None and account.profile_id is None:
                    account.profile_id = profile_row_id
        except Exception as exc:  # noqa: BLE001 - bookkeeping must not kill the flow
            log.warning("profile_persist_failed", profile_id=profile.id, error=str(exc)[:200])

    async def _enter_proxy_bound(self, ctx: StageContext) -> dict[str, Any]:
        target: ProxyTarget = ctx.data["proxy"]
        settings = self.settings
        result = await probe(
            target,
            timeout_s=settings.proxy.probe_timeout_s,
            expected_country=settings.target.country,
            expected_city=ctx.data["persona"].city,
        )
        if not result.ok:
            if result.error and result.error.startswith("geo_country"):
                raise GeoMismatch(result.error or "geo mismatch", code="geo_mismatch")
            log.warning("proxy_city_drift", expected=ctx.data["persona"].city, observed=result.city, error=result.error)
        if result.latency_ms and result.latency_ms > settings.proxy.probe_timeout_s * 1000:
            raise ProxyTooSlow(f"probe took {result.latency_ms}ms")
        return {"proxy_ip": result.ip, "asn": result.asn}

    async def _enter_browser_up(self, ctx: StageContext) -> dict[str, Any]:
        profile: ProfileDTO = ctx.data["profile"]
        started = None
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                started = self.gpm.start_profile(profile.id, window_size="1280,800", skip_proxy_check=True)
                break
            except GPMUnavailable as exc:
                last_error = exc
                await asyncio.sleep(3)
        if started is None:
            raise BrowserAttachError(f"profile start failed: {last_error}")

        ctx.data["start_result"] = started
        try:
            browser = await attach(started.cdp_url, timeout_s=self.settings.gpm.connect_timeout_s)
        except BrowserAttachError as exc:
            # E-02: stop and start once more on a fresh port.
            try:
                self.gpm.stop_profile(profile.id)
                restarted = self.gpm.start_profile(profile.id, remote_debugging_port=random.randint(40000, 60000))
                browser = await attach(restarted.cdp_url, timeout_s=self.settings.gpm.connect_timeout_s)
                ctx.data["start_result"] = restarted
            except Exception as inner:  # noqa: BLE001
                raise BrowserAttachError(f"CDP attach failed twice: {exc} / {inner}") from inner

        ctx.data["browser"] = browser
        page = browser.page
        await page.set_viewport_size({"width": 1280, "height": 800})
        return {"process_id": started.process_id, "cdp_url": started.cdp_url}

    async def _enter_prewarmed(self, ctx: StageContext) -> dict[str, Any]:
        page = self._page(ctx)
        await page.goto(HOME_URL, wait_until="domcontentloaded", timeout=45_000)
        if await self._detect_blocked(ctx):
            raise YFError("IP blocked on first page", code="ip_blocked")
        await self._dismiss_overlays(ctx)
        await scroll_page(page, steps=random.randint(2, 4))
        await read_pause(page, seconds=(2.0, 4.5))
        # Deliberately do not click Sign Up yet (bot score), we navigate directly later.
        return {"prewarm_ms": int(random.uniform(3000, 6000))}

    async def _enter_form_filled(self, ctx: StageContext) -> dict[str, Any]:
        page = self._page(ctx)
        persona: Persona = ctx.data["persona"]
        last_code: str | None = None

        for attempt in range(3):
            await page.goto(SIGNUP_URL, wait_until="domcontentloaded", timeout=45_000)
            await self._enforce_locale(ctx)
            await self._dismiss_overlays(ctx)
            if await self._detect_blocked(ctx):
                raise YFError("IP blocked at signup", code="ip_blocked")

            await human_type(await self.registry.find(page, "signup.first_name"), persona.first_name)
            await human_type(await self.registry.find(page, "signup.last_name"), persona.last_name)
            await human_type(await self.registry.find(page, "signup.email"), persona.email_alias)
            await human_type(await self.registry.find(page, "signup.password"), persona.password)
            await human_type(await self.registry.find(page, "signup.postal_code"), persona.zip)
            await idle(page, 0.4, 1.2)

            errors = await self._inline_errors(ctx)
            classified = self._classify_error(errors)
            if classified is None:
                ctx.data["form"] = {"email": persona.email_alias, "zip": persona.zip}
                return {"inline_errors": [], "attempt": attempt + 1}

            code, reason = classified
            last_code = reason
            log.warning("form_validation_rejected", code=code, reason=reason, errors=errors[:3])
            if reason == "email_taken":
                # E-09: new alias, back to FORM_FILLED.
                domain = self.settings.email.domains[0]
                refreshed = build_persona(persona.city, domain, zip_override=persona.zip)
                refreshed.first_name, refreshed.last_name = persona.first_name, persona.last_name
                ctx.data["persona"] = refreshed
                persona = refreshed
                continue
            if reason == "password_rejected":
                persona.password = generate_password()
                continue
            if reason == "zip_invalid":
                persona.zip = pick_zip(persona.city, exclude={persona.zip})
                continue
            if reason in ("name_rejected", "email_domain_blocked"):
                raise YFError(f"{reason}: {errors[:2]}", code=reason, meta={"errors": errors[:5]})
            raise YFError(f"unclassified form error: {errors[:3]}", code="form_drift", meta={"errors": errors[:5]})

        raise YFError(f"form rejected after retries ({last_code})", code=last_code or "form_drift")

    async def _enter_captcha(self, ctx: StageContext) -> dict[str, Any]:
        page = self._page(ctx)
        challenge = await detect_captcha(page)
        if challenge is None:
            return {"captcha": "none"}
        if self.captcha is None:
            raise CaptchaError("captcha present but no solver chain configured")
        try:
            token = await self.captcha.solve(challenge, page=page)
        except CaptchaError as exc:
            raise CaptchaError(f"{challenge.kind}: {exc}") from exc
        ctx.data["captcha_token"] = token
        return {"captcha": challenge.kind, "sitekey": challenge.sitekey}

    async def _enter_submitted(self, ctx: StageContext) -> dict[str, Any]:
        page = self._page(ctx)
        persona: Persona = ctx.data["persona"]

        # Start the mailbox poll *before* submitting (latency, section 6).
        poll_task = asyncio.create_task(
            self.email.wait_for_verification(
                persona.email_alias,
                timeout_s=self.settings.email.poll_timeout_s,
                since=datetime.now(timezone.utc),
            )
        )
        ctx.data["mail_task"] = poll_task

        submit = await self.registry.find(page, "signup.submit")
        await human_click(page, submit)

        deadline = time.monotonic() + float(ctx.data.get("submit_timeout_s", 45))
        while time.monotonic() < deadline:
            await asyncio.sleep(float(ctx.data.get("submit_poll_s", 1.0)))
            url = page.url
            if any(marker in url for marker in ("/signup/verify", "/confirm", "/verify")):
                return {"submit_url": url}
            try:
                content = (await page.content()).lower()
            except Exception:  # noqa: BLE001
                content = ""
            if "suspended" in content:
                persist_account_state(ctx.account_id, AccountState.SUSPENDED, substate="suspend_after_signup")
                raise YFError("account suspended right after signup", code="suspended")
            if "captcha" in content and "iframe" in content:
                # E-48: captcha again on the next page, solve in place, do not reload.
                challenge = await detect_captcha(page)
                if challenge and self.captcha:
                    await self.captcha.solve(challenge, page=page)
                    continue
            errors = await self._inline_errors(ctx)
            if errors:
                self._cancel_mail_task(ctx)
                raise YFError(f"submit rejected: {errors[:2]}", code="submit_error", meta={"errors": errors[:5]})
            if "extra-form" in content or "save & continue" in content or "phone number optional" in content:
                # Post-submit profile page: phone is optional there, not an SMS challenge.
                return {"next": "onboarding"}
            if "phone" in content and ("verify your phone" in content or "we'll text" in content or "text you a code" in content):
                return {"next": "phone"}
        # E-05: no signal in 45s -> one reload, then fail.
        await page.reload(wait_until="domcontentloaded", timeout=30_000)
        self._cancel_mail_task(ctx)
        errors = await self._inline_errors(ctx)
        if errors:
            raise YFError(f"submit timeout with inline errors: {errors[:2]}", code="submit_timeout")
        raise YFError("submit produced no signal within 45s", code="submit_timeout")

    @staticmethod
    def _cancel_mail_task(ctx: StageContext) -> None:
        task = ctx.data.get("mail_task")
        if task is not None and not task.done():
            task.cancel()

    async def _enter_phone_pending(self, ctx: StageContext) -> dict[str, Any]:
        """E-14..E-17: Yelp sometimes insists on SMS verification after submit."""
        from adapters.sms import area_code_for_city

        if self.sms is None:
            raise SMSError("Yelp requires SMS verification but no provider is configured", code="sms_fail")

        page = self._page(ctx)
        persona: Persona = ctx.data["persona"]
        area_code = area_code_for_city(persona.city)
        attempts = 0
        while attempts < 3:
            attempts += 1
            session = await self.sms.acquire(area_code=area_code, max_price=self.settings.sms.max_price)
            ctx.data["sms_session"] = session
            ctx.data["phone_e164"] = session.phone_e164
            phone_input = await self.registry.find(page, "phone.phone_input")
            await human_type(phone_input, session.phone_e164)
            submit = await self.registry.find(page, "phone.submit")
            await human_click(page, submit)
            await idle(page, 1.0, 2.5)

            code_input = await self.registry.find(page, "phone.otp_input", required=False, timeout_ms=8000)
            if code_input is None:
                # No OTP box: either Yelp accepted the number silently, or it rejected it.
                still_form = await self.registry.find(page, "phone.phone_input", required=False, timeout_ms=1500)
                try:
                    content = (await page.content()).lower()
                except Exception:  # noqa: BLE001
                    content = ""
                rejected = any(
                    marker in content
                    for marker in ("invalid phone", "valid phone number", "couldn't verify", "cannot be used", "not supported")
                )
                if still_form is not None or rejected:
                    await self.sms.release(session)
                    raise SMSError(
                        f"Yelp rejected phone {session.phone_e164}",
                        code="sms_fail",
                        meta={"phone": session.phone_e164, "rejected": rejected},
                    )
                return {"phone": session.phone_e164, "otp_required": False}
            try:
                code = await self.sms.wait_for_code(session, timeout_s=self.settings.sms.timeout_s)
            except SMSError:
                await self.sms.release(session)
                continue
            await human_type(code_input, code)
            submit = await self.registry.find(page, "phone.submit")
            await human_click(page, submit)
            await idle(page, 1.5, 3.0)

            error = await self.registry.find(page, "phone.error", required=False, timeout_ms=2500)
            if error is None:
                return {"phone": session.phone_e164, "otp_required": True, "attempts": attempts}
            log.warning("sms_code_rejected", attempt=attempts)
        raise SMSError("SMS verification failed after 3 attempts", code="sms_fail")

    async def _enter_phone_verified(self, ctx: StageContext) -> dict[str, Any]:
        page = self._page(ctx)
        content = (await page.content()).lower()
        if "verify" in content and "phone" in content and "invalid" in content:
            raise SMSError("phone still unverified", code="sms_fail")
        return {"phone_verified": True}

    async def _enter_email_pending(self, ctx: StageContext) -> dict[str, Any]:
        persona: Persona = ctx.data["persona"]
        task = ctx.data.get("mail_task")
        try:
            if task is not None:
                mail = await task
            else:
                mail = await self.email.wait_for_verification(
                    persona.email_alias, timeout_s=self.settings.email.poll_timeout_s
                )
        except NoVerificationMail:
            # Yelp often skips the confirmation mail on this flow; do not stall the account.
            # EMAIL_VERIFIED will prove the session by logging in with the stored credential
            # (E-44) and only that failure is fatal.
            log.warning("verification_mail_missing", email=persona.email_alias)
            self._cancel_mail_task(ctx)
            return {"mail": "not_received"}

        page = self._page(ctx)
        if mail.message.looks_expired():
            raise YFError("verification link already expired", code="verify_expired")

        pages_before = len(ctx.data["browser"].context.pages)
        await page.goto(mail.link, wait_until="domcontentloaded", timeout=45_000)
        # E-43: Yelp sometimes opens the link in a new tab; adopt or close it.
        if len(ctx.data["browser"].context.pages) > pages_before:
            page = await ctx.data["browser"].adopt_page()
            ctx.data["browser"].page = page

        content = (await page.content()).lower()
        if "expired" in content or "invalid" in content:
            raise YFError("verification page says expired/invalid", code="verify_expired")

        ctx.data["verify_link_used"] = mail.link
        return {"mail_subject": mail.message.subject, "link_host": _host(mail.link)}

    async def _enter_email_verified(self, ctx: StageContext) -> dict[str, Any]:
        page = self._page(ctx)
        persona: Persona = ctx.data["persona"]
        cookies = await ctx.data["browser"].context.cookies()
        has_session = any(c.get("name", "").startswith(("yelp-user-id", "ysuid", "bse")) for c in cookies)
        if not has_session:
            # E-44: verified but not logged in -> log in with the stored credential.
            await page.goto("https://www.yelp.com/login?locale=en_US", wait_until="domcontentloaded", timeout=45_000)
            await human_type(await self.registry.find(page, "login.email"), persona.email_alias)
            await human_type(await self.registry.find(page, "login.password"), persona.password)
            await human_click(page, await self.registry.find(page, "login.submit"))
            await page.wait_for_load_state("domcontentloaded", timeout=30_000)
            cookies = await ctx.data["browser"].context.cookies()
            if not any(c.get("name", "").startswith("yelp-user-id") for c in cookies):
                raise YFError("login after verification failed", code="reauth_failed")
        return {"session": True}

    async def _enter_onboarded(self, ctx: StageContext) -> dict[str, Any]:
        page = self._page(ctx)
        persona: Persona = ctx.data["persona"]
        steps = 0

        from flows.identity import build_identity, fetch_avatar
        from flows.profile_settings import fill_birthday, fill_extra_form, fill_location

        identity = ctx.data.get("identity")
        if identity is None:
            probe = ctx.data.get("proxy_probe")
            identity = build_identity(
                account_id=persona.email_alias,
                first_name=persona.first_name,
                last_name=persona.last_name,
                city_state=persona.city,
                zip_code=persona.zip,
                geo_city=getattr(probe, "city", None),
            )
            ctx.data["identity"] = identity
        avatar_path = ctx.data.get("avatar_path")
        if avatar_path is None:
            avatar_path = await fetch_avatar(Path(self.settings.artifacts_dir) / f"avatar_{ctx.account_id}.jpg", gender=identity.gender)
            ctx.data["avatar_path"] = avatar_path

        completed: dict[str, Any] = {}
        extra_save = await self.registry.find(page, "onboarding.extra_form_save", required=False, timeout_ms=4000)
        if extra_save is not None:
            # Avatar + gender go into the extra form, then Save & Continue.
            completed.update(await fill_extra_form(page, self.registry, identity, avatar_path) or {})
            await human_click(page, extra_save, dwell=(350, 900))
            await page.wait_for_load_state("domcontentloaded", timeout=30_000)
            await idle(page, 1.0, 2.5)
            steps += 1

        completed.update(await fill_location(page, self.registry, identity) or {})
        completed.update(await fill_birthday(page, self.registry, identity) or {})

        while steps < 5:
            element = await self.registry.find(page, "onboarding.skip", required=False, timeout_ms=2500)
            if element is None:
                break
            try:
                await human_click(page, element, dwell=(250, 700))
            except Exception:  # noqa: BLE001
                break
            steps += 1
            await idle(page, 0.6, 1.6)

        # Follow 3-5 businesses and save one.
        card = await self.registry.find(page, "onboarding.business_card", required=False, timeout_ms=3000)
        if card is not None:
            await human_click(page, card)
            save = await self.registry.find(page, "onboarding.save_business", required=False, timeout_ms=2500)
            if save is not None:
                await human_click(page, save)

        await scroll_page(page, steps=2)
        return {"onboarding_steps": steps, "city": persona.city, "profile": completed}

    async def _enter_active(self, ctx: StageContext) -> dict[str, Any]:
        browser = ctx.data.get("browser")
        started = ctx.data.get("start_result")
        if browser is not None:
            await browser.close()
        if started is not None:
            try:
                self.gpm.stop_profile(started.profile_id)
            except Exception as exc:  # noqa: BLE001
                log.warning("profile_stop_failed", error=str(exc)[:200])
        return {"activated_at": datetime.now(timezone.utc).isoformat()}


def build_flow(**kwargs) -> SignupFlow:
    return SignupFlow(**kwargs)
