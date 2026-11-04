"""Re-authentication when the GPM profile lost its Yelp session (E-50)."""

from __future__ import annotations

from adapters.base import YFError
from core.backoff import RetryPolicy
from core.state_machine import Stage
from db.models import AccountState
from human.mouse import human_click
from human.typing import human_type
from obs.log import get_logger

log = get_logger("flows.reauth")

LOGIN_URL = "https://www.yelp.com/login?locale=en_US"


class ReauthFlow:
    def __init__(self, *, gpm, registry, settings):
        self.gpm = gpm
        self.registry = registry
        self.settings = settings

    def stages(self) -> list[Stage]:
        return [
            Stage(AccountState.WARMING, self._enter_warm, retry=RetryPolicy(max_attempts=2)),
        ]

    async def _enter_warm(self, ctx):
        browser = ctx.data.get("browser")
        if browser is None:
            raise YFError("reauth requires an attached browser", code="cdp_failed")
        page = browser.page
        await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=45_000)
        persona = ctx.data["persona"]
        await human_type(await self.registry.find(page, "login.email"), persona.email_alias)
        await human_type(await self.registry.find(page, "login.password"), persona.password)
        await human_click(page, await self.registry.find(page, "login.submit"))
        await page.wait_for_load_state("domcontentloaded", timeout=30_000)
        cookies = await browser.context.cookies()
        if not any(c.get("name", "").startswith("yelp-user-id") for c in cookies):
            # Two failed reauths mean the account is gone, not that we should keep trying.
            raise YFError("reauth failed twice", code="reauth_failed")
        return {"reauth": True}
