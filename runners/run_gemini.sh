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

# Use --yolo and --prompt for non-interactive execution
gemini --yolo --prompt "$(cat "$prompt_file")"
