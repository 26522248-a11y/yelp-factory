from __future__ import annotations

import httpx
import pytest

from adapters.base import SMSError
from adapters.sms import HupSmsProvider, _normalise_vn

pytestmark = pytest.mark.asyncio


def provider(handler, **kwargs) -> HupSmsProvider:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return HupSmsProvider("hup_test", client=client, **kwargs)


def test_vn_number_normalisation():
    assert _normalise_vn("0996203710") == "+84996203710"
    assert _normalise_vn("84996203710") == "+84996203710"
    assert _normalise_vn("+84996203710") == "+84996203710"


async def test_balance():
    def handler(request):
        assert request.url.path.endswith("/balance")
        return httpx.Response(200, json={"status": "success", "data": {"balance": 15000}})

    assert await provider(handler).balance() == 15000


async def test_acquire_returns_order_and_phone():
    def handler(request):
        assert request.url.path.endswith("/rent")
        assert request.url.params["serviceId"] == "84"
        return httpx.Response(
            200,
            json={
                "status": "success",
                "message": "Tạo đơn thành công",
                "data": {"orderId": "HupSMSabc123", "phone": "0996203710", "price": 2500, "expiration": 1793782682, "balance": 17500},
            },
        )

    session = await provider(handler).acquire()
    assert session.provider_id == "HupSMSabc123"
    assert session.phone_e164 == "+84996203710"
    assert session.provider == "hup"


async def test_wait_for_code_polls_until_ready():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        assert request.url.path.endswith("/check/HupSMSabc123")
        if calls["n"] < 2:
            return httpx.Response(200, json={"status": "success", "data": {"status": "pending", "otp": None}})
        return httpx.Response(
            200,
            json={"status": "success", "data": {"status": "success", "otp": "123456", "smsContent": "123456 la ma"}},
        )

    provider_ = provider(handler, timeout_s=10)
    session = type("S", (), {"provider_id": "HupSMSabc123"})()
    import adapters.sms as sms_module

    original = sms_module.asyncio.sleep

    async def fast(_):
        return None

    sms_module.asyncio.sleep = fast
    try:
        assert await provider_.wait_for_code(session) == "123456"
    finally:
        sms_module.asyncio.sleep = original
    assert calls["n"] >= 2


async def test_unknown_endpoint_raises_sms_api_error():
    def handler(request):
        return httpx.Response(404)

    with pytest.raises(SMSError) as excinfo:
        await provider(handler).acquire()
    assert excinfo.value.code == "sms_api"


async def test_business_error_is_surfaced():
    def handler(request):
        return httpx.Response(
            200, json={"status": "error", "message": "Tham số không hợp lệ", "code": "INVALID_PARAMETERS"}
        )

    with pytest.raises(SMSError) as excinfo:
        await provider(handler).acquire()
    assert "INVALID_PARAMETERS" in str(excinfo.value)

async def test_release_calls_cancel_endpoint():
    called = {}

    def handler(request):
        called["path"] = request.url.path
        return httpx.Response(200, json={"status": "success", "data": {"refund": 2000}})

    provider_ = provider(handler)
    session = type("S", (), {"provider_id": "HupSMSabc123"})()
    await provider_.release(session)
    assert called["path"].endswith("/cancel/HupSMSabc123")


async def test_rerent_uses_phone_param():
    def handler(request):
        assert request.url.path.endswith("/rerent")
        assert request.url.params["phone"] == "+84996203710"
        return httpx.Response(
            200,
            json={"status": "success", "data": {"orderId": "HupSMSnew", "phone": "0996203710", "price": 2000}},
        )

    session = await provider(handler).rerent("+84996203710")
    assert session.provider_id == "HupSMSnew"
    assert session.phone_e164 == "+84996203710"
