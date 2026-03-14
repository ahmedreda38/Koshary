#!/usr/bin/env python3
"""
Koshary Framework - First Blood Utility (Continuous Mode)
Continuously polls the CTFd API until the competition starts, then 
automatically secures early flags and submits any provided override flag.
"""

import os
import re
import sys
import json
import time
import argparse
from pathlib import Path
from orchestrator import CTFdClient, load_env, load_json, extract_flags, log_info, log_ok, log_warn, log_err, log_step

def main():
    parser = argparse.ArgumentParser(description="Koshary First Blood Utility")
    parser.add_argument("--flag", help="Override flag to submit to all discovered sanity challenges")
    parser.add_argument("--interval", type=int, default=10, help="Polling interval in seconds (default: 10)")
    parser.add_argument("--brute-first", type=int, default=10, help="Number of initial IDs to attempt with override flag (default: 10)")
    args = parser.parse_args()

    root = Path(".").resolve()
    
    # 1. Load Environment & Config
    load_env(root / ".env")
    config = load_json(root / "config.json")
    
    session = os.getenv("CTFD_SESSION", "").strip()
    if not session:
        log_err("Authentication failure: Missing CTFD_SESSION in .env")
        return 1
        
    base_url = config.get("ctf", {}).get("base_url")
    if not base_url:
        log_err("Configuration error: Missing base_url in config.json")
        return 1

    # 2. Initialize Client
    log_step(f"Monitoring {base_url} for First Blood...")
    if args.flag:
        log_info(f"Targeting start with override flag: {args.flag}")
    
    client = CTFdClient(base_url, session)
    
    target_keywords = [
        "sanity", "welcome", "rules", "join", "start", "check-in", 
        "discord", "free", "intro", "survey", "social", "twitter", 
        "linkedin", "instagram", "register", "setup", "announcement",
        "feedback", "newsletter", "getting started", "support"
    ]
    
    flag_patterns = config.get("ctf", {}).get("flag_patterns", [r"flag\{.*\}"])
    solved_ids = set()

    # 3. Continuous Polling Loop
    try:
        while True:
            try:
                summaries = client.get_challenges()
                if summaries:
                    log_ok(f"CTF is ACTIVE! Discovered {len(summaries)} challenges.")
                    
                    # Sort challenges by ID to identify the first few
                    summaries.sort(key=lambda x: x["id"])
                    
                    # --- PASS 1: Targeted Keyword Match ---
                    for s in summaries:
                        cid = s["id"]
                        name = s["name"]
                        if s.get("solved_by_me") or cid in solved_ids:
                            continue
                            
                        name_lower = name.lower()
                        if any(kw in name_lower for kw in target_keywords):
                            log_step(f"Targeting potential sanity: {name} (ID: {cid})")
                            
                            if args.flag:
                                log_info(f"Submitting override flag to {name}...")
                                resp = client.submit_flag(cid, args.flag)
                                msg_text = json.dumps(resp).lower()
                                if resp.get("success") is True and not any(bad in msg_text for bad in ["incorrect", "wrong"]):
                                    log_ok(f"SUCCESS: {name} solved with override flag!")
                                    solved_ids.add(cid)
                                    continue

                            # Auto-extraction
                            detail = client.get_challenge_detail(cid)
                            description = detail.get("description", "")
                            found_flags = extract_flags(description, flag_patterns)
                            if not found_flags: found_flags = extract_flags(name, flag_patterns)
                                
                            if found_flags:
                                for flag in found_flags:
                                    log_info(f"Submitting extracted flag: {flag}")
                                    resp = client.submit_flag(cid, flag)
                                    msg_text = json.dumps(resp).lower()
                                    if resp.get("success") is True and not any(bad in msg_text for bad in ["incorrect", "wrong"]):
                                        log_ok(f"SUCCESS: {name} solved with extracted flag!")
                                        solved_ids.add(cid)
                                        break

                    # --- PASS 2: First N IDs Fallback (if override flag provided) ---
                    if args.flag:
                        log_info(f"Attempting override flag on first {args.brute_first} challenge IDs as fallback...")
                        for i in range(min(len(summaries), args.brute_first)):
                            s = summaries[i]
                            cid = s["id"]
                            if s.get("solved_by_me") or cid in solved_ids:
                                continue
                            
                            log_info(f"Fallback attempt on ID {cid} ({s['name']})...")
                            resp = client.submit_flag(cid, args.flag)
                            msg_text = json.dumps(resp).lower()
                            if resp.get("success") is True and not any(bad in msg_text for bad in ["incorrect", "wrong"]):
                                log_ok(f"FALLBACK SUCCESS: {s['name']} (ID: {cid}) solved!")
                                solved_ids.add(cid)

                else:
                    log_info("CTF not started yet. Waiting for challenges...")

            except Exception as e:
                if "403" in str(e) or "404" in str(e):
                    log_info("API access restricted. CTF likely has not started...")
                else:
                    log_err(f"Polling error: {e}")
            
            time.sleep(args.interval)
            
    except KeyboardInterrupt:
        log_warn("\nMonitoring stopped by user.")
        return 0

if __name__ == "__main__":
    sys.exit(main())
