"""Lightweight Playwright/page doubles used by unit and edge-case tests."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from adapters.base import ProfileDTO, StartResult


@dataclass
class FakeLocator:
    page: "FakePage"
    selector: str
    text: str = ""
    visible: bool = True
    value: str = ""
    click_errors: list[Exception] = field(default_factory=list)
    clicks: int = 0
    fills: list[str] = field(default_factory=list)
    typed: list[str] = field(default_factory=list)

    @property
    def first(self) -> "FakeLocator":
        return self

    async def count(self) -> int:
        return 1 if self.visible or self.click_errors else 0

    async def is_visible(self, timeout: int | None = None) -> bool:
        return self.visible

    async def all_inner_texts(self) -> list[str]:
        return [self.text] if self.text else []

    async def fill(self, value: str) -> None:
        self.value = value
        self.fills.append(value)
        self.page.events.append(("fill", self.selector, value))

    async def type(self, value: str) -> None:
        self.value += value
        self.typed.append(value)
        self.page.events.append(("type", self.selector, value))

    async def press(self, key: str) -> None:
        self.page.events.append(("press", self.selector, key))

    async def click(self, timeout: int | None = None, force: bool = False) -> None:
        self.clicks += 1
        if self.click_errors and not force:
            raise self.click_errors.pop(0)
        self.page.events.append(("click", self.selector, force))

    async def bounding_box(self) -> dict[str, float] | None:
        return {"x": 10.0, "y": 20.0, "width": 100.0, "height": 30.0}

    async def evaluate(self, script: str, arg: Any = None) -> None:
        self.page.events.append(("evaluate", self.selector, arg))

    async def set_input_files(self, path: str) -> None:
        self.page.events.append(("upload", self.selector, path))


class FakePage:
    def __init__(self, url: str = "https://www.yelp.com/signup", html: str = ""):
        self.url = url
        self.html = html
        self.events: list[tuple] = []
        self.locators: dict[str, FakeLocator] = {}
        self.frames: list[Any] = []
        self.closed = False
        self.mouse = FakeMouse(self)
        self.reloads = 0
        self.gotos: list[str] = []
        self._context: FakeContext | None = None

    # ------------------------------------------------------------------ locators

    def locator(self, selector: str) -> FakeLocator:
        # Unknown selectors must behave like a real miss, not like a magic element.
        return self.locators.setdefault(selector, FakeLocator(self, selector, visible=False))

    def get_by_label(self, value: str, exact: bool = False) -> FakeLocator:
        return self.locators.setdefault(f"label={value}", FakeLocator(self, f"label={value}", visible=False))

    def get_by_placeholder(self, value: str, exact: bool = False) -> FakeLocator:
        return self.locators.setdefault(f"placeholder={value}", FakeLocator(self, f"placeholder={value}", visible=False))

    def get_by_text(self, value: str, exact: bool = False) -> FakeLocator:
        return self.locators.setdefault(f"text={value}", FakeLocator(self, f"text={value}", visible=False))

    def get_by_role(self, value: str) -> FakeLocator:
        return self.locators.setdefault(f"role={value}", FakeLocator(self, f"role={value}", visible=False))

    def add(self, selector: str, **kwargs) -> FakeLocator:
        loc = FakeLocator(self, selector, **kwargs)
        self.locators[selector] = loc
        return loc

    async def hide(self, selector: str) -> None:
        self.locators.pop(selector, None)

    # ------------------------------------------------------------------ navigation

    async def goto(self, url: str, **kwargs: Any) -> None:
        self.gotos.append(url)
        self.url = url
        self.events.append(("goto", url))

    async def reload(self, **kwargs: Any) -> None:
        self.reloads += 1
        self.events.append(("reload",))

    async def go_back(self, **kwargs: Any) -> None:
        self.events.append(("back",))

    async def content(self) -> str:
        return self.html

    async def title(self) -> str:
        return "Fake Yelp"

    async def wait_for_load_state(self, *args: Any, **kwargs: Any) -> None:
        return None

    async def wait_for_timeout(self, ms: int) -> None:
        await asyncio.sleep(0)

    async def set_viewport_size(self, size: dict) -> None:
        self.events.append(("viewport", size))

    async def evaluate(self, script: str, arg: Any = None) -> Any:
        self.events.append(("evaluate", script[:60], arg))
        if "g-recaptcha-response" in script and isinstance(arg, str):
            for key, loc in self.locators.items():
                if "captcha" in key:
                    loc.value = arg
        if "value && n.value.length > 20" in script:
            return any(loc.value for key, loc in self.locators.items() if "captcha" in key)
        return True

    def is_closed(self) -> bool:
        return self.closed

    async def close(self) -> None:
        self.closed = True
        if self._context is not None and self in self._context.pages:
            self._context.pages.remove(self)


class FakeMouse:
    def __init__(self, page: FakePage):
        self.page = page
        self.moves: list[tuple[float, float]] = []

    async def move(self, x: float, y: float) -> None:
        self.moves.append((x, y))

    async def click(self, x: float, y: float) -> None:
        self.page.events.append(("mouse_click", x, y))

    async def wheel(self, dx: int, dy: int) -> None:
        self.page.events.append(("wheel", dx, dy))


class FakeContext:
    def __init__(self, pages: list[FakePage] | None = None, cookies: list[dict] | None = None):
        self.pages = pages or [FakePage()]
        for page in self.pages:
            page._context = self
        self.cookies_value = cookies if cookies is not None else [{"name": "yelp-user-id", "value": "u1"}]
        self.closed = False

    async def cookies(self) -> list[dict]:
        return self.cookies_value

    async def new_page(self) -> FakePage:
        page = FakePage()
        page._context = self
        self.pages.append(page)
        return page


class FakeBrowser:
    def __init__(self, context: FakeContext | None = None):
        self.context = context or FakeContext()
        self.contexts = [self.context]
        self.closed = False

    @property
    def page(self) -> FakePage:
        return self.context.pages[0]

    @page.setter
    def page(self, value: FakePage) -> None:
        if not self.context.pages:
            self.context.pages.append(value)
        else:
            self.context.pages[0] = value
        value._context = self.context

    async def close(self) -> None:
        self.closed = True


@dataclass
class FakeGPM:
    profiles: list[ProfileDTO] = field(default_factory=list)
    started: list[StartResult] = field(default_factory=list)
    fail_health: bool = False
    fail_start: bool = False
    create_calls: list[dict] = field(default_factory=list)
    stopped: list[str] = field(default_factory=list)
    last_transport: str = "http"

    def health(self):
        if self.fail_health:
            raise RuntimeError("gpm down")
        return {"ok": True}

    def list_profiles(self):
        return list(self.profiles)

    def get_profile(self, profile_id):
        for profile in self.profiles:
            if profile.id == profile_id:
                return profile
        raise KeyError(profile_id)

    def create_profile(self, name: str, **kwargs):
        self.create_calls.append({"name": name, **kwargs})
        profile = ProfileDTO(id=f"p{len(self.profiles) + 1}", name=name, raw_proxy=kwargs.get("raw_proxy", ""))
        self.profiles.append(profile)
        return profile

    def start_profile(self, profile_id: str, **kwargs):
        if self.fail_start:
            from adapters.base import GPMUnavailable

            raise GPMUnavailable("start failed")
        result = StartResult(profile_id=profile_id, remote_debugging_port=45000, process_id=1234, raw={})
        self.started.append(result)
        return result

    def stop_profile(self, profile_id: str):
        self.stopped.append(profile_id)

    def delete_profile(self, profile_id: str, hard: bool = False):
        self.profiles = [p for p in self.profiles if p.id != profile_id]

    def rename_profile(self, profile_id: str, name: str):
        return None

    def close(self):
        return None
