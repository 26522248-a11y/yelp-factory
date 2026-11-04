"""Retry policy: exponential backoff with jitter and side-effect protection."""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from obs.log import get_logger

log = get_logger("backoff")


@dataclass(slots=True)
class RetryPolicy:
    max_attempts: int = 3
    base_s: float = 5.0
    max_s: float = 30.0
    jitter: float = 0.25
    # Retrying an action with side effects requires a verify() first (section 10 rule).
    has_side_effect: bool = False

    def delay(self, attempt: int) -> float:
        raw = min(self.base_s * (2 ** max(attempt - 1, 0)), self.max_s)
        spread = raw * self.jitter
        return max(0.0, raw + random.uniform(-spread, spread))


class SideEffectGuard:
    """Prevents a submit/resend from being replayed after success was observed (E-05, E-44)."""

    def __init__(self):
        self._done: dict[str, Any] = {}

    def mark_done(self, key: str, evidence: Any = True) -> None:
        self._done[key] = evidence

    def is_done(self, key: str) -> bool:
        return key in self._done

    def evidence(self, key: str) -> Any:
        return self._done.get(key)

    def reset(self, key: str) -> None:
        self._done.pop(key, None)


async def retry_async(
    fn: Callable[[], Awaitable[Any]],
    policy: RetryPolicy,
    *,
    on_retry: Callable[[int, Exception], Awaitable[None] | None] | None = None,
    verify: Callable[[], Awaitable[bool]] | None = None,
    retry_if: Callable[[Exception], bool] | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
):
    last: Exception | None = None
    for attempt in range(1, policy.max_attempts + 1):
        try:
            return await fn()
        except Exception as exc:  # noqa: BLE001
            last = exc
            if retry_if and not retry_if(exc):
                raise
            if policy.has_side_effect and verify is not None and await verify():
                log.info("side_effect_already_done", attempt=attempt, error=str(exc)[:200])
                return None
            if attempt == policy.max_attempts:
                raise
            delay = policy.delay(attempt)
            log.warning("retrying", attempt=attempt, delay_s=round(delay, 2), error=str(exc)[:200])
            if on_retry:
                result = on_retry(attempt, exc)
                if asyncio.iscoroutine(result):
                    await result
            await sleep(delay)
    assert last is not None
    raise last


@dataclass(slots=True)
class AttemptCounter:
    """Bookkeeping shared with the DB so retries survive a crash."""

    max_retries: int
    used: dict[str, int] = field(default_factory=dict)

    def bump(self, key: str) -> int:
        self.used[key] = self.used.get(key, 0) + 1
        return self.used[key]

    def exhausted(self, key: str) -> bool:
        return self.used.get(key, 0) >= self.max_retries
