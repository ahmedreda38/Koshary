"""Platform adapter registry / factory."""

from __future__ import annotations

from typing import Optional

from platforms.base import BasePlatform, NormalizedChallenge, SubmitResult

__all__ = [
    "BasePlatform",
    "NormalizedChallenge",
    "SubmitResult",
    "get_platform",
]


def get_platform(name: str, config: dict, *, session: Optional[str] = None,
                 logger=None, **kwargs) -> BasePlatform:
    """Instantiate a platform adapter by name.

    Imports are lazy so that, e.g., running the CTFd flow never imports the HTB
    MCP client (and vice-versa).
    """
    key = (name or "ctfd").lower().strip()
    if key in ("ctfd", "ctf"):
        from platforms.ctfd import CTFdPlatform

        return CTFdPlatform(config, session=session, logger=logger, **kwargs)
    if key in ("htb_ctf", "htb", "hackthebox"):
        from platforms.htb_ctf_mcp import HTBCTFPlatform

        return HTBCTFPlatform(config, logger=logger, **kwargs)
    raise ValueError(f"Unknown platform: {name!r}")
