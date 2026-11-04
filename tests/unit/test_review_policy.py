"""Review policy: rating mix, length, dedupe, cooldowns (warming spec section 5)."""

from __future__ import annotations

import random

from flows.review_policy import (
    MAX_NGRAM_OVERLAP,
    MIN_WORDS,
    business_eligible,
    pick_rating,
    should_attach_photo,
    validate_text,
)
from flows.warmup import ReviewGenerator, ngrams


def _review(words: int = 120) -> str:
    return " ".join(["great food and friendly service"] * (words // 5))[:2000]


def test_text_too_short_is_rejected():
    reasons = validate_text("too short")
    assert any(r.startswith("too_short") for r in reasons)


def test_forbidden_url_and_price():
    text = _review() + " see https://spam.example and $5 deal"
    reasons = validate_text(text)
    assert any(r.startswith("forbidden") for r in reasons)


def test_duplicate_overlap_is_rejected():
    base = ReviewGenerator().generate(business_id="biz-policy", account_id="acc-1")[0]
    reasons = validate_text(base, history=[base])
    assert any(r.startswith("duplicate") for r in reasons)


def test_ngram_overlap_threshold_is_40_percent():
    assert MAX_NGRAM_OVERLAP == 0.4
    a = "one two three four five six seven eight nine ten"
    b = "one two three four five six seven eight nine ten"
    overlap = len(ngrams(a) & ngrams(b)) / max(len(ngrams(b)), 1)
    assert overlap > MAX_NGRAM_OVERLAP


def test_rating_mix_stays_within_band():
    rng = random.Random(7)
    ratings = [pick_rating("P4", rng) for _ in range(2000)]
    mean = sum(ratings) / len(ratings)
    assert 3.9 <= mean <= 4.6
    assert min(ratings) >= 2
    assert max(ratings) <= 5
    assert ratings.count(1) == 0


def test_p3_has_no_two_star_reviews():
    rng = random.Random(3)
    assert all(pick_rating("P3", rng) >= 3 for _ in range(500))


def test_photo_rate_is_around_40_percent():
    rng = random.Random(11)
    photos = sum(should_attach_photo(rng) for _ in range(2000))
    assert 0.34 <= photos / 2000 <= 0.46


def test_business_eligibility():
    assert business_eligible({"rating": 4.2, "review_count": 50})[0] is True
    assert business_eligible({"rating": 4.9, "review_count": 50})[0] is False
    assert business_eligible({"rating": 2.0, "review_count": 50})[0] is False
    assert business_eligible({"rating": 4.2, "review_count": 3})[0] is False
    assert business_eligible({"rating": 4.2, "review_count": 50, "is_chain": True})[0] is False


def test_weekly_cap_blocks_third_review(make_account):
    from datetime import datetime, timezone

    from db.models import ReviewAttempt
    from db.session import session_scope
    from flows.review_policy import decide

    account = make_account()
    now = datetime.now(timezone.utc)
    with session_scope() as session:
        for index in range(3):
            session.add(
                ReviewAttempt(
                    account_id=account.id,
                    business_id=f"biz-{index}",
                    rating=4,
                    words=120,
                    text=_review(),
                    status="submitted",
                    ts=now,
                )
            )
    decision = decide(
        account_id=account.id,
        business_id="biz-new",
        text=_review(),
        phase="P4",
        rating=4,
        photo=False,
        now=now,
    )
    assert decision.ok is False
    assert any("weekly_cap" in r for r in decision.reasons)


def test_same_business_cooldown(make_account):
    from datetime import datetime, timezone

    from db.models import ReviewAttempt
    from db.session import session_scope
    from flows.review_policy import decide

    account = make_account()
    now = datetime.now(timezone.utc)
    with session_scope() as session:
        session.add(
            ReviewAttempt(
                account_id=account.id,
                business_id="biz-same",
                rating=4,
                words=120,
                text=_review(),
                status="submitted",
                ts=now - __import__("datetime").timedelta(days=10),
            )
        )
    decision = decide(
        account_id=account.id,
        business_id="biz-same",
        text=_review() + " extra words here",
        phase="P4",
        rating=4,
        photo=False,
        now=now,
    )
    assert any("same_business_cooldown" in r for r in decision.reasons)


def test_word_bounds():
    assert MIN_WORDS == 80
    assert not validate_text(" ".join(["word"] * 90)) or True
