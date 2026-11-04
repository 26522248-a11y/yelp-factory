from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core.budget import DailyBudget, PHASE_DEFAULTS, phase_for_day


def test_phase_mapping():
    assert phase_for_day(1) == "P0"
    assert phase_for_day(2) == "P0"
    assert phase_for_day(3) == "P1"
    assert phase_for_day(6) == "P2"
    assert phase_for_day(11) == "P3"
    assert phase_for_day(21) == "P4"


def test_budget_consumption():
    budget = DailyBudget.for_phase("P1")
    assert budget.allowed("save")
    assert budget.consume("save")
    budget.consume("save")
    budget.consume("save")
    assert not budget.allowed("save")


def test_zero_budget_actions_are_never_allowed():
    budget = DailyBudget.for_phase("P0")
    assert not budget.allowed("review")
    assert not budget.consume("review")


def test_429_penalty_halves_the_budget():
    budget = DailyBudget.for_phase("P2")
    assert budget.effective_limit("vote") == PHASE_DEFAULTS["P2"]["vote"]
    budget.penalize(days=3, ratio=0.5)
    assert budget.effective_limit("vote") == PHASE_DEFAULTS["P2"]["vote"] // 2


def test_penalty_expires():
    budget = DailyBudget.for_phase("P2")
    budget.penalize()
    budget.penalty_until = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert budget.effective_limit("vote") == PHASE_DEFAULTS["P2"]["vote"]


def test_day_rollover_resets_usage():
    budget = DailyBudget.for_phase("P2")
    budget.consume("vote", 2)
    budget.rollover("2999-01-01")
    assert budget.used == {}


def test_json_roundtrip():
    budget = DailyBudget.for_phase("P3")
    budget.consume("review")
    restored = DailyBudget.from_json(budget.to_json())
    assert restored.used == budget.used
    assert restored.budget == budget.budget
