#!/usr/bin/env python3
"""
HTB CTF cookie/bearer HTTP client.

This is the reusable, redaction-aware client behind the ``htb_cookie`` platform
adapter. It speaks the same browser API that ``ctf.hackthebox.com`` uses
(observed from an authorized Burp capture of a joined event).

Authentication
--------------
Every relevant HTB API request in the capture carried *both* a session
``Cookie`` and an ``Authorization: Bearer`` header, so the default auth mode is
``cookie_bearer``. ``cookie_only`` / ``bearer_only`` are offered as fallbacks.

Credentials come from, in order of precedence:
  1. an explicit ``--headers-file`` (a copied raw HTTP request / Burp item), then
  2. the environment: ``HTB_CTF_COOKIE`` / ``HTB_CTF_BEARER`` / ``HTB_CTF_USER_AGENT``.

Security
--------
The cookie and bearer are registered with :mod:`core.logging_utils` so they are
redacted from every log line. Signed, expiring download URLs are redacted too.
Use only for CTF events you are authorized to access.

Dev CLI::

    python3 -m core.htb_cookie_client --ctf-id 1434 --headers-file htb_headers.txt list
    python3 -m core.htb_cookie_client --ctf-id 1434 --headers-file htb_headers.txt check
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import unquote, urlparse

import requests

from core.logging_utils import StreamLogger, redact, register_secret

BASE_URL = "https://ctf.hackthebox.com"
DEFAULT_USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) Koshary-HTB-CTF-Client/1.0"

# These never go to logs.
_SECRET_HEADER_KEYS = {"cookie", "authorization"}


def parse_headers_file(path: str | Path) -> dict[str, str]:
    """Extract ``cookie`` / ``authorization`` / ``user-agent`` from a copied raw
    HTTP request or simple ``Key: value`` header file. Only those three keys are
    read; everything else (browser telemetry) is ignored."""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    headers: dict[str, str] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        key = key.strip().lower()
        val = val.strip()
        if key in {"cookie", "authorization", "user-agent"} and val:
            headers[key] = val
    return headers


def safe_slug(s: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "_", (s or "").strip()).strip("_")
    return slug or "challenge"


def filename_from_response(resp: requests.Response, fallback: str) -> str:
    cd = resp.headers.get("content-disposition", "")
    m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', cd, re.I)
    if m:
        return safe_slug(unquote(m.group(1)))
    name = Path(urlparse(resp.url).path).name
    if name and name != "download":
        return safe_slug(unquote(name))
    return safe_slug(fallback)


def _redact_url(url: str) -> str:
    """Drop the signed query string so expiring download URLs never hit logs."""
    if not url:
        return url
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    return base + ("?<redacted-signature>" if parsed.query else "")


class HTBAuthError(RuntimeError):
    """Raised on 401/403 — the session/bearer is invalid or lacks access."""


class HTBCookieClient:
    def __init__(
        self,
        ctf_id: int,
        cookie: Optional[str] = None,
        bearer: Optional[str] = None,
        user_agent: Optional[str] = None,
        base_url: str = BASE_URL,
        timeout: int = 30,
        auth_mode: str = "cookie_bearer",
        session: Optional[requests.Session] = None,
        logger: Optional[StreamLogger] = None,
    ):
        self.ctf_id = int(ctf_id)
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.auth_mode = (auth_mode or "cookie_bearer").lower()
        self.log = logger or StreamLogger("htb_cookie", log_file=Path("logs/htb_cookie.log"))
        self.session = session or requests.Session()

        self.session.headers.update({
            "Accept": "application/json",
            "User-Agent": user_agent or DEFAULT_USER_AGENT,
            "Referer": f"{self.base_url}/event/{self.ctf_id}",
        })

        use_cookie = self.auth_mode in ("cookie_bearer", "cookie_only")
        use_bearer = self.auth_mode in ("cookie_bearer", "bearer_only")

        if cookie and use_cookie:
            cookie = cookie.strip()
            register_secret(cookie)
            self.session.headers["Cookie"] = cookie
        if bearer and use_bearer:
            bearer = bearer.strip()
            if bearer.lower().startswith("bearer "):
                bearer = bearer[7:].strip()
            register_secret(bearer)
            self.session.headers["Authorization"] = f"Bearer {bearer}"

    # ------------------------------------------------------------------ #
    # Construction from env / headers file
    # ------------------------------------------------------------------ #
    @classmethod
    def from_env_or_headers_file(
        cls,
        ctf_id: int,
        headers_file: Optional[str] = None,
        base_url: str = BASE_URL,
        timeout: int = 30,
        auth_mode: str = "cookie_bearer",
        session: Optional[requests.Session] = None,
        logger: Optional[StreamLogger] = None,
    ) -> "HTBCookieClient":
        cookie = os.getenv("HTB_CTF_COOKIE")
        bearer = os.getenv("HTB_CTF_BEARER")
        user_agent = os.getenv("HTB_CTF_USER_AGENT")

        if headers_file:
            parsed = parse_headers_file(headers_file)
            cookie = parsed.get("cookie", cookie)
            auth = parsed.get("authorization")
            if auth:
                bearer = auth
            user_agent = parsed.get("user-agent", user_agent)

        if not cookie and not bearer:
            raise HTBAuthError(
                "Missing HTB auth. Set HTB_CTF_COOKIE / HTB_CTF_BEARER in .env "
                "or pass a --headers-file with a captured request."
            )

        return cls(
            ctf_id=ctf_id, cookie=cookie, bearer=bearer, user_agent=user_agent,
            base_url=base_url, timeout=timeout, auth_mode=auth_mode,
            session=session, logger=logger,
        )

    # ------------------------------------------------------------------ #
    # Low-level HTTP
    # ------------------------------------------------------------------ #
    def _url(self, path: str) -> str:
        return path if path.startswith("http") else f"{self.base_url}{path}"

    def _request(self, method: str, path_or_url: str, **kwargs) -> requests.Response:
        url = self._url(path_or_url)
        headers = kwargs.pop("headers", {}) or {}
        if method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
            headers.setdefault("Origin", self.base_url)
            headers.setdefault("Referer", f"{self.base_url}/event/{self.ctf_id}")
        resp = self.session.request(method, url, timeout=self.timeout, headers=headers, **kwargs)
        if resp.status_code == 401:
            raise HTBAuthError("HTB returned 401 Unauthorized — refresh Cookie/Bearer.")
        if resp.status_code == 403:
            raise HTBAuthError(
                "HTB returned 403 Forbidden — check event access (joined? can view "
                "challenges?) or session/Cloudflare state."
            )
        return resp

    # Endpoints where a non-2xx body is meaningful and must not raise.
    _SOFT_FAIL_PATHS = ("/api/flags/own",)

    def _json(self, method: str, path: str, **kwargs) -> tuple[Any, int]:
        resp = self._request(method, path, **kwargs)
        try:
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            snippet = redact(resp.text[:300])
            raise RuntimeError(
                f"Expected JSON from {path}, got HTTP {resp.status_code}: {snippet}"
            ) from exc
        if not resp.ok and not any(path.startswith(p) for p in self._SOFT_FAIL_PATHS):
            raise RuntimeError(f"{method} {path} failed: HTTP {resp.status_code}: {redact(json.dumps(data))}")
        return data, resp.status_code

    # ------------------------------------------------------------------ #
    # Read endpoints
    # ------------------------------------------------------------------ #
    def get_categories(self) -> dict[int, str]:
        data, _ = self._json("GET", "/api/public/challenge-categories")
        rows = data if isinstance(data, list) else data.get("data", data)
        out: dict[int, str] = {}
        for row in rows or []:
            try:
                out[int(row["id"])] = row["name"]
            except (KeyError, TypeError, ValueError):
                continue
        return out

    def get_event(self) -> dict:
        data, _ = self._json("GET", f"/api/ctfs/{self.ctf_id}")
        # Some payloads wrap the event under a "data"/"ctf" key.
        if isinstance(data, dict) and "challenges" not in data:
            for key in ("data", "ctf", "event"):
                inner = data.get(key)
                if isinstance(inner, dict) and "challenges" in inner:
                    return inner
        return data if isinstance(data, dict) else {}

    def get_menu(self) -> dict:
        data, _ = self._json("GET", f"/api/ctfs/{self.ctf_id}/menu")
        if isinstance(data, dict):
            return data.get("data", data) if not data.get("id") else data
        return {}

    def list_challenges_raw(self) -> list[dict]:
        event = self.get_event()
        challenges = event.get("challenges") or []
        if not challenges:
            for cat in event.get("challengeCategories", []) or []:
                challenges.extend(cat.get("challenges", []) or [])
        return [c for c in challenges if isinstance(c, dict)]

    def get_challenge_raw(self, challenge_id: int | str) -> dict:
        for raw in self.list_challenges_raw():
            if str(raw.get("id")) == str(challenge_id):
                return raw
        raise KeyError(f"Challenge {challenge_id} not found in CTF {self.ctf_id}")

    def validate_access(self) -> tuple[bool, dict]:
        """Return ``(can_view_challenges, menu)`` using the menu endpoint."""
        menu = self.get_menu()
        can = bool(menu.get("userCanViewChallenges", menu.get("user_can_view_challenges", False)))
        return can, menu

    # ------------------------------------------------------------------ #
    # Downloads
    # ------------------------------------------------------------------ #
    def get_download_link(self, challenge_id: int | str) -> Optional[str]:
        data, status = self._json("GET", f"/api/challenges/{int(challenge_id)}/download/link")
        if status != 200:
            return None
        return data.get("url") if isinstance(data, dict) else None

    def fetch(self, url: str, out_path: Path) -> None:
        """Stream a (signed) URL to disk via the authed session. URL is redacted
        from logs."""
        self.log.info(f"Downloading {_redact_url(url)}")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with self._request(
            "GET", url, stream=True, allow_redirects=True,
            headers={"Accept": "application/octet-stream,*/*"},
        ) as resp:
            resp.raise_for_status()
            with open(out_path, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=1024 * 256):
                    if chunk:
                        fh.write(chunk)

    # ------------------------------------------------------------------ #
    # Containers
    # ------------------------------------------------------------------ #
    def start_container(self, challenge_id: int | str) -> dict:
        data, status = self._json(
            "POST", "/api/challenges/containers/start",
            json={"id": int(challenge_id)},
            headers={"Content-Type": "application/json"},
        )
        if status not in {200, 201, 202}:
            raise RuntimeError(f"Container start failed: HTTP {status}: {redact(json.dumps(data))}")
        return data if isinstance(data, dict) else {"raw": data}

    def stop_container(self, challenge_id: int | str) -> dict:
        data, status = self._json(
            "POST", "/api/challenges/containers/stop",
            json={"id": int(challenge_id)},
            headers={"Content-Type": "application/json"},
        )
        if status not in {200, 201, 202}:
            raise RuntimeError(f"Container stop failed: HTTP {status}: {redact(json.dumps(data))}")
        return data if isinstance(data, dict) else {"raw": data}

    def poll_until_ready(self, challenge_id: int | str, poll_seconds: int = 60,
                         interval: float = 2.0) -> dict:
        """Poll the event endpoint until the challenge container exposes
        host + port, or the timeout elapses. Returns the last raw challenge."""
        deadline = time.time() + poll_seconds
        last: dict = {}
        while time.time() < deadline:
            try:
                last = self.get_challenge_raw(challenge_id)
            except KeyError:
                last = {}
            ports = last.get("docker_ports") or []
            if last.get("docker_online") and last.get("hostname") and ports:
                return last
            time.sleep(interval)
        return last

    # ------------------------------------------------------------------ #
    # Submission
    # ------------------------------------------------------------------ #
    def submit_flag(self, challenge_id: int | str, flag: str) -> dict:
        data, status = self._json(
            "POST", "/api/flags/own",
            json={"challenge_id": int(challenge_id), "flag": flag},
            headers={"Content-Type": "application/json"},
        )
        message = ""
        if isinstance(data, dict):
            message = str(data.get("message", "") or "")
        accepted = status in {200, 201} and "wrong" not in message.lower()
        return {"accepted": accepted, "status_code": status, "message": message,
                "raw": data if isinstance(data, dict) else {"raw": data}}

    # ------------------------------------------------------------------ #
    # Scoreboard / solves
    # ------------------------------------------------------------------ #
    def get_ctf_solves(self) -> Any:
        data, _ = self._json("GET", f"/api/ctfs/solves/{self.ctf_id}")
        return data

    def get_challenge_solves(self, challenge_id: int | str) -> Any:
        data, _ = self._json("GET", f"/api/challenges/{int(challenge_id)}/solves")
        return data

    def get_scores(self) -> Any:
        data, _ = self._json("GET", f"/api/ctfs/scores/{self.ctf_id}")
        return data

    def get_score_charts(self) -> Any:
        data, _ = self._json("GET", f"/api/ctfs/score-charts/{self.ctf_id}")
        return data

    def close(self) -> None:
        try:
            self.session.close()
        except Exception:  # noqa: BLE001
            pass


# --------------------------------------------------------------------------- #
# Dev CLI
# --------------------------------------------------------------------------- #
def _build_client(args) -> HTBCookieClient:
    return HTBCookieClient.from_env_or_headers_file(
        ctf_id=args.ctf_id, headers_file=args.headers_file,
        base_url=args.base_url, timeout=args.timeout, auth_mode=args.auth_mode,
    )


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="HTB CTF cookie/bearer dev client")
    parser.add_argument("--ctf-id", required=True, type=int)
    parser.add_argument("--headers-file")
    parser.add_argument("--base-url", default=BASE_URL)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--auth-mode", default="cookie_bearer",
                        choices=["cookie_bearer", "cookie_only", "bearer_only"])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="Validate access via the menu endpoint")
    p_list = sub.add_parser("list", help="List challenges")
    p_list.add_argument("--category")
    p_scores = sub.add_parser("scores", help="Print scoreboard")  # noqa: F841

    args = parser.parse_args(argv)
    client = _build_client(args)

    if args.cmd == "check":
        can, menu = client.validate_access()
        print(json.dumps({
            "event": menu.get("name"),
            "status": menu.get("status"),
            "userCanViewChallenges": can,
        }, indent=2, ensure_ascii=False))
        return 0 if can else 2

    if args.cmd == "list":
        cats = client.get_categories()
        rows = []
        for raw in client.list_challenges_raw():
            cat = cats.get(int(raw.get("challenge_category_id") or 0), "unknown")
            if getattr(args, "category", None) and cat.lower() != args.category.lower():
                continue
            rows.append({
                "id": raw.get("id"), "name": raw.get("name"), "category": cat,
                "points": raw.get("points"), "solves": raw.get("solves"),
                "solved": bool(raw.get("solved")), "filename": raw.get("filename"),
                "docker_online": bool(raw.get("docker_online")),
            })
        print(json.dumps(rows, indent=2, ensure_ascii=False))
        return 0

    if args.cmd == "scores":
        print(redact(json.dumps(client.get_scores(), indent=2, ensure_ascii=False)))
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
