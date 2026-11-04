"""E-43: verification link opens a second tab -> adopt the original, close the extra."""

from __future__ import annotations

import pytest

from adapters.browser import AttachedBrowser
from tests.fakes import FakeBrowser, FakePage

pytestmark = pytest.mark.asyncio


async def test_E43_extra_tab_is_closed():
    browser = FakeBrowser()
    extra = await browser.context.new_page()
    attached = AttachedBrowser(
        playwright=None, browser=browser, context=browser.context, page=browser.context.pages[0], cdp_url="http://x"
    )
    adopted = await attached.adopt_page()
    assert adopted is browser.context.pages[0]
    assert extra.closed is True
    assert len(browser.context.pages) == 1
