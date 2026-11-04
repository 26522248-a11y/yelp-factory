"""Stateful fake of the GPM local API, wired as an httpx transport.

It speaks the real envelope (``success/data/message/sender``) and can inject
``success:false`` answers, schema drift and port moves, without opening a socket.
"""

from __future__ import annotations

import itertools
import json
import uuid
from typing import Any

import httpx

SENDER = "GPMLoginGlobal v5.1.1-stable"


class FakeGPMTransport(httpx.BaseTransport):
    def __init__(self) -> None:
        self.profiles: dict[str, dict[str, Any]] = {}
        self.started: dict[str, int] = {}
        self.calls: list[tuple[str, str]] = []
        self.fail_create = False
        self.drift = False
        self._ports = itertools.count(41000)
        self._ids = itertools.count(1)

    # ------------------------------------------------------------------ transport

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        method = request.method
        self.calls.append((method, path))

        if self.drift:
            return httpx.Response(200, json={"ok": True, "result": []})

        if path == "/api/v1/groups":
            return self._ok({"current_page": 1, "per_page": 30, "total": 1, "last_page": 1, "data": []})

        if path == "/api/v1/profiles" and method == "GET":
            return self._ok({"current_page": 1, "per_page": 500, "total": len(self.profiles), "last_page": 1, "data": list(self.profiles.values())})

        if path == "/api/v1/profiles/create" and method == "POST":
            body = json.loads(request.content)
            if self.fail_create:
                return httpx.Response(200, json={"success": False, "data": None, "message": "Profile name already exists"})
            profile_id = str(uuid.uuid4())
            self.profiles[profile_id] = {
                "id": profile_id,
                "name": body["name"],
                "group_id": None,
                "storage_path": profile_id,
                "raw_proxy": body.get("raw_proxy", ""),
                "browser": {"name": "chrome", "version": body.get("browser_version", "153.0.8010.53")},
                "os": "windows",
                "created_at": "2026-11-04 10:00:00",
                "updated_at": "2026-11-04 10:00:00",
                "tags": [],
            }
            return self._ok(self.profiles[profile_id])

        if path.startswith("/api/v1/profiles/start/"):
            profile_id = path.rsplit("/", 1)[-1]
            if profile_id not in self.profiles:
                return httpx.Response(404, json={"success": False, "message": "not found", "data": None})
            port = int(next(self._ports))
            self.started[profile_id] = port
            return self._ok(
                {
                    "profile_id": profile_id,
                    "driver_path": "C:/gpm/gpmdriver.exe",
                    "remote_debugging_port": port,
                    "addition_info": {"process_id": next(self._ids) + 5000, "profile_name": self.profiles[profile_id]["name"]},
                }
            )

        if path.startswith("/api/v1/profiles/stop/"):
            profile_id = path.rsplit("/", 1)[-1]
            self.started.pop(profile_id, None)
            return self._ok(None)

        if path.startswith("/api/v1/profiles/delete/"):
            profile_id = path.rsplit("/", 1)[-1]
            self.profiles.pop(profile_id, None)
            return self._ok(None)

        if path.startswith("/api/v1/profiles/") and method == "GET":
            profile_id = path.rsplit("/", 1)[-1]
            if profile_id not in self.profiles:
                return httpx.Response(404, json={"success": False, "message": "not found", "data": None})
            return self._ok(self.profiles[profile_id])

        return httpx.Response(404, json={"success": False, "message": f"unhandled {method} {path}", "data": None})

    @staticmethod
    def _ok(data: Any) -> httpx.Response:
        return httpx.Response(200, json={"success": True, "data": data, "message": "OK", "sender": SENDER})
