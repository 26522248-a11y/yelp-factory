"""Deterministic data pools: names, ZIPs, passwords, aliases (section 7)."""

from __future__ import annotations

import json
import random
import secrets
import string
from dataclasses import dataclass
from pathlib import Path

from core.config import ROOT

FIRST_NAMES = [
    "James", "Michael", "Christopher", "Daniel", "Matthew", "Anthony", "Joshua", "Andrew",
    "Emily", "Sarah", "Ashley", "Jessica", "Amanda", "Melissa", "Nicole", "Rachel",
    "Brandon", "Justin", "Tyler", "Kevin", "Laura", "Megan", "Katie", "Hannah",
]
LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis",
    "Rodriguez", "Martinez", "Hernandez", "Lopez", "Wilson", "Anderson", "Thomas", "Taylor",
    "Moore", "Jackson", "Martin", "Lee", "Thompson", "White", "Harris", "Clark",
]

# ZIP -> (city, state). Real prefixes so Yelp geo validation passes (E-33).
ZIP_POOL: dict[str, tuple[str, str]] = {
    "78701": ("Austin", "TX"),
    "78702": ("Austin", "TX"),
    "78704": ("Austin", "TX"),
    "78745": ("Austin", "TX"),
    "75201": ("Dallas", "TX"),
    "75204": ("Dallas", "TX"),
    "77002": ("Houston", "TX"),
    "77005": ("Houston", "TX"),
    "33101": ("Miami", "FL"),
    "33139": ("Miami", "FL"),
    "33444": ("Delray Beach", "FL"),
    "33445": ("Delray Beach", "FL"),
    "33483": ("Delray Beach", "FL"),
    "33432": ("Boca Raton", "FL"),
    "98101": ("Seattle", "WA"),
    "98109": ("Seattle", "WA"),
    "97201": ("Portland", "OR"),
    "97205": ("Portland", "OR"),
}

SPECIAL = "!@#$%^&*-_=+"


@dataclass(slots=True)
class Persona:
    first_name: str
    last_name: str
    zip: str
    city: str
    password: str
    email_alias: str


def generate_password(rng: random.Random | None = None) -> str:
    """14-18 chars, mixed classes, never repeated between accounts."""
    rng = rng or random.Random(secrets.randbits(64))
    length = rng.randint(14, 18)
    chars = [
        rng.choice(string.ascii_uppercase),
        rng.choice(string.ascii_lowercase),
        rng.choice(string.digits),
        rng.choice(SPECIAL),
    ]
    alphabet = string.ascii_letters + string.digits + SPECIAL
    chars += [rng.choice(alphabet) for _ in range(length - len(chars))]
    rng.shuffle(chars)
    return "".join(chars)


def pick_zip(city: str, rng: random.Random | None = None, *, exclude: set[str] | None = None) -> str:
    rng = rng or random.Random()
    city_name = city.split(",")[0].strip().lower()
    candidates = [z for z, (c, _) in ZIP_POOL.items() if c.lower() == city_name and (not exclude or z not in exclude)]
    if not candidates:
        raise ValueError(f"no ZIP in pool for city {city}")
    return rng.choice(candidates)


def load_zip_file(path: str | Path | None = None) -> dict[str, tuple[str, str]]:
    path = Path(path) if path else ROOT / "data" / "zips_us.json"
    if not path.exists():
        return dict(ZIP_POOL)
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {str(k): (v["city"], v["state"]) for k, v in raw.items()}


def make_alias(domain: str, *, prefix: str | None = None, rng: random.Random | None = None) -> str:
    rng = rng or random.Random(secrets.randbits(64))
    base = prefix or "".join(rng.choices(string.ascii_lowercase, k=10))
    suffix = "".join(rng.choices(string.ascii_lowercase + string.digits, k=4))
    return f"{base}{suffix}@{domain}"


def build_persona(city: str, domain: str, *, rng: random.Random | None = None, zip_override: str | None = None) -> Persona:
    rng = rng or random.Random(secrets.randbits(64))
    zip_code = zip_override or pick_zip(city, rng)
    city_name, state = ZIP_POOL.get(zip_code, (city.split(",")[0].strip(), "TX"))
    return Persona(
        first_name=rng.choice(FIRST_NAMES),
        last_name=rng.choice(LAST_NAMES),
        zip=zip_code,
        city=f"{city_name}, {state}",
        password=generate_password(rng),
        email_alias=make_alias(domain, rng=rng),
    )


def slugify_name(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum() or ch in "-_") or "user"
