"""Account warming: plans, daily sessions, review generation (section 8)."""

from __future__ import annotations

import hashlib
import math
import random
import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable

from core.budget import DailyBudget, PHASE_DEFAULTS, phase_for_day
from obs.log import get_logger
from obs.metrics import warming_actions_total

log = get_logger("flows.warmup")

REVIEW_MIN_WORDS = 80
REVIEW_MAX_WORDS = 200
NGRAM = 5

REVIEW_TEMPLATES = [
    (
        "Came here on a {weekday} around {time} and the place was {crowd}. "
        "Ordered the {dish} and the {drink}; the {dish} was {praise}, though the {drink} took a while to arrive. "
        "Staff checked on us twice without hovering, which I appreciated. "
        "{neutral} Parking nearby is a bit of a walk, so plan for that. "
        "Would come back for the {dish} alone, maybe on a quieter night."
    ),
    (
        "Stopped by after work since a friend kept mentioning this spot. "
        "The {dish} is the reason to come: {praise}. Portions are {portion}, and prices sit where you would expect for the area. "
        "{neutral} Service was friendly but clearly stretched during the rush, and our {drink} showed up after the food. "
        "Seating is {seating}. Solid neighborhood option if you are not in a hurry."
    ),
    (
        "Third visit this year, so this is not a first-impression review. "
        "The {dish} has been consistent every time and the kitchen handles {diet} requests without drama. "
        "{neutral} The room gets loud after {time}, which makes conversation work a little harder. "
        "{praise} I keep coming back for the {dish} and will probably keep doing so, just earlier in the evening."
    ),
    (
        "Booked a table for {party} on short notice and they squeezed us in. "
        "We split the {dish} and a couple of {drink}s; everything landed hot and the {dish} was {praise}. "
        "{neutral} The {seating} situation is tight, so do not expect much elbow room. "
        "Not the cheapest night out, but nothing felt overpriced for what we got."
    ),
]

DISHES = ["brisket plate", "breakfast tacos", "ramen", "wood-fired pizza", "birria", "pad see ew", "fried chicken sandwich", "ceviche"]
DRINKS = ["house margarita", "cold brew", "local IPA", "horchata", "espresso tonic", "sweet tea"]
PRAISE = ["genuinely well seasoned", "better than I expected", "the best version I have had in this city", "worth the hype"]
NEUTRAL = [
    "Nothing was bad, nothing was unforgettable.",
    "The wait was longer than quoted, which seems normal here.",
    "Music was louder than it needed to be for a weeknight.",
    "Bathroom could use a refresh.",
]
WEEKDAYS = ["Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
TIMES = ["noon", "1pm", "6:30", "7pm", "8pm"]


def _seed_for(business_id: str, account_id: str | None = None) -> int:
    payload = f"{business_id}:{account_id or ''}".encode()
    return int(hashlib.sha256(payload).hexdigest()[:12], 16)


def ngrams(text: str, n: int = NGRAM) -> set[tuple[str, ...]]:
    words = re.findall(r"[a-z0-9']+", text.lower())
    return {tuple(words[i : i + n]) for i in range(max(0, len(words) - n + 1))}


@dataclass
class ReviewGenerator:
    """Template + seed, with 5-gram de-duplication per business (E-53)."""

    history: dict[str, list[str]] = field(default_factory=dict)

    def generate(
        self,
        *,
        business_id: str,
        account_id: str | None = None,
        rating: int | None = None,
        seed_offset: int = 0,
    ) -> tuple[str, int]:
        rng = random.Random(_seed_for(business_id, account_id) + seed_offset)
        template = rng.choice(REVIEW_TEMPLATES)
        for _ in range(20):
            text = template.format(
                weekday=rng.choice(WEEKDAYS),
                time=rng.choice(TIMES),
                crowd=rng.choice(["packed", "half full", "quiet", "busy but moving"]),
                dish=rng.choice(DISHES),
                drink=rng.choice(DRINKS),
                praise=rng.choice(PRAISE),
                neutral=rng.choice(NEUTRAL),
                portion=rng.choice(["generous", "reasonable", "smaller than expected"]),
                seating=rng.choice(["tight", "comfortable", "mostly bar stools"]),
                diet=rng.choice(["vegetarian", "gluten-free", "dairy-free"]),
                party=rng.choice(["two", "four", "six"]),
            )
            words = text.split()
            if len(words) < REVIEW_MIN_WORDS:
                text += " " + rng.choice(NEUTRAL) + " " + rng.choice(PRAISE).capitalize() + "."
            if len(text.split()) > REVIEW_MAX_WORDS:
                text = " ".join(text.split()[:REVIEW_MAX_WORDS])
            if not self._collides(business_id, text):
                stars = rating if rating is not None else rng.choice([3, 4, 4, 4, 5, 5])
                self.history.setdefault(business_id, []).append(text)
                return text, stars
            seed_offset += 1
        raise RuntimeError("could not generate a unique review")

    def _collides(self, business_id: str, text: str) -> bool:
        candidate = ngrams(text)
        for previous in self.history.get(business_id, []):
            overlap = len(candidate & ngrams(previous))
            if overlap / max(len(candidate), 1) > 0.6:
                return True
        return False


@dataclass(slots=True)
class WarmingTaskSpec:
    kind: str
    due_at: datetime
    meta: dict[str, Any] = field(default_factory=dict)


def build_day_tasks(account_id: uuid.UUID, day: int, *, city: str, rng: random.Random | None = None) -> list[WarmingTaskSpec]:
    """Map a warming day to concrete tasks bounded by the phase budget."""
    rng = rng or random.Random()
    phase = phase_for_day(day)
    budget = PHASE_DEFAULTS[phase]
    tasks: list[WarmingTaskSpec] = []
    base = datetime.now(timezone.utc).replace(hour=14, minute=0, second=0, microsecond=0)
    sessions = rng.randint(1, 3)

    for session in range(sessions):
        start = base + timedelta(minutes=session * rng.randint(120, 240))
        tasks.append(WarmingTaskSpec("session", start, {"phase": phase, "city": city}))
        for _ in range(rng.randint(2, budget["pageview"])):
            tasks.append(WarmingTaskSpec("pageview", start + timedelta(seconds=rng.randint(20, 300)), {"phase": phase}))
        if budget["save"] and rng.random() < 0.7:
            tasks.append(WarmingTaskSpec("save", start + timedelta(minutes=2), {"count": rng.randint(1, budget["save"])}))
        if budget["vote"] and rng.random() < 0.8:
            tasks.append(WarmingTaskSpec("vote", start + timedelta(minutes=3), {"count": rng.randint(1, budget["vote"])}))
        if budget["follow"] and rng.random() < 0.5:
            tasks.append(WarmingTaskSpec("follow", start + timedelta(minutes=4), {"count": 1}))
        if budget["review"] and day >= 11:
            # P3: one review every 2-3 days, P4: every 1-2 days.
            cadence = 3 if phase == "P3" else 2
            if day % cadence == 0:
                tasks.append(WarmingTaskSpec("review", start + timedelta(minutes=5), {"min_session_s": 480}))
    return tasks


class WarmingRunner:
    def __init__(self, *, gpm, registry, settings, generator: ReviewGenerator | None = None):
        self.gpm = gpm
        self.registry = registry
        self.settings = settings
        self.generator = generator or ReviewGenerator()

    # ------------------------------------------------------------------ session

    async def run_session(self, ctx, *, budget: DailyBudget, empty: bool = False, max_seconds: int = 720) -> dict[str, Any]:
        from core.trust import allowed_kinds, compute_trust, record_trust
        from db.models import ActionLog, WarmingSession
        from db.session import session_scope

        page = ctx.data["browser"].page
        started = datetime.now(timezone.utc)
        account_id = getattr(ctx, "account_id", None)
        phase = ctx.data.get("phase", "P1")
        proxy_ip = ctx.data.get("proxy_ip")
        breakdown_before = compute_trust(account_id) if account_id else None
        allowed = allowed_kinds(breakdown_before.score if breakdown_before else 0)

        session_id = None
        if account_id:
            with session_scope() as session:
                row = WarmingSession(
                    account_id=account_id,
                    plan_id=ctx.data.get("plan_id"),
                    started_at=started,
                    entry_path=ctx.data.get("entry_path", "search"),
                    proxy_ip=proxy_ip,
                    trust_before=breakdown_before.score if breakdown_before else None,
                )
                session.add(row)
                session.flush()
                session_id = row.id

        actions: list[str] = []

        def log_action(kind: str, target: str | None = None, meta: dict | None = None) -> None:
            if not account_id:
                return
            with session_scope() as session:
                session.add(
                    ActionLog(
                        account_id=account_id,
                        session_id=session_id,
                        kind=kind,
                        target=(target or "")[:300] or None,
                        meta=meta or {"proxy_ip": proxy_ip},
                    )
                )

        if empty:
            await page.goto("https://www.yelp.com/?locale=en_US", wait_until="domcontentloaded", timeout=45_000)
            await page.wait_for_timeout(random.randint(20_000, 60_000))
            log_action("session", "empty")
            await self._finish_session(session_id, account_id, ["empty"], 1, started, breakdown_before)
            return {"actions": ["empty"], "duration_s": (datetime.now(timezone.utc) - started).total_seconds()}

        try:
            while (datetime.now(timezone.utc) - started).total_seconds() < max_seconds:
                if page.is_closed():
                    break
                status = await self._step(page, ctx, budget, allowed=allowed, phase=phase, log=log_action)
                if not status:
                    break
                actions.append(status)
                await page.wait_for_timeout(random.randint(3_000, 9_000))
        except Exception as exc:  # noqa: BLE001
            if "429" in str(exc) or "403" in str(exc):
                budget.penalize()
                log.warning("warming_rate_limited", error=str(exc)[:150])
        log_action("session", "end")
        await self._finish_session(session_id, account_id, actions, len(actions), started, breakdown_before)
        return {
            "actions": actions,
            "duration_s": round((datetime.now(timezone.utc) - started).total_seconds(), 1),
            "trust_before": breakdown_before.score if breakdown_before else None,
        }

    async def _finish_session(self, session_id, account_id, actions, count, started, before) -> None:
        from core.trust import compute_trust, record_trust
        from db.models import WarmingSession
        from db.session import session_scope

        after = compute_trust(account_id) if account_id else None
        if session_id:
            with session_scope() as session:
                row = session.get(WarmingSession, session_id)
                if row is not None:
                    row.ended_at = datetime.now(timezone.utc)
                    row.actions = count
                    row.trust_after = after.score if after else None
        if account_id:
            record_trust(account_id, after)

    async def _step(self, page, ctx, budget: DailyBudget, *, allowed: set[str], phase: str, log) -> str:
        choice = self._choose_action(budget, allowed, phase)
        if not choice:
            return ""
        if choice == "review" and not cfg_review_allowed(ctx):
            return ""
        if not budget.consume(choice):
            choice = "pageview"
            if not budget.consume(choice):
                return ""
        warming_actions_total.labels(kind=choice, phase=phase).inc()

        if choice == "pageview":
            query = random.choice(["coffee", "tacos", "ramen", "brunch", "bbq", "seafood", "pizza", "dessert"])
            await page.goto(f"https://www.yelp.com/search?find_desc={query}", timeout=45_000)
            await page.wait_for_timeout(random.randint(2_000, 6_000))
            await page.mouse.wheel(0, random.randint(200, 900))
            log("pageview", page.url)
            return "pageview"
        if choice == "search":
            box = await self.registry.find(page, "warmup.search", required=False, timeout_ms=3000)
            if box is None:
                return "search_miss"
            await box.fill(random.choice(["best tacos", "coffee near me", "brunch", "seafood"]))
            await box.press("Enter")
            await page.wait_for_load_state("domcontentloaded", timeout=30_000)
            log("search", page.url)
            return "search"
        if choice == "save":
            button = await self.registry.find(page, "warmup.save_business", required=False, timeout_ms=2500)
            if button is not None:
                await button.click()
                log("save", page.url)
                return "save"
            return "save_miss"
        if choice == "vote":
            button = await self.registry.find(page, "warmup.vote_useful", required=False, timeout_ms=2500)
            if button is not None:
                await button.click()
                log("vote", page.url)
                return "vote"
            return "vote_miss"
        if choice == "follow":
            button = await self.registry.find(page, "onboarding.follow_user", required=False, timeout_ms=2500)
            if button is not None:
                await button.click()
                log("follow", page.url)
                return "follow"
            return "follow_miss"
        if choice == "review":
            return await self._do_review(page, ctx, phase, log)
        return ""

    def _choose_action(self, budget: DailyBudget, allowed: set[str], phase: str) -> str:
        weights: list[tuple[str, int]] = [
            ("pageview", 5),
            ("search", 3),
            ("save", 2),
            ("vote", 2),
            ("follow", 1),
        ]
        if phase in ("P3", "P4"):
            weights.append(("review", 1 if phase == "P3" else 2))
        choices = [(kind, weight) for kind, weight in weights if kind in allowed and budget.allowed(kind)]
        if not choices:
            return "pageview" if budget.allowed("pageview") else ""
        kinds = [k for k, _ in choices]
        return random.choices(kinds, weights=[w for _, w in choices], k=1)[0]

    async def _do_review(self, page, ctx, phase: str, log) -> str:
        from core.trust import review_eligible
        from db.models import ReviewAttempt
        from db.session import session_scope
        from flows.review_policy import decide, history_texts, pick_rating, should_attach_photo
        from human.mouse import human_click

        business_id = _business_id_from_url(page.url)
        account_id = getattr(ctx, "account_id", None)
        if not business_id or not account_id:
            return "review_no_business"
        ok, reason = review_eligible(account_id)
        if not ok:
            log("review_blocked", business_id, {"reason": reason})
            return f"review_blocked:{reason}"

        rating = pick_rating(phase)
        photo = should_attach_photo()
        text, _ = self.generator.generate(business_id=business_id, account_id=str(account_id), rating=rating)
        decision = decide(
            account_id=account_id,
            business_id=business_id,
            text=text,
            phase=phase,
            rating=rating,
            photo=photo,
            business_meta=None,
        )
        if not decision.ok:
            log("review_rejected", business_id, {"reasons": decision.reasons[:3]})
            return "review_rejected"

        stars = page.locator("div[role='radiogroup'] button[aria-label*='star']")
        try:
            if await stars.count():
                await stars.nth(min(rating, 5) - 1).click()
            box = await self.registry.find(page, "warmup.review_text", required=False, timeout_ms=3000)
            if box is None:
                return "review_no_box"
            await box.fill(text)
            submit = await self.registry.find(page, "warmup.review_submit", required=False, timeout_ms=3000)
            if submit is None:
                return "review_no_submit"
            await human_click(page, submit)
            await page.wait_for_timeout(4000)
        except Exception as exc:  # noqa: BLE001
            log("review_error", business_id, {"error": str(exc)[:150]})
            return "review_error"

        with session_scope() as session:
            session.add(
                ReviewAttempt(
                    account_id=account_id,
                    business_id=business_id,
                    rating=rating,
                    words=len(text.split()),
                    text=text,
                    photo=photo,
                    status="submitted",
                )
            )
        log("review", business_id, {"rating": rating, "words": len(text.split())})
        return "review"


# --------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------

import re as _re

_BIZ_RE = _re.compile(r"/biz/([^/?#]+)")


def _business_id_from_url(url: str) -> str | None:
    match = _BIZ_RE.search(url or "")
    return match.group(1) if match else None


def cfg_review_allowed(ctx) -> bool:
    return bool(ctx.data.get("review_enabled", True))
