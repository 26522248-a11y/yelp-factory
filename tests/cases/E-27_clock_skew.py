"""E-27: clock skew above 60s is logged and the DB time is used for decisions."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core.guards import clock_skew_ok, clock_skew_seconds


def test_E27_small_skew_is_fine():
    now = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)
    server = now - timedelta(seconds=30)
    assert clock_skew_ok(server, now=now) is True
    assert clock_skew_seconds(server, now=now) == 30


def test_E27_large_skew_is_flagged():
    now = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)
    server = now - timedelta(minutes=5)
    assert clock_skew_ok(server, now=now) is False


def test_E27_naive_timestamp_is_treated_as_utc():
    now = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)
    assert clock_skew_seconds(datetime(2026, 11, 4, 11, 59), now=now) == 60
