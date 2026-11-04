"""E-06: no verification mail -> account is not stuck; the flow falls back to login proof."""

from __future__ import annotations

import uuid

import pytest

from adapters.base import NoVerificationMail
from adapters.email import FakeMailbox
from core.state_machine import StageContext
from db.models import AccountState
from flows.signup import SignupFlow
from tests.fakes import FakeGPM

pytestmark = pytest.mark.asyncio


async def test_E06_missing_mail_does_not_quarantine(settings, fake_page_factory):
    class EmptyMailbox:
        async def wait_for_verification(self, *a, **kw):
            raise NoVerificationMail("empty")

    browser = __import__("tests.fakes", fromlist=["FakeBrowser"]).FakeBrowser()
    browser.page = fake_page_factory()
    flow = SignupFlow(settings=settings, gpm=FakeGPM(), registry=None, email_provider=EmptyMailbox())
    ctx = StageContext(account_id=uuid.uuid4(), run_id=uuid.uuid4(), state=AccountState.EMAIL_PENDING)
    ctx.data.update({"browser": browser, "persona": type("P", (), {"email_alias": "a@b.com"})()})
    result = await flow._enter_email_pending(ctx)
    assert result == {"mail": "not_received"}
