# HTB CTF Runbook — Koshary `htb_cookie` mode

Operational runbook for solving a Hack The Box CTF event with Koshary using a
captured browser session (cookie + bearer). This mode drives the HTB CTF web API
(`https://ctf.hackthebox.com/api/...`) and works on events where MCP is disabled
(`mcp_access_mode = no_mcp`).

> Use only on events you have legitimately joined. Credentials replay your live
> HTB session — never commit them. See **Security hygiene** at the bottom.

---

## TL;DR — the 4 commands

```bash
# 1. put HTB_CTF_COOKIE / HTB_CTF_BEARER in .env  (see Step 1)
# 2. configure + verify the event
python3 setup_htb_cookie.py --ctf-id <CTF_ID> --check
# 3. (optional) eyeball the board
python3 orchestrator.py --platform htb_cookie --ctf-id <CTF_ID> --list-challenges
# 4. solve everything in your categories, spawn docker as needed, submit, clean up
python3 orchestrator.py --platform htb_cookie --ctf-id <CTF_ID> \
        --categories web,crypto,rev,misc,forensics,blockchain,pwn \
        --parallel 3 --plan --auto-stop
```

`<CTF_ID>` is the number in the event URL: `https://ctf.hackthebox.com/event/`**`1434`**.

---

## Step 1 — The credentials you need (and how to get them)

HTB's CTF web API authenticates with **two** things on every request, so you need **both**:

| What | Header | Notes |
|---|---|---|
| Session cookies | `Cookie: …` | Copy the **entire** Cookie header value (all cookies — you don't cherry-pick) |
| Access token | `Authorization: Bearer …` | The JWT; paste with or without the `Bearer ` prefix |
| (optional) UA | `User-Agent: …` | Makes the request look identical to your browser |

> Default `auth_mode` is `cookie_bearer` (sends both). `cookie_only` / `bearer_only`
> exist as fallbacks but usually fail — keep the default.

**Capture them (browser, ~30 seconds):**
1. Log into HTB and **join the CTF event** in your browser (challenges 403 until you've joined).
2. Open DevTools → **Network** tab. Reload the event page.
3. Click any request to `ctf.hackthebox.com/api/...` (e.g. `ctfs/<id>`).
4. In **Request Headers**, copy the values of `Cookie`, `Authorization`, and `User-Agent`.

**Give them to Koshary — pick one:**

**Option A — `.env` (simplest, recommended):**
```bash
HTB_CTF_COOKIE='paste the whole Cookie header value here'
HTB_CTF_BEARER='paste the bearer token (Bearer prefix optional)'
HTB_CTF_USER_AGENT='paste your browser UA'    # optional
```

**Option B — a headers file** (`htb_headers.txt`, gitignored). Three lines:
```
Cookie: <full cookie value>
Authorization: Bearer <token>
User-Agent: <ua>
```
Then pass `--headers-file htb_headers.txt` to any command.

**Option C — from a Burp export:**
```bash
python3 tools/import_burp_headers.py -i <burp_export.xml> -o htb_headers.txt
```

All three are redacted from logs and gitignored. **Never commit any of them.**

---

## Step 2 — Configure + verify access

```bash
# Writes platform=htb_cookie + htb_cookie.ctf_id into config.json, adds HTB flag patterns
python3 setup_htb_cookie.py --ctf-id <CTF_ID> --check        # uses .env creds
#   …or with a headers file:
python3 setup_htb_cookie.py --ctf-id <CTF_ID> --headers-file htb_headers.txt --check
```

`--check` calls `GET /api/ctfs/<id>/menu` and must print **`Access OK (userCanViewChallenges = true)`**.
- `401` → cookie/bearer expired → re-capture (Step 1).
- `403` → you haven't joined the event in the browser yet → join, retry.

Set your model routing while you're here (optional):
```bash
python3 setup_htb_cookie.py --ctf-id <CTF_ID> \
        --models 'web:G,crypto:L,pwn:C,rev:L,forensics:G,misc:L,blockchain:L'
#   G = Gemini, C = Codex, L = Claude
```

---

## Step 3 — Recon

```bash
# Full table: id, name, category, kind (static/docker/fullpwn), solved status
python3 orchestrator.py --platform htb_cookie --ctf-id <CTF_ID> --list-challenges

# Ranked "what to do first" queue (points, has-files, solve difficulty)
python3 orchestrator.py --platform htb_cookie --ctf-id <CTF_ID> --strategy

# Scoreboard
python3 orchestrator.py --platform htb_cookie --ctf-id <CTF_ID> --scoreboard
```

---

## Step 4 — Download challenge files

Downloads happen automatically during a solve, but you can pre-stage everything:

```bash
# Download + extract every downloadable challenge, no solving
python3 orchestrator.py --platform htb_cookie --ctf-id <CTF_ID> --download --sync-only
```

Per challenge it: requests a fresh signed URL → downloads → sha256 → tries
extraction (passwordless, then `hackthebox`). Files land in:

```
challenges/htb_cookie/<CTF_ID>/<category>/<id>_<slug>/
├── challenge.json      target.json      submitted.json
├── files/  (+ files_metadata.json)
├── extracted/
├── plan.md             walkthrough.md   (if --walkthrough)
└── agent_rounds/       (every prompt/output/exec per round)
```

---

## Step 5 — Spawn a Docker instance

Auto-spawn is **on by default** for `docker` challenges during a solve. To do it manually:

```bash
# Spawn one challenge's container, poll until ready, write target.json, then exit
python3 orchestrator.py --platform htb_cookie --ctf-id <CTF_ID> --challenge-id <ID> --start-only

# Tear it down
python3 orchestrator.py --platform htb_cookie --ctf-id <CTF_ID> --challenge-id <ID> --stop-instance
```

`target.json` gets the live `host` / `port` / `url` (e.g. `http://154.57.x.x:31070`).
HTB usually **auto-removes the container when you solve**, so an explicit stop may
`403` — that's harmless.

> **Fullpwn** machines are gated off (`auto_start_fullpwn: false`) because they need
> your HTB VPN connected. Enable per-event in `config.json` only if you're on the VPN.

---

## Step 6 — Solve + submit (graduated control)

```bash
# Dry run — solve but NEVER submit (see candidate flags first)
python3 orchestrator.py --platform htb_cookie --ctf-id <CTF_ID> --categories web --plan --no-submit

# One specific challenge, full auto (download/spawn/solve/submit)
python3 orchestrator.py --platform htb_cookie --ctf-id <CTF_ID> --challenge-id <ID> --plan

# A whole category, submitting live
python3 orchestrator.py --platform htb_cookie --ctf-id <CTF_ID> --categories crypto --plan

# Submit a flag you found yourself
python3 orchestrator.py --platform htb_cookie --ctf-id <CTF_ID> --challenge-id <ID> --submit-candidate 'HTB{...}'
```

Submission safety is built in: every attempt is logged to `submitted.json`, the
same flag is never sent twice, `--max-wrong N` (default **3**) caps wrong tries per
challenge, and placeholder flags like `HTB{...}` are auto-dropped.

---

## Step 7 — Automate the whole CTF

**One command does end-to-end** across categories, in parallel, spawning docker as
needed, submitting, and cleaning up instances:

```bash
python3 orchestrator.py --platform htb_cookie --ctf-id <CTF_ID> \
        --categories web,crypto,rev,misc,forensics,blockchain,pwn \
        --parallel 3 --plan --auto-stop --max-wrong 3
```

It's **idempotent** — re-running skips anything already solved (local state + the
server's `solved` flag) and only re-attempts the rest. So "automation" = re-run it
on a loop. Use the bundled wrapper:

```bash
chmod +x run_htb_ctf.sh
./run_htb_ctf.sh <CTF_ID>
#   optional: override categories
./run_htb_ctf.sh <CTF_ID> "web,crypto,rev"
```

If you'd rather drive it from inside Claude Code, the `/loop` skill does the same:
```
/loop 15m python3 orchestrator.py --platform htb_cookie --ctf-id <CTF_ID> --categories web,crypto,rev,misc --plan --auto-stop
```

Add `--walkthrough` to any solve run to auto-generate `walkthrough.md` writeups per
solved challenge.

---

## Category → model routing (`config.json` → `routing`)

| Categories | Model CLI | Needs installed |
|---|---|---|
| web, forensics, mobile | **gemini** | `gemini` |
| crypto, rev/reverse, misc, blockchain | **claude** | `claude` |
| pwn, binary, fullpwn, machine, hardware | **codex** | `codex` |

Unrouted categories (e.g. ICS, Coding) show `UNSUPPORTED` and are skipped — add them
to `routing` in `config.json` to include them.

## Key safety knobs

| Flag / config | Effect |
|---|---|
| `--no-submit` | Detect flags, never submit (recon/testing) |
| `--manual-submit` | Print candidates, don't submit |
| `--max-wrong N` | Cap wrong submissions per challenge (`0` = unlimited) |
| `--auto-stop` / `auto_stop_on_solve` | Stop the container after a solve |
| `--no-auto-start` / `auto_start_instances:false` | Don't spawn docker automatically |
| `--parallel N` | Concurrent workers (fullpwn forces serial) |
| `--timeout S` | Per-round model timeout (default 300s; 8 rounds max) |

## `config.json` → `htb_cookie` block

| Key | Meaning |
|---|---|
| `base_url` | `https://ctf.hackthebox.com` |
| `ctf_id` | Numeric event id (e.g. `1434`) |
| `auth_mode` | `cookie_bearer` (default), `cookie_only`, or `bearer_only` |
| `auto_start_instances` | Auto-spawn Docker containers (default `true`) |
| `auto_start_fullpwn` | Auto-spawn Fullpwn machines (default `false`; VPN-bound) |
| `auto_stop_on_solve` | Stop the container after a solve (default `false`) |
| `download_password` | Archive password tried after passwordless (`hackthebox`) |
| `max_wrong_submissions_per_challenge` | Wrong-submission cap (default `3`) |
| `poll_seconds` / `poll_interval` | Container-ready polling window |
| `headers_file` | Optional path to a headers file (else rely on `.env`) |

## Troubleshooting

| Symptom | Fix |
|---|---|
| `401 Unauthorized` | Bearer/cookie expired (JWTs are short-lived) — re-capture and update `.env`/headers file. Expect to refresh every few hours in a long CTF. |
| `403 Forbidden` on challenges | You haven't **joined** the event in the browser, or the session lost access |
| Download fails / link expired | Signed URLs are ~5 min; Koshary always re-requests one immediately, so just re-run |
| Container "not reachable" | Re-run; `poll_seconds`/`poll_interval` control the wait. Web targets need an HTTP path |
| Stop returns `403` | Container already auto-removed on solve — benign |

## Security hygiene

- `.env`, `htb_headers.txt`, `*.headers`, `burp_*.xml`, `htb_requests` are
  **gitignored** — keep it that way. Cookie/bearer/signed-URLs are redacted from logs.
- Your session = your account. **Rotate it after the CTF** (HTB logout / re-login) so
  a captured token stops working.
- Use only on events you have legitimately joined.

---

## Quick reference — all relevant CLI

```bash
# Setup
python3 setup_htb_cookie.py --ctf-id <ID> [--headers-file F] [--check|--list|--interactive] [--models 'web:G,...']

# Burp -> headers file
python3 tools/import_burp_headers.py -i <burp.xml> -o htb_headers.txt

# Dev client (no model gate)
python3 -m core.htb_cookie_client --ctf-id <ID> [--headers-file F] {check|list|scores}

# Orchestrator
python3 orchestrator.py --platform htb_cookie --ctf-id <ID> [options]
#   recon:    --list-challenges | --strategy | --scoreboard
#   files:    --download --sync-only
#   instance: --challenge-id <ID> --start-only | --stop-instance
#   solve:    --categories a,b,c --parallel N --plan [--walkthrough]
#   submit:   (auto) | --no-submit | --manual-submit | --challenge-id <ID> --submit-candidate 'HTB{...}'
#   safety:   --max-wrong N --auto-stop --no-auto-start --timeout S
```
