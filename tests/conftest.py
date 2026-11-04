"""Shared fixtures: settings, DNS-free defaults, in-memory fakes."""

from __future__ import annotations

import base64
import os
import uuid

import pytest

os.environ.setdefault("YF_MASTER_KEY", base64.urlsafe_b64encode(b"0" * 32).decode())

from core.config import Settings, load_settings  # noqa: E402
from human.timing import session_length_seconds  # noqa: E402
from obs.log import configure_logging  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _logging():
    configure_logging("WARNING", json_output=True)


@pytest.fixture()
def settings() -> Settings:
    cfg = load_settings()
    cfg.email.provider = "fake"
    cfg.captcha.providers = []
    cfg.captcha.human_in_loop = False
    cfg.gpm.mcp_url = ""
    cfg.gpm.base_url = "http://127.0.0.1:9"
    return cfg


@pytest.fixture()
def fake_page_factory():
    from tests.fakes import FakePage

    def make(url: str = "https://www.yelp.com/signup", html: str = "") -> FakePage:
        return FakePage(url=url, html=html)

    return make


@pytest.fixture()
def fake_browser():
    from tests.fakes import FakeBrowser

    return FakeBrowser()


@pytest.fixture()
def account_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture()
def run_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture()
def clean_pool(db_ready):
    """Remove pool rows created by tests (imported without a source file)."""
    yield
    from sqlalchemy import delete, or_

    from db.models import EmailPool, ProxyPool
    from db.session import session_scope

    with session_scope() as session:
        session.execute(delete(EmailPool).where(or_(EmailPool.source_file.is_(None), EmailPool.source_file == "")))
        session.execute(delete(ProxyPool).where(or_(ProxyPool.source_file.is_(None), ProxyPool.source_file == "")))


@pytest.fixture()
def isolate_pool(db_ready):
    """Park real pool rows as 'disabled' so allocation tests only see their own rows."""
    from db.models import EmailPool, ProxyPool
    from db.session import session_scope

    saved = {"email": [], "proxy": []}
    with session_scope() as session:
        for row in session.query(EmailPool).all():
            saved["email"].append((row.id, row.status))
            row.status = "disabled"
        for row in session.query(ProxyPool).all():
            saved["proxy"].append((row.id, row.status))
            row.status = "disabled"
    yield
    with session_scope() as session:
        for row_id, status in saved["email"]:
            row = session.get(EmailPool, row_id)
            if row is not None:
                row.status = status
        for row_id, status in saved["proxy"]:
            row = session.get(ProxyPool, row_id)
            if row is not None:
                row.status = status


def pytest_configure(config):
    config.addinivalue_line("markers", "db: requires a live Postgres")


# --------------------------------------------------------------------------- DB fixtures


@pytest.fixture()
def db_ready():
    """Skip DB tests when Postgres is not reachable (default in CI without a DB)."""
    import pytest as _pytest

    from db.session import session_scope

    try:
        with session_scope():
            pass
    except Exception as exc:  # noqa: BLE001
        _pytest.skip(f"postgres unavailable: {exc}")


@pytest.fixture()
def make_account(db_ready):
    import uuid as _uuid

    from core.crypto import SecretBox
    from db.models import Account, AccountState
    from db.session import session_scope

    created: list[_uuid.UUID] = []

    def factory(*, state: AccountState = AccountState.NEW, city: str = "Delray Beach, FL", zip_code: str = "33444") -> Account:
        box = SecretBox()
        with session_scope() as session:
            account = Account(
                email=f"test{_uuid.uuid4().hex[:10]}@fviainboxes.com",
                email_alias="alias@fviainboxes.com",
                first_name="Test",
                last_name="User",
                zip=zip_code,
                city=city,
                password_enc=box.encrypt("Sup3rSecret!x"),
                state=state.value,
            )
            session.add(account)
            session.flush()
            created.append(account.id)
            session.expunge(account)
            return account

    yield factory

    from sqlalchemy import delete

    from db.models import (
        Account,
        AccountLock,
        ActionLog,
        Quarantine,
        ReviewAttempt,
        Run,
        Step,
        TrustScore,
        WarmingPlan,
        WarmingSession,
        WarmingTask,
    )

    with session_scope() as session:
        if created:
            session.execute(delete(ReviewAttempt).where(ReviewAttempt.account_id.in_(created)))
            session.execute(delete(ActionLog).where(ActionLog.account_id.in_(created)))
            session.execute(delete(TrustScore).where(TrustScore.account_id.in_(created)))
            session.execute(delete(WarmingSession).where(WarmingSession.account_id.in_(created)))
            session.execute(delete(WarmingTask).where(WarmingTask.plan_id.in_(select_plan_ids(created))))
            session.execute(delete(WarmingPlan).where(WarmingPlan.account_id.in_(created)))
            session.execute(delete(Step).where(Step.run_id.in_(select_run_ids(created))))
            session.execute(delete(Run).where(Run.account_id.in_(created)))
            session.execute(delete(Quarantine).where(Quarantine.account_id.in_(created)))
            session.execute(delete(AccountLock).where(AccountLock.account_id.in_(created)))
            session.execute(delete(Account).where(Account.id.in_(created)))


def select_plan_ids(account_ids):
    from sqlalchemy import select

    from db.models import WarmingPlan
    from db.session import session_scope

    with session_scope() as session:
        return list(session.scalars(select(WarmingPlan.id).where(WarmingPlan.account_id.in_(account_ids))).all())


def select_run_ids(account_ids):
    from sqlalchemy import select

    from db.models import Run
    from db.session import session_scope

    with session_scope() as session:
        return list(session.scalars(select(Run.id).where(Run.account_id.in_(account_ids))).all())
