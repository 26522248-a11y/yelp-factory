"""Direct HTTP access to the local GPM Login API (fallback + primary transport).

GPM Global v1 (``flavor=global-v1``) exposes ``/api/v1`` on port 9495 by default and
writes the real port to ``http.port`` inside ``%APPDATA%\\GPMLoginGlobal`` when 9495 is
taken. The legacy build (``flavor=gpm-v3``) exposes ``/api/v1`` on 19995.
"""

from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import httpx

from adapters.base import (
    GPMConflict,
    GPMError,
    GPMSchemaDrift,
    GPMUnavailable,
    ProfileDTO,
    StartResult,
)
from obs.log import get_logger

log = get_logger("gpm_http")

DEFAULT_PORTS = {"global-v1": 9495, "gpm-v3": 19995}
SCAN_RANGE = range(8000, 10001)
DEFAULT_DATA_DIRS = [
    Path(os.environ.get("APPDATA", "")) / "GPMLoginGlobal",
    Path(os.environ.get("LOCALAPPDATA", "")) / "GPMLoginGlobal",
    Path("C:/GPMLogin"),
]


def _app_is_alive(app: Any) -> bool:
    try:
        return bool(app) and not getattr(app, "is_closed", lambda: True)()
    except Exception:  # pragma: no cover - defensive
        return False


class GPMHttpClient:
    """Thin, synchronous client. One instance per worker."""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        flavor: str = "global-v1",
        timeout: float = 20.0,
        transport: httpx.BaseTransport | None = None,
        data_dirs: list[Path] | None = None,
    ):
        self.flavor = flavor
        self.timeout = timeout
        self._explicit_base = base_url.rstrip("/") if base_url else None
        self._base_url: str | None = None
        self._data_dirs = data_dirs or DEFAULT_DATA_DIRS
        self._client = httpx.Client(
            timeout=httpx.Timeout(timeout, connect=min(timeout, 8.0)),
            transport=transport,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )

    # ------------------------------------------------------------------ transport

    @property
    def base_url(self) -> str:
        if self._base_url:
            return self._base_url
        url = self._explicit_base or self._read_port_file() or self._default_base()
        self._base_url = url
        return url

    def _default_base(self) -> str:
        return f"http://127.0.0.1:{DEFAULT_PORTS.get(self.flavor, 9495)}"

    def _read_port_file(self) -> str | None:
        for directory in self._data_dirs:
            for name in ("http.port", "Data/http.port"):
                candidate = directory / name
                try:
                    if candidate.is_file():
                        port = candidate.read_text(encoding="utf-8", errors="ignore").strip().split()[0]
                        if port.isdigit():
                            return f"http://127.0.0.1:{port}"
                except Exception:
                    continue
        return None

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "GPMHttpClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        url = f"{self.base_url}{path}"
        started = time.perf_counter()
        try:
            response = self._client.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            raise GPMUnavailable(f"GPM request failed: {type(exc).__name__}: {exc}") from exc
        elapsed = (time.perf_counter() - started) * 1000
        log.debug("gpm_request", method=method, path=path, status=response.status_code, ms=round(elapsed))
        return response

    def _call(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self._request(method, path, **kwargs)
        if response.status_code >= 500:
            raise GPMUnavailable(f"GPM {path} -> {response.status_code}")
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise GPMSchemaDrift(f"non-JSON response from {path}", meta={"body": response.text[:500]}) from exc
        if not isinstance(payload, dict) or "success" not in payload:
            raise GPMSchemaDrift("missing success envelope", meta={"payload": payload})
        if not payload["success"]:
            message = str(payload.get("message", ""))
            if "exist" in message.lower() or "conflict" in message.lower() or "duplicat" in message.lower():
                raise GPMConflict(message, meta={"payload": payload})
            raise GPMError(f"GPM {path} failed: {message}", meta={"payload": payload})
        return payload.get("data")

    # ------------------------------------------------------------------ API

    def health(self) -> dict[str, Any]:
        try:
            data = self._call("GET", "/api/v1/groups")
        except GPMError as exc:
            raise GPMUnavailable(str(exc)) from exc
        return {"ok": True, "base_url": self.base_url, "data": data}

    def list_profiles(self) -> list[ProfileDTO]:
        data = self._call("GET", "/api/v1/profiles", params={"page": 1, "per_page": 500})
        items = (data or {}).get("data", [])
        if not isinstance(items, list):
            raise GPMSchemaDrift("profiles payload is not a list")
        return [self._to_profile(item) for item in items]

    def get_profile(self, profile_id: str) -> ProfileDTO:
        data = self._call("GET", f"/api/v1/profiles/{profile_id}")
        if not isinstance(data, dict) or not data.get("id"):
            raise GPMSchemaDrift("profile payload missing id", meta={"payload": data})
        return self._to_profile(data)

    def browser_versions(self) -> list[str]:
        """Ask GPM which browser builds are installed; the create call requires one."""
        try:
            data = self._call("GET", "/api/v1/browsers")
        except GPMError:
            return []
        versions: list[str] = []
        for item in data or []:
            if isinstance(item, dict):
                for key in ("version", "browser_version", "name"):
                    value = item.get(key)
                    if isinstance(value, str) and value.count(".") >= 2:
                        versions.append(value)
                        break
            elif isinstance(item, str) and item.count(".") >= 2:
                versions.append(item)
        return versions

    def resolve_browser_version(self, preferred: str = "") -> str:
        if preferred:
            return preferred
        versions = self.browser_versions()
        if versions:
            return sorted(versions)[-1]
        # last resort: reuse the build of an existing profile
        try:
            for profile in self.list_profiles():
                if profile.browser_version:
                    return profile.browser_version
        except GPMError:
            pass
        return ""

    def create_profile(
        self,
        name: str,
        *,
        raw_proxy: str | None = None,
        browser_version: str = "",
        os_type: int = 1,
        browser_type: int = 1,
        **fingerprint: Any,
    ) -> ProfileDTO:
        body = {
            "name": name,
            "group_id": None,
            "raw_proxy": raw_proxy or "",
            "browser_type": browser_type,
            "browser_version": browser_version or self.resolve_browser_version(),
            "os_type": os_type,
            "custom_user_agent": None,
            "task_bar_title": None,
            "webrtc_mode": fingerprint.pop("webrtc_mode", 1),
            "fixed_webrtc_public_ip": "",
            "geolocation_mode": None,
            "canvas_mode": fingerprint.pop("canvas_mode", 1),
            "client_rect_mode": fingerprint.pop("client_rect_mode", 1),
            "webgl_image_mode": fingerprint.pop("webgl_image_mode", 1),
            "webgl_metadata_mode": fingerprint.pop("webgl_metadata_mode", 1),
            "audio_mode": fingerprint.pop("audio_mode", 1),
            "font_mode": fingerprint.pop("font_mode", 1),
            "timezone_base_on_ip": fingerprint.pop("timezone_base_on_ip", True),
            "timezone": fingerprint.pop("timezone", None),
            "is_language_base_on_ip": fingerprint.pop("is_language_base_on_ip", True),
            "fixed_language": fingerprint.pop("fixed_language", None),
        }
        body.update(fingerprint)
        data = self._call("POST", "/api/v1/profiles/create", json=body)
        if not isinstance(data, dict) or not data.get("id"):
            raise GPMSchemaDrift("create response missing id", meta={"payload": data})
        return self._to_profile(data)

    def start_profile(
        self,
        profile_id: str,
        *,
        remote_debugging_port: int = 0,
        window_size: str = "1280,800",
        window_scale: float = 1.0,
        skip_proxy_check: bool = True,
        addition_args: str = "",
    ) -> StartResult:
        params = {
            "remote_debugging_port": remote_debugging_port,
            "window_size": window_size,
            "window_scale": window_scale,
            "addition_args": addition_args,
        }
        if skip_proxy_check:
            # Not documented on every build; older builds simply ignore it.
            params["skip_proxy_check"] = "true"
        data = self._call("GET", f"/api/v1/profiles/start/{profile_id}", params=params)
        if not isinstance(data, dict) or "remote_debugging_port" not in data:
            raise GPMSchemaDrift("start response missing remote_debugging_port", meta={"payload": data})
        info = data.get("addition_info") or {}
        return StartResult(
            profile_id=data.get("profile_id", profile_id),
            remote_debugging_port=int(data["remote_debugging_port"]),
            process_id=info.get("process_id"),
            driver_path=data.get("driver_path"),
            raw=data,
        )

    def stop_profile(self, profile_id: str) -> None:
        try:
            self._call("GET", f"/api/v1/profiles/stop/{profile_id}")
        except GPMError as exc:
            # Stopping an already-closed profile answers success:false with message "OK".
            text = str(exc).lower()
            if "not running" in text or "not found" in text or text.rstrip().endswith("failed: ok"):
                log.warning("gpm_stop_noop", profile_id=profile_id)
                return
            raise

    def delete_profile(self, profile_id: str, hard: bool = False) -> None:
        try:
            self._call("GET", f"/api/v1/profiles/delete/{profile_id}", params={"mode": "hard" if hard else "soft"})
        except GPMError as exc:
            # GPM answers success:false with a "0/1" progress string when the profile is
            # still winding down; the deletion itself is queued, so this is not fatal.
            if str(exc).strip().endswith("/1") or "0/1" in str(exc):
                log.warning("gpm_delete_queued", profile_id=profile_id)
                return
            raise

    def rename_profile(self, profile_id: str, name: str) -> None:
        self._call("POST", f"/api/v1/profiles/update/{profile_id}", json={"name": name})

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _to_profile(item: dict[str, Any]) -> ProfileDTO:
        browser = item.get("browser") or {}
        return ProfileDTO(
            id=str(item.get("id", "")),
            name=str(item.get("name", "")),
            raw_proxy=str(item.get("raw_proxy") or ""),
            browser_version=str(browser.get("version") or ""),
            os_name=str(item.get("os") or "windows"),
            created_at=item.get("created_at"),
            extra=item,
        )


def discover_base_url(flavor: str = "global-v1", timeout: float = 0.4) -> str | None:
    """Scan 8000-10000 for a live GPM local API (E-01)."""
    client = GPMHttpClient(flavor=flavor, timeout=timeout)

    def probe(port: int) -> str | None:
        try:
            response = httpx.get(
                f"http://127.0.0.1:{port}/api/v1/groups",
                timeout=timeout,
                trust_env=False,
            )
            if response.status_code == 200:
                payload = response.json()
                sender = str(payload.get("sender", ""))
                if payload.get("success") and "gpm" in sender.lower():
                    return f"http://127.0.0.1:{port}"
        except Exception:
            return None
        return None

    try:
        with ThreadPoolExecutor(max_workers=64) as pool:
            for result in pool.map(probe, SCAN_RANGE):
                if result:
                    log.warning("gpm_port_discovered", url=result)
                    return result
    finally:
        client.close()
    return None


def restart_gpm_app() -> bool:
    """Best effort restart; only used when the executable path is known (E-01)."""
    candidates = [d / "GPMLoginGlobal.exe" for d in DEFAULT_DATA_DIRS]
    for exe in candidates:
        if exe.is_file():
            import subprocess

            try:
                subprocess.Popen([str(exe)], close_fds=True)  # noqa: S603
                return True
            except Exception as exc:  # pragma: no cover
                log.error("gpm_restart_failed", error=str(exc))
    return False
