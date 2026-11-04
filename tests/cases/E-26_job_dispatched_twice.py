"""E-26: the same job dispatched twice -> the second worker exits cleanly at the DB index."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from core.checkpoints import open_run
from db.session import session_scope

pytestmark = pytest.mark.usefixtures("db_ready")


def test_E26_second_running_run_is_rejected(make_account):
    account = make_account()
    first = open_run(account.id)
    assert first

    with pytest.raises(IntegrityError):
        open_run(account.id)

    with session_scope() as session:
        from db.models import Run, RunState

        session.query(Run).filter(Run.account_id == account.id).update({"state": RunState.FAILED.value})
