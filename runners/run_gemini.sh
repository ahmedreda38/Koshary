#!/usr/bin/env bash
set -euo pipefail

prompt_file="$1"

echo "[runner] pwd: $(pwd)"
echo "[runner] prompt_file: $prompt_file"
echo "[runner] visible files:"
find . -maxdepth 3 -type f | sort

echo
echo "[runner] gemini output begins"
echo

if ! command -v gemini >/dev/null 2>&1; then
  echo "gemini CLI not found in PATH"
  exit 127
fi

# Pass the prompt via stdin using the '-' argument (standard for many CLIs)
# or just pipe it in if the CLI supports it. 
# For gemini-cli, --prompt with '-' usually reads from stdin.
cat "$prompt_file" | gemini --yolo --prompt -
