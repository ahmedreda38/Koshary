#!/usr/bin/env python3
"""
Koshary Framework - Hack The Box CTF (cookie/bearer) Setup Utility.

Configures config.json for solving an HTB CTF event through the HTB web API,
authenticated with a captured browser session (Cookie + Authorization: Bearer).
Works on events where MCP is disabled.

Credentials are read from .env (HTB_CTF_COOKIE / HTB_CTF_BEARER /
HTB_CTF_USER_AGENT) or from a --headers-file. This script NEVER prints them.

Examples:
    python3 setup_htb_cookie.py --ctf-id 1434 --headers-file htb_headers.txt --check
    python3 setup_htb_cookie.py --ctf-id 1434 --headers-file htb_headers.txt --list
    python3 setup_htb_cookie.py --ctf-id 1434 --interactive
    python3 setup_htb_cookie.py --ctf-id 1434 --models 'web:G,crypto:L,pwn:C,rev:L'
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from core.flag_extractor import HTB_DEFAULT_PATTERNS
from core.logging_utils import redact

_ROUTE_CODES = {"G": "gemini", "C": "codex", "L": "claude"}


def load_env(env_path: Path) -> None:
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.strip().strip("'").strip('"'))


def load_config(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save_config(path: Path, config: dict) -> None:
    path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


def ensure_flag_patterns(config: dict) -> None:
    patterns = config.setdefault("ctf", {}).setdefault("flag_patterns", [])
    for pat in HTB_DEFAULT_PATTERNS:
        if pat not in patterns:
            patterns.append(pat)


def apply_model_mapping(config: dict, mapping: str) -> None:
    routing = config.setdefault("routing", {})
    for item in mapping.split(","):
        if ":" not in item:
            continue
        cat, code = item.split(":", 1)
        engine = _ROUTE_CODES.get(code.strip().upper())
        if not engine:
            continue
        routing[cat.strip().lower()] = engine
        print(f"    - {cat.strip().lower()} -> {engine}")


def build_client(ctf_id: int, headers_file, base_url, auth_mode):
    from core.htb_cookie_client import HTBCookieClient

    return HTBCookieClient.from_env_or_headers_file(
        ctf_id=ctf_id, headers_file=headers_file, base_url=base_url, auth_mode=auth_mode,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Koshary HTB CTF cookie/bearer setup")
    parser.add_argument("--ctf-id", required=True, type=int, help="HTB CTF event id, e.g. 1434")
    parser.add_argument("--headers-file", help="Raw request file with Cookie/Authorization")
    parser.add_argument("--base-url", default="https://ctf.hackthebox.com")
    parser.add_argument("--auth-mode", default="cookie_bearer",
                        choices=["cookie_bearer", "cookie_only", "bearer_only"])
    parser.add_argument("--models", help="Routing mapping, e.g. 'web:G,crypto:L,pwn:C' (G/C/L)")
    parser.add_argument("--check", action="store_true", help="Validate access, then exit")
    parser.add_argument("--list", action="store_true", help="List challenges, then exit")
    parser.add_argument("-i", "--interactive", action="store_true", help="Interactive routing")
    parser.add_argument("--store-headers-file", action="store_true",
                        help="Persist the --headers-file path in config (else rely on .env)")
    args = parser.parse_args()

    root = Path(".").resolve()
    env_path = root / ".env"
    config_path = root / "config.json"

    load_env(env_path)
    config = load_config(config_path)
    config.setdefault("htb_cookie", {})

    # 1-3. Build client + validate auth
    print(f"[*] Connecting to {args.base_url} for event {args.ctf_id}...")
    try:
        client = build_client(args.ctf_id, args.headers_file, args.base_url, args.auth_mode)
    except Exception as exc:  # noqa: BLE001
        print(f"[!] {redact(str(exc))}")
        return 1

    try:
        can_view, menu = client.validate_access()
    except Exception as exc:  # noqa: BLE001
        print(f"[!] Access check failed: {redact(str(exc))}")
        print("    (401 -> refresh Cookie/Bearer; 403 -> join the event in the browser first.)")
        return 1

    print(f"[+] Event: {menu.get('name', '?')}  [status={menu.get('status', '?')}]")
    if not can_view:
        print("[!] userCanViewChallenges = false. Join the event in the browser, then retry.")
        return 2
    print("[+] Access OK (userCanViewChallenges = true).")

    if args.check:
        return 0

    # 4-5. Event + categories + challenge summary
    try:
        cats = client.get_categories()
        challenges = client.list_challenges_raw()
        by_cat: dict[str, int] = {}
        for raw in challenges:
            name = cats.get(int(raw.get("challenge_category_id") or 0), "unknown")
            by_cat[name] = by_cat.get(name, 0) + 1
        summary = ", ".join(f"{k}:{v}" for k, v in sorted(by_cat.items()))
        print(f"[+] {len(challenges)} challenge(s): {summary or 'none'}")
    except Exception as exc:  # noqa: BLE001
        print(f"[!] Could not list challenges: {redact(str(exc))}")
        challenges = []

    if args.list:
        for raw in challenges:
            cat = cats.get(int(raw.get("challenge_category_id") or 0), "unknown")
            mark = "x" if raw.get("solved") else " "
            print(f"    [{mark}] {raw.get('id'):>7}  {cat:<12} {raw.get('name')}")
        return 0

    # 6. Routing
    if args.models:
        print("[*] Updating model routing:")
        apply_model_mapping(config, args.models)
    elif args.interactive:
        print("\n[?] Routing (G=Gemini, C=Codex, L=Claude). Enter keeps current.")
        routing = config.setdefault("routing", {})
        for cat in ["web", "crypto", "pwn", "rev", "forensics", "misc", "blockchain", "fullpwn"]:
            cur = routing.get(cat, "codex")
            choice = input(f"    - {cat} [G/C/L] (default {cur}): ").strip().upper()
            if choice in _ROUTE_CODES:
                routing[cat] = _ROUTE_CODES[choice]

    # 7. Persist config
    config["platform"] = "htb_cookie"
    hc = config["htb_cookie"]
    hc["base_url"] = args.base_url
    hc["ctf_id"] = args.ctf_id
    hc["auth_mode"] = args.auth_mode
    hc.setdefault("auto_start_instances", True)
    hc.setdefault("auto_stop_on_solve", False)
    hc.setdefault("auto_start_fullpwn", False)
    hc.setdefault("download_password", "hackthebox")
    hc.setdefault("max_wrong_submissions_per_challenge", 3)
    hc.setdefault("allow_nonstandard_flags", False)
    hc.setdefault("poll_seconds", 60)
    hc.setdefault("poll_interval", 2)
    if args.headers_file and args.store_headers_file:
        hc["headers_file"] = args.headers_file
    elif "headers_file" in hc and not args.headers_file:
        pass  # keep existing

    ensure_flag_patterns(config)
    save_config(config_path, config)
    print("[+] Updated config.json (platform=htb_cookie, htb_cookie.ctf_id set, HTB flag patterns added).")
    if args.headers_file and not args.store_headers_file:
        print("[i] headers-file path NOT stored in config. Either keep passing --headers-file, "
              "or put HTB_CTF_COOKIE/HTB_CTF_BEARER in .env.")

    print("\n[!] Setup complete. Next:")
    print(f"    python3 orchestrator.py --platform htb_cookie --ctf-id {args.ctf_id} --list-challenges")
    print(f"    python3 orchestrator.py --platform htb_cookie --ctf-id {args.ctf_id} --categories web --plan --no-submit")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n[!] Setup aborted.")
        sys.exit(1)
