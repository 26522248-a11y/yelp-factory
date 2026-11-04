"""E-12: proxy city does not match the target ZIP -> GeoMismatch, account is not created."""

from __future__ import annotations

import uuid

import pytest

from adapters.base import GeoMismatch
from adapters.proxy_probe import ProbeResult
from core.state_machine import StageContext
from db.models import AccountState
from flows.signup import SignupFlow
from tests.fakes import FakeGPM

pytestmark = pytest.mark.asyncio


async def test_E12_geo_mismatch_raises(settings, monkeypatch):
    async def fake_probe(target, **kwargs):
        return ProbeResult(ok=False, country="CA", city="Toronto", error="geo_country CA != US")

    monkeypatch.setattr("flows.signup.probe", fake_probe)

    flow = SignupFlow(settings=settings, gpm=FakeGPM(), registry=None, email_provider=None)
    ctx = StageContext(account_id=uuid.uuid4(), run_id=uuid.uuid4(), state=AccountState.PROXY_BOUND)
    from adapters.proxy_probe import ProxyTarget

    ctx.data["proxy"] = ProxyTarget(raw="1.2.3.4:1:u:p", country="US", city="Austin, TX")
    ctx.data["persona"] = type("P", (), {"city": "Austin, TX"})()
    with pytest.raises(GeoMismatch) as excinfo:
        await flow._enter_proxy_bound(ctx)
    assert excinfo.value.code == "geo_mismatch"
