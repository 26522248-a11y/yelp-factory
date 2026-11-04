"""E-54: selector registry misses above threshold trigger an alert."""

from __future__ import annotations

from types import SimpleNamespace

from selector_registry.resolver import MISS_ALERT_THRESHOLD, registry_health


def test_E54_alert_when_misses_exceed_threshold():
    rows = [
        SimpleNamespace(key="signup.email", miss_count=MISS_ALERT_THRESHOLD + 1),
        SimpleNamespace(key="signup.zip", miss_count=MISS_ALERT_THRESHOLD),
    ]
    assert registry_health(rows) == ["signup.email"]
