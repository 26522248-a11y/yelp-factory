"""E-19: name rejected (odd characters) -> classified so the pool can be swapped."""

from __future__ import annotations

from flows.pools import FIRST_NAMES, LAST_NAMES
from flows.signup import SignupFlow


def test_E19_name_error_is_classified():
    code, reason = SignupFlow._classify_error(["Please enter a valid name"])
    assert (code, reason) == ("E-19", "name_rejected")


def test_E19_name_pool_is_plain_ascii():
    for name in FIRST_NAMES + LAST_NAMES:
        assert name.isascii() and name.isalpha()
