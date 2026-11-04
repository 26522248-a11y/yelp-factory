"""E-52: a filtered review is recorded and the business is paused for 7 days."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core.guards import REVIEW_COOLDOWN_DAYS, ReviewTracker


def test_E52_filtered_review_pauses_the_business():
    tracker = ReviewTracker()
    now = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)
    tracker.mark_filtered("biz-1", now=now)
    assert tracker.can_review("biz-1", now=now) is False
    assert tracker.can_review("biz-1", now=now + timedelta(days=REVIEW_COOLDOWN_DAYS + 1)) is True


def test_E52_other_businesses_are_unaffected():
    tracker = ReviewTracker()
    tracker.mark_filtered("biz-1")
    assert tracker.can_review("biz-2") is True


def test_E52_review_is_never_deleted_from_history():
    tracker = ReviewTracker()
    tracker.mark_filtered("biz-1")
    assert "biz-1" in tracker.filtered
