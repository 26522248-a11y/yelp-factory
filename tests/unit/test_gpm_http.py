from __future__ import annotations

import json

import httpx
import pytest

from adapters.base import GPMConflict, GPMSchemaDrift, GPMUnavailable
from adapters.gpm_http import GPMHttpClient

pytestmark = pytest.mark.asyncio


def client_for(handler) -> GPMHttpClient:
    return GPMHttpClient(base_url="http://127.0.0.1:9495", transport=httpx.MockTransport(handler))


async def test_health_ok():
    def handler(request):
        return httpx.Response(200, json={"success": True, "data": {"total": 1}, "message": "OK", "sender": "GPMLoginGlobal"})

    assert client_for(handler).health()["ok"] is True


async def test_connection_error_maps_to_gpm_down():
    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(GPMUnavailable):
        client_for(handler).health()


async def test_success_false_conflict():
    """E-20: GPM answers success:false for a duplicate operation."""
    def handler(request):
        return httpx.Response(200, json={"success": False, "message": "Profile name already exists", "data": None})

    with pytest.raises(GPMConflict):
        client_for(handler).create_profile(name="dup")


async def test_schema_drift_is_detected():
    """E-21: the envelope changes after a GPM upgrade."""
    def handler(request):
        return httpx.Response(200, json={"status": "ok", "profiles": []})

    with pytest.raises(GPMSchemaDrift):
        client_for(handler).list_profiles()


async def test_non_json_response_is_schema_drift():
    def handler(request):
        return httpx.Response(200, text="<html>oops</html>")

    with pytest.raises(GPMSchemaDrift):
        client_for(handler).list_profiles()


async def test_start_returns_debugging_port():
    def handler(request):
        assert "/profiles/start/" in str(request.url)
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "profile_id": "p1",
                    "remote_debugging_port": 40444,
                    "driver_path": "C:/gpmdriver.exe",
                    "addition_info": {"process_id": 999},
                },
                "message": "",
                "sender": "GPMLoginGlobal",
            },
        )

    result = client_for(handler).start_profile("p1")
    assert result.remote_debugging_port == 40444
    assert result.process_id == 999
    assert result.cdp_url == "http://127.0.0.1:40444"


async def test_start_missing_port_is_schema_drift():
    def handler(request):
        return httpx.Response(200, json={"success": True, "data": {"profile_id": "p1"}})

    with pytest.raises(GPMSchemaDrift):
        client_for(handler).start_profile("p1")


async def test_create_passes_fingerprint_flags():
    captured = {}

    def handler(request):
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"success": True, "data": {"id": "p9", "name": captured["name"], "browser": {"version": "153"}}})

    profile = client_for(handler).create_profile(
        name="yf-1",
        raw_proxy="h:1:u:p",
        browser_version="153.0.8010.53",
        canvas_mode=1,
        webrtc_mode=1,
    )
    assert profile.id == "p9"
    assert captured["canvas_mode"] == 1
    assert captured["webrtc_mode"] == 1
    assert captured["timezone_base_on_ip"] is True
