"""RAM/CPU governor: keeps concurrency below the machine limits (E-22, section 11)."""

from __future__ import annotations

import asyncio
import math
import os
from dataclasses import dataclass, field

import psutil

from obs.log import get_logger

log = get_logger("governor")


def ram_gb() -> float:
    return psutil.virtual_memory().total / (1024**3)


def hard_profile_cap(configured: int = 8) -> int:
    return max(1, min(configured, int(ram_gb() // 2)))


@dataclass
class Governor:
    max_profiles: int = 8
    ram_guard_pct: float = 85.0
    workers: int = 8
    _semaphore: asyncio.Semaphore = field(init=False)
    active: int = 0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    def __post_init__(self) -> None:
        cap = hard_profile_cap(self.max_profiles)
        if cap != self.max_profiles:
            log.warning("profile_cap_reduced", configured=self.max_profiles, cap=cap, ram_gb=round(ram_gb(), 1))
        self.max_profiles = cap
        self.workers = min(self.workers, cap)
        self._semaphore = asyncio.Semaphore(cap)

    # ------------------------------------------------------------------ checks

    def ram_pressure(self) -> bool:
        return psutil.virtual_memory().percent >= self.ram_guard_pct

    def disk_free_gb(self, path: str = ".") -> float:
        return psutil.disk_usage(path).free / (1024**3)

    def desired_concurrency(self) -> int:
        """Shrink concurrency when RAM is tight instead of crashing (E-22)."""
        if self.ram_pressure():
            return max(1, self.max_profiles // 2)
        return self.max_profiles

    # ------------------------------------------------------------------ slots

    async def acquire(self) -> None:
        while self.ram_pressure():
            log.warning("ram_guard_wait", pct=psutil.virtual_memory().percent)
            await asyncio.sleep(5)
        await self._semaphore.acquire()
        async with self._lock:
            self.active += 1

    def release(self) -> None:
        self._semaphore.release()
        self.active = max(0, self.active - 1)

    async def __aenter__(self):
        await self.acquire()
        return self

    async def __aexit__(self, *exc):
        self.release()

    def snapshot(self) -> dict:
        mem = psutil.virtual_memory()
        return {
            "ram_gb": round(ram_gb(), 1),
            "ram_used_pct": mem.percent,
            "cpu_pct": psutil.cpu_percent(interval=0.1),
            "max_profiles": self.max_profiles,
            "active": self.active,
            "disk_free_gb": round(self.disk_free_gb(), 1),
            "pid": os.getpid(),
        }


def suggest_workers(configured: int) -> int:
    return min(configured, hard_profile_cap(configured), max(1, math.floor(ram_gb() / 2)))
