"""
Koshary platform abstraction layer.

Every supported CTF source (CTFd, Hack The Box CTF, ...) implements
``BasePlatform``. The orchestrator only ever talks to this interface and the
normalized data objects below, so it never needs to know whether a challenge
came from CTFd or HTB.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class NormalizedChallenge:
    """A platform-independent view of a single CTF challenge."""

    platform: str
    event_id: str
    challenge_id: str
    name: str
    category: str
    points: Optional[int]
    description: str
    solved: bool = False

    files: list[str] = field(default_factory=list)

    # Generic / HTB target info
    target_kind: str = "static"  # static, docker, fullpwn, unknown
    host: Optional[str] = None
    port: Optional[int] = None
    url: Optional[str] = None
    vpn_required: bool = False

    # Raw platform payload, kept for debugging and for platform-specific
    # actions (e.g. CTFd needs the integer id for submission).
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def slug(self) -> str:
        import re

        return re.sub(r"[^a-z0-9]+", "-", self.name.lower()).strip("-") or "challenge"

    @property
    def connection_info(self) -> Optional[str]:
        """Best-effort human-readable connection string for prompts."""
        if self.url:
            return self.url
        if self.host and self.port:
            return f"{self.host}:{self.port}"
        if self.host:
            return self.host
        return None


@dataclass
class SubmitResult:
    accepted: bool
    message: str
    raw: dict[str, Any] = field(default_factory=dict)

    # Some platforms can tell us a flag was already solved / duplicate.
    already_solved: bool = False


class BasePlatform(ABC):
    """Common interface implemented by every platform adapter."""

    name: str = "base"

    # ------------------------------------------------------------------ #
    # Discovery
    # ------------------------------------------------------------------ #
    @abstractmethod
    def list_challenges(self) -> list[NormalizedChallenge]:
        """Return all challenges for the active event/competition."""

    @abstractmethod
    def get_challenge(self, challenge_id: str) -> NormalizedChallenge:
        """Return the fully-detailed challenge for ``challenge_id``."""

    # ------------------------------------------------------------------ #
    # Files
    # ------------------------------------------------------------------ #
    @abstractmethod
    def download_files(self, challenge: NormalizedChallenge, dest_dir: str) -> list[str]:
        """Download all challenge attachments into ``dest_dir``.

        Returns the list of local paths written.
        """

    # ------------------------------------------------------------------ #
    # Instance management (optional - default no-ops for static platforms)
    # ------------------------------------------------------------------ #
    def needs_instance(self, challenge: NormalizedChallenge) -> bool:
        return challenge.target_kind in ("docker", "fullpwn")

    def start_instance(self, challenge: NormalizedChallenge) -> NormalizedChallenge:
        return challenge

    def stop_instance(self, challenge: NormalizedChallenge) -> None:
        return None

    def instance_status(self, challenge: NormalizedChallenge) -> dict:
        return {}

    # ------------------------------------------------------------------ #
    # Submission
    # ------------------------------------------------------------------ #
    @abstractmethod
    def submit_flag(self, challenge: NormalizedChallenge, flag: str) -> SubmitResult:
        """Submit ``flag`` for ``challenge`` and return a normalized result."""

    # ------------------------------------------------------------------ #
    # Optional capabilities
    # ------------------------------------------------------------------ #
    def get_scoreboard(self) -> list[dict]:
        return []

    def close(self) -> None:
        return None
