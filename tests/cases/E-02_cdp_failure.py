"""E-02: CDP attach failure -> stop/start retry, then BrowserAttachError."""

from __future__ import annotations

import pytest

from adapters.base import BrowserAttachError
from core.state_machine import StageContext
from db.models import AccountState
from flows.signup import SignupFlow
from tests.fakes import FakeGPM

pytestmark = pytest.mark.asyncio


async def test_E02_cdp_failure_is_reported(settings, monkeypatch):
    import adapters.browser as browser_module

    async def always_fail(*args, **kwargs):
        raise BrowserAttachError("connectOverCDP timeout")

    monkeypatch.setattr(browser_module, "attach", always_fail)
    monkeypatch.setattr("flows.signup.attach", always_fail)

    flow = SignupFlow(settings=settings, gpm=FakeGPM(fail_start=True), registry=None, email_provider=None)
    ctx = StageContext(account_id=__import__("uuid").uuid4(), run_id=__import__("uuid").uuid4(), state=AccountState.BROWSER_UP)
    ctx.data["profile"] = type("P", (), {"id": "p1"})()
    with pytest.raises(BrowserAttachError):
        await flow._enter_browser_up(ctx)
