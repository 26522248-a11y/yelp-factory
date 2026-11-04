"""Deterministic state machine with checkpoint-based resume (section 6)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from adapters.base import YFError
from core.backoff import RetryPolicy, retry_async
from core.checkpoints import CheckpointStore, persist_account_state
from db.models import AccountState
from obs.log import bind_context, get_logger
from obs.metrics import step_failures_total

log = get_logger("state_machine")

SIGNUP_ORDER: list[AccountState] = [
    AccountState.NEW,
    AccountState.PROVISIONING,
    AccountState.PROXY_BOUND,
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
    AccountState.ACTIVE,
]

TRANSITIONS: dict[AccountState, set[AccountState]] = {
    AccountState.NEW: {AccountState.PROVISIONING, AccountState.QUARANTINED},
    AccountState.PROVISIONING: {AccountState.PROXY_BOUND, AccountState.QUARANTINED, AccountState.DEAD},
    AccountState.PROXY_BOUND: {AccountState.BROWSER_UP, AccountState.QUARANTINED},
    AccountState.BROWSER_UP: {AccountState.PREWARMED, AccountState.DEAD, AccountState.QUARANTINED},
    AccountState.PREWARMED: {AccountState.FORM_FILLED, AccountState.DEAD},
    AccountState.FORM_FILLED: {AccountState.CAPTCHA_SOLVED, AccountState.DEAD, AccountState.QUARANTINED},
    AccountState.CAPTCHA_SOLVED: {AccountState.SUBMITTED, AccountState.QUARANTINED, AccountState.DEAD},
    AccountState.SUBMITTED: {
        AccountState.EMAIL_PENDING,
        AccountState.PHONE_PENDING,
        AccountState.ONBOARDED,
        AccountState.SUSPENDED,
        AccountState.DEAD,
        AccountState.QUARANTINED,
    },
    AccountState.EMAIL_PENDING: {AccountState.EMAIL_VERIFIED, AccountState.QUARANTINED, AccountState.DEAD},
    AccountState.EMAIL_VERIFIED: {AccountState.ONBOARDED, AccountState.PHONE_PENDING, AccountState.DEAD},
    AccountState.PHONE_PENDING: {AccountState.PHONE_VERIFIED, AccountState.QUARANTINED, AccountState.DEAD},
    AccountState.PHONE_VERIFIED: {AccountState.ONBOARDED, AccountState.DEAD},
    AccountState.ONBOARDED: {AccountState.EMAIL_PENDING, AccountState.ACTIVE, AccountState.DEAD},
    AccountState.ACTIVE: {AccountState.WARMING, AccountState.RESTRICTED, AccountState.SUSPENDED},
    AccountState.WARMING: {AccountState.ACTIVE, AccountState.RESTRICTED, AccountState.SUSPENDED, AccountState.DEAD},
    AccountState.RESTRICTED: {AccountState.WARMING, AccountState.SUSPENDED, AccountState.DEAD},
    AccountState.SUSPENDED: {AccountState.DEAD},
    AccountState.QUARANTINED: set(),
    AccountState.DEAD: set(),
}


def can_transition(src: AccountState, dst: AccountState) -> bool:
    return dst in TRANSITIONS.get(src, set())


class InvalidTransition(YFError):
    code = "invalid_transition"


@dataclass(slots=True)
class StageContext:
    account_id: uuid.UUID
    run_id: uuid.UUID
    state: AccountState
    data: dict[str, Any] = field(default_factory=dict)
    attempts: dict[str, int] = field(default_factory=dict)

    def bump(self, key: str) -> int:
        self.attempts[key] = self.attempts.get(key, 0) + 1
        return self.attempts[key]


@dataclass(slots=True)
class Stage:
    """One state of the flow; ``enter`` performs the work, ``verify`` proves it happened."""

    state: AccountState
    enter: Callable[[StageContext], Awaitable[dict[str, Any] | None]]
    verify: Callable[[StageContext], Awaitable[bool]] | None = None
    checkpoint: Callable[[StageContext], Awaitable[None]] | None = None
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    optional: bool = False
    # States that may legally be re-entered after a crash.
    resumable: bool = False


class StateMachine:
    def __init__(self, stages: list[Stage], *, stop_at: AccountState | None = None, persist=None):
        self.stages = stages
        self.stop_at = stop_at
        # Injection point: tests/offline runs pass a no-op instead of touching Postgres.
        self._persist = persist or persist_account_state

    def _stage(self, state: AccountState) -> Stage | None:
        for stage in self.stages:
            if stage.state == state:
                return stage
        return None

    def next_states(self, state: AccountState) -> list[AccountState]:
        order = [s.state for s in self.stages]
        if state in order:
            idx = order.index(state)
            return order[idx + 1 : idx + 2]
        return []

    async def run(self, ctx: StageContext, store: CheckpointStore, *, start_from: AccountState | None = None) -> AccountState:
        completed = set(store.completed_names())
        current = start_from or ctx.state
        order = [stage.state for stage in self.stages]

        if current in order:
            pending = order[order.index(current) :]
        else:
            pending = []

        for state in pending:
            # Conditional branch after SUBMITTED: Yelp may demand SMS instead of email.
            wants_phone = ctx.data.get("next") == "phone"
            if state in (AccountState.EMAIL_PENDING, AccountState.EMAIL_VERIFIED) and wants_phone:
                continue
            if state in (AccountState.PHONE_PENDING, AccountState.PHONE_VERIFIED) and not wants_phone:
                continue
            if state == AccountState.ONBOARDED and wants_phone:
                continue
            stage = self._stage(state)
            if stage is None:
                continue
            if state.value in completed:
                ctx.state = state
                continue
            ctx.state = state
            with bind_context(account_id=str(ctx.account_id), run_id=str(ctx.run_id), step=state.value):
                seq = store.start(state.value)
                try:
                    result = await retry_async(
                        lambda s=stage: s.enter(ctx),
                        stage.retry,
                        on_retry=lambda attempt, exc: log.warning(
                            "stage_retry", stage=state.value, attempt=attempt, error=str(exc)[:200]
                        ),
                    )
                    if result:
                        ctx.data.update(result)
                    if stage.verify and not await stage.verify(ctx):
                        raise YFError(f"verify failed for {state.value}", code="verify_failed")
                    if stage.checkpoint:
                        await stage.checkpoint(ctx)
                    store.finish(seq, state.value, "DONE", meta={"data": _safe(ctx.data)})
                    self._persist(ctx.account_id, state)
                    if self.stop_at is not None and state == self.stop_at:
                        return state
                except YFError as exc:
                    store.finish(seq, state.value, "FAILED", meta={"code": exc.code, "error": str(exc)[:500]})
                    step_failures_total.labels(code=exc.code, step=state.value).inc()
                    log.error("stage_failed", step=state.value, code=exc.code, error=str(exc)[:300])
                    if exc.code in ("captcha", "captcha_timeout", "dom_drift", "api_drift", "gpm_down"):
                        self._persist(ctx.account_id, AccountState.QUARANTINED, substate=exc.code)
                        return AccountState.QUARANTINED
                    if stage.optional:
                        continue
                    raise
        return ctx.state


def _safe(data: dict[str, Any]) -> dict[str, Any]:
    import json

    from obs.redact import redact_obj

    # ctx.data chứa cả dataclass (Persona, ProxyTarget) lẫn bytes; JSONB chỉ nhận JSON.
    return json.loads(json.dumps(redact_obj(data), default=str))
