#!/usr/bin/env bash
set -euo pipefail

prompt_file="${1:-}"

# Primary = strongest model; fallback is used if the primary errors out,
# times out, or hits a usage limit. Override any of these from the environment.
# Accepts aliases (opus/sonnet/haiku) or full model IDs (e.g. claude-opus-4-8).
PRIMARY_MODEL="${PRIMARY_MODEL:-opus}"
FALLBACK_MODEL="${FALLBACK_MODEL:-sonnet}"

TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-7200}" # 2 hours

if [[ -z "$prompt_file" || ! -f "$prompt_file" ]]; then
  echo "Usage: $0 <prompt_file>" >&2
  exit 2
fi

if ! command -v claude >/dev/null 2>&1; then
  echo "claude CLI not found in PATH" >&2
  exit 127
fi

echo "[runner] pwd: $(pwd)"
echo "[runner] prompt_file: $prompt_file"
echo "[runner] visible files:"
find . -maxdepth 3 -type f | sort

run_claude() {
  local model="$1"

  echo >&2
  echo "[runner] Running model=$model" >&2

  # Claude Code in non-interactive print mode; permissions skipped so it can
  # read/write files and run commands inside the scoped challenge workspace.
  timeout "$TIMEOUT_SECONDS" \
    claude -p \
      --model "$model" \
      --dangerously-skip-permissions \
      < "$prompt_file"
}

echo
echo "[runner] claude output begins"
echo

set +e
run_claude "$PRIMARY_MODEL"
status=$?
set -e

if [[ "$status" -eq 0 ]]; then
  exit 0
fi

echo >&2
echo "[runner] ⚠️ Primary failed, timed out, or quota ended. Exit code: $status" >&2
echo "[runner] 🔄 Switching to fallback: $FALLBACK_MODEL" >&2
echo >&2

run_claude "$FALLBACK_MODEL"
