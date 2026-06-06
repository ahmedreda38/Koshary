"""
CTFd platform adapter.

Contains the low-level CTFd HTTP client (kept API-compatible with the original
``orchestrator.CTFdClient`` so ``first_blood.py`` keeps working) and the
``CTFdPlatform`` adapter that exposes CTFd through Koshary's common interface.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from core.logging_utils import StreamLogger, register_secret
from platforms.base import BasePlatform, NormalizedChallenge, SubmitResult


class CTFdClient:
    """Thin CTFd REST client with CSRF-nonce handling."""

    def __init__(self, base_url: str, session_cookie: str, logger: Optional[StreamLogger] = None):
        self.base_url = base_url.rstrip("/")
        self.log = logger or StreamLogger("ctfd")
        register_secret(session_cookie)
        self.s = requests.Session()
        self.s.headers["Cookie"] = f"session={session_cookie}"
        self.s.headers["User-Agent"] = "ctf-ai-orchestrator/3.0"
        self.nonce = self._fetch_nonce()

    def _fetch_nonce(self) -> str:
        try:
            r = self.s.get(f"{self.base_url}/challenges", timeout=20)
            r.raise_for_status()
            m = re.search(r"['\"]?csrf_?[Nn]once['\"]?:\s*['\"]([a-f0-9]+)['\"]", r.text)
            if m:
                nonce = m.group(1)
                self.log.ok(f"Synchronized CSRF nonce: {nonce}")
                self.s.headers["CSRF-Token"] = nonce
                return nonce
            m = re.search(r'<meta name="csrf-token" content="([a-f0-9]+)">', r.text)
            if m:
                nonce = m.group(1)
                self.s.headers["CSRF-Token"] = nonce
                return nonce
            self.log.warn("CSRF nonce synchronization failed for current session.")
        except Exception as e:  # noqa: BLE001
            self.log.err(f"Session error while fetching nonce: {e}")
        return ""

    def get_challenges(self) -> List[Dict[str, Any]]:
        r = self.s.get(f"{self.base_url}/api/v1/challenges", timeout=20)
        r.raise_for_status()
        data = r.json()
        if not data.get("success", False):
            raise RuntimeError(f"CTFd challenge list fetch failed: {data}")
        return data["data"]

    def get_challenge_detail(self, chall_id: int) -> Dict[str, Any]:
        r = self.s.get(f"{self.base_url}/api/v1/challenges/{chall_id}", timeout=20)
        r.raise_for_status()
        data = r.json()
        if not data.get("success", False):
            raise RuntimeError(f"CTFd challenge detail fetch failed for {chall_id}: {data}")
        return data["data"]

    def download_file(self, url: str, out_path: Path) -> None:
        if not url.startswith("http"):
            url = self.base_url + url
        with self.s.get(url, timeout=90, stream=True) as r:
            r.raise_for_status()
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with open(out_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)

    def submit_flag(self, challenge_id: int, flag: str) -> Dict[str, Any]:
        if "CSRF-Token" not in self.s.headers or not self.s.headers["CSRF-Token"]:
            self._fetch_nonce()
        headers = {
            "Content-Type": "application/json",
            "CSRF-Token": self.s.headers.get("CSRF-Token", ""),
        }
        r = self.s.post(
            f"{self.base_url}/api/v1/challenges/attempt",
            json={"challenge_id": challenge_id, "submission": flag},
            headers=headers,
            timeout=20,
        )
        r.raise_for_status()
        return r.json()


def _ctfd_files_from_detail(detail: Dict[str, Any]) -> List[str]:
    files = []
    for f in detail.get("files", []) or []:
        if isinstance(f, str):
            files.append(f)
        elif isinstance(f, dict) and "location" in f:
            files.append(f["location"])
    return files


class CTFdPlatform(BasePlatform):
    name = "ctfd"

    def __init__(self, config: dict, client: Optional[CTFdClient] = None,
                 session: Optional[str] = None, logger: Optional[StreamLogger] = None):
        self.config = config
        self.log = logger or StreamLogger("ctfd")
        ctf_cfg = config.get("ctf", {})
        self.base_url = ctf_cfg.get("base_url", "").rstrip("/")
        self.event_id = ctf_cfg.get("name") or self.base_url
        if client is not None:
            self.client = client
        else:
            if not session:
                raise ValueError("CTFdPlatform requires a session cookie")
            self.client = CTFdClient(self.base_url, session, logger=self.log)

    # ------------------------------------------------------------------ #
    def _normalize_summary(self, s: Dict[str, Any]) -> NormalizedChallenge:
        return NormalizedChallenge(
            platform=self.name,
            event_id=str(self.event_id),
            challenge_id=str(s["id"]),
            name=s.get("name", ""),
            category=s.get("category", ""),
            points=s.get("value"),
            description=s.get("description", ""),
            solved=bool(s.get("solved_by_me", False)),
            target_kind="static",
            raw=dict(s),
        )

    def _normalize_detail(self, detail: Dict[str, Any]) -> NormalizedChallenge:
        files = _ctfd_files_from_detail(detail)
        conn = detail.get("connection_info")
        chall = NormalizedChallenge(
            platform=self.name,
            event_id=str(self.event_id),
            challenge_id=str(detail["id"]),
            name=detail.get("name", ""),
            category=detail.get("category", ""),
            points=detail.get("value"),
            description=detail.get("description", "") or "",
            solved=bool(detail.get("solved_by_me", False)),
            files=files,
            target_kind="static",
            raw=dict(detail),
        )
        if conn:
            # Surface connection info via url/host so prompts and the instance
            # manager can use it, without spawning anything.
            chall.url = conn if str(conn).startswith("http") else None
        return chall

    def list_challenges(self) -> List[NormalizedChallenge]:
        return [self._normalize_summary(s) for s in self.client.get_challenges()]

    def get_challenge(self, challenge_id: str) -> NormalizedChallenge:
        detail = self.client.get_challenge_detail(int(challenge_id))
        return self._normalize_detail(detail)

    def download_files(self, challenge: NormalizedChallenge, dest_dir: str) -> List[str]:
        dest = Path(dest_dir)
        dest.mkdir(parents=True, exist_ok=True)
        written: List[str] = []
        for url in challenge.files:
            from urllib.parse import unquote, urlparse

            name = Path(urlparse(url).path).name
            name = unquote(name) or "download.bin"
            out_path = dest / name
            if not out_path.exists():
                try:
                    self.client.download_file(url, out_path)
                except Exception as e:  # noqa: BLE001
                    self.log.err(f"Download failed for {challenge.name}: {e}")
                    continue
            written.append(str(out_path))
        return written

    def submit_flag(self, challenge: NormalizedChallenge, flag: str) -> SubmitResult:
        cid = int(challenge.raw.get("id", challenge.challenge_id))
        resp = self.client.submit_flag(cid, flag)
        msg_text = json.dumps(resp).lower()
        accepted = resp.get("success") is True and not any(
            bad in msg_text for bad in ("incorrect", "wrong")
        )
        message = ""
        data = resp.get("data")
        if isinstance(data, dict):
            message = data.get("message", "") or data.get("status", "")
        return SubmitResult(accepted=accepted, message=message or msg_text, raw=resp)
