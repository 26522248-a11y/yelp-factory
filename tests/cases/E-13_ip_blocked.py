"""E-13: Yelp blocks the IP on the first page -> ip_blocked, proxy must be rotated."""

from __future__ import annotations

import uuid

import pytest

from adapters.base import YFError
from core.state_machine import StageContext
from db.models import AccountState
from flows.signup import SignupFlow
from tests.fakes import FakeBrowser, FakeGPM

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize(
    "html",
    [
        "<html><body>Access Denied</body></html>",
        "<html><body>You have been blocked</body></html>",
        "<html><body>Request blocked</body></html>",
    ],
)
async def test_E13_blocked_page_is_detected(settings, fake_page_factory, html):
    browser = FakeBrowser()
    browser.page = fake_page_factory(html=html)
    flow = SignupFlow(settings=settings, gpm=FakeGPM(), registry=None, email_provider=None)
    ctx = StageContext(account_id=uuid.uuid4(), run_id=uuid.uuid4(), state=AccountState.PREWARMED)
    ctx.data["browser"] = browser
    assert await flow._detect_blocked(ctx) is True


async def test_E13_clean_page_is_not_blocked(settings, fake_page_factory):
    browser = FakeBrowser()
    browser.page = fake_page_factory(html="<html><body>Restaurants near you</body></html>")
    flow = SignupFlow(settings=settings, gpm=FakeGPM(), registry=None, email_provider=None)
    ctx = StageContext(account_id=uuid.uuid4(), run_id=uuid.uuid4(), state=AccountState.PREWARMED)
    ctx.data["browser"] = browser
    assert await flow._detect_blocked(ctx) is False
