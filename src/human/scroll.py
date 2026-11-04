"""Randomised scrolling: variable steps with pauses, no two sessions alike."""

from __future__ import annotations

import asyncio
import random


async def scroll_page(page, *, steps: int | None = None, max_px: int = 2400) -> int:
    steps = steps or random.randint(3, 9)
    total = 0
    for _ in range(steps):
        delta = random.randint(120, 420)
        if total + delta > max_px:
            break
        await page.mouse.wheel(0, delta)
        total += delta
        await asyncio.sleep(random.uniform(0.35, 1.6))
        if random.random() < 0.15:  # occasional scroll back up, like a human re-reading
            await page.mouse.wheel(0, -random.randint(40, 180))
            await asyncio.sleep(random.uniform(0.2, 0.9))
    return total
