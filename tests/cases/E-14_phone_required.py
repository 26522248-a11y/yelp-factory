"""E-14: Yelp requires phone verification -> SMS branch runs, email branch is skipped."""

from __future__ import annotations

import uuid

import pytest

from adapters.base import SMSError
from core.state_machine import Stage, StageContext, StateMachine
from db.models import AccountState
from flows.signup import SignupFlow
from tests.fakes import FakeBrowser, FakeGPM

pytestmark = pytest.mark.asyncio


class MemoryStore:
    def completed_names(self):
        return []

    def start(self, name, seq=None):
        return 1

    def finish(self, *a, **k):
        return None


async def test_E14_machine_skips_email_when_phone_required():
    executed: list[str] = []

    async def email_stage(ctx):
        executed.append("email")

    async def phone_stage(ctx):
        executed.append("phone")

    stages = [Stage(AccountState.EMAIL_PENDING, email_stage), Stage(AccountState.PHONE_PENDING, phone_stage)]
    ctx = StageContext(account_id=uuid.uuid4(), run_id=uuid.uuid4(), state=AccountState.EMAIL_PENDING)
    ctx.data["next"] = "phone"
    machine = StateMachine(stages, persist=lambda *a, **k: None)
    await machine.run(ctx, MemoryStore())
    assert executed == ["phone"]


async def test_E14_phone_stage_requires_provider(settings, fake_page_factory):
    browser = FakeBrowser()
    browser.page = fake_page_factory()
    flow = SignupFlow(settings=settings, gpm=FakeGPM(), registry=None, email_provider=None, sms_provider=None)
    ctx = StageContext(account_id=uuid.uuid4(), run_id=uuid.uuid4(), state=AccountState.PHONE_PENDING)
    ctx.data.update({"browser": browser, "persona": type("P", (), {"city": "Delray Beach, FL"})()})
    with pytest.raises(SMSError) as excinfo:
        await flow._enter_phone_pending(ctx)
    assert excinfo.value.code == "sms_fail"
