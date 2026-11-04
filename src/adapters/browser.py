"""CDP attachment to a GPM-launched Chromium.

Rules (section 3.1):
* attach to ``browser.contexts()[0]`` - never create a context, that would drop the
  fingerprint and the profile cookies;
* verification links open in the existing page, new tabs are closed (E-43).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from adapters.base import BrowserAttachError
from obs.log import get_logger

log = get_logger("browser")


@dataclass(slots=True)
class AttachedBrowser:
    playwright: Any
    browser: Any
    context: Any
    page: Any
    cdp_url: str
    initial_pages: list[str] = field(default_factory=list)

    async def close(self) -> None:
        """Disconnect only; the GPM profile keeps its cookies on disk."""
        try:
            await self.browser.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            await self.playwright.stop()
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------ pages

    def page_urls(self) -> list[str]:
        return [p.url for p in self.context.pages]

    async def adopt_page(self) -> Any:
        """Reuse the original tab; close any tab a target=_blank link opened (E-43)."""
        pages = self.context.pages
        if not pages:
            raise BrowserAttachError("browser has no pages left")
        original = pages[0]
        for extra in pages[1:]:
            try:
                await extra.close()
            except Exception:  # noqa: BLE001
                pass
        self.page = original
        return original


async def attach(cdp_url: str, *, timeout_s: float = 20.0, retries: int = 2) -> AttachedBrowser:
    """``connectOverCDP`` with the retry/backoff required by E-02."""
    from playwright.async_api import async_playwright

    last_error: Exception | None = None
    for attempt in range(retries + 1):
        playwright = await async_playwright().start()
        try:
            browser = await playwright.chromium.connect_over_cdp(cdp_url, timeout=timeout_s * 1000)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            await playwright.stop()
            log.warning("cdp_connect_failed", cdp_url=cdp_url, attempt=attempt, error=str(exc)[:200])
            await asyncio.sleep(min(2**attempt, 8))
            continue

        contexts = browser.contexts
        if not contexts:
            # GPM always opens one context; a fresh one means the profile is not ours.
            await browser.close()
            await playwright.stop()
            raise BrowserAttachError("no browser context available after CDP attach")
        context = contexts[0]
        pages = context.pages
        if not pages:
            page = await context.new_page()
        else:
            page = pages[0]
        return AttachedBrowser(
            playwright=playwright,
            browser=browser,
            context=context,
            page=page,
            cdp_url=cdp_url,
            initial_pages=[p.url for p in pages],
        )
    raise BrowserAttachError(f"connectOverCDP failed after {retries + 1} attempts: {last_error}")


async def page_health(page: Any) -> bool:
    """Cheap liveness probe used by the reaper (E-03)."""
    try:
        await page.evaluate("1")
        return True
    except Exception:  # noqa: BLE001
        return False


async def is_logged_in(page: Any) -> bool:
    """Yelp keeps the session in bse/bsi, not yelp-user-id; detect the account menu instead."""
    try:
        html = (await page.content()).lower()
    except Exception:  # noqa: BLE001
        return False
    return "user_details?userid=" in html or "account settings" in html or "/logout" in html
