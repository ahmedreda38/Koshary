#!/usr/bin/env bash
#
# Koshary HTB CTF auto-runner (cookie/bearer mode).
#
# Repeatedly solves all challenges in the chosen categories for one HTB CTF event.
# Each pass is idempotent: already-solved challenges are skipped, the rest are
# re-attempted. Docker challenges are spawned/torn down automatically.
#
# Credentials come from .env (HTB_CTF_COOKIE / HTB_CTF_BEARER / HTB_CTF_USER_AGENT)
# or a headers file (set HTB_HEADERS_FILE). Never commit those.
#
# Usage:
#   ./run_htb_ctf.sh <CTF_ID> [categories] [parallel] [sleep_seconds]
#
# Examples:
#   ./run_htb_ctf.sh 1434
#   ./run_htb_ctf.sh 1434 "web,crypto,rev"
#   ./run_htb_ctf.sh 1434 "web,crypto,rev,misc,forensics,blockchain,pwn" 3 600
#
# Env overrides:
#   HTB_HEADERS_FILE=htb_headers.txt   # use a headers file instead of .env
#   KOSHARY_EXTRA_ARGS="--walkthrough" # extra orchestrator flags
#
set -uo pipefail

CTF_ID="${1:?usage: ./run_htb_ctf.sh <ctf_id> [categories] [parallel] [sleep_seconds]}"
CATS="${2:-web,crypto,rev,misc,forensics,blockchain,pwn}"
PARALLEL="${3:-3}"
SLEEP_SECONDS="${4:-600}"

cd "$(dirname "$0")"

HEADERS_ARG=()
if [[ -n "${HTB_HEADERS_FILE:-}" ]]; then
  HEADERS_ARG=(--headers-file "$HTB_HEADERS_FILE")
fi

# shellcheck disable=SC2206
EXTRA_ARGS=(${KOSHARY_EXTRA_ARGS:-})

echo "[*] Koshary HTB auto-runner"
echo "    event=$CTF_ID  categories=$CATS  parallel=$PARALLEL  sleep=${SLEEP_SECONDS}s"
echo "    creds: ${HTB_HEADERS_FILE:-.env}"

# Fail fast if access is broken before we start looping.
if ! python3 setup_htb_cookie.py --ctf-id "$CTF_ID" "${HEADERS_ARG[@]}" --check; then
  echo "[!] Access check failed. Fix credentials (401 -> refresh; 403 -> join the event), then retry." >&2
  exit 1
fi

pass=0
while true; do
  pass=$((pass + 1))
  echo
  echo "[*] $(date '+%F %T') — solve pass #$pass for event $CTF_ID"

  python3 orchestrator.py --platform htb_cookie --ctf-id "$CTF_ID" \
          "${HEADERS_ARG[@]}" \
          --categories "$CATS" \
          --parallel "$PARALLEL" \
          --plan --auto-stop --max-wrong 3 \
          "${EXTRA_ARGS[@]}"
  rc=$?

  if [[ $rc -ne 0 ]]; then
    echo "[!] pass #$pass exited $rc (commonly a 401 — refresh creds in ${HTB_HEADERS_FILE:-.env})." >&2
  fi

  echo "[*] pass #$pass done; sleeping ${SLEEP_SECONDS}s before re-attempting unsolved… (Ctrl-C to stop)"
  sleep "$SLEEP_SECONDS"
done
