"""E-29: more than five redirects to the same URL -> loop detected, cookies cleared."""

from __future__ import annotations

from core.guards import RedirectGuard


def test_E29_loop_is_detected():
    guard = RedirectGuard(limit=5)
    for _ in range(5):
        assert guard.observe("https://www.yelp.com/signup") is True
    assert guard.observe("https://www.yelp.com/signup") is False


def test_E29_normal_navigation_is_allowed():
    guard = RedirectGuard()
    for url in ["https://www.yelp.com/", "https://www.yelp.com/signup", "https://www.yelp.com/signup/extra"]:
        assert guard.observe(url) is True
    assert guard.hops == 3


def test_E29_reset_clears_history():
    guard = RedirectGuard(limit=1)
    guard.observe("https://www.yelp.com/a")
    guard.observe("https://www.yelp.com/a")
    guard.reset()
    assert guard.observe("https://www.yelp.com/a") is True
