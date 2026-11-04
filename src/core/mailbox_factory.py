"""Per-account mailbox providers (pool emails rotate their own refresh token)."""

from __future__ import annotations

import uuid

from adapters.email import EmailProvider, GraphMailbox
from core.config import Settings
from core.crypto import SecretBox
from core.pool import email_credentials, store_rotated_token
from db.models import Account, EmailPool
from db.session import session_scope
from obs.log import get_logger

log = get_logger("mailbox_factory")


def provider_for_account(account: Account, settings: Settings, *, fallback: EmailProvider | None = None) -> EmailProvider:
    if not account.email_pool_id:
        if fallback is None:
            raise RuntimeError("no mailbox provider for account")
        return fallback

    with session_scope() as session:
        row = session.get(EmailPool, account.email_pool_id)
        if row is None:
            if fallback is None:
                raise RuntimeError("pool email missing")
            return fallback
        credentials = email_credentials(row)
        email_id = row.id

    def persist(token: str) -> None:
        try:
            store_rotated_token(email_id, token, SecretBox())
        except Exception as exc:  # noqa: BLE001
            log.warning("pool_token_persist_failed", error=str(exc)[:150])

    return GraphMailbox(
        credentials["client_id"],
        credentials["refresh_token"],
        tenant=settings.email.graph_tenant,
        on_token_refresh=persist,
    )
