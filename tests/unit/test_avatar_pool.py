"""Avatar pool scrapers: parsing + validation with mocked HTTP (no network in tests)."""

from __future__ import annotations

import json

import httpx
import pytest

from flows import avatar_sources as av

pytestmark = pytest.mark.asyncio


def test_og_image_regex():
    html = '<meta property="og:image" content="https://cdn.example.com/a.jpg">'
    assert av.OG_RE.search(html).group(1) == "https://cdn.example.com/a.jpg"


def test_pinterest_regex():
    html = 'src="https://i.pinimg.com/564x/ab/cd/ef.jpg" and "https://i.pinimg.com/originals/11/22/33.png"'
    found = av.IMG_RE.findall(html)
    assert len(found) == 2


async def test_reddit_candidates_parses_json():
    payload = {
        "data": {
            "children": [
                {"data": {"over_18": False, "url_overridden_by_dest": "https://i.redd.it/a.jpg"}},
                {"data": {"over_18": True, "url_overridden_by_dest": "https://i.redd.it/nsfw.jpg"}},
                {"data": {"over_18": False, "url_overridden_by_dest": "https://v.redd.it/video"}},
            ]
        }
    }

    def handler(request):
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        candidates = await av.reddit_candidates(client, limit=5)
    assert [c.url for c in candidates] == ["https://i.redd.it/a.jpg"]
    assert candidates[0].source.startswith("reddit/")


async def test_wikimedia_candidates_parses_api():
    payload = {
        "query": {
            "pages": {
                "1": {"imageinfo": [{"thumburl": "https://upload.wikimedia.org/a.jpg"}]},
                "2": {"imageinfo": [{"url": "https://upload.wikimedia.org/b.jpg"}]},
            }
        }
    }

    def handler(request):
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        candidates = await av.wikimedia_candidates(client, limit=5)
    assert len(candidates) == 2
    assert all(c.source == "wikimedia" for c in candidates)


async def test_refill_pool_validates_and_dedupes(tmp_path, monkeypatch):
    monkeypatch.setattr(av, "POOL_DIR", tmp_path)
    monkeypatch.setattr(av, "INDEX", tmp_path / "index.json")

    good = b"\xff\xd8\xff" + b"x" * 20_000
    small = b"\xff\xd8\xff" + b"x" * 100

    async def fake_scraper(client, limit=10):
        return [av.Candidate("https://cdn.example.com/good.jpg", "test"), av.Candidate("https://cdn.example.com/small.jpg", "test")]

    def handler(request):
        if "small" in str(request.url):
            return httpx.Response(200, content=small, headers={"content-type": "image/jpeg"})
        return httpx.Response(200, content=good, headers={"content-type": "image/jpeg"})

    monkeypatch.setattr(av, "reddit_candidates", fake_scraper)
    for name in ("pinterest_candidates", "wikimedia_candidates", "instagram_candidates", "facebook_candidates"):
        async def empty(client, limit=10):
            return []

        monkeypatch.setattr(av, name, empty)
    monkeypatch.setattr(av, "stock_candidates", lambda limit=6: [])
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        added = await av.refill_pool(wanted=5, client=client)
        assert added == 1
        # Second pass must dedupe by sha256.
        again = await av.refill_pool(wanted=5, client=client)
    assert again == 0
    index = json.loads((tmp_path / "index.json").read_text())
    assert len(index) == 1
    assert index[0]["source"] == "test"


async def test_pick_from_pool_returns_none_when_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(av, "POOL_DIR", tmp_path)
    monkeypatch.setattr(av, "INDEX", tmp_path / "index.json")
    assert av.pick_from_pool() is None
