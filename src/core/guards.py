"""Small deterministic guards used by the flows and covered by the E-xx test matrix."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from obs.log import get_logger

log = get_logger("guards")

CLOCK_SKEW_WARN_S = 60
REDIRECT_LIMIT = 5
DOMAIN_FAIL_LIMIT = 3
DOMAIN_COOLDOWN_HOURS = 24
REVIEW_COOLDOWN_DAYS = 7


# --------------------------------------------------------------------------- E-27


def clock_skew_seconds(server_time: datetime, *, now: datetime | None = None) -> float:
    now = now or datetime.now(timezone.utc)
    if server_time.tzinfo is None:
        server_time = server_time.replace(tzinfo=timezone.utc)
    return (now - server_time).total_seconds()


def clock_skew_ok(server_time: datetime, *, now: datetime | None = None) -> bool:
    skew = clock_skew_seconds(server_time, now=now)
    if abs(skew) > CLOCK_SKEW_WARN_S:
        log.warning("clock_skew", seconds=round(skew, 1))
        return False
    return True


# --------------------------------------------------------------------------- E-28


async def reload_once(page, *, wait: str = "domcontentloaded") -> bool:
    """E-28: one controlled reload when the page loads half-way or JS throws."""
    try:
        await page.reload(wait_until=wait)
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("reload_failed", error=str(exc)[:150])
        return False


# --------------------------------------------------------------------------- E-29


@dataclass
class RedirectGuard:
    """Detects redirect loops without relying on the browser's navigation history."""

    limit: int = REDIRECT_LIMIT
    _chain: list[str] = field(default_factory=list)
    _last: float = field(default_factory=time.monotonic)

    def observe(self, url: str) -> bool:
        """Record a hop; returns False when the same URL repeats more than ``limit`` times."""
        now = time.monotonic()
        if now - self._last > 10:  # a new navigation session
            self._chain.clear()
        self._last = now
        self._chain.append(url)
        if self._chain.count(url) > self.limit:
            log.warning("redirect_loop", url=url, hops=len(self._chain))
            return False
        return len(self._chain) <= self.limit * 2

    @property
    def hops(self) -> int:
        return len(self._chain)

    def reset(self) -> None:
        self._chain.clear()


# --------------------------------------------------------------------------- E-45


@dataclass
class DomainHealth:
    """Tracks consecutive failures per email domain and cools a bad domain down for 24h."""

    failures: dict[str, int] = field(default_factory=dict)
    disabled_until: dict[str, datetime] = field(default_factory=dict)

    def record_failure(self, domain: str, *, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        self.failures[domain] = self.failures.get(domain, 0) + 1
        if self.failures[domain] >= DOMAIN_FAIL_LIMIT:
            self.disabled_until[domain] = now + timedelta(hours=DOMAIN_COOLDOWN_HOURS)
            log.warning("email_domain_disabled", domain=domain, hours=DOMAIN_COOLDOWN_HOURS)
            return True
        return False

    def record_success(self, domain: str) -> None:
        self.failures.pop(domain, None)
        self.disabled_until.pop(domain, None)

    def is_available(self, domain: str, *, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        until = self.disabled_until.get(domain)
        return until is None or until <= now

    def pick(self, domains: list[str], *, now: datetime | None = None) -> str | None:
        return next((d for d in domains if self.is_available(d, now=now)), None)


# --------------------------------------------------------------------------- E-52


@dataclass
class ReviewTracker:
    """Remembers reviews that Yelp filtered so the account pauses that business for 7 days."""

    filtered: dict[str, datetime] = field(default_factory=dict)

    def mark_filtered(self, business_id: str, *, now: datetime | None = None) -> None:
        self.filtered[business_id] = (now or datetime.now(timezone.utc)) + timedelta(days=REVIEW_COOLDOWN_DAYS)
        log.warning("review_filtered", business_id=business_id, cooldown_days=REVIEW_COOLDOWN_DAYS)

    def can_review(self, business_id: str, *, now: datetime | None = None) -> bool:
        until = self.filtered.get(business_id)
        return until is None or until <= (now or datetime.now(timezone.utc))


# --------------------------------------------------------------------------- E-55


async def navigate_via_search(page, registry, query: str) -> bool:
    """E-55: when a URL changes, reach the page through the site's own search bar."""
    box = await registry.find(page, "warmup.search", required=False, timeout_ms=4000)
    if box is None:
        log.warning("search_fallback_missing")
        return False
    await box.fill(query)
    await box.press("Enter")
    await page.wait_for_load_state("domcontentloaded", timeout=30_000)
    return True


# --------------------------------------------------------------------------- E-36


def v3_throttle(prewarm_seconds: int) -> int:
    """A low reCAPTCHA v3 score means longer pre-warm before the next attempt."""
    return min(prewarm_seconds * 2, 60)
