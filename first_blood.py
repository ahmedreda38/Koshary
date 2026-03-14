#!/usr/bin/env python3
"""
Koshary Framework - First Blood Utility
Targets Sanity Check and Welcome challenges to secure early points.
"""

import os
import re
import sys
import json
from pathlib import Path
from orchestrator import CTFdClient, load_env, load_json, extract_flags, log_info, log_ok, log_warn, log_err, log_step

def main():
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
    log_step(f"Securing First Blood on {base_url}")
    client = CTFdClient(base_url, session)
    
    # 3. Fetch Challenges
    try:
        summaries = client.get_challenges()
    except Exception as e:
        log_err(f"Failed to fetch challenges: {e}")
        return 1

    # 4. Filter for Sanity/Welcome/Rules/Social
    target_keywords = [
        "sanity", "welcome", "rules", "join", "start", "check-in", 
        "discord", "free", "intro", "survey", "social", "twitter", 
        "linkedin", "instagram", "register", "setup", "announcement",
        "feedback", "newsletter", "getting started", "support"
    ]
    sanity_candidates = []
    
    for s in summaries:
        if s.get("solved_by_me"):
            continue
            
        name_lower = s["name"].lower()
        if any(kw in name_lower for kw in target_keywords):
            sanity_candidates.append(s)

    if not sanity_candidates:
        log_warn("No potential sanity check challenges found.")
        return 0

    # 5. Extract Flags and Submit
    flag_patterns = config.get("ctf", {}).get("flag_patterns", [r"flag\{.*\}"])
    
    for candidate in sanity_candidates:
        cid = candidate["id"]
        name = candidate["name"]
        log_info(f"Analyzing candidate: {name} (ID: {cid})")
        
        try:
            detail = client.get_challenge_detail(cid)
            description = detail.get("description", "")
            
            # Check description for flags
            found_flags = extract_flags(description, flag_patterns)
            
            if not found_flags:
                # Sometimes the flag is in the name (less common but happens)
                found_flags = extract_flags(name, flag_patterns)
            
            if found_flags:
                for flag in found_flags:
                    log_step(f"Extracted candidate flag from {name}: {flag}")
                    resp = client.submit_flag(cid, flag)
                    
                    msg_text = json.dumps(resp).lower()
                    if resp.get("success") is True and not any(bad in msg_text for bad in ["incorrect", "wrong"]):
                        log_ok(f"FIRST BLOOD SECURED: {name} solved with {flag}")
                        return 0
                    else:
                        log_warn(f"Submission failed for {flag}: {resp.get('data', {}).get('message', 'Unknown error')}")
            else:
                log_info(f"No direct flag found in description for {name}. Manual check may be required if it's a social media join task.")
                
        except Exception as e:
            log_err(f"Error processing {name}: {e}")

    log_warn("First blood sequence completed. No automatic flags could be submitted.")
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log_warn("Sequence aborted by user.")
        sys.exit(130)
