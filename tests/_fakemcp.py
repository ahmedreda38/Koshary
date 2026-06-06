"""Test doubles: a fake HTB MCP client backed by JSON fixtures.

No network is used. Tool results are wrapped in the MCP ``content`` envelope so
that the real ``HTBCTFPlatform`` exercises its normalization code paths exactly
as it would against the live server.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

FIXTURES = Path(__file__).parent / "fixtures" / "htb"


def load_fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _wrap(data: Any) -> dict:
    """Wrap a structured payload as an MCP tools/call result."""
    return {"content": [{"type": "text", "text": json.dumps(data)}], "isError": False}


# Discovered tools, ordered so list_* resolves before get_* (matches the
# adapter's first-match heuristic). Schemas drive argument mapping.
def _schema(*props: str) -> dict:
    return {"type": "object", "properties": {p: {"type": "string"} for p in props}}


DEFAULT_TOOLS: Dict[str, dict] = {
    "list_ctf_events": {"name": "list_ctf_events", "inputSchema": _schema()},
    "get_ctf_event": {"name": "get_ctf_event", "inputSchema": _schema("event_id")},
    "list_challenges": {"name": "list_challenges", "inputSchema": _schema("event_id")},
    "get_challenge": {"name": "get_challenge", "inputSchema": _schema("event_id", "challenge_id")},
    "download_challenge_file": {"name": "download_challenge_file", "inputSchema": _schema("challenge_id")},
    "spawn_docker_instance": {"name": "spawn_docker_instance", "inputSchema": _schema("event_id", "challenge_id")},
    "stop_docker_instance": {"name": "stop_docker_instance", "inputSchema": _schema("event_id", "challenge_id")},
    "get_instance_status": {"name": "get_instance_status", "inputSchema": _schema("challenge_id")},
    "submit_flag": {"name": "submit_flag", "inputSchema": _schema("event_id", "challenge_id", "flag")},
    "get_scoreboard": {"name": "get_scoreboard", "inputSchema": _schema("event_id")},
}


class FakeMCP:
    def __init__(self, tools: Dict[str, dict] | None = None):
        self.tools: Dict[str, dict] = dict(tools or DEFAULT_TOOLS)
        self.calls: list[tuple[str, dict]] = []

    def list_tools(self, force: bool = False) -> Dict[str, dict]:
        return self.tools

    def call_tool(self, name: str, arguments: dict | None = None) -> dict:
        arguments = arguments or {}
        self.calls.append((name, arguments))
        if "event" in name and "list" in name:
            return _wrap(load_fixture("list_events.json"))
        if "event" in name:
            return _wrap(load_fixture("event_details.json"))
        if "list" in name and "challenge" in name:
            return _wrap(load_fixture("list_challenges.json"))
        if "get" in name and "challenge" in name:
            cid = arguments.get("challenge_id", "")
            return _wrap(load_fixture("challenge_pwn.json" if "pwn" in str(cid) else "challenge_web.json"))
        if "spawn" in name or "start" in name:
            return _wrap(load_fixture("instance_started.json"))
        if "status" in name:
            return _wrap(load_fixture("instance_started.json"))
        if "stop" in name:
            return _wrap({"status": "stopped"})
        if "submit" in name or "flag" in name:
            flag = arguments.get("flag", "")
            return _wrap(load_fixture("submit_correct.json" if flag == "HTB{correct}" else "submit_wrong.json"))
        if "scoreboard" in name:
            return _wrap({"scoreboard": [{"rank": 1, "team": "alpha", "points": 1000}]})
        return _wrap({})

    def close(self) -> None:
        pass
