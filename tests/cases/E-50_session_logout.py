"""E-50: session lost during warming -> reauth with stored credential, else SUSPENDED."""

from __future__ import annotations

import uuid

import pytest

from adapters.base import YFError
from core.state_machine import StageContext
from db.models import AccountState
from flows.reauth import ReauthFlow
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


def ctx_with(page, cookies):
    browser = FakeBrowser(context=FakeContext(pages=[page], cookies=cookies))
    ctx = StageContext(account_id=uuid.uuid4(), run_id=uuid.uuid4(), state=AccountState.WARMING)
    ctx.data.update({"browser": browser, "persona": type("P", (), {"email_alias": "a@b.com", "password": "pw"})()})
    return ctx


async def test_E50_reauth_succeeds_with_new_cookie(settings, fake_page_factory):
    page = fake_page_factory(html='<a href="/user_details?userid=42">account</a>')
    page.add("form#ajax-login input#email", visible=True)
    page.add("form#ajax-login input#password", visible=True)
    page.add("form#ajax-login button[type='submit']", visible=True)
    ctx = ctx_with(page, [])

    flow = ReauthFlow(gpm=FakeGPM(), registry=REGISTRY, settings=settings)
    assert await flow._enter_warm(ctx) == {"reauth": True}


async def test_E50_reauth_failure_is_terminal(settings, fake_page_factory):
    page = fake_page_factory()
    page.add("form#ajax-login input#email", visible=True)
    page.add("form#ajax-login input#password", visible=True)
    page.add("form#ajax-login button[type='submit']", visible=True)
    ctx = ctx_with(page, [])
    flow = ReauthFlow(gpm=FakeGPM(), registry=REGISTRY, settings=settings)
    with pytest.raises(YFError) as excinfo:
        await flow._enter_warm(ctx)
    assert excinfo.value.code == "reauth_failed"
