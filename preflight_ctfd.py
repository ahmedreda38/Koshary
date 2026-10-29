#!/usr/bin/env python3
"""Check local tools and CTFd access without submitting or changing challenges."""
import argparse
import os
import shutil
import sys
from pathlib import Path
from urllib.parse import urlparse

from orchestrator import load_env, load_json
from platforms.ctfd import CTFdClient


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', help='CTFd event URL; overrides config.json')
    args = parser.parse_args()
    root = Path.cwd()
    load_env(root / '.env')
    config = load_json(root / 'config.json')
    url = args.url or config.get('ctf', {}).get('base_url', '')
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname:
        print('FAIL: supply a valid event URL using --url', file=sys.stderr)
        return 1
    session = os.environ.get('CTFD_SESSION', '').strip()
    if not session:
        print('FAIL: set CTFD_SESSION in .env or the environment', file=sys.stderr)
        return 1
    routes = set(config.get('routing', {}).values())
    missing = sorted(x for x in routes if shutil.which(x) is None)
    if missing:
        print('FAIL: missing runner CLI(s): ' + ', '.join(missing), file=sys.stderr)
        return 1
    print('OK: configured runner CLIs are on PATH')
    try:
        client = CTFdClient(url, session)
        response = client.s.get(f"{client.base_url}/api/v1/users/me", timeout=20, allow_redirects=False)
        response.raise_for_status()
        if response.status_code != 200 or not response.json().get("success"):
            raise ValueError("session not authenticated")
        challenges = client.get_challenges()
        if not client.nonce:
            print('FAIL: CSRF nonce unavailable; flag submission may fail', file=sys.stderr)
            return 1
        print(f'OK: authenticated session and {len(challenges)} listed challenges')
    except Exception as exc:
        print(f'FAIL: CTFd access check failed: {type(exc).__name__}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
