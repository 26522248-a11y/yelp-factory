"""E-39: captcha token never lands in the DOM / is empty -> solve again, never submit."""

from __future__ import annotations

import pytest

from adapters.base import CaptchaError
from adapters.captcha import CaptchaChain, CaptchaChallenge, RECAPTCHA_V2

pytestmark = pytest.mark.asyncio


async def test_E39_empty_token_blocks_submit(fake_page_factory):
    page = fake_page_factory()
    page.add("g-recaptcha-response", visible=True, value="")

    class EmptyTokenSolver:
        name = "empty"

        async def solve(self, challenge, proxy=None):
            return ""

    chain = CaptchaChain([EmptyTokenSolver()])
    challenge = CaptchaChallenge(kind=RECAPTCHA_V2, sitekey="k", page_url="https://www.yelp.com/signup")
    with pytest.raises(CaptchaError):
        await chain.solve(challenge, page=page)
