"""E-07: verification mail that lands in Junk is picked up, not ignored."""

from __future__ import annotations

import pytest

from adapters.email import FakeMailbox

pytestmark = pytest.mark.asyncio

LINK = "https://www.yelp.com/signup/verify?token=junk"


async def test_E07_junk_folder_is_scanned():
    box = FakeMailbox()
    box.deliver(to="alias@fviainboxes.com", subject="Verify your email", link=LINK, folder="junkemail")
    mail = await box.wait_for_verification("alias@fviainboxes.com", timeout_s=1)
    assert mail.link == LINK
    assert mail.message.folder == "junkemail"
