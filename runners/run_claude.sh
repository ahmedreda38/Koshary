#!/usr/bin/env bash
set -euo pipefail

prompt_file="${1:-}"

# Model and reasoning effort can be overridden per run.
PRIMARY_MODEL="${CLAUDE_MODEL:-claude-opus-5-5}"
CLAUDE_EFFORT="${CLAUDE_EFFORT:-high}"

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

run_claude() {
  local model="$1"

  echo >&2
  echo "[runner] Running model=$model" >&2

  # Claude Code in non-interactive print mode; permissions skipped so it can
  # read/write files and run commands inside the scoped challenge workspace.
  timeout "$TIMEOUT_SECONDS" \
    claude -p \
      --model "$model" \
      --effort "$CLAUDE_EFFORT" \
      --dangerously-skip-permissions \
      < "$prompt_file"
}

echo
echo "[runner] claude output begins"
echo

run_claude "$PRIMARY_MODEL"
