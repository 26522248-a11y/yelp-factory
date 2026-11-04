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


class HupSmsProvider:
    """HupSMS (hupsms.com) - Vietnamese OTP SIM rental.

    Verified endpoints (2026-11-04):
      GET /api/v1/balance           -> {"data": {"balance": 20000}}
      GET /api/v1/services          -> list of {id, name, server, price, timeoutMinutes}
      GET /api/v1/rent?serviceId=N  -> {"data": {"orderId": "HupSMS...", "phone": "0996...", "expiration": 1793782682}}
    OTP polling + cancellation endpoints are documented behind the dashboard login
    (https://hupsms.com/api-docs). They are configurable here so the adapter works as soon
    as the paths are confirmed, without touching the flow code.
    """

    name = "hup"

    def __init__(
        self,
        api_key: str,
        *,
        service_id: int = 84,
        base_url: str = "https://hupsms.com/api/v1",
        status_path: str = "/rent/status",
        cancel_path: str = "/rent/cancel",
        timeout_s: int = 120,
        client: httpx.AsyncClient | None = None,
    ):
        self.api_key = api_key
        self.service_id = service_id
        self.base_url = base_url.rstrip("/")
        self.status_path = status_path
        self.cancel_path = cancel_path
        self.timeout_s = timeout_s
        self._client = client or httpx.AsyncClient(
            timeout=30, headers={"X-API-KEY": api_key, "Accept": "application/json"}
        )

    async def _get(self, path: str, params: dict | None = None) -> dict:
        response = await self._client.get(f"{self.base_url}{path}", params=params)
        if response.status_code == 404:
            raise SMSError(f"hup endpoint not found: {path}", code="sms_api")
        if response.status_code >= 400:
            raise SMSError(f"hup {path} -> {response.status_code}: {response.text[:200]}", code="sms_api")
        payload = response.json()
        if payload.get("status") != "success":
            raise SMSError(f"hup {path}: {payload.get('message')} ({payload.get('code')})", code="sms_api")
        return payload.get("data") or {}

    async def balance(self) -> float:
        data = await self._get("/balance")
        return float(data.get("balance", 0))

    async def acquire(self, *, area_code: str | None = None, max_price: float = 0.35) -> SmsSession:
        # area_code is US-centric; HupSMS rents Vietnamese numbers, so it is ignored.
        data = await self._get("/rent", {"serviceId": self.service_id})
        order_id = data.get("orderId")
        phone = data.get("phone")
        if not order_id or not phone:
            raise SMSError(f"hup rent returned no order: {data}", code="sms_api")
        return SmsSession(
            provider_id=str(order_id),
            phone_e164=_normalise_vn(phone),
            provider=self.name,
            raw=data,
        )

    async def wait_for_code(self, session: SmsSession, *, timeout_s: int | None = None) -> str:
        deadline = time.monotonic() + (timeout_s or self.timeout_s)
        while time.monotonic() < deadline:
            try:
                data = await self._get(self.status_path, {"orderId": session.provider_id})
            except SMSError as exc:
                if exc.code == "sms_api":
                    raise
                data = {}
            code = str(data.get("code") or data.get("otp") or "").strip()
            if code:
                return code
            if data.get("status") in ("cancelled", "expired"):
                raise SMSError(f"hup order {session.provider_id} {data.get('status')}")
            await asyncio.sleep(5)
        raise SMSError("hup sms timeout")

    async def request_new_code(self, session: SmsSession) -> None:
        return None

    async def release(self, session: SmsSession) -> None:
        try:
            await self._get(self.cancel_path, {"orderId": session.provider_id})
        except Exception:  # noqa: BLE001
            pass


def _normalise_vn(phone: str) -> str:
    digits = "".join(ch for ch in phone if ch.isdigit())
    if digits.startswith("0"):
        return "+84" + digits[1:]
    if digits.startswith("84"):
        return "+" + digits
    return "+" + digits


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
