#!/usr/bin/env python3
"""
Koshary Framework - Hack The Box CTF Setup Utility.

Configures .env and config.json for solving an HTB CTF event through the
official HTB CTF MCP server.

Examples:
    python3 setup_htb.py --check-token
    python3 setup_htb.py --list-events
    python3 setup_htb.py --interactive
    python3 setup_htb.py --event cyber-apocalypse-2026 --sync-only
    python3 setup_htb.py --event cyber-apocalypse-2026 \
        --models 'web:C,crypto:C,pwn:C,rev:C,forensics:G,misc:G,fullpwn:C'
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from core.flag_extractor import HTB_DEFAULT_PATTERNS


def load_env(env_path: Path) -> None:
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.strip().strip("'").strip('"'))


def upsert_env(env_path: Path, key: str, value: str) -> None:
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    out, replaced = [], False
    for line in lines:
        if line.startswith(f"{key}="):
            out.append(f"{key}={value}")
            replaced = True
        else:
            out.append(line)
    if not replaced:
        out.append(f"{key}={value}")
    env_path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")


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
        cat = cat.strip().lower()
        engine = "gemini" if code.strip().upper() == "G" else "codex"
        routing[cat] = engine
        print(f"    - {cat} -> {engine}")


def build_platform(config: dict):
    from platforms.htb_ctf_mcp import HTBCTFPlatform

    return HTBCTFPlatform(config)


def main() -> int:
    parser = argparse.ArgumentParser(description="Koshary HTB CTF Setup Utility")
    parser.add_argument("--token", help="HTB MCP token (otherwise read from .env / env)")
    parser.add_argument("--event", help="HTB event id/slug to configure")
    parser.add_argument("--models", help="Routing mapping, e.g. 'web:C,crypto:C,forensics:G'")
    parser.add_argument("--mcp-url", help="Override HTB MCP URL")
    parser.add_argument("--check-token", action="store_true", help="Verify token + connectivity, then exit")
    parser.add_argument("--list-events", action="store_true", help="List available HTB events, then exit")
    parser.add_argument("--sync-only", action="store_true", help="Only update config (no solving)")
    parser.add_argument("--join", action="store_true", help="Register your team for the selected event (state-changing)")
    parser.add_argument("--team-id", help="Team id to join with (otherwise your first team)")
    parser.add_argument("--ctf-password", help="Event password, if the event requires one")
    parser.add_argument("-i", "--interactive", action="store_true", help="Interactively pick event + routing")
    args = parser.parse_args()

    root = Path(".").resolve()
    env_path = root / ".env"
    config_path = root / "config.json"

    load_env(env_path)
    config = load_config(config_path)
    config.setdefault("htb", {})
    if args.mcp_url:
        config["htb"]["mcp_url"] = args.mcp_url

    # 1-2. Token handling
    token = args.token or os.getenv("HTB_MCP_TOKEN", "").strip()
    if args.token:
        upsert_env(env_path, "HTB_MCP_TOKEN", args.token)
        os.environ["HTB_MCP_TOKEN"] = args.token
        print("[+] Wrote HTB_MCP_TOKEN to .env")
    if not token:
        print("[!] HTB_MCP_TOKEN is not set. Provide --token or add it to .env.")
        return 1
    os.environ["HTB_MCP_TOKEN"] = token

    # 3. Connect
    print("[*] Connecting to HTB MCP...")
    try:
        platform = build_platform(config)
        platform.client.list_tools()
    except Exception as exc:  # noqa: BLE001
        from core.logging_utils import redact

        print(f"[!] Could not connect to HTB MCP: {redact(str(exc))}")
        return 1
    print(f"[+] Connected. Discovered {len(platform.client.tools)} MCP tool(s).")

    if args.check_token:
        print("[+] Token OK.")
        return 0

    # 4. List events
    events = []
    try:
        events = platform.list_events()
    except Exception as exc:  # noqa: BLE001
        from core.logging_utils import redact

        print(f"[!] Could not list events: {redact(str(exc))}")

    if args.list_events:
        print(f"[+] {len(events)} event(s):")
        for ev in events:
            slug = ev.get("slug") or ev.get("id") or ev.get("event_id") or "?"
            name = ev.get("name") or ev.get("title") or "?"
            print(f"    - {slug}  ::  {name}")
        return 0

    # 5. Select event
    event = args.event or config["htb"].get("event", "")
    if args.interactive and events and not args.event:
        print("\n[?] Select an event:")
        for i, ev in enumerate(events, 1):
            slug = ev.get("slug") or ev.get("id") or ev.get("event_id") or "?"
            name = ev.get("name") or ev.get("title") or "?"
            print(f"    {i}. {slug}  ::  {name}")
        choice = input("    Event number (or paste slug): ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(events):
            ev = events[int(choice) - 1]
            event = ev.get("slug") or ev.get("id") or ev.get("event_id") or ""
        elif choice:
            event = choice

    if not event:
        print("[!] No event selected. Use --event SLUG or --interactive.")
        return 1

    config["platform"] = "htb_ctf"
    config["htb"]["event"] = event
    platform.event = event
    platform._ctf_id = None
    if args.team_id:
        config["htb"]["team_id"] = args.team_id
        platform.team_id = args.team_id
    print(f"[*] Configured event: {event}")

    # 6. Optionally join the event (state-changing — only with --join/auto_join)
    if args.join or config["htb"].get("auto_join"):
        from core.logging_utils import redact

        try:
            res = platform.join_event(team_id=args.team_id, consent=True,
                                      password=args.ctf_password)
            if platform.team_id and not config["htb"].get("team_id"):
                config["htb"]["team_id"] = platform.team_id
            print(f"[+] Joined event {event} (team {platform.team_id}).")
        except Exception as exc:  # noqa: BLE001
            print(f"[!] Join failed: {redact(str(exc))}")

    # 7. Pull challenge categories (best effort)
    try:
        challenges = platform.list_challenges()
        cats = sorted({c.category for c in challenges if c.category})
        print(f"[+] {len(challenges)} challenge(s) across categories: {', '.join(cats) or 'unknown'}")
    except Exception as exc:  # noqa: BLE001
        from core.logging_utils import redact

        print(f"[!] Could not list challenges yet: {redact(str(exc))}")
        print("    (If this is a 403, join the event first: setup_htb.py --event "
              f"{event} --join)")

    # 8. Routing preferences
    if args.models:
        print("[*] Updating model routing:")
        apply_model_mapping(config, args.models)
    elif args.interactive:
        print("\n[?] Routing (G = Gemini, C = Codex). Press Enter to keep current.")
        routing = config.setdefault("routing", {})
        for cat in ["web", "crypto", "pwn", "rev", "forensics", "misc", "fullpwn"]:
            cur = routing.get(cat, "codex")
            choice = input(f"    - {cat} [G/C] (default {cur[0].upper()}): ").strip().upper()
            if choice in ("G", "C"):
                routing[cat] = "gemini" if choice == "G" else "codex"

    # 10-11. Persist
    ensure_flag_patterns(config)
    save_config(config_path, config)
    print("[+] Updated config.json (platform=htb_ctf, htb.event set, HTB flag patterns added).")

    print("\n[!] Setup complete. Next:")
    print(f"    python3 orchestrator.py --platform htb_ctf --event {event} --list-challenges")
    print(f"    python3 orchestrator.py --platform htb_ctf --event {event} --categories web --plan --no-submit")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n[!] Setup aborted.")
        sys.exit(1)
