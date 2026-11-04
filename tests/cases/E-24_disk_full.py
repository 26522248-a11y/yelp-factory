"""E-24: disk below 2 GB -> old artifacts are pruned before the flow continues."""

from __future__ import annotations

import os
import time

from core.reaper import ensure_disk_space, prune_artifacts


def test_E24_old_artifacts_are_deleted(tmp_path):
    old = tmp_path / "old.png"
    old.write_bytes(b"x" * 2048)
    fresh = tmp_path / "fresh.png"
    fresh.write_bytes(b"y" * 1024)
    eight_days = time.time() - 8 * 86400
    os.utime(old, (eight_days, eight_days))

    deleted, freed_mb = prune_artifacts(tmp_path, days=7)
    assert deleted == 1
    assert not old.exists()
    assert fresh.exists()
    assert freed_mb >= 0


def test_E24_ensure_disk_space_true_when_plenty(tmp_path):
    assert ensure_disk_space(tmp_path, min_free_gb=0.0001) is True
