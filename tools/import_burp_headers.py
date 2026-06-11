#!/usr/bin/env python3
"""
Convert a Burp Suite XML export (or a raw HTTP request) into a minimal
``htb_headers.txt`` holding only the headers Koshary's htb_cookie client needs:
``Cookie``, ``Authorization``, and ``User-Agent``.

This NEVER prints the secret values — only which headers were found. The output
file is written with 0600 permissions and is gitignored by default.

Usage:
    python3 tools/import_burp_headers.py                       # reads htb_requests -> htb_headers.txt
    python3 tools/import_burp_headers.py -i capture.xml -o htb_headers.txt
    python3 tools/import_burp_headers.py --host ctf.hackthebox.com
"""

from __future__ import annotations

import argparse
import base64
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

WANTED = ("cookie", "authorization", "user-agent")


def _headers_from_raw_request(raw: str) -> dict[str, str]:
    """Pull the wanted headers out of a raw HTTP request blob."""
    out: dict[str, str] = {}
    # Headers end at the first blank line.
    head = raw.split("\r\n\r\n", 1)[0].split("\n\n", 1)[0]
    for line in head.splitlines():
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        k = key.strip().lower()
        if k in WANTED and val.strip():
            out.setdefault(k, val.strip())
    return out


def _iter_burp_requests(xml_path: Path):
    """Yield (host, decoded_request_text) for each item in a Burp export."""
    tree = ET.parse(xml_path)
    for item in tree.getroot().findall("item"):
        host_el = item.find("host")
        req_el = item.find("request")
        if req_el is None:
            continue
        host = (host_el.text or "") if host_el is not None else ""
        raw = req_el.text or ""
        if (req_el.get("base64") or "").lower() == "true":
            try:
                raw = base64.b64decode(raw).decode("utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                continue
        yield host, raw


def extract_headers(input_path: Path, host_filter: str) -> dict[str, str]:
    text = input_path.read_text(encoding="utf-8", errors="replace")
    # Burp XML export?
    if text.lstrip().startswith("<?xml") or "<items" in text[:200]:
        best: dict[str, str] = {}
        for host, raw in _iter_burp_requests(input_path):
            if host_filter and host_filter.lower() not in host.lower():
                continue
            headers = _headers_from_raw_request(raw)
            # Prefer the request that carries an Authorization header.
            if "authorization" in headers:
                return headers
            if headers and not best:
                best = headers
        return best
    # Otherwise treat the whole file as a single raw request.
    return _headers_from_raw_request(text)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Import HTB headers from a Burp export")
    parser.add_argument("-i", "--input", default="htb_requests", help="Burp XML or raw request file")
    parser.add_argument("-o", "--out", default="htb_headers.txt", help="Output headers file")
    parser.add_argument("--host", default="ctf.hackthebox.com", help="Only use requests to this host")
    args = parser.parse_args(argv)

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"[!] Input not found: {input_path}")
        return 1

    headers = extract_headers(input_path, args.host)
    if not headers or ("cookie" not in headers and "authorization" not in headers):
        print("[!] No Cookie/Authorization headers found in the capture.")
        return 2

    out_path = Path(args.out)
    lines = []
    for key in ("Cookie", "Authorization", "User-Agent"):
        val = headers.get(key.lower())
        if val:
            lines.append(f"{key}: {val}")
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        os.chmod(out_path, 0o600)
    except OSError:
        pass

    # Only report which headers were captured — never their values.
    found = ", ".join(k for k in ("cookie", "authorization", "user-agent") if k in headers)
    print(f"[+] Wrote {out_path} (0600) with: {found}")
    print("[i] This file holds live session secrets — it is gitignored. Never commit it.")
    print(f"\nNext:\n    python3 setup_htb_cookie.py --ctf-id <ID> --headers-file {out_path} --check")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
