#!/usr/bin/env bash
set -euo pipefail

prompt_file="${1:-}"

PRIMARY_MODEL="${CODEX_MODEL:-gpt-6.1-terra}"
PRIMARY_EFFORT="${CODEX_EFFORT:-high}"

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

run_codex() {
  local model="$1"
  local effort="$2"

  echo >&2
  echo "[runner] Running model=$model effort=$effort" >&2

  timeout "$TIMEOUT_SECONDS" \
    codex exec \
      -m "$model" \
      -c "model_reasoning_effort=$effort" \
      -s workspace-write \
      -c approval_policy=never \
      --skip-git-repo-check \
      < "$prompt_file"
}

echo
echo "[runner] codex output begins"
echo

run_codex "$PRIMARY_MODEL" "$PRIMARY_EFFORT"
