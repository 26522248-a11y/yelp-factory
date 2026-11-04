"""City resolution from proxy IP (UI no longer asks for a city)."""

from __future__ import annotations

import pytest

from flows.geo import city_for_state, match_known_city, resolve_target_city

pytestmark = pytest.mark.asyncio


def test_exact_city_match():
    assert match_known_city("Delray Beach") == "Delray Beach, FL"


def test_match_is_case_insensitive():
    assert match_known_city("delray beach") == "Delray Beach, FL"


def test_unknown_city_falls_back_to_state():
    assert match_known_city("Nowhere", "FL") == city_for_state("FL")


def test_unknown_city_and_state_returns_none():
    assert match_known_city("Nowhere", "ZZ") is None


def test_city_for_state_known_and_unknown():
    assert city_for_state("TX") is not None
    assert city_for_state("ZZ") is None


async def test_resolve_uses_probe_city(monkeypatch):
    from adapters.proxy_probe import ProbeResult

    async def fake_probe(target, **kwargs):
        return ProbeResult(ok=True, ip="1.2.3.4", country="US", city="Delray Beach")

    monkeypatch.setattr("flows.geo.probe", fake_probe)
    city, result = await resolve_target_city("1.2.3.4:8000:u:p", fallback="Austin, TX")
    assert city == "Delray Beach, FL"
    assert result.ok


async def test_resolve_falls_back_when_probe_fails(monkeypatch):
    from adapters.proxy_probe import ProbeResult

    async def fake_probe(target, **kwargs):
        return ProbeResult(ok=False, error="connect refused")

    monkeypatch.setattr("flows.geo.probe", fake_probe)
    city, result = await resolve_target_city("1.2.3.4:8000:u:p", fallback="Austin, TX")
    assert city == "Austin, TX"
    assert result.ok is False


async def test_resolve_unknown_city_uses_fallback_state(monkeypatch):
    from adapters.proxy_probe import ProbeResult

    async def fake_probe(target, **kwargs):
        return ProbeResult(ok=True, ip="1.2.3.4", country="US", city="Nowhere", raw={"region": "FL"})

    monkeypatch.setattr("flows.geo.probe", fake_probe)
    city, _ = await resolve_target_city("1.2.3.4:8000:u:p", fallback="Delray Beach, FL")
    assert city == city_for_state("FL")
