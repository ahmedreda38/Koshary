"""
Attachment download + archive extraction with metadata.

Used by both the CTFd and HTB adapters. Extraction tries passwordless first,
then the configured archive password (HTB ships many archives protected with
``hackthebox``). Existing extracted files are never silently overwritten.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Callable, List, Optional

# A fetcher downloads a remote ``url`` to a local ``out_path``.
Fetcher = Callable[[str, Path], None]

ARCHIVE_SUFFIXES = (
    ".zip",
    ".tar",
    ".tar.gz",
    ".tgz",
    ".tar.bz2",
    ".tbz2",
    ".tar.xz",
    ".7z",
    ".gz",
    ".xz",
    ".bz2",
    ".rar",
)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _is_archive(name: str) -> bool:
    low = name.lower()
    return any(low.endswith(suf) for suf in ARCHIVE_SUFFIXES)


def _run(cmd: List[str], cwd: Path, timeout: int = 180) -> bool:
    try:
        proc = subprocess.run(
            cmd, cwd=str(cwd), capture_output=True, text=True, timeout=timeout, check=False
        )
        return proc.returncode == 0
    except Exception:
        return False


def extract_archive(path: Path, dest_dir: Path, password: Optional[str] = None) -> bool:
    """Extract ``path`` into ``dest_dir``. Returns True on success.

    Tries the most appropriate tool by extension and, when ``password`` is
    given, retries once with it.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    low = path.name.lower()

    attempts: List[List[str]] = []
    if low.endswith(".zip"):
        attempts.append(["unzip", "-o", "-qq", str(path), "-d", str(dest_dir)])
        if password:
            attempts.append(["unzip", "-P", password, "-o", "-qq", str(path), "-d", str(dest_dir)])
    elif low.endswith((".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz")):
        attempts.append(["tar", "-xf", str(path), "-C", str(dest_dir)])
    elif low.endswith(".rar"):
        attempts.append(["unrar", "x", "-o+", str(path), str(dest_dir) + "/"])
        if password:
            attempts.append(["unrar", "x", f"-p{password}", "-o+", str(path), str(dest_dir) + "/"])
    else:
        # .7z, .gz, .xz, .bz2 and anything else -> let 7z try.
        attempts.append(["7z", "x", "-y", f"-o{dest_dir}", str(path)])
        if password:
            attempts.append(["7z", "x", "-y", f"-p{password}", f"-o{dest_dir}", str(path)])

    # Always keep 7z as a final fallback (handles most formats).
    attempts.append(["7z", "x", "-y", f"-o{dest_dir}", str(path)])
    if password:
        attempts.append(["7z", "x", "-y", f"-p{password}", f"-o{dest_dir}", str(path)])

    for cmd in attempts:
        if shutil.which(cmd[0]) is None:
            continue
        if _run(cmd, cwd=dest_dir):
            return True
    return False


def prepare_files(
    file_specs: List[dict],
    files_dir: Path,
    fetcher: Optional[Fetcher] = None,
    password: Optional[str] = None,
    auto_extract: bool = True,
) -> List[dict]:
    """Download + (optionally) extract a list of attachments.

    ``file_specs`` items may be either ``{"url": ..., "name": ...}`` for remote
    files, or ``{"path": ...}`` for already-local files. Returns a list of
    metadata dicts and writes ``files_metadata.json`` into ``files_dir``.
    """
    files_dir.mkdir(parents=True, exist_ok=True)
    extracted_root = files_dir.parent / "extracted"
    metadata: List[dict] = []

    for spec in file_specs:
        name = spec.get("name") or (Path(spec["path"]).name if spec.get("path") else None)
        if not name and spec.get("url"):
            from urllib.parse import unquote, urlparse

            name = Path(urlparse(spec["url"]).path).name or "download.bin"
        if not name:
            continue

        out_path = files_dir / name
        try:
            if spec.get("path"):
                src = Path(spec["path"])
                if src.resolve() != out_path.resolve():
                    shutil.copy2(src, out_path)
            elif spec.get("url") and fetcher is not None and not out_path.exists():
                fetcher(spec["url"], out_path)
        except Exception as exc:  # noqa: BLE001 - record and continue
            metadata.append({"filename": name, "error": str(exc)})
            continue

        if not out_path.exists():
            metadata.append({"filename": name, "error": "not downloaded"})
            continue

        entry = {
            "filename": name,
            "sha256": sha256_file(out_path),
            "size": out_path.stat().st_size,
            "downloaded_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "extracted": False,
            "password_used": None,
        }

        if auto_extract and _is_archive(name):
            target = extracted_root / name
            if target.exists():
                backup = target.with_name(target.name + f".bak.{int(time.time())}")
                shutil.move(str(target), str(backup))
            # Try passwordless first, then the configured password.
            if extract_archive(out_path, target, password=None):
                entry["extracted"] = True
            elif password and extract_archive(out_path, target, password=password):
                entry["extracted"] = True
                entry["password_used"] = password

        metadata.append(entry)

    (files_dir / "files_metadata.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )
    return metadata
