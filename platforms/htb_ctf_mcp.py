"""
Hack The Box CTF platform adapter (via the official HTB CTF MCP server).

HTB's exact MCP tool names are *not* hardcoded. At runtime the adapter performs
tool discovery (``tools/list``) and resolves a logical role
(list_events / list_challenges / start_instance / submit_flag / ...) to a real
tool name using, in order:

1. an explicit override in ``config["htb"]["tools"]``;
2. keyword heuristics over the discovered tool names.

Tool call arguments are mapped onto each tool's advertised ``inputSchema`` so we
adapt to whatever parameter names HTB actually uses (event vs slug vs eventId).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.logging_utils import StreamLogger
from core.mcp_client import MCPClient
from platforms.base import BasePlatform, NormalizedChallenge, SubmitResult

# HTB CTF challenges expose a numeric ``challenge_category_id`` rather than a
# category name. This default map covers the standard HTB CTF categories and can
# be extended/overridden via ``config["htb"]["category_map"]``.
_HTB_CATEGORY_MAP: Dict[str, str] = {
    "1": "fullpwn", "2": "web", "3": "pwn", "4": "crypto", "5": "reversing",
    "6": "stego", "7": "forensics", "8": "misc", "9": "osint", "10": "mobile",
    "11": "coding", "12": "ml", "13": "cloud", "14": "blockchain",
    "15": "hardware", "16": "misc", "17": "warmup", "19": "ai", "21": "ics",
}

# Logical role -> keyword groups. A tool name matches a role when it contains at
# least one keyword from every group (AND of ORs).
_ROLE_KEYWORDS: Dict[str, List[List[str]]] = {
    "list_events": [["event", "competition"], ["list", "all", "available", "running"]],
    "get_event": [["ctf", "event"], ["retrieve", "detail", "info", "get", "describe"]],
    # HTB has no standalone "list challenges" tool; challenges come from the
    # event retrieval, so these intentionally fall back to a config override.
    "list_challenges": [["challenge"], ["list", "all"]],
    "get_challenge": [["challenge"], ["detail", "info", "describe", "get"]],
    "download": [["download"]],
    "start_instance": [["spawn", "start", "create", "launch"], ["instance", "docker", "container", "machine"]],
    "stop_instance": [["stop", "kill", "terminate", "reset", "delete", "destroy"], ["instance", "docker", "container", "machine"]],
    "instance_status": [["status", "state"], ["instance", "docker", "container", "machine"]],
    "submit_flag": [["submit"], ["flag"]],
    "scoreboard": [["scoreboard", "leaderboard", "ranking", "rank", "score"]],
    "join_event": [["join", "register", "enroll"], ["event", "ctf"]],
    "my_teams": [["team"], ["my", "retrieve", "list", "get"]],
}

# Logical argument -> candidate property-name substrings (most specific first).
_ARG_ALIASES: Dict[str, List[str]] = {
    "event": ["ctf_id", "ctfid", "event_id", "eventid", "event", "ctf", "slug"],
    "challenge": ["challenge_id", "challengeid", "challenge", "chall", "id"],
    "flag": ["flag", "submission", "answer", "solution"],
    "team": ["team_id", "teamid", "team"],
    "consent": ["consent"],
    "password": ["ctf_password", "password", "passcode"],
}


class HTBCTFPlatform(BasePlatform):
    name = "htb_ctf"

    def __init__(self, config: dict, logger: Optional[StreamLogger] = None,
                 client: Optional[MCPClient] = None):
        self.config = config
        htb_cfg = config.get("htb", {})
        self.log = logger or StreamLogger("htb_mcp", log_file=Path("logs/htb_mcp.log"))
        self.event = htb_cfg.get("event", "")
        self.download_password = htb_cfg.get("download_password", "hackthebox")
        self._tool_overrides: Dict[str, str] = htb_cfg.get("tools", {}) or {}
        if client is not None:
            self.client = client
        else:
            token = os.environ.get("HTB_MCP_TOKEN", "").strip()
            if not token:
                raise RuntimeError("HTB_MCP_TOKEN is not set in the environment / .env")
            self.client = MCPClient(
                url=htb_cfg.get("mcp_url", "https://mcp.hackthebox.ai/v1/ctf/mcp/"),
                token=token,
                logger=self.log,
            )
        self._resolved: Dict[str, Optional[str]] = {}
        self._ctf_id: Optional[str] = None
        self.team_id = htb_cfg.get("team_id")
        self._category_map: Dict[str, str] = dict(_HTB_CATEGORY_MAP)
        self._category_map.update({str(k): v for k, v in (htb_cfg.get("category_map") or {}).items()})

    # ------------------------------------------------------------------ #
    # Tool resolution
    # ------------------------------------------------------------------ #
    def _ensure_tools(self) -> Dict[str, dict]:
        if not self.client.tools:
            self.client.list_tools()
        return self.client.tools

    def _resolve(self, role: str) -> Optional[str]:
        if role in self._resolved:
            return self._resolved[role]
        tools = self._ensure_tools()
        # 1. explicit override
        override = self._tool_overrides.get(role)
        if override and override in tools:
            self._resolved[role] = override
            return override
        # 2. heuristic match
        groups = _ROLE_KEYWORDS.get(role, [])
        best: Optional[str] = None
        for tool_name in tools:
            low = tool_name.lower()
            if all(any(kw in low for kw in group) for group in groups):
                best = tool_name
                break
        self._resolved[role] = best
        if best is None:
            self.log.debug(f"No MCP tool resolved for role '{role}'.")
        return best

    def _tool_schema_props(self, tool_name: str) -> List[str]:
        tool = self.client.tools.get(tool_name, {})
        schema = tool.get("inputSchema") or tool.get("input_schema") or {}
        props = schema.get("properties", {}) if isinstance(schema, dict) else {}
        return list(props.keys())

    def _build_args(self, tool_name: str, logical: Dict[str, Any]) -> Dict[str, Any]:
        """Map logical values (event/challenge/flag) onto a tool's real params."""
        props = self._tool_schema_props(tool_name)
        if not props:
            # Unknown schema: fall back to passing logical keys directly.
            return {k: v for k, v in logical.items() if v is not None}
        args: Dict[str, Any] = {}
        low_props = {p.lower(): p for p in props}
        for logical_key, value in logical.items():
            if value is None:
                continue
            for alias in _ARG_ALIASES.get(logical_key, [logical_key]):
                match = next((low_props[lp] for lp in low_props if alias == lp), None)
                if match is None:
                    match = next((low_props[lp] for lp in low_props if alias in lp), None)
                if match is not None:
                    args[match] = value
                    break
        return args

    def _call_role(self, role: str, logical: Dict[str, Any]) -> Any:
        tool_name = self._resolve(role)
        if not tool_name:
            raise RuntimeError(f"HTB MCP exposes no tool for '{role}'")
        args = self._build_args(tool_name, logical)
        result = self.client.call_tool(tool_name, args)
        data = MCPClient.result_to_data(result)
        self._raise_on_error(data)
        return data

    @staticmethod
    def _raise_on_error(data: Any) -> None:
        """HTB tools return {"error": "...", "status_code": N} on failure."""
        if isinstance(data, dict) and data.get("error"):
            msg = str(data.get("error"))
            if "403" in msg or "forbidden" in msg.lower():
                msg += " (you may need to join the event first: setup_htb.py --join)"
            raise RuntimeError(msg)

    # ------------------------------------------------------------------ #
    # Data normalization helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _as_list(data: Any, *keys: str) -> List[dict]:
        if isinstance(data, list):
            return [d for d in data if isinstance(d, dict)]
        if isinstance(data, dict):
            for key in (*keys, "data", "items", "results", "challenges", "events"):
                val = data.get(key)
                if isinstance(val, list):
                    return [d for d in val if isinstance(d, dict)]
            # Single object
            return [data]
        return []

    @staticmethod
    def _first(obj: dict, *keys: str, default: Any = None) -> Any:
        for k in keys:
            if k in obj and obj[k] not in (None, ""):
                return obj[k]
        return default

    def _category_name(self, obj: dict) -> str:
        # Prefer an explicit name; otherwise map the numeric category id.
        name = self._first(obj, "category", "category_name", "type")
        if name:
            return str(name)
        cid = obj.get("challenge_category_id")
        if cid is not None:
            return self._category_map.get(str(cid), f"category-{cid}")
        return ""

    def _detect_target(self, obj: dict) -> str:
        cat = self._category_name(obj).lower()
        if obj.get("hasMachine") or obj.get("isProlab") or any(
            w in cat for w in ("fullpwn", "full-pwn", "machine", "endgame")
        ):
            return "fullpwn"
        docker_signals = [
            self._first(obj, "docker", "hasDocker", "has_docker", "dockerType",
                        "spawnable", "is_instance"),
            (obj.get("instance") is not None),
        ]
        if any(bool(s) for s in docker_signals):
            return "docker"
        if self._first(obj, "docker_ip", "ip", "host") and "static" not in cat:
            return "docker"
        return "static"

    @staticmethod
    def _has_download(obj: dict) -> bool:
        return bool(
            obj.get("hasDownload") or obj.get("has_download")
            or obj.get("filename") or obj.get("files") or obj.get("download")
        )

    @classmethod
    def _files_from(cls, obj: dict) -> List[str]:
        files: List[str] = []
        for key in ("files", "attachments", "downloads", "file"):
            val = obj.get(key)
            if not val:
                continue
            if isinstance(val, str):
                files.append(val)
            elif isinstance(val, list):
                for item in val:
                    if isinstance(item, str):
                        files.append(item)
                    elif isinstance(item, dict):
                        url = item.get("url") or item.get("location") or item.get("href") or item.get("download_url")
                        if url:
                            files.append(url)
        # HTB exposes a single downloadable per challenge via get_download_link;
        # surface its name so the orchestrator triggers the download step.
        if not files and obj.get("filename"):
            files.append(str(obj["filename"]))
        elif not files and cls._has_download(obj):
            files.append("challenge.zip")
        return files

    def _normalize_challenge(self, obj: dict, event_id: Optional[str] = None) -> NormalizedChallenge:
        cid = self._first(obj, "id", "challenge_id", "uuid", "_id", default="")
        target_kind = self._detect_target(obj)
        host = self._first(obj, "host", "hostname", "ip", "docker_ip")
        url = self._first(obj, "url", "docker_url")
        # HTB exposes docker_ports as a list; take the first.
        port = self._first(obj, "port", "docker_port")
        ports = obj.get("docker_ports")
        if port is None and isinstance(ports, list) and ports:
            port = ports[0]
        try:
            port = int(port) if port is not None else None
        except (TypeError, ValueError):
            port = None
        return NormalizedChallenge(
            platform=self.name,
            event_id=str(event_id or self.event),
            challenge_id=str(cid),
            name=str(self._first(obj, "name", "title", default="")),
            category=self._category_name(obj),
            points=self._coerce_int(self._first(obj, "points", "value", "score")),
            description=str(self._first(obj, "description", "desc", default="") or ""),
            solved=bool(self._first(obj, "solved", "is_solved", "owned", "completed", default=False)),
            files=self._files_from(obj),
            target_kind=target_kind,
            host=str(host) if host else None,
            port=port,
            url=str(url) if url else None,
            vpn_required=(target_kind == "fullpwn") or bool(self._first(obj, "vpn_required", "needs_vpn", default=False)),
            raw=obj,
        )

    @staticmethod
    def _coerce_int(val: Any) -> Optional[int]:
        try:
            return int(val) if val is not None else None
        except (TypeError, ValueError):
            return None

    # ------------------------------------------------------------------ #
    # Event id resolution (HTB tools key off the numeric ctf_id, not the slug)
    # ------------------------------------------------------------------ #
    def _event_ctf_id(self) -> str:
        if self._ctf_id is not None:
            return self._ctf_id
        ev = str(self.event).strip()
        if not ev:
            raise RuntimeError("No HTB event configured (htb.event / --event)")
        if ev.isdigit():
            self._ctf_id = ev
            return ev
        # Resolve a slug or name to its numeric id via the event list.
        try:
            for e in self.list_events():
                if ev in (str(e.get("slug")), str(e.get("id")), str(e.get("name"))):
                    self._ctf_id = str(e.get("id"))
                    return self._ctf_id
        except Exception:  # noqa: BLE001
            pass
        # HTB slugs are typically '<name>-<id>'.
        import re

        m = re.search(r"(\d+)$", ev)
        if m:
            self._ctf_id = m.group(1)
            return self._ctf_id
        raise RuntimeError(f"Could not resolve HTB event '{self.event}' to a numeric ctf_id")

    def _default_team_id(self) -> Optional[str]:
        if self.team_id:
            return str(self.team_id)
        try:
            tool = self._tool_overrides.get("my_teams") or self._resolve("my_teams")
            if not tool:
                return None
            data = MCPClient.result_to_data(self.client.call_tool(tool, {}))
            teams = self._as_list(data, "teams")
            if teams:
                self.team_id = teams[0].get("id")
                return str(self.team_id) if self.team_id is not None else None
        except Exception:  # noqa: BLE001
            return None
        return None

    @staticmethod
    def _extract_link(data: Any) -> Optional[str]:
        if isinstance(data, str) and data.startswith("http"):
            return data
        if isinstance(data, dict):
            for key in ("url", "download_url", "link", "signed_url", "href", "downloadUrl"):
                val = data.get(key)
                if isinstance(val, str) and val.startswith("http"):
                    return val
        return None

    # ------------------------------------------------------------------ #
    # Events
    # ------------------------------------------------------------------ #
    def list_events(self) -> List[dict]:
        data = self._call_role("list_events", {})
        return self._as_list(data, "events")

    def get_event(self, event_id: Optional[str] = None) -> dict:
        ctf_id = event_id or self._event_ctf_id()
        data = self._call_role("get_event", {"event": ctf_id})
        if isinstance(data, dict):
            return data
        items = self._as_list(data, "event")
        return items[0] if items else {}

    def join_event(self, team_id: Optional[str] = None, consent: bool = True,
                   password: Optional[str] = None) -> dict:
        """Register the user's team for the configured event. State-changing —
        only invoked when the caller explicitly asks (auto_join / setup)."""
        team = team_id or self._default_team_id()
        if not team:
            raise RuntimeError("join_event requires a team_id (set htb.team_id)")
        logical = {"event": self._event_ctf_id(), "team": team, "consent": consent}
        if password:
            logical["password"] = password
        data = self._call_role("join_event", logical)
        return data if isinstance(data, dict) else {"raw": data}

    # ------------------------------------------------------------------ #
    # Challenges
    # ------------------------------------------------------------------ #
    def _event_payload(self) -> Any:
        """retrieve_ctf returns the event object including its challenges."""
        return self._call_role("list_challenges", {"event": self._event_ctf_id()})

    def list_challenges(self) -> List[NormalizedChallenge]:
        data = self._event_payload()
        ctf_id = self._event_ctf_id()
        objs = self._as_list(data, "challenges")
        # Some events group challenges by category.
        if not objs and isinstance(data, dict):
            for cat in self._as_list(data.get("challengeCategories"), "challenges"):
                objs.extend(self._as_list(cat, "challenges"))
        return [self._normalize_challenge(o, self.event or ctf_id) for o in objs]

    def get_challenge(self, challenge_id: str) -> NormalizedChallenge:
        # HTB has no per-challenge detail tool; pull from the event payload.
        for c in self.list_challenges():
            if str(c.challenge_id) == str(challenge_id):
                return c
        raise RuntimeError(f"HTB challenge '{challenge_id}' not found in event")

    # ------------------------------------------------------------------ #
    # Files
    # ------------------------------------------------------------------ #
    def download_files(self, challenge: NormalizedChallenge, dest_dir: str) -> List[str]:
        from urllib.parse import urlparse

        from core.downloads import prepare_files

        dest = Path(dest_dir)
        specs: List[dict] = []

        # Preferred path: HTB returns a 5-minute signed URL via get_download_link.
        if self._has_download(challenge.raw) and self._resolve("download"):
            try:
                data = self._call_role("download", {"challenge": challenge.challenge_id})
                url = self._extract_link(data)
                if url:
                    name = (challenge.raw.get("filename")
                            or Path(urlparse(url).path).name
                            or f"{challenge.slug}.zip")
                    specs.append({"url": url, "name": name})
            except Exception as e:  # noqa: BLE001
                self.log.warn(f"get_download_link failed for {challenge.name}: {e}")

        # Fall back to any direct URLs present on the challenge object.
        if not specs:
            specs = [{"url": u} for u in challenge.files if str(u).startswith("http")]
        if not specs:
            return []

        def fetcher(url: str, out_path: Path) -> None:
            import requests

            with requests.get(url, timeout=120, stream=True) as r:
                r.raise_for_status()
                out_path.parent.mkdir(parents=True, exist_ok=True)
                with open(out_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)

        meta = prepare_files(specs, dest, fetcher=fetcher, password=self.download_password)
        return [str(dest / m["filename"]) for m in meta if "error" not in m]

    # ------------------------------------------------------------------ #
    # Instances
    # ------------------------------------------------------------------ #
    def start_instance(self, challenge: NormalizedChallenge) -> NormalizedChallenge:
        import time

        self._call_role("start_instance", {"challenge": challenge.challenge_id})
        # start_container only returns request status; poll container_status until
        # connection details (ip/port) appear.
        info: dict = {}
        for _ in range(20):
            info = self.instance_status(challenge)
            challenge = self._apply_instance_info(challenge, info)
            if challenge.host:
                break
            time.sleep(5)
        challenge.raw["instance"] = info
        return challenge

    def stop_instance(self, challenge: NormalizedChallenge) -> None:
        if not self._resolve("stop_instance"):
            return
        self._call_role("stop_instance", {"challenge": challenge.challenge_id})

    def instance_status(self, challenge: NormalizedChallenge) -> dict:
        if not self._resolve("instance_status"):
            return {}
        data = self._call_role("instance_status", {"challenge": challenge.challenge_id})
        return data if isinstance(data, dict) else {"raw": data}

    def _apply_instance_info(self, challenge: NormalizedChallenge, info: dict) -> NormalizedChallenge:
        if not isinstance(info, dict):
            return challenge
        host = self._first(info, "ip", "host", "docker_ip", "address", "server", "server_ip")
        port = self._first(info, "port", "docker_port", "server_port")
        url = self._first(info, "url", "docker_url", "connection")
        if host:
            challenge.host = str(host)
        if port is not None:
            challenge.port = self._coerce_int(port)
        if url:
            challenge.url = str(url)
        if not challenge.url and challenge.host and challenge.port:
            challenge.url = f"http://{challenge.host}:{challenge.port}"
        return challenge

    # ------------------------------------------------------------------ #
    # Submission
    # ------------------------------------------------------------------ #
    def submit_flag(self, challenge: NormalizedChallenge, flag: str) -> SubmitResult:
        data = self._call_role(
            "submit_flag",
            {"challenge": challenge.challenge_id, "flag": flag},
        )
        return self._interpret_submission(data)

    @staticmethod
    def _interpret_submission(data: Any) -> SubmitResult:
        raw = data if isinstance(data, dict) else {"raw": data}
        text = (str(data) if not isinstance(data, dict) else
                str(data.get("message") or data.get("status") or data)).lower()
        # Explicit boolean signals first.
        if isinstance(data, dict):
            for key in ("correct", "accepted", "success", "solved", "is_correct"):
                if key in data and isinstance(data[key], bool):
                    accepted = data[key]
                    already = bool(data.get("already_solved") or "already" in text)
                    return SubmitResult(accepted=accepted, message=str(data.get("message", key)),
                                        raw=raw, already_solved=already)
        accepted = any(w in text for w in ("correct", "accepted", "solved")) and not any(
            w in text for w in ("incorrect", "wrong", "invalid", "not correct")
        )
        already = "already" in text
        return SubmitResult(accepted=accepted or already, message=text[:200], raw=raw,
                            already_solved=already)

    # ------------------------------------------------------------------ #
    def get_scoreboard(self) -> List[dict]:
        if not self._resolve("scoreboard"):
            return []
        data = self._call_role("scoreboard", {"event": self._event_ctf_id()})
        return self._as_list(data, "scoreboard", "leaderboard", "scores")

    def close(self) -> None:
        self.client.close()
