#!/usr/bin/env bash
set -euo pipefail

prompt_file="$1"

echo "[runner] pwd: $(pwd)"
echo "[runner] prompt_file: $prompt_file"
echo "[runner] visible files:"
find . -maxdepth 3 -type f | sort

echo
echo "[runner] codex output begins"
echo

if ! command -v codex >/dev/null 2>&1; then
  echo "codex CLI not found in PATH"
  exit 127
fi

# Use --full-auto and --skip-git-repo-check for non-interactive execution
codex exec --full-auto --skip-git-repo-check "$(cat "$prompt_file")"
