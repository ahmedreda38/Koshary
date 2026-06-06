# Koshary HTB CTF Solver Integration Plan

## Goal

Add a **Hack The Box CTF solver option** to the existing **Koshary** autonomous CTF solver framework while preserving the current CTFd workflow.

The new mode should support commands like:

```bash
python3 setup_htb.py --event cyber-apocalypse-2026 --interactive

python3 orchestrator.py \
  --platform htb_ctf \
  --categories "web,pwn,crypto,rev,dfir" \
  --parallel 3 \
  --plan \
  --walkthrough \
  --venv ~/CTF-env
```

The old CTFd mode should continue to work:

```bash
python3 setup_ctf.py \
  --url https://utctf.live \
  --session 'session_cookie' \
  --flag 'utflag{}' \
  --interactive

python3 orchestrator.py --platform ctfd --categories "crypto,pwn"
```

The main architectural idea is to turn Koshary into a **multi-platform AI CTF solver**:

```text
Koshary Core
├── CTFd adapter
└── HTB CTF MCP adapter
```

The orchestrator should not care whether challenges come from CTFd or HTB. It should only receive normalized challenge objects, local files, target information, and a `submit_flag()` method.

---

## Final Architecture

```text
Koshary/
├── orchestrator.py
├── setup_ctf.py
├── setup_htb.py
├── clean_workspace.py
├── first_blood.py
│
├── platforms/
│   ├── __init__.py
│   ├── base.py
│   ├── ctfd.py
│   └── htb_ctf_mcp.py
│
├── core/
│   ├── challenge.py
│   ├── workspace.py
│   ├── flag_extractor.py
│   ├── artifact_runner.py
│   ├── model_router.py
│   ├── state_db.py
│   ├── instance_manager.py
│   ├── mcp_client.py
│   └── downloads.py
│
├── prompts/
│   ├── web.md
│   ├── crypto.md
│   ├── pwn.md
│   ├── rev.md
│   ├── forensics.md
│   ├── misc.md
│   ├── fullpwn.md
│   └── htb_system.md
│
├── runners/
│   ├── run_codex.sh
│   ├── run_gemini.sh
│   └── run_claude.sh
│
├── challenges/
├── state/
├── logs/
├── config.json
└── .env
```

---

# Phase 1 — Refactor Koshary into Platform Adapters

Koshary is currently CTFd-centered. The first step is to move all platform-specific logic behind adapters.

The orchestrator should no longer directly know about:

```text
- CTFd URLs
- CTFd cookies
- CTFd challenge endpoints
- CTFd flag submission endpoints
- HTB MCP tool names
- HTB instance-management details
```

Instead, it should talk to a common interface.

---

## Add `platforms/base.py`

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Any


@dataclass
class NormalizedChallenge:
    platform: str
    event_id: str
    challenge_id: str
    name: str
    category: str
    points: Optional[int]
    description: str
    solved: bool = False

    files: list[str] = field(default_factory=list)

    # Generic/HTB target info
    target_kind: str = "static"  # static, docker, fullpwn, unknown
    host: Optional[str] = None
    port: Optional[int] = None
    url: Optional[str] = None
    vpn_required: bool = False

    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class SubmitResult:
    accepted: bool
    message: str
    raw: dict[str, Any] = field(default_factory=dict)


class BasePlatform(ABC):
    name: str

    @abstractmethod
    def list_challenges(self) -> list[NormalizedChallenge]:
        pass

    @abstractmethod
    def get_challenge(self, challenge_id: str) -> NormalizedChallenge:
        pass

    @abstractmethod
    def download_files(self, challenge: NormalizedChallenge, dest_dir: str) -> list[str]:
        pass

    def start_instance(self, challenge: NormalizedChallenge) -> NormalizedChallenge:
        return challenge

    def stop_instance(self, challenge: NormalizedChallenge) -> None:
        return None

    def instance_status(self, challenge: NormalizedChallenge) -> dict:
        return {}

    @abstractmethod
    def submit_flag(self, challenge: NormalizedChallenge, flag: str) -> SubmitResult:
        pass
```

---

## Add `platforms/ctfd.py`

Move existing CTFd-specific functions into this class:

```python
class CTFdPlatform(BasePlatform):
    name = "ctfd"

    def __init__(self, config: dict):
        self.config = config
        self.base_url = config["ctfd"]["url"]
        self.session = config["ctfd"]["session"]

    def list_challenges(self) -> list[NormalizedChallenge]:
        ...

    def get_challenge(self, challenge_id: str) -> NormalizedChallenge:
        ...

    def download_files(self, challenge: NormalizedChallenge, dest_dir: str) -> list[str]:
        ...

    def submit_flag(self, challenge: NormalizedChallenge, flag: str) -> SubmitResult:
        ...
```

The first milestone is simple:

```text
Old CTFd mode must still work exactly as before.
```

---

# Phase 2 — Add HTB CTF MCP Adapter

HTB’s modern CTF integration should be implemented through HTB’s official CTF MCP interface.

Add:

```text
platforms/htb_ctf_mcp.py
core/mcp_client.py
```

---

## HTB Authentication

Store the HTB MCP token in `.env`:

```bash
HTB_MCP_TOKEN="paste_token_here"
```

Never log this token.

Redact it from all logs.

---

## HTB Config

Add this to `config.json`:

```json
{
  "platform": "htb_ctf",
  "htb": {
    "mcp_url": "https://mcp.hackthebox.ai/v1/ctf/mcp/",
    "event": "cyber-apocalypse-2026",
    "auto_join": false,
    "auto_start_instances": true,
    "auto_stop_on_solve": false,
    "max_wrong_submissions_per_challenge": 3,
    "download_password": "hackthebox",
    "allow_nonstandard_flags": false
  }
}
```

---

## Add `core/mcp_client.py`

Create a low-level MCP client with tool discovery.

Do not hardcode exact HTB tool names before discovery.

```python
class MCPClient:
    def __init__(self, url: str, token: str):
        self.url = url
        self.token = token
        self.tools = {}

    def initialize(self):
        """
        Initialize MCP session.
        """
        ...

    def list_tools(self) -> dict:
        """
        Return available MCP tools.
        """
        ...

    def call_tool(self, name: str, arguments: dict) -> dict:
        """
        Call an MCP tool by name.
        """
        ...
```

Responsibilities:

```text
- Connect to HTB MCP Streamable HTTP endpoint
- Send Authorization Bearer header
- Initialize MCP session
- List available tools
- Call tools by name
- Normalize errors
- Redact token from logs
```

---

## Add `platforms/htb_ctf_mcp.py`

```python
class HTBCTFPlatform(BasePlatform):
    name = "htb_ctf"

    def __init__(self, config: dict):
        self.config = config
        self.event = config["htb"]["event"]
        self.client = MCPClient(
            url=config["htb"]["mcp_url"],
            token=os.environ["HTB_MCP_TOKEN"],
        )

    def list_events(self):
        ...

    def get_event(self, event_id):
        ...

    def list_challenges(self) -> list[NormalizedChallenge]:
        ...

    def get_challenge(self, challenge_id: str) -> NormalizedChallenge:
        ...

    def download_files(self, challenge: NormalizedChallenge, dest_dir: str) -> list[str]:
        ...

    def start_instance(self, challenge: NormalizedChallenge) -> NormalizedChallenge:
        ...

    def stop_instance(self, challenge: NormalizedChallenge) -> None:
        ...

    def instance_status(self, challenge: NormalizedChallenge) -> dict:
        ...

    def submit_flag(self, challenge: NormalizedChallenge, flag: str) -> SubmitResult:
        ...

    def get_scoreboard(self):
        ...

    def get_solves(self):
        ...
```

---

# Phase 3 — Add `setup_htb.py`

Create a separate HTB setup helper.

---

## Desired Usage

```bash
python3 setup_htb.py --interactive
```

or:

```bash
python3 setup_htb.py \
  --event cyber-apocalypse-2026 \
  --models 'web:C,crypto:C,pwn:C,rev:C,forensics:G,misc:G,fullpwn:C'
```

---

## What `setup_htb.py` Should Do

```text
1. Load .env
2. Check HTB_MCP_TOKEN exists
3. Connect to HTB MCP
4. List available/running CTF events
5. Let user select event
6. Optionally join/register team if enabled
7. Pull challenge categories
8. Ask routing preferences
9. Update config.json
10. Write htb.event
11. Add HTB flag regexes
```

---

## Add CLI Options

```bash
python3 setup_htb.py --list-events
python3 setup_htb.py --event EVENT --sync-only
python3 setup_htb.py --interactive
python3 setup_htb.py --check-token
```

---

# Phase 4 — Add HTB Challenge State Model

HTB challenges need more state than CTFd challenges because some challenges have spawnable infrastructure.

---

## HTB Workspace Layout

```text
challenges/<event>/<category>/<challenge-slug>/
├── challenge.json
├── target.json
├── instance.json
├── files/
├── plan.md
├── submitted.json
├── notes.md
├── walkthrough.md
└── agent_rounds/
    ├── planning_prompt.txt
    ├── round_01.prompt.txt
    ├── round_01.out.txt
    ├── round_01.commands.txt
    ├── round_01.exec.txt
    └── round_01.artifact.py
```

---

## `challenge.json`

```json
{
  "platform": "htb_ctf",
  "event_id": "cyber-apocalypse-2026",
  "challenge_id": "web-123",
  "name": "Example Web",
  "category": "Web",
  "points": 325,
  "description": "...",
  "solved": false,
  "files": ["files/source.zip"],
  "target_kind": "docker",
  "vpn_required": false,
  "raw": {}
}
```

---

## `target.json`

```json
{
  "kind": "docker",
  "host": "94.237.x.x",
  "port": 31337,
  "url": "http://94.237.x.x:31337",
  "vpn_required": false,
  "started_by_koshary": true
}
```

---

## `instance.json`

```json
{
  "status": "running",
  "started_at": "2026-06-06T00:00:00+03:00",
  "last_checked_at": "2026-06-06T00:05:00+03:00",
  "expires_at": null,
  "raw": {}
}
```

---

# Phase 5 — Add Instance Manager

Create:

```text
core/instance_manager.py
```

---

## Responsibilities

```text
- Check if challenge needs instance
- Start instance through platform adapter
- Wait until target is reachable
- Save host/port/url into target.json
- Refresh status before each solver round
- Stop instance optionally after solve
- Detect VPN-required challenges
```

---

## Logic

```python
def prepare_target(platform, challenge, workspace):
    if challenge.target_kind in ["docker", "fullpwn"]:
        if config["htb"]["auto_start_instances"]:
            challenge = platform.start_instance(challenge)
            workspace.write_target(challenge)
            wait_for_target(challenge)
    return challenge
```

---

## Reachability Checks

For web:

```bash
curl -I --max-time 5 http://HOST:PORT/
```

For pwn:

```bash
nc -vz HOST PORT
```

For Fullpwn:

```bash
ping -c 1 MACHINE_IP
nmap -Pn -sV --top-ports 100 MACHINE_IP
```

---

# Phase 6 — Update Orchestrator CLI

Add these CLI options:

```bash
--platform ctfd|htb_ctf
--event EVENT_ID_OR_SLUG
--no-auto-start
--auto-stop
--no-submit
--manual-submit
--max-wrong N
--sync-only
--list-events
--list-challenges
--scoreboard
--strategy
--allow-nonstandard-flags
```

---

## Example Commands

List HTB events:

```bash
python3 orchestrator.py --platform htb_ctf --list-events
```

Sync only:

```bash
python3 orchestrator.py --platform htb_ctf --event cyber-apocalypse-2026 --sync-only
```

Solve only web:

```bash
python3 orchestrator.py \
  --platform htb_ctf \
  --event cyber-apocalypse-2026 \
  --categories web \
  --parallel 2 \
  --plan \
  --walkthrough
```

Fullpwn only:

```bash
python3 orchestrator.py \
  --platform htb_ctf \
  --categories fullpwn \
  --parallel 1 \
  --plan \
  --walkthrough \
  --venv ~/CTF-env
```

Use `parallel=1` for Fullpwn because VPN and machine solving are noisy and stateful.

---

# Phase 7 — HTB-Aware Prompting

Add:

```text
prompts/htb_system.md
prompts/fullpwn.md
```

---

## `prompts/htb_system.md`

```text
You are solving an authorized Hack The Box CTF challenge.

Scope:
- Only use the provided challenge files.
- Only interact with the official target host, port, URL, or machine IP given in target.json.
- Do not attack unrelated infrastructure.
- Do not perform denial-of-service.
- Keep commands reproducible.
- Prefer writing scripts into the current workspace.
- Report candidate flags clearly.
- If the flag is non-standard, explain why the final answer is likely correct.

Output format:
1. Current hypothesis
2. Commands to run
3. Scripts/files to create
4. Observed evidence
5. Candidate flags
6. Final solve path
```

---

## `prompts/fullpwn.md`

```text
This is an HTB CTF Fullpwn or machine-style challenge.

You may enumerate the provided machine IP only.

Prioritize:
- service discovery
- web enumeration
- credential discovery
- initial foothold
- privilege escalation
- user/root or challenge flag discovery

Always maintain a clear attack path log.
Avoid destructive actions.
```

---

## Add Target Context to Every Prompt

Each solver prompt should include:

```text
Platform: htb_ctf
Event: cyber-apocalypse-2026
Challenge: NAME
Category: Web
Description: ...
Files: ...
Target kind: docker
Target URL: http://HOST:PORT
Host: HOST
Port: PORT
VPN required: false
Workspace: ...
```

---

# Phase 8 — Download and Extraction Handling

Create:

```text
core/downloads.py
```

---

## Behavior

```text
1. Download all attachments into files/
2. Preserve original filenames
3. Hash files and save metadata
4. Auto-extract known archive types
5. Try passwordless first
6. Try password "hackthebox" second
7. Never overwrite existing extracted files without backup
```

---

## Supported Formats

```text
.zip
.tar
.tar.gz
.tgz
.7z
.gz
.xz
.rar optional
```

---

## Metadata Example

```json
{
  "filename": "source.zip",
  "sha256": "...",
  "size": 12345,
  "downloaded_at": "...",
  "extracted": true,
  "password_used": "hackthebox"
}
```

---

# Phase 9 — Flag Extraction and Submission

Improve the existing Koshary flag extraction system for HTB.

---

## `core/flag_extractor.py`

```python
import re

DEFAULT_PATTERNS = [
    r"HTB\{[^}\n\r]{1,300}\}",
    r"CHTB\{[^}\n\r]{1,300}\}",
]

def extract_flags(text: str, patterns: list[str]) -> list[str]:
    found = []
    for pat in patterns:
        found.extend(re.findall(pat, text))
    return list(dict.fromkeys(found))
```

---

## Non-Standard Flags

HTB challenges can sometimes use non-standard answers.

The model should be able to output:

```text
FINAL_ANSWER_CANDIDATE: CVE-2024-1234
CONFIDENCE: high
EVIDENCE: The challenge asks for the CVE and the exploit banner confirms it.
```

Koshary should submit non-regex candidates only when:

```bash
--allow-nonstandard-flags
```

or when this is enabled:

```json
"allow_nonstandard_flags": true
```

---

## Submission Safety

```text
- Never submit the same candidate twice
- Stop after accepted
- Enforce max wrong submissions per challenge
- Store response in submitted.json
- Allow --manual-submit to print instead of submit
- Allow --no-submit to disable platform submission entirely
```

---

## `submitted.json`

```json
{
  "attempts": [
    {
      "flag": "HTB{example}",
      "accepted": false,
      "message": "Incorrect flag",
      "time": "..."
    }
  ],
  "solved": false
}
```

---

# Phase 10 — Scoreboard and Strategy Mode

HTB score and solve statistics can help choose targets.

Add:

```bash
python3 orchestrator.py --platform htb_ctf --strategy
```

---

## Strategy Ranking

Example scoring formula:

```text
priority = points_weight + low_solve_weight + category_preference - failed_attempt_penalty
```

Use factors like:

```text
- current points
- number of solves
- category
- has downloadable files
- has source code
- docker/fullpwn/static
- previous failure count
- model confidence from planning phase
```

---

## Example Output

```text
Recommended queue:
1. Web / easy-looking / 425 pts / low solves / has source
2. Crypto / 375 pts / medium solves / static files only
3. Pwn / 500 pts / low solves / docker target
```

---

# Phase 11 — State Database Changes

Extend `state/db.json`.

```json
{
  "platforms": {
    "ctfd": {},
    "htb_ctf": {
      "events": {
        "cyber-apocalypse-2026": {
          "last_sync": "...",
          "challenges": {
            "web-123": {
              "status": "solved",
              "workspace": "challenges/cyber-apocalypse-2026/web/example-web",
              "instance": {
                "status": "stopped",
                "host": "94.237.x.x",
                "port": 31337
              },
              "submissions": []
            }
          }
        }
      }
    }
  }
}
```

---

# Phase 12 — Locking and Parallel Safety

Keep the current `.lock` behavior, but add HTB-specific locks.

```text
challenge.lock
instance.lock
submit.lock
```

Rules:

```text
- One worker per challenge
- One submitter action per challenge
- One instance start/stop operation at a time
- Fullpwn challenges default to parallel=1
```

---

# Phase 13 — Clean Workspace Updates

Update `clean_workspace.py` to handle HTB state safely.

---

## Required Behavior

```text
clean_workspace.py --yes
  - remove challenges/
  - remove state/
  - remove logs
  - scrub htb.event
  - keep HTB_MCP_TOKEN key but empty value unless --keep-secrets
  - keep config routing
```

---

## Add Options

```bash
python3 clean_workspace.py --platform htb_ctf --yes
python3 clean_workspace.py --keep-htb-token --yes
python3 clean_workspace.py --stop-running-instances --yes
```

The last option should call HTB MCP stop-instance tools before deleting state.

---

# Phase 14 — Logging

Add structured logs:

```text
logs/
├── orchestrator.log
├── htb_mcp.log
├── submissions.log
├── downloads.log
└── instances.log
```

---

## Never Log

```text
HTB_MCP_TOKEN
Authorization headers
session cookies
private URLs if sensitive
```

---

## Redaction Helper

```python
def redact(s: str) -> str:
    secrets = [
        os.getenv("HTB_MCP_TOKEN", ""),
        os.getenv("CTFD_SESSION", ""),
    ]
    for secret in secrets:
        if secret:
            s = s.replace(secret, "[REDACTED]")
    return s
```

---

# Phase 15 — Testing Plan

Create:

```text
tests/
├── test_flag_extractor.py
├── test_workspace.py
├── test_platform_base.py
├── test_ctfd_adapter.py
├── test_htb_adapter_mapping.py
├── test_instance_manager.py
└── test_clean_workspace.py
```

---

## Mock HTB MCP Responses

Do not depend on real HTB during unit tests.

Create fixtures:

```text
tests/fixtures/htb/
├── list_events.json
├── event_details.json
├── list_challenges.json
├── challenge_web.json
├── challenge_pwn.json
├── instance_started.json
├── submit_correct.json
└── submit_wrong.json
```

---

## Test Scenarios

```text
1. HTB token missing -> setup fails cleanly
2. MCP unavailable -> retry then fail cleanly
3. Event selected -> config updated
4. Challenge list normalized
5. Attachment downloaded
6. ZIP extracted with hackthebox password
7. Docker instance started
8. Fullpwn challenge marked vpn_required
9. Duplicate flag not resubmitted
10. Wrong submission limit enforced
11. Accepted flag marks challenge solved
12. Auto-stop runs only if enabled
13. Old CTFd flow still works
14. Secrets are redacted from logs
15. --no-submit prevents platform submission
```

---

# Phase 16 — Minimal MVP Order

Implement this in small milestones.

---

## MVP 1 — Platform Split

Files:

```text
platforms/base.py
platforms/ctfd.py
core/challenge.py
```

Goal:

```text
Old CTFd mode still works exactly the same.
```

Success test:

```bash
python3 orchestrator.py --platform ctfd --categories web --plan
```

---

## MVP 2 — HTB MCP Connection

Files:

```text
core/mcp_client.py
platforms/htb_ctf_mcp.py
setup_htb.py
```

Goal:

```text
Can authenticate, list events, and list challenges.
```

Success test:

```bash
python3 setup_htb.py --list-events
python3 setup_htb.py --event EVENT --sync-only
```

---

## MVP 3 — HTB Workspace Sync

Goal:

```text
Create local challenge workspaces from HTB event.
```

Success output:

```text
challenges/cyber-apocalypse-2026/web/example/
├── challenge.json
├── target.json
└── files/
```

---

## MVP 4 — Downloads

Goal:

```text
Download and extract attachments.
```

Success test:

```bash
python3 orchestrator.py --platform htb_ctf --event EVENT --sync-only --download
```

---

## MVP 5 — Instance Start/Status

Goal:

```text
Start Docker challenge and save host/port.
```

Success test:

```bash
python3 orchestrator.py \
  --platform htb_ctf \
  --event EVENT \
  --categories web \
  --start-only
```

---

## MVP 6 — Solve Loop

Goal:

```text
Codex/Gemini gets HTB challenge data, files, and target info.
```

Success test:

```bash
python3 orchestrator.py \
  --platform htb_ctf \
  --event EVENT \
  --categories web \
  --parallel 1 \
  --plan \
  --no-submit
```

---

## MVP 7 — Flag Submission

Goal:

```text
Submit accepted flags through HTB MCP.
```

Success test:

```bash
python3 orchestrator.py \
  --platform htb_ctf \
  --event EVENT \
  --categories misc \
  --parallel 1 \
  --plan
```

---

## MVP 8 — Scoreboard/Strategy

Goal:

```text
Rank challenges based on score and solves.
```

Success test:

```bash
python3 orchestrator.py --platform htb_ctf --event EVENT --strategy
```

---

# Full Config Example

```json
{
  "platform": "htb_ctf",
  "ctf": {
    "name": "Hack The Box CTF",
    "flag_patterns": [
      "HTB\\{[^}\\n\\r]{1,300}\\}",
      "CHTB\\{[^}\\n\\r]{1,300}\\}"
    ],
    "parallel_workers": 3
  },
  "htb": {
    "mcp_url": "https://mcp.hackthebox.ai/v1/ctf/mcp/",
    "event": "",
    "auto_join": false,
    "auto_start_instances": true,
    "auto_stop_on_solve": false,
    "download_password": "hackthebox",
    "max_wrong_submissions_per_challenge": 3,
    "allow_nonstandard_flags": false
  },
  "routing": {
    "web": "codex",
    "crypto": "codex",
    "pwn": "codex",
    "rev": "codex",
    "forensics": "gemini",
    "dfir": "gemini",
    "misc": "gemini",
    "mobile": "codex",
    "hardware": "codex",
    "blockchain": "codex",
    "fullpwn": "codex"
  },
  "models": {
    "codex": {
      "runner": "runners/run_codex.sh",
      "timeout": 900
    },
    "gemini": {
      "runner": "runners/run_gemini.sh",
      "timeout": 900
    },
    "claude": {
      "runner": "runners/run_claude.sh",
      "timeout": 900
    }
  },
  "workspace": {
    "root": "challenges",
    "state": "state/db.json",
    "logs": "logs"
  }
}
```

---

# Final Codex Implementation Prompt

Use this as the first big prompt to Codex:

```text
We are modifying the Koshary CTF solver framework.

Current project:
- Autonomous CTFd solver framework.
- Main files: orchestrator.py, setup_ctf.py, clean_workspace.py, config.json.
- Existing features: model CLI routing for Gemini/Codex/Claude, category filters, parallel workers, planning mode, artifact execution, walkthrough generation, state tracking, per-challenge workspaces.

Goal:
Add Hack The Box CTF support through HTB’s official CTF MCP server while preserving current CTFd behavior.

Architecture requirements:
1. Introduce platform abstraction:
   - platforms/base.py
   - platforms/ctfd.py
   - platforms/htb_ctf_mcp.py
2. Move current CTFd-specific challenge fetching/submission code into CTFdPlatform.
3. Add NormalizedChallenge and SubmitResult dataclasses.
4. Update orchestrator.py to load platform based on config["platform"] or --platform.
5. Add setup_htb.py.
6. Add low-level core/mcp_client.py for HTB MCP Streamable HTTP.
7. HTB config uses:
   - HTB_MCP_TOKEN from .env
   - htb.mcp_url
   - htb.event
   - htb.auto_start_instances
   - htb.auto_stop_on_solve
8. Add HTB workspace files:
   - challenge.json
   - target.json
   - instance.json
9. Add instance manager:
   - start instance
   - check instance status
   - stop instance
   - save host/port/url
10. Add HTB-aware prompt context:
   - target kind
   - host
   - port
   - url
   - vpn_required
   - files
11. Preserve all existing CTFd commands.
12. Add tests with mocked HTB MCP responses.
13. Never log HTB_MCP_TOKEN or Authorization headers.
14. Add --no-submit and wrong-submission limit.
15. Add support for normal HTB flags HTB{...}, CHTB{...}, and optional non-standard candidates behind a config flag.

Implementation order:
A. Refactor platform base and CTFd adapter.
B. Confirm old CTFd flow still works.
C. Add MCP client skeleton and HTB adapter with tool discovery.
D. Add setup_htb.py list-events/list-challenges.
E. Add workspace sync and downloads.
F. Add instance manager.
G. Add solve loop integration.
H. Add flag submission.
I. Add scoreboard/strategy mode.
J. Add tests and README updates.

Do not remove any existing feature.
Keep backward compatibility.
Commit changes in small logical patches.
```

---

# Best Final Shape

The clean final result should be:

```text
Koshary = multi-platform AI CTF solver

Supported platforms:
1. CTFd
2. HTB CTF via official MCP
```

The core solver should not care where challenges come from. It should only receive:

```text
NormalizedChallenge + files + target info + submit_flag()
```

That is the key abstraction. Once this is done, adding TryHackMe, rCTF, or custom platforms later becomes much easier.

---

# Suggested First Commit Sequence

```text
commit 1: add platform base classes and normalized challenge model
commit 2: move CTFd logic into CTFdPlatform
commit 3: update orchestrator to use platform adapters
commit 4: add MCP client skeleton
commit 5: add HTBCTFPlatform with event/challenge listing
commit 6: add setup_htb.py
commit 7: add HTB workspace sync
commit 8: add downloads/extraction handling
commit 9: add instance manager
commit 10: add HTB prompt context
commit 11: add HTB flag submission
commit 12: add scoreboard/strategy mode
commit 13: add tests and fixtures
commit 14: update README
```

---

# Notes

- Keep CTFd behavior backward-compatible.
- Keep HTB token out of logs.
- Use `--no-submit` by default during early testing.
- Default Fullpwn parallelism should be `1`.
- Use MCP tool discovery instead of assuming exact tool names.
- Treat HTB Docker instances and Fullpwn machines differently.
- Store all platform-specific raw responses under `raw` for debugging.
- Never let Codex directly control platform credentials. The framework should handle platform actions, and the model should only solve challenges inside scoped workspaces.
