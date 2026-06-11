# Koshary HTB Cookie-Based Solver Implementation Plan

## Purpose

This plan describes how to implement the next Koshary version that supports **Hack The Box CTF solving using browser-captured HTB session cookies and bearer tokens**, similar to the existing CTFd cookie/session workflow.

This version is different from the earlier MCP-based plan. This one uses the same backend API endpoints observed from the joined CTF in the captured Burp traffic.

The implementation should be added as a new platform adapter:

```text
platforms/htb_cookie.py
```

The final supported platforms should become:

```text
Koshary
├── CTFd adapter
├── HTB MCP adapter, optional/future
└── HTB cookie/bearer adapter
```

---

## Source Files Used for This Plan

The implementation agent should use these local files as references:

```text
/mnt/data/htb_requests
/mnt/data/htb_cookie_crawling_notes.md
/mnt/data/htb_cookie_client.py
```

### 1. `htb_requests`

This is the Burp XML export captured from an authenticated HTB CTF session.

It is the source of truth for the real browser API behavior.

Important facts from this file:

```text
Host: ctf.hackthebox.com
Observed CTF event id: 1434
Observed API requests: 37
API base path: /api/...
Auth style: Cookie + Authorization: Bearer ...
```

The capture included these relevant API paths:

```text
GET  /api/public/challenge-categories
GET  /api/ctfs/1434
GET  /api/ctfs/1434/menu
GET  /api/challenges/31856/download/link
POST /api/challenges/containers/start
POST /api/challenges/containers/stop
POST /api/flags/own
GET  /api/challenges/{challenge_id}/solves
GET  /api/ctfs/solves/1434
GET  /api/ctfs/scores/1434
GET  /api/ctfs/score-charts/1434
GET  /api/challenges/{challenge_id}/associations
GET  /api/chat/1434/messages?page=1
GET  /api/notifications/unread-count
```

### 2. `htb_cookie_crawling_notes.md`

This file summarizes the captured flow in human-readable form.

It contains:

```text
- key finding: HTB API uses Cookie + Authorization Bearer
- event ID observed: 1434
- challenge category endpoint
- event/challenge crawl endpoint
- download flow
- container start flow
- container stop flow
- flag submission flow
- scoreboard/solves endpoints
- recommended adapter name and config
```

### 3. `htb_cookie_client.py`

This file is a working reference client that should be refactored into Koshary.

It already implements:

```text
- parsing Cookie / Authorization / User-Agent from a raw request file
- GET /api/public/challenge-categories
- GET /api/ctfs/{ctf_id}
- GET /api/ctfs/{ctf_id}/menu
- challenge normalization into HTBChallenge
- GET /api/challenges/{challenge_id}/download/link
- challenge file download using the signed URL
- POST /api/challenges/containers/start
- POST /api/challenges/containers/stop
- POST /api/flags/own
- GET /api/ctfs/scores/{ctf_id}
- GET /api/ctfs/solves/{ctf_id}
- GET /api/challenges/{challenge_id}/solves
```

The implementation agent should **not blindly copy it into the final codebase**. Instead, it should split it into:

```text
core/htb_cookie_client.py
platforms/htb_cookie.py
setup_htb_cookie.py
```

---

# High-Level Goal

Add this workflow:

```bash
python3 setup_htb_cookie.py \
  --ctf-id 1434 \
  --headers-file htb_headers.txt \
  --interactive

python3 orchestrator.py \
  --platform htb_cookie \
  --ctf-id 1434 \
  --categories "web,pwn,crypto,rev,forensics,misc" \
  --parallel 3 \
  --plan \
  --walkthrough
```

Also support environment variables:

```bash
export HTB_CTF_COOKIE='full Cookie header value'
export HTB_CTF_BEARER='Bearer token value without "Bearer "'
export HTB_CTF_USER_AGENT='browser user agent'
```

Then:

```bash
python3 orchestrator.py \
  --platform htb_cookie \
  --ctf-id 1434 \
  --categories web \
  --parallel 2
```

---

# Important Authentication Finding

The captured HTB API traffic is not pure cookie-only.

Every relevant HTB API request in the Burp capture used:

```http
Cookie: ...
Authorization: Bearer ...
```

Therefore, the adapter should support three auth modes:

```text
1. cookie_bearer  recommended
2. cookie_only    fallback, may fail
3. bearer_only    fallback, may fail
```

The safest default is:

```text
cookie_bearer
```

The implementation should never print or commit either value.

---

# Required Headers

Based on the captured requests, the agent should preserve these headers where useful:

```http
Accept: application/json
User-Agent: <browser user agent>
Cookie: <captured cookie header>
Authorization: Bearer <captured bearer token>
Referer: https://ctf.hackthebox.com/event/{ctf_id}
Origin: https://ctf.hackthebox.com
Content-Type: application/json
```

For GET JSON requests:

```http
Accept: application/json
Cookie: ...
Authorization: Bearer ...
Referer: https://ctf.hackthebox.com/event/{ctf_id}
```

For POST JSON requests:

```http
Accept: application/json
Content-Type: application/json
Origin: https://ctf.hackthebox.com
Referer: https://ctf.hackthebox.com/event/{ctf_id}
Cookie: ...
Authorization: Bearer ...
```

Avoid copying non-essential browser telemetry headers unless needed:

```text
Baggage
Sentry-Trace
Priority
Sec-Fetch-*
Te
```

They appeared in the browser capture but are not part of the core API contract.

---

# HTB API Endpoint Map

## 1. Categories

### Request

```http
GET /api/public/challenge-categories
Host: ctf.hackthebox.com
Accept: application/json
Cookie: ...
Authorization: Bearer ...
```

### Full URL

```text
https://ctf.hackthebox.com/api/public/challenge-categories
```

### Observed Response Shape

```json
[
  {
    "id": 1,
    "name": "Fullpwn"
  },
  {
    "id": 2,
    "name": "Web"
  }
]
```

### Purpose

This maps challenge category IDs from the event response to names.

The event response includes:

```text
challenge_category_id
```

So Koshary should do:

```python
category_name = categories[challenge["challenge_category_id"]]
```

---

## 2. Main Event and Challenge List

### Request

```http
GET /api/ctfs/{ctf_id}
Host: ctf.hackthebox.com
Accept: application/json
Cookie: ...
Authorization: Bearer ...
```

### Example

```http
GET /api/ctfs/1434
```

### Full URL

```text
https://ctf.hackthebox.com/api/ctfs/{ctf_id}
```

### Observed Top-Level Response Fields

```text
id
name
org_name
workshop
team_size
starts_at
ends_at
status
logo
hide_scoreboard
participating_team
hasVPN
hasPwnbox
light_mode
mcp_access_mode
ai_usage_policy
challenges
```

### Observed Challenge Fields

```text
id
name
creator
description
challenge_category_id
difficulty
filename
hasDocker
docker_online
docker_ports
docker_instance_type
points
solves
hostname
new
hasMachine
isProlab
flagsInfo
machine
status
solved
team_solves
```

### Purpose

This is the main crawl endpoint. It provides:

```text
- CTF metadata
- challenge list
- challenge descriptions
- category IDs
- points
- solve counts
- whether a downloadable file exists
- whether Docker exists
- whether Docker is online
- hostname and ports after container start
- solved state
```

---

## 3. Event Menu / Permission Check

### Request

```http
GET /api/ctfs/{ctf_id}/menu
```

### Example

```http
GET /api/ctfs/1434/menu
```

### Observed Response Fields

```text
id
name
ends_at
hasVpn
hasPwnbox
userIsHost
userCanViewAnalytics
userCanViewChallenges
userCanViewScoreboard
participatingTeamVpnServer
isBusiness
isUni
status
```

### Purpose

Use this during setup/auth validation.

If:

```text
userCanViewChallenges != true
```

then Koshary should stop and tell the user that the session is not authorized for the CTF event.

---

## 4. Download Link

### Request

```http
GET /api/challenges/{challenge_id}/download/link
```

### Example

```http
GET /api/challenges/31856/download/link
```

### Observed Response

```json
{
  "url": "http://ctf.hackthebox.com/challenges/31856/download?expires=...&signature=..."
}
```

### Purpose

This endpoint returns a temporary signed download URL.

Important behavior:

```text
- only call it for challenges where filename is non-empty
- the signed URL expires
- download immediately
- save original filename if available
```

### Download Flow

```text
1. GET /api/ctfs/{ctf_id}
2. Find challenges where filename is not null/empty
3. GET /api/challenges/{challenge_id}/download/link
4. Extract response["url"]
5. GET signed URL
6. Save file to workspace
7. Hash file
8. Extract archives if possible
```

### Suggested Workspace Path

```text
challenges/<ctf_id>/<category>/<challenge_id>_<slug>/files/<filename>
```

---

## 5. Start Docker Container

### Request

```http
POST /api/challenges/containers/start
Content-Type: application/json

{
  "id": 31856
}
```

### Observed Response

```json
{
  "message": "Container starting."
}
```

### Important Behavior

The start response does not include host/port.

To get the target, Koshary must poll:

```http
GET /api/ctfs/{ctf_id}
```

until the matching challenge shows:

```text
docker_online = true / 1
hostname is not empty
docker_ports is not empty
```

### Polling Logic

```python
def start_instance(challenge_id):
    POST /api/challenges/containers/start {"id": challenge_id}

    deadline = now + 60 seconds

    while now < deadline:
        event = GET /api/ctfs/{ctf_id}
        challenge = find challenge by id

        if challenge["docker_online"] and challenge["hostname"] and challenge["docker_ports"]:
            return target_info

        sleep(2)

    raise TimeoutError("Container did not become ready")
```

### Target URL Construction

If:

```json
{
  "hostname": "154.57.x.x",
  "docker_ports": [30502],
  "docker_instance_type": "web"
}
```

Then:

```text
host = 154.57.x.x
port = 30502
url = http://154.57.x.x:30502
```

For TCP/pwn:

```text
host = 154.57.x.x
port = 30502
connect = nc 154.57.x.x 30502
```

---

## 6. Stop Docker Container

### Request

```http
POST /api/challenges/containers/stop
Content-Type: application/json

{
  "id": 40742
}
```

### Observed Response

```json
{
  "message": "Container stopping."
}
```

### Purpose

Call this when:

```text
- --auto-stop-on-solve is enabled
- clean_workspace.py --stop-running-instances is used
- user manually runs stop command
```

---

## 7. Submit Flag

### Request

```http
POST /api/flags/own
Content-Type: application/json

{
  "challenge_id": 40742,
  "flag": "HTB{...}"
}
```

### Observed Wrong Response

```json
{
  "message": "Wrong flag, sorry!"
}
```

### Observed Wrong Status

```text
HTTP 400
```

### Acceptance Logic

Treat as wrong if:

```text
HTTP 400
message contains "Wrong flag"
```

Treat as accepted if:

```text
HTTP 200 or HTTP 201
and message does not contain "wrong"
```

Store raw response in `submitted.json`.

### Submission Safety Rules

```text
- Do not submit without --submit or unless config enables auto-submit
- Never submit the same candidate twice
- Respect max_wrong_submissions_per_challenge
- Stop immediately on accepted flag
- Store every attempt
- Allow --manual-submit mode to print candidates only
```

---

## 8. Challenge Solves

### Request

```http
GET /api/challenges/{challenge_id}/solves
```

### Example

```http
GET /api/challenges/31856/solves
```

### Purpose

Use for:

```text
- challenge popularity
- strategy mode
- solve statistics
- “easy first” queue ordering
```

---

## 9. CTF Solves

### Request

```http
GET /api/ctfs/solves/{ctf_id}
```

### Example

```http
GET /api/ctfs/solves/1434
```

### Purpose

Use for:

```text
- live solve feed
- current event activity
- strategy mode
```

---

## 10. Scoreboard

### Request

```http
GET /api/ctfs/scores/{ctf_id}
```

### Example

```http
GET /api/ctfs/scores/1434
```

### Purpose

Use for:

```text
- scoreboard display
- team ranking
- progress reporting
```

---

## 11. Score Charts

### Request

```http
GET /api/ctfs/score-charts/{ctf_id}
```

### Example

```http
GET /api/ctfs/score-charts/1434
```

### Purpose

Use for:

```text
- score-over-time display
- optional analytics
```

---

## 12. Associations

### Request

```http
GET /api/challenges/{challenge_id}/associations
```

### Purpose

Optional.

The capture includes many association requests. Do not make this required for MVP unless it contains useful attachments, hints, related services, assigned users, or team-specific metadata.

Implement later as:

```python
def get_associations(challenge_id): ...
```

---

## 13. Chat and Notifications

Observed but not required for solver MVP:

```text
GET /api/chat/{ctf_id}/messages?page=1
GET /api/notifications/unread-count
```

Do not use these for automated solving unless a future feature explicitly needs CTF chat context.

---

# New Platform: `htb_cookie`

## New Files

Add:

```text
core/htb_cookie_client.py
platforms/htb_cookie.py
setup_htb_cookie.py
prompts/htb_cookie_system.md
tests/test_htb_cookie_client.py
tests/test_htb_cookie_platform.py
tests/fixtures/htb_cookie/
```

Optional:

```text
tools/import_burp_headers.py
```

---

## `core/htb_cookie_client.py`

This should be the cleaned-up reusable version of `htb_cookie_client.py`.

Responsibilities:

```text
- store base URL
- store ctf_id
- manage requests.Session
- parse Cookie / Authorization / User-Agent from env or headers file
- apply correct Referer/Origin headers
- perform JSON GET/POST requests
- detect 401/403 auth failure
- expose endpoint methods
- never print secrets
```

Main methods:

```python
class HTBCookieClient:
    def __init__(
        self,
        ctf_id: int,
        cookie: str | None,
        bearer: str | None,
        user_agent: str | None,
        base_url: str = "https://ctf.hackthebox.com",
        timeout: int = 30,
    ):
        ...

    @classmethod
    def from_env_or_headers_file(cls, ctf_id: int, headers_file: str | None = None):
        ...

    def get_categories(self) -> dict[int, str]:
        ...

    def get_event(self) -> dict:
        ...

    def get_menu(self) -> dict:
        ...

    def list_challenges_raw(self) -> list[dict]:
        ...

    def get_challenge_raw(self, challenge_id: int) -> dict:
        ...

    def get_download_link(self, challenge_id: int) -> str | None:
        ...

    def download_challenge(self, challenge_id: int, out_dir: Path) -> Path | None:
        ...

    def start_container(self, challenge_id: int) -> dict:
        ...

    def stop_container(self, challenge_id: int) -> dict:
        ...

    def submit_flag(self, challenge_id: int, flag: str) -> dict:
        ...

    def get_challenge_solves(self, challenge_id: int) -> dict | list:
        ...

    def get_ctf_solves(self) -> dict | list:
        ...

    def get_scores(self) -> dict | list:
        ...

    def get_score_charts(self) -> dict | list:
        ...
```

---

## `platforms/htb_cookie.py`

This is the Koshary platform adapter.

It should implement the same interface as the existing CTFd platform.

```python
class HTBCookiePlatform(BasePlatform):
    name = "htb_cookie"

    def __init__(self, config: dict):
        self.config = config
        self.ctf_id = config["htb_cookie"]["ctf_id"]
        self.client = HTBCookieClient.from_env_or_headers_file(
            ctf_id=self.ctf_id,
            headers_file=config["htb_cookie"].get("headers_file"),
            base_url=config["htb_cookie"].get("base_url", "https://ctf.hackthebox.com"),
        )

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
```

---

# Normalized Challenge Mapping

Map HTB raw challenge fields into Koshary’s normalized challenge object.

## Input: Raw HTB Challenge

```json
{
  "id": 31856,
  "name": "Example",
  "description": "...",
  "challenge_category_id": 2,
  "difficulty": "Easy",
  "filename": "source.zip",
  "hasDocker": true,
  "docker_online": false,
  "docker_ports": [],
  "docker_instance_type": "web",
  "points": 325,
  "solves": 12,
  "hostname": null,
  "hasMachine": false,
  "machine": null,
  "solved": false
}
```

## Output: `NormalizedChallenge`

```python
NormalizedChallenge(
    platform="htb_cookie",
    event_id=str(ctf_id),
    challenge_id=str(raw["id"]),
    name=raw["name"],
    category=category_name,
    points=raw["points"],
    description=raw["description"],
    solved=bool(raw["solved"]),
    files=[raw["filename"]] if raw["filename"] else [],
    target_kind="docker_web",
    host=raw["hostname"],
    port=raw["docker_ports"][0] if raw["docker_ports"] else None,
    url="http://host:port" if ready and web else None,
    vpn_required=bool(raw.get("hasMachine")),
    raw=raw,
)
```

---

## Target Kind Rules

Use these mapping rules:

```text
if hasMachine or machine:
    target_kind = "fullpwn"
    vpn_required = true

elif hasDocker and docker_instance_type == "web":
    target_kind = "docker_web"

elif hasDocker:
    target_kind = "docker_tcp"

elif filename:
    target_kind = "static"

else:
    target_kind = "unknown"
```

## Target URL Rules

For Docker web:

```python
url = f"http://{hostname}:{docker_ports[0]}"
```

For Docker TCP/Pwn:

```python
host = hostname
port = docker_ports[0]
url = None
```

For Fullpwn:

```python
host = machine.ip or raw machine value if present
vpn_required = True
```

---

# Setup Script: `setup_htb_cookie.py`

## Purpose

Make setup as easy as the CTFd version.

## Commands

```bash
python3 setup_htb_cookie.py --ctf-id 1434 --headers-file htb_headers.txt --interactive
python3 setup_htb_cookie.py --ctf-id 1434 --headers-file htb_headers.txt --check
python3 setup_htb_cookie.py --ctf-id 1434 --headers-file htb_headers.txt --list
```

## Setup Flow

```text
1. Load .env
2. Parse --headers-file if provided
3. Extract:
   - Cookie
   - Authorization Bearer
   - User-Agent
4. Validate auth:
   - GET /api/ctfs/{ctf_id}/menu
   - confirm userCanViewChallenges is true
5. Fetch event:
   - GET /api/ctfs/{ctf_id}
6. Fetch categories:
   - GET /api/public/challenge-categories
7. Show event name/status/challenge count
8. Ask routing preferences
9. Write config.json
10. Write local auth guidance without dumping secrets
```

## Config Output

```json
{
  "platform": "htb_cookie",
  "htb_cookie": {
    "base_url": "https://ctf.hackthebox.com",
    "ctf_id": 1434,
    "headers_file": "htb_headers.txt",
    "auth_mode": "cookie_bearer",
    "auto_start_instances": true,
    "auto_stop_on_solve": false,
    "download_password": "hackthebox",
    "max_wrong_submissions_per_challenge": 3,
    "allow_nonstandard_flags": false,
    "poll_seconds": 60,
    "poll_interval": 2
  }
}
```

## `.env` Output Option

Instead of storing a headers file path, the setup script may suggest:

```bash
HTB_CTF_COOKIE='...'
HTB_CTF_BEARER='...'
HTB_CTF_USER_AGENT='...'
```

But the script must not print the actual values after parsing.

---

# Workspace Layout

Use this layout for HTB cookie mode:

```text
challenges/
└── htb_cookie/
    └── 1434/
        └── web/
            └── 31856_example_challenge/
                ├── challenge.json
                ├── target.json
                ├── instance.json
                ├── files/
                ├── extracted/
                ├── plan.md
                ├── notes.md
                ├── submitted.json
                ├── walkthrough.md
                └── agent_rounds/
                    ├── round_01.prompt.txt
                    ├── round_01.out.txt
                    ├── round_01.commands.txt
                    └── round_01.exec.txt
```

---

## `challenge.json`

```json
{
  "platform": "htb_cookie",
  "event_id": "1434",
  "challenge_id": "31856",
  "name": "Example Challenge",
  "category": "Web",
  "difficulty": "Easy",
  "points": 325,
  "solves": 12,
  "description": "...",
  "solved": false,
  "files": ["files/source.zip"],
  "target_kind": "docker_web",
  "raw": {}
}
```

---

## `target.json`

```json
{
  "target_kind": "docker_web",
  "host": "154.57.x.x",
  "port": 30502,
  "url": "http://154.57.x.x:30502",
  "vpn_required": false,
  "ready": true,
  "source": "GET /api/ctfs/1434 after POST start"
}
```

---

## `instance.json`

```json
{
  "status": "running",
  "docker_online": true,
  "started_by_koshary": true,
  "started_at": "2026-06-06T00:00:00+03:00",
  "last_checked_at": "2026-06-06T00:00:10+03:00",
  "stop_endpoint": "/api/challenges/containers/stop",
  "raw": {}
}
```

---

## `submitted.json`

```json
{
  "solved": false,
  "attempts": [
    {
      "flag": "HTB{example}",
      "accepted": false,
      "http_status": 400,
      "message": "Wrong flag, sorry!",
      "submitted_at": "2026-06-06T00:00:00+03:00",
      "raw": {
        "message": "Wrong flag, sorry!"
      }
    }
  ]
}
```

---

# Orchestrator Integration

Update `orchestrator.py` to support:

```bash
--platform htb_cookie
--ctf-id 1434
--headers-file htb_headers.txt
--sync-only
--download
--start-only
--stop-on-solve
--no-submit
--manual-submit
--strategy
```

## Main Flow

```text
1. Load config
2. Load HTBCookiePlatform
3. Validate session through /api/ctfs/{ctf_id}/menu
4. Fetch categories
5. Fetch event and challenges
6. Normalize challenges
7. Filter by category / solved / include-solved
8. Create workspaces
9. Download files if filename exists
10. Extract archives if configured
11. Start instance if hasDocker and auto_start_instances
12. Build prompt with challenge + files + target
13. Run agent
14. Extract candidate flags
15. Submit if enabled
16. Mark solved if accepted
17. Stop container if configured
18. Write walkthrough
```

---

# Download and Extraction Handling

## Required Logic

```text
1. Challenge has filename
2. GET /api/challenges/{id}/download/link
3. Extract signed URL
4. GET signed URL
5. Save to files/
6. Hash file with sha256
7. Write files/metadata.json
8. Try extraction:
   - no password
   - password hackthebox
9. Save extracted files to extracted/
```

## Metadata

```json
{
  "original_filename": "source.zip",
  "saved_path": "files/source.zip",
  "sha256": "...",
  "size": 12345,
  "download_url_source": "/api/challenges/31856/download/link",
  "downloaded_at": "...",
  "extracted": true,
  "password_used": "hackthebox"
}
```

---

# Instance Management

## When to Start

Start an instance if:

```text
challenge.target_kind in ["docker_web", "docker_tcp"]
and config["htb_cookie"]["auto_start_instances"] is true
```

Do not auto-start Fullpwn unless explicitly configured because Fullpwn may require VPN/machine access and is more stateful.

## Start Method

```text
POST /api/challenges/containers/start
Body: {"id": challenge_id}
```

Then poll:

```text
GET /api/ctfs/{ctf_id}
```

until:

```text
docker_online == true
hostname exists
docker_ports length > 0
```

## Stop Method

```text
POST /api/challenges/containers/stop
Body: {"id": challenge_id}
```

## Reachability Check

After target is ready from API, optionally check reachability:

For web:

```bash
curl -I --max-time 5 http://HOST:PORT/
```

For pwn/tcp:

```bash
nc -vz HOST PORT
```

Do not fail the whole challenge if this check fails once. Retry a few times.

---

# Flag Extraction and Submission

## Flag Patterns

Default:

```python
[
    r"HTB\{[^}\n\r]{1,300}\}",
    r"CHTB\{[^}\n\r]{1,300}\}"
]
```

Also support model-declared non-standard candidates:

```text
FINAL_ANSWER_CANDIDATE: ...
CONFIDENCE: high
EVIDENCE: ...
```

Only submit non-standard candidates if enabled:

```bash
--allow-nonstandard-flags
```

## Submit Method

```text
POST /api/flags/own
Body:
{
  "challenge_id": 40742,
  "flag": "HTB{...}"
}
```

## Wrong Response

```json
{
  "message": "Wrong flag, sorry!"
}
```

## Acceptance Rules

```python
def is_accepted(status_code, data):
    message = str(data.get("message", "")).lower()

    if status_code == 400:
        return False

    if "wrong flag" in message:
        return False

    if "wrong" in message:
        return False

    return status_code in [200, 201]
```

---

# Strategy Mode

Add:

```bash
python3 orchestrator.py --platform htb_cookie --ctf-id 1434 --strategy
```

Use:

```text
GET /api/ctfs/{ctf_id}
GET /api/ctfs/scores/{ctf_id}
GET /api/ctfs/solves/{ctf_id}
GET /api/challenges/{challenge_id}/solves
```

Rank by:

```text
- unsolved only
- high points
- lower solve count
- has downloadable source
- category preference
- target kind
- previous failure count
- static challenges first if fast mode
```

Example ranking:

```text
1. Web / 325 pts / 12 solves / has source / docker web
2. Crypto / 300 pts / 25 solves / static
3. Pwn / 475 pts / 5 solves / docker tcp
```

---

# Prompting for AI Agents

Add:

```text
prompts/htb_cookie_system.md
```

## Prompt Template

```text
You are solving an authorized Hack The Box CTF challenge through Koshary.

Scope:
- Only use the files in the current challenge workspace.
- Only interact with the target host/port/url listed in target.json.
- Do not attack unrelated infrastructure.
- Do not perform denial of service.
- Keep commands reproducible.
- Prefer writing scripts into the workspace.
- Clearly report candidate flags.

Platform:
- htb_cookie

CTF ID:
- {ctf_id}

Challenge:
- ID: {challenge_id}
- Name: {name}
- Category: {category}
- Difficulty: {difficulty}
- Points: {points}
- Solves: {solves}
- Solved: {solved}

Description:
{description}

Files:
{files}

Target:
- Kind: {target_kind}
- Host: {host}
- Port: {port}
- URL: {url}
- VPN required: {vpn_required}

Workspace:
{workspace}

Output format:
1. Hypothesis
2. Commands to run
3. Scripts to create
4. Observations
5. Candidate flags
6. Final solve path
```

---

# Safety and Secret Handling

## Never Commit

```text
HTB_CTF_COOKIE
HTB_CTF_BEARER
raw headers files
download signed URLs
```

## Add to `.gitignore`

```gitignore
.env
*.headers
htb_headers.txt
burp_*.xml
state/secrets.json
```

## Redaction Helper

```python
def redact(text: str) -> str:
    secrets = [
        os.getenv("HTB_CTF_COOKIE", ""),
        os.getenv("HTB_CTF_BEARER", ""),
    ]

    for secret in secrets:
        if secret:
            text = text.replace(secret, "[REDACTED]")

    return text
```

Also redact:

```text
Authorization: Bearer ...
Cookie: ...
download?expires=...&signature=...
```

---

# Testing Plan

## Fixtures

Create:

```text
tests/fixtures/htb_cookie/
├── categories.json
├── event_1434.json
├── menu_1434.json
├── download_link_31856.json
├── container_start.json
├── container_stop.json
├── flag_wrong.json
├── flag_correct.json
├── scores_1434.json
├── solves_1434.json
└── challenge_solves_31856.json
```

## Unit Tests

```text
tests/test_htb_cookie_client.py
tests/test_htb_cookie_platform.py
tests/test_htb_cookie_setup.py
tests/test_htb_cookie_submission.py
tests/test_htb_cookie_instance_manager.py
```

## Required Test Cases

```text
1. Parse Cookie, Authorization, User-Agent from raw request file
2. Missing auth fails with clear error
3. GET /api/ctfs/{ctf_id}/menu validates access
4. Categories map correctly
5. Challenge list normalizes correctly
6. Static challenge target_kind = static
7. Docker web challenge target_kind = docker_web
8. Docker tcp challenge target_kind = docker_tcp
9. Fullpwn challenge target_kind = fullpwn
10. Download link is requested only when filename exists
11. Signed URL download saves file
12. Container start polls until target is ready
13. Container stop sends correct JSON body
14. Wrong flag is not marked accepted
15. Correct flag is marked accepted
16. Duplicate flag is not resubmitted
17. max_wrong_submissions_per_challenge is enforced
18. Secrets are redacted from logs
19. --no-submit prevents POST /api/flags/own
20. Old CTFd mode still works
```

---

# Implementation Roadmap

## Phase 0 — Preserve Current Koshary

Before modifying:

```bash
git checkout -b htb-cookie-platform
python3 orchestrator.py --platform ctfd --help
```

Run current tests if available.

Do not break CTFd.

---

## Phase 1 — Add Core HTB Cookie Client

Create:

```text
core/htb_cookie_client.py
```

Refactor from:

```text
/mnt/data/htb_cookie_client.py
```

Keep client code independent from Koshary platform interface.

Success command:

```bash
python3 -m core.htb_cookie_client --ctf-id 1434 --headers-file htb_headers.txt list
```

Or create a dev CLI:

```bash
python3 tools/htb_cookie_client.py --ctf-id 1434 --headers-file htb_headers.txt list
```

---

## Phase 2 — Add Platform Adapter

Create:

```text
platforms/htb_cookie.py
```

It should convert raw HTB challenge objects to Koshary `NormalizedChallenge`.

Success command:

```bash
python3 orchestrator.py --platform htb_cookie --ctf-id 1434 --sync-only
```

Expected result:

```text
challenges/htb_cookie/1434/<category>/<id>_<slug>/challenge.json
```

---

## Phase 3 — Add Setup Script

Create:

```text
setup_htb_cookie.py
```

Success commands:

```bash
python3 setup_htb_cookie.py --ctf-id 1434 --headers-file htb_headers.txt --check
python3 setup_htb_cookie.py --ctf-id 1434 --headers-file htb_headers.txt --interactive
```

It should write/update:

```text
config.json
```

without storing raw secrets unless the user explicitly chooses a local headers file path.

---

## Phase 4 — Download Support

Implement:

```text
download_files()
```

Flow:

```text
GET /api/challenges/{id}/download/link
GET signed URL
save file
hash file
extract file
```

Success command:

```bash
python3 orchestrator.py --platform htb_cookie --ctf-id 1434 --download --sync-only
```

---

## Phase 5 — Container Start/Stop

Implement:

```text
start_instance()
stop_instance()
instance_status()
```

Success command:

```bash
python3 orchestrator.py --platform htb_cookie --ctf-id 1434 --start-only --challenge-id 31856
```

Expected `target.json`:

```json
{
  "host": "154.57.x.x",
  "port": 30502,
  "url": "http://154.57.x.x:30502",
  "ready": true
}
```

---

## Phase 6 — Solve Loop Integration

The orchestrator should pass:

```text
challenge.json
target.json
files/
extracted/
prompt context
```

to the selected model runner.

Success command:

```bash
python3 orchestrator.py \
  --platform htb_cookie \
  --ctf-id 1434 \
  --categories web \
  --parallel 1 \
  --plan \
  --no-submit
```

---

## Phase 7 — Submission

Implement:

```text
submit_flag()
```

Endpoint:

```text
POST /api/flags/own
```

Success command:

```bash
python3 orchestrator.py \
  --platform htb_cookie \
  --ctf-id 1434 \
  --challenge-id 40742 \
  --submit-candidate 'HTB{...}'
```

During automated solving, submission should happen only if config allows it.

---

## Phase 8 — Strategy and Scoreboard

Implement:

```bash
python3 orchestrator.py --platform htb_cookie --ctf-id 1434 --scoreboard
python3 orchestrator.py --platform htb_cookie --ctf-id 1434 --strategy
```

Use:

```text
GET /api/ctfs/scores/{ctf_id}
GET /api/ctfs/score-charts/{ctf_id}
GET /api/ctfs/solves/{ctf_id}
```

---

## Phase 9 — Documentation

Update README with:

```text
HTB cookie mode
Auth setup
Endpoints used
Security notes
Usage examples
Troubleshooting 401/403
```

Include:

```text
This mode uses a browser-authenticated HTB session. Use only for CTF events you are authorized to access.
```

---

# Agent Implementation Prompt

Use this prompt for Codex or another coding agent.

```text
We are developing the next Koshary version with HTB CTF cookie/bearer support.

Reference files:
- /mnt/data/htb_requests
- /mnt/data/htb_cookie_crawling_notes.md
- /mnt/data/htb_cookie_client.py

Goal:
Add a new Koshary platform adapter named htb_cookie that uses the browser API endpoints observed in the Burp capture from ctf.hackthebox.com.

Important auth finding:
The captured API requests use both:
- Cookie: ...
- Authorization: Bearer ...

Implement support for Cookie + Bearer auth. Do not log or commit secrets.

Observed base URL:
https://ctf.hackthebox.com

Observed event id:
1434

Required endpoints:
1. GET /api/public/challenge-categories
2. GET /api/ctfs/{ctf_id}
3. GET /api/ctfs/{ctf_id}/menu
4. GET /api/challenges/{challenge_id}/download/link
5. GET returned signed download URL
6. POST /api/challenges/containers/start with JSON {"id": challenge_id}
7. POST /api/challenges/containers/stop with JSON {"id": challenge_id}
8. POST /api/flags/own with JSON {"challenge_id": challenge_id, "flag": flag}
9. GET /api/challenges/{challenge_id}/solves
10. GET /api/ctfs/solves/{ctf_id}
11. GET /api/ctfs/scores/{ctf_id}
12. GET /api/ctfs/score-charts/{ctf_id}

Architecture:
- Add core/htb_cookie_client.py
- Add platforms/htb_cookie.py
- Add setup_htb_cookie.py
- Add prompts/htb_cookie_system.md
- Add tests/fixtures/htb_cookie/
- Add tests for client, platform adapter, setup, submission, instance management

Implementation details:
- Refactor /mnt/data/htb_cookie_client.py into core/htb_cookie_client.py.
- Keep a dev CLI if useful.
- HTBCookieClient should parse Cookie, Authorization, and User-Agent from either:
  1. environment variables:
     - HTB_CTF_COOKIE
     - HTB_CTF_BEARER
     - HTB_CTF_USER_AGENT
  2. --headers-file containing a copied raw HTTP request.
- HTBCookiePlatform should implement BasePlatform:
  - list_challenges
  - get_challenge
  - download_files
  - start_instance
  - stop_instance
  - instance_status
  - submit_flag

Challenge normalization:
- Map challenge_category_id to category name using /api/public/challenge-categories.
- target_kind rules:
  - hasMachine or machine => fullpwn
  - hasDocker and docker_instance_type == web => docker_web
  - hasDocker otherwise => docker_tcp
  - filename only => static
  - else => unknown
- Docker targets:
  - After POST start, poll GET /api/ctfs/{ctf_id}
  - Wait for docker_online + hostname + docker_ports
  - Save host, port, and url into target.json

Download flow:
- Only download if filename exists.
- GET /api/challenges/{id}/download/link.
- GET returned signed URL immediately.
- Save under challenges/htb_cookie/{ctf_id}/{category}/{id}_{slug}/files.
- Hash downloaded file.
- Try extraction with no password, then password "hackthebox".

Submission flow:
- POST /api/flags/own.
- Wrong flag observed:
  HTTP 400
  {"message": "Wrong flag, sorry!"}
- Mark accepted only if HTTP 200/201 and response message does not contain wrong.
- Deduplicate candidates.
- Enforce max_wrong_submissions_per_challenge.
- Support --no-submit and --manual-submit.

Security:
- Never log Cookie or Authorization.
- Redact signed download URLs.
- Add .env, headers files, and Burp exports to .gitignore.
- Use only authorized CTF event targets.

Do not break existing CTFd functionality.
Keep changes modular and commit in small patches.
```

---

# Troubleshooting Guide

## 401 Unauthorized

Likely causes:

```text
- expired bearer token
- expired session cookie
- copied incomplete Cookie header
- missing Authorization header
```

Fix:

```text
1. Open HTB CTF in browser
2. Capture a fresh API request
3. Copy Cookie and Authorization
4. Update .env or headers file
```

## 403 Forbidden

Likely causes:

```text
- not joined to CTF
- account cannot view challenges
- missing bearer token
- Cloudflare/browser session mismatch
```

Check:

```bash
python3 setup_htb_cookie.py --ctf-id 1434 --headers-file htb_headers.txt --check
```

This should call:

```text
GET /api/ctfs/{ctf_id}/menu
```

and verify:

```text
userCanViewChallenges = true
```

## Download URL Fails

Likely causes:

```text
- signed URL expired
- used old download URL from logs
- challenge has no filename
```

Fix:

```text
Always call /api/challenges/{id}/download/link immediately before downloading.
```

## Container Start Returns Success but No Host

This is normal.

Fix:

```text
Poll GET /api/ctfs/{ctf_id}
until docker_online, hostname, and docker_ports appear.
```

## Wrong Flag Marked as Exception

Do not treat HTTP 400 from `/api/flags/own` as a fatal client error.

For this endpoint only, parse the body:

```json
{
  "message": "Wrong flag, sorry!"
}
```

and store it as a wrong attempt.

---

# Final Expected User Commands

## Setup

```bash
python3 setup_htb_cookie.py \
  --ctf-id 1434 \
  --headers-file htb_headers.txt \
  --interactive
```

## List Challenges

```bash
python3 orchestrator.py \
  --platform htb_cookie \
  --ctf-id 1434 \
  --list-challenges
```

## Download All Files

```bash
python3 orchestrator.py \
  --platform htb_cookie \
  --ctf-id 1434 \
  --download \
  --sync-only
```

## Start One Challenge

```bash
python3 orchestrator.py \
  --platform htb_cookie \
  --ctf-id 1434 \
  --challenge-id 31856 \
  --start-only
```

## Solve Web Challenges Without Submission

```bash
python3 orchestrator.py \
  --platform htb_cookie \
  --ctf-id 1434 \
  --categories web \
  --parallel 1 \
  --plan \
  --no-submit
```

## Solve and Submit

```bash
python3 orchestrator.py \
  --platform htb_cookie \
  --ctf-id 1434 \
  --categories web,pwn,crypto \
  --parallel 3 \
  --plan \
  --walkthrough
```

## Manual Submit Candidate

```bash
python3 orchestrator.py \
  --platform htb_cookie \
  --ctf-id 1434 \
  --challenge-id 40742 \
  --submit-candidate 'HTB{...}'
```

## Stop Container

```bash
python3 orchestrator.py \
  --platform htb_cookie \
  --ctf-id 1434 \
  --challenge-id 40742 \
  --stop-instance
```

---

# Final Deliverable Definition

The new Koshary version is complete when:

```text
1. Existing CTFd mode still works.
2. HTB cookie mode can validate auth.
3. HTB cookie mode can list categories and challenges.
4. HTB cookie mode can create workspaces.
5. HTB cookie mode can download files through signed URLs.
6. HTB cookie mode can start Docker containers.
7. HTB cookie mode can poll and save target host/port.
8. HTB cookie mode can pass target info to Codex/Gemini agents.
9. HTB cookie mode can extract and submit flags.
10. HTB cookie mode stores all submissions and avoids duplicates.
11. HTB cookie mode can stop containers.
12. Scoreboard/strategy mode works.
13. Secrets are redacted.
14. Tests cover mocked endpoint flows.
15. README documents setup and usage.
```
