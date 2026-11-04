"""Avatar pool scraped from large public sources (Reddit, Wikimedia, Pinterest, IG/FB og:image).

Only public, unauthenticated endpoints are used. Instagram/Facebook usually serve a login wall,
so they are best-effort: we read the ``og:image`` meta tag when it is present. Everything that
passes validation is stored in ``data/avatar_pool`` and reused, so a session never depends on a
live scrape.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
from dataclasses import dataclass
from pathlib import Path

import httpx

from obs.log import get_logger

log = get_logger("avatar_pool")

POOL_DIR = Path("data/avatar_pool")
INDEX = POOL_DIR / "index.json"
MIN_BYTES = 15_000
MAX_BYTES = 6_000_000

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

REDDIT_SUBS = ["aww", "cats", "dogs", "EarthPorn", "mildlyinteresting", "memes", "food"]
PINTEREST_QUERIES = [
    "nature",
    "cute%20dogs",
    "cats",
    "landscape%20photography",
    "funny%20memes",
    "food%20photography",
]
PUBLIC_IG = ["natgeo", "nasa", "bbcearth", "animals.are.awesome"]
PUBLIC_FB = ["NatGeo", "nasa", "bbcearth"]

OG_RE = re.compile(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', re.IGNORECASE)
IMG_RE = re.compile(r'https://i\.pinimg\.com/[^"\'\s]+\.(?:jpg|jpeg|png|webp)', re.IGNORECASE)


@dataclass
class Candidate:
    url: str
    source: str


# --------------------------------------------------------------------------- scrapers


async def reddit_candidates(client: httpx.AsyncClient, limit: int = 20) -> list[Candidate]:
    out: list[Candidate] = []
    seen: set[str] = set()
    for sub in random.sample(REDDIT_SUBS, k=min(3, len(REDDIT_SUBS))):
        try:
            response = await client.get(f"https://www.reddit.com/r/{sub}/top.json", params={"t": "week", "limit": 25})
            if response.status_code != 200:
                continue
            for child in response.json().get("data", {}).get("children", []):
                data = child.get("data", {})
                if data.get("over_18"):
                    continue
                url = data.get("url_overridden_by_dest") or ""
                if not url.lower().split("?")[0].endswith((".jpg", ".jpeg", ".png", ".webp")):
                    continue
                if url in seen:
                    continue
                seen.add(url)
                out.append(Candidate(url, f"reddit/{sub}"))
                if len(out) >= limit:
                    return out
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("reddit_scrape_failed", sub=sub, error=str(exc)[:120])
    return out


async def wikimedia_candidates(client: httpx.AsyncClient, limit: int = 15) -> list[Candidate]:
    try:
        response = await client.get(
            "https://commons.wikimedia.org/w/api.php",
            params={
                "action": "query",
                "generator": "categorymembers",
                "gcmtitle": "Category:Featured_pictures_on_Wikimedia_Commons",
                "gcmtype": "file",
                "gcmlimit": 20,
                "prop": "imageinfo",
                "iiprop": "url",
                "iiurlwidth": 800,
                "format": "json",
            },
        )
        pages = response.json().get("query", {}).get("pages", {})
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("wikimedia_scrape_failed", error=str(exc)[:120])
        return []
    out = []
    for page in pages.values():
        info = (page.get("imageinfo") or [{}])[0]
        url = info.get("thumburl") or info.get("url")
        if url:
            out.append(Candidate(url, "wikimedia"))
        if len(out) >= limit:
            break
    return out


async def pinterest_candidates(client: httpx.AsyncClient, limit: int = 15) -> list[Candidate]:
    seen: set[str] = set()
    out: list[Candidate] = []
    for query in random.sample(PINTEREST_QUERIES, k=min(3, len(PINTEREST_QUERIES))):
        for path in (f"https://www.pinterest.com/ideas/{query}/", f"https://www.pinterest.com/search/pins/?q={query}"):
            try:
                response = await client.get(path)
                if response.status_code != 200:
                    continue
                for url in IMG_RE.findall(response.text):
                    if url in seen:
                        continue
                    seen.add(url)
                    out.append(Candidate(url, "pinterest"))
                    if len(out) >= limit:
                        return out
            except httpx.HTTPError as exc:
                log.warning("pinterest_scrape_failed", error=str(exc)[:120])
    return out


def stock_candidates(limit: int = 6) -> list[Candidate]:
    """Public image services that stay reachable when social sites block scraping."""
    out: list[Candidate] = []
    for _ in range(limit):
        seed = random.randint(1000, 99999)
        out.append(Candidate(f"https://picsum.photos/seed/{seed}/800/800", "stock/picsum"))
        out.append(Candidate("https://cataas.com/cat?width=800&height=800", "stock/cataas"))
    return out[:limit]


async def og_image_candidates(client: httpx.AsyncClient, pages: list[tuple[str, str]], limit: int = 10) -> list[Candidate]:
    out: list[Candidate] = []
    for source, url in pages:
        try:
            response = await client.get(url, follow_redirects=True)
            match = OG_RE.search(response.text)
            if match:
                out.append(Candidate(match.group(1).replace("&amp;", "&"), source))
        except httpx.HTTPError:
            continue
        if len(out) >= limit:
            break
    return out


async def instagram_candidates(client: httpx.AsyncClient, limit: int = 8) -> list[Candidate]:
    pages = [(f"instagram/{user}", f"https://www.instagram.com/{user}/") for user in PUBLIC_IG]
    return await og_image_candidates(client, pages, limit)


async def facebook_candidates(client: httpx.AsyncClient, limit: int = 8) -> list[Candidate]:
    pages = [(f"facebook/{page}", f"https://www.facebook.com/{page}") for page in PUBLIC_FB]
    return await og_image_candidates(client, pages, limit)


# --------------------------------------------------------------------------- pool


def _load_index() -> list[dict]:
    if not INDEX.exists():
        return []
    try:
        return json.loads(INDEX.read_text(encoding="utf-8"))
    except ValueError:
        return []


def pool_size() -> int:
    return len(_load_index())


def _save_index(entries: list[dict]) -> None:
    POOL_DIR.mkdir(parents=True, exist_ok=True)
    INDEX.write_text(json.dumps(entries, ensure_ascii=False, indent=1), encoding="utf-8")


def _existing_hashes(entries: list[dict]) -> set[str]:
    return {entry.get("sha256") for entry in entries if entry.get("sha256")}


def pick_from_pool() -> Path | None:
    entries = _load_index()
    if not entries:
        return None
    entry = random.choice(entries)
    path = POOL_DIR / entry["file"]
    return path if path.exists() else None


async def refill_pool(*, wanted: int = 8, client: httpx.AsyncClient | None = None) -> int:
    """Scrape candidates, download and store the valid ones. Returns how many were added."""
    owned = client is None
    client = client or httpx.AsyncClient(timeout=30, follow_redirects=True, headers=HEADERS, trust_env=False)
    entries = _load_index()
    hashes = _existing_hashes(entries)
    added = 0
    try:
        candidates = []
        for scraper in (pinterest_candidates, reddit_candidates, wikimedia_candidates, instagram_candidates, facebook_candidates):
            try:
                candidates.extend(await scraper(client, limit=wanted))
            except Exception as exc:  # noqa: BLE001
                log.warning("avatar_scraper_failed", scraper=scraper.__name__, error=str(exc)[:120])
            if len(candidates) >= wanted * 3:
                break
        candidates.extend(stock_candidates(limit=max(2, wanted // 2)))
        random.shuffle(candidates)
        for candidate in candidates:
            if added >= wanted:
                break
            try:
                response = await client.get(candidate.url)
            except httpx.HTTPError:
                continue
            if response.status_code != 200:
                continue
            content = response.content
            if not MIN_BYTES <= len(content) <= MAX_BYTES:
                continue
            if not response.headers.get("content-type", "").startswith("image/"):
                continue
            digest = hashlib.sha256(content).hexdigest()
            if digest in hashes:
                continue
            ext = ".jpg"
            if content[:4] == b"\x89PNG":
                ext = ".png"
            elif content[:4] == b"RIFF":
                ext = ".webp"
            name = f"{digest[:16]}{ext}"
            POOL_DIR.mkdir(parents=True, exist_ok=True)
            (POOL_DIR / name).write_bytes(content)
            entries.append({"file": name, "source": candidate.source, "url": candidate.url, "sha256": digest})
            hashes.add(digest)
            added += 1
        if added:
            _save_index(entries)
            log.info("avatar_pool_refilled", added=added, total=len(entries))
    finally:
        if owned:
            await client.aclose()
    return added


async def ensure_pool(*, minimum: int = 5) -> int:
    if pool_size() >= minimum:
        return 0
    return await refill_pool(wanted=max(minimum, 8))
