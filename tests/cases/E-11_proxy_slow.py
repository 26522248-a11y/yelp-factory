"""E-11: proxy answers but too slowly -> ProxyTooSlow instead of a 45s page timeout."""

from __future__ import annotations

import pytest

from adapters.base import ProxyTooSlow
from adapters.proxy_probe import ProbeResult, ProxyTarget, assert_healthy

pytestmark = pytest.mark.asyncio


async def test_E11_slow_proxy_raises(monkeypatch):
    async def fake_probe(target, **kwargs):
        return ProbeResult(ok=True, ip="1.2.3.4", country="US", latency_ms=42000)

    monkeypatch.setattr("adapters.proxy_probe.probe", fake_probe)
    with pytest.raises(ProxyTooSlow):
        await assert_healthy(ProxyTarget(raw="1.2.3.4:8000:u:p"), slow_p95_s=25)


async def test_E11_fast_proxy_passes(monkeypatch):
    async def fake_probe(target, **kwargs):
        return ProbeResult(ok=True, ip="1.2.3.4", country="US", latency_ms=900)

    monkeypatch.setattr("adapters.proxy_probe.probe", fake_probe)
    result = await assert_healthy(ProxyTarget(raw="1.2.3.4:8000:u:p"))
    assert result.ok
