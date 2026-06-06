"""
Minimal MCP (Model Context Protocol) client over the *Streamable HTTP*
transport, used to talk to Hack The Box's official CTF MCP server.

Only the small slice of MCP that Koshary needs is implemented:

* ``initialize`` (+ ``notifications/initialized``)
* ``tools/list``
* ``tools/call``

Responses may arrive as a single JSON object or as Server-Sent Events; both are
handled. The bearer token is registered for redaction and is never logged.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, Optional

import requests

from core.logging_utils import StreamLogger, register_secret

PROTOCOL_VERSION = "2025-06-18"


class MCPError(RuntimeError):
    """Raised when the MCP server returns a JSON-RPC error or invalid data."""


class MCPClient:
    def __init__(self, url: str, token: str, logger: Optional[StreamLogger] = None,
                 timeout: int = 60, max_retries: int = 3):
        self.url = url
        self._token = token
        self.timeout = timeout
        self.max_retries = max_retries
        self.log = logger or StreamLogger("htb_mcp")
        self.session_id: Optional[str] = None
        self.tools: Dict[str, dict] = {}
        self._id = 0
        self._http = requests.Session()
        self._initialized = False

        # Never leak the token to logs.
        register_secret(token)
        register_secret(f"Bearer {token}")

    # ------------------------------------------------------------------ #
    # Low-level transport
    # ------------------------------------------------------------------ #
    def _headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {self._token}",
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        if self._initialized:
            headers["MCP-Protocol-Version"] = PROTOCOL_VERSION
        return headers

    def _next_id(self) -> int:
        self._id += 1
        return self._id

    @staticmethod
    def _parse_body(resp: requests.Response) -> Optional[dict]:
        """Return the JSON-RPC payload from a JSON or SSE response body."""
        ctype = resp.headers.get("Content-Type", "")
        text = resp.text or ""
        if "text/event-stream" in ctype:
            # Collect the last `data:` JSON payload that parses as a JSON-RPC msg.
            payload: Optional[dict] = None
            data_lines: list[str] = []
            for line in text.splitlines():
                if line.startswith("data:"):
                    data_lines.append(line[len("data:"):].strip())
                elif line.strip() == "" and data_lines:
                    chunk = "\n".join(data_lines)
                    data_lines = []
                    try:
                        msg = json.loads(chunk)
                        if isinstance(msg, dict) and ("result" in msg or "error" in msg):
                            payload = msg
                    except json.JSONDecodeError:
                        pass
            if data_lines:
                try:
                    msg = json.loads("\n".join(data_lines))
                    if isinstance(msg, dict):
                        payload = msg
                except json.JSONDecodeError:
                    pass
            return payload
        if not text.strip():
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise MCPError(f"Invalid JSON from MCP server: {exc}") from exc

    def _post(self, body: dict, expect_response: bool = True) -> Optional[dict]:
        last_err: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self._http.post(
                    self.url, headers=self._headers(),
                    data=json.dumps(body), timeout=self.timeout,
                )
                # Capture / refresh the session id.
                sid = resp.headers.get("Mcp-Session-Id")
                if sid:
                    self.session_id = sid
                if resp.status_code >= 400:
                    raise MCPError(
                        f"MCP HTTP {resp.status_code} for method "
                        f"'{body.get('method')}': {resp.text[:300]}"
                    )
                if not expect_response:
                    return None
                payload = self._parse_body(resp)
                if payload is None:
                    raise MCPError(f"Empty MCP response for '{body.get('method')}'")
                if "error" in payload:
                    err = payload["error"]
                    raise MCPError(
                        f"MCP error {err.get('code')}: {err.get('message')}"
                    )
                return payload.get("result", {})
            except (requests.RequestException, MCPError) as exc:
                last_err = exc
                if attempt < self.max_retries:
                    self.log.warn(
                        f"MCP call '{body.get('method')}' failed "
                        f"(attempt {attempt}/{self.max_retries}): {exc}"
                    )
                    time.sleep(min(2 ** attempt, 8))
        raise MCPError(str(last_err))

    # ------------------------------------------------------------------ #
    # MCP lifecycle
    # ------------------------------------------------------------------ #
    def initialize(self) -> dict:
        body = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "clientInfo": {"name": "koshary", "version": "0.1"},
            },
        }
        result = self._post(body) or {}
        self._initialized = True
        # Notify the server that initialization completed.
        try:
            self._post(
                {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
                expect_response=False,
            )
        except MCPError:
            pass
        self.log.ok("MCP session initialized.")
        return result

    def list_tools(self, force: bool = False) -> Dict[str, dict]:
        if self.tools and not force:
            return self.tools
        if not self._initialized:
            self.initialize()
        body = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/list",
            "params": {},
        }
        result = self._post(body) or {}
        tools = result.get("tools", [])
        self.tools = {t["name"]: t for t in tools if isinstance(t, dict) and "name" in t}
        self.log.info(f"Discovered {len(self.tools)} MCP tool(s).")
        return self.tools

    def call_tool(self, name: str, arguments: Optional[dict] = None) -> dict:
        if not self._initialized:
            self.initialize()
        body = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}},
        }
        result = self._post(body) or {}
        if result.get("isError"):
            text = self._content_text(result)
            raise MCPError(f"Tool '{name}' returned an error: {text[:300]}")
        return result

    # ------------------------------------------------------------------ #
    # Result helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _content_text(result: dict) -> str:
        parts = []
        for item in result.get("content", []) or []:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))
        return "\n".join(parts)

    @classmethod
    def result_to_data(cls, result: dict) -> Any:
        """Best-effort extraction of structured data from a tool result.

        Prefers ``structuredContent`` when present, otherwise parses the first
        text content block as JSON, otherwise returns the raw text.
        """
        if not isinstance(result, dict):
            return result
        if "structuredContent" in result and result["structuredContent"] is not None:
            return result["structuredContent"]
        text = cls._content_text(result)
        if not text:
            return result
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

    def close(self) -> None:
        try:
            self._http.close()
        except Exception:
            pass
