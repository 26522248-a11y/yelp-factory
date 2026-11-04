"""Trust score + gates (warming spec v1.0)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from core.trust import (
    REVIEW_THRESHOLD,
    TrustBreakdown,
    allowed_kinds,
    compute_trust,
    latest_trust,
    record_trust,
)

pytestmark = pytest.mark.usefixtures("db_ready")


def test_score_is_clamped_and_weighted():
    perfect = TrustBreakdown(age=20, profile=15, consistency=15, diversity=20, content=20, risk=0)
    assert perfect.score == 90
    assert TrustBreakdown(age=20, profile=15, consistency=15, diversity=20, content=20, risk=-60).score == 30
    assert TrustBreakdown(age=-50).score == 0


def test_gates_by_score():
    assert allowed_kinds(10) == {"pageview", "search", "scroll", "session"}
    assert "save" in allowed_kinds(45)
    assert "vote" in allowed_kinds(65)
    assert "review" not in allowed_kinds(65)
    assert "review" in allowed_kinds(REVIEW_THRESHOLD)


def test_new_account_cannot_review(make_account):
    account = make_account()
    ok, reason = __import__("core.trust", fromlist=["review_eligible"]).review_eligible(account.id)
    assert ok is False
    assert "trust" in reason or "age" in reason or "sessions" in reason


def test_trust_is_persisted_and_read_back(make_account):
    account = make_account()
    score = record_trust(account.id)
    assert 0 <= score <= 100
    assert latest_trust(account.id) == score


def test_age_component_grows(monkeypatch, make_account):
    account = make_account()
    now = datetime.now(timezone.utc) + timedelta(days=20)
    breakdown = compute_trust(account.id, now=now)
    assert breakdown.age >= 13  # 20 days * 0.7
