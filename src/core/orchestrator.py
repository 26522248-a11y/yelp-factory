"""Orchestrator: one account, one job, one lock (sections 3 and 11)."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from adapters.base import YFError
from core.checkpoints import CheckpointStore, close_run, load_account, open_run
from core.config import Settings
from core.crypto import SecretBox
from core.lock import AccountLockManager
from core.state_machine import StageContext, StateMachine
from db.models import Account, AccountState, Profile, Quarantine, RunState
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


def create_account(city: str, domain: str, *, box: SecretBox | None = None) -> uuid.UUID:
    persona = build_persona(city, domain)
    box = box or SecretBox()
    with session_scope() as session:
        account = Account(
            email=persona.email_alias,
            email_alias=persona.email_alias,
            first_name=persona.first_name,
            last_name=persona.last_name,
            zip=persona.zip,
            city=persona.city,
            password_enc=box.encrypt(persona.password),
            state=AccountState.NEW.value,
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
            store = CheckpointStore(run_id)
            ctx = StageContext(account_id=account_id, run_id=run_id, state=AccountState(account.state), data={"persona": persona, "raw_proxy": raw_proxy})
            flow = SignupFlow(
                settings=settings,
                gpm=deps.gpm,
                registry=deps.registry,
                email_provider=deps.email,
                captcha_chain=deps.captcha,
                sms_provider=deps.sms,
                artifacts=deps.artifacts,
            )
            machine = StateMachine(flow.stages())
            final = await machine.run(ctx, store)
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


async def run_batch(account_ids: list[uuid.UUID], deps: SignupDeps, *, concurrency: int = 1, proxy: str | None = None) -> dict:
    semaphore = asyncio.Semaphore(max(1, concurrency))
    results: dict[str, str] = {}

    async def one(account_id: uuid.UUID) -> None:
        async with semaphore:
            final = await run_signup(account_id, deps, raw_proxy=proxy)
            results[str(account_id)] = final.value

    await asyncio.gather(*(one(aid) for aid in account_ids))
    return results
