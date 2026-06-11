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

# 1. Attempt execution with the high-reasoning Pro model first
echo "[runner] Initializing with gemini-3.1-pro-preview..." >&2
if ! cat "$prompt_file" | gemini --approval-mode=yolo --model gemini-3.1-pro-preview --prompt -; then
  
  # 2. If the command above fails (e.g. 429 Quota Exhausted), catch it and switch to Flash
  echo >&2
  echo "[runner] ⚠️ gemini-3.1-pro-preview failed or quota dead." >&2
  echo "[runner] 🔄 Switching automatically to gemini-3.5-flash..." >&2
  echo >&2
  
  cat "$prompt_file" | gemini --approval-mode=yolo --model gemini-3.5-flash --prompt -
fi
