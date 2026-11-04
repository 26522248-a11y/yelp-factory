"""Post-verification onboarding: avatar, city, follow 3-5 businesses, save one (E-49)."""

from __future__ import annotations

import random
from pathlib import Path

from adapters.base import YFError
from core.state_machine import Stage
from db.models import AccountState
from human.mouse import human_click
from human.scroll import scroll_page
from obs.log import get_logger

log = get_logger("flows.onboarding")

MAX_STEPS = 5


class OnboardingFlow:
    def __init__(self, *, registry, settings, avatar_path: Path | None = None):
        self.registry = registry
        self.settings = settings
        self.avatar_path = avatar_path or (Path(settings.artifacts_dir) / "avatar.jpg")

    async def enter(self, ctx) -> dict:
        browser = ctx.data.get("browser")
        if browser is None:
            raise YFError("onboarding requires a browser", code="cdp_failed")
        page = browser.page
        steps = 0

        # Unknown onboarding steps are skipped with Skip/Next, up to five (E-49).
        while steps < MAX_STEPS:
            button = await self.registry.find(page, "onboarding.skip", required=False, timeout_ms=2500)
            if button is None:
                break
            await human_click(page, button, dwell=(250, 700))
            steps += 1

        if self.avatar_path.exists():
            upload = await self.registry.find(page, "onboarding.avatar", required=False, timeout_ms=2000)
            if upload is not None:
                try:
                    await upload.set_input_files(str(self.avatar_path))
                except Exception as exc:  # noqa: BLE001
                    log.warning("avatar_upload_failed", error=str(exc)[:150])

        city_input = await self.registry.find(page, "onboarding.city", required=False, timeout_ms=2500)
        if city_input is not None:
            await city_input.fill(ctx.data["persona"].city)
            option = await self.registry.find(page, "onboarding.city_option", required=False, timeout_ms=2000)
            if option is not None:
                await option.click()

        followed = 0
        for _ in range(random.randint(3, 5)):
            card = await self.registry.find(page, "onboarding.business_card", required=False, timeout_ms=2000)
            if card is None:
                break
            await human_click(page, card)
            follow = await self.registry.find(page, "onboarding.follow_user", required=False, timeout_ms=1500)
            if follow is not None:
                await follow.click()
                followed += 1
            await page.go_back(wait_until="domcontentloaded")

        save = await self.registry.find(page, "onboarding.save_business", required=False, timeout_ms=2000)
        if save is not None:
            await human_click(page, save)

        await scroll_page(page, steps=2)
        return {"steps": steps, "followed": followed}
