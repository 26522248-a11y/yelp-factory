"""Adapter contracts shared by the real clients and every test double."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


class YFError(Exception):
    """Base error carrying the edge-case code used by the orchestrator."""

    code = "YF"

    def __init__(self, message: str, *, code: str | None = None, meta: dict[str, Any] | None = None):
        super().__init__(message)
        if code:
            self.code = code
        self.meta = meta or {}


class GPMError(YFError):
    code = "gpm_error"


class GPMUnavailable(GPMError):
    """E-01: app down, port changed, HTTP endpoint unreachable."""

    code = "gpm_down"


class GPMConflict(GPMError):
    """E-20: same operation_id, different payload."""

    code = "operation_conflict"


class GPMSchemaDrift(GPMError):
    """E-21: response envelope/fields no longer match the known schema."""

    code = "api_drift"


class BrowserAttachError(YFError):
    """E-02 / E-03: CDP connect failed or the browser died mid-flow."""

    code = "cdp_failed"


class ProxyError(YFError):
    code = "proxy_error"


class ProxyDead(ProxyError):
    code = "proxy_dead"


class GeoMismatch(ProxyError):
    code = "geo_mismatch"


class ProxyTooSlow(ProxyError):
    code = "proxy_slow"


class EmailError(YFError):
    code = "email_error"


class NoVerificationMail(EmailError):
    code = "no_email"


class CaptchaError(YFError):
    code = "captcha"


class CaptchaTimeout(CaptchaError):
    code = "captcha_timeout"


class SMSError(YFError):
    code = "sms_error"


class SelectorMiss(YFError):
    code = "selector_miss"


class FormDrift(YFError):
    code = "form_drift"


class DOMDrift(YFError):
    code = "dom_drift"


@dataclass(slots=True)
class ProfileDTO:
    id: str
    name: str
    raw_proxy: str = ""
    browser_version: str = ""
    os_name: str = "windows"
    created_at: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class StartResult:
    profile_id: str
    remote_debugging_port: int
    process_id: int | None = None
    driver_path: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def cdp_url(self) -> str:
        # GPM Global v1 exposes a debugging port, not a websocket URL (see DEVIATIONS D-01).
        return f"http://127.0.0.1:{self.remote_debugging_port}"


@runtime_checkable
class GPMAdapter(Protocol):
    def health(self) -> dict[str, Any]: ...

    def list_profiles(self) -> list[ProfileDTO]: ...

    def get_profile(self, profile_id: str) -> ProfileDTO: ...

    def create_profile(self, **kwargs: Any) -> ProfileDTO: ...

    def start_profile(self, profile_id: str, **kwargs: Any) -> StartResult: ...

    def stop_profile(self, profile_id: str) -> None: ...

    def delete_profile(self, profile_id: str, hard: bool = False) -> None: ...

    def rename_profile(self, profile_id: str, name: str) -> None: ...
