#!/usr/bin/env python3
import argparse
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Clean CTF orchestrator workspace.")
    parser.add_argument("--root", default=".", help="Project root directory")
    parser.add_argument("--keep-config", action="store_true", help="Keep config.json")
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

    if not args.keep_config:
        optional_files.append(root / "config.json")

    if not args.keep_prompts:
        targets.append(root / "prompts")

    if not args.keep_runners:
        targets.append(root / "runners")

    print("[*] Cleanup plan")
    for t in targets + optional_files:
        print(f" - {t}")

    if not args.yes and not args.dry_run:
        reply = input("Proceed? [y/N]: ").strip().lower()
        if reply not in {"y", "yes"}:
            print("[!] Aborted")
            return 1

    for t in targets:
        remove_path(t, dry_run=args.dry_run)

    for f in optional_files:
        remove_path(f, dry_run=args.dry_run)

    print("[ok] Cleanup complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
