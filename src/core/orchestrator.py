"""Orchestrator: one account, one job, one lock (sections 3 and 11)."""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from adapters.base import YFError
from core.checkpoints import CheckpointStore, close_run, load_account, open_run, persist_account_state
from core.config import Settings
from core.crypto import SecretBox
from core.lock import AccountLockManager
from core.state_machine import StageContext, StateMachine
from db.models import Account, AccountState, Profile, Quarantine, Run, RunState
from db.session import session_scope
from flows.pools import build_persona
from flows.signup import SignupFlow
from obs.log import bind_context, get_logger
from obs.metrics import signup_total

log = get_logger("orchestrator")


@dataclass
class SignupDeps:
    settings: Settings
    gpm: object
    registry: object
    email: object
    captcha: object
    sms: object = None
    artifacts: object = None


def create_account(
    city: str,
    domain: str,
    *,
    box: SecretBox | None = None,
    source: str = "auto",
    max_per_proxy: int = 2,
    probe_city: bool = False,
    batch_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """Create one account row. ``source`` chooses generated vs imported email/proxy."""
    from core.pool import reserve_email, reserve_proxy

    box = box or SecretBox()
    account_id = uuid.uuid4()
    pool_email = None
    pool_proxy = None
    if source in ("pool_email", "pool_both"):
        pool_email = reserve_email(account_id)
        if pool_email is None:
            raise RuntimeError("pool_exhausted:email")
    if source in ("pool_both", "pool_proxy"):
        pool_proxy = reserve_proxy(account_id, max_per_proxy=max_per_proxy)
        if pool_proxy is None:
            from core.pool import release_email

            if pool_email is not None:
                release_email(pool_email.id)
            raise RuntimeError("pool_exhausted:proxy")

    if pool_proxy is not None and probe_city:
        # The persona city/ZIP must match the exit IP or Yelp rejects the address.
        from adapters.proxysession import rotate_session
        from core.pool import proxy_raw
        from flows.geo import resolve_target_city

        try:
            sticky = rotate_session(proxy_raw(pool_proxy), str(account_id))
            city, _ = asyncio.run(resolve_target_city(sticky, fallback=city, country="US"))
        except Exception as exc:  # noqa: BLE001 - probe is best effort
            log.warning("pool_proxy_geo_failed", account_id=str(account_id), error=str(exc)[:150])

    if pool_email is not None:
        persona = build_persona(city, pool_email.domain or domain)
        persona.email_alias = pool_email.alias
    else:
        persona = build_persona(city, domain)

    with session_scope() as session:
        account = Account(
            id=account_id,
            batch_id=batch_id,
            email=persona.email_alias,
            email_alias=persona.email_alias,
            first_name=persona.first_name,
            last_name=persona.last_name,
            zip=persona.zip,
            city=persona.city,
            password_enc=box.encrypt(persona.password),
            state=AccountState.NEW.value,
            email_pool_id=pool_email.id if pool_email else None,
            proxy_pool_id=pool_proxy.id if pool_proxy else None,
        )
        session.add(account)
        session.flush()
        return account.id


def quarantine(account_id: uuid.UUID, code: str, evidence: dict | None = None) -> None:
    with session_scope() as session:
        session.add(Quarantine(account_id=account_id, code=code, evidence=evidence or {}))
        account = session.get(Account, account_id)
        if account is not None:
            account.state = AccountState.QUARANTINED.value
            account.substate = code
            account.quarantine_reason = code
            account.last_error_code = code[:16]
    log.error("account_quarantined", account_id=str(account_id), code=code)


async def run_signup(account_id: uuid.UUID, deps: SignupDeps, *, raw_proxy: str | None = None) -> AccountState:
    settings = deps.settings
    lock = AccountLockManager(ttl_seconds=900)
    if not lock.acquire(account_id):
        log.warning("account_locked", account_id=str(account_id))
        return AccountState.NEW
    lock.start_heartbeat()
    run_id: uuid.UUID | None = None
    try:
        run_id = open_run(account_id, kind="signup")
        with bind_context(account_id=str(account_id), run_id=str(run_id)):
            account = load_account(account_id)
            if account is None:
                raise KeyError(account_id)
            persona = build_persona(account.city or settings.target.cities[0], settings.email.domains[0], zip_override=account.zip)
            persona.first_name = account.first_name
            persona.last_name = account.last_name
            persona.email_alias = account.email

            # Imported pools take precedence over the generated defaults.
            from core.mailbox_factory import provider_for_account
            from core.pool import commit_email, commit_proxy, proxy_raw, release_email

            email_provider = provider_for_account(account, settings, fallback=deps.email)
            pool_proxy_raw = None
            if account.proxy_pool_id:
                from db.models import ProxyPool

                with session_scope() as session:
                    proxy_row = session.get(ProxyPool, account.proxy_pool_id)
                    if proxy_row is not None:
                        pool_proxy_raw = proxy_raw(proxy_row)
            effective_proxy = pool_proxy_raw or raw_proxy

            store = CheckpointStore(run_id)
            ctx = StageContext(
                account_id=account_id,
                run_id=run_id,
                state=AccountState(account.state),
                data={"persona": persona, "raw_proxy": effective_proxy},
            )
            flow = SignupFlow(
                settings=settings,
                gpm=deps.gpm,
                registry=deps.registry,
                email_provider=email_provider,
                captcha_chain=deps.captcha,
                sms_provider=deps.sms,
                artifacts=deps.artifacts,
            )
            machine = StateMachine(flow.stages())
            final = await machine.run(ctx, store)

            # Pool bookkeeping: a created account consumes the email; the proxy is always
            # consumed once the browser has been opened on it (the IP is already exposed).
            if account.email_pool_id:
                if final in (AccountState.ACTIVE, AccountState.WARMING, AccountState.ONBOARDED):
                    commit_email(account.email_pool_id)
                else:
                    release_email(account.email_pool_id)
            if account.proxy_pool_id:
                commit_proxy(account.proxy_pool_id)

            close_run(run_id, RunState.DONE if final == AccountState.ACTIVE else RunState.FAILED,)
            signup_total.labels(result=final.value.lower()).inc()
            return final
    except YFError as exc:
        code = getattr(exc, "code", "error")
        quarantine(account_id, code, {"error": str(exc)[:500], "meta": exc.meta})
        if run_id:
            close_run(run_id, RunState.FAILED)
        signup_total.labels(result="failed").inc()
        return AccountState.QUARANTINED
    except Exception as exc:  # noqa: BLE001
        quarantine(account_id, "unhandled", {"error": f"{type(exc).__name__}: {exc}"[:500]})
        if run_id:
            close_run(run_id, RunState.FAILED)
        signup_total.labels(result="failed").inc()
        return AccountState.DEAD
    finally:
        lock.stop_heartbeat()
        lock.release(account_id)


async def resume_account(account_id: uuid.UUID, deps: SignupDeps, *, raw_proxy: str | None = None) -> AccountState:
    """Resume a crashed run: reopen the GPM profile, re-attach CDP, continue from checkpoint."""
    from adapters.browser import attach
    from adapters.gpm_ops import profile_name as _profile_name
    from db.models import Profile

    settings = deps.settings
    lock = AccountLockManager(ttl_seconds=900)
    if not lock.acquire(account_id):
        return AccountState.NEW
    lock.start_heartbeat()
    run_id: uuid.UUID | None = None
    browser = None
    try:
        account = load_account(account_id)
        if account is None:
            raise KeyError(account_id)
        # We hold the account lock, so any leftover RUNNING row belongs to a dead worker.
        with session_scope() as session:
            session.query(Run).filter(Run.account_id == account_id, Run.state == RunState.RUNNING.value).update(
                {"state": RunState.FAILED.value}
            )
        run_id = open_run(account_id, kind="resume")
        with bind_context(account_id=str(account_id), run_id=str(run_id)):
            persona = build_persona(account.city or settings.target.cities[0], settings.email.domains[0], zip_override=account.zip)
            persona.first_name = account.first_name
            persona.last_name = account.last_name
            persona.email_alias = account.email

            # Imported pools stay authoritative on resume too.
            from core.mailbox_factory import provider_for_account
            from core.pool import proxy_raw

            email_provider = provider_for_account(account, settings, fallback=deps.email)
            if account.proxy_pool_id:
                from db.models import ProxyPool

                with session_scope() as session:
                    proxy_row = session.get(ProxyPool, account.proxy_pool_id)
                    if proxy_row is not None:
                        raw_proxy = proxy_raw(proxy_row) or raw_proxy

            ctx = StageContext(account_id=account_id, run_id=run_id, state=AccountState(account.state), data={"persona": persona, "raw_proxy": raw_proxy})
            state = AccountState(account.state)

            # Any state past BROWSER_UP needs a live browser again.
            if state in {
                AccountState.BROWSER_UP,
                AccountState.PREWARMED,
                AccountState.FORM_FILLED,
                AccountState.CAPTCHA_SOLVED,
                AccountState.SUBMITTED,
                AccountState.ONBOARDED,
                AccountState.EMAIL_PENDING,
                AccountState.EMAIL_VERIFIED,
                AccountState.PHONE_PENDING,
                AccountState.PHONE_VERIFIED,
            }:
                with session_scope() as session:
                    profile_row = (
                        session.query(Profile).filter(Profile.id == account.profile_id).one_or_none()
                        if account.profile_id
                        else None
                    )
                    gpm_profile_id = profile_row.gpm_profile_id if profile_row else None
                if gpm_profile_id:
                    started = deps.gpm.start_profile(gpm_profile_id, window_size="1280,800", skip_proxy_check=True)
                    browser = await attach(started.cdp_url, timeout_s=settings.gpm.connect_timeout_s)
                    ctx.data["browser"] = browser
                    ctx.data["start_result"] = started
                    ctx.data["profile"] = type("P", (), {"id": gpm_profile_id})()
            else:
                gpm_profile_id = None

            if ctx.data.get("next") is None:
                # Re-derive the branch from the current page when possible.
                page = ctx.data.get("browser").page if ctx.data.get("browser") else None
                if page is not None:
                    try:
                        content = (await page.content()).lower()
                        if "extra-form" in content or "save & continue" in content:
                            ctx.data["next"] = "onboarding"
                    except Exception:  # noqa: BLE001
                        pass

            store = CheckpointStore(run_id)
            flow = SignupFlow(
                settings=settings,
                gpm=deps.gpm,
                registry=deps.registry,
                email_provider=email_provider,
                captcha_chain=deps.captcha,
                sms_provider=deps.sms,
                artifacts=deps.artifacts,
            )
            machine = StateMachine(flow.stages())
            final = await machine.run(ctx, store, start_from=state)

            # Pool bookkeeping mirrors run_signup(): resume must consume/release the same rows.
            if account.email_pool_id:
                from core.pool import commit_email, release_email

                if final in (AccountState.ACTIVE, AccountState.WARMING, AccountState.ONBOARDED):
                    commit_email(account.email_pool_id)
                else:
                    release_email(account.email_pool_id)
            if account.proxy_pool_id:
                from core.pool import commit_proxy

                commit_proxy(account.proxy_pool_id)

            close_run(run_id, RunState.DONE if final == AccountState.ACTIVE else RunState.FAILED)
            return final
    except YFError as exc:
        quarantine(account_id, getattr(exc, "code", "error"), {"error": str(exc)[:500], "meta": exc.meta})
        if run_id:
            close_run(run_id, RunState.FAILED)
        return AccountState.QUARANTINED
    except Exception as exc:  # noqa: BLE001
        quarantine(account_id, "unhandled", {"error": f"{type(exc).__name__}: {exc}"[:500]})
        if run_id:
            close_run(run_id, RunState.FAILED)
        return AccountState.DEAD
    finally:
        if browser is not None:
            try:
                await browser.close()
            except Exception:  # noqa: BLE001
                pass
        lock.stop_heartbeat()
        lock.release(account_id)


async def probe_account(account_id: uuid.UUID, deps: SignupDeps) -> dict:
    """Check whether the Yelp account exists by re-submitting its email on /signup.

    Login itself sits behind DataDome on this proxy, but the signup page answers
    "already registered" for existing emails, which is a reliable existence probe.
    """
    from adapters.browser import attach
    from core.crypto import SecretBox
    from db.models import Profile
    from human.mouse import human_click
    from human.typing import human_type
    from selector_registry.resolver import SelectorRegistry

    settings = deps.settings
    account = load_account(account_id)
    if account is None:
        return {"exists": False, "reason": "account_missing"}
    with session_scope() as session:
        profile_row = session.query(Profile).filter(Profile.id == account.profile_id).one_or_none() if account.profile_id else None
        gpm_profile_id = profile_row.gpm_profile_id if profile_row else None
    # A missing profile only means the run died early; the account may still exist on Yelp.

    password = SecretBox().decrypt(account.password_enc) if account.password_enc else ""
    registry = deps.registry or SelectorRegistry.from_yaml()
    from adapters.proxysession import rotate_session

    probe_raw = rotate_session(
        settings.proxy.default_raw,
        f"probe-{account_id}-{int(time.time())}",
        sticky_minutes=settings.proxy.sticky_minutes,
    )
    temp = deps.gpm.create_profile(
        name=f"yf-probe-{str(account_id)[:8]}",
        raw_proxy=probe_raw,
        browser_version=settings.gpm.browser_version,
    )
    started = deps.gpm.start_profile(temp.id, window_size="1280,800", skip_proxy_check=True)
    browser = None
    try:
        browser = await attach(started.cdp_url, timeout_s=settings.gpm.connect_timeout_s)
        page = browser.page
        await page.goto("https://www.yelp.com/signup?locale=en_US", wait_until="domcontentloaded", timeout=90_000)
        await page.wait_for_timeout(3000)
        for key, value in (
            ("signup.first_name", account.first_name),
            ("signup.last_name", account.last_name),
            ("signup.email", account.email),
            ("signup.password", password or "TempPass123!x"),
            ("signup.postal_code", account.zip),
        ):
            field = await registry.find(page, key, required=False, timeout_ms=6000)
            if field is not None:
                await human_type(field, value)
        submit = await registry.find(page, "signup.submit", required=False, timeout_ms=5000)
        if submit is None:
            return {"exists": None, "reason": "signup_form_missing", "email": account.email}
        await human_click(page, submit)
        await page.wait_for_timeout(9000)

        content = (await page.content()).lower()
        url = page.url
        # The signup page always contains "Already on Yelp? Log in", so a bare "already"
        # check is a false positive. Use the page state instead.
        if "welcome to yelp" in content or ("extra-form" in content and "signup-form" not in content):
            result = {"exists": True, "reason": "created_now", "email": account.email}
        elif "signup-form" in content and ("already registered" in content or "already have an account" in content):
            result = {"exists": True, "reason": "already_registered", "email": account.email}
        elif "signup-form" in content and "wrong" in content:
            result = {"exists": True, "reason": "wrong_password", "email": account.email}
        else:
            errors = await registry.find(page, "signup.inline_error", required=False, timeout_ms=2000)
            texts = []
            if errors is not None:
                try:
                    texts = await errors.all_inner_texts()
                except Exception:  # noqa: BLE001
                    texts = []
            result = {"exists": None, "reason": "inconclusive", "email": account.email, "url": url, "errors": texts[:3]}
        with session_scope() as session:
            row = session.get(Account, account_id)
            if row is not None:
                row.substate = f"probe_{result['reason']}"
        return result
    finally:
        if browser is not None:
            try:
                await browser.close()
            except Exception:  # noqa: BLE001
                pass
        try:
            deps.gpm.stop_profile(temp.id)
        except Exception:  # noqa: BLE001
            pass
        try:
            deps.gpm.delete_profile(temp.id, hard=True)
        except Exception:  # noqa: BLE001
            pass


async def verify_login(account_id: uuid.UUID, deps: SignupDeps) -> dict:
    """Prove the account exists by logging in with the stored credential."""
    from adapters.browser import attach
    from core.crypto import SecretBox
    from db.models import Profile
    from human.mouse import human_click
    from human.typing import human_type

    settings = deps.settings
    account = load_account(account_id)
    if account is None:
        return {"ok": False, "reason": "account_missing"}
    with session_scope() as session:
        profile_row = session.query(Profile).filter(Profile.id == account.profile_id).one_or_none() if account.profile_id else None
        gpm_profile_id = profile_row.gpm_profile_id if profile_row else None
    if not gpm_profile_id:
        return {"ok": False, "reason": "no_gpm_profile", "email": account.email}

    password = SecretBox().decrypt(account.password_enc) if account.password_enc else ""
    from adapters.proxysession import rotate_session

    login_raw = rotate_session(
        settings.proxy.default_raw, f"login-{account_id}-{int(time.time())}", sticky_minutes=settings.proxy.sticky_minutes
    )
    temp = deps.gpm.create_profile(
        name=f"yf-login-{str(account_id)[:8]}",
        raw_proxy=login_raw,
        browser_version=settings.gpm.browser_version,
    )
    started = deps.gpm.start_profile(temp.id, window_size="1280,800", skip_proxy_check=True)
    browser = None
    try:
        browser = await attach(started.cdp_url, timeout_s=settings.gpm.connect_timeout_s)
        page = browser.page
        await page.goto("https://www.yelp.com/login?locale=en_US", wait_until="domcontentloaded", timeout=60_000)
        await page.wait_for_timeout(3000)
        html = ""
        try:
            html = (await page.content()).lower()
        except Exception:  # noqa: BLE001
            pass
        if "captcha-delivery" in html or "datadome" in html:
            return {"ok": None, "reason": "datadome_blocked", "email": account.email}

        # A live session redirects away from /login straight to the homepage.
        from adapters.browser import is_logged_in

        if await is_logged_in(page):
            with session_scope() as session:
                row = session.get(Account, account_id)
                if row is not None:
                    row.substate = "login_ok"
            return {"ok": True, "email": account.email, "url": page.url, "reason": "already_logged_in"}

        email_field = await deps.registry.find(page, "login.email", required=False, timeout_ms=6000)
        password_field = await deps.registry.find(page, "login.password", required=False, timeout_ms=4000)
        if email_field is None or password_field is None:
            return {"ok": False, "reason": "login_form_missing", "email": account.email, "url": page.url}
        await human_type(email_field, account.email)
        await human_type(password_field, password)
        submit = await deps.registry.find(page, "login.submit", required=False, timeout_ms=4000)
        if submit is None:
            return {"ok": False, "reason": "login_submit_missing", "email": account.email}
        await human_click(page, submit)
        await page.wait_for_timeout(7000)

        has_session = await is_logged_in(page)
        try:
            content = (await page.content()).lower()
        except Exception:  # noqa: BLE001
            content = ""
        wrong = "wrong email or password" in content or "incorrect" in content
        if has_session and not wrong:
            with session_scope() as session:
                row = session.get(Account, account_id)
                if row is not None:
                    row.substate = "login_ok"
            return {"ok": True, "email": account.email, "url": page.url, "state": account.state}
        with session_scope() as session:
            row = session.get(Account, account_id)
            if row is not None:
                row.substate = "login_failed"
        return {
            "ok": False,
            "reason": "wrong_credentials" if wrong else "no_session",
            "email": account.email,
            "url": page.url,
        }
    finally:
        if browser is not None:
            try:
                await browser.close()
            except Exception:  # noqa: BLE001
                pass
        try:
            deps.gpm.stop_profile(temp.id)
        except Exception:  # noqa: BLE001
            pass
        try:
            deps.gpm.delete_profile(temp.id, hard=True)
        except Exception:  # noqa: BLE001
            pass


async def upload_avatar(account_id: uuid.UUID, deps: SignupDeps, *, avatar_path: str | None = None) -> dict:
    """Upload the stored avatar through /user_photos/add (works only with a live session)."""
    from pathlib import Path

    from adapters.browser import attach
    from db.models import Profile

    settings = deps.settings
    account = load_account(account_id)
    if account is None:
        return {"ok": False, "reason": "account_missing"}
    path = Path(avatar_path or account.avatar_path or "")
    if not path.exists():
        return {"ok": False, "reason": "avatar_missing"}
    with session_scope() as session:
        profile_row = session.query(Profile).filter(Profile.id == account.profile_id).one_or_none() if account.profile_id else None
        gpm_profile_id = profile_row.gpm_profile_id if profile_row else None
    if not gpm_profile_id:
        return {"ok": False, "reason": "no_gpm_profile"}

    started = deps.gpm.start_profile(gpm_profile_id, window_size="1280,800", skip_proxy_check=True)
    browser = None
    try:
        browser = await attach(started.cdp_url, timeout_s=settings.gpm.connect_timeout_s)
        page = browser.page
        await page.goto("https://www.yelp.com/user_photos/add", wait_until="domcontentloaded", timeout=90_000)
        await page.wait_for_timeout(4000)
        files = page.locator("input[type='file']")
        if not await files.count():
            return {"ok": False, "reason": "upload_not_available", "url": page.url}
        await files.first.set_input_files(str(path.resolve()))
        await page.wait_for_timeout(8000)
        with session_scope() as session:
            row = session.get(Account, account_id)
            if row is not None:
                row.substate = "avatar_uploaded"
                row.avatar_path = str(path)
        return {"ok": True, "url": page.url, "avatar": str(path)}
    finally:
        if browser is not None:
            try:
                await browser.close()
            except Exception:  # noqa: BLE001
                pass
        try:
            deps.gpm.stop_profile(gpm_profile_id)
        except Exception:  # noqa: BLE001
            pass


async def run_profile_completion(account_id: uuid.UUID, deps: SignupDeps) -> dict:
    """Fill every optional profile field (about me, location, birthday) on an existing account."""
    from adapters.browser import attach
    from db.models import Profile
    from flows.identity import build_identity
    from flows.profile_settings import fill_birthday, fill_profile_details

    settings = deps.settings
    account = load_account(account_id)
    if account is None:
        raise KeyError(account_id)
    with session_scope() as session:
        profile_row = session.query(Profile).filter(Profile.id == account.profile_id).one_or_none() if account.profile_id else None
        gpm_profile_id = profile_row.gpm_profile_id if profile_row else None
    if not gpm_profile_id:
        raise RuntimeError("account has no GPM profile; run signup first")

    identity = build_identity(
        account_id=account.email or str(account_id),
        first_name=account.first_name or "User",
        last_name=account.last_name or "Yelp",
        city_state=account.city or "Austin, TX",
        zip_code=account.zip or "78701",
    )
    started = deps.gpm.start_profile(gpm_profile_id, window_size="1280,800", skip_proxy_check=True)
    browser = await attach(started.cdp_url, timeout_s=settings.gpm.connect_timeout_s)
    result: dict = {}
    try:
        page = await browser.adopt_page()
        for step_name, step_coro in (
            ("details", fill_profile_details(page, deps.registry, identity)),
            ("birthday", fill_birthday(page, deps.registry, identity)),
        ):
            try:
                result.update(await step_coro or {})
            except Exception as exc:  # noqa: BLE001
                log.warning("profile_step_skipped", step=step_name, error=str(exc)[:180])
        if result:
            with session_scope() as session:
                row = session.get(Account, account_id)
                if row is not None:
                    row.substate = "profile_completed"
                    row.gender = identity.gender
                    row.birth_date = identity.birth_date.isoformat()
                    row.address_line = identity.address_line()
    finally:
        try:
            await browser.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            deps.gpm.stop_profile(gpm_profile_id)
        except Exception:  # noqa: BLE001
            pass
    return {"account": str(account_id), "filled": result}


async def run_warm(account_id: uuid.UUID, deps: SignupDeps, *, sessions: int = 1, max_seconds: int = 720) -> dict:
    """Warm an ACTIVE account: reopen the profile, run N human-like sessions."""
    from adapters.browser import attach
    from core.budget import DailyBudget, phase_for_day
    from db.models import Profile
    from flows.warmup import WarmingRunner

    settings = deps.settings
    account = load_account(account_id)
    if account is None:
        raise KeyError(account_id)
    with session_scope() as session:
        profile_row = session.query(Profile).filter(Profile.id == account.profile_id).one_or_none() if account.profile_id else None
        gpm_profile_id = profile_row.gpm_profile_id if profile_row else None
    if not gpm_profile_id:
        raise RuntimeError("account has no GPM profile; run signup first")

    started = deps.gpm.start_profile(gpm_profile_id, window_size="1280,800", skip_proxy_check=True)
    browser = await attach(started.cdp_url, timeout_s=settings.gpm.connect_timeout_s)
    runner = WarmingRunner(gpm=deps.gpm, registry=deps.registry, settings=settings)
    from core.scheduler import daily_plan_day

    day = daily_plan_day(account_id)
    phase = phase_for_day(day)
    plan = DailyBudget.for_phase(phase)
    results = []
    try:
        for index in range(sessions):
            empty = __import__("human.timing", fromlist=["empty_session"]).empty_session()
            outcome = await runner.run_session(
                _WarmCtx(account_id, browser, phase=phase, proxy_ip=getattr(account, "proxy_ip", None)),
                budget=plan,
                empty=empty,
                max_seconds=max_seconds,
            )
            results.append(outcome)
            persist_account_state(account_id, AccountState.WARMING)
    finally:
        try:
            await browser.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            deps.gpm.stop_profile(gpm_profile_id)
        except Exception:  # noqa: BLE001
            pass
    return {"account": str(account_id), "sessions": results, "budget": plan.to_json()}


class _WarmCtx:
    def __init__(self, account_id: uuid.UUID, browser, *, phase: str = "P1", proxy_ip: str | None = None, plan_id=None):
        self.account_id = account_id
        self.data = {
            "browser": browser,
            "phase": phase,
            "proxy_ip": proxy_ip,
            "plan_id": plan_id,
            "review_enabled": True,
            "entry_path": __import__("random").choices(
                ["search", "direct", "category", "referral"], weights=[6, 2, 1, 1], k=1
            )[0],
        }


async def run_batch(account_ids: list[uuid.UUID], deps: SignupDeps, *, concurrency: int = 1, proxy: str | None = None) -> dict:
    semaphore = asyncio.Semaphore(max(1, concurrency))
    results: dict[str, str] = {}

    async def one(account_id: uuid.UUID) -> None:
        async with semaphore:
            final = await run_signup(account_id, deps, raw_proxy=proxy)
            results[str(account_id)] = final.value

    await asyncio.gather(*(one(aid) for aid in account_ids))
    return results
