"""Idempotent profile creation on top of the GPM transport (E-20, E-25)."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import select

from adapters.base import GPMAdapter, GPMConflict, ProfileDTO
from adapters.gpm_http import GPMHttpClient
from db.models import GPMOperation
from db.session import session_scope
from obs.log import get_logger

log = get_logger("gpm_ops")


def payload_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def profile_name(account_id: str) -> str:
    return f"yf-{account_id}"


def ensure_profile(
    client: GPMAdapter,
    *,
    operation_id: str,
    name: str,
    create_kwargs: dict[str, Any],
) -> tuple[ProfileDTO, bool]:
    """Create the GPM profile exactly once per operation_id.

    Returns ``(profile, reused)``. If the process died between ``profiles/create`` and the
    bookkeeping insert, the profile is recovered by name instead of being duplicated.
    """
    digest = payload_hash({"name": name, **create_kwargs})

    with session_scope() as session:
        row = session.get(GPMOperation, operation_id)
        if row is not None:
            if row.payload_hash != digest:
                raise GPMConflict(
                    f"operation {operation_id} already used with a different payload",
                    meta={"operation_id": operation_id, "profile_id": row.gpm_profile_id},
                )
            try:
                return client.get_profile(row.gpm_profile_id), True
            except Exception:
                # Profile was deleted out-of-band; fall through and recreate.
                log.warning("gpm_operation_stale", operation_id=operation_id, profile_id=row.gpm_profile_id)
        else:
            existing = [p for p in client.list_profiles() if p.name == name]
            if existing:
                session.add(
                    GPMOperation(
                        operation_id=operation_id,
                        payload_hash=digest,
                        gpm_profile_id=existing[0].id,
                        payload={"name": name, **create_kwargs},
                    )
                )
                return existing[0], True

    profile = client.create_profile(name=name, **create_kwargs)

    with session_scope() as session:
        session.merge(
            GPMOperation(
                operation_id=operation_id,
                payload_hash=digest,
                gpm_profile_id=profile.id,
                payload={"name": name, **create_kwargs},
            )
        )
    log.info("gpm_profile_created", operation_id=operation_id, profile_id=profile.id)
    return profile, False


def make_client(settings=None, **kwargs: Any) -> GPMHttpClient:
    from core.config import get_settings

    cfg = (settings or get_settings()).gpm
    return GPMHttpClient(
        base_url=kwargs.pop("base_url", cfg.base_url),
        flavor=cfg.flavor,
        timeout=kwargs.pop("timeout", cfg.connect_timeout_s),
        **kwargs,
    )
