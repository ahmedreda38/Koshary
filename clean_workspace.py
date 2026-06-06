#!/usr/bin/env python3
import argparse
import json
import os
import shutil
import sys
from pathlib import Path


def remove_path(path: Path, dry_run: bool = False) -> None:
    if not path.exists():
        print(f"[skip] not found: {path}")
        return

    if dry_run:
        print(f"[dry-run] would remove: {path}")
        return

    if path.is_dir():
        shutil.rmtree(path)
        print(f"[ok] removed directory: {path}")
    else:
        path.unlink()
        print(f"[ok] removed file: {path}")


def scrub_config(path: Path, dry_run: bool = False) -> None:
    if not path.exists():
        print(f"[skip] config not found: {path}")
        return

    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[warn] could not parse config for scrubbing: {path} ({exc})")
        return

    ctf_cfg = config.setdefault("ctf", {})
    ctf_cfg["name"] = ""
    ctf_cfg["base_url"] = ""
    ctf_cfg["flag_patterns"] = []
    ctf_cfg["include_categories"] = []
    ctf_cfg["exclude_categories"] = []

    # Scrub HTB event selection but keep routing + HTB connection settings.
    htb_cfg = config.get("htb")
    if isinstance(htb_cfg, dict):
        htb_cfg["event"] = ""

    if dry_run:
        print(f"[dry-run] would scrub config fields in: {path}")
        return

    path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    print(f"[ok] scrubbed config values: {path}")


def scrub_env(path: Path, dry_run: bool = False, keep_htb_token: bool = False,
              keep_session: bool = False) -> None:
    if not path.exists():
        print(f"[skip] env not found: {path}")
        return

    # Empty the value but KEEP the key for these secrets.
    scrub_keys = []
    if not keep_session:
        scrub_keys.append("CTFD_SESSION")
    if not keep_htb_token:
        scrub_keys.append("HTB_MCP_TOKEN")

    lines = path.read_text(encoding="utf-8").splitlines()
    seen = set()
    output = []
    for line in lines:
        handled = False
        for key in scrub_keys:
            if line.startswith(f"{key}="):
                output.append(f"{key}=")
                seen.add(key)
                handled = True
                break
        if not handled:
            output.append(line)

    # Ensure scrubbed keys exist even if they weren't present before.
    for key in scrub_keys:
        if key not in seen:
            output.append(f"{key}=")

    new_text = "\n".join(output).rstrip() + "\n"

    if dry_run:
        print(f"[dry-run] would scrub secrets ({', '.join(scrub_keys) or 'none'}) in: {path}")
        return

    path.write_text(new_text, encoding="utf-8")
    print(f"[ok] scrubbed environment secrets ({', '.join(scrub_keys) or 'none'}): {path}")


def stop_running_instances(root: Path, dry_run: bool = False) -> None:
    """Best-effort: ask the HTB platform to stop any instances tracked in state."""
    state_path = root / "state" / "db.json"
    config_path = root / "config.json"
    if not state_path.exists() or not config_path.exists():
        print("[skip] no state/config to inspect for running instances")
        return
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[warn] could not read state/config: {exc}")
        return

    running = []
    for cid, info in state.get("challenges", {}).items():
        if info.get("platform") == "htb_ctf" and info.get("target_kind") in ("docker", "fullpwn"):
            running.append((cid, info))
    if not running:
        print("[skip] no HTB instances tracked in state")
        return

    if dry_run:
        print(f"[dry-run] would stop {len(running)} HTB instance(s)")
        return

    # Load .env so HTB_MCP_TOKEN is available.
    env_path = root / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("HTB_MCP_TOKEN=") and "=" in line:
                os.environ.setdefault("HTB_MCP_TOKEN", line.split("=", 1)[1].strip().strip("'\""))

    try:
        from platforms.htb_ctf_mcp import HTBCTFPlatform
        from platforms.base import NormalizedChallenge

        platform = HTBCTFPlatform(config)
        for cid, info in running:
            try:
                chall = NormalizedChallenge(
                    platform="htb_ctf", event_id=info.get("event_id", ""),
                    challenge_id=str(cid), name=info.get("name", ""),
                    category=info.get("category", ""), points=info.get("value"),
                    description="", target_kind=info.get("target_kind", "docker"),
                )
                platform.stop_instance(chall)
                print(f"[ok] stop requested for instance {cid}")
            except Exception as exc:
                print(f"[warn] could not stop instance {cid}: {exc}")
    except Exception as exc:
        print(f"[warn] HTB platform unavailable for instance teardown: {exc}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Clean CTF orchestrator workspace.")
    parser.add_argument("--root", default=".", help="Project root directory")
    parser.add_argument("--platform", choices=["ctfd", "htb_ctf"], help="Limit scrubbing hints to a platform")
    parser.add_argument("--keep-config", action="store_true", help="Keep config.json and .env contents unchanged")
    parser.add_argument("--keep-prompts", action="store_true", help="Keep prompts/")
    parser.add_argument("--keep-runners", action="store_true", help="Keep runners/")
    parser.add_argument("--keep-secrets", action="store_true", help="Keep all secret values in .env")
    parser.add_argument("--keep-htb-token", action="store_true", help="Keep HTB_MCP_TOKEN value in .env")
    parser.add_argument("--stop-running-instances", action="store_true", help="Stop tracked HTB instances before deleting state")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be removed")
    parser.add_argument("--yes", action="store_true", help="Do not ask for confirmation")
    args = parser.parse_args()

    root = Path(args.root).resolve()

    targets = [
        root / "challenges",
        root / "state",
        root / "logs",
        root / ".pytest_cache",
        root / "__pycache__",
    ]

    optional_files = [
        root / "orchestrator.log",
    ]
    config_path = root / "config.json"
    env_path = root / ".env"

    if not args.keep_prompts:
        targets.append(root / "prompts")

    if not args.keep_runners:
        targets.append(root / "runners")

    keep_htb_token = args.keep_htb_token or args.keep_secrets
    keep_session = args.keep_secrets

    print("[*] Cleanup plan")
    for t in targets + optional_files:
        print(f" - {t}")
    if args.stop_running_instances:
        print(" - stop running HTB instances (via MCP) before deleting state")
    if args.keep_config:
        print(f" - keep config/env contents: {config_path}, {env_path}")
    else:
        print(f" - scrub config values (incl. htb.event): {config_path}")
        kept = []
        if keep_htb_token:
            kept.append("HTB_MCP_TOKEN")
        if keep_session:
            kept.append("CTFD_SESSION")
        print(f" - scrub secrets in {env_path}" + (f" (keeping {', '.join(kept)})" if kept else ""))

    if not args.yes and not args.dry_run:
        reply = input("Proceed? [y/N]: ").strip().lower()
        if reply not in {"y", "yes"}:
            print("[!] Aborted")
            return 1

    if args.stop_running_instances:
        stop_running_instances(root, dry_run=args.dry_run)

    for t in targets:
        remove_path(t, dry_run=args.dry_run)

    for f in optional_files:
        remove_path(f, dry_run=args.dry_run)

    if not args.keep_config:
        scrub_config(config_path, dry_run=args.dry_run)
        scrub_env(env_path, dry_run=args.dry_run, keep_htb_token=keep_htb_token, keep_session=keep_session)

    print("[ok] Cleanup complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
