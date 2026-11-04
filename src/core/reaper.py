"""Reaper: orphan browsers, stuck runs, expired locks, stale artifacts (E-24, E-25)."""

from __future__ import annotations

import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select, text, update

from core.lock import reap_stale_locks
from db.models import Account, AccountState, Profile, Run, RunState
from db.session import session_scope
from obs.log import get_logger

log = get_logger("reaper")

STUCK_RUN_MINUTES = 30


@dataclass
class ReapReport:
    stale_locks: int = 0
    stuck_runs: int = 0
    orphan_profiles: int = 0
    deleted_artifacts: int = 0
    freed_mb: float = 0.0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "stale_locks": self.stale_locks,
            "stuck_runs": self.stuck_runs,
            "orphan_profiles": self.orphan_profiles,
            "deleted_artifacts": self.deleted_artifacts,
            "freed_mb": round(self.freed_mb, 1),
            "errors": self.errors,
        }


def reap_stuck_runs(max_age_minutes: int = STUCK_RUN_MINUTES) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)
    with session_scope() as session:
        result = session.execute(
            update(Run)
            .where(Run.state == RunState.RUNNING.value, Run.started_at < cutoff)
            .values(state=RunState.FAILED.value, ended_at=datetime.now(timezone.utc))
        )
        count = result.rowcount or 0
    if count:
        log.warning("stuck_runs_reaped", count=count)
    return count


def reap_orphan_profiles(gpm, *, dry_run: bool = False) -> int:
    """Profiles in GPM with no ACTIVE/WARMING account and no open browser."""
    with session_scope() as session:
        linked = {p.gpm_profile_id for p in session.scalars(select(Profile)).all()}
        live = {
            p.gpm_profile_id
            for p in session.scalars(
                select(Profile).join(Account, Account.profile_id == Profile.id).where(
                    Account.state.in_((AccountState.ACTIVE.value, AccountState.WARMING.value))
                )
            ).all()
        }
    count = 0
    try:
        profiles = gpm.list_profiles()
    except Exception as exc:  # noqa: BLE001
        log.error("orphan_scan_failed", error=str(exc)[:200])
        return 0
    for profile in profiles:
        if profile.name.startswith("yf-") and profile.id not in live:
            if dry_run:
                count += 1
                continue
            try:
                gpm.stop_profile(profile.id)
                gpm.delete_profile(profile.id, hard=False)
                count += 1
            except Exception as exc:  # noqa: BLE001
                log.warning("orphan_delete_failed", profile_id=profile.id, error=str(exc)[:200])
    if count:
        log.warning("orphan_profiles_reaped", count=count, linked=len(linked))
    return count


def prune_artifacts(root: Path, days: int = 7) -> tuple[int, float]:
    if not root.exists():
        return 0, 0.0
    cutoff = time.time() - days * 86400
    deleted = 0
    freed = 0.0
    for path in root.rglob("*"):
        try:
            if path.is_file() and path.stat().st_mtime < cutoff:
                size = path.stat().st_size
                path.unlink()
                deleted += 1
                freed += size
        except OSError as exc:  # noqa: BLE001
            log.debug("artifact_prune_failed", path=str(path), error=str(exc))
    for directory in sorted(root.rglob("*"), reverse=True):
        if directory.is_dir() and not any(directory.iterdir()):
            shutil.rmtree(directory, ignore_errors=True)
    return deleted, freed / (1024**2)


def ensure_disk_space(root: Path, days: int = 7, min_free_gb: float = 2.0) -> bool:
    usage = shutil.disk_usage(root)
    if usage.free / (1024**3) >= min_free_gb:
        return True
    deleted, freed = prune_artifacts(root, days=days)
    log.warning("disk_pressure", deleted=deleted, freed_mb=round(freed, 1))
    return shutil.disk_usage(root).free / (1024**3) >= min_free_gb


def run_reaper(gpm=None, *, artifacts_root: Path | None = None, artifacts_days: int = 7) -> dict:
    report = ReapReport()
    try:
        report.stale_locks = reap_stale_locks()
        report.stuck_runs = reap_stuck_runs()
        if gpm is not None:
            report.orphan_profiles = reap_orphan_profiles(gpm)
        if artifacts_root is not None:
            report.deleted_artifacts, report.freed_mb = prune_artifacts(artifacts_root, days=artifacts_days)
    except Exception as exc:  # noqa: BLE001
        report.errors.append(str(exc)[:300])
        log.error("reaper_failed", error=str(exc)[:300])
    return report.as_dict()
