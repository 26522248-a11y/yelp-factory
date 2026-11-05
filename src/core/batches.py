"""Batch tracking: group signup runs and report which warming stage they reached.

A batch is a label on accounts; all progress is derived from the existing state machine,
warming plans and trust tables, so the report never drifts from reality.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Iterable

from sqlalchemy import func, select

from core.budget import phase_for_day
from db.models import (
    Account,
    AccountState,
    ActionLog,
    Batch,
    Run,
    Step,
    TrustScore,
    WarmingPlan,
    WarmingSession,
    WarmingTask,
)
from db.session import session_scope
from obs.log import get_logger

log = get_logger("batches")

SUCCESS_STATES = (AccountState.ACTIVE.value, AccountState.WARMING.value)

REGISTERING_STATES = {
    AccountState.NEW.value,
    AccountState.PROVISIONING.value,
    AccountState.PROXY_BOUND.value,
    AccountState.BROWSER_UP.value,
    AccountState.PREWARMED.value,
    AccountState.FORM_FILLED.value,
    AccountState.CAPTCHA_SOLVED.value,
}
CREATED_STATES = {
    AccountState.SUBMITTED.value,
    AccountState.EMAIL_PENDING.value,
    AccountState.EMAIL_VERIFIED.value,
    AccountState.PHONE_PENDING.value,
    AccountState.PHONE_VERIFIED.value,
    AccountState.ONBOARDED.value,
}
TERMINAL_STATES = {
    AccountState.QUARANTINED.value,
    AccountState.RESTRICTED.value,
    AccountState.SUSPENDED.value,
    AccountState.DEAD.value,
}


@dataclass(slots=True)
class AccountProgress:
    email: str
    stage: str
    state: str
    trust: int | None
    last_session: datetime | None
    sessions_today: int
    next_action: str
    due_at: datetime | None


# --------------------------------------------------------------------------- pure helpers


def stage_for_state(state: str, *, day: int = 1, has_session: bool = False) -> str:
    """Map an account to its registration/warming stage (deterministic, no DB)."""
    if state in TERMINAL_STATES:
        return state
    if state in REGISTERING_STATES:
        return "REGISTERING"
    if state in CREATED_STATES:
        return "CREATED"
    if state in SUCCESS_STATES:
        if not has_session:
            return "READY"
        if day > 30:
            return "MATURE"
        return f"WARM_{phase_for_day(day)}"
    return "UNKNOWN"


def next_action_for(
    state: str,
    *,
    submitted_done: bool = False,
    has_avatar: bool = False,
    profile_done: bool = False,
    warm_due: bool = False,
) -> str:
    if state == AccountState.QUARANTINED.value:
        return "recover" if submitted_done else "skip"
    if state == AccountState.ONBOARDED.value:
        return "onboard"
    if state in SUCCESS_STATES:
        if not has_avatar:
            return "avatar"
        if not profile_done:
            return "profile"
        if warm_due:
            return "warm"
        return "idle"
    if state in (AccountState.RESTRICTED.value, AccountState.SUSPENDED.value, AccountState.DEAD.value):
        return "manual"
    return "wait"


# --------------------------------------------------------------------------- batch CRUD


def create_batch(
    name: str,
    *,
    source: str = "auto",
    target_count: int = 0,
    config_snapshot: dict | None = None,
    notes: str | None = None,
) -> dict:
    with session_scope() as session:
        existing = session.scalar(select(Batch).where(Batch.name == name))
        if existing is not None:
            raise ValueError(f"batch_exists:{name}")
        batch = Batch(
            name=name,
            source=source,
            target_count=target_count,
            status="planned",
            config_snapshot=config_snapshot or {},
            notes=notes,
        )
        session.add(batch)
        session.flush()
        return {"id": str(batch.id), "name": batch.name, "status": batch.status}


def get_batch(ref: str) -> Batch | None:
    try:
        batch_id = uuid.UUID(ref)
    except (ValueError, TypeError):
        batch_id = None
    with session_scope() as session:
        if batch_id is not None:
            return session.get(Batch, batch_id)
        return session.scalar(select(Batch).where(Batch.name == ref))


def set_status(ref: str, status: str) -> dict:
    with session_scope() as session:
        batch = session.scalar(select(Batch).where(Batch.name == ref)) if not _is_uuid(ref) else session.get(Batch, uuid.UUID(ref))
        if batch is None:
            raise ValueError(f"batch_not_found:{ref}")
        batch.status = status
        if status == "running" and batch.started_at is None:
            batch.started_at = datetime.now(timezone.utc)
        if status == "closed":
            batch.closed_at = datetime.now(timezone.utc)
        return {"name": batch.name, "status": batch.status}


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except (ValueError, TypeError):
        return False


def paused_batch_ids() -> set[uuid.UUID]:
    with session_scope() as session:
        return set(session.scalars(select(Batch.id).where(Batch.status == "paused")))


def batch_account_ids(ref: str) -> list[uuid.UUID]:
    batch = get_batch(ref)
    if batch is None:
        raise ValueError(f"batch_not_found:{ref}")
    with session_scope() as session:
        return list(session.scalars(select(Account.id).where(Account.batch_id == batch.id).order_by(Account.created_at)))


def backfill_legacy() -> dict:
    """Create B1/B2/B3 from the known 2026-11-04 windows and B0 for the rest."""
    from sqlalchemy import update

    windows = [
        ("B1", datetime(2026, 11, 4, 8, 0, tzinfo=timezone.utc), datetime(2026, 11, 4, 14, 0, tzinfo=timezone.utc)),
        ("B2", datetime(2026, 11, 4, 14, 0, tzinfo=timezone.utc), datetime(2026, 11, 4, 16, 0, tzinfo=timezone.utc)),
        ("B3", datetime(2026, 11, 4, 16, 0, tzinfo=timezone.utc), datetime(2026, 11, 4, 18, 0, tzinfo=timezone.utc)),
    ]
    assigned = 0
    with session_scope() as session:
        legacy = session.scalar(select(Batch).where(Batch.name == "B0"))
        if legacy is None:
            legacy = Batch(name="B0", source="auto", status="warming", target_count=0, notes="legacy accounts")
            session.add(legacy)
            session.flush()

        for name, start, end in windows:
            batch = session.scalar(select(Batch).where(Batch.name == name))
            if batch is None:
                batch = Batch(name=name, source="pool_proxy", status="warming", target_count=0)
                session.add(batch)
                session.flush()
            # Keep earlier/later accounts out of this window.
            session.execute(
                update(Account)
                .where(Account.batch_id == batch.id, Account.created_at < start)
                .values(batch_id=legacy.id)
            )
            session.execute(
                update(Account)
                .where(Account.batch_id == batch.id, Account.created_at >= end)
                .values(batch_id=legacy.id)
            )
            accounts = session.scalars(
                select(Account).where(
                    Account.batch_id.is_(None),
                    Account.created_at >= start,
                    Account.created_at < end,
                )
            ).all()
            for account in accounts:
                account.batch_id = batch.id
                assigned += 1

        orphans = session.scalars(select(Account).where(Account.batch_id.is_(None))).all()
        for account in orphans:
            account.batch_id = legacy.id
            assigned += 1
    return {"assigned": assigned}


# --------------------------------------------------------------------------- reporting


def _account_progress(session, account: Account, *, today_start: datetime) -> AccountProgress:
    day = max(1, (datetime.now(timezone.utc).date() - account.created_at.date()).days + 1) if account.created_at else 1
    sessions_today = session.scalar(
        select(func.count()).select_from(WarmingSession).where(
            WarmingSession.account_id == account.id, WarmingSession.started_at >= today_start
        )
    ) or 0
    last_session = session.scalar(
        select(func.max(WarmingSession.ended_at)).where(WarmingSession.account_id == account.id)
    )
    trust = session.scalar(
        select(TrustScore.score).where(TrustScore.account_id == account.id).order_by(TrustScore.id.desc()).limit(1)
    )
    submitted = session.scalar(
        select(func.count()).select_from(Step).join(Run, Run.id == Step.run_id).where(
            Run.account_id == account.id, Step.name == "SUBMITTED", Step.status == "DONE"
        )
    ) or 0
    profile_done = (account.substate or "") in ("profile_completed", "avatar_uploaded") or bool(
        account.birth_date and account.address_line
    )
    avatar_done = (account.substate or "") == "avatar_uploaded" and bool(account.avatar_path) and Path(account.avatar_path).exists()
    due = session.scalar(
        select(func.min(WarmingTask.due_at)).join(WarmingPlan, WarmingPlan.id == WarmingTask.plan_id).where(
            WarmingPlan.account_id == account.id,
            WarmingTask.kind == "session",
            WarmingTask.status == "pending",
            WarmingTask.due_at <= datetime.now(timezone.utc),
        )
    )
    stage = stage_for_state(account.state, day=day, has_session=last_session is not None)
    action = next_action_for(
        account.state,
        submitted_done=bool(submitted),
        has_avatar=avatar_done,
        profile_done=profile_done,
        warm_due=due is not None,
    )
    return AccountProgress(
        email=account.email,
        stage=stage,
        state=account.state,
        trust=trust,
        last_session=last_session,
        sessions_today=int(sessions_today),
        next_action=action,
        due_at=due,
    )


def batch_summary(ref: str) -> dict:
    batch = get_batch(ref)
    if batch is None:
        raise ValueError(f"batch_not_found:{ref}")
    today_start = datetime.combine(datetime.now(timezone.utc).date(), time.min, tzinfo=timezone.utc)
    with session_scope() as session:
        accounts = session.scalars(select(Account).where(Account.batch_id == batch.id).order_by(Account.created_at)).all()
        progress = [_account_progress(session, account, today_start=today_start) for account in accounts]
        actions_today = session.scalar(
            select(func.count()).select_from(ActionLog).join(Account, Account.id == ActionLog.account_id).where(
                Account.batch_id == batch.id, ActionLog.ts >= today_start
            )
        ) or 0
    stages: dict[str, int] = {}
    actions: dict[str, int] = {}
    for item in progress:
        stages[item.stage] = stages.get(item.stage, 0) + 1
        actions[item.next_action] = actions.get(item.next_action, 0) + 1
    phases = {key: value for key, value in stages.items() if key.startswith("WARM_") or key in ("READY", "MATURE")}
    phase = max(phases, key=phases.get) if phases else None
    trusts = [item.trust for item in progress if item.trust is not None]
    due_times = [item.due_at for item in progress if item.due_at is not None]
    return {
        "name": batch.name,
        "status": batch.status,
        "source": batch.source,
        "target": batch.target_count,
        "created_at": batch.created_at,
        "accounts": len(accounts),
        "stages": stages,
        "phase": phase.replace("WARM_", "") if phase and phase.startswith("WARM_") else phase,
        "phases": phases,
        "sessions_today": sum(item.sessions_today for item in progress),
        "actions_today": int(actions_today),
        "trust_min": min(trusts) if trusts else None,
        "trust_max": max(trusts) if trusts else None,
        "next_actions": actions,
        "next_due": min(due_times) if due_times else None,
    }


def list_batches() -> list[dict]:
    with session_scope() as session:
        names = list(session.scalars(select(Batch.name).order_by(Batch.created_at, Batch.name)))
    return [batch_summary(name) for name in names]


def batch_next(ref: str) -> list[dict]:
    batch = get_batch(ref)
    if batch is None:
        raise ValueError(f"batch_not_found:{ref}")
    today_start = datetime.combine(datetime.now(timezone.utc).date(), time.min, tzinfo=timezone.utc)
    with session_scope() as session:
        accounts = session.scalars(select(Account).where(Account.batch_id == batch.id).order_by(Account.created_at)).all()
        rows = [_account_progress(session, account, today_start=today_start) for account in accounts]
    return [
        {
            "email": item.email,
            "stage": item.stage,
            "trust": item.trust,
            "last_session": item.last_session,
            "next_action": item.next_action,
            "due_at": item.due_at,
        }
        for item in rows
        if item.next_action not in ("idle",)
    ]


def status_snapshot() -> dict:
    today_start = datetime.combine(datetime.now(timezone.utc).date(), time.min, tzinfo=timezone.utc)
    with session_scope() as session:
        state_counts = dict(session.execute(select(Account.state, func.count()).group_by(Account.state)).all())
        pending = session.scalar(select(func.count()).select_from(WarmingTask).where(WarmingTask.status == "pending")) or 0
        done_today = session.scalar(
            select(func.count()).select_from(WarmingTask).where(
                WarmingTask.status == "done", WarmingTask.due_at >= today_start
            )
        ) or 0
        sessions = session.scalar(
            select(func.count()).select_from(WarmingSession).where(WarmingSession.started_at >= today_start)
        ) or 0
        actions = session.scalar(
            select(func.count()).select_from(ActionLog).where(ActionLog.ts >= today_start)
        ) or 0
        next_due = session.scalar(
            select(func.min(WarmingTask.due_at)).where(WarmingTask.status == "pending", WarmingTask.due_at > datetime.now(timezone.utc))
        )
    return {
        "states": state_counts,
        "pending_tasks": int(pending),
        "done_today": int(done_today),
        "sessions_today": int(sessions),
        "actions_today": int(actions),
        "next_due": next_due,
    }
