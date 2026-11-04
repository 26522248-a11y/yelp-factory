"""E-04: profile already running with a stale lock -> reuse when expired, stop+start otherwise."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from core.lock import AccountLockManager
from db.models import AccountLock
from db.session import session_scope

pytestmark = pytest.mark.usefixtures("db_ready")


def test_E04_expired_lock_can_be_reacquired(make_account):
    account = make_account()
    first = AccountLockManager("worker-a")
    assert first.acquire(account.id) is True

    # Simulate a dead worker: heartbeat older than the TTL.
    with session_scope() as session:
        row = session.get(AccountLock, account.id)
        row.heartbeat_at = datetime.now(timezone.utc) - timedelta(hours=1)
        row.ttl_seconds = 60

    second = AccountLockManager("worker-b")
    assert second.acquire(account.id) is True
    first.release(account.id)


def test_E04_live_lock_blocks_a_second_worker(make_account):
    account = make_account()
    first = AccountLockManager("worker-a")
    assert first.acquire(account.id) is True
    second = AccountLockManager("worker-b")
    assert second.acquire(account.id) is False
    first.release(account.id)
