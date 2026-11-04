"""Review policy: rating mix, quality rules, dedupe (warming spec section 5)."""

from __future__ import annotations

import random
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from db.models import ReviewAttempt
from db.session import session_scope
from flows.warmup import ngrams
from obs.log import get_logger

log = get_logger("review_policy")

MIN_WORDS = 80
MAX_WORDS = 200
MAX_NGRAM_OVERLAP = 0.4
PHOTO_RATE = 0.4
SAME_BUSINESS_COOLDOWN_DAYS = 90
MAX_PER_WEEK = {"P3": 2, "P4": 3}
MIN_RATING_EARLY = 2  # no 1-star in the first 60 days

RATING_MIX = {
    "P3": {5: 0.35, 4: 0.45, 3: 0.20},
    "P4": {5: 0.50, 4: 0.30, 3: 0.15, 2: 0.05},
}

FORBIDDEN = [
    re.compile(r"https?://|www\.", re.IGNORECASE),
    re.compile(r"\$\s?\d"),
    re.compile(r"\b(discount|promo code|coupon code)\b", re.IGNORECASE),
    re.compile(r"\b(they should hire|fired|manager name)\b", re.IGNORECASE),
]


@dataclass
class ReviewDecision:
    ok: bool
    reasons: list[str]
    rating: int
    words: int
    photo: bool


def pick_rating(phase: str, rng: random.Random | None = None) -> int:
    rng = rng or random.Random()
    mix = RATING_MIX.get(phase, RATING_MIX["P3"])
    ratings = list(mix)
    weights = [mix[r] for r in ratings]
    return rng.choices(ratings, weights=weights, k=1)[0]


def should_attach_photo(rng: random.Random | None = None) -> bool:
    return (rng or random.Random()).random() < PHOTO_RATE


def validate_text(text: str, *, history: list[str] | None = None) -> list[str]:
    reasons: list[str] = []
    words = text.split()
    if len(words) < MIN_WORDS:
        reasons.append(f"too_short:{len(words)}")
    if len(words) > MAX_WORDS:
        reasons.append(f"too_long:{len(words)}")
    for pattern in FORBIDDEN:
        if pattern.search(text):
            reasons.append(f"forbidden:{pattern.pattern[:20]}")
    candidate = ngrams(text)
    for previous in history or []:
        overlap = len(candidate & ngrams(previous)) / max(len(candidate), 1)
        if overlap > MAX_NGRAM_OVERLAP:
            reasons.append(f"duplicate:{overlap:.2f}")
            break
    return reasons


def business_eligible(meta: dict | None) -> tuple[bool, str]:
    """meta = {rating, review_count, city, is_chain}"""
    if not meta:
        return True, "no_meta"
    rating = float(meta.get("rating", 4.0))
    count = int(meta.get("review_count", 10))
    if count < 5:
        return False, "too_few_reviews"
    if not 3.5 <= rating <= 4.8:
        return False, "rating_out_of_band"
    if meta.get("is_chain"):
        return False, "chain_business"
    return True, "ok"


def reviews_in_window(account_id, days: int = 7, *, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    with session_scope() as session:
        rows = session.scalars(
            select(ReviewAttempt).where(
                ReviewAttempt.account_id == account_id,
                ReviewAttempt.ts >= now - timedelta(days=days),
            )
        ).all()
    return len(rows)


def same_business_recent(account_id, business_id: str, *, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    with session_scope() as session:
        row = session.scalars(
            select(ReviewAttempt).where(
                ReviewAttempt.account_id == account_id,
                ReviewAttempt.business_id == business_id,
                ReviewAttempt.ts >= now - timedelta(days=SAME_BUSINESS_COOLDOWN_DAYS),
            )
        ).first()
    return row is not None


def history_texts(business_id: str, limit: int = 30) -> list[str]:
    """Recent review texts for the same business across all accounts (dedupe corpus)."""
    from db.models import ReviewAttempt as RA

    with session_scope() as session:
        rows = session.scalars(
            select(RA).where(RA.business_id == business_id).order_by(RA.ts.desc()).limit(limit)
        ).all()
    return [getattr(r, "text", "") for r in rows if getattr(r, "text", "")]


def decide(
    *,
    account_id,
    business_id: str,
    text: str,
    phase: str,
    rating: int,
    photo: bool,
    business_meta: dict | None = None,
    now: datetime | None = None,
) -> ReviewDecision:
    reasons: list[str] = []
    ok, why = business_eligible(business_meta)
    if not ok:
        reasons.append(f"business:{why}")
    if same_business_recent(account_id, business_id, now=now):
        reasons.append("same_business_cooldown")
    cap = MAX_PER_WEEK.get(phase, 2)
    if reviews_in_window(account_id, days=7, now=now) >= cap:
        reasons.append(f"weekly_cap:{cap}")
    if rating < MIN_RATING_EARLY:
        reasons.append("rating_too_low_early")
    reasons.extend(validate_text(text))
    return ReviewDecision(ok=not reasons, reasons=reasons, rating=rating, words=len(text.split()), photo=photo)
