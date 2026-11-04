"""E-46: unknown field labels are mapped by keyword, unmatched fields are only logged."""

from __future__ import annotations

import pytest

from selector_registry.resolver import guess_field_key


@pytest.mark.parametrize(
    "label,expected",
    [
        ("Postal / ZIP", "zip"),
        ("Town or city", "city"),
        ("Telephone number", "phone"),
        ("Given name", "first_name"),
        ("Family name", "last_name"),
        ("Email address", "email"),
    ],
)
def test_E46_keyword_mapping(label, expected):
    assert guess_field_key(label) == expected


def test_E46_unknown_field_returns_none():
    assert guess_field_key("How did you hear about us?") is None
