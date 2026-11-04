"""E-22: RAM pressure lowers concurrency instead of crashing the worker."""

from __future__ import annotations

import pytest

from core.governor import Governor


def test_E22_profile_cap_follows_ram(monkeypatch):
    import core.governor as gov

    monkeypatch.setattr(gov, "ram_gb", lambda: 4.0)
    g = Governor(max_profiles=8, ram_guard_pct=85, workers=8)
    assert g.max_profiles == 2  # min(8, 4GB / 2)
    assert g.workers <= 2


def test_E22_ram_pressure_shrinks_desired_concurrency(monkeypatch):
    import core.governor as gov

    monkeypatch.setattr(gov, "ram_gb", lambda: 16.0)
    g = Governor(max_profiles=8, ram_guard_pct=85, workers=8)
    monkeypatch.setattr(gov, "psutil", type("P", (), {"virtual_memory": staticmethod(lambda: type("M", (), {"percent": 92})())})())
    assert g.ram_pressure() is True
    assert g.desired_concurrency() == max(1, g.max_profiles // 2)
