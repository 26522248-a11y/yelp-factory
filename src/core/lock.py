"""Per-account advisory locks with TTL + heartbeat (section 11, E-25)."""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from db.models import AccountLock
from db.session import session_scope
from obs.log import get_logger

log = get_logger("lock")

DEFAULT_TTL_SECONDS = 900
HEARTBEAT_SECONDS = 30


class AccountLockManager:
    def __init__(self, worker_id: str | None = None, ttl_seconds: int = DEFAULT_TTL_SECONDS):
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
        self.ttl_seconds = ttl_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._held: set[uuid.UUID] = set()

    # ------------------------------------------------------------------ API

    def acquire(self, account_id: uuid.UUID) -> bool:
        now = datetime.now(timezone.utc)
        with session_scope() as session:
            stmt = pg_insert(AccountLock).values(
                account_id=account_id,
                worker_id=self.worker_id,
                acquired_at=now,
                heartbeat_at=now,
                ttl_seconds=self.ttl_seconds,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=[AccountLock.account_id],
                set_={
                    "worker_id": self.worker_id,
                    "acquired_at": now,
                    "heartbeat_at": now,
                    "ttl_seconds": self.ttl_seconds,
                },
                where=text(
                    "account_locks.heartbeat_at < now() - make_interval(secs => account_locks.ttl_seconds)"
                ),
            )
            result = session.execute(stmt.returning(AccountLock.account_id))
            acquired = result.first() is not None
        if acquired:
            self._held.add(account_id)
            log.info("lock_acquired", account_id=str(account_id))
        return acquired

    def heartbeat(self, account_id: uuid.UUID) -> bool:
        with session_scope() as session:
            row = session.get(AccountLock, account_id)
            if row is None or row.worker_id != self.worker_id:
                return False
            row.heartbeat_at = datetime.now(timezone.utc)
        return True

    def release(self, account_id: uuid.UUID) -> None:
        with session_scope() as session:
            session.execute(
                delete(AccountLock).where(
                    AccountLock.account_id == account_id, AccountLock.worker_id == self.worker_id
                )
            )
        self._held.discard(account_id)

    def held(self) -> set[uuid.UUID]:
        return set(self._held)

    # ------------------------------------------------------------------ heartbeat loop

    def start_heartbeat(self, interval_s: float = HEARTBEAT_SECONDS) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()

        def loop() -> None:
            while not self._stop.wait(interval_s):
                for account_id in list(self._held):
                    try:
                        if not self.heartbeat(account_id):
                            log.warning("lock_lost", account_id=str(account_id))
                            self._held.discard(account_id)
                    except Exception as exc:  # noqa: BLE001
                        log.error("heartbeat_failed", error=str(exc)[:200])

        self._thread = threading.Thread(target=loop, name="lock-heartbeat", daemon=True)
        self._thread.start()

    def stop_heartbeat(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)


def reap_stale_locks(older_than_seconds: int = DEFAULT_TTL_SECONDS) -> int:
    """Delete locks whose heartbeat is older than their TTL (E-25)."""
    with session_scope() as session:
        result = session.execute(
            text(
                "DELETE FROM account_locks "
                "WHERE heartbeat_at < now() - make_interval(secs => CASE WHEN ttl_seconds > 0 THEN ttl_seconds ELSE :fallback END)"
            ),
            {"fallback": older_than_seconds},
        )
        count = result.rowcount or 0
    if count:
        log.warning("stale_locks_reaped", count=count)
    return count


def list_locks():
    with session_scope() as session:
        return session.scalars(select(AccountLock)).all()
