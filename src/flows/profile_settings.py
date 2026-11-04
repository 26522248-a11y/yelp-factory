"""Account profile completion: avatar, gender, birthday, location, about-me.

Yelp exposes the post-signup "complete your profile" form (`/signup/extra`) plus the
settings pages `/profile_location`, `/profile` and `/user_details`. Every field is optional
for the account to work, so failures are logged and the flow continues (E-49).
"""

from __future__ import annotations

import hashlib
import random
from datetime import date
from pathlib import Path
from typing import Any

from flows.identity import Identity
from human.mouse import human_click, read_pause
from obs.log import get_logger

log = get_logger("flows.profile")

SETTINGS_URLS = {
    "location": "https://www.yelp.com/profile_location?locale=en_US",
    "profile": "https://www.yelp.com/profile?locale=en_US",
    "account": "https://www.yelp.com/user_details?locale=en_US",
    "photos": "https://www.yelp.com/user_photos?return_url=/profile",
}

TAGLINES = [
    "Always looking for the next good meal.",
    "Weekend explorer, coffee enthusiast.",
    "Here for the food and the hidden gems.",
    "Trying every taco in town.",
    "Local spots over chains, always.",
    "Happiest when I'm outside.",
]

LOVES = [
    "Farmers markets, cold brew, live music and long walks.",
    "Street food, road trips, dogs and good playlists.",
    "Brunch, bookstores, hiking trails and rainy days.",
    "Small local restaurants, vintage shops and photography.",
    "Coffee, sushi, museums and anything outdoors.",
]

HOMETOWNS = [
    "Tampa, FL",
    "Austin, TX",
    "Columbus, OH",
    "Portland, OR",
    "Richmond, VA",
    "Sacramento, CA",
    "Raleigh, NC",
    "Denver, CO",
]

FAVORITE_BOOKS = ["The Old Man and the Sea", "Educated", "The Hobbit", "Atomic Habits", "Beloved"]
FAVORITE_FILMS = ["Back to the Future", "Spirited Away", "The Big Lebowski", "Arrival", "Rocky"]
FAVORITE_MEALS = ["Tacos al pastor", "Margherita pizza", "Pho", "Fried chicken", "Pad thai"]
FAVORITE_MUSIC = ["Fleetwood Mac", "Kendrick Lamar", "The Strokes", "Sade", "Nirvana"]


async def _safe(step: str, coro) -> Any:
    try:
        return await coro
    except Exception as exc:  # noqa: BLE001
        log.warning("profile_step_failed", step=step, error=str(exc)[:180])
        return None


def _rng(identity: Identity, salt: str) -> random.Random:
    seed = int(hashlib.sha256(f"{identity.birth_date}:{identity.city}:{salt}".encode()).hexdigest()[:12], 16)
    return random.Random(seed)


def _pick(identity: Identity, salt: str, options: list[str]) -> str:
    return _rng(identity, salt).choice(options)


async def _fill_selector(page, selectors: tuple[str, ...], value: str) -> bool:
    """Fill the first element that matches any of the CSS fallbacks."""
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if await locator.count() == 0:
                continue
            await locator.fill(value)
            return True
        except Exception:  # noqa: BLE001
            continue
    return False


async def _select_selector(page, selectors: tuple[str, ...], value: str) -> bool:
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if await locator.count() == 0:
                continue
            await locator.select_option(value=value)
            return True
        except Exception:  # noqa: BLE001
            continue
    return False


async def _click_save(page, registry) -> bool:
    save = await _safe("save", registry.find(page, "profile.save", required=False, timeout_ms=2500))
    if save is None:
        return False
    await _safe("save_click", human_click(page, save))
    await page.wait_for_timeout(2000)
    return True


async def fill_extra_form(page, registry, identity: Identity, avatar_path: Path | None) -> dict:
    filled: dict[str, Any] = {}
    if avatar_path and avatar_path.exists():
        upload = await _safe("avatar", registry.find(page, "profile.avatar_input", required=False, timeout_ms=3000))
        if upload is not None:
            await _safe("avatar_set", upload.set_input_files(str(avatar_path.resolve())))
            await page.wait_for_timeout(2500)
            filled["avatar"] = True

    gender_key = "onboarding.gender_male" if identity.gender.lower().startswith("m") else "onboarding.gender_female"
    radio = await _safe("gender", registry.find(page, gender_key, required=False, timeout_ms=2500))
    if radio is not None:
        await _safe("gender_click", radio.check(force=True) if hasattr(radio, "check") else radio.click())
        filled["gender"] = identity.gender

    pronoun = await _safe("pronoun", registry.find(page, "onboarding.gender_pronoun", required=False, timeout_ms=2000))
    if pronoun is not None:
        value = "He/Him" if identity.gender.lower().startswith("m") else "She/Her"
        await _safe("pronoun_select", pronoun.select_option(label=value))
        filled["pronoun"] = value
    return filled


async def fill_location(page, registry, identity: Identity) -> dict:
    filled: dict[str, Any] = {}
    await _safe("loc_goto", page.goto(SETTINGS_URLS["location"], wait_until="domcontentloaded", timeout=60_000))
    await read_pause(page, seconds=(1.5, 3.0))

    city_name = identity.city.split(",")[0].strip()
    state = identity.city.split(",")[-1].strip() if "," in identity.city else ""
    if await _fill_selector(page, ("input#city", "input[name='city']"), city_name):
        filled["city"] = city_name
    if state and await _select_selector(page, ("select#state", "select[name='state']"), state):
        filled["state"] = state
    if await _fill_selector(
        page,
        ("input#zip", "input[name='zip']", "input#postal_code", "input[name='postal_code']"),
        identity.zip,
    ):
        filled["zip"] = identity.zip

    if filled and await _click_save(page, registry):
        filled["saved"] = True
    return filled


async def _fill_birthday_on_current_page(page, identity: Identity) -> dict:
    filled: dict[str, Any] = {}
    birth: date = identity.birth_date
    pairs = (
        ("month", str(birth.month)),
        ("day", str(birth.day)),
        ("year", str(birth.year)),
    )
    for suffix, value in pairs:
        selectors = (
            f"select[name='birthday_{suffix}']",
            f"select[id='birthday_{suffix}']",
            f"select[name*='birth_{suffix}']",
            f"input[name*='birth_{suffix}']",
        )
        if await _select_selector(page, selectors, value) or await _fill_selector(page, selectors, value):
            filled[suffix] = value

    # Some variants expose a single native date input.
    if not filled:
        for selector in ("input[type='date'][name*='birth']", "input[type='date'][id*='birth']"):
            locator = page.locator(selector).first
            if await locator.count():
                if await _safe("birthday_date", locator.fill(birth.isoformat())):
                    filled["date"] = birth.isoformat()
                break
    return filled


async def fill_birthday(page, registry, identity: Identity) -> dict:
    """The birthday control moved between /profile and /user_details across Yelp versions."""
    filled: dict[str, Any] = {}
    for url in (SETTINGS_URLS["profile"], SETTINGS_URLS["account"]):
        await _safe("birthday_goto", page.goto(url, wait_until="domcontentloaded", timeout=60_000))
        await read_pause(page, seconds=(1.2, 2.6))
        found = await _fill_birthday_on_current_page(page, identity)
        if found:
            filled.update(found)
            if await _click_save(page, registry):
                filled["saved"] = True
            break
    if not filled:
        log.info("birthday_field_absent")
    return filled


async def fill_profile_details(page, registry, identity: Identity) -> dict:
    """Fill every free-text field the public profile offers (no external links)."""
    filled: dict[str, Any] = {}
    await _safe("profile_goto", page.goto(SETTINGS_URLS["profile"], wait_until="domcontentloaded", timeout=60_000))
    await read_pause(page, seconds=(1.5, 3.0))

    first = identity.first_name.strip()
    last_initial = (identity.last_name.strip()[:1] + ".") if identity.last_name.strip() else ""
    fields = {
        "nickname": f"{first} {last_initial}".strip(),
        "tagline": _pick(identity, "tagline", TAGLINES),
        "love_name": _pick(identity, "loves", LOVES),
        "find_me_in": identity.city.split(",")[0].strip(),
        "hometown": _pick(identity, "hometown", HOMETOWNS),
        "book": _pick(identity, "book", FAVORITE_BOOKS),
        "film": _pick(identity, "film", FAVORITE_FILMS),
        "concert": _pick(identity, "concert", FAVORITE_MUSIC),
        "lastmeal": _pick(identity, "meal", FAVORITE_MEALS),
        "recentdiscovery": _pick(identity, "discovery", FAVORITE_MEALS),
        "donttell": _pick(identity, "donttell", ["The hole-in-the-wall spots.", "My quiet coffee corner.", "The best late-night tacos."]),
        "crush": _pick(identity, "crush", ["Good espresso.", "A perfect taco.", "Sunday markets."]),
    }
    for name, value in fields.items():
        if await _fill_selector(page, (f"input#{name}", f"input[name='{name}']", f"textarea#{name}", f"textarea[name='{name}']"), value):
            filled[name] = value

    # Gender/pronoun on this page are radio groups; the pronoun group is hidden behind a
    # styled control, so only the visible gender radios are set (pronoun comes from the
    # post-signup extra form).
    gender_value = "m" if identity.gender.lower().startswith("m") else "f"
    for selector in (f"input#gender{gender_value}", f"input[name='gender'][value='{gender_value}']"):
        locator = page.locator(selector).first
        if await locator.count():
            await _safe("profile_gender", locator.check(force=True))
            filled["gender"] = identity.gender
            break

    if filled and await _click_save(page, registry):
        filled["saved"] = True
    return filled


async def fill_everything(page, registry, identity: Identity, avatar_path: Path | None) -> dict:
    """Run every optional profile step; returns what actually stuck."""
    result: dict[str, Any] = {}
    for step, coro in (
        ("extra", fill_extra_form(page, registry, identity, avatar_path)),
        ("details", fill_profile_details(page, registry, identity)),
        ("location", fill_location(page, registry, identity)),
        ("birthday", fill_birthday(page, registry, identity)),
    ):
        try:
            result.update(await coro or {})
        except Exception as exc:  # noqa: BLE001
            log.warning("profile_block_failed", step=step, error=str(exc)[:180])
    log.info("profile_completed", **{k: str(v)[:40] for k, v in result.items()})
    return result
