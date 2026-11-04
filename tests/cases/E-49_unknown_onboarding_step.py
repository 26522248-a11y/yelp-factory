"""E-49: unknown onboarding step -> Skip/Next, at most five steps, never stuck."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from core.state_machine import StageContext
from db.models import AccountState
from flows.signup import SignupFlow
from selector_registry.resolver import SelectorRegistry, SelectorRule
from tests.fakes import FakeBrowser, FakeGPM

pytestmark = pytest.mark.asyncio


async def test_E49_skips_at_most_five_steps(settings, fake_page_factory):
    page = fake_page_factory()
    # "Skip" always resolves, so without the cap the loop would never end.
    page.add("text=Skip", visible=True)
    browser = FakeBrowser()
    browser.page = page
    registry = SelectorRegistry({"onboarding.skip": [SelectorRule("text", "Skip", 1)]})

    flow = SignupFlow(settings=settings, gpm=FakeGPM(), registry=registry, email_provider=None)
    ctx = StageContext(account_id=uuid.uuid4(), run_id=uuid.uuid4(), state=AccountState.ONBOARDED)
    ctx.data.update(
        {
            "browser": browser,
            "persona": type("P", (), {"city": "Delray Beach, FL"})(),
            "avatar_path": Path("nonexistent.jpg"),
        }
    )
    result = await flow._enter_onboarded(ctx)
    assert result["onboarding_steps"] == 5
