"""SMS number pool + OTP retrieval (E-14..E-17)."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Protocol

import httpx

from adapters.base import SMSError
from obs.log import get_logger

log = get_logger("sms")

SMS_API = "https://api.sms-activate.org/stubs/handler_api.php"


@dataclass(slots=True)
class SmsSession:
    provider_id: str
    phone_e164: str
    provider: str
    raw: dict = field(default_factory=dict)


class SmsProvider(Protocol):
    async def acquire(self, *, area_code: str | None = None, max_price: float = 0.35) -> SmsSession: ...

    async def wait_for_code(self, session: SmsSession, *, timeout_s: int = 120) -> str: ...

    async def release(self, session: SmsSession) -> None: ...

    async def request_new_code(self, session: SmsSession) -> None: ...


class SmsActivateProvider:
    name = "smsapi"

    def __init__(self, api_key: str, country: str = "US", client: httpx.AsyncClient | None = None):
        self.api_key = api_key
        self.country = country
        self._client = client or httpx.AsyncClient(timeout=30)

    async def _call(self, params: dict) -> str:
        merged = {"api_key": self.api_key, **params}
        response = await self._client.get(SMS_API, params=merged)
        response.raise_for_status()
        return response.text

    async def acquire(self, *, area_code: str | None = None, max_price: float = 0.35) -> SmsSession:
        params = {"action": "getNumber", "service": "yel", "country": self.country, "maxPrice": max_price}
        if area_code:
            params["operator"] = area_code
        text = await self._call(params)
        if not text.startswith("ACCESS_NUMBER"):
            raise SMSError(f"acquire failed: {text}")
        _, provider_id, phone = text.split(":", 2)
        return SmsSession(provider_id=provider_id, phone_e164=f"+{phone.lstrip('+')}", provider=self.name)

    async def wait_for_code(self, session: SmsSession, *, timeout_s: int = 120) -> str:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            text = await self._call({"action": "getStatus", "id": session.provider_id})
            if text.startswith("STATUS_OK"):
                return text.split(":", 1)[1]
            if text in ("STATUS_CANCEL", "NO_ACTIVATION"):
                raise SMSError(f"sms session lost: {text}")
            await asyncio.sleep(5)
        raise SMSError("sms timeout")

    async def request_new_code(self, session: SmsSession) -> None:
        await self._call({"action": "setStatus", "status": 3, "id": session.provider_id})

    async def release(self, session: SmsSession) -> None:
        try:
            await self._call({"action": "setStatus", "status": 8, "id": session.provider_id})
        except Exception:  # noqa: BLE001
            pass


class FakeSmsProvider:
    """Deterministic provider used by tests: codes are queued per session."""

    name = "fake"

    def __init__(self, numbers: list[str] | None = None, codes: list[str] | None = None):
        self.numbers = numbers or ["+15125550100", "+15125550101", "+15125550102"]
        self.codes = codes or ["123456", "123456", "123456"]
        self.used: set[str] = set()
        self.issued: dict[str, list[str]] = {}
        self._counter = 0

    async def acquire(self, *, area_code: str | None = None, max_price: float = 0.35) -> SmsSession:
        for number in self.numbers:
            if number in self.used:
                continue
            if area_code and not number.startswith(f"+1{area_code}"):
                continue
            self.used.add(number)
            self.issued[number] = list(self.codes)
            return SmsSession(provider_id=number, phone_e164=number, provider=self.name)
        raise SMSError("no number available")

    async def wait_for_code(self, session: SmsSession, *, timeout_s: int = 120) -> str:
        queue = self.issued.get(session.phone_e164) or []
        if not queue:
            raise SMSError("no sms received")
        return queue.pop(0)

    async def request_new_code(self, session: SmsSession) -> None:
        self.issued.setdefault(session.phone_e164, []).append(self.codes[0] if self.codes else "000000")

    async def release(self, session: SmsSession) -> None:
        self.used.discard(session.phone_e164)


def area_code_for_city(city: str, mapping: dict[str, str] | None = None) -> str | None:
    mapping = mapping or {"austin": "512", "dallas": "214", "houston": "713", "miami": "305", "seattle": "206"}
    key = city.split(",")[0].strip().lower()
    return mapping.get(key)
