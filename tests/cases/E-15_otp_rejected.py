"""E-15: wrong OTP twice, new code third time; three bad codes -> sms_fail quarantine."""

from __future__ import annotations

import uuid

import pytest

from adapters.base import SMSError
from adapters.sms import FakeSmsProvider
from core.state_machine import StageContext
from db.models import AccountState
from flows.signup import SignupFlow
from selector_registry.resolver import SelectorRegistry, SelectorRule
from tests.fakes import FakeBrowser, FakeGPM

pytestmark = pytest.mark.asyncio


def registry() -> SelectorRegistry:
    return SelectorRegistry(
        {
            "phone.phone_input": [SelectorRule("css", "input[name='phone_number']", 1)],
            "phone.otp_input": [SelectorRule("css", "input[name='code']", 1)],
            "phone.submit": [SelectorRule("css", "button[type='submit']", 1)],
            "phone.error": [SelectorRule("text", "invalid", 1)],
        }
    )


def make_ctx(page):
    browser = FakeBrowser()
    browser.page = page
    ctx = StageContext(account_id=uuid.uuid4(), run_id=uuid.uuid4(), state=AccountState.PHONE_PENDING)
    ctx.data.update({"browser": browser, "persona": type("P", (), {"city": "Delray Beach, FL"})()})
    return ctx


async def test_E15_rejected_code_is_retried_then_fails(settings, fake_page_factory):
    page = fake_page_factory()
    page.add("input[name='phone_number']", visible=True)
    page.add("input[name='code']", visible=True)
    page.add("button[type='submit']", visible=True)
    page.add("text=invalid", visible=True)  # Yelp keeps saying the code is invalid

    sms = FakeSmsProvider(codes=["111111"])
    flow = SignupFlow(settings=settings, gpm=FakeGPM(), registry=registry(), email_provider=None, sms_provider=sms)
    with pytest.raises(SMSError) as excinfo:
        await flow._enter_phone_pending(make_ctx(page))
    assert excinfo.value.code == "sms_fail"


async def test_E15_valid_code_passes(settings, fake_page_factory):
    page = fake_page_factory()
    page.add("input[name='phone_number']", visible=True)
    page.add("input[name='code']", visible=True)
    page.add("button[type='submit']", visible=True)
    page.add("text=invalid", visible=False)

    sms = FakeSmsProvider(codes=["222222"])
    flow = SignupFlow(settings=settings, gpm=FakeGPM(), registry=registry(), email_provider=None, sms_provider=sms)
    result = await flow._enter_phone_pending(make_ctx(page))
    assert result["otp_required"] is True
