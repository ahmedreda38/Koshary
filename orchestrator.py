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
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse, unquote

import requests

from platforms import get_platform, NormalizedChallenge
from platforms.base import BasePlatform, SubmitResult
# Re-exported for backward compatibility (first_blood.py imports CTFdClient here).
from platforms.ctfd import CTFdClient
from core import instance_manager
from core.flag_extractor import extract_candidate_answers, is_placeholder_flag
from core.logging_utils import register_secret, redact

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

SPLASH = f"""{Fore.YELLOW}{Style.BRIGHT}
  _  _____  ____  _   _   _    ______   __
 | |/ / _ \\/ ___|| | | | / \\  |  _ \\ \\ / /
 | ' / | | \\___ \\| |_| |/ _ \\ | |_) \\ V / 
 | . \\ |_| |___) |  _  / ___ \\|  _ < | |  
 |_|\\_\\___/|____/|_| |_/_/   \\_\\_| \\_\\|_|  {Fore.CYAN}[BETA v0.1]{Style.RESET_ALL}
{Fore.WHITE}      Autonomous Multi-Agent CTF Framework{Style.RESET_ALL}
"""

BANNER_CORRECT = f"""{Fore.GREEN}{Style.BRIGHT}
  ############################################################
  #                                                          #
  #   [!] CORRECT FLAG SUBMITTED! MISSION ACCOMPLISHED [!]   #
  #                                                          #
  ############################################################
{Style.RESET_ALL}"""


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
# The orchestrator now operates on the platform-independent NormalizedChallenge.
# ``Challenge`` remains as an alias for backward compatibility.
Challenge = NormalizedChallenge


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
        if item in seen or is_placeholder_flag(item):
            continue
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


def choose_route(category: str, routing: Dict[str, str]) -> Optional[str]:
    c = category.lower().strip()
    for key, route in routing.items():
        if key in c:
            return route
    return None


def category_matches_filter(category: str, category_filter: str, routing: Dict[str, str]) -> bool:
    category_name = category.lower().strip()
    filter_name = category_filter.lower().strip()

    if not filter_name:
        return False
    if filter_name in category_name or category_name in filter_name:
        return True

    alias_groups = (
        {"pwn", "binary", "binary exploitation"},
        {"dfir", "forensics"},
        {"rev", "reverse", "reverse engineering"},
        {"crypto", "cryptography"},
        {"web", "web exploitation"},
        {"misc", "miscellaneous"},
        {"mobile", "android"},
    )
    for aliases in alias_groups:
        if filter_name in aliases and any(alias in category_name for alias in aliases):
            return True

    return False


def choose_model_key(route: str, category: str) -> str:
    c = category.lower()
    if route == "gemini":
        if "misc" in c:
            return "gemini_misc"
        if "forensics" in c or "dfir" in c:
            return "gemini_forensics"
        return "gemini"
    if route == "codex":
        if "fullpwn" in c or "full-pwn" in c or "machine" in c:
            return "codex_fullpwn"
        if "pwn" in c or "binary" in c:
            return "codex_pwn"
        if "rev" in c or "reverse" in c:
            return "codex_rev"
        if "mobile" in c or "android" in c:
            return "codex_mobile"
        return "codex_crypto"
    if route == "claude":
        return "claude"
    raise ValueError(f"Unknown route: {route}")


def resolve_model_key(route: str, category: str, models: Dict[str, Any]) -> Optional[str]:
    """Pick a configured model key for this category, falling back gracefully
    when the most-specific key is not present in config["models"]."""
    preferred = choose_model_key(route, category)
    if preferred in models:
        return preferred
    fallbacks = {
        "gemini": ["gemini", "gemini_misc", "gemini_forensics"],
        "codex": ["codex_crypto", "codex_pwn", "codex_rev", "codex_fullpwn", "codex_mobile"],
        "claude": ["claude"],
    }
    for key in fallbacks.get(route, []):
        if key in models:
            return key
    return None


def check_model_availability(config: Dict[str, Any]) -> set[str]:
    available: set[str] = set()
    known_models = ("gemini", "codex", "claude")

    log_step("Checking available AI model CLIs...")
    for model in known_models:
        if shutil.which(model):
            available.add(model)
            log_ok(f"Available model: {model}")

    if not available:
        log_err("No AI model CLIs are available on this system. Checked: gemini, codex, claude.")
        sys.exit(1)

    log_info(f"Available models on this system: {', '.join(sorted(available))}")

    missing_routes = sorted({route for route in config.get("routing", {}).values() if route not in available})
    for route in missing_routes:
        categories = sorted(key for key, value in config.get("routing", {}).items() if value == route)
        categories_text = ", ".join(categories) if categories else "unknown categories"
        log_warn(f"Configured model '{route}' is not available. Affected categories: {categories_text}")

    return available


def clean_model_output(text: str) -> str:
    """
    Strips runner-specific headers and logs to keep the AI context clean.
    """
    lines = text.splitlines()
    cleaned = []
    capture = False
    
    # Common markers for the end of runner headers
    markers = ["codex output begins", "gemini output begins", "---"]
    
    for line in lines:
        if any(marker in line.lower() for marker in markers):
            capture = True
            continue
        if capture:
            cleaned.append(line)
            
    # If no markers found, return original (fallback)
    if not cleaned:
        # Just strip common runner prefix lines if they exist
        return "\n".join([line for line in lines if not line.startswith("[runner]")])
        
    return "\n".join(cleaned).strip()


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
        
        # EXCLUSIONS: agent_rounds, plan.md, challenge.json
        if "agent_rounds" in p.parts or p.name in ["plan.md", "challenge.json"]:
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


def build_htb_context(root: Path, chall: Challenge) -> str:
    """Assemble the HTB system prompt + target context prepended to every
    HTB solver round (Phase 7 of the integration plan)."""
    if chall.platform not in ("htb_ctf", "htb_cookie"):
        return ""
    parts: List[str] = []
    sys_candidates: List[Path] = []
    if chall.platform == "htb_cookie":
        sys_candidates.append(root / "prompts" / "htb_cookie_system.md")
    sys_candidates.append(root / "prompts" / "htb_system.md")
    for sys_path in sys_candidates:
        if sys_path.exists():
            parts.append(sys_path.read_text(encoding="utf-8").strip())
            break
    if "fullpwn" in (chall.category or "").lower() or chall.target_kind == "fullpwn":
        fp_path = root / "prompts" / "fullpwn.md"
        if fp_path.exists():
            parts.append(fp_path.read_text(encoding="utf-8").strip())
    target_block = (
        "[TARGET CONTEXT]\n"
        f"Platform: {chall.platform}\n"
        f"Event: {chall.event_id}\n"
        f"Challenge: {chall.name}\n"
        f"Category: {chall.category}\n"
        f"Target kind: {chall.target_kind}\n"
        f"Target URL: {chall.url or 'N/A'}\n"
        f"Host: {chall.host or 'N/A'}\n"
        f"Port: {chall.port if chall.port is not None else 'N/A'}\n"
        f"VPN required: {str(chall.vpn_required).lower()}\n"
    )
    parts.append(target_block)
    return "\n\n".join(parts) + "\n\n" + ("=" * 60) + "\n\n"


def render_prompt(template_path: Path, chall: Challenge, challenge_dir: Path, round_no: int, workspace: str, history: str, env_info: str = "N/A", plan: str = "No plan generated.", walkthrough_active: bool = False, prefix: str = "") -> str:
    template = template_path.read_text(encoding="utf-8")

    walkthrough_instr = ""
    if walkthrough_active:
        walkthrough_instr = (
            "\n[MANDATORY DOCUMENTATION]\n"
            "If you identify the flag or have a working exploit, you MUST also generate a 'walkthrough.md' file. "
            "This file should explain: 1) Challenge structure, 2) Identified vulnerabilities/flaws, 3) Detailed exploitation path. "
            "You can create this file using a fenced code block or a RUN: command."
        )

    body = template.format(
        challenge_name=chall.name,
        category=chall.category,
        value=chall.points if chall.points is not None else "",
        description=chall.description,
        connection_info=chall.connection_info if chall.connection_info else "N/A",
        workdir=str(challenge_dir.resolve()),
        files="\n".join(f"- {x}" for x in chall.files) if chall.files else "- none",
        round_no=round_no,
        workspace=workspace,
        history=history,
        env_info=env_info,
        plan=plan,
        walkthrough_instruction=walkthrough_instr
    )
    return prefix + body


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
            self.data["challenges"][str(chall.challenge_id)] = {
                "id": chall.challenge_id,
                "platform": chall.platform,
                "event_id": chall.event_id,
                "name": chall.name,
                "category": chall.category,
                "value": chall.points,
                "target_kind": chall.target_kind,
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

    def attempted_flag(self, chall_id, flag: str) -> bool:
        return any(
            str(x["challenge_id"]) == str(chall_id) and x["flag"] == flag
            for x in self.data.get("submitted", [])
        )

    def count_attempts(self, chall_id) -> int:
        return sum(
            1 for x in self.data.get("submitted", [])
            if str(x["challenge_id"]) == str(chall_id)
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
# CTFdClient now lives in platforms/ctfd.py and is imported at the top of this
# module (re-exported here for backward compatibility with first_blood.py).


# =========================
# Execution Engine
# =========================
def ensure_executable(path: Path) -> None:
    mode = path.stat().st_mode
    path.chmod(mode | 0o111)


def resolve_host(hostname: str) -> Optional[str]:
    try:
        import socket
        return socket.gethostbyname(hostname)
    except Exception:
        return None


def run_subprocess(cmd: List[str], cwd: Path, timeout: int = 180, env: Optional[Dict[str, str]] = None) -> Tuple[int, str]:
    # Ensure env is a dictionary and contains necessary variables
    run_env = os.environ.copy()
    if env:
        run_env.update(env)
        
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
        env=run_env,
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
    walkthrough: bool = False,
) -> str:
    plan_prompt = (
        f"You are a CTF Planning Agent. Analyze the following challenge and files to create a high-level strategy.\n\n"
        f"Challenge: {chall.name}\nCategory: {chall.category}\nDescription: {chall.description}\n"
        f"Connection: {chall.connection_info}\n"
        f"Files: {chall.files}\n\n"
        "Your output should be a structured markdown plan. Do not write code yet. "
        "Focus on: Potential vulnerabilities, Required tools, and Execution steps."
    )
    if walkthrough:
        plan_prompt += "\nAdditionally, your plan MUST include a final step to document the solution in a 'walkthrough.md' file once the flag is successfully identified."
    prompt_file = chdir / "agent_rounds" / "planning_prompt.txt"
    prompt_file.write_text(plan_prompt, encoding="utf-8")
    
    log_info(f"Generating strategy for #{chall.challenge_id} {chall.name} (Timeout: {timeout}s)...")
    # A subprocess call might take a while, this log confirms we are now waiting on the AI.
    rc, output = run_model(runner_cmd, prompt_file, chdir, timeout=timeout)

    cleaned_plan = clean_model_output(output)

    if rc != 0 or not cleaned_plan:
        log_warn(f"Strategy generation failed for #{chall.challenge_id}. Proceeding without plan.")
        return "No plan generated."
        
    (chdir / "plan.md").write_text(cleaned_plan, encoding="utf-8")
    return cleaned_plan


# =========================
# Workspace layout
# =========================
def challenge_workspace(root: Path, config: Dict[str, Any], chall: Challenge) -> Path:
    """Per-challenge workspace path (platform-aware).

    CTFd:        challenges/<id>-<slug>/
    HTB MCP:     challenges/<event>/<category>/<slug>/
    HTB cookie:  challenges/htb_cookie/<ctf_id>/<category>/<id>_<slug>/
    """
    base = root / config["workspace"]["root"]
    if chall.platform == "htb_cookie":
        return (base / "htb_cookie" / slugify(chall.event_id or "event")
                / slugify(chall.category or "misc")
                / f"{chall.challenge_id}_{chall.slug}")
    if chall.platform == "htb_ctf":
        return base / slugify(chall.event_id or "event") / slugify(chall.category or "misc") / chall.slug
    return base / f"{chall.challenge_id}-{slugify(chall.name)}"


def record_submission(chdir: Path, flag: str, accepted: bool, message: str) -> None:
    """Append a submission attempt to submitted.json (Phase 9 format)."""
    path = chdir / "submitted.json"
    data = {"attempts": [], "solved": False}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    data.setdefault("attempts", []).append({
        "flag": flag,
        "accepted": accepted,
        "message": redact(str(message))[:500],
        "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
    })
    if accepted:
        data["solved"] = True
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


# =========================
# Autonomous Solver Worker
# =========================
def process_challenge(
    chall: Challenge,
    config: Dict[str, Any],
    db: StateDB,
    platform: BasePlatform,
    root: Path,
    exec_env: Optional[Dict[str, str]] = None,
    env_info: str = "N/A",
    enable_planning: bool = False,
    override_timeout: Optional[int] = None,
    walkthrough: bool = False,
    submit_mode: str = "auto",
    auto_start: bool = True,
    auto_stop: bool = False,
    max_wrong: int = 3,
    allow_nonstandard: bool = False,
) -> Dict[str, Any]:
    cid = chall.challenge_id
    route = choose_route(chall.category, config["routing"])
    if not route:
        log_warn(f"Skipping unsupported category [{chall.category}] :: {chall.name}")
        return {"status": "skipped", "challenge_id": cid}

    model_key = resolve_model_key(route, chall.category, config.get("models", {}))
    if not model_key:
        log_warn(f"No configured model for route '{route}' :: {chall.name}")
        return {"status": "skipped", "challenge_id": cid}
    model_cfg = config["models"][model_key]
    runner_cmd = model_cfg["runner"]
    prompt_template = root / model_cfg["prompt_template"]

    chdir = challenge_workspace(root, config, chall)
    rounds_dir = chdir / "agent_rounds"
    files_dir = chdir / "files"
    ensure_dirs(chdir, rounds_dir, files_dir)

    lock_path = chdir / ".lock"
    if not acquire_lock(lock_path):
        return {"status": "locked", "challenge_id": cid}

    try:
        db.mark_seen(chall, str(chdir), route, "queued")
        (chdir / "challenge.json").write_text(json.dumps(asdict(chall), indent=2), encoding="utf-8")

        # Download Attachments (delegated to the platform adapter)
        if chall.files:
            try:
                platform.download_files(chall, str(files_dir))
            except Exception as e:  # noqa: BLE001
                log_err(f"Download failed for #{cid}: {redact(str(e))}")

        # Instance preparation (HTB Docker / Fullpwn). Static challenges no-op.
        if auto_start and platform.needs_instance(chall):
            inst_lock = chdir / "instance.lock"
            if acquire_lock(inst_lock):
                try:
                    chall = instance_manager.prepare_target(
                        platform, chall, chdir, config, logger=_AdaptLogger(), wait=True
                    )
                finally:
                    release_lock(inst_lock)
        else:
            instance_manager.write_target(chall, chdir, started_by_koshary=False)

        # Planning Phase
        plan_txt = "No plan generated."
        if enable_planning:
            plan_txt = generate_challenge_plan(chall, runner_cmd, chdir, timeout=override_timeout or config["ctf"].get("model_timeout", 300), walkthrough=walkthrough)
            log_ok(f"Strategy formulated for #{cid}")

        # DNS Helper logic
        dns_hints = []
        all_text_for_dns = f"{chall.description} {chall.connection_info or ''}"
        potential_hosts = re.findall(r"([a-z0-9]+(?:\.[a-z0-9\-]+)+)", all_text_for_dns.lower())
        for h in set(potential_hosts):
            if "." in h and not h.replace(".", "").isdigit():
                ip = resolve_host(h)
                if ip:
                    dns_hints.append(f"{h} -> {ip}")

        env_with_dns = env_info
        if dns_hints:
            log_ok(f"Resolved DNS Hints for #{cid}: {Fore.YELLOW}{', '.join(dns_hints)}{Style.RESET_ALL}")
            env_with_dns += "\nResolved hostnames for your convenience: " + ", ".join(dns_hints)

        htb_prefix = build_htb_context(root, chall)

        db.mark_status(cid, "running")
        last_workspace_hash = None
        idle_rounds = 0
        solved = False

        max_rounds = config["ctf"].get("max_agent_rounds", 8)
        max_idle_rounds = config["ctf"].get("max_idle_rounds", 3)
        model_timeout = override_timeout or config["ctf"].get("model_timeout", 300)

        for round_no in range(1, max_rounds + 1):
            log_step(f"Round {round_no}/{max_rounds} :: #{cid} {chall.name}")
            db.inc_stat("model_rounds", 1)

            # Refresh instance status / target.json before each round.
            if platform.needs_instance(chall):
                instance_manager.refresh_target(platform, chall, chdir, logger=_AdaptLogger())
                htb_prefix = build_htb_context(root, chall)

            workspace_text = collect_workspace_text(chdir)
            history_text = collect_history_text(chdir, round_no)

            workspace_hash = sha1_text(workspace_text)
            if workspace_hash == last_workspace_hash:
                idle_rounds += 1
                if idle_rounds >= max_idle_rounds:
                    log_warn(f"Challenge #{cid} stalled (no workspace changes). Terminating.")
                    break
            else: idle_rounds = 0
            last_workspace_hash = workspace_hash

            prompt = render_prompt(prompt_template, chall, chdir, round_no, workspace_text[:20000], history_text[:20000], env_info=env_with_dns, plan=plan_txt, walkthrough_active=walkthrough, prefix=htb_prefix)
            prompt_file = rounds_dir / f"round_{round_no:02d}.prompt.txt"
            prompt_file.write_text(prompt, encoding="utf-8")

            # Agent Execution
            try:
                rc, output = run_model(runner_cmd, prompt_file, chdir, timeout=model_timeout)

                # Extract from RAW output
                lang, code = extract_first_code_block(output)
                run_commands = extract_run_commands(output)

                cleaned_output = clean_model_output(output)

                out_file = rounds_dir / f"round_{round_no:02d}.out.txt"
                out_file.write_text(cleaned_output, encoding="utf-8")
                combined_text = cleaned_output

                # RUN Commands
                if run_commands:
                    cmd_results = run_model_commands(run_commands, chdir, timeout=config["ctf"].get("command_timeout", 90), env=exec_env)
                    db.inc_stat("commands_executed", len(cmd_results))
                    combined_text += "\n" + "\n".join([r[2] for r in cmd_results])
                    (rounds_dir / f"round_{round_no:02d}.commands.txt").write_text("\n\n".join([f"$ {r[0]}\n{r[2]}" for r in cmd_results]))

                # Artifact Execution
                if code:
                    artifact_path = save_generated_artifact(chdir, round_no, lang or "", code)
                    exec_rc, exec_output = run_generated_artifact(artifact_path, timeout=config["ctf"].get("artifact_timeout", 240), env=exec_env)
                    db.inc_stat("artifacts_executed", 1)
                    (rounds_dir / f"round_{round_no:02d}.exec.txt").write_text(exec_output, encoding="utf-8")
                    combined_text += "\n" + exec_output

                # Flag Detection & Submission
                candidates = list(extract_flags(combined_text, config["ctf"]["flag_patterns"]))
                if allow_nonstandard:
                    candidates += [c.value for c in extract_candidate_answers(combined_text)]

                if _solve_with_candidates(chall, candidates, platform, db, chdir, submit_mode, max_wrong):
                    solved = True

                if solved:
                    break

            except subprocess.TimeoutExpired:
                log_err(f"Model timeout on #{cid}, round {round_no}")
            except Exception as e:
                log_err(f"Agent error on #{cid}, round {round_no}: {redact(str(e))}")

        if solved and auto_stop and platform.needs_instance(chall):
            instance_manager.teardown_target(platform, chall, chdir, logger=_AdaptLogger())

        if not solved:
            db.mark_status(cid, "failed")
        return {"status": "solved" if solved else "done", "challenge_id": cid}
    finally:
        release_lock(lock_path)


class _AdaptLogger:
    """Adapter so instance_manager (which expects .info/.warn/.err) can use the
    orchestrator's colourful console logger."""

    def info(self, msg: str) -> None:
        log_info(redact(str(msg)))

    def ok(self, msg: str) -> None:
        log_ok(redact(str(msg)))

    def warn(self, msg: str) -> None:
        log_warn(redact(str(msg)))

    def err(self, msg: str) -> None:
        log_err(redact(str(msg)))

    def debug(self, msg: str) -> None:
        log_dbg(redact(str(msg)))


def _solve_with_candidates(chall: Challenge, candidates: List[str], platform: BasePlatform,
                           db: StateDB, chdir: Path, submit_mode: str, max_wrong: int) -> bool:
    """Try each candidate flag/answer. Returns True if the challenge is solved."""
    cid = chall.challenge_id
    for flag in candidates:
        if db.attempted_flag(cid, flag):
            continue

        if submit_mode == "none":
            log_warn(f"Flag detected for #{cid} [--no-submit]: {flag}")
            record_submission(chdir, flag, accepted=False, message="submission disabled")
            continue
        if submit_mode == "manual":
            log_ok(f"Candidate flag for #{cid} [--manual-submit, NOT submitted]: {flag}")
            record_submission(chdir, flag, accepted=False, message="manual submit pending")
            db.mark_attempt(cid, flag, {"manual": True})
            continue

        if max_wrong > 0 and db.count_attempts(cid) >= max_wrong:
            log_warn(f"Wrong-submission limit ({max_wrong}) reached for #{cid}; not submitting '{flag}'.")
            return False

        log_step(f"Attempting flag submission for #{cid}: {flag}")
        try:
            result = platform.submit_flag(chall, flag)
        except Exception as e:  # noqa: BLE001
            log_err(f"Submission error for #{cid}: {redact(str(e))}")
            db.mark_attempt(cid, flag, {"error": str(e)})
            continue

        record_submission(chdir, flag, accepted=result.accepted, message=result.message)
        if result.accepted:
            _p(BANNER_CORRECT)
            log_ok(f"SOLVED: #{cid} {chall.name} Flag: {flag}")
            db.mark_solved(cid, flag, result.raw)
            return True
        log_warn(f"Submission rejected for #{cid}: {flag} ({redact(result.message)})")
        db.mark_attempt(cid, flag, result.raw)
    return False


# =========================
# Main Entry Point
# =========================
def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Koshary multi-platform CTF orchestrator")
    # Platform selection
    parser.add_argument("--platform", choices=["ctfd", "htb_ctf", "htb_cookie"], help="Source platform (default: config.platform or ctfd)")
    parser.add_argument("--event", help="HTB MCP event id/slug (overrides config.htb.event)")
    # HTB cookie/bearer mode
    parser.add_argument("--ctf-id", type=int, help="HTB cookie-mode CTF event id (overrides config.htb_cookie.ctf_id)")
    parser.add_argument("--headers-file", help="HTB cookie-mode: raw request file holding Cookie/Authorization")
    parser.add_argument("--challenge-id", help="Operate on a single challenge id (start/stop/submit/solve)")
    parser.add_argument("--submit-candidate", help="Submit this flag for --challenge-id, then exit")
    parser.add_argument("--stop-instance", action="store_true", help="Stop the instance for --challenge-id, then exit")
    # CTFd
    parser.add_argument("--url", help="CTFd base URL")
    parser.add_argument("--session", help="CTFd session cookie")
    # Common
    parser.add_argument("--categories", help="Comma-separated categories to include")
    parser.add_argument("--parallel", type=int, help="Number of parallel workers")
    parser.add_argument("--flag-format", help="Specific flag regex pattern")
    parser.add_argument("--venv", help="Path to python virtual environment")
    parser.add_argument("--plan", action="store_true", help="Enable strategic planning phase")
    parser.add_argument("--timeout", type=int, help="Override default model timeout (seconds)")
    parser.add_argument("--walkthrough", action="store_true", help="Request agent to write walkthrough.md upon success")
    # Submission control
    parser.add_argument("--no-submit", action="store_true", help="Never submit flags to the platform")
    parser.add_argument("--manual-submit", action="store_true", help="Print candidate flags instead of submitting")
    parser.add_argument("--max-wrong", type=int, help="Max wrong submissions per challenge (0 = unlimited)")
    parser.add_argument("--allow-nonstandard-flags", action="store_true", help="Allow submitting non-regex FINAL_ANSWER_CANDIDATE values")
    # Instance control
    parser.add_argument("--no-auto-start", action="store_true", help="Do not auto-start HTB instances")
    parser.add_argument("--auto-stop", action="store_true", help="Stop HTB instance after a solve")
    parser.add_argument("--stop-on-solve", action="store_true", help="Alias for --auto-stop")
    parser.add_argument("--start-only", action="store_true", help="Sync + start instances, then exit")
    # Read-only / utility modes
    parser.add_argument("--list-events", action="store_true", help="List HTB events and exit")
    parser.add_argument("--list-challenges", action="store_true", help="List challenges and exit")
    parser.add_argument("--sync-only", action="store_true", help="Create local workspaces, then exit")
    parser.add_argument("--download", action="store_true", help="Download attachments during sync")
    parser.add_argument("--scoreboard", action="store_true", help="Print scoreboard and exit")
    parser.add_argument("--strategy", action="store_true", help="Print a ranked solve queue and exit")
    return parser


def resolve_submit_mode(args, platform_name: str, config: Dict[str, Any]) -> str:
    if args.no_submit:
        return "none"
    if args.manual_submit:
        return "manual"
    if platform_name == "ctfd":
        return "auto" if config["ctf"].get("auto_submit", False) else "none"
    return "auto"


def strategy_rank(challenges: List[Challenge], db: StateDB) -> List[Tuple[float, Challenge]]:
    """Phase 10 - rank challenges by a simple heuristic score."""
    ranked = []
    for c in challenges:
        points = c.points or 0
        has_files = 1 if c.files else 0
        kind_bonus = {"static": 2, "docker": 1, "fullpwn": 0}.get(c.target_kind, 0)
        failed = db.count_attempts(c.challenge_id)
        score = points + (40 * has_files) + (25 * kind_bonus) - (30 * failed)
        ranked.append((score, c))
    ranked.sort(key=lambda x: x[0], reverse=True)
    return ranked


def sync_workspace(root: Path, config: Dict[str, Any], platform: BasePlatform,
                   chall: Challenge, download: bool, db: StateDB) -> Path:
    chdir = challenge_workspace(root, config, chall)
    ensure_dirs(chdir, chdir / "agent_rounds", chdir / "files")
    (chdir / "challenge.json").write_text(json.dumps(asdict(chall), indent=2), encoding="utf-8")
    instance_manager.write_target(chall, chdir, started_by_koshary=False)
    db.mark_seen(chall, str(chdir), choose_route(chall.category, config["routing"]) or "?", "synced")
    if download and chall.files:
        try:
            platform.download_files(chall, str(chdir / "files"))
        except Exception as e:  # noqa: BLE001
            log_err(f"Download failed for {chall.name}: {redact(str(e))}")
    return chdir


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()

    root = Path(".").resolve()
    load_env(root / ".env")
    config = load_json(root / "config.json")

    platform_name = (args.platform or config.get("platform") or "ctfd").lower()
    config["platform"] = platform_name
    config.setdefault("htb", {})
    config.setdefault("htb_cookie", {})

    # CLI Overrides
    if args.url:
        config["ctf"]["base_url"] = args.url.rstrip("/")
    if args.event:
        config["htb"]["event"] = args.event
    if args.ctf_id:
        config["htb_cookie"]["ctf_id"] = args.ctf_id
    if args.headers_file:
        config["htb_cookie"]["headers_file"] = args.headers_file
    if args.categories:
        config["ctf"]["include_categories"] = [c.strip().lower() for c in args.categories.split(",")]
    if args.parallel:
        config["ctf"]["parallel_workers"] = args.parallel
    if args.flag_format and args.flag_format not in config["ctf"]["flag_patterns"]:
        config["ctf"]["flag_patterns"].insert(0, args.flag_format)

    # HTB always recognises HTB{...}/CHTB{...}
    if platform_name in ("htb_ctf", "htb_cookie"):
        from core.flag_extractor import HTB_DEFAULT_PATTERNS
        for pat in HTB_DEFAULT_PATTERNS:
            if pat not in config["ctf"]["flag_patterns"]:
                config["ctf"]["flag_patterns"].append(pat)

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

    db = StateDB(root / config["workspace"]["state_file"])
    db.inc_stat("runs", 1)
    _p(SPLASH)

    # ------------------------------------------------------------------ #
    # Build the platform adapter
    # ------------------------------------------------------------------ #
    try:
        if platform_name == "ctfd":
            session = args.session or os.getenv("CTFD_SESSION", "").strip()
            if not session:
                log_err("Authentication failure: Missing CTFD_SESSION.")
                return 1
            platform = get_platform("ctfd", config, session=session)
        elif platform_name == "htb_cookie":
            cookie = os.getenv("HTB_CTF_COOKIE", "").strip()
            bearer = os.getenv("HTB_CTF_BEARER", "").strip()
            headers_file = config["htb_cookie"].get("headers_file")
            if not cookie and not bearer and not headers_file:
                log_err("Authentication failure: set HTB_CTF_COOKIE / HTB_CTF_BEARER in .env "
                        "or pass --headers-file.")
                return 1
            register_secret(cookie)
            register_secret(bearer)
            platform = get_platform("htb_cookie", config)
            # Best-effort access validation via the menu endpoint.
            try:
                can_view, menu = platform.client.validate_access()  # type: ignore[attr-defined]
                if can_view:
                    log_ok(f"Access validated: {menu.get('name', 'event')} [{menu.get('status', '?')}]")
                else:
                    log_warn("Session cannot view challenges (userCanViewChallenges=false). "
                             "Make sure you've joined this event in the browser.")
            except Exception as e:  # noqa: BLE001
                log_warn(f"Access validation skipped: {redact(str(e))}")
        else:
            token = os.getenv("HTB_MCP_TOKEN", "").strip()
            if not token:
                log_err("Authentication failure: Missing HTB_MCP_TOKEN in .env.")
                return 1
            register_secret(token)
            platform = get_platform("htb_ctf", config)
    except Exception as e:  # noqa: BLE001
        log_err(f"Platform initialization failed: {redact(str(e))}")
        return 1

    if platform_name == "htb_ctf":
        label = config.get("htb", {}).get("event")
    elif platform_name == "htb_cookie":
        label = config.get("htb_cookie", {}).get("ctf_id")
    else:
        label = config["ctf"].get("name")
    log_step(f"Platform: {platform_name} :: {label or 'Competition'}")

    # ------------------------------------------------------------------ #
    # Single-challenge utility actions (stop / submit one challenge, then exit)
    # ------------------------------------------------------------------ #
    if args.stop_instance or args.submit_candidate:
        if not args.challenge_id:
            log_err("--stop-instance / --submit-candidate require --challenge-id.")
            return 1
        try:
            chall = platform.get_challenge(str(args.challenge_id))
        except Exception as e:  # noqa: BLE001
            log_err(f"Could not load challenge {args.challenge_id}: {redact(str(e))}")
            return 1
        if args.stop_instance:
            try:
                platform.stop_instance(chall)
                log_ok(f"Stop requested for #{chall.challenge_id} {chall.name}")
            except Exception as e:  # noqa: BLE001
                log_err(f"Stop failed: {redact(str(e))}")
                return 1
            return 0
        # --submit-candidate
        chdir = challenge_workspace(root, config, chall)
        ensure_dirs(chdir)
        try:
            result = platform.submit_flag(chall, args.submit_candidate)
        except Exception as e:  # noqa: BLE001
            log_err(f"Submission error: {redact(str(e))}")
            return 1
        record_submission(chdir, args.submit_candidate, result.accepted, result.message)
        if result.accepted:
            _p(BANNER_CORRECT)
            log_ok(f"SOLVED: #{chall.challenge_id} {chall.name}")
            db.mark_solved(chall.challenge_id, args.submit_candidate, result.raw)
            return 0
        log_warn(f"Submission rejected for #{chall.challenge_id}: {redact(result.message)}")
        db.mark_attempt(chall.challenge_id, args.submit_candidate, result.raw)
        return 2

    # ------------------------------------------------------------------ #
    # Read-only / utility modes (early exit)
    # ------------------------------------------------------------------ #
    if args.list_events:
        if not isinstance(platform, BasePlatform) or not hasattr(platform, "list_events"):
            log_err("--list-events is only supported for htb_ctf.")
            return 1
        try:
            events = platform.list_events()  # type: ignore[attr-defined]
        except Exception as e:  # noqa: BLE001
            log_err(f"Could not list events: {redact(str(e))}")
            return 1
        log_ok(f"Found {len(events)} event(s):")
        for ev in events:
            name = ev.get("name") or ev.get("title") or "?"
            slug = ev.get("slug") or ev.get("id") or ev.get("event_id") or "?"
            _p(f"  - {slug}  ::  {name}")
        return 0

    if args.scoreboard:
        try:
            board = platform.get_scoreboard()
        except Exception as e:  # noqa: BLE001
            log_err(f"Could not fetch scoreboard: {redact(str(e))}")
            return 1
        log_ok(f"Scoreboard ({len(board)} rows):")
        for i, row in enumerate(board[:25], 1):
            _p(f"  {i:>3}. {redact(json.dumps(row))[:120]}")
        return 0

    # ------------------------------------------------------------------ #
    # List challenges
    # ------------------------------------------------------------------ #
    available_models = check_model_availability(config)
    try:
        challenges = platform.list_challenges()
        log_ok(f"Retrieved {len(challenges)} challenges from {platform_name}.")
    except Exception as e:  # noqa: BLE001
        log_err(f"Network/MCP error while listing challenges: {redact(str(e))}")
        return 1

    cat_inc = set(x.lower() for x in config["ctf"].get("include_categories", []))
    eligible: List[Challenge] = []

    _p("\n" + "=" * 92)
    _p(f"{'ID':<10} | {'Challenge Name':<32} | {'Category':<14} | {'Kind':<8} | {'Status'}")
    _p("-" * 92)
    for c in challenges:
        cid = c.challenge_id
        solved = c.solved or str(cid) in {str(x) for x in db.data.get("solved_ids", [])}
        if c.solved and str(cid) not in {str(x) for x in db.data.get("solved_ids", [])}:
            db.data["solved_ids"].append(cid)
            db.save()

        status = "SOLVED" if solved else "OPEN"
        route = choose_route(c.category, config["routing"])

        included = True
        if cat_inc and not any(category_matches_filter(c.category, x, config["routing"]) for x in cat_inc):
            included = False
        if not route:
            included = False
            if status == "OPEN":
                status = "UNSUPPORTED"
        elif route not in available_models:
            included = False
            if status == "OPEN":
                status = f"MODEL MISSING ({route})"

        _p(f"{str(cid)[:10]:<10} | {c.name[:32]:<32} | {c.category[:14]:<14} | {c.target_kind[:8]:<8} | {status}")

        if status == "OPEN" and included:
            # Enrich with full detail when the summary lacks description/files.
            detail = c
            if not c.description and not c.files:
                try:
                    detail = platform.get_challenge(cid)
                except Exception as e:  # noqa: BLE001
                    log_warn(f"Detail fetch failed for {c.name}: {redact(str(e))}")
            eligible.append(detail)
    _p("=" * 92 + "\n")

    # Strategy ranking (read-only).
    if args.strategy:
        log_ok("Recommended solve queue:")
        for i, (score, c) in enumerate(strategy_rank(eligible, db), 1):
            _p(f"  {i}. {c.name} / {c.category} / {c.points or 0} pts / {c.target_kind}"
               f" / {'has files' if c.files else 'no files'}  (score={score:.0f})")
        return 0

    # Explicit single-challenge selection bypasses category/solved filtering.
    if args.challenge_id:
        match = next((c for c in challenges if str(c.challenge_id) == str(args.challenge_id)), None)
        if not match:
            log_err(f"Challenge {args.challenge_id} not found in this event.")
            return 1
        try:
            match = platform.get_challenge(str(args.challenge_id))
        except Exception:  # noqa: BLE001
            pass
        eligible = [match]

    if not eligible:
        log_warn("No pending challenges matched the inclusion criteria.")
        return 0

    # Sync-only: write workspaces (and optionally download) then exit.
    if args.sync_only or args.list_challenges:
        for c in eligible:
            chdir = sync_workspace(root, config, platform, c, download=args.download, db=db)
            log_ok(f"Synced {c.name} -> {chdir}")
        return 0

    # Start-only: sync + start instances, then exit.
    if args.start_only:
        for c in eligible:
            chdir = sync_workspace(root, config, platform, c, download=args.download, db=db)
            if platform.needs_instance(c):
                instance_manager.prepare_target(platform, c, chdir, config, logger=_AdaptLogger(), wait=True)
        log_ok("Instances prepared.")
        return 0

    # ------------------------------------------------------------------ #
    # Solve
    # ------------------------------------------------------------------ #
    submit_mode = resolve_submit_mode(args, platform_name, config)
    pcfg = config.get("htb_cookie", {}) if platform_name == "htb_cookie" else config.get("htb", {})
    auto_start = (not args.no_auto_start) and pcfg.get("auto_start_instances", True)
    auto_stop = args.auto_stop or args.stop_on_solve or pcfg.get("auto_stop_on_solve", False)
    if args.max_wrong is not None:
        max_wrong = args.max_wrong
    elif platform_name in ("htb_ctf", "htb_cookie"):
        max_wrong = pcfg.get("max_wrong_submissions_per_challenge", 3)
    else:
        max_wrong = 0  # CTFd: unlimited, preserving original behaviour
    allow_nonstandard = args.allow_nonstandard_flags or pcfg.get("allow_nonstandard_flags", False)

    workers = max(1, int(config["ctf"].get("parallel_workers", 3)))
    if any(c.target_kind == "fullpwn" for c in eligible) and not args.parallel:
        workers = 1  # Fullpwn is stateful/VPN-bound; default to serial.

    log_info(f"Deploying agents to {len(eligible)} challenge(s) "
             f"[submit={submit_mode}, workers={workers}, auto_start={auto_start}].")

    with futures.ThreadPoolExecutor(max_workers=workers) as executor:
        fmap = {
            executor.submit(
                process_challenge, chall, config, db, platform, root, exec_env, env_info,
                args.plan, args.timeout, args.walkthrough, submit_mode, auto_start,
                auto_stop, max_wrong, allow_nonstandard,
            ): chall
            for chall in eligible
        }
        for fut in futures.as_completed(fmap):
            chall = fmap[fut]
            try:
                res = fut.result()
                log_ok(f"Process terminated for #{chall.challenge_id} {chall.name}: {res['status']}")
            except Exception as e:  # noqa: BLE001
                log_err(f"Worker failure for #{chall.challenge_id}: {redact(str(e))}")

    with contextlib.suppress(Exception):
        platform.close()
    log_step("Mission complete. Solved: " + str(len(db.data.get("solved_ids", []))))
    return 0


if __name__ == "__main__":
    try: raise SystemExit(main())
    except KeyboardInterrupt:
        log_warn("Process interrupted by user.")
        raise SystemExit(130)
