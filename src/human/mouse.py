"""Bezier mouse movement with dwell-before-click (section 9)."""

from __future__ import annotations

import asyncio
import math
import random


def _bezier(p0, p1, p2, p3, steps: int = 24):
    for i in range(steps + 1):
        t = i / steps
        x = (1 - t) ** 3 * p0[0] + 3 * (1 - t) ** 2 * t * p1[0] + 3 * (1 - t) * t**2 * p2[0] + t**3 * p3[0]
        y = (1 - t) ** 3 * p0[1] + 3 * (1 - t) ** 2 * t * p1[1] + 3 * (1 - t) * t**2 * p2[1] + t**3 * p3[1]
        yield x, y


async def move_to(page, x: float, y: float, *, start: tuple[float, float] | None = None, steps: int = 24) -> None:
    start = start or (random.uniform(20, 400), random.uniform(20, 400))
    c1 = (start[0] + random.uniform(-120, 120), start[1] + random.uniform(-120, 120))
    c2 = (x + random.uniform(-120, 120), y + random.uniform(-120, 120))
    for px, py in _bezier(start, c1, c2, (x, y), steps):
        await page.mouse.move(px, py)
        await asyncio.sleep(random.uniform(0.004, 0.018))


async def human_click(page, locator, *, dwell: tuple[int, int] = (300, 900)) -> None:
    box = await locator.bounding_box()
    if box:
        x = box["x"] + box["width"] * random.uniform(0.35, 0.65)
        y = box["y"] + box["height"] * random.uniform(0.35, 0.65)
        await move_to(page, x, y)
        await asyncio.sleep(random.uniform(*dwell) / 1000)
        await page.mouse.click(x, y)
    else:
        await asyncio.sleep(random.uniform(*dwell) / 1000)
        await locator.click()
    await asyncio.sleep(random.uniform(0.1, 0.35))


async def read_pause(page, *, seconds: tuple[float, float] = (2.0, 5.0)) -> None:
    """Reading dwell between actions."""
    await page.wait_for_timeout(int(random.uniform(*seconds) * 1000))
