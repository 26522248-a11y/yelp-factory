"""E-31: a required field appears that we do not know -> fill by label keyword, else form_drift."""

from __future__ import annotations

from flows.signup import SignupFlow
from selector_registry.resolver import guess_field_key


def test_E31_unknown_error_is_form_drift():
    assert SignupFlow._classify_error(["This field is required"]) == ("E-31", "form_drift")


def test_E31_label_heuristic_covers_common_fields():
    assert guess_field_key("Postal code") == "zip"
    assert guess_field_key("Town") == "city"
    assert guess_field_key("Mobile number") == "phone"


def test_E31_unmapped_field_is_left_for_logging():
    assert guess_field_key("Referral source") is None
