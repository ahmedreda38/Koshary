"""A no-network fake ``requests.Session`` for the htb_cookie adapter tests.

Dispatches by HTTP method + URL path to JSON fixtures under
``tests/fixtures/htb_cookie``. The signed-download URL returns fake archive
bytes. Flag submission is ``correct`` only for ``HTB{correct}``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

import requests

FIX = Path(__file__).parent / "fixtures" / "htb_cookie"


def load(name: str) -> Any:
    return json.loads((FIX / name).read_text(encoding="utf-8"))


class FakeResponse:
    def __init__(self, status_code: int, json_data: Any = None, *, text: str = "",
                 url: str = "", headers: Optional[dict] = None, content: bytes = b""):
        self.status_code = status_code
        self._json = json_data
        self.text = text or (json.dumps(json_data) if json_data is not None else "")
        self.url = url
        self.headers = headers or {}
        self._content = content

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    def json(self) -> Any:
        if self._json is None:
            raise ValueError("no json body")
        return self._json

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size: int = 1):
        if self._content:
            yield self._content

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeHTBSession:
    def __init__(self, ctf_id: int = 1434, correct_flag: str = "HTB{correct}",
                 download_bytes: bytes = b"PK\x03\x04 not a real zip"):
        self.headers: dict = {}
        self.calls: list[tuple[str, str, Any]] = []
        self.ctf_id = ctf_id
        self.correct = correct_flag
        self.download_bytes = download_bytes
        self.start_count = 0
        self.stop_count = 0

    def request(self, method: str, url: str, timeout=None, headers=None, **kwargs) -> FakeResponse:
        path = urlparse(url).path
        body = kwargs.get("json")
        self.calls.append((method.upper(), path, body))
        return self._route(method.upper(), path, body, url)

    def _route(self, method: str, path: str, body: Any, url: str) -> FakeResponse:
        if path == "/api/public/challenge-categories":
            return FakeResponse(200, load("categories.json"))
        if path == f"/api/ctfs/{self.ctf_id}/menu":
            return FakeResponse(200, load("menu_1434.json"))
        if path == f"/api/ctfs/{self.ctf_id}":
            return FakeResponse(200, load("event_1434.json"))
        if re.fullmatch(r"/api/challenges/\d+/download/link", path):
            return FakeResponse(200, load("download_link.json"))
        if re.fullmatch(r"/challenges/\d+/download", path):
            return FakeResponse(
                200, content=self.download_bytes, url=url,
                headers={"content-disposition": 'attachment; filename="dynastic.zip"'},
            )
        if path == "/api/challenges/containers/start":
            self.start_count += 1
            return FakeResponse(200, load("container_start.json"))
        if path == "/api/challenges/containers/stop":
            self.stop_count += 1
            return FakeResponse(200, load("container_stop.json"))
        if path == "/api/flags/own":
            flag = (body or {}).get("flag")
            if flag == self.correct:
                return FakeResponse(200, load("flag_correct.json"))
            return FakeResponse(400, load("flag_wrong.json"))
        if path == f"/api/ctfs/scores/{self.ctf_id}":
            return FakeResponse(200, load("scores_1434.json"))
        return FakeResponse(404, {"message": "not found"})

    def close(self) -> None:
        pass


class AuthFailSession(FakeHTBSession):
    """Returns 401 for every request (to exercise the auth-error path)."""

    def _route(self, method, path, body, url):
        return FakeResponse(401, {"message": "Unauthenticated."})
