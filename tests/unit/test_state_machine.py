from __future__ import annotations

import uuid

import pytest

from core.state_machine import (
    SIGNUP_ORDER,
    InvalidTransition,
    Stage,
    StageContext,
    StateMachine,
    can_transition,
)
from db.models import AccountState

pytestmark = pytest.mark.asyncio


class MemoryStore:
    """CheckpointStore stand-in: same contract, no database."""

    def __init__(self):
        self.steps: list[tuple[str, str]] = []
        self._seq = 0

    def next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def start(self, name: str, seq: int | None = None) -> int:
        return seq or self.next_seq()

    def finish(self, seq, name, status="DONE", meta=None, artifact_prefix=None):
        self.steps.append((name, status))

    def completed_names(self) -> list[str]:
        return [name for name, status in self.steps if status in ("DONE", "SKIPPED")]

    def last_state(self):
        done = self.completed_names()
        return done[-1] if done else None


def make_ctx(state=AccountState.NEW) -> StageContext:
    return StageContext(account_id=uuid.uuid4(), run_id=uuid.uuid4(), state=state)


async def test_happy_path_runs_all_stages():
    executed = []
    stages = [
        Stage(state, lambda ctx, s=state: _run(ctx, executed, s)) for state in SIGNUP_ORDER
    ]
    machine = StateMachine(stages, persist=lambda *a, **k: None)
    ctx = make_ctx()
    store = MemoryStore()
    final = await machine.run(ctx, store)
    assert final == AccountState.ACTIVE
    expected = [
        s.value for s in SIGNUP_ORDER if s not in (AccountState.PHONE_PENDING, AccountState.PHONE_VERIFIED)
    ]
    assert executed == expected


async def test_phone_path_runs_phone_stages():
    """E-14: when Yelp asks for SMS, the phone stages run instead of the email ones."""
    executed = []
    stages = [Stage(state, lambda ctx, s=state: _run(ctx, executed, s)) for state in SIGNUP_ORDER]
    machine = StateMachine(stages, persist=lambda *a, **k: None)
    ctx = make_ctx()
    ctx.data["next"] = "phone"
    final = await machine.run(ctx, MemoryStore())
    assert final == AccountState.ACTIVE
    assert "PHONE_PENDING" in executed
    assert "EMAIL_PENDING" not in executed
    assert "ONBOARDED" not in executed


async def test_resume_skips_completed_checkpoints():
    """E-03: after a crash only the unfinished stages run again."""
    executed = []
    stages = [Stage(state, lambda ctx, s=state: _run(ctx, executed, s)) for state in SIGNUP_ORDER]
    store = MemoryStore()
    store.steps = [(state.value, "DONE") for state in SIGNUP_ORDER[:6]]
    machine = StateMachine(stages, persist=lambda *a, **k: None)
    ctx = make_ctx(AccountState.FORM_FILLED)
    final = await machine.run(ctx, store)
    assert final == AccountState.ACTIVE
    expected = [
        s.value
        for s in SIGNUP_ORDER[6:]
        if s not in (AccountState.PHONE_PENDING, AccountState.PHONE_VERIFIED)
    ]
    assert executed == expected


async def test_quarantine_on_captcha_failure():
    async def fail_captcha(ctx):
        from adapters.base import CaptchaError

        raise CaptchaError("two failures")

    stages = [Stage(AccountState.CAPTCHA_SOLVED, fail_captcha)]
    machine = StateMachine(stages, persist=lambda *a, **k: None)
    ctx = make_ctx(AccountState.CAPTCHA_SOLVED)
    final = await machine.run(ctx, MemoryStore())
    assert final == AccountState.QUARANTINED


def test_transitions_block_illegal_jumps():
    assert can_transition(AccountState.NEW, AccountState.PROVISIONING)
    assert not can_transition(AccountState.NEW, AccountState.ACTIVE)
    assert not can_transition(AccountState.QUARANTINED, AccountState.ACTIVE)
    assert can_transition(AccountState.EMAIL_PENDING, AccountState.EMAIL_VERIFIED)


def test_pending_states_are_the_only_replayable_ones():
    replayable = {s for s, targets in __import__("core.state_machine", fromlist=["TRANSITIONS"]).TRANSITIONS.items() if s.value.endswith("_PENDING")}
    assert AccountState.EMAIL_PENDING in replayable
    assert AccountState.PHONE_PENDING in replayable
    assert AccountState.SUBMITTED not in replayable


async def _run(ctx, executed, state):
    executed.append(state.value)
    return {}
