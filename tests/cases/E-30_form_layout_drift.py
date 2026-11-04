"""E-30: A/B form layout -> fallback through name attribute, then label."""

from __future__ import annotations

import pytest

from selector_registry.resolver import SelectorRegistry, SelectorRule

pytestmark = pytest.mark.asyncio


async def test_E30_fallback_chain(fake_page_factory):
    registry = SelectorRegistry(
        {
            "signup.email": [
                SelectorRule("css", "input#email", 1),
                SelectorRule("name", "email", 2),
                SelectorRule("label", "Email", 3),
            ]
        }
    )
    page = fake_page_factory()
    page.add("input#email", visible=False)
    page.add("[name='email']", visible=True)
    element = await registry.find(page, "signup.email")
    assert element.selector == "[name='email']"


async def test_E30_all_rules_missing_raises(fake_page_factory):
    from adapters.base import SelectorMiss

    registry = SelectorRegistry({"signup.email": [SelectorRule("css", "input#none", 1)]})
    page = fake_page_factory()
    with pytest.raises(SelectorMiss):
        await registry.find(page, "signup.email")
