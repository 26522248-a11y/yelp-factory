"""E-48: captcha shows up again on the page after submit -> solve in place, no reload."""

from __future__ import annotations

import uuid

import pytest

from adapters.base import CaptchaError, YFError
from core.state_machine import StageContext
from db.models import AccountState
from flows.signup import SignupFlow
from selector_registry.resolver import SelectorRegistry, SelectorRule
from tests.fakes import FakeBrowser, FakeGPM

pytestmark = pytest.mark.asyncio


async def test_E48_captcha_is_solved_again_without_reload(settings, fake_page_factory, monkeypatch):
    page = fake_page_factory(html="<html><body>captcha iframe</body></html>")
    page.add("button#signup-button", visible=True)
    browser = FakeBrowser()
    browser.page = page
    registry = SelectorRegistry({"signup.submit": [SelectorRule("css", "button#signup-button", 1)]})

    calls = {"n": 0}

    class Chain:
        async def solve(self, challenge, page=None):
            calls["n"] += 1
            return "token"

    from adapters.captcha import CaptchaChallenge, RECAPTCHA_V2

    async def fake_detect(p):
        return CaptchaChallenge(kind=RECAPTCHA_V2, sitekey="k", page_url="https://www.yelp.com/signup")

    monkeypatch.setattr("flows.signup.detect_captcha", fake_detect)

    class Pending:
        async def wait_for_verification(self, *a, **kw):
            import asyncio

            await asyncio.sleep(3600)

    flow = SignupFlow(settings=settings, gpm=FakeGPM(), registry=registry, email_provider=Pending(), captcha_chain=Chain())
    ctx = StageContext(account_id=uuid.uuid4(), run_id=uuid.uuid4(), state=AccountState.SUBMITTED)
    ctx.data.update(
        {"browser": browser, "persona": type("P", (), {"email_alias": "a@b.com"})(), "submit_timeout_s": 0.4, "submit_poll_s": 0.05}
    )
    with pytest.raises(YFError):
        await flow._enter_submitted(ctx)
    assert calls["n"] >= 1
    assert page.reloads == 1  # only the single timeout reload, never one per captcha
