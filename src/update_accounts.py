"""Assign avatars from the scraped pool to the successful accounts and clean test rows."""

from __future__ import annotations

import shutil
from pathlib import Path

from db.models import Account, AccountLock, ActionLog, Quarantine, ReviewAttempt, Run, Step, TrustScore, WarmingPlan, WarmingSession, WarmingTask
from db.session import session_scope
from flows.avatar_sources import pick_from_pool, refill_pool
from sqlalchemy import delete

SUCCESS = {"ACTIVE", "WARMING", "ONBOARDED"}


def remove_test_accounts(session) -> int:
    ids = [a.id for a in session.query(Account).filter(Account.email.like("test%@fviainboxes.com")).all()]
    if not ids:
        return 0
    session.execute(delete(ReviewAttempt).where(ReviewAttempt.account_id.in_(ids)))
    session.execute(delete(ActionLog).where(ActionLog.account_id.in_(ids)))
    session.execute(delete(TrustScore).where(TrustScore.account_id.in_(ids)))
    session.execute(delete(WarmingSession).where(WarmingSession.account_id.in_(ids)))
    plan_ids = [p.id for p in session.query(WarmingPlan).filter(WarmingPlan.account_id.in_(ids)).all()]
    if plan_ids:
        session.execute(delete(WarmingTask).where(WarmingTask.plan_id.in_(plan_ids)))
        session.execute(delete(WarmingPlan).where(WarmingPlan.id.in_(plan_ids)))
    run_ids = [r.id for r in session.query(Run).filter(Run.account_id.in_(ids)).all()]
    if run_ids:
        session.execute(delete(Step).where(Step.run_id.in_(run_ids)))
        session.execute(delete(Run).where(Run.account_id.in_(ids)))
    session.execute(delete(Quarantine).where(Quarantine.account_id.in_(ids)))
    session.execute(delete(AccountLock).where(AccountLock.account_id.in_(ids)))
    session.execute(delete(Account).where(Account.id.in_(ids)))
    return len(ids)


def main() -> None:
    import asyncio

    asyncio.run(refill_pool(wanted=4))
    artifacts = Path("artifacts")
    artifacts.mkdir(exist_ok=True)
    assigned = []
    with session_scope() as session:
        removed = remove_test_accounts(session)
        accounts = session.query(Account).filter(Account.state.in_(tuple(SUCCESS))).all()
        used = set()
        for account in accounts:
            source = None
            for _ in range(5):
                candidate = pick_from_pool()
                if candidate is None:
                    break
                if candidate.name not in used:
                    source = candidate
                    break
            if source is None:
                continue
            dest = artifacts / f"avatar_{account.id}.jpg"
            shutil.copyfile(source, dest)
            account.avatar_path = str(dest)
            used.add(source.name)
            assigned.append({"email": account.email, "avatar": str(dest), "source": source.name})
    print({"removed_test_accounts": removed, "assigned": assigned})


if __name__ == "__main__":
    main()
