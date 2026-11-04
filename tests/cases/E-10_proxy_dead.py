"""E-10: dead proxy -> ProxyDead, account quarantined as proxy_dead."""

from __future__ import annotations

import pytest

from adapters.base import ProxyDead
from adapters.proxy_probe import ProxyTarget, assert_healthy, probe

pytestmark = pytest.mark.asyncio


async def test_E10_unreachable_proxy_is_dead(monkeypatch):
    async def fake_probe(target, **kwargs):
        from adapters.proxy_probe import ProbeResult

        return ProbeResult(ok=False, error="ConnectError: connection refused")

    monkeypatch.setattr("adapters.proxy_probe.probe", fake_probe)
    with pytest.raises(ProxyDead):
        await assert_healthy(ProxyTarget(raw="10.0.0.1:8000:u:p"))


async def test_E10_bad_proxy_format_is_rejected():
    with pytest.raises(ValueError):
        ProxyTarget(raw="not-a-proxy").url
