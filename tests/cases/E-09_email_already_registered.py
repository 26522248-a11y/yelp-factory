"""E-09: email already registered -> alias regenerated, account retried at FORM_FILLED."""

from __future__ import annotations

from flows.signup import SignupFlow


def test_E09_already_registered_is_classified():
    assert SignupFlow._classify_error(["This email is already registered"]) == ("E-09", "email_taken")
    assert SignupFlow._classify_error(["Already have an account? Log in"]) == ("E-09", "email_taken")


def test_E09_other_errors_are_not_email_taken():
    code, reason = SignupFlow._classify_error(["Password is too weak"])
    assert reason == "password_rejected"
