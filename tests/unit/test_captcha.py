from __future__ import annotations

import pytest

from adapters.base import CaptchaError
from adapters.captcha import CaptchaChain, CaptchaChallenge, FakeSolver, RECAPTCHA_V2

pytestmark = pytest.mark.asyncio


def challenge() -> CaptchaChallenge:
    return CaptchaChallenge(kind=RECAPTCHA_V2, sitekey="site-key", page_url="https://www.yelp.com/signup")


async def test_first_solver_success():
    first = FakeSolver(token="tok-1")
    chain = CaptchaChain([first])
    assert await chain.solve(challenge()) == "tok-1"


async def test_falls_back_to_second_solver():
    """E-38: solver timeout -> next provider, not a hard failure."""
    failing = FakeSolver(fail_times=5)
    backup = FakeSolver(token="tok-2")
    chain = CaptchaChain([failing, backup])
    assert await chain.solve(challenge()) == "tok-2"
    assert failing.calls == 1
    assert backup.calls == 1


async def test_all_solvers_failing_raises():
    chain = CaptchaChain([FakeSolver(fail_times=5), FakeSolver(fail_times=5)])
    with pytest.raises(CaptchaError):
        await chain.solve(challenge())


async def test_token_is_injected_and_verified():
    page = __import__("tests.fakes", fromlist=["FakePage"]).FakePage()
    page.add("g-recaptcha-response", visible=True, value="")
    chain = CaptchaChain([FakeSolver(token="x" * 40)])
    token = await chain.solve(challenge(), page=page)
    assert token
    assert any(event[0] == "evaluate" for event in page.events)


async def test_expired_token_is_rejected():
    """E-39: a token that never lands in the DOM must not be submitted."""
    page = __import__("tests.fakes", fromlist=["FakePage"]).FakePage()

    class SilentInjection:
        async def solve(self, challenge, proxy=None):
            return "short"

    chain = CaptchaChain([SilentInjection()])
    with pytest.raises(CaptchaError):
        await chain.solve(challenge(), page=page)
