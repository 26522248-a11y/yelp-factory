"""Step checkpoints: after every state the flow can be resumed without replaying it."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from db.models import Account, AccountState, Run, RunState, Step
from db.session import session_scope
from obs.log import get_logger

log = get_logger("checkpoints")

TERMINAL_STATES = {AccountState.QUARANTINED.value, AccountState.DEAD.value, AccountState.SUSPENDED.value}
RESUMABLE_PENDING = {AccountState.EMAIL_PENDING.value, AccountState.PHONE_PENDING.value}


@dataclass(slots=True)
class StepRecord:
    seq: int
    name: str
    status: str
    meta: dict[str, Any]
    artifact_prefix: str | None = None


class CheckpointStore:
    def __init__(self, run_id: uuid.UUID):
        self.run_id = run_id

    def next_seq(self) -> int:
        with session_scope() as session:
            row = session.execute(
                select(Step.seq).where(Step.run_id == self.run_id).order_by(Step.seq.desc()).limit(1)
            ).first()
        return (row[0] + 1) if row else 1

    def start(self, name: str, *, seq: int | None = None) -> int:
        seq = seq or self.next_seq()
        with session_scope() as session:
            session.add(
                Step(
                    run_id=self.run_id,
                    seq=seq,
                    name=name,
                    status="RUNNING",
                    started_at=datetime.now(timezone.utc),
                    meta={},
                )
            )
        return seq

    def finish(
        self,
        seq: int,
        name: str,
        status: str = "DONE",
        *,
        meta: dict[str, Any] | None = None,
        artifact_prefix: str | None = None,
    ) -> None:
        with session_scope() as session:
            row = session.execute(select(Step).where(Step.run_id == self.run_id, Step.seq == seq)).scalar_one_or_none()
            if row is None:
                row = Step(run_id=self.run_id, seq=seq, name=name, status=status, meta=meta or {})
                session.add(row)
            row.status = status
            row.ended_at = datetime.now(timezone.utc)
            row.meta = meta or row.meta or {}
            row.artifact_prefix = artifact_prefix or row.artifact_prefix
        log.info("step_checkpoint", step=name, status=status, seq=seq)

    def completed_names(self) -> list[str]:
        with session_scope() as session:
            rows = session.scalars(
                select(Step).where(Step.run_id == self.run_id, Step.status.in_(("DONE", "SKIPPED")))
            ).all()
        return [row.name for row in rows]

    def last_state(self) -> str | None:
        with session_scope() as session:
            row = (
                session.execute(
                    select(Step).where(Step.run_id == self.run_id, Step.status.in_(("DONE", "SKIPPED"))).order_by(Step.seq.desc()).limit(1)
                ).scalar_one_or_none()
            )
        return row.name if row else None


def persist_account_state(account_id: uuid.UUID, state: AccountState, *, substate: str | None = None) -> None:
    with session_scope() as session:
        account = session.get(Account, account_id)
        if account is None:
            raise KeyError(f"account {account_id} not found")
        account.state = state.value
        account.substate = substate
        if state == AccountState.ACTIVE and account.activated_at is None:
            account.activated_at = datetime.now(timezone.utc)
        if state == AccountState.SUSPENDED and account.suspended_at is None:
            account.suspended_at = datetime.now(timezone.utc)


def load_account(account_id: uuid.UUID) -> Account | None:
    with session_scope() as session:
        return session.get(Account, account_id)


def open_run(account_id: uuid.UUID, *, kind: str = "signup", trace_id: str | None = None, worker_id: str | None = None) -> uuid.UUID:
    """Open a run; a duplicate RUNNING run is rejected by the partial unique index (E-26)."""
    with session_scope() as session:
        run = Run(
            account_id=account_id,
            kind=kind,
            state=RunState.RUNNING.value,
            started_at=datetime.now(timezone.utc),
            worker_id=worker_id,
            trace_id=trace_id,
        )
        session.add(run)
        session.flush()
        return run.id


def close_run(run_id: uuid.UUID, state: RunState = RunState.DONE) -> None:
    with session_scope() as session:
        run = session.get(Run, run_id)
        if run is None:
            return
        run.state = state.value
        run.ended_at = datetime.now(timezone.utc)
