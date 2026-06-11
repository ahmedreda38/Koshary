#!/usr/bin/env python3
"""
HTB CTF cookie/bearer client for Koshary.

This client is based on browser requests captured from ctf.hackthebox.com.
Use only with your own HTB account/session and only for CTF events you are
authorized to access.

Recommended auth input:
  - HTB_CTF_COOKIE: full Cookie header value from browser/Burp
  - HTB_CTF_BEARER: Bearer token value without the "Bearer " prefix

Alternative:
  - --headers-file containing a copied raw request. The client extracts Cookie
    and Authorization from it.

Example:
  python3 htb_cookie_client.py --ctf-id 1434 --headers-file htb_headers.txt list
  python3 htb_cookie_client.py --ctf-id 1434 --headers-file htb_headers.txt download --out challenges/1434
  python3 htb_cookie_client.py --ctf-id 1434 --headers-file htb_headers.txt start 31856
  python3 htb_cookie_client.py --ctf-id 1434 --headers-file htb_headers.txt submit 31856 'HTB{...}'
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse, unquote

import requests


BASE_URL = "https://ctf.hackthebox.com"


@dataclass
class HTBChallenge:
    id: int
    name: str
    category_id: Optional[int]
    category: str
    difficulty: Optional[str]
    points: Optional[int]
    solves: Optional[int]
    solved: bool
    description: str
    filename: Optional[str]
    has_docker: bool
    docker_online: bool
    docker_ports: list[int]
    docker_instance_type: Optional[str]
    hostname: Optional[str]
    has_machine: bool
    target_kind: str
    raw: dict[str, Any]


def parse_headers_file(path: str | Path) -> dict[str, str]:
    """
    Parse a copied raw HTTP request or simple header file and return headers.
    This intentionally extracts only the headers needed by the client.
    """
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    headers: dict[str, str] = {}

    for line in text.splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        key = k.strip().lower()
        val = v.strip()
        if key in {"cookie", "authorization", "user-agent"}:
            headers[key] = val

    return headers


def safe_slug(s: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "_", s.strip()).strip("_")
    return slug or "challenge"


def filename_from_response(resp: requests.Response, fallback: str) -> str:
    cd = resp.headers.get("content-disposition", "")
    m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', cd, re.I)
    if m:
        return safe_slug(unquote(m.group(1)))

    parsed = urlparse(resp.url)
    name = Path(parsed.path).name
    if name and name != "download":
        return safe_slug(unquote(name))

    return safe_slug(fallback)


class HTBCookieClient:
    def __init__(
        self,
        ctf_id: int,
        cookie: Optional[str] = None,
        bearer: Optional[str] = None,
        user_agent: Optional[str] = None,
        base_url: str = BASE_URL,
        timeout: int = 30,
    ):
        self.ctf_id = int(ctf_id)
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()

        self.session.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": user_agent
                or "Mozilla/5.0 (X11; Linux x86_64) Koshary-HTB-CTF-Client/1.0",
                "Referer": f"{self.base_url}/event/{self.ctf_id}",
            }
        )

        if cookie:
            self.session.headers["Cookie"] = cookie.strip()

        if bearer:
            bearer = bearer.strip()
            if bearer.lower().startswith("bearer "):
                self.session.headers["Authorization"] = bearer
            else:
                self.session.headers["Authorization"] = f"Bearer {bearer}"

    @classmethod
    def from_env_or_headers_file(
        cls,
        ctf_id: int,
        headers_file: Optional[str] = None,
        base_url: str = BASE_URL,
        timeout: int = 30,
    ) -> "HTBCookieClient":
        cookie = os.getenv("HTB_CTF_COOKIE")
        bearer = os.getenv("HTB_CTF_BEARER")
        user_agent = os.getenv("HTB_CTF_USER_AGENT")

        if headers_file:
            parsed = parse_headers_file(headers_file)
            cookie = parsed.get("cookie", cookie)
            auth = parsed.get("authorization")
            if auth:
                bearer = auth.replace("Bearer ", "", 1).strip()
            user_agent = parsed.get("user-agent", user_agent)

        if not cookie and not bearer:
            raise SystemExit(
                "Missing auth. Set HTB_CTF_COOKIE/HTB_CTF_BEARER or pass --headers-file."
            )

        return cls(
            ctf_id=ctf_id,
            cookie=cookie,
            bearer=bearer,
            user_agent=user_agent,
            base_url=base_url,
            timeout=timeout,
        )

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _request(self, method: str, path_or_url: str, **kwargs) -> requests.Response:
        url = path_or_url if path_or_url.startswith("http") else self._url(path_or_url)

        headers = kwargs.pop("headers", {})
        if method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
            headers.setdefault("Origin", self.base_url)
            headers.setdefault("Referer", f"{self.base_url}/event/{self.ctf_id}")

        resp = self.session.request(
            method,
            url,
            timeout=self.timeout,
            headers=headers,
            **kwargs,
        )

        if resp.status_code == 401:
            raise RuntimeError("HTB returned 401 Unauthorized. Refresh Cookie/Bearer token.")
        if resp.status_code == 403:
            raise RuntimeError("HTB returned 403 Forbidden. Check event access/session/Cloudflare.")
        return resp

    def _json(self, method: str, path: str, **kwargs) -> Any:
        resp = self._request(method, path, **kwargs)
        try:
            data = resp.json()
        except Exception as e:
            raise RuntimeError(f"Expected JSON from {path}, got {resp.status_code}: {resp.text[:300]}") from e

        # Keep 400 responses visible for flag submission handling, but fail for others.
        if not resp.ok and path != "/api/flags/own":
            raise RuntimeError(f"{method} {path} failed: HTTP {resp.status_code}: {data}")

        return data, resp.status_code

    def get_categories(self) -> dict[int, str]:
        data, _ = self._json("GET", "/api/public/challenge-categories")
        return {int(row["id"]): row["name"] for row in data}

    def get_event(self) -> dict[str, Any]:
        data, _ = self._json("GET", f"/api/ctfs/{self.ctf_id}")
        return data

    def get_menu(self) -> dict[str, Any]:
        data, _ = self._json("GET", f"/api/ctfs/{self.ctf_id}/menu")
        return data

    def list_challenges(self) -> list[HTBChallenge]:
        categories = self.get_categories()
        event = self.get_event()
        challenges = []

        for raw in event.get("challenges", []):
            category_id = raw.get("challenge_category_id")
            category = categories.get(int(category_id), f"category_{category_id}") if category_id else "unknown"

            has_docker = bool(raw.get("hasDocker"))
            has_machine = bool(raw.get("hasMachine") or raw.get("machine"))

            if has_machine:
                target_kind = "fullpwn"
            elif has_docker:
                inst_type = (raw.get("docker_instance_type") or "").lower()
                target_kind = "web" if inst_type == "web" else "tcp"
            elif raw.get("filename"):
                target_kind = "static"
            else:
                target_kind = "unknown"

            ports = raw.get("docker_ports") or []
            if not isinstance(ports, list):
                ports = [ports]

            challenges.append(
                HTBChallenge(
                    id=int(raw["id"]),
                    name=raw.get("name") or str(raw["id"]),
                    category_id=category_id,
                    category=category,
                    difficulty=raw.get("difficulty"),
                    points=raw.get("points"),
                    solves=raw.get("solves"),
                    solved=bool(raw.get("solved")),
                    description=raw.get("description") or "",
                    filename=raw.get("filename") or None,
                    has_docker=has_docker,
                    docker_online=bool(raw.get("docker_online")),
                    docker_ports=[int(p) for p in ports if str(p).isdigit()],
                    docker_instance_type=raw.get("docker_instance_type"),
                    hostname=raw.get("hostname"),
                    has_machine=has_machine,
                    target_kind=target_kind,
                    raw=raw,
                )
            )

        return challenges

    def get_challenge(self, challenge_id: int) -> HTBChallenge:
        for challenge in self.list_challenges():
            if challenge.id == int(challenge_id):
                return challenge
        raise KeyError(f"Challenge {challenge_id} not found in CTF {self.ctf_id}")

    def get_download_link(self, challenge_id: int) -> Optional[str]:
        data, status = self._json("GET", f"/api/challenges/{int(challenge_id)}/download/link")
        if status != 200:
            return None
        return data.get("url")

    def download_challenge(self, challenge_id: int, out_dir: str | Path) -> Optional[Path]:
        challenge = self.get_challenge(challenge_id)
        if not challenge.filename:
            return None

        signed_url = self.get_download_link(challenge_id)
        if not signed_url:
            return None

        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        resp = self._request(
            "GET",
            signed_url,
            headers={
                "Accept": "application/octet-stream,*/*",
                "Referer": f"{self.base_url}/event/{self.ctf_id}",
            },
            stream=True,
            allow_redirects=True,
        )
        resp.raise_for_status()

        fname = filename_from_response(resp, challenge.filename)
        path = out_dir / fname

        with path.open("wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 256):
                if chunk:
                    f.write(chunk)

        return path

    def start_container(self, challenge_id: int, poll: bool = True, poll_seconds: int = 60) -> HTBChallenge:
        data, status = self._json(
            "POST",
            "/api/challenges/containers/start",
            json={"id": int(challenge_id)},
            headers={"Content-Type": "application/json"},
        )

        if status not in {200, 201, 202}:
            raise RuntimeError(f"Container start failed: HTTP {status}: {data}")

        if not poll:
            return self.get_challenge(challenge_id)

        deadline = time.time() + poll_seconds
        last = None
        while time.time() < deadline:
            last = self.get_challenge(challenge_id)
            if last.docker_online and last.hostname and last.docker_ports:
                return last
            time.sleep(2)

        return last or self.get_challenge(challenge_id)

    def stop_container(self, challenge_id: int) -> dict[str, Any]:
        data, status = self._json(
            "POST",
            "/api/challenges/containers/stop",
            json={"id": int(challenge_id)},
            headers={"Content-Type": "application/json"},
        )
        if status not in {200, 201, 202}:
            raise RuntimeError(f"Container stop failed: HTTP {status}: {data}")
        return data

    def submit_flag(self, challenge_id: int, flag: str) -> dict[str, Any]:
        data, status = self._json(
            "POST",
            "/api/flags/own",
            json={"challenge_id": int(challenge_id), "flag": flag},
            headers={"Content-Type": "application/json"},
        )

        message = data.get("message", "")
        accepted = status in {200, 201} and "wrong" not in message.lower()

        return {
            "accepted": accepted,
            "status_code": status,
            "message": message,
            "raw": data,
        }

    def get_ctf_solves(self) -> Any:
        data, _ = self._json("GET", f"/api/ctfs/solves/{self.ctf_id}")
        return data

    def get_challenge_solves(self, challenge_id: int) -> Any:
        data, _ = self._json("GET", f"/api/challenges/{int(challenge_id)}/solves")
        return data

    def get_scores(self) -> Any:
        data, _ = self._json("GET", f"/api/ctfs/scores/{self.ctf_id}")
        return data

    def get_score_charts(self) -> Any:
        data, _ = self._json("GET", f"/api/ctfs/score-charts/{self.ctf_id}")
        return data


def cmd_list(client: HTBCookieClient, args: argparse.Namespace) -> int:
    challenges = client.list_challenges()
    rows = []
    for c in challenges:
        if args.category and c.category.lower() != args.category.lower():
            continue
        rows.append(
            {
                "id": c.id,
                "category": c.category,
                "name": c.name,
                "difficulty": c.difficulty,
                "points": c.points,
                "solves": c.solves,
                "solved": c.solved,
                "filename": c.filename,
                "target_kind": c.target_kind,
                "online": c.docker_online,
                "target": f"{c.hostname}:{c.docker_ports[0]}" if c.hostname and c.docker_ports else None,
            }
        )
    print(json.dumps(rows, indent=2, ensure_ascii=False))
    return 0


def cmd_download(client: HTBCookieClient, args: argparse.Namespace) -> int:
    out = Path(args.out)
    if args.challenge_id:
        ids = [int(args.challenge_id)]
    else:
        ids = [c.id for c in client.list_challenges() if c.filename]

    for cid in ids:
        try:
            c = client.get_challenge(cid)
            cdir = out / safe_slug(c.category.lower()) / f"{cid}_{safe_slug(c.name)}" / "files"
            path = client.download_challenge(cid, cdir)
            if path:
                print(f"[+] {cid}: downloaded {path}")
            else:
                print(f"[-] {cid}: no downloadable file")
        except Exception as e:
            print(f"[!] {cid}: {e}", file=sys.stderr)

    return 0


def cmd_start(client: HTBCookieClient, args: argparse.Namespace) -> int:
    c = client.start_container(args.challenge_id, poll=not args.no_poll, poll_seconds=args.poll_seconds)
    print(json.dumps(asdict(c), indent=2, ensure_ascii=False))
    return 0


def cmd_stop(client: HTBCookieClient, args: argparse.Namespace) -> int:
    print(json.dumps(client.stop_container(args.challenge_id), indent=2, ensure_ascii=False))
    return 0


def cmd_submit(client: HTBCookieClient, args: argparse.Namespace) -> int:
    result = client.submit_flag(args.challenge_id, args.flag)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["accepted"] else 2


def cmd_scores(client: HTBCookieClient, args: argparse.Namespace) -> int:
    print(json.dumps(client.get_scores(), indent=2, ensure_ascii=False))
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="HTB CTF cookie/bearer client for Koshary")
    parser.add_argument("--ctf-id", required=True, type=int, help="HTB CTF event id, e.g. 1434")
    parser.add_argument("--headers-file", help="Raw browser/Burp request file to extract Cookie/Authorization")
    parser.add_argument("--base-url", default=BASE_URL)
    parser.add_argument("--timeout", type=int, default=30)

    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="List challenges")
    p_list.add_argument("--category")
    p_list.set_defaults(func=cmd_list)

    p_dl = sub.add_parser("download", help="Download one or all downloadable challenges")
    p_dl.add_argument("challenge_id", nargs="?", type=int)
    p_dl.add_argument("--out", default="challenges")
    p_dl.set_defaults(func=cmd_download)

    p_start = sub.add_parser("start", help="Start challenge container")
    p_start.add_argument("challenge_id", type=int)
    p_start.add_argument("--no-poll", action="store_true")
    p_start.add_argument("--poll-seconds", type=int, default=60)
    p_start.set_defaults(func=cmd_start)

    p_stop = sub.add_parser("stop", help="Stop challenge container")
    p_stop.add_argument("challenge_id", type=int)
    p_stop.set_defaults(func=cmd_stop)

    p_submit = sub.add_parser("submit", help="Submit flag")
    p_submit.add_argument("challenge_id", type=int)
    p_submit.add_argument("flag")
    p_submit.set_defaults(func=cmd_submit)

    p_scores = sub.add_parser("scores", help="Get scoreboard")
    p_scores.set_defaults(func=cmd_scores)

    args = parser.parse_args(argv)
    client = HTBCookieClient.from_env_or_headers_file(
        ctf_id=args.ctf_id,
        headers_file=args.headers_file,
        base_url=args.base_url,
        timeout=args.timeout,
    )
    return args.func(client, args)


if __name__ == "__main__":
    raise SystemExit(main())
