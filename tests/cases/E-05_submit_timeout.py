"""E-05: submit produces no signal within the window -> reload once, then fail."""

from __future__ import annotations

import uuid

import pytest

from adapters.base import YFError
from core.state_machine import StageContext
from db.models import AccountState
from flows.signup import SignupFlow
from selector_registry.resolver import SelectorRegistry, SelectorRule
from tests.fakes import FakeBrowser, FakeGPM

pytestmark = pytest.mark.asyncio


async def test_E05_submit_timeout(settings):
    page = FakeBrowser().context.pages[0]
    page.add("button[type='submit']", visible=True)
    registry = SelectorRegistry({"signup.submit": [SelectorRule("css", "button[type='submit']", 1)]})

    class NullMailbox:
        async def wait_for_verification(self, *a, **kw):
            raise RuntimeError("should not be awaited in this test")

    flow = SignupFlow(settings=settings, gpm=FakeGPM(), registry=registry, email_provider=NullMailbox())
    ctx = StageContext(account_id=uuid.uuid4(), run_id=uuid.uuid4(), state=AccountState.SUBMITTED)
    ctx.data.update({"browser": FakeBrowser(), "persona": type("P", (), {"email_alias": "a@b.com"})(), "submit_timeout_s": 0.05, "submit_poll_s": 0.01})
    ctx.data["browser"].page = page
    with pytest.raises(YFError) as excinfo:
        await flow._enter_submitted(ctx)
    assert excinfo.value.code == "submit_timeout"
    assert page.reloads == 1
