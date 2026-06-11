"""
Hack The Box CTF platform adapter — browser cookie/bearer mode.

Unlike :mod:`platforms.htb_ctf_mcp` (which talks to HTB's official MCP server),
this adapter drives the same JSON API the HTB CTF web app uses, authenticated
with a captured session ``Cookie`` + ``Authorization: Bearer``. This works on
events where MCP is disabled (``mcp_access_mode = no_mcp``).

The low-level HTTP lives in :class:`core.htb_cookie_client.HTBCookieClient`; this
class only maps raw HTB challenge objects onto Koshary's ``NormalizedChallenge``
and the ``BasePlatform`` lifecycle.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from core.htb_cookie_client import HTBCookieClient
from core.logging_utils import StreamLogger
from platforms.base import BasePlatform, NormalizedChallenge, SubmitResult

# Fallback category map (matches /api/public/challenge-categories ids) used only
# when the live categories endpoint is unavailable.
_DEFAULT_CATEGORY_MAP: Dict[int, str] = {
    1: "fullpwn", 2: "web", 3: "pwn", 4: "crypto", 5: "reversing",
    6: "stego", 7: "forensics", 8: "misc", 9: "osint", 10: "mobile",
    11: "coding", 12: "ml", 13: "cloud", 14: "blockchain", 15: "hardware",
    16: "misc", 17: "warmup", 19: "ai", 21: "ics",
}


class HTBCookiePlatform(BasePlatform):
    name = "htb_cookie"

    def __init__(self, config: dict, logger: Optional[StreamLogger] = None,
                 client: Optional[HTBCookieClient] = None):
        self.config = config
        cfg = config.get("htb_cookie", {}) or {}
        self.log = logger or StreamLogger("htb_cookie", log_file=Path("logs/htb_cookie.log"))
        self.ctf_id = int(cfg.get("ctf_id") or 0)
        self.base_url = cfg.get("base_url", "https://ctf.hackthebox.com")
        self.download_password = cfg.get("download_password", "hackthebox")
        self.poll_seconds = int(cfg.get("poll_seconds", 60))
        self.poll_interval = float(cfg.get("poll_interval", 2))
        self.auto_start_fullpwn = bool(cfg.get("auto_start_fullpwn", False))

        if client is not None:
            self.client = client
            if not self.ctf_id:
                self.ctf_id = client.ctf_id
        else:
            if not self.ctf_id:
                raise RuntimeError("htb_cookie requires a ctf_id (config.htb_cookie.ctf_id / --ctf-id)")
            self.client = HTBCookieClient.from_env_or_headers_file(
                ctf_id=self.ctf_id,
                headers_file=cfg.get("headers_file"),
                base_url=self.base_url,
                timeout=int(cfg.get("timeout", 30)),
                auth_mode=cfg.get("auth_mode", "cookie_bearer"),
                logger=self.log,
            )
        self._categories: Optional[Dict[int, str]] = None

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def _category_map(self) -> Dict[int, str]:
        if self._categories is None:
            cats = dict(_DEFAULT_CATEGORY_MAP)
            try:
                cats.update(self.client.get_categories())
            except Exception as exc:  # noqa: BLE001
                self.log.warn(f"Could not fetch challenge categories: {exc}")
            self._categories = cats
        return self._categories

    def _category_name(self, raw: dict) -> str:
        cid = raw.get("challenge_category_id")
        if cid is None:
            return str(raw.get("category") or "unknown")
        return self._category_map().get(int(cid), f"category-{cid}")

    @staticmethod
    def _target_kind(raw: dict) -> str:
        """Map onto Koshary's vocabulary: static / docker / fullpwn / unknown."""
        if raw.get("hasMachine") or raw.get("machine") or raw.get("isProlab"):
            return "fullpwn"
        if raw.get("hasDocker"):
            return "docker"
        if raw.get("filename"):
            return "static"
        return "unknown"

    @staticmethod
    def _ports(raw: dict) -> List[int]:
        ports = raw.get("docker_ports") or []
        if not isinstance(ports, list):
            ports = [ports]
        return [int(p) for p in ports if str(p).isdigit()]

    def _normalize(self, raw: dict) -> NormalizedChallenge:
        target_kind = self._target_kind(raw)
        host = raw.get("hostname") or None
        ports = self._ports(raw)
        port = ports[0] if ports else None

        url = None
        if target_kind == "docker" and host and port:
            inst_type = str(raw.get("docker_instance_type") or "").lower()
            if inst_type == "web":
                url = f"http://{host}:{port}"

        files = [str(raw["filename"])] if raw.get("filename") else []

        return NormalizedChallenge(
            platform=self.name,
            event_id=str(self.ctf_id),
            challenge_id=str(raw.get("id")),
            name=str(raw.get("name") or raw.get("id") or ""),
            category=self._category_name(raw),
            points=self._coerce_int(raw.get("points")),
            description=str(raw.get("description") or ""),
            solved=bool(raw.get("solved")),
            files=files,
            target_kind=target_kind,
            host=host,
            port=port,
            url=url,
            vpn_required=(target_kind == "fullpwn"),
            raw=raw,
        )

    @staticmethod
    def _coerce_int(val) -> Optional[int]:
        try:
            return int(val) if val is not None else None
        except (TypeError, ValueError):
            return None

    # ------------------------------------------------------------------ #
    # Discovery
    # ------------------------------------------------------------------ #
    def list_challenges(self) -> List[NormalizedChallenge]:
        return [self._normalize(raw) for raw in self.client.list_challenges_raw()]

    def get_challenge(self, challenge_id: str) -> NormalizedChallenge:
        return self._normalize(self.client.get_challenge_raw(challenge_id))

    # ------------------------------------------------------------------ #
    # Files
    # ------------------------------------------------------------------ #
    def download_files(self, challenge: NormalizedChallenge, dest_dir: str) -> List[str]:
        from core.downloads import prepare_files

        if not challenge.raw.get("filename"):
            return []
        dest = Path(dest_dir)
        url = self.client.get_download_link(challenge.challenge_id)
        if not url:
            self.log.warn(f"No download link for {challenge.name}")
            return []
        name = str(challenge.raw.get("filename") or f"{challenge.slug}.zip")
        meta = prepare_files(
            [{"url": url, "name": name}], dest,
            fetcher=self.client.fetch, password=self.download_password,
        )
        return [str(dest / m["filename"]) for m in meta if "error" not in m]

    # ------------------------------------------------------------------ #
    # Instances
    # ------------------------------------------------------------------ #
    def needs_instance(self, challenge: NormalizedChallenge) -> bool:
        if challenge.target_kind == "fullpwn":
            return self.auto_start_fullpwn
        return challenge.target_kind == "docker"

    def start_instance(self, challenge: NormalizedChallenge) -> NormalizedChallenge:
        self.client.start_container(challenge.challenge_id)
        raw = self.client.poll_until_ready(
            challenge.challenge_id, poll_seconds=self.poll_seconds, interval=self.poll_interval,
        )
        if raw:
            updated = self._normalize(raw)
            challenge.host = updated.host or challenge.host
            challenge.port = updated.port if updated.port is not None else challenge.port
            challenge.url = updated.url or challenge.url
            challenge.raw = raw
        if not challenge.url and challenge.host and challenge.port:
            challenge.url = f"http://{challenge.host}:{challenge.port}"
        challenge.raw.setdefault("instance", {})
        return challenge

    def stop_instance(self, challenge: NormalizedChallenge) -> None:
        self.client.stop_container(challenge.challenge_id)

    def instance_status(self, challenge: NormalizedChallenge) -> dict:
        try:
            raw = self.client.get_challenge_raw(challenge.challenge_id)
        except Exception:  # noqa: BLE001
            return {}
        online = bool(raw.get("docker_online"))
        ports = self._ports(raw)
        return {
            "status": "running" if online else "stopped",
            "docker_online": online,
            "hostname": raw.get("hostname"),
            "docker_ports": ports,
        }

    # ------------------------------------------------------------------ #
    # Submission
    # ------------------------------------------------------------------ #
    def submit_flag(self, challenge: NormalizedChallenge, flag: str) -> SubmitResult:
        res = self.client.submit_flag(challenge.challenge_id, flag)
        message = res.get("message", "")
        already = "already" in str(message).lower()
        return SubmitResult(
            accepted=bool(res.get("accepted")) or already,
            message=str(message),
            raw=res.get("raw", res),
            already_solved=already,
        )

    # ------------------------------------------------------------------ #
    # Scoreboard
    # ------------------------------------------------------------------ #
    def get_scoreboard(self) -> List[dict]:
        try:
            data = self.client.get_scores()
        except Exception as exc:  # noqa: BLE001
            self.log.warn(f"Scoreboard fetch failed: {exc}")
            return []
        if isinstance(data, list):
            return [d for d in data if isinstance(d, dict)]
        if isinstance(data, dict):
            for key in ("scores", "scoreboard", "data", "teams", "leaderboard"):
                val = data.get(key)
                if isinstance(val, list):
                    return [d for d in val if isinstance(d, dict)]
        return []

    def close(self) -> None:
        self.client.close()
