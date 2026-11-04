"""Resolve the registration city from the proxy IP instead of asking the user."""

from __future__ import annotations

from adapters.proxy_probe import ProbeResult, ProxyTarget, probe
from flows.pools import ZIP_POOL
from obs.log import get_logger

log = get_logger("geo")

# City -> state from the local ZIP pool (only cities we can build a persona for).
KNOWN_CITIES: dict[str, str] = {}
for _zip, (_city, _state) in ZIP_POOL.items():
    KNOWN_CITIES.setdefault(f"{_city}, {_state}", _state)


def city_for_state(state: str) -> str | None:
    for city in KNOWN_CITIES:
        if city.endswith(f", {state}"):
            return city
    return None


def match_known_city(probe_city: str | None, state: str | None = None) -> str | None:
    if probe_city:
        needle = probe_city.split(",")[0].strip().lower()
        for known in KNOWN_CITIES:
            if known.split(",")[0].strip().lower() == needle:
                return known
    if state:
        return city_for_state(state.upper())
    return None


async def resolve_target_city(
    raw_proxy: str,
    *,
    fallback: str,
    country: str = "US",
    timeout_s: float = 8.0,
) -> tuple[str, ProbeResult | None]:
    """Probe the proxy and map its city to a city we have ZIPs for.

    Returns ``(city, probe_result)``; falls back to ``fallback`` when the exit city is unknown
    (mobile proxies rotate a lot, so this is common).
    """
    if not raw_proxy:
        return fallback, None
    result = await probe(ProxyTarget(raw=raw_proxy, country=country), timeout_s=timeout_s)
    if not result.ok:
        log.warning("geo_probe_failed", error=result.error)
        return fallback, result
    known = match_known_city(result.city, (result.raw or {}).get("region") if result.raw else None)
    if known:
        log.info("city_resolved_from_proxy", ip=result.ip, probe_city=result.city, city=known)
        return known, result
    fallback_state = fallback.split(",")[-1].strip() if "," in fallback else None
    by_state = city_for_state(fallback_state) if fallback_state else None
    city = by_state or fallback
    log.warning("city_unknown_fallback", probe_city=result.city, city=city)
    return city, result
