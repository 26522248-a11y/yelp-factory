"""E-45: three failures in a row on one domain -> domain disabled for 24h."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core.guards import DOMAIN_COOLDOWN_HOURS, DomainHealth


def test_E45_domain_disabled_after_three_failures():
    health = DomainHealth()
    now = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)
    assert health.record_failure("bad.com", now=now) is False
    assert health.record_failure("bad.com", now=now) is False
    assert health.record_failure("bad.com", now=now) is True
    assert health.is_available("bad.com", now=now) is False


def test_E45_domain_returns_after_cooldown():
    health = DomainHealth()
    now = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)
    for _ in range(3):
        health.record_failure("bad.com", now=now)
    later = now + timedelta(hours=DOMAIN_COOLDOWN_HOURS + 1)
    assert health.is_available("bad.com", now=later) is True
    assert health.pick(["bad.com", "good.com"], now=now) == "good.com"


def test_E45_success_resets_the_counter():
    health = DomainHealth()
    for _ in range(2):
        health.record_failure("ok.com")
    health.record_success("ok.com")
    assert health.record_failure("ok.com") is False
    assert health.failures["ok.com"] == 1
