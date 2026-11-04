"""Pool allocation: reservation, max-2-per-proxy, commit/release, exhaustion."""

from __future__ import annotations

import uuid

import pytest

from core.importers import ParsedEmail, ParsedProxy
from core.pool import (
    commit_email,
    commit_proxy,
    import_emails,
    import_proxies,
    proxy_raw,
    release_email,
    release_proxy,
    reserve_email,
    reserve_proxy,
    stats,
)

pytestmark = pytest.mark.usefixtures("db_ready", "isolate_pool", "clean_pool")

TOKEN = "M.C524." + "x" * 40


def _email(alias: str) -> ParsedEmail:
    return ParsedEmail(
        mailbox_email=f"{alias}@hotmail.com",
        mailbox_password="pw",
        refresh_token=TOKEN,
        client_id="client",
        alias=f"{alias}@fviainboxes.com",
    )


def _proxy(host: str) -> ParsedProxy:
    return ParsedProxy(raw=f"{host}:8000:user:pw", host=host, port=8000, username="user", password="pw")


def test_p09_reservation_is_exclusive(db_ready):
    import_emails([_email(f"p09{uuid.uuid4().hex[:6]}")])
    a = reserve_email(uuid.uuid4())
    b = reserve_email(uuid.uuid4())
    assert a is not None
    # Only one row was imported, so the second reservation must fail.
    assert b is None
    release_email(a.id)


def test_commit_email_marks_used():
    alias = f"c{uuid.uuid4().hex[:6]}"
    import_emails([_email(alias)])
    row = reserve_email(uuid.uuid4())
    commit_email(row.id)
    assert stats()["emails"].get("used", 0) >= 1


def test_release_email_returns_to_available():
    alias = f"r{uuid.uuid4().hex[:6]}"
    import_emails([_email(alias)])
    row = reserve_email(uuid.uuid4())
    release_email(row.id)
    assert stats()["emails"].get("available", 0) >= 1


def test_p12_proxy_max_two_accounts():
    host = f"10.0.{uuid.uuid4().int % 250}.{uuid.uuid4().int % 250}"
    import_proxies([_proxy(host)])
    first = reserve_proxy(uuid.uuid4())
    assert first is not None
    commit_proxy(first.id)
    second = reserve_proxy(uuid.uuid4())
    assert second is not None
    commit_proxy(second.id)
    third = reserve_proxy(uuid.uuid4())
    assert third is None


def test_proxy_raw_decrypts_password():
    host = f"10.9.{uuid.uuid4().int % 250}.{uuid.uuid4().int % 250}"
    import_proxies([_proxy(host)])
    row = reserve_proxy(uuid.uuid4())
    raw = proxy_raw(row)
    assert raw.endswith(":pw")
    release_proxy(row.id)


def test_stats_shape():
    payload = stats()
    assert {"emails", "proxies", "available_emails", "available_proxies"} <= set(payload)
