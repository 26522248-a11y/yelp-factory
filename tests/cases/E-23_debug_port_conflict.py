"""E-23: debug port collision -> caller can pin a fresh port in 40000-60000."""

from __future__ import annotations

import random

import httpx

from adapters.gpm_http import GPMHttpClient


def test_E23_explicit_port_is_forwarded():
    seen = {}

    def handler(request):
        seen["port"] = request.url.params.get("remote_debugging_port")
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": {"profile_id": "p1", "remote_debugging_port": int(seen["port"]), "addition_info": {"process_id": 1}},
            },
        )

    client = GPMHttpClient(base_url="http://127.0.0.1:9495", transport=httpx.MockTransport(handler))
    port = random.randint(40000, 60000)
    result = client.start_profile("p1", remote_debugging_port=port)
    assert seen["port"] == str(port)
    assert result.remote_debugging_port == port


def test_E23_random_port_range_is_valid():
    for _ in range(50):
        port = random.randint(40000, 60000)
        assert 40000 <= port <= 60000
