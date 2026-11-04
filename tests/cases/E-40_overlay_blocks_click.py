"""E-40: an overlay swallows the first two clicks; third attempt is forced."""

from __future__ import annotations

import pytest

from selector_registry.resolver import SelectorRegistry, SelectorRule

pytestmark = pytest.mark.asyncio


async def test_E40_click_force_after_two_failures(fake_page_factory):
    registry = SelectorRegistry({"cookie.accept": [SelectorRule("css", "button#onetrust-accept-btn-handler", 1)]})
    page = fake_page_factory()
    button = page.add(
        "button#onetrust-accept-btn-handler",
        visible=True,
        click_errors=[RuntimeError("intercepted"), RuntimeError("intercepted")],
    )
    ok = await registry.click(page, "cookie.accept", force_after=2)
    assert ok is True
    assert button.clicks == 3
    assert page.events[-1][0] == "click" and page.events[-1][2] is True
