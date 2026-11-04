"""E-18: password rejected -> new password generated and the form is submitted again."""

from __future__ import annotations

from flows.signup import SignupFlow


def test_E18_password_error_is_detected():
    assert SignupFlow._classify_error(["Password must contain a number"]) == ("E-18", "password_rejected")
    assert SignupFlow._classify_error(["Your password is too common"]) == ("E-18", "password_rejected")


def test_E18_generated_passwords_never_repeat():
    from flows.pools import generate_password

    first, second = generate_password(), generate_password()
    assert first != second
    assert len({generate_password() for _ in range(100)}) == 100
