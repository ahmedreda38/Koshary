#!/usr/bin/env python3
"""
Koshary Framework - CTF Setup Utility
Automates the configuration of .env and config.json for new competitions.
Includes interactive and manual model engine mapping (Gemini/Codex).
"""

import json
import argparse
import os
import re
import sys
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description="Koshary CTF Setup Utility")
    parser.add_argument("--url", required=True, help="Base URL of the CTFd instance")
    parser.add_argument("--session", required=True, help="CTFd session cookie value")
    parser.add_argument("--flag", required=True, help="Flag format (e.g., 'MyCTF{}')")
    parser.add_argument("--models", help="Manual mapping (e.g., 'web:G,crypto:C')")
    parser.add_argument("-i", "--interactive", action="store_true", help="Interactively choose models for each category")
    args = parser.parse_args()

    root = Path(".").resolve()
    config_path = root / "config.json"
    env_path = root / ".env"

    # 1. Process Inputs
    url = args.url.rstrip("/")
    ctf_name = url.split("//")[-1].split(".")[0].replace("-", " ").title()
    
    session = args.session
    if session.startswith("session="):
        session = session[len("session="):]

    flag_format = args.flag
    if "{}" in flag_format:
        flag_regex = flag_format.replace("{", "\\{").replace("}", "[^\\s]+\\}")
    else:
        flag_regex = flag_format

    print(f"\n[*] Setting up for: {ctf_name}")
    print(f"[*] URL: {url}")
    print(f"[*] Regex Pattern: {flag_regex}")

    # 2. Update .env
    env_path.write_text(f"CTFD_SESSION={session}\n", encoding="utf-8")
    print("[+] Updated .env")

    # 3. Update config.json
    if config_path.exists():
        config = json.loads(config_path.read_text(encoding="utf-8"))
        
        config["ctf"]["name"] = ctf_name
        config["ctf"]["base_url"] = url
        
        if flag_regex not in config["ctf"]["flag_patterns"]:
            config["ctf"]["flag_patterns"].insert(0, flag_regex)

        # Handle Model Mapping (Interactive or Manual)
        if args.interactive:
            print("\n[?] Interactive Model Configuration (G = Gemini, C = Codex)")
            # Unique categories to avoid asking for 'web' and 'web exploitation' separately
            unique_cats = sorted(list(set(config["routing"].keys())))
            
            for cat in unique_cats:
                while True:
                    choice = input(f"    - Engine for '{cat}' [G/C] (default {config['routing'][cat][0].upper()}): ").strip().upper()
                    if not choice:
                        break # Keep default
                    if choice in ['G', 'C']:
                        engine = "gemini" if choice == 'G' else "codex"
                        config["routing"][cat] = engine
                        break
                    print("      [!] Invalid choice. Enter G or C.")

        elif args.models:
            print("\n[*] Updating Model Routing:")
            mappings = args.models.split(",")
            for m in mappings:
                if ":" in m:
                    cat, engine_code = m.split(":", 1)
                    cat = cat.strip().lower()
                    engine_code = engine_code.strip().upper()
                    engine = "gemini" if engine_code == "G" else "codex"
                    
                    found_any = False
                    for route_key in list(config["routing"].keys()):
                        if cat in route_key:
                            config["routing"][route_key] = engine
                            found_any = True
                    if not found_any:
                        config["routing"][cat] = engine
                    print(f"    - {cat} -> {engine}")

        config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
        print("[+] Updated config.json")
    else:
        print("[!] Warning: config.json not found. Skipping config update.")

    print("\n[!] Setup Complete. You are ready to run Koshary.")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[!] Setup aborted.")
        sys.exit(1)
