#!/usr/bin/env bash
set -euo pipefail

prompt_file="$1"

echo "[runner] pwd: $(pwd)"
echo "[runner] prompt_file: $prompt_file"
echo "[runner] visible files:"
find . -maxdepth 3 -type f | sort

echo
echo "[runner] claude output begins"
echo

if ! command -v claude >/dev/null 2>&1; then
  echo "claude CLI not found in PATH"
  exit 127
fi

# Claude Code in non-interactive print mode; permissions skipped so it can
# read/write files and run commands inside the scoped challenge workspace.
cat "$prompt_file" | claude -p --dangerously-skip-permissions
