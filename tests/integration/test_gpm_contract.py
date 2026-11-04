"""Contract test against the fake GPM transport (create -> start -> stop -> delete)."""

from __future__ import annotations

import pytest

from adapters.base import GPMConflict, GPMSchemaDrift
from adapters.gpm_http import GPMHttpClient
from tests.integration.fake_gpm import FakeGPMTransport

pytestmark = pytest.mark.asyncio


def make_client(transport: FakeGPMTransport) -> GPMHttpClient:
    return GPMHttpClient(base_url="http://127.0.0.1:9495", transport=transport)


async def test_full_profile_lifecycle():
    transport = FakeGPMTransport()
    client = make_client(transport)

    profile = client.create_profile(name="yf-acc-1", raw_proxy="1.1.1.1:8000:u:p", browser_version="153.0.8010.53")
    assert profile.id in transport.profiles

    listed = client.list_profiles()
    assert [p.name for p in listed] == ["yf-acc-1"]

    started = client.start_profile(profile.id)
    assert started.remote_debugging_port >= 41000
    assert started.process_id

    client.stop_profile(profile.id)
    assert profile.id not in transport.started

    client.delete_profile(profile.id)
    assert transport.profiles == {}


async def test_duplicate_name_raises_conflict():
    transport = FakeGPMTransport()
    transport.fail_create = True
    client = make_client(transport)
    with pytest.raises(GPMConflict):
        client.create_profile(name="dup")


async def test_schema_drift_after_upgrade():
    transport = FakeGPMTransport()
    transport.drift = True
    client = make_client(transport)
    with pytest.raises(GPMSchemaDrift):
        client.list_profiles()


async def test_port_discovery_reads_http_port_file(tmp_path):
    (tmp_path / "http.port").write_text("9527", encoding="utf-8")
    client = GPMHttpClient(data_dirs=[tmp_path])
    assert client.base_url == "http://127.0.0.1:9527"
