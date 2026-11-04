"""Per-account warming budgets (section 8.2) and the 429 penalty of 8.4."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

PHASE_DEFAULTS: dict[str, dict[str, int]] = {
    # phase: {kind: max actions per day}
    "P0": {"pageview": 8, "search": 4, "scroll": 20, "save": 0, "vote": 0, "follow": 0, "review": 0, "photo": 0, "checkin": 0},
    "P1": {"pageview": 8, "search": 4, "scroll": 20, "save": 3, "vote": 0, "follow": 0, "review": 0, "photo": 2, "checkin": 0},
    "P2": {"pageview": 8, "search": 4, "scroll": 20, "save": 3, "vote": 5, "follow": 2, "review": 0, "photo": 2, "checkin": 0},
    "P3": {"pageview": 8, "search": 4, "scroll": 20, "save": 3, "vote": 5, "follow": 2, "review": 1, "photo": 2, "checkin": 0},
    "P4": {"pageview": 10, "search": 5, "scroll": 30, "save": 4, "vote": 6, "follow": 2, "review": 1, "photo": 3, "checkin": 1},
}


def phase_for_day(day: int) -> str:
    if day <= 2:
        return "P0"
    if day <= 5:
        return "P1"
    if day <= 10:
        return "P2"
    if day <= 20:
        return "P3"
    return "P4"


@dataclass
class DailyBudget:
    budget: dict[str, Any]
    day_key: str = field(default_factory=lambda: date.today().isoformat())
    used: dict[str, int] = field(default_factory=dict)
    penalty_until: datetime | None = None
    penalty_ratio: float = 1.0

    @classmethod
    def for_phase(cls, phase: str, *, day: int = 1, overrides: dict[str, Any] | None = None) -> "DailyBudget":
        budget = dict(PHASE_DEFAULTS.get(phase, PHASE_DEFAULTS["P0"]))
        if overrides:
            budget.update(overrides)
        return cls(budget=budget, day_key=date.today().isoformat())

    def rollover(self, today: str | None = None) -> None:
        today = today or date.today().isoformat()
        if today != self.day_key:
            self.day_key = today
            self.used.clear()

    def effective_limit(self, kind: str) -> int:
        limit = int(self.budget.get(kind, 0))
        if limit == 0:
            return 0
        if self.penalty_until and datetime.now(timezone.utc) < self.penalty_until:
            return max(0, int(limit * 0.5))
        return limit

    def remaining(self, kind: str) -> int:
        return max(0, self.effective_limit(kind) - self.used.get(kind, 0))

    def allowed(self, kind: str) -> bool:
        return self.remaining(kind) > 0

    def consume(self, kind: str, amount: int = 1) -> bool:
        if self.remaining(kind) < amount:
            return False
        self.used[kind] = self.used.get(kind, 0) + amount
        return True

    def penalize(self, *, days: int = 3, ratio: float = 0.5) -> None:
        """429/403 twice in a row halves the budget for 3 days (8.4 / E-51)."""
        self.penalty_until = datetime.now(timezone.utc) + timedelta(days=days)
        self.penalty_ratio = ratio

    def to_json(self) -> dict[str, Any]:
        return {
            "budget": self.budget,
            "day": self.day_key,
            "used": self.used,
            "penalty_until": self.penalty_until.isoformat() if self.penalty_until else None,
        }

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> "DailyBudget":
        penalty = payload.get("penalty_until")
        return cls(
            budget=payload.get("budget", {}),
            day_key=payload.get("day", date.today().isoformat()),
            used=payload.get("used", {}),
            penalty_until=datetime.fromisoformat(penalty) if penalty else None,
        )
