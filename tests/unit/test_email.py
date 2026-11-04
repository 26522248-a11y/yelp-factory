from __future__ import annotations

import pytest

from adapters.email import FakeMailbox, MailMessage, VERIFY_LINK_RE

pytestmark = pytest.mark.asyncio

LINK = "https://www.yelp.com/signup/verify?token=abc123&uid=42"


def message(to: str = "alias@fviainboxes.com", body: str = f"Click {LINK}", folder: str = "inbox") -> MailMessage:
    return MailMessage(
        id="m1",
        subject="Verify your email for Yelp",
        sender="Yelp <no-reply@yelp.com>",
        recipients=[to],
        body=body,
        folder=folder,
    )


def test_link_is_extracted():
    assert message().verification_link() == LINK


def test_link_regex_handles_locale_host():
    text = "https://www.yelp.ca/signup/confirm?token=zzz"
    match = VERIFY_LINK_RE.search(text)
    assert match and match.group(0) == text


def test_expired_markers():
    assert message(body="This link has expired").looks_expired()
    assert not message().looks_expired()


async def test_wait_returns_first_matching_mail():
    box = FakeMailbox()
    box.deliver(to="alias@fviainboxes.com", subject="Verify your email", link=LINK)
    mail = await box.wait_for_verification("alias@fviainboxes.com", timeout_s=1)
    assert mail.link == LINK


async def test_mail_for_other_alias_is_ignored():
    box = FakeMailbox()
    box.deliver(to="other@fviainboxes.com", subject="Verify", link=LINK)
    from adapters.base import NoVerificationMail

    with pytest.raises(NoVerificationMail):
        await box.wait_for_verification("alias@fviainboxes.com", timeout_s=0.2)


async def test_junk_folder_mail_is_found():
    """E-07: mail that lands in Junk must still be picked up."""
    box = FakeMailbox()
    box.deliver(to="alias@fviainboxes.com", subject="Verify", link=LINK, folder="junkemail")
    mail = await box.wait_for_verification("alias@fviainboxes.com", timeout_s=1)
    assert mail.message.folder == "junkemail"
