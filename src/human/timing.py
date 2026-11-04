"""Session rhythm helpers: working hours, session length, idle jitter (section 8.1)."""

from __future__ import annotations

import random
from datetime import datetime, time

# US city -> IANA timezone for the working-hours window
CITY_TIMEZONES = {
    "Austin, TX": "America/Chicago",
    "Dallas, TX": "America/Chicago",
    "Houston, TX": "America/Chicago",
    "Miami, FL": "America/New_York",
    "Delray Beach, FL": "America/New_York",
    "Boca Raton, FL": "America/New_York",
    "Seattle, WA": "America/Los_Angeles",
    "Portland, OR": "America/Los_Angeles",
    "Phoenix, AZ": "America/Phoenix",
}

WORK_START = time(6, 0)
WORK_END = time(23, 0)


def local_now(city: str) -> datetime:
    from zoneinfo import ZoneInfo

    tz = ZoneInfo(CITY_TIMEZONES.get(city, "America/Chicago"))
    return datetime.now(tz)


def within_working_hours(city: str) -> bool:
    now = local_now(city).time()
    return WORK_START <= now <= WORK_END


def session_length_seconds() -> int:
    return random.randint(4 * 60, 12 * 60)


def empty_session(probability: float = 0.05) -> bool:
    """SHOULD: ~5% of sessions only open the site to break the pattern."""
    return random.random() < probability


async def idle(page, low: float = 0.8, high: float = 3.0) -> None:
    await page.wait_for_timeout(int(random.uniform(low, high) * 1000))
