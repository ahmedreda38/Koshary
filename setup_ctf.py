#!/usr/bin/env python3
"""
Koshary Framework - CTF Setup Utility
Automates the configuration of .env and config.json for new competitions.
"""

import json
import argparse
import os
import re
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description="Koshary CTF Setup Utility")
    parser.add_argument("--url", required=True, help="Base URL of the CTFd instance (e.g., https://ctf.example.com)")
    parser.add_argument("--session", required=True, help="CTFd session cookie value")
    parser.add_argument("--flag", required=True, help="Flag format (e.g., 'MyCTF{}')")
    args = parser.parse_args()

    root = Path(".").resolve()
    config_path = root / "config.json"
    env_path = root / ".env"

    # 1. Process Inputs
    url = args.url.rstrip("/")
    
    # Extract name from URL for config
    ctf_name = url.split("//")[-1].split(".")[0].replace("-", " ").title()
    
    # Clean session string (handle 'session=...' format)
    session = args.session
    if session.startswith("session="):
        session = session[len("session="):]

    # Convert MyCTF{} format to regex MyCTF\{[^\\s]+\}
    flag_format = args.flag
    if "{}" in flag_format:
        flag_regex = flag_format.replace("{", "\\{").replace("}", "[^\\s]+\\}")
    else:
        flag_regex = flag_format

    print(f"[*] Setting up for: {ctf_name}")
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
        
        # Prepend new flag format if not already there
        if flag_regex not in config["ctf"]["flag_patterns"]:
            config["ctf"]["flag_patterns"].insert(0, flag_regex)
            
        config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
        print("[+] Updated config.json")
    else:
        print("[!] Warning: config.json not found. Skipping config update.")

    print("\n[!] Setup Complete. You are ready to run first_blood.py or orchestrator.py")

if __name__ == "__main__":
    main()
