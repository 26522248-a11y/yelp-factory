"""E-47: Yelp suspends the account right after signup -> SUSPENDED, never retried."""

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


async def test_E47_suspension_is_terminal(settings, fake_page_factory, make_account):
    account = make_account()
    page = fake_page_factory(html="<html><body>Your account has been suspended</body></html>")
    page.add("button#signup-button", visible=True)
    browser = FakeBrowser()
    browser.page = page
    registry = SelectorRegistry({"signup.submit": [SelectorRule("css", "button#signup-button", 1)]})

    class Pending:
        async def wait_for_verification(self, *a, **kw):
            import asyncio

            await asyncio.sleep(3600)

    flow = SignupFlow(settings=settings, gpm=FakeGPM(), registry=registry, email_provider=Pending())
    ctx = StageContext(account_id=account.id, run_id=uuid.uuid4(), state=AccountState.SUBMITTED)
    ctx.data.update({"browser": browser, "persona": type("P", (), {"email_alias": "a@b.com"})(), "submit_timeout_s": 3, "submit_poll_s": 0.05})
    with pytest.raises(YFError) as excinfo:
        await flow._enter_submitted(ctx)
    assert excinfo.value.code == "suspended"
