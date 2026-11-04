from __future__ import annotations

import pytest

from adapters.browser import AttachedBrowser
from adapters.proxy_probe import ProxyTarget, _parse

pytestmark = pytest.mark.asyncio


def test_proxy_url_from_colon_format():
    target = ProxyTarget(raw="pr.oxylabs.io:7777:user-name:pa=ss")
    assert target.url == "http://user-name:pa%3Dss@pr.oxylabs.io:7777"


def test_proxy_url_keeps_scheme():
    assert ProxyTarget(raw="socks5://1.2.3.4:1080").url == "socks5://1.2.3.4:1080"


def test_parse_ip_api_payload():
    result = _parse(
        "http://ip-api.com/json/",
        {"status": "success", "query": "1.2.3.4", "countryCode": "US", "city": "Austin", "as": "AS1"},
    )
    assert result.ok and result.city == "Austin" and result.asn == "AS1"


def test_parse_ipinfo_payload():
    result = _parse("https://ipinfo.io/json", {"ip": "5.6.7.8", "country": "US", "city": "Austin", "org": "AS2"})
    assert result.ok and result.ip == "5.6.7.8"


async def test_adopt_page_closes_extra_tabs(fake_browser):
    """E-43: a verify link that opens a new tab must not leave an orphan tab behind."""
    first = fake_browser.context.pages[0]
    second = await fake_browser.context.new_page()
    fake_browser.context.pages.append(second)
    attached = AttachedBrowser(
        playwright=None,
        browser=fake_browser,
        context=fake_browser.context,
        page=first,
        cdp_url="http://127.0.0.1:1234",
    )
    adopted = await attached.adopt_page()
    assert adopted is first
    assert second.closed
    assert len(fake_browser.context.pages) == 1
