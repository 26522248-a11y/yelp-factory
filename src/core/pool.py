"""Email/proxy pool storage and allocation (spec v1.1)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import case, func, select, text

from core.crypto import SecretBox
from core.importers import ParsedEmail, ParsedProxy
from db.models import Account, EmailPool, ProxyPool
from db.session import session_scope
from obs.log import get_logger

log = get_logger("pool")

DEFAULT_MAX_PER_PROXY = 2


# --------------------------------------------------------------------------- import


def import_emails(rows: Iterable[ParsedEmail], *, source_file: str = "", box: SecretBox | None = None) -> dict:
    box = box or SecretBox()
    inserted = 0
    with session_scope() as session:
        for row in rows:
            session.add(
                EmailPool(
                    mailbox_email=row.mailbox_email,
                    mailbox_password_enc=box.encrypt(row.mailbox_password),
                    refresh_token_enc=box.encrypt(row.refresh_token),
                    client_id=row.client_id,
                    alias=row.alias,
                    domain=row.alias.split("@")[-1],
                    status="available",
                    source_file=source_file,
                )
            )
            inserted += 1
    log.info("emails_imported", count=inserted, file=source_file)
    return {"inserted": inserted}


def import_proxies(rows: Iterable[ParsedProxy], *, source_file: str = "", box: SecretBox | None = None) -> dict:
    box = box or SecretBox()
    inserted = 0
    with session_scope() as session:
        for row in rows:
            session.add(
                ProxyPool(
                    raw=row.raw,
                    host=row.host,
                    port=row.port,
                    username=row.username,
                    password_enc=box.encrypt(row.password),
                    status="available",
                    source_file=source_file,
                )
            )
            inserted += 1
    log.info("proxies_imported", count=inserted, file=source_file)
    return {"inserted": inserted}


# --------------------------------------------------------------------------- allocation


def reserve_email(account_id: uuid.UUID) -> EmailPool | None:
    """Atomically reserve one available mailbox for an account (P-09)."""
    now = datetime.now(timezone.utc)
    with session_scope() as session:
        row = session.execute(
            select(EmailPool)
            .where(EmailPool.status == "available")
            .order_by(EmailPool.imported_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        ).scalar_one_or_none()
        if row is None:
            return None
        row.status = "reserved"
        row.reserved_by = account_id
        row.reserved_at = now
        session.flush()
        session.expunge(row)
        return row


def reserve_proxy(account_id: uuid.UUID, *, max_per_proxy: int = DEFAULT_MAX_PER_PROXY) -> ProxyPool | None:
    now = datetime.now(timezone.utc)
    with session_scope() as session:
        row = session.execute(
            select(ProxyPool)
            .where(
                ProxyPool.status.in_(("available", "reserved", "used")),
                ProxyPool.accounts_count < max_per_proxy,
            )
            # Spread load: brand-new proxies first, then proxies already carrying accounts.
            .order_by(
                ProxyPool.accounts_count,
                case((ProxyPool.status == "available", 0), else_=1),
                ProxyPool.imported_at,
            )
            .with_for_update(skip_locked=True)
            .limit(1)
        ).scalar_one_or_none()
        if row is None:
            return None
        row.status = "reserved"
        row.reserved_by = account_id
        row.reserved_at = now
        session.flush()
        session.expunge(row)
        return row


def commit_email(email_id: uuid.UUID) -> None:
    with session_scope() as session:
        row = session.get(EmailPool, email_id)
        if row is not None:
            row.status = "used"
            row.reserved_by = None
            row.reserved_at = None


def release_email(email_id: uuid.UUID, *, error: str | None = None) -> None:
    with session_scope() as session:
        row = session.get(EmailPool, email_id)
        if row is not None and row.status == "reserved":
            row.status = "available"
            row.reserved_by = None
            row.reserved_at = None
            if error:
                row.last_error = error[:300]


def commit_proxy(proxy_id: uuid.UUID) -> None:
    with session_scope() as session:
        row = session.get(ProxyPool, proxy_id)
        if row is not None:
            row.accounts_count = (row.accounts_count or 0) + 1
            row.status = "used"
            row.reserved_by = None
            row.reserved_at = None


def release_proxy(proxy_id: uuid.UUID, *, mark_dead: bool = False) -> None:
    with session_scope() as session:
        row = session.get(ProxyPool, proxy_id)
        if row is None:
            return
        row.reserved_by = None
        row.reserved_at = None
        if mark_dead:
            row.status = "dead"
        else:
            row.status = "used" if (row.accounts_count or 0) > 0 else "available"


def proxy_raw(proxy: ProxyPool, box: SecretBox | None = None) -> str:
    box = box or SecretBox()
    password = box.decrypt(proxy.password_enc) if proxy.password_enc else ""
    return f"{proxy.host}:{proxy.port}:{proxy.username}:{password}"


def email_credentials(email: EmailPool, box: SecretBox | None = None) -> dict:
    box = box or SecretBox()
    return {
        "mailbox_email": email.mailbox_email,
        "password": box.decrypt(email.mailbox_password_enc) if email.mailbox_password_enc else "",
        "refresh_token": box.decrypt(email.refresh_token_enc) if email.refresh_token_enc else "",
        "client_id": email.client_id,
        "alias": email.alias,
    }


def store_rotated_token(email_id: uuid.UUID, refresh_token: str, box: SecretBox | None = None) -> None:
    box = box or SecretBox()
    with session_scope() as session:
        row = session.get(EmailPool, email_id)
        if row is not None:
            row.refresh_token_enc = box.encrypt(refresh_token)


# --------------------------------------------------------------------------- reporting


def stats() -> dict:
    with session_scope() as session:
        email_counts = dict(
            session.execute(select(EmailPool.status, func.count()).group_by(EmailPool.status)).all()
        )
        proxy_counts = dict(
            session.execute(select(ProxyPool.status, func.count()).group_by(ProxyPool.status)).all()
        )
        usable_emails = email_counts.get("available", 0)
        usable_proxies = session.scalar(
            select(func.count()).select_from(ProxyPool).where(
                ProxyPool.status.in_(("available", "used")), ProxyPool.accounts_count < DEFAULT_MAX_PER_PROXY
            )
        )
    return {
        "emails": email_counts,
        "proxies": proxy_counts,
        "available_emails": usable_emails,
        "available_proxies": int(usable_proxies or 0),
    }


def assign_to_account(account_id: uuid.UUID, *, email_id: uuid.UUID | None, proxy_id: uuid.UUID | None) -> None:
    with session_scope() as session:
        account = session.get(Account, account_id)
        if account is None:
            return
        if email_id:
            account.email_pool_id = email_id
        if proxy_id:
            account.proxy_pool_id = proxy_id
