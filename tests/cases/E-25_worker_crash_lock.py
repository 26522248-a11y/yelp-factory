"""E-25: worker died -> stale lock is reaped and the job can run again."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from core.lock import AccountLockManager, reap_stale_locks
from db.models import AccountLock
from db.session import session_scope

pytestmark = pytest.mark.usefixtures("db_ready")


def test_E25_stale_lock_is_reaped(make_account):
    account = make_account()
    manager = AccountLockManager("worker-dead")
    assert manager.acquire(account.id)

    with session_scope() as session:
        row = session.get(AccountLock, account.id)
        row.heartbeat_at = datetime.now(timezone.utc) - timedelta(hours=2)
        row.ttl_seconds = 60

    reaped = reap_stale_locks()
    assert reaped >= 1

    successor = AccountLockManager("worker-alive")
    assert successor.acquire(account.id) is True
    successor.release(account.id)
