"""E-44: verified but not logged in -> log in with the stored credential; failure is fatal."""

from __future__ import annotations

import uuid

import pytest

from adapters.base import YFError
from core.state_machine import StageContext
from db.models import AccountState
from flows.signup import SignupFlow
from selector_registry.resolver import SelectorRegistry, SelectorRule
from tests.fakes import FakeBrowser, FakeContext, FakeGPM, FakePage

pytestmark = pytest.mark.asyncio


REGISTRY = SelectorRegistry(
    {
        "login.email": [SelectorRule("css", "form#ajax-login input#email", 1)],
        "login.password": [SelectorRule("css", "form#ajax-login input#password", 1)],
        "login.submit": [SelectorRule("css", "form#ajax-login button[type='submit']", 1)],
    }
)


def ctx_for(page, cookies):
    browser = FakeBrowser(context=FakeContext(pages=[page], cookies=cookies))
    ctx = StageContext(account_id=uuid.uuid4(), run_id=uuid.uuid4(), state=AccountState.EMAIL_VERIFIED)
    ctx.data.update({"browser": browser, "persona": type("P", (), {"email_alias": "a@b.com", "password": "pw"})()})
    return ctx


async def test_E44_session_cookie_means_no_login(settings, fake_page_factory):
    page = fake_page_factory(html='<a href="/user_details?userid=42">account</a>')
    ctx = ctx_for(page, [])
    assert await SignupFlow(settings=settings, gpm=FakeGPM(), registry=REGISTRY, email_provider=None)._enter_email_verified(ctx) == {"session": True}
    assert page.gotos == []


async def test_E44_login_failure_raises_reauth_failed(settings, fake_page_factory):
    page = fake_page_factory()
    page.add("form#ajax-login input#email", visible=True)
    page.add("form#ajax-login input#password", visible=True)
    page.add("form#ajax-login button[type='submit']", visible=True)
    ctx = ctx_for(page, [])
    with pytest.raises(YFError) as excinfo:
        await SignupFlow(settings=settings, gpm=FakeGPM(), registry=REGISTRY, email_provider=None)._enter_email_verified(ctx)
    assert excinfo.value.code == "reauth_failed"
    assert page.gotos and "login" in page.gotos[0]
