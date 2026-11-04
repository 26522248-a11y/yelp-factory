"""E-01: GPM app down / port moved -> fast GPMUnavailable, no hang."""

from __future__ import annotations

import pytest

from adapters.base import GPMUnavailable
from core.state_machine import StageContext
from db.models import AccountState
from flows.signup import SignupFlow
from tests.fakes import FakeGPM

pytestmark = pytest.mark.asyncio


async def test_E01_gpm_down_quarantines_without_browser(settings):
    flow = SignupFlow(settings=settings, gpm=FakeGPM(fail_health=True), registry=None, email_provider=None)
    ctx = StageContext(account_id=__import__("uuid").uuid4(), run_id=__import__("uuid").uuid4(), state=AccountState.PROVISIONING)
    from flows.pools import build_persona

    ctx.data["persona"] = build_persona("Austin, TX", "fviainboxes.com")
    with pytest.raises(GPMUnavailable) as excinfo:
        await flow._enter_provisioning(ctx)
    assert excinfo.value.code == "gpm_down"
