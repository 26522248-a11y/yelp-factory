"""E-55: Yelp changes a URL -> reach the page through the search bar instead of hard-coding."""

from __future__ import annotations

import pytest

from core.guards import navigate_via_search
from selector_registry.resolver import SelectorRegistry, SelectorRule

pytestmark = pytest.mark.asyncio


async def test_E55_search_fallback(fake_page_factory):
    page = fake_page_factory(url="https://www.yelp.com/signup")
    page.add("input[name='find_desc']", visible=True)
    registry = SelectorRegistry({"warmup.search": [SelectorRule("css", "input[name='find_desc']", 1)]})
    assert await navigate_via_search(page, registry, "coffee") is True
    assert ("press", "input[name='find_desc']", "Enter") in page.events


async def test_E55_missing_search_bar_returns_false(fake_page_factory):
    page = fake_page_factory()
    assert await navigate_via_search(page, SelectorRegistry({}), "coffee") is False
