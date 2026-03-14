#!/usr/bin/env python3
import argparse
import json
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

    if dry_run:
        print(f"[dry-run] would scrub config fields in: {path}")
        return

    path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    print(f"[ok] scrubbed config values: {path}")


def scrub_env(path: Path, dry_run: bool = False) -> None:
    if not path.exists():
        print(f"[skip] env not found: {path}")
        return

    lines = path.read_text(encoding="utf-8").splitlines()
    replaced = False
    output = []

    for line in lines:
        if line.startswith("CTFD_SESSION="):
            output.append("CTFD_SESSION=")
            replaced = True
        else:
            output.append(line)

    if not replaced:
        output.append("CTFD_SESSION=")

    new_text = "\n".join(output).rstrip() + "\n"

    if dry_run:
        print(f"[dry-run] would scrub secrets in: {path}")
        return

    path.write_text(new_text, encoding="utf-8")
    print(f"[ok] scrubbed environment secrets: {path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Clean CTF orchestrator workspace.")
    parser.add_argument("--root", default=".", help="Project root directory")
    parser.add_argument("--keep-config", action="store_true", help="Keep config.json and .env contents unchanged")
    parser.add_argument("--keep-prompts", action="store_true", help="Keep prompts/")
    parser.add_argument("--keep-runners", action="store_true", help="Keep runners/")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be removed")
    parser.add_argument("--yes", action="store_true", help="Do not ask for confirmation")
    args = parser.parse_args()

    root = Path(args.root).resolve()

    targets = [
        root / "challenges",
        root / "state",
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

    print("[*] Cleanup plan")
    for t in targets + optional_files:
        print(f" - {t}")
    if args.keep_config:
        print(f" - keep config/env contents: {config_path}, {env_path}")
    else:
        print(f" - scrub config values: {config_path}")
        print(f" - scrub session token: {env_path}")

    if not args.yes and not args.dry_run:
        reply = input("Proceed? [y/N]: ").strip().lower()
        if reply not in {"y", "yes"}:
            print("[!] Aborted")
            return 1

    for t in targets:
        remove_path(t, dry_run=args.dry_run)

    for f in optional_files:
        remove_path(f, dry_run=args.dry_run)

    if not args.keep_config:
        scrub_config(config_path, dry_run=args.dry_run)
        scrub_env(env_path, dry_run=args.dry_run)

    print("[ok] Cleanup complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
