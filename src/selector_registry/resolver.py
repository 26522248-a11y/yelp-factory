"""Selector registry resolver (section 19, E-30/E-42/E-46/E-54)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml

from adapters.base import SelectorMiss
from obs.log import get_logger
from obs.metrics import selector_miss_total

log = get_logger("selectors")

REGISTRY_PATH = Path(__file__).with_name("registry.yaml")
MISS_ALERT_THRESHOLD = 20  # misses per hour before E-54 fires


@dataclass(frozen=True, slots=True)
class SelectorRule:
    strategy: str
    value: str
    priority: int = 1

    def as_locator(self) -> tuple[str, str]:
        strategy = self.strategy
        if strategy == "css":
            return "css", self.value
        if strategy == "xpath":
            return "xpath", self.value
        if strategy == "label":
            return "label", self.value
        if strategy == "name":
            return "css", f"[name='{self.value}']"
        if strategy == "placeholder":
            return "placeholder", self.value
        if strategy == "text":
            return "text", self.value
        if strategy == "role":
            return "role", self.value
        return "css", self.value


class SelectorRegistry:
    def __init__(self, rules: dict[str, list[SelectorRule]] | None = None):
        self.rules = rules or {}

    @classmethod
    def from_yaml(cls, path: Path | str = REGISTRY_PATH) -> "SelectorRegistry":
        path = Path(path)
        if not path.exists():
            return cls({})
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        rules: dict[str, list[SelectorRule]] = {}
        for key, entries in raw.items():
            parsed = []
            for entry in entries or []:
                parsed.append(
                    SelectorRule(
                        strategy=str(entry.get("strategy", "css")),
                        value=str(entry.get("value", "")),
                        priority=int(entry.get("priority", 1)),
                    )
                )
            rules[key] = sorted(parsed, key=lambda rule: rule.priority)
        return cls(rules)

    def keys(self) -> list[str]:
        return sorted(self.rules)

    def rules_for(self, key: str, page_tag: str | None = None) -> list[SelectorRule]:
        base = self.rules.get(key, [])
        if page_tag:
            tagged = self.rules.get(f"{key}@{page_tag}", [])
            if tagged:
                return tagged + base
        return base

    # ------------------------------------------------------------------ resolution

    async def find(self, page, key: str, *, page_tag: str | None = None, timeout_ms: int = 5000, required: bool = True):
        for rule in self.rules_for(key, page_tag):
            strategy, value = rule.as_locator()
            locator = getattr(page, "get_by_label", None)
            try:
                if strategy == "css":
                    candidate = page.locator(value).first
                elif strategy == "xpath":
                    candidate = page.locator(f"xpath={value}").first
                elif strategy == "label":
                    candidate = page.get_by_label(value, exact=False).first
                elif strategy == "placeholder":
                    candidate = page.get_by_placeholder(value, exact=False).first
                elif strategy == "text":
                    candidate = page.get_by_text(value, exact=False).first
                elif strategy == "role":
                    candidate = page.get_by_role(value).first
                else:
                    candidate = page.locator(value).first
                if await candidate.count() and await candidate.is_visible(timeout=timeout_ms):
                    log.debug("selector_hit", key=key, strategy=strategy, value=value)
                    return candidate
            except Exception as exc:  # noqa: BLE001
                log.debug("selector_rule_failed", key=key, strategy=strategy, error=str(exc)[:120])
        selector_miss_total.labels(key=key).inc()
        log.warning("selector_miss", key=key, page_tag=page_tag)
        if required:
            raise SelectorMiss(f"no selector matched for '{key}'", meta={"key": key, "page_tag": page_tag})
        return None

    async def fill(self, page, key: str, value: str, **kwargs: Any) -> bool:
        element = await self.find(page, key, **kwargs)
        if element is None:
            return False
        await element.fill(value)
        return True

    async def click(self, page, key: str, *, force_after: int = 2, **kwargs: Any):
        element = await self.find(page, key, **kwargs)
        if element is None:
            return False
        for attempt in range(force_after + 1):
            try:
                await element.click(timeout=5000, force=attempt >= force_after)
                return True
            except Exception as exc:  # noqa: BLE001
                # E-40: an overlay can swallow the click; force only after two clean failures.
                log.warning("click_retry", key=key, attempt=attempt, error=str(exc)[:160])
        return False


FIELD_HINTS = {
    "zip": ("zip", "postal", "postcode"),
    "city": ("city", "town", "locality"),
    "phone": ("phone", "mobile", "tel"),
    "first_name": ("first", "given"),
    "last_name": ("last", "surname", "family"),
    "email": ("email", "e-mail"),
}


def guess_field_key(label_text: str) -> str | None:
    """E-46: unknown fields are mapped by keyword in their label."""
    text = (label_text or "").lower()
    for key, hints in FIELD_HINTS.items():
        if any(hint in text for hint in hints):
            return key
    return None


def registry_health(rows: Iterable[Any], threshold: int = MISS_ALERT_THRESHOLD) -> list[str]:
    """E-54: selector keys with more than N misses inside one hour."""
    return [row.key for row in rows if getattr(row, "miss_count", 0) > threshold]
