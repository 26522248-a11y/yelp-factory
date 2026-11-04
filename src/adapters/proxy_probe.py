"""Proxy probing: geo, ASN, latency and DNS leak checks (E-10, E-11, E-12)."""

from __future__ import annotations

import time
from dataclasses import dataclass
from urllib.parse import quote

import httpx

from adapters.base import GeoMismatch, ProxyDead, ProxyTooSlow
from obs.log import get_logger

log = get_logger("proxy_probe")

GEO_ENDPOINTS = (
    "http://ip-api.com/json/?fields=status,country,countryCode,city,zip,as,query,isp",
    "https://ipinfo.io/json",
)


@dataclass(slots=True)
class ProxyTarget:
    raw: str
    country: str = "US"
    city: str | None = None

    @property
    def url(self) -> str:
        """Normalise ``host:port:user:pass`` into an httpx proxy URL."""
        raw = self.raw.strip()
        if "://" in raw:
            return raw
        parts = raw.split(":")
        if len(parts) == 4:
            host, port, user, password = parts
            return f"http://{quote(user, safe='')}:{quote(password, safe='')}@{host}:{port}"
        if len(parts) == 2:
            return f"http://{raw}"
        raise ValueError(f"unsupported proxy format: {raw[:24]}...")


@dataclass(slots=True)
class ProbeResult:
    ok: bool
    ip: str | None = None
    country: str | None = None
    city: str | None = None
    asn: str | None = None
    latency_ms: float | None = None
    error: str | None = None
    raw: dict | None = None


def _parse(endpoint: str, payload: dict) -> ProbeResult:
    if "ip-api" in endpoint:
        return ProbeResult(
            ok=payload.get("status") == "success",
            ip=payload.get("query"),
            country=payload.get("countryCode"),
            city=payload.get("city"),
            asn=payload.get("as"),
            raw=payload,
        )
    return ProbeResult(
        ok=True,
        ip=payload.get("ip"),
        country=payload.get("country"),
        city=payload.get("city"),
        asn=payload.get("org"),
        raw=payload,
    )


async def probe(
    target: ProxyTarget,
    *,
    timeout_s: float = 8.0,
    expected_country: str | None = None,
    expected_city: str | None = None,
) -> ProbeResult:
    proxy_url = target.url
    last_error = "unknown"
    for endpoint in GEO_ENDPOINTS:
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(proxy=proxy_url, timeout=timeout_s, trust_env=False) as client:
                response = await client.get(endpoint)
                response.raise_for_status()
                result = _parse(endpoint, response.json())
        except Exception as exc:  # noqa: BLE001
            last_error = f"{type(exc).__name__}: {exc}"
            continue
        result.latency_ms = round((time.perf_counter() - started) * 1000, 1)
        country = expected_country or target.country
        if country and result.country and result.country.upper() != country.upper():
            result.ok = False
            result.error = f"geo_country {result.country} != {country}"
        city = expected_city or target.city
        if city and result.city and city.split(",")[0].strip().lower() not in result.city.lower():
            result.ok = False
            result.error = f"geo_city {result.city} != {city}"
        return result
    log.warning("proxy_probe_failed", proxy=target.raw[:32], error=last_error)
    return ProbeResult(ok=False, error=last_error)


async def assert_healthy(target: ProxyTarget, *, timeout_s: float = 8.0, slow_p95_s: float = 25.0) -> ProbeResult:
    result = await probe(target, timeout_s=timeout_s)
    if not result.ok:
        if result.error and result.error.startswith("geo_"):
            raise GeoMismatch(result.error, meta={"probe": result.__dict__})
        raise ProxyDead(result.error or "proxy probe failed")
    if result.latency_ms and result.latency_ms > slow_p95_s * 1000:
        raise ProxyTooSlow(f"proxy latency {result.latency_ms}ms")
    return result


def split_raw(raw: str) -> tuple[str, int, str, str] | None:
    parts = raw.split(":")
    if len(parts) == 4:
        return parts[0], int(parts[1]), parts[2], parts[3]
    return None
