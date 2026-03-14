#!/usr/bin/env python3
"""
Koshary Framework v0.1-beta

Autonomous multi-agent framework for solving CTFd-hosted competitions.
This is a BETA VERSION for testing and evaluation purposes.
"""

import argparse
import concurrent.futures as futures
import contextlib
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse, unquote

import requests

# =========================
# Professional Logging
# =========================
try:
    from colorama import Fore, Style, init as colorama_init
    colorama_init()
except Exception:
    class _Dummy:
        BLACK = RED = GREEN = YELLOW = BLUE = MAGENTA = CYAN = WHITE = RESET = ""
    class _DummyStyle:
        BRIGHT = NORMAL = RESET_ALL = ""
    Fore = _Dummy()
    Style = _DummyStyle()


# =========================
# Global Synchronization
# =========================
PRINT_LOCK = threading.Lock()
STATE_LOCK = threading.Lock()


def _p(msg: str) -> None:
    with PRINT_LOCK:
        print(msg, flush=True)


def ts() -> str:
    return time.strftime("%H:%M:%S")


def log_info(msg: str) -> None:
    _p(f"{Fore.CYAN}[{ts()}][INFO]{Style.RESET_ALL} {msg}")


def log_ok(msg: str) -> None:
    _p(f"{Fore.GREEN}[{ts()}][ OK ]{Style.RESET_ALL} {msg}")


def log_warn(msg: str) -> None:
    _p(f"{Fore.YELLOW}[{ts()}][WARN]{Style.RESET_ALL} {msg}")


def log_err(msg: str) -> None:
    _p(f"{Fore.RED}[{ts()}][ERR ]{Style.RESET_ALL} {msg}")


def log_dbg(msg: str) -> None:
    _p(f"{Fore.MAGENTA}[{ts()}][DBG ]{Style.RESET_ALL} {msg}")


def log_step(msg: str) -> None:
    _p(f"{Fore.BLUE}{Style.BRIGHT}[{ts()}][STEP]{Style.RESET_ALL} {msg}")


# =========================
# Data structures
# =========================
@dataclass
class Challenge:
    id: int
    name: str
    category: str
    value: Optional[int]
    description: str
    files: List[str]
    connection_info: Optional[str] = None
    solved_by_me: bool = False


# =========================
# Utilities
# =========================
def load_env(env_path: Path) -> None:
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            parts = line.split("=", 1)
            if len(parts) == 2:
                key, val = parts
                key = key.strip()
                val = val.strip().strip("'").strip("\"")
                os.environ[key] = val


def load_json(path: Path, default: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if not path.exists():
        return default if default is not None else {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def safe_filename(file_url: str) -> str:
    parsed = urlparse(file_url)
    name = Path(parsed.path).name
    name = unquote(name)
    return name or "download.bin"


def sha1_text(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()


def extract_flags(text: str, patterns: List[str]) -> List[str]:
    found: List[str] = []
    for pat in patterns:
        try:
            found.extend(re.findall(pat, text, flags=re.IGNORECASE))
        except Exception as e:
            log_err(f"Regex error with pattern '{pat}': {e}")
    out = []
    seen = set()
    for item in found:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def extract_first_code_block(text: str) -> Tuple[Optional[str], Optional[str]]:
    m = re.search(r"```([a-zA-Z0-9_+\-]*)\n(.*?)```", text, re.DOTALL)
    if not m:
        return None, None
    lang = (m.group(1) or "").strip().lower()
    code = m.group(2).strip()
    return lang, code


def extract_run_commands(text: str, max_commands: int = 4) -> List[str]:
    cmds = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("RUN:"):
            cmd = line[4:].strip()
            if cmd:
                cmds.append(cmd)
        if len(cmds) >= max_commands:
            break
    return cmds


def append_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(text)
        if not text.endswith("\n"):
            f.write("\n")


def ensure_dirs(*paths: Path) -> None:
    for p in paths:
        p.mkdir(parents=True, exist_ok=True)


def build_challenge(detail: Dict[str, Any]) -> Challenge:
    files = []
    for f in detail.get("files", []):
        if isinstance(f, str):
            files.append(f)
        elif isinstance(f, dict) and "location" in f:
            files.append(f["location"])

    return Challenge(
        id=detail["id"],
        name=detail["name"],
        category=detail.get("category", ""),
        value=detail.get("value"),
        description=detail.get("description", ""),
        files=files,
        connection_info=detail.get("connection_info"),
        solved_by_me=detail.get("solved_by_me", False)
    )


def choose_route(category: str, routing: Dict[str, str]) -> Optional[str]:
    c = category.lower().strip()
    for key, route in routing.items():
        if key in c:
            return route
    return None


def choose_model_key(route: str, category: str) -> str:
    c = category.lower()
    if route == "gemini":
        return "gemini"
    if route == "codex":
        if "pwn" in c or "binary" in c:
            return "codex_pwn"
        return "codex_crypto"
    raise ValueError(f"Unknown route: {route}")


def collect_workspace_text(chdir: Path, max_files: int = 40, max_chars_per_file: int = 12000) -> str:
    interesting_ext = {
        ".txt", ".md", ".py", ".json", ".log", ".out", ".cfg",
        ".csv", ".xml", ".html", ".js", ".php", ".c", ".cpp", ".cc",
        ".h", ".hpp", ".java", ".rs", ".go", ".sh", ".yaml", ".yml",
        ".sage", ".asm"
    }
    chunks = []
    count = 0
    for p in sorted(chdir.rglob("*")):
        if not p.is_file():
            continue
        if p.name.startswith("."):
            continue
        if "agent_rounds" in p.parts:
            continue
            
        if p.suffix.lower() not in interesting_ext:
            continue
        try:
            txt = p.read_text(errors="ignore")
        except Exception:
            continue
        txt = txt.strip()
        if not txt:
            continue
        rel = p.relative_to(chdir)
        chunks.append(f"\n===== FILE: {rel} =====\n{txt[:max_chars_per_file]}")
        count += 1
        if count >= max_files:
            break
    return "\n".join(chunks)


def collect_history_text(chdir: Path, current_round: int) -> str:
    history = []
    rounds_dir = chdir / "agent_rounds"
    
    for r in range(1, current_round):
        round_summary = [f"--- ROUND {r} ---"]
        out_path = rounds_dir / f"round_{r:02d}.out.txt"
        if out_path.exists():
            out_txt = out_path.read_text(errors="ignore").strip()
            round_summary.append(f"[Model Output]:\n{out_txt[-1500:]}")
            
        exec_path = rounds_dir / f"round_{r:02d}.exec.txt"
        if exec_path.exists():
            exec_txt = exec_path.read_text(errors="ignore").strip()
            round_summary.append(f"[Execution Result]:\n{exec_txt[:800]}")
            
        cmd_path = rounds_dir / f"round_{r:02d}.commands.txt"
        if cmd_path.exists():
            cmd_txt = cmd_path.read_text(errors="ignore").strip()
            round_summary.append(f"[Command Results]:\n{cmd_txt[:800]}")
            
        history.append("\n".join(round_summary))
        
    return "\n\n".join(history)


def render_prompt(template_path: Path, chall: Challenge, challenge_dir: Path, round_no: int, workspace: str, history: str, env_info: str = "N/A", plan: str = "No plan generated.") -> str:
    template = template_path.read_text(encoding="utf-8")
    return template.format(
        challenge_name=chall.name,
        category=chall.category,
        value=chall.value if chall.value is not None else "",
        description=chall.description,
        connection_info=chall.connection_info if chall.connection_info else "N/A",
        workdir=str(challenge_dir.resolve()),
        files="\n".join(f"- {x}" for x in chall.files) if chall.files else "- none",
        round_no=round_no,
        workspace=workspace,
        history=history,
        env_info=env_info,
        plan=plan,
    )


# =========================
# State Management
# =========================
class StateDB:
    def __init__(self, path: Path):
        self.path = path
        self.data = load_json(path, default={
            "solved_ids": [],
            "submitted": [],
            "challenges": {},
            "errors": [],
            "stats": {
                "runs": 0,
                "model_rounds": 0,
                "artifacts_executed": 0,
                "commands_executed": 0,
            }
        })
        self.save()

    def save(self) -> None:
        with STATE_LOCK:
            save_json(self.path, self.data)

    def is_solved(self, chall_id: int) -> bool:
        return chall_id in self.data.get("solved_ids", [])

    def inc_stat(self, key: str, delta: int = 1) -> None:
        with STATE_LOCK:
            self.data.setdefault("stats", {})
            self.data["stats"][key] = self.data["stats"].get(key, 0) + delta
            save_json(self.path, self.data)

    def mark_seen(self, chall: Challenge, workdir: str, route: str, status: str) -> None:
        with STATE_LOCK:
            self.data["challenges"][str(chall.id)] = {
                "id": chall.id,
                "name": chall.name,
                "category": chall.category,
                "value": chall.value,
                "route": route,
                "status": status,
                "workdir": workdir,
                "last_update": int(time.time()),
            }
            save_json(self.path, self.data)

    def mark_status(self, chall_id: int, status: str) -> None:
        key = str(chall_id)
        with STATE_LOCK:
            if key not in self.data["challenges"]:
                self.data["challenges"][key] = {}
            self.data["challenges"][key]["status"] = status
            self.data["challenges"][key]["last_update"] = int(time.time())
            save_json(self.path, self.data)

    def mark_solved(self, chall_id: int, flag: str, response: Dict[str, Any]) -> None:
        key = str(chall_id)
        with STATE_LOCK:
            if chall_id not in self.data["solved_ids"]:
                self.data["solved_ids"].append(chall_id)
            self.data["submitted"].append({
                "challenge_id": chall_id,
                "flag": flag,
                "response": response,
                "ts": int(time.time()),
            })
            if key in self.data["challenges"]:
                self.data["challenges"][key]["status"] = "solved"
                self.data["challenges"][key]["solved_flag"] = flag
            save_json(self.path, self.data)

    def mark_attempt(self, chall_id: int, flag: str, response: Dict[str, Any]) -> None:
        with STATE_LOCK:
            self.data["submitted"].append({
                "challenge_id": chall_id,
                "flag": flag,
                "response": response,
                "ts": int(time.time()),
            })
            save_json(self.path, self.data)

    def attempted_flag(self, chall_id: int, flag: str) -> bool:
        return any(
            x["challenge_id"] == chall_id and x["flag"] == flag
            for x in self.data.get("submitted", [])
        )

    def add_error(self, stage: str, chall_id: Optional[int], message: str) -> None:
        with STATE_LOCK:
            self.data["errors"].append({
                "ts": int(time.time()),
                "stage": stage,
                "challenge_id": chall_id,
                "message": message,
            })
            save_json(self.path, self.data)


# =========================
# CTFd API Interaction
# =========================
class CTFdClient:
    def __init__(self, base_url: str, session_cookie: str):
        self.base_url = base_url.rstrip("/")
        self.s = requests.Session()
        self.s.headers["Cookie"] = f"session={session_cookie}"
        self.s.headers["User-Agent"] = "ctf-ai-orchestrator/3.0"
        self.nonce = self._fetch_nonce()

    def _fetch_nonce(self) -> str:
        try:
            r = self.s.get(f"{self.base_url}/challenges", timeout=20)
            r.raise_for_status()
            m = re.search(r"['\"]?csrf_?[Nn]once['\"]?:\s*['\"]([a-f0-9]+)['\"]", r.text)
            if m:
                nonce = m.group(1)
                log_ok(f"Synchronized CSRF nonce: {nonce}")
                self.s.headers["CSRF-Token"] = nonce
                return nonce
            m = re.search(r'<meta name="csrf-token" content="([a-f0-9]+)">', r.text)
            if m:
                nonce = m.group(1)
                self.s.headers["CSRF-Token"] = nonce
                return nonce
            log_warn("CSRF nonce synchronization failed for current session.")
        except Exception as e:
            log_err(f"Session error while fetching nonce: {e}")
        return ""

    def get_challenges(self) -> List[Dict[str, Any]]:
        r = self.s.get(f"{self.base_url}/api/v1/challenges", timeout=20)
        r.raise_for_status()
        data = r.json()
        if not data.get("success", False):
            raise RuntimeError(f"CTFd challenge list fetch failed: {data}")
        return data["data"]

    def get_challenge_detail(self, chall_id: int) -> Dict[str, Any]:
        r = self.s.get(f"{self.base_url}/api/v1/challenges/{chall_id}", timeout=20)
        r.raise_for_status()
        data = r.json()
        if not data.get("success", False):
            raise RuntimeError(f"CTFd challenge detail fetch failed for {chall_id}: {data}")
        return data["data"]

    def download_file(self, url: str, out_path: Path) -> None:
        if not url.startswith("http"):
            url = self.base_url + url
        with self.s.get(url, timeout=90, stream=True) as r:
            r.raise_for_status()
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with open(out_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)

    def submit_flag(self, challenge_id: int, flag: str) -> Dict[str, Any]:
        if not self.s.headers.get("CSRF-Token"):
            self._fetch_nonce()
        headers = {
            "Content-Type": "application/json",
            "CSRF-Token": self.s.headers.get("CSRF-Token", "")
        }
        r = self.s.post(
            f"{self.base_url}/api/v1/challenges/attempt",
            json={"challenge_id": challenge_id, "submission": flag},
            headers=headers,
            timeout=20,
        )
        r.raise_for_status()
        return r.json()


# =========================
# Execution Engine
# =========================
def ensure_executable(path: Path) -> None:
    mode = path.stat().st_mode
    path.chmod(mode | 0o111)


def run_subprocess(cmd: List[str], cwd: Path, timeout: int = 180, env: Optional[Dict[str, str]] = None) -> Tuple[int, str]:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
        env=env if env else os.environ,
    )
    output = (proc.stdout or "") + ("\n" if proc.stdout and proc.stderr else "") + (proc.stderr or "")
    return proc.returncode, output


def run_model(runner_cmd: str, prompt_file: Path, cwd: Path, timeout: int = 300) -> Tuple[int, str]:
    parts = shlex.split(runner_cmd)
    if len(parts) >= 2 and parts[0] == "bash":
        script = Path(parts[1])
        if not script.is_absolute():
            script = (Path(__file__).resolve().parent / script).resolve()
        parts[1] = str(script)
    parts.append(str(prompt_file.resolve()))
    return run_subprocess(parts, cwd=cwd, timeout=timeout)


def save_generated_artifact(chdir: Path, round_no: int, lang: str, code: str) -> Optional[Path]:
    ext = ".txt"
    lang = (lang or "").lower()
    if lang in {"python", "py"}: ext = ".py"
    elif lang in {"bash", "sh", "zsh"}: ext = ".sh"
    elif lang in {"javascript", "js"}: ext = ".js"
    elif lang in {"ruby", "rb"}: ext = ".rb"
    elif lang in {"perl", "pl"}: ext = ".pl"

    out = chdir / "agent_rounds" / f"round_{round_no:02d}.artifact{ext}"
    out.write_text(code, encoding="utf-8")
    if ext == ".sh": ensure_executable(out)
    return out


def run_generated_artifact(path: Path, timeout: int = 240, env: Optional[Dict[str, str]] = None) -> Tuple[int, str]:
    if path.suffix == ".py": cmd = ["python3", path.name]
    elif path.suffix == ".sh": cmd = ["bash", path.name]
    elif path.suffix == ".js": cmd = ["node", path.name]
    elif path.suffix == ".rb": cmd = ["ruby", path.name]
    elif path.suffix == ".pl": cmd = ["perl", path.name]
    else: return 0, ""
    return run_subprocess(cmd, cwd=path.parent, timeout=timeout, env=env)


def run_model_commands(commands: List[str], chdir: Path, timeout: int = 90, env: Optional[Dict[str, str]] = None) -> List[Tuple[str, int, str]]:
    results = []
    for cmd_str in commands:
        try:
            rc, output = run_subprocess(shlex.split(cmd_str), cwd=chdir, timeout=timeout, env=env)
        except Exception as e:
            rc, output = 1, str(e)
        results.append((cmd_str, rc, output))
    return results


def acquire_lock(lock_path: Path) -> bool:
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    except FileExistsError: return False


def release_lock(lock_path: Path) -> None:
    with contextlib.suppress(FileNotFoundError): lock_path.unlink()


# =========================
# Planning Agent
# =========================
def generate_challenge_plan(
    chall: Challenge,
    runner_cmd: str,
    chdir: Path,
    timeout: int = 300,
) -> str:
    plan_prompt = (
        f"You are a CTF Planning Agent. Analyze the following challenge and files to create a high-level strategy.\n\n"
        f"Challenge: {chall.name}\nCategory: {chall.category}\nDescription: {chall.description}\n"
        f"Connection: {chall.connection_info}\n"
        f"Files: {chall.files}\n\n"
        "Your output should be a structured markdown plan. Do not write code yet. "
        "Focus on: Potential vulnerabilities, Required tools, and Execution steps."
    )
    prompt_file = chdir / "agent_rounds" / "planning_prompt.txt"
    prompt_file.write_text(plan_prompt, encoding="utf-8")
    
    log_info(f"Generating strategy for #{chall.id} {chall.name}...")
    rc, output = run_model(runner_cmd, prompt_file, chdir, timeout=timeout)
    
    if rc != 0:
        log_warn(f"Strategy generation failed for #{chall.id}. Proceeding without plan.")
        return "No plan generated."
        
    (chdir / "plan.md").write_text(output, encoding="utf-8")
    return output


# =========================
# Autonomous Solver Worker
# =========================
def process_challenge(
    chall: Challenge,
    config: Dict[str, Any],
    db: StateDB,
    client: CTFdClient,
    root: Path,
    exec_env: Optional[Dict[str, str]] = None,
    env_info: str = "N/A",
    enable_planning: bool = False,
    override_timeout: Optional[int] = None,
) -> Dict[str, Any]:
    route = choose_route(chall.category, config["routing"])
    if not route:
        log_warn(f"Skipping unsupported category [{chall.category}] :: {chall.name}")
        return {"status": "skipped", "challenge_id": chall.id}

    model_key = choose_model_key(route, chall.category)
    model_cfg = config["models"][model_key]
    runner_cmd = model_cfg["runner"]
    prompt_template = root / model_cfg["prompt_template"]

    chdir = root / config["workspace"]["root"] / f"{chall.id}-{slugify(chall.name)}"
    rounds_dir = chdir / "agent_rounds"
    files_dir = chdir / "files"
    ensure_dirs(chdir, rounds_dir, files_dir)

    lock_path = chdir / ".lock"
    if not acquire_lock(lock_path):
        return {"status": "locked", "challenge_id": chall.id}

    try:
        db.mark_seen(chall, str(chdir), route, "queued")
        (chdir / "challenge.json").write_text(json.dumps(asdict(chall), indent=2), encoding="utf-8")
        
        # Download Attachments
        for file_url in chall.files:
            fname = safe_filename(file_url)
            dst = files_dir / fname
            if not dst.exists():
                try: client.download_file(file_url, dst)
                except Exception as e: log_err(f"Download failed for #{chall.id}: {e}")

        # Planning Phase
        plan_txt = "No plan generated."
        if enable_planning:
            plan_txt = generate_challenge_plan(chall, runner_cmd, chdir, timeout=override_timeout or config["ctf"].get("model_timeout", 300))
            log_ok(f"Strategy formulated for #{chall.id}")

        db.mark_status(chall.id, "running")
        last_workspace_hash = None
        idle_rounds = 0
        solved = False

        max_rounds = config["ctf"].get("max_agent_rounds", 8)
        max_idle_rounds = config["ctf"].get("max_idle_rounds", 2)
        model_timeout = override_timeout or config["ctf"].get("model_timeout", 300)

        for round_no in range(1, max_rounds + 1):
            log_step(f"Round {round_no}/{max_rounds} :: #{chall.id} {chall.name}")
            db.inc_stat("model_rounds", 1)

            workspace_text = collect_workspace_text(chdir)
            history_text = collect_history_text(chdir, round_no)
            
            workspace_hash = sha1_text(workspace_text)
            if workspace_hash == last_workspace_hash:
                idle_rounds += 1
                if idle_rounds >= max_idle_rounds:
                    log_warn(f"Challenge #{chall.id} stalled. Terminating.")
                    break
            else: idle_rounds = 0
            last_workspace_hash = workspace_hash

            prompt = render_prompt(prompt_template, chall, chdir, round_no, workspace_text[:20000], history_text[:20000], env_info=env_info, plan=plan_txt)
            prompt_file = rounds_dir / f"round_{round_no:02d}.prompt.txt"
            prompt_file.write_text(prompt, encoding="utf-8")

            # Agent Execution
            try:
                rc, output = run_model(runner_cmd, prompt_file, chdir, timeout=model_timeout)
                out_file = rounds_dir / f"round_{round_no:02d}.out.txt"
                out_file.write_text(output, encoding="utf-8")
                combined_text = output

                # RUN Commands
                run_commands = extract_run_commands(output)
                if run_commands:
                    cmd_results = run_model_commands(run_commands, chdir, timeout=config["ctf"].get("command_timeout", 90), env=exec_env)
                    db.inc_stat("commands_executed", len(cmd_results))
                    combined_text += "\n" + "\n".join([r[2] for r in cmd_results])
                    (rounds_dir / f"round_{round_no:02d}.commands.txt").write_text("\n\n".join([f"$ {r[0]}\n{r[2]}" for r in cmd_results]))

                # Artifact Execution
                lang, code = extract_first_code_block(output)
                if code:
                    artifact_path = save_generated_artifact(chdir, round_no, lang or "", code)
                    exec_rc, exec_output = run_generated_artifact(artifact_path, timeout=config["ctf"].get("artifact_timeout", 240), env=exec_env)
                    db.inc_stat("artifacts_executed", 1)
                    (rounds_dir / f"round_{round_no:02d}.exec.txt").write_text(exec_output, encoding="utf-8")
                    combined_text += "\n" + exec_output

                # Flag Detection & Submission
                flags = extract_flags(combined_text, config["ctf"]["flag_patterns"])
                for flag in flags:
                    if db.attempted_flag(chall.id, flag): continue
                    if not config["ctf"].get("auto_submit", False):
                        log_warn(f"Flag detected for #{chall.id} [Submission Disabled]: {flag}")
                        continue
                    
                    log_step(f"Attempting flag submission for #{chall.id}: {flag}")
                    resp = client.submit_flag(chall.id, flag)
                    (chdir / "submitted.json").write_text(json.dumps(resp, indent=2), encoding="utf-8")
                    
                    msg_text = json.dumps(resp).lower()
                    if resp.get("success") is True and not any(bad in msg_text for bad in ["incorrect", "wrong"]):
                        log_ok(f"SOLVED: #{chall.id} {chall.name} Flag: {flag}")
                        db.mark_solved(chall.id, flag, resp)
                        solved = True
                        break
                    else:
                        log_warn(f"Submission rejected for #{chall.id}: {flag}")
                        db.mark_attempt(chall.id, flag, resp)
                
                if solved: break

            except subprocess.TimeoutExpired:
                log_err(f"Model timeout on #{chall.id}, round {round_no}")
            except Exception as e:
                log_err(f"Agent error on #{chall.id}, round {round_no}: {e}")

        if not solved: db.mark_status(chall.id, "failed")
        return {"status": "solved" if solved else "done", "challenge_id": chall.id}
    finally:
        release_lock(lock_path)


# =========================
# Main Entry Point
# =========================
def main() -> int:
    parser = argparse.ArgumentParser(description="CTF AI Orchestrator v2.5")
    parser.add_argument("--url", help="CTFd base URL")
    parser.add_argument("--session", help="CTFd session cookie")
    parser.add_argument("--categories", help="Comma-separated categories to include")
    parser.add_argument("--parallel", type=int, help="Number of parallel workers")
    parser.add_argument("--flag-format", help="Specific flag regex pattern")
    parser.add_argument("--venv", help="Path to python virtual environment")
    parser.add_argument("--plan", action="store_true", help="Enable strategic planning phase")
    parser.add_argument("--timeout", type=int, help="Override default model timeout (seconds)")
    args = parser.parse_args()

    root = Path(".").resolve()
    load_env(root / ".env")
    config = load_json(root / "config.json")

    # CLI Overrides
    if args.url: config["ctf"]["base_url"] = args.url.rstrip("/")
    if args.categories: config["ctf"]["include_categories"] = [c.strip().lower() for c in args.categories.split(",")]
    if args.parallel: config["ctf"]["parallel_workers"] = args.parallel
    if args.flag_format and args.flag_format not in config["ctf"]["flag_patterns"]:
        config["ctf"]["flag_patterns"].insert(0, args.flag_format)
    
    # Environment Setup
    exec_env = os.environ.copy()
    env_info = "Standard system environment."
    if args.venv:
        vp = Path(args.venv).expanduser().resolve()
        if (vp / "bin" / "python3").exists():
            log_ok(f"Active Virtual Environment: {vp}")
            exec_env["PATH"] = str(vp / "bin") + os.pathsep + exec_env.get("PATH", "")
            exec_env["VIRTUAL_ENV"] = str(vp)
            exec_env.pop("PYTHONHOME", None)
            env_info = f"Python venv at {vp} (includes specialized CTF libraries)."

    session = args.session or os.getenv("CTFD_SESSION", "").strip()
    if not session:
        log_err("Authentication failure: Missing CTFD_SESSION.")
        return 1

    db = StateDB(root / config["workspace"]["state_file"])
    client = CTFdClient(config["ctf"]["base_url"], session)
    db.inc_stat("runs", 1)

    log_step(f"Initialization complete for {config['ctf'].get('name', 'Competition')}")
    
    try:
        summaries = client.get_challenges()
        log_ok(f"Retrieved {len(summaries)} challenges from repository.")
    except Exception as e:
        log_err(f"Network error: {e}")
        return 1

    eligible = []
    cat_inc = set(x.lower() for x in config["ctf"].get("include_categories", []))
    
    _p("\n" + "="*85)
    _p(f"{'ID':<4} | {'Challenge Name':<35} | {'Category':<20} | {'Status'}")
    _p("-" * 85)
    for s in summaries:
        cid = s["id"]
        if s.get("solved_by_me"):
            if cid not in db.data["solved_ids"]: db.data["solved_ids"].append(cid)
            db.save()
        
        status = "SOLVED" if cid in db.data["solved_ids"] else "OPEN"
        cname = s["category"].lower()
        route = choose_route(s["category"], config["routing"])
        
        included = True
        if cat_inc and not any(x in cname for x in cat_inc): included = False
        if not route:
            included = False
            if status == "OPEN": status = "UNSUPPORTED"

        _p(f"{cid:<4} | {s['name'][:35]:<35} | {s['category']:<20} | {status}")
        if status == "OPEN" and included:
            detail = client.get_challenge_detail(cid)
            eligible.append(build_challenge(detail))
    _p("="*85 + "\n")

    if not eligible:
        log_warn("No pending challenges matched the inclusion criteria.")
        return 0

    log_info(f"Deploying agents to {len(eligible)} challenge(s).")
    workers = max(1, int(config["ctf"].get("parallel_workers", 3)))

    with futures.ThreadPoolExecutor(max_workers=workers) as executor:
        fmap = {
            executor.submit(process_challenge, chall, config, db, client, root, exec_env, env_info, args.plan, args.timeout): chall
            for chall in eligible
        }
        for fut in futures.as_completed(fmap):
            chall = fmap[fut]
            try:
                res = fut.result()
                log_ok(f"Process terminated for #{chall.id} {chall.name}: {res['status']}")
            except Exception as e:
                log_err(f"Worker failure for #{chall.id}: {e}")

    log_step("Mission complete. Solved: " + str(len(db.data.get("solved_ids", []))))
    return 0


if __name__ == "__main__":
    try: raise SystemExit(main())
    except KeyboardInterrupt:
        log_warn("Process interrupted by user.")
        raise SystemExit(130)
