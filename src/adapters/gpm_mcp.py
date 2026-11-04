"""MCP client for GPM (profile lifecycle only) with HTTP fallback.

The MCP server is a streamable-HTTP JSON-RPC endpoint (default ``http://127.0.0.1:9495/mcp``).
Per section 3.1 MCP never drives the page; browser control always goes through
``connectOverCDP`` in :mod:`adapters.browser`.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from adapters.base import (
    GPMConflict,
    GPMError,
    GPMUnavailable,
    GPMSchemaDrift,
    ProfileDTO,
    StartResult,
)
from adapters.gpm_http import GPMHttpClient
from obs.log import get_logger

log = get_logger("gpm_mcp")


class MCPClient:
    def __init__(self, url: str, token: str = "", timeout: float = 30.0):
        self.url = url
        self.timeout = timeout
        self._id = 0
        self._session_id: str | None = None
        headers = {"Accept": "application/json, text/event-stream"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._client = httpx.Client(timeout=timeout, headers=headers)
        self._initialized = False

    def close(self) -> None:
        self._client.close()

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {}
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        response = self._client.post(self.url, json=payload, headers=headers)
        if sid := response.headers.get("Mcp-Session-Id"):
            self._session_id = sid
        if response.status_code >= 500:
            raise GPMUnavailable(f"MCP {response.status_code}")
        text = response.text.strip()
        if text.startswith("event:") or "\ndata:" in text or text.startswith("data:"):
            # Streamable HTTP may answer with SSE frames; keep the last JSON data frame.
            data_lines = [line[5:].strip() for line in text.splitlines() if line.startswith("data:")]
            if not data_lines:
                raise GPMSchemaDrift("empty SSE response")
            text = data_lines[-1]
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise GPMSchemaDrift(f"MCP non-JSON response: {text[:200]}") from exc

    def _rpc(self, method: str, params: dict[str, Any] | None = None) -> Any:
        self._id += 1
        payload = {"jsonrpc": "2.0", "id": self._id, "method": method}
        if params is not None:
            payload["params"] = params
        result = self._post(payload)
        if "error" in result:
            raise GPMError(str(result["error"].get("message") or result["error"]))
        return result.get("result")

    def initialize(self) -> dict[str, Any]:
        if self._initialized:
            return {"ok": True}
        result = self._rpc(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "yelp-factory", "version": "0.1.0"},
            },
        )
        # Fire-and-forget notification; some servers 202 with an empty body.
        try:
            self._client.post(
                self.url,
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                headers={"Mcp-Session-Id": self._session_id} if self._session_id else {},
            )
        except httpx.HTTPError:
            pass
        self._initialized = True
        return result or {"ok": True}

    def list_tools(self) -> list[dict[str, Any]]:
        self.initialize()
        return (self._rpc("tools/list") or {}).get("tools", [])

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        self.initialize()
        result = self._rpc("tools/call", {"name": name, "arguments": arguments})
        if isinstance(result, dict) and result.get("isError"):
            raise GPMError(str(result))
        content = (result or {}).get("content") or []
        for item in content:
            if item.get("type") == "text":
                try:
                    payload = json.loads(item["text"])
                except json.JSONDecodeError:
                    return item["text"]
                # GPM tools return the same {success,data,message} envelope as the HTTP API.
                if isinstance(payload, dict) and "success" in payload:
                    if not payload["success"]:
                        message = str(payload.get("message", ""))
                        if "exist" in message.lower() or "conflict" in message.lower():
                            raise GPMConflict(message)
                        raise GPMError(message or "MCP tool failed")
                    return payload.get("data")
                return payload
        return result


class HybridGPM:
    """MCP first, local HTTP API as fallback (section 3.1)."""

    def __init__(self, mcp_url: str = "", token: str = "", http_client: GPMHttpClient | None = None):
        self._mcp = MCPClient(mcp_url, token) if mcp_url else None
        self._http = http_client or GPMHttpClient()
        self.last_transport = "http"

    def close(self) -> None:
        if self._mcp:
            self._mcp.close()
        self._http.close()

    def _call(self, tool: str, arguments: dict[str, Any], http_fn, fallback_args: dict[str, Any] | None = None):
        if self._mcp is not None:
            try:
                result = self._mcp.call_tool(tool, arguments)
                self.last_transport = "mcp"
                return result
            except Exception as exc:  # noqa: BLE001 - fallback is intentional
                log.warning("mcp_fallback", tool=tool, error=str(exc)[:200])
        self.last_transport = "http"
        return http_fn(**(fallback_args if fallback_args is not None else arguments))

    # ---------------------------------------------------------------- lifecycle

    def health(self) -> dict[str, Any]:
        try:
            if self._mcp is not None:
                tools = self._mcp.list_tools()
                self.last_transport = "mcp"
                return {"ok": True, "transport": "mcp", "tools": [t.get("name") for t in tools]}
        except Exception as exc:  # noqa: BLE001
            log.warning("mcp_health_failed", error=str(exc)[:200])
        result = self._http.health()
        return {**result, "transport": "http"}

    def list_profiles(self) -> list[ProfileDTO]:
        data = self._call("list_profiles", {"page": 1, "per_page": 500}, self._http.list_profiles, {})
        if isinstance(data, dict):
            items = data.get("data") or data.get("profiles") or []
        elif isinstance(data, list):
            items = data
        else:
            items = []
        return [self._http._to_profile(item) for item in items if isinstance(item, dict)]

    def get_profile(self, profile_id: str) -> ProfileDTO:
        data = self._call("get_profile", {"id": profile_id}, self._http.get_profile, {"profile_id": profile_id})
        if isinstance(data, dict) and data.get("profile"):
            data = data["profile"]
        return self._http._to_profile(data)

    def create_profile(self, name: str, **kwargs: Any) -> ProfileDTO:
        data = self._call(
            "create_profile",
            {"name": name, **kwargs},
            self._http.create_profile,
            {"name": name, **kwargs},
        )
        if isinstance(data, dict) and data.get("profile"):
            data = data["profile"]
        return self._http._to_profile(data)

    def start_profile(self, profile_id: str, **kwargs: Any) -> StartResult:
        data = self._call(
            "start_profile",
            {"id": profile_id, **kwargs},
            self._http.start_profile,
            {"profile_id": profile_id, **kwargs},
        )
        if isinstance(data, dict) and "remote_debugging_port" in data:
            info = data.get("addition_info") or {}
            return StartResult(
                profile_id=data.get("profile_id", profile_id),
                remote_debugging_port=int(data["remote_debugging_port"]),
                process_id=info.get("process_id"),
                driver_path=data.get("driver_path"),
                raw=data,
            )
        raise GPMSchemaDrift("start result missing remote_debugging_port", meta={"data": data})

    def stop_profile(self, profile_id: str) -> None:
        self._call("stop_profile", {"id": profile_id}, self._http.stop_profile, {"profile_id": profile_id})

    def delete_profile(self, profile_id: str, hard: bool = False) -> None:
        self._call(
            "delete_profile",
            {"id": profile_id, "mode": "hard" if hard else "soft"},
            self._http.delete_profile,
            {"profile_id": profile_id, "hard": hard},
        )

    def rename_profile(self, profile_id: str, name: str) -> None:
        self._call(
            "update_profile",
            {"id": profile_id, "name": name},
            self._http.rename_profile,
            {"profile_id": profile_id, "name": name},
        )
