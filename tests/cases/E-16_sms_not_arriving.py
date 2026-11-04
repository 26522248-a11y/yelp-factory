"""E-16: SMS never arrives -> timeout, number released, next attempt uses a new number."""

from __future__ import annotations

import pytest

from adapters.base import SMSError
from adapters.sms import FakeSmsProvider, SmsSession

pytestmark = pytest.mark.asyncio


async def test_E16_empty_queue_times_out():
    provider = FakeSmsProvider(codes=[])
    session = await provider.acquire()
    with pytest.raises(SMSError):
        await provider.wait_for_code(session, timeout_s=1)


async def test_E16_release_frees_the_number_for_reuse():
    provider = FakeSmsProvider(numbers=["+15125550100"], codes=["123456"])
    first = await provider.acquire()
    with pytest.raises(SMSError):
        await provider.acquire()  # pool exhausted while the number is held
    await provider.release(first)
    second = await provider.acquire()
    assert second.phone_e164 == first.phone_e164
