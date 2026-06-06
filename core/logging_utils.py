"""
Lightweight, dependency-free logging + secret redaction for Koshary's
platform and core modules.

The orchestrator keeps its own colourful console logger; these helpers exist so
that ``core`` / ``platforms`` modules stay decoupled from the orchestrator and
*never* leak secrets (HTB MCP token, CTFd session cookie, Authorization
headers) into stdout or the per-stream log files under ``logs/``.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Iterable, Optional

# Environment variable names whose values must never be logged.
_SECRET_ENV_KEYS = ("HTB_MCP_TOKEN", "CTFD_SESSION")

# Extra literal secrets registered at runtime (e.g. Authorization header value).
_RUNTIME_SECRETS: set[str] = set()


def register_secret(value: Optional[str]) -> None:
    """Register an additional literal value that must be redacted from logs."""
    if value and len(value) >= 4:
        _RUNTIME_SECRETS.add(value)


def redact(text: str) -> str:
    """Replace any known secret occurrence in ``text`` with ``[REDACTED]``."""
    if not text:
        return text
    secrets: Iterable[str] = list(_RUNTIME_SECRETS) + [
        os.getenv(key, "") for key in _SECRET_ENV_KEYS
    ]
    for secret in secrets:
        if secret and len(secret) >= 4:
            text = text.replace(secret, "[REDACTED]")
    # Defensive: redact obvious bearer tokens even if not pre-registered.
    return text


def _ts() -> str:
    return time.strftime("%H:%M:%S")


class StreamLogger:
    """Tiny logger that mirrors messages to stdout and an optional file.

    Always passes messages through :func:`redact` first.
    """

    def __init__(self, name: str, log_file: Optional[Path] = None, echo: bool = True):
        self.name = name
        self.echo = echo
        self.log_file = Path(log_file) if log_file else None
        if self.log_file:
            self.log_file.parent.mkdir(parents=True, exist_ok=True)

    def _emit(self, level: str, msg: str) -> None:
        line = f"[{_ts()}][{self.name}][{level}] {redact(str(msg))}"
        if self.echo:
            print(line, flush=True)
        if self.log_file:
            try:
                with open(self.log_file, "a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
            except Exception:
                pass

    def info(self, msg: str) -> None:
        self._emit("INFO", msg)

    def ok(self, msg: str) -> None:
        self._emit(" OK ", msg)

    def warn(self, msg: str) -> None:
        self._emit("WARN", msg)

    def err(self, msg: str) -> None:
        self._emit("ERR ", msg)

    def debug(self, msg: str) -> None:
        self._emit("DBG ", msg)
