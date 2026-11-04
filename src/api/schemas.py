"""Admin API schemas (localhost only, bearer token)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    gpm_transport: str | None = None
    db: bool = False
    active_profiles: int = 0


class SignupRequest(BaseModel):
    count: int = Field(default=1, ge=1, le=500)
    city: str | None = None
    dry_run: bool = False


class ReportResponse(BaseModel):
    since: str
    accounts: dict[str, int]
    runs: dict[str, int]
    signups_ok: int
    signups_failed: int
    quarantine: dict[str, int]
    queue_depth: int


class QuarantineEntry(BaseModel):
    account_id: str
    code: str
    created_at: str
    evidence: dict[str, Any] = {}
