"""Account trust score + action gates (warming spec v1.0, section 0)."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from db.models import Account, ActionLog, Event, ReviewAttempt, TrustScore
from db.session import session_scope
from obs.log import get_logger

log = get_logger("trust")

WEIGHTS = {
    "age": 20,
    "profile": 15,
    "consistency": 15,
    "diversity": 20,
    "content": 20,
    "risk": -20,
}

RISK_PENALTY = {
    "http_429": 3,
    "http_403": 5,
    "captcha": 4,
    "identity_check": 15,
    "filtered_review": 8,
    "sms_fail": 2,
    "gpm_down": 1,
}

REVIEW_THRESHOLD = 75
REVIEW_MIN_AGE_DAYS = 11
REVIEW_MIN_SESSIONS_7D = 6


@dataclass
class TrustBreakdown:
    age: float = 0
    profile: float = 0
    consistency: float = 0
    diversity: float = 0
    content: float = 0
    risk: float = 0

    @property
    def score(self) -> int:
        raw = self.age + self.profile + self.consistency + self.diversity + self.content + self.risk
        return max(0, min(100, int(round(raw))))

    def as_dict(self) -> dict:
        data = asdict(self)
        data["score"] = self.score
        return data


def _age_component(account: Account, now: datetime) -> float:
    created = account.created_at or now
    days = max(0.0, (now - created).total_seconds() / 86400)
    return min(20.0, days * 0.7)


def _profile_component(account: Account) -> float:
    score = 0.0
    if account.avatar_path:
        score += 4
    if account.first_name and account.last_name:
        score += 2
    if account.city and account.address_line:
        score += 3
    if account.birth_date:
        score += 2
    if account.email:
        score += 2
    if account.phone_e164:
        score += 2
    return min(15.0, score)


def _consistency_component(account: Account, actions: list[ActionLog]) -> float:
    if not actions:
        return 0.0
    ips = {a.meta.get("proxy_ip") for a in actions if a.meta and a.meta.get("proxy_ip")}
    score = 8.0
    if len(ips) <= 1:
        score += 4
    elif len(ips) == 2:
        score += 2
    if account.profile_id:
        score += 3
    return min(15.0, score)


def _diversity_component(actions: list[ActionLog]) -> float:
    kinds = {a.kind for a in actions}
    targets = {a.target for a in actions if a.target}
    score = min(12.0, len(kinds) * 2.0) + min(8.0, len(targets) * 0.5)
    return min(20.0, score)


def _content_component(reviews: list[ReviewAttempt]) -> float:
    if not reviews:
        return 0.0
    score = 0.0
    for review in reviews[-5:]:
        if 80 <= review.words <= 200:
            score += 2.0
        if review.photo:
            score += 1.0
        if review.status == "published":
            score += 1.0
        if review.filtered_at is not None:
            score -= 1.0
    return max(0.0, min(20.0, score))


def _risk_component(account_id: uuid.UUID, now: datetime) -> float:
    cutoff = now - timedelta(days=30)
    with session_scope() as session:
        events = session.execute(
            select(Event.code).where(Event.account_id == account_id, Event.ts >= cutoff)
        ).all()
    penalty = 0.0
    for (code,) in events:
        if not code:
            continue
        penalty += RISK_PENALTY.get(code, 1)
    return -min(20.0, penalty)


def compute_trust(account_id: uuid.UUID, *, now: datetime | None = None) -> TrustBreakdown:
    now = now or datetime.now(timezone.utc)
    with session_scope() as session:
        account = session.get(Account, account_id)
        if account is None:
            return TrustBreakdown()
        actions = session.scalars(
            select(ActionLog).where(ActionLog.account_id == account_id, ActionLog.ts >= now - timedelta(days=7))
        ).all()
        reviews = session.scalars(
            select(ReviewAttempt).where(ReviewAttempt.account_id == account_id).order_by(ReviewAttempt.ts)
        ).all()
        breakdown = TrustBreakdown(
            age=_age_component(account, now),
            profile=_profile_component(account),
            consistency=_consistency_component(account, actions),
            diversity=_diversity_component(actions),
            content=_content_component(reviews),
        )
        breakdown.risk = _risk_component(account_id, now)
    return breakdown


def record_trust(account_id: uuid.UUID, breakdown: TrustBreakdown | None = None) -> int:
    breakdown = breakdown or compute_trust(account_id)
    with session_scope() as session:
        session.add(TrustScore(account_id=account_id, score=breakdown.score, components=breakdown.as_dict()))
    return breakdown.score


def latest_trust(account_id: uuid.UUID) -> int:
    with session_scope() as session:
        row = session.scalars(
            select(TrustScore).where(TrustScore.account_id == account_id).order_by(TrustScore.id.desc()).limit(1)
        ).first()
        if row is not None:
            return row.score
    return compute_trust(account_id).score


def allowed_kinds(score: int) -> set[str]:
    """Deterministic gate: which action kinds an account may perform at this score."""
    kinds = {"pageview", "search", "scroll", "session"}
    if score >= 40:
        kinds |= {"save", "view_photo", "view_review"}
    if score >= 60:
        kinds |= {"vote", "follow"}
    if score >= 75:
        kinds |= {"review", "checkin", "upload_photo"}
    return kinds


def review_eligible(account_id: uuid.UUID, *, now: datetime | None = None) -> tuple[bool, str]:
    now = now or datetime.now(timezone.utc)
    breakdown = compute_trust(account_id, now=now)
    if breakdown.score < REVIEW_THRESHOLD:
        return False, f"trust {breakdown.score} < {REVIEW_THRESHOLD}"
    with session_scope() as session:
        account = session.get(Account, account_id)
        if account is None or account.created_at is None:
            return False, "no_account"
        age_days = (now - account.created_at).days
        sessions = session.scalar(
            select(func.count(WarmingSession.id)).where(
                WarmingSession.account_id == account_id,
                WarmingSession.started_at >= now - timedelta(days=7),
            )
        )
        filtered = session.scalars(
            select(ReviewAttempt).where(
                ReviewAttempt.account_id == account_id,
                ReviewAttempt.filtered_at.isnot(None),
                ReviewAttempt.filtered_at >= now - timedelta(days=7),
            )
        ).first()
    if age_days < REVIEW_MIN_AGE_DAYS:
        return False, f"age {age_days}d < {REVIEW_MIN_AGE_DAYS}"
    if (sessions or 0) < REVIEW_MIN_SESSIONS_7D:
        return False, f"sessions_7d {sessions} < {REVIEW_MIN_SESSIONS_7D}"
    if filtered is not None:
        return False, "recent_filtered_review"
    return True, "ok"
