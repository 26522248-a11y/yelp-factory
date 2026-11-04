"""Random avatar download + identity data derived from the proxy geo (section 7)."""

from __future__ import annotations

import hashlib
import random
import secrets
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import httpx

from obs.log import get_logger

log = get_logger("identity")

# Public, large-image sources. Order matters: first one that returns a real JPEG wins.
AVATAR_SOURCES = [
    "https://thispersondoesnotexist.com/",
    "https://randomuser.me/api/portraits/{gender}/{n}.jpg",
    "https://picsum.photos/seed/{seed}/800/800",
]

STREET_NAMES = [
    "Ocean Blvd", "Atlantic Ave", "Palm Beach Rd", "Federal Hwy", "Cypress Ln",
    "Magnolia Dr", "Sunrise Blvd", "Lake Ave", "Dixie Hwy", "Palmetto Park Rd",
    "Bay St", "Seabreeze Blvd", "Coral Way", "Banyan Dr", "Lighthouse Dr",
]
STREET_SUFFIX = ["Apt 2", "Apt 5", "Unit 3B", "Suite 12", "Apt 101", ""]


@dataclass(slots=True)
class Identity:
    first_name: str
    last_name: str
    birth_date: date
    street: str
    city: str
    state: str
    zip: str
    gender: str
    avatar_path: Path | None = None

    @property
    def age(self) -> int:
        today = date.today()
        return today.year - self.birth_date.year - ((today.month, today.day) < (self.birth_date.month, self.birth_date.day))

    def address_line(self) -> str:
        return f"{self.street}, {self.city}, {self.state} {self.zip}"


def _seed_for(account_id: str) -> random.Random:
    digest = hashlib.sha256(account_id.encode()).hexdigest()
    return random.Random(int(digest[:12], 16))


def build_identity(
    *,
    account_id: str,
    first_name: str,
    last_name: str,
    city_state: str,
    zip_code: str,
    geo_city: str | None = None,
) -> Identity:
    rng = _seed_for(account_id)
    city = (geo_city or city_state).split(",")[0].strip()
    state = city_state.split(",")[-1].strip() if "," in city_state else "FL"
    birth = date(rng.randint(1978, 2000), rng.randint(1, 12), rng.randint(1, 28))
    street = f"{rng.randint(100, 9800)} {rng.choice(STREET_NAMES)} {rng.choice(STREET_SUFFIX)}".strip()
    return Identity(
        first_name=first_name,
        last_name=last_name,
        birth_date=birth,
        street=street,
        city=city,
        state=state,
        zip=zip_code,
        gender=rng.choice(["Male", "Female"]),
    )


async def fetch_avatar(dest: Path, *, gender: str | None = None, seed: str | None = None) -> Path | None:
    """Download one photo from a public source; returns the local path or None."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    seed = seed or secrets.token_hex(6)
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    async with httpx.AsyncClient(timeout=45, follow_redirects=True, headers=headers, trust_env=False) as client:
        for template in AVATAR_SOURCES:
            url = template.format(gender=(gender or "women").lower(), n=random.randint(1, 90), seed=seed)
            try:
                response = await client.get(url)
                if response.status_code != 200 or len(response.content) < 10_000:
                    continue
                dest.write_bytes(response.content)
                log.info("avatar_downloaded", source=url.split("?")[0], bytes=len(response.content))
                return dest
            except httpx.HTTPError as exc:
                log.warning("avatar_source_failed", source=template, error=str(exc)[:120])
    return None


def random_dob(rng: random.Random | None = None) -> date:
    rng = rng or random.Random()
    return date(rng.randint(1978, 2000), rng.randint(1, 12), rng.randint(1, 28))
