#!/usr/bin/env bash
set -euo pipefail

prompt_file="${1:-}"

PRIMARY_MODEL="${PRIMARY_MODEL:-gpt-5.5}"
PRIMARY_EFFORT="${PRIMARY_EFFORT:-xhigh}"

FALLBACK_MODEL="${FALLBACK_MODEL:-gpt-5.3-codex}"
FALLBACK_EFFORT="${FALLBACK_EFFORT:-high}"

TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-7200}" # 2 hours

if [[ -z "$prompt_file" || ! -f "$prompt_file" ]]; then
  echo "Usage: $0 <prompt_file>" >&2
  exit 2
fi

if ! command -v codex >/dev/null 2>&1; then
  echo "codex CLI not found in PATH" >&2
  exit 127
fi

echo "[runner] pwd: $(pwd)"
echo "[runner] prompt_file: $prompt_file"
echo "[runner] visible files:"
find . -maxdepth 3 -type f | sort

run_codex() {
  local model="$1"
  local effort="$2"

  echo >&2
  echo "[runner] Running model=$model effort=$effort" >&2

  timeout "$TIMEOUT_SECONDS" \
    codex exec \
      -m "$model" \
      -c "model_reasoning_effort=$effort" \
      --full-auto \
      --skip-git-repo-check \
      < "$prompt_file"
}

echo
echo "[runner] codex output begins"
echo

set +e
run_codex "$PRIMARY_MODEL" "$PRIMARY_EFFORT"
status=$?
set -e

if [[ "$status" -eq 0 ]]; then
  exit 0
fi

echo >&2
echo "[runner] ⚠️ Primary failed, timed out, or quota ended. Exit code: $status" >&2
echo "[runner] 🔄 Switching to fallback: $FALLBACK_MODEL effort=$FALLBACK_EFFORT" >&2
echo >&2

run_codex "$FALLBACK_MODEL" "$FALLBACK_EFFORT"
