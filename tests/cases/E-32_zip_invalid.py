"""E-32: ZIP rejected -> next ZIP in the same city, max 3 attempts."""

from __future__ import annotations

from flows.pools import ZIP_POOL, pick_zip
from flows.signup import SignupFlow


def test_E32_zip_error_is_classified():
    assert SignupFlow._classify_error(["Please enter a valid ZIP code"]) == ("E-32", "zip_invalid")


def test_E32_alternative_zip_same_city():
    first = pick_zip("Austin, TX")
    second = pick_zip("Austin, TX", exclude={first})
    assert second != first
    assert ZIP_POOL[second][0] == "Austin"
