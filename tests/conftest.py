"""Shared fixtures: settings, DNS-free defaults, in-memory fakes."""

from __future__ import annotations

import base64
import os
import uuid

import pytest

os.environ.setdefault("YF_MASTER_KEY", base64.urlsafe_b64encode(b"0" * 32).decode())

from core.config import Settings, load_settings  # noqa: E402
from human.timing import session_length_seconds  # noqa: E402
from obs.log import configure_logging  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _logging():
    configure_logging("WARNING", json_output=True)


@pytest.fixture()
def settings() -> Settings:
    cfg = load_settings()
    cfg.email.provider = "fake"
    cfg.captcha.providers = []
    cfg.captcha.human_in_loop = False
    cfg.gpm.mcp_url = ""
    cfg.gpm.base_url = "http://127.0.0.1:9"
    return cfg


@pytest.fixture()
def fake_page_factory():
    from tests.fakes import FakePage

    def make(url: str = "https://www.yelp.com/signup", html: str = "") -> FakePage:
        return FakePage(url=url, html=html)

    return make


@pytest.fixture()
def fake_browser():
    from tests.fakes import FakeBrowser

    return FakeBrowser()


@pytest.fixture()
def account_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture()
def run_id() -> uuid.UUID:
    return uuid.uuid4()


def pytest_configure(config):
    config.addinivalue_line("markers", "db: requires a live Postgres")
