"""E-28: half-loaded page -> one controlled reload before the step is retried."""

from __future__ import annotations

import pytest

from core.guards import reload_once

pytestmark = pytest.mark.asyncio


async def test_E28_reload_once(fake_page_factory):
    page = fake_page_factory()
    assert await reload_once(page) is True
    assert page.reloads == 1


async def test_E28_reload_failure_is_swallowed(fake_page_factory):
    page = fake_page_factory()

    async def boom(**kwargs):
        raise RuntimeError("target closed")

    page.reload = boom
    assert await reload_once(page) is False
