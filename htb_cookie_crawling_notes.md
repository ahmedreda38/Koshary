# HTB CTF Cookie/Bearer Crawling Notes from Captured Burp Requests

## Key Finding

The captured browser API traffic for `ctf.hackthebox.com` uses JSON endpoints under:

```text
https://ctf.hackthebox.com/api/...
```

Every captured API request included both:

```text
Cookie: ...
Authorization: Bearer ...
```

So the Koshary "HTB cookie mode" should support both `Cookie` and `Authorization: Bearer`, even if we call it cookie mode.

## Event ID Observed

```text
1434
```

The main event endpoint was:

```http
GET /api/ctfs/1434
```

This returned:

```text
id
name
org_name
starts_at
ends_at
status
participating_team
hasVPN
hasPwnbox
mcp_access_mode
ai_usage_policy
challenges
```

## Categories

Endpoint:

```http
GET /api/public/challenge-categories
```

Response shape:

```json
[
  {"id": 1, "name": "Fullpwn"},
  {"id": 2, "name": "Web"},
  {"id": 3, "name": "Pwn"},
  {"id": 4, "name": "Crypto"}
]
```

The event challenge objects use:

```text
challenge_category_id
```

So the crawler should map:

```python
category_name = categories[challenge["challenge_category_id"]]
```

## Main Challenge Crawl

Endpoint:

```http
GET /api/ctfs/{ctf_id}
```

Important challenge fields observed:

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

## Download Flow

Only challenges with a non-empty `filename` are downloadable.

Endpoint:

```http
GET /api/challenges/{challenge_id}/download/link
```

Response:

```json
{
  "url": "http://ctf.hackthebox.com/challenges/{challenge_id}/download?expires=...&signature=..."
}
```

The returned URL is signed and expiring, so download it immediately.

Suggested logic:

```text
1. GET /api/ctfs/{ctf_id}
2. For every challenge where filename is not empty:
3. GET /api/challenges/{id}/download/link
4. GET returned signed URL
5. Save into challenges/<event>/<category>/<id>_<slug>/files/
```

## Container Start

Endpoint:

```http
POST /api/challenges/containers/start
Content-Type: application/json

{"id": 31856}
```

Response observed:

```json
{
  "message": "Container starting."
}
```

The start response does not include host/port. Re-fetch the event endpoint and poll until the challenge shows:

```text
docker_online = 1
hostname = "154.57.x.x"
docker_ports = [30502]
```

Suggested polling:

```text
POST start
repeat for 60 seconds:
  GET /api/ctfs/{ctf_id}
  find challenge id
  if docker_online and hostname and docker_ports:
      target is ready
```

## Container Stop

Endpoint:

```http
POST /api/challenges/containers/stop
Content-Type: application/json

{"id": 40742}
```

Response observed:

```json
{
  "message": "Container stopping."
}
```

## Submit Flag

Endpoint:

```http
POST /api/flags/own
Content-Type: application/json

{
  "challenge_id": 40742,
  "flag": "HTB{...}"
}
```

Wrong response observed:

```json
{
  "message": "Wrong flag, sorry!"
}
```

For accepted flags, treat HTTP 200 or 201 with no "wrong" message as accepted.

## Solves and Scoreboard

CTF solves:

```http
GET /api/ctfs/solves/{ctf_id}
```

Challenge solves:

```http
GET /api/challenges/{challenge_id}/solves
```

Scores:

```http
GET /api/ctfs/scores/{ctf_id}
```

Score charts:

```http
GET /api/ctfs/score-charts/{ctf_id}
```

## Koshary Integration Plan

Add a second HTB adapter:

```text
platforms/htb_cookie.py
```

It should implement the same normalized interface as the CTFd adapter:

```python
class HTBCookiePlatform(BasePlatform):
    def list_challenges(self): ...
    def get_challenge(self, challenge_id): ...
    def download_files(self, challenge, dest_dir): ...
    def start_instance(self, challenge): ...
    def stop_instance(self, challenge): ...
    def submit_flag(self, challenge, flag): ...
```

## Config Example

```json
{
  "platform": "htb_cookie",
  "htb_cookie": {
    "base_url": "https://ctf.hackthebox.com",
    "ctf_id": 1434,
    "auth_mode": "cookie_bearer",
    "auto_start_instances": true,
    "auto_stop_on_solve": false,
    "download_password": "hackthebox",
    "max_wrong_submissions_per_challenge": 3
  }
}
```

## Environment Example

```bash
export HTB_CTF_COOKIE='paste full Cookie header value here'
export HTB_CTF_BEARER='paste Bearer token value here, without "Bearer "'
```

## Recommended Commands

```bash
python3 htb_cookie_client.py --ctf-id 1434 --headers-file htb_headers.txt list

python3 htb_cookie_client.py --ctf-id 1434 --headers-file htb_headers.txt download --out challenges/1434

python3 htb_cookie_client.py --ctf-id 1434 --headers-file htb_headers.txt start 31856

python3 htb_cookie_client.py --ctf-id 1434 --headers-file htb_headers.txt submit 31856 'HTB{...}'
```

## Security Notes

- Do not commit cookies or bearer tokens.
- Do not print tokens in logs.
- Refresh the token/cookie if HTB returns 401 or 403.
- Keep rate limits conservative.
- Use only for CTF events you are authorized to access.
