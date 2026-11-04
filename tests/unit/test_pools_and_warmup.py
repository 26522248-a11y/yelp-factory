from __future__ import annotations

import re

import pytest

from flows.pools import build_persona, generate_password, pick_zip
from flows.warmup import ReviewGenerator, build_day_tasks, ngrams

SPECIAL = r"!@#$%^&*\-_=+"


def test_password_rules():
    for _ in range(200):
        password = generate_password()
        assert 14 <= len(password) <= 18
        assert re.search(r"[A-Z]", password)
        assert re.search(r"[a-z]", password)
        assert re.search(r"\d", password)
        assert re.search(f"[{SPECIAL}]", password)


def test_passwords_are_unique():
    passwords = {generate_password() for _ in range(500)}
    assert len(passwords) == 500


def test_zip_belongs_to_city():
    zip_code = pick_zip("Austin, TX")
    assert zip_code.startswith("787")


def test_persona_is_coherent():
    persona = build_persona("Austin, TX", "fviainboxes.com")
    assert persona.city.startswith("Austin")
    assert persona.email_alias.endswith("@fviainboxes.com")
    assert persona.first_name and persona.last_name


def test_unknown_city_is_rejected():
    with pytest.raises(ValueError):
        pick_zip("Springfield, ZZ")


def test_review_length_and_rating():
    generator = ReviewGenerator()
    text, stars = generator.generate(business_id="biz-1", account_id="acc-1")
    assert 80 <= len(text.split()) <= 200
    assert 1 <= stars <= 5


def test_review_dedupes_5grams_per_business():
    """E-53: a second account cannot publish a near-identical review."""
    generator = ReviewGenerator()
    first, _ = generator.generate(business_id="biz-1", account_id="acc-1")
    second, _ = generator.generate(business_id="biz-1", account_id="acc-2")
    overlap = len(ngrams(first) & ngrams(second)) / max(len(ngrams(second)), 1)
    assert overlap <= 0.6


def test_ngrams_are_case_insensitive():
    assert ngrams("The Quick Brown Fox Jumps") == ngrams("the quick brown fox jumps")


def test_plan_phases_limit_actions():
    tasks = build_day_tasks(__import__("uuid").uuid4(), day=1, city="Austin, TX")
    kinds = [t.kind for t in tasks]
    assert "review" not in kinds  # P0/P1 never review
    assert kinds.count("session") <= 3


def test_reviews_start_at_day_11():
    tasks = build_day_tasks(__import__("uuid").uuid4(), day=22, city="Austin, TX")
    assert any(t.kind == "review" for t in tasks)

def test_identity_is_deterministic_and_plausible():
    from flows.identity import build_identity

    a = build_identity(account_id="acc-1", first_name="A", last_name="B", city_state="Delray Beach, FL", zip_code="33444")
    b = build_identity(account_id="acc-1", first_name="A", last_name="B", city_state="Delray Beach, FL", zip_code="33444")
    assert a.birth_date == b.birth_date
    assert a.street == b.street
    assert 25 <= a.age <= 48
    assert a.city == "Delray Beach" and a.state == "FL"
    assert "33444" in a.address_line()
    assert a.gender in ("Male", "Female")


async def test_profile_completion_is_best_effort(fake_page_factory):
    from flows.identity import build_identity
    from flows.profile_settings import fill_extra_form
    from selector_registry.resolver import SelectorRegistry

    page = fake_page_factory(html="<html></html>")
    identity = build_identity(account_id="acc-2", first_name="A", last_name="B", city_state="Austin, TX", zip_code="78701")
    out = await fill_extra_form(page, SelectorRegistry({}), identity, avatar_path=None)
    assert out == {}
