"""Human-like typing (section 9): 45-180ms per key, 12% typo rate, bezier-free focus."""

from __future__ import annotations

import asyncio
import random

from obs.log import get_logger

log = get_logger("human.typing")

MIN_DELAY_MS = 45
MAX_DELAY_MS = 180
TYPO_RATE = 0.12

_NEIGHBOURS = {
    "a": "sqwz",
    "b": "vgnh",
    "c": "xdfv",
    "d": "sfec",
    "e": "wrsd",
    "f": "dgrt",
    "g": "fhty",
    "h": "gjyu",
    "i": "uojk",
    "j": "hkiu",
    "k": "jlio",
    "l": "kop",
    "m": "njk",
    "n": "bmhj",
    "o": "ipkl",
    "p": "ol",
    "q": "wa",
    "r": "etdf",
    "s": "adew",
    "t": "ryfg",
    "u": "yihj",
    "v": "cbfg",
    "w": "qeas",
    "x": "czsd",
    "y": "tuhg",
    "z": "asx",
}


def _typo(char: str) -> str:
    options = _NEIGHBOURS.get(char.lower())
    if not options:
        return char
    replacement = random.choice(options)
    return replacement.upper() if char.isupper() else replacement


async def human_type(locator, text: str, *, typo_rate: float = TYPO_RATE) -> None:
    await locator.click()
    for char in text:
        if random.random() < typo_rate and char.isalpha():
            wrong = _typo(char)
            await locator.type(wrong)
            await asyncio.sleep(random.uniform(0.08, 0.22))
            await locator.press("Backspace")
            await asyncio.sleep(random.uniform(0.05, 0.15))
        await locator.type(char)
        await asyncio.sleep(random.uniform(MIN_DELAY_MS, MAX_DELAY_MS) / 1000)
    # Blur so inline validation fires (form has to report its errors).
    await locator.evaluate("el => el.blur()")
    await asyncio.sleep(random.uniform(0.15, 0.45))


async def set_value_native(locator, text: str) -> None:
    """Fast path for values a human would paste (e.g. OTP)."""
    await locator.fill(text)
