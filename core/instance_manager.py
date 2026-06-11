"""
Instance lifecycle management for challenges that ship spawnable infrastructure
(HTB Docker challenges and Fullpwn machines).

The orchestrator calls :func:`prepare_target` before solving and, optionally,
:func:`teardown_target` after a solve. All instance start/stop work is delegated
to the platform adapter; this module only decides *when* to do it, waits for the
target to become reachable, and persists ``target.json`` / ``instance.json``.
"""

from __future__ import annotations

import json
import socket
import subprocess
import time
from pathlib import Path
from typing import Optional

from platforms.base import NormalizedChallenge


def write_target(challenge: NormalizedChallenge, workspace: Path, started_by_koshary: bool) -> None:
    data = {
        "kind": challenge.target_kind,
        "host": challenge.host,
        "port": challenge.port,
        "url": challenge.url,
        "vpn_required": challenge.vpn_required,
        "started_by_koshary": started_by_koshary,
    }
    (workspace / "target.json").write_text(json.dumps(data, indent=2), encoding="utf-8")


def write_instance(status: str, workspace: Path, raw: Optional[dict] = None,
                   expires_at: Optional[str] = None) -> None:
    now = time.strftime("%Y-%m-%dT%H:%M:%S%z") or time.strftime("%Y-%m-%dT%H:%M:%S")
    existing = {}
    inst_path = workspace / "instance.json"
    if inst_path.exists():
        try:
            existing = json.loads(inst_path.read_text(encoding="utf-8"))
        except Exception:
            existing = {}
    data = {
        "status": status,
        "started_at": existing.get("started_at") or now,
        "last_checked_at": now,
        "expires_at": expires_at if expires_at is not None else existing.get("expires_at"),
        "raw": raw if raw is not None else existing.get("raw", {}),
    }
    inst_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


# --------------------------------------------------------------------------- #
# Reachability checks
# --------------------------------------------------------------------------- #
def tcp_reachable(host: str, port: int, timeout: float = 5.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def http_reachable(url: str, timeout: float = 5.0) -> bool:
    try:
        import requests

        resp = requests.head(url, timeout=timeout, allow_redirects=True)
        return resp.status_code < 600
    except Exception:
        # HEAD may be unsupported; fall back to a cheap GET.
        try:
            import requests

            resp = requests.get(url, timeout=timeout, stream=True)
            return resp.status_code < 600
        except Exception:
            return False


def icmp_reachable(host: str, timeout: int = 2) -> bool:
    try:
        proc = subprocess.run(
            ["ping", "-c", "1", "-W", str(timeout), host],
            capture_output=True, timeout=timeout + 2, check=False,
        )
        return proc.returncode == 0
    except Exception:
        return False


def wait_for_target(challenge: NormalizedChallenge, attempts: int = 20, delay: float = 6.0,
                    logger=None) -> bool:
    """Poll the challenge target until it answers, or attempts are exhausted."""
    def _log(msg: str) -> None:
        if logger:
            logger.info(msg)

    for i in range(1, attempts + 1):
        ok = False
        if challenge.url:
            ok = http_reachable(challenge.url)
        elif challenge.host and challenge.port:
            ok = tcp_reachable(challenge.host, challenge.port)
        elif challenge.host:
            # Fullpwn machine - ICMP is a reasonable first signal.
            ok = icmp_reachable(challenge.host)
        else:
            return False
        if ok:
            _log(f"Target reachable after {i} check(s).")
            return True
        time.sleep(delay)
    _log("Target did not become reachable in time.")
    return False


# --------------------------------------------------------------------------- #
# Orchestration entry points
# --------------------------------------------------------------------------- #
def prepare_target(platform, challenge: NormalizedChallenge, workspace: Path,
                   config: dict, logger=None, wait: bool = True) -> NormalizedChallenge:
    """Start an instance if the challenge needs one and the config allows it."""
    workspace.mkdir(parents=True, exist_ok=True)

    if not platform.needs_instance(challenge):
        write_target(challenge, workspace, started_by_koshary=False)
        return challenge

    cfg_key = "htb_cookie" if challenge.platform == "htb_cookie" else "htb"
    htb_cfg = config.get(cfg_key, {})

    if challenge.vpn_required and not htb_cfg.get("assume_vpn_connected", False):
        if logger:
            logger.warn(
                f"Challenge '{challenge.name}' requires VPN. Ensure your HTB VPN is connected."
            )

    if not htb_cfg.get("auto_start_instances", True):
        write_target(challenge, workspace, started_by_koshary=False)
        return challenge

    try:
        if logger:
            logger.info(f"Starting instance for '{challenge.name}'...")
        challenge = platform.start_instance(challenge)
        write_target(challenge, workspace, started_by_koshary=True)
        write_instance("running", workspace, raw=challenge.raw.get("instance", {}))
    except Exception as exc:  # noqa: BLE001
        if logger:
            logger.err(f"Instance start failed for '{challenge.name}': {exc}")
        write_target(challenge, workspace, started_by_koshary=False)
        return challenge

    if wait:
        wait_for_target(challenge, logger=logger)
    return challenge


def refresh_target(platform, challenge: NormalizedChallenge, workspace: Path, logger=None) -> dict:
    """Refresh instance status before a solver round."""
    try:
        status = platform.instance_status(challenge)
        if status:
            write_instance(status.get("status", "running"), workspace, raw=status)
        return status
    except Exception as exc:  # noqa: BLE001
        if logger:
            logger.warn(f"Instance status refresh failed: {exc}")
        return {}


def teardown_target(platform, challenge: NormalizedChallenge, workspace: Path, logger=None) -> None:
    """Stop a running instance (used on solve when auto_stop_on_solve is set)."""
    if not platform.needs_instance(challenge):
        return
    try:
        if logger:
            logger.info(f"Stopping instance for '{challenge.name}'...")
        platform.stop_instance(challenge)
        write_instance("stopped", workspace)
    except Exception as exc:  # noqa: BLE001
        if logger:
            logger.warn(f"Instance stop failed for '{challenge.name}': {exc}")
