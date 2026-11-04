from __future__ import annotations

import pytest

from core.backoff import AttemptCounter, RetryPolicy, SideEffectGuard, retry_async


def test_delay_grows_and_is_capped():
    policy = RetryPolicy(max_attempts=5, base_s=5, max_s=30, jitter=0)
    delays = [policy.delay(attempt) for attempt in range(1, 6)]
    assert delays[0] == pytest.approx(5)
    assert delays[1] == pytest.approx(10)
    assert delays[2] == pytest.approx(20)
    assert delays[3] == pytest.approx(30)
    assert delays[4] == pytest.approx(30)


def test_jitter_stays_within_bounds():
    policy = RetryPolicy(base_s=10, max_s=10, jitter=0.25)
    for _ in range(50):
        assert 7.5 <= policy.delay(1) <= 12.5


async def test_retry_stops_after_success():
    calls = {"n": 0}

    async def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("boom")
        return "ok"

    slept: list[float] = []

    async def fake_sleep(delay: float) -> None:
        slept.append(delay)

    result = await retry_async(flaky, RetryPolicy(max_attempts=5, base_s=0.01, jitter=0), sleep=fake_sleep)
    assert result == "ok"
    assert calls["n"] == 3
    assert len(slept) == 2


async def test_retry_raises_after_max_attempts():
    async def always_fail():
        raise ValueError("nope")

    with pytest.raises(ValueError):
        await retry_async(always_fail, RetryPolicy(max_attempts=2, base_s=0, jitter=0), sleep=_noop)


async def test_side_effect_is_not_replayed_when_verify_says_done():
    guard = SideEffectGuard()
    calls = {"n": 0}

    async def submit():
        calls["n"] += 1
        guard.mark_done("submit")
        raise TimeoutError("response lost")

    async def verify():
        return guard.is_done("submit")

    result = await retry_async(
        submit,
        RetryPolicy(max_attempts=3, base_s=0, has_side_effect=True),
        verify=verify,
        sleep=_noop,
    )
    assert result is None
    assert calls["n"] == 1


async def _noop(delay: float) -> None:
    return None


def test_attempt_counter():
    counter = AttemptCounter(max_retries=2)
    assert not counter.exhausted("sms")
    counter.bump("sms")
    counter.bump("sms")
    assert counter.exhausted("sms")
