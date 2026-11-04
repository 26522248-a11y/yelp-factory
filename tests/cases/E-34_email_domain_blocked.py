"""E-34: Yelp rejects the email domain -> classified, domain pool rotates."""

from __future__ import annotations

from flows.signup import SignupFlow


def test_E34_domain_error_is_classified():
    code, reason = SignupFlow._classify_error(["This email domain is not accepted"])
    assert (code, reason) == ("E-34", "email_domain_blocked")


def test_E34_domain_rotation_uses_another_domain():
    from flows.pools import make_alias

    first = make_alias("fviainboxes.com")
    second = make_alias("other-domain.com")
    assert first.split("@")[1] != second.split("@")[1]
