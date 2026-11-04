from __future__ import annotations

import pytest

from selector_registry.resolver import SelectorRegistry, SelectorRule, guess_field_key

pytestmark = pytest.mark.asyncio


def registry() -> SelectorRegistry:
    return SelectorRegistry(
        {
            "signup.email": [
                SelectorRule("css", "input#email", 1),
                SelectorRule("css", "input[name='email']", 2),
                SelectorRule("label", "Email", 3),
            ]
        }
    )


async def test_first_rule_wins(fake_page_factory):
    page = fake_page_factory()
    page.add("input#email", visible=True)
    page.add("input[name='email']", visible=True)
    element = await registry().find(page, "signup.email")
    assert element.selector == "input#email"


async def test_falls_back_when_preferred_selector_missing(fake_page_factory):
    """E-30: A/B layout changes; resolution falls through to name/label rules."""
    page = fake_page_factory()
    page.add("input#email", visible=False)
    page.add("label=Email", visible=True)
    element = await registry().find(page, "signup.email")
    assert element.selector == "label=Email"


async def test_miss_raises_selector_miss(fake_page_factory):
    from adapters.base import SelectorMiss

    page = fake_page_factory()
    with pytest.raises(SelectorMiss):
        await registry().find(page, "signup.email")


async def test_miss_is_optional(fake_page_factory):
    page = fake_page_factory()
    assert await registry().find(page, "signup.email", required=False) is None


@pytest.mark.parametrize(
    "label,expected",
    [
        ("ZIP code", "zip"),
        ("Postal Code", "zip"),
        ("City", "city"),
        ("Mobile phone", "phone"),
        ("First name", "first_name"),
        ("Surname", "last_name"),
        ("E-mail address", "email"),
        ("Favorite color", None),
    ],
)
def test_guess_field_key(label, expected):
    assert guess_field_key(label) == expected


async def test_page_tag_overrides_base_rules(fake_page_factory):
    reg = SelectorRegistry(
        {
            "signup.email": [SelectorRule("css", "input#email", 1)],
            "signup.email@ab_v2": [SelectorRule("css", "input.ab-email", 1)],
        }
    )
    page = fake_page_factory()
    page.add("input.ab-email", visible=True)
    element = await reg.find(page, "signup.email", page_tag="ab_v2")
    assert element.selector == "input.ab-email"


async def test_registry_yaml_loads_and_is_sorted():
    reg = SelectorRegistry.from_yaml()
    assert "signup.email" in reg.keys()
    priorities = [rule.priority for rule in reg.rules_for("signup.email")]
    assert priorities == sorted(priorities)


def test_registry_health_flags_missing_selectors():
    from types import SimpleNamespace

    from selector_registry.resolver import registry_health

    rows = [SimpleNamespace(key="signup.email", miss_count=25), SimpleNamespace(key="ok", miss_count=1)]
    assert registry_health(rows) == ["signup.email"]
