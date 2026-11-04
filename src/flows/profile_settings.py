"""Account profile completion: avatar, gender, birthday, location (best effort, never fatal).

Yelp exposes the post-signup "complete your profile" form (`/signup/extra`) plus the
settings pages `/profile_location`, `/profile` and `/user_photos`. Every field is optional
for the account to work, so failures are logged and the flow continues (E-49).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from flows.identity import Identity
from human.mouse import human_click, read_pause
from obs.log import get_logger

log = get_logger("flows.profile")

SETTINGS_URLS = {
    "location": "https://www.yelp.com/profile_location?locale=en_US",
    "profile": "https://www.yelp.com/profile?locale=en_US",
    "photos": "https://www.yelp.com/user_photos?return_url=/profile",
}


async def _safe(step: str, coro) -> Any:
    try:
        return await coro
    except Exception as exc:  # noqa: BLE001
        log.warning("profile_step_failed", step=step, error=str(exc)[:180])
        return None


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
    await page.goto(SETTINGS_URLS["location"], wait_until="domcontentloaded", timeout=60_000)
    await read_pause(page, seconds=(1.5, 3.0))
    city = await _safe("loc_city", registry.find(page, "profile.location_city", required=False, timeout_ms=3000))
    if city is not None:
        await _safe("loc_city_fill", city.fill(identity.city))
        filled["city"] = identity.city
    zip_input = await _safe("loc_zip", registry.find(page, "profile.location_zip", required=False, timeout_ms=2500))
    if zip_input is not None:
        await _safe("loc_zip_fill", zip_input.fill(identity.zip))
        filled["zip"] = identity.zip
    save = await _safe("loc_save", registry.find(page, "profile.save", required=False, timeout_ms=2500))
    if save is not None:
        await human_click(page, save)
        await page.wait_for_timeout(2500)
        filled["saved"] = True
    return filled


async def fill_birthday(page, registry, identity: Identity) -> dict:
    filled: dict[str, Any] = {}
    await page.goto(SETTINGS_URLS["profile"], wait_until="domcontentloaded", timeout=60_000)
    await read_pause(page, seconds=(1.5, 3.0))
    for key, value in (
        ("profile.birthday_month", str(identity.birth_date.month)),
        ("profile.birthday_day", str(identity.birth_date.day)),
        ("profile.birthday_year", str(identity.birth_date.year)),
    ):
        field = await _safe(key, registry.find(page, key, required=False, timeout_ms=2000))
        if field is None:
            continue
        await _safe(f"{key}_select", field.select_option(value=value))
        filled[key.rsplit(".", 1)[-1]] = value
    if filled:
        save = await _safe("profile_save", registry.find(page, "profile.save", required=False, timeout_ms=2500))
        if save is not None:
            await human_click(page, save)
            await page.wait_for_timeout(2000)
    return filled


async def fill_everything(page, registry, identity: Identity, avatar_path: Path | None) -> dict:
    """Run every optional profile step; returns what actually stuck."""
    result: dict[str, Any] = {}
    result.update(await fill_extra_form(page, registry, identity, avatar_path) or {})
    result.update(await fill_location(page, registry, identity) or {})
    result.update(await fill_birthday(page, registry, identity) or {})
    log.info("profile_completed", **{k: str(v)[:40] for k, v in result.items()})
    return result
