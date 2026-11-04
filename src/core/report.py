"""Reporting queries shared by the CLI and the admin API (acceptance #9)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from db.models import Account, Event, Quarantine, Run, RunState
from db.session import session_scope


def parse_window(value: str) -> datetime:
    value = (value or "24h").strip().lower()
    units = {"h": "hours", "d": "days", "m": "minutes"}
    if value[-1] in units and value[:-1].isdigit():
        return datetime.now(timezone.utc) - timedelta(**{units[value[-1]]: int(value[:-1])})
    if value.isdigit():
        return datetime.now(timezone.utc) - timedelta(hours=int(value))
    raise ValueError(f"unsupported window: {value}")


def build_report(since: str = "24h") -> dict:
    cutoff = parse_window(since)
    with session_scope() as session:
        account_rows = session.execute(
            select(Account.state, func.count()).group_by(Account.state)
        ).all()
        accounts = {state: count for state, count in account_rows}

        run_rows = session.execute(
            select(Run.state, func.count()).where(Run.started_at >= cutoff).group_by(Run.state)
        ).all()
        runs = {state: count for state, count in run_rows}

        quarantine_rows = session.execute(
            select(Quarantine.code, func.count()).where(Quarantine.created_at >= cutoff).group_by(Quarantine.code)
        ).all()
        quarantine = {code: count for code, count in quarantine_rows}

        queue_depth = session.execute(
            select(func.count()).select_from(Run).where(Run.state == RunState.PENDING.value)
        ).scalar_one()

    return {
        "since": since,
        "accounts": accounts,
        "runs": runs,
        "signups_ok": accounts.get("ACTIVE", 0) + accounts.get("WARMING", 0),
        "signups_failed": runs.get(RunState.FAILED.value, 0),
        "quarantine": quarantine,
        "queue_depth": int(queue_depth),
    }


def recent_events(limit: int = 100, code: str | None = None) -> list[dict]:
    with session_scope() as session:
        stmt = select(Event).order_by(Event.id.desc()).limit(limit)
        if code:
            stmt = stmt.where(Event.code == code)
        rows = session.scalars(stmt).all()
    return [
        {
            "id": row.id,
            "ts": row.ts.isoformat() if row.ts else None,
            "level": row.level,
            "code": row.code,
            "msg": row.msg,
            "account_id": str(row.account_id) if row.account_id else None,
        }
        for row in rows
    ]
