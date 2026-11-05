"""Warming scheduler: builds daily plans and runs due sessions inside local hours.

Section 8.1: 1-3 sessions per day, 4-12 minutes each, only between 06:00 and 23:00 in the
account's city timezone. Plans live in ``warming_plans``/``warming_tasks`` so a restart does
not lose the day's schedule.
"""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from core.budget import DailyBudget, phase_for_day
from db.models import Account, AccountState, WarmingPlan, WarmingTask
from db.session import session_scope
from flows.warmup import WarmingTaskSpec, build_day_tasks
from human.timing import within_working_hours
from obs.log import get_logger

log = get_logger("scheduler")

MAX_SESSIONS_PER_DAY = 3


@dataclass(slots=True)
class DueSession:
    account_id: uuid.UUID
    task_id: uuid.UUID
    city: str
    phase: str


def ensure_plan(account_id: uuid.UUID, *, city: str, day: int) -> uuid.UUID:
    with session_scope() as session:
        plan = session.scalars(
            select(WarmingPlan).where(WarmingPlan.account_id == account_id).order_by(WarmingPlan.day.desc())
        ).first()
        if plan is None:
            phase = phase_for_day(day)
            plan = WarmingPlan(
                account_id=account_id,
                phase=int(phase[1]),
                day=day,
                budget=DailyBudget.for_phase(phase).to_json(),
                status="active",
            )
            session.add(plan)
            session.flush()
        plan.day = day
        plan.phase = int(phase_for_day(day)[1])
        return plan.id


def enqueue_day(account_id: uuid.UUID, *, city: str, day: int, rng: random.Random | None = None) -> int:
    """Create today's tasks once. Returns how many were inserted."""
    if rng is None:
        # Deterministic per (account, day) so a retry never duplicates the plan.
        seed = int(uuid.uuid5(uuid.NAMESPACE_URL, f"{account_id}:{day}").hex[:12], 16)
        rng = random.Random(seed)
    # One rest day per week (every 7th day), deterministic and easy to audit.
    if day > 1 and day % 7 == 0:
        log.info("warming_rest_day", account_id=str(account_id), day=day)
        return 0
    plan_id = ensure_plan(account_id, city=city, day=day)
    specs: list[WarmingTaskSpec] = build_day_tasks(account_id, day, city=city, rng=rng)
    inserted = 0
    with session_scope() as session:
        existing = session.scalars(
            select(WarmingTask).where(
                WarmingTask.plan_id == plan_id,
                WarmingTask.due_at >= datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0),
            )
        ).all()
        seen = [(task.kind, task.due_at) for task in existing]
        for spec in specs:
            key = (spec.kind, spec.due_at)
            if key in seen:
                continue
            session.add(
                WarmingTask(
                    plan_id=plan_id,
                    kind=spec.kind,
                    due_at=spec.due_at,
                    status="pending",
                    result=spec.meta,
                )
            )
            inserted += 1
    if inserted:
        log.info("warming_plan_created", account_id=str(account_id), day=day, tasks=inserted)
    return inserted


def due_sessions(now: datetime | None = None, *, limit: int = 8) -> list[DueSession]:
    now = now or datetime.now(timezone.utc)
    sessions: list[DueSession] = []
    seen_proxies: set[str] = set()
    with session_scope() as session:
        rows = session.execute(
            select(WarmingTask, WarmingPlan, Account)
            .join(WarmingPlan, WarmingPlan.id == WarmingTask.plan_id)
            .join(Account, Account.id == WarmingPlan.account_id)
            .where(WarmingTask.kind == "session", WarmingTask.status == "pending", WarmingTask.due_at <= now)
            .order_by(WarmingTask.due_at)
            .limit(limit * 3)
        ).all()
        candidates = [(task, plan, account) for task, plan, account in rows]

    from core.batches import paused_batch_ids
    from core.trust import latest_trust
    from db.models import WarmingSession

    paused = paused_batch_ids()

    for task, plan, account in candidates:
        if len(sessions) >= limit:
            break
        if account.state not in (AccountState.ACTIVE.value, AccountState.WARMING.value):
            continue
        if account.batch_id is not None and account.batch_id in paused:
            continue
        if not within_working_hours(account.city or "Austin, TX"):
            continue
        # Minimum 90 minutes between sessions of the same account (spec 3).
        with session_scope() as session:
            last = session.scalars(
                select(WarmingSession)
                .where(WarmingSession.account_id == account.id, WarmingSession.ended_at.isnot(None))
                .order_by(WarmingSession.ended_at.desc())
                .limit(1)
            ).first()
            last_end = last.ended_at if last else None
        if last_end is not None:
            elapsed = (now - last_end).total_seconds()
            if elapsed < 90 * 60:
                continue
        # Very low trust (risk events) pauses sessions; normal gating happens per action
        # inside the session (trust < 40 => browse only).
        proxy_key = getattr(account, "proxy_ip", None) or f"acc:{account.id}"
        if proxy_key in seen_proxies:
            continue
        seen_proxies.add(proxy_key)
        sessions.append(
            DueSession(
                account_id=account.id,
                task_id=task.id,
                city=account.city or "Austin, TX",
                phase=f"P{plan.phase}",
            )
        )
    return sessions


def mark_task(task_id: uuid.UUID, status: str = "done", result: dict[str, Any] | None = None) -> None:
    with session_scope() as session:
        task = session.get(WarmingTask, task_id)
        if task is None:
            return
        task.status = status
        task.attempts = (task.attempts or 0) + 1
        task.result = {**(task.result or {}), **(result or {})}


def sessions_used_today(account_id: uuid.UUID) -> int:
    start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    with session_scope() as session:
        return len(
            session.scalars(
                select(WarmingTask)
                .join(WarmingPlan, WarmingPlan.id == WarmingTask.plan_id)
                .where(
                    WarmingPlan.account_id == account_id,
                    WarmingTask.kind == "session",
                    WarmingTask.status == "done",
                    WarmingTask.due_at >= start,
                )
            ).all()
        )


def daily_plan_day(account_id: uuid.UUID) -> int:
    """Day counter since the account was created (1-based)."""
    with session_scope() as session:
        account = session.get(Account, account_id)
    if account is None or account.created_at is None:
        return 1
    created = account.created_at.date()
    return max(1, (date.today() - created).days + 1)


def bootstrap(limit_accounts: int = 200) -> dict[str, int]:
    """Ensure every ACTIVE/WARMING account has a plan for today (paused batches excluded)."""
    from core.batches import paused_batch_ids

    created = 0
    paused = paused_batch_ids()
    with session_scope() as session:
        accounts = session.scalars(
            select(Account)
            .where(Account.state.in_((AccountState.ACTIVE.value, AccountState.WARMING.value)))
            .limit(limit_accounts)
        ).all()
        rows = [(a.id, a.city, a.batch_id) for a in accounts if a.batch_id is None or a.batch_id not in paused]
    for account_id, city, _batch_id in rows:
        day = daily_plan_day(account_id)
        if enqueue_day(account_id, city=city or "Austin, TX", day=day):
            created += 1
    return {"accounts": len(rows), "planned": created}


async def run_due(deps, *, limit: int = 8, max_seconds: int = 480) -> dict[str, Any]:
    from core.orchestrator import run_warm

    sessions = due_sessions(limit=limit)
    results = []
    for item in sessions:
        if sessions_used_today(item.account_id) >= MAX_SESSIONS_PER_DAY:
            mark_task(item.task_id, "skipped", {"reason": "daily_cap"})
            continue
        try:
            outcome = await run_warm(item.account_id, deps, sessions=1, max_seconds=max_seconds)
            mark_task(item.task_id, "done", {"actions": outcome.get("sessions", [{}])[0].get("actions", [])})
            results.append({"account": str(item.account_id), "ok": True})
        except Exception as exc:  # noqa: BLE001
            mark_task(item.task_id, "failed", {"error": str(exc)[:300]})
            results.append({"account": str(item.account_id), "ok": False, "error": str(exc)[:200]})
            log.error("warming_session_failed", account_id=str(item.account_id), error=str(exc)[:200])
    return {"due": len(sessions), "results": results}


async def scheduler_loop(deps, *, interval_s: int = 300, max_seconds: int = 480) -> None:
    import asyncio

    while True:
        try:
            bootstrap()
            summary = await run_due(deps, max_seconds=max_seconds)
            log.info("scheduler_tick", **{k: v for k, v in summary.items() if k != "results"})
        except Exception as exc:  # noqa: BLE001
            log.error("scheduler_tick_failed", error=str(exc)[:300])
        await asyncio.sleep(interval_s)
