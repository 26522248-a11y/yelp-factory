"""Pool API endpoints (dry-run, no writes against real data)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.admin import create_app
from core.config import get_settings

pytestmark = pytest.mark.usefixtures("db_ready", "isolate_pool")


def client() -> TestClient:
    return TestClient(create_app())


def auth() -> dict:
    return {"Authorization": f"Bearer {get_settings().admin_token}"}


def test_pool_stats_requires_auth():
    assert client().get("/api/pool").status_code == 401


def test_pool_stats_ok():
    response = client().get("/api/pool", headers=auth())
    assert response.status_code == 200
    assert "available_emails" in response.json()


def test_import_emails_dry_run_validates():
    text = "a@b.com|pw|" + "M.C" + "x" * 40 + "|client|a@fviainboxes.com\nbadline"
    response = client().post(
        "/api/pool/import",
        headers=auth(),
        json={"kind": "emails", "text": text, "dry_run": True},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["valid"] == 1
    assert body["invalid"] == 1
    assert body["errors"][0]["line"] == 2


def test_import_proxies_dry_run():
    response = client().post(
        "/api/pool/import",
        headers=auth(),
        json={"kind": "proxies", "text": "1.2.3.4:8080:user:pass", "dry_run": True},
    )
    assert response.status_code == 200
    assert response.json()["valid"] == 1


def test_unknown_kind_rejected():
    response = client().post("/api/pool/import", headers=auth(), json={"kind": "other", "text": "x"})
    assert response.status_code == 400
