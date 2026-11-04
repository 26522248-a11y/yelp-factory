"""Scheduler tests: daily planning, working-hours gate, idempotent enqueue."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from core.scheduler import due_sessions, enqueue_day, sessions_used_today
from db.models import AccountState, WarmingPlan, WarmingTask
from db.session import session_scope

pytestmark = pytest.mark.usefixtures("db_ready")


def _sessions(account_id):
    with session_scope() as session:
        plan_ids = [p.id for p in session.query(WarmingPlan).filter_by(account_id=account_id).all()]
        if not plan_ids:
            return []
        return session.query(WarmingTask).filter(WarmingTask.plan_id.in_(plan_ids), WarmingTask.kind == "session").all()


def test_plan_contains_one_to_three_sessions(make_account):
    account = make_account()
    inserted = enqueue_day(account.id, city="Delray Beach, FL", day=4)
    assert inserted > 0
    sessions = _sessions(account.id)
    assert 1 <= len(sessions) <= 3


def test_enqueue_is_idempotent_for_the_same_day(make_account):
    account = make_account()
    first = enqueue_day(account.id, city="Delray Beach, FL", day=4)
    second = enqueue_day(account.id, city="Delray Beach, FL", day=4)
    assert first > 0
    assert second == 0


def test_sessions_used_today_starts_at_zero(make_account):
    account = make_account()
    assert sessions_used_today(account.id) == 0


def test_due_sessions_skip_non_active_accounts(make_account):
    account = make_account(state=AccountState.QUARANTINED)
    enqueue_day(account.id, city="Delray Beach, FL", day=4)
    for task in _sessions(account.id):
        mark_id = task.id
        with session_scope() as session:
            session.get(WarmingTask, mark_id).due_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    assert all(item.account_id != account.id for item in due_sessions(limit=50))


def test_due_sessions_include_active_account_when_hours_allow(make_account, monkeypatch):
    account = make_account(state=AccountState.ACTIVE)
    enqueue_day(account.id, city="Delray Beach, FL", day=4)
    for task in _sessions(account.id):
        with session_scope() as session:
            session.get(WarmingTask, task.id).due_at = datetime.now(timezone.utc) - timedelta(minutes=5)

    monkeypatch.setattr("core.scheduler.within_working_hours", lambda city: True)
    found = {item.account_id for item in due_sessions(limit=50)}
    assert account.id in found


def test_due_sessions_respect_working_hours(make_account, monkeypatch):
    account = make_account(state=AccountState.ACTIVE)
    enqueue_day(account.id, city="Delray Beach, FL", day=4)
    monkeypatch.setattr("core.scheduler.within_working_hours", lambda city: False)
    assert all(item.account_id != account.id for item in due_sessions(limit=50))
