"""E-41: regional redirect (yelp.ca / yelp.co.uk) is forced back to yelp.com with en_US."""

from __future__ import annotations

import uuid

import pytest

from adapters.base import YFError
from core.state_machine import StageContext
from db.models import AccountState
from flows.signup import SIGNUP_URL, SignupFlow
from tests.fakes import FakeBrowser, FakeGPM

pytestmark = pytest.mark.asyncio


def make_flow(settings):
    return SignupFlow(settings=settings, gpm=FakeGPM(), registry=None, email_provider=None)


async def test_E41_locale_redirect_is_corrected(settings, fake_page_factory):
    page = fake_page_factory(url="https://www.yelp.ca/signup")
    browser = FakeBrowser()
    browser.page = page
    ctx = StageContext(account_id=uuid.uuid4(), run_id=uuid.uuid4(), state=AccountState.FORM_FILLED)
    ctx.data["browser"] = browser
    await make_flow(settings)._enforce_locale(ctx)
    assert page.gotos[-1] == SIGNUP_URL
    assert "yelp.com" in page.url


async def test_E41_unfixable_redirect_raises(settings, fake_page_factory):
    page = fake_page_factory(url="https://www.yelp.co.uk/signup")

    async def goto(url, **kwargs):
        page.url = "https://www.yelp.co.uk/signup"
        page.gotos.append(url)

    page.goto = goto
    browser = FakeBrowser()
    browser.page = page
    ctx = StageContext(account_id=uuid.uuid4(), run_id=uuid.uuid4(), state=AccountState.FORM_FILLED)
    ctx.data["browser"] = browser
    with pytest.raises(YFError) as excinfo:
        await make_flow(settings)._enforce_locale(ctx)
    assert excinfo.value.code == "locale_redirect"
