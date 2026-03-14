# Koshary Framework (BETA VERSION)

An autonomous multi-agent framework designed for solving CTFd-hosted Capture The Flag competitions.
 The system leverages large language models (LLMs) to analyze challenges, generate exploits, and execute them in a sandboxed environment.

## Architectural Overview

The orchestrator follows a structured lifecycle for each challenge:
1. **Discovery**: Fetches challenge metadata and attachments via the CTFd API.
2. **Planning**: An LLM analyzes the challenge description and files to formulate a high-level strategy.
3. **Execution Loop**: Autonomous agents attempt to solve the challenge across multiple rounds.
4. **Environment Interaction**: Scripts are executed within a configured Python virtual environment.
5. **Validation**: Automated flag detection and submission with CSRF synchronization.

## System Requirements

- Python 3.8+
- CTFd Session Cookie (provided via `.env` or CLI)
- Gemini CLI and/or Codex CLI installed in PATH
- Optional: Python Virtual Environment (for pwntools/crypto dependencies)

## Installation

```bash
pip install requests colorama
# Ensure gemini and codex CLIs are authenticated and functional
```

## Usage

### Environment Setup
Create a `.env` file in the project root:
```env
CTFD_SESSION=your_session_cookie_here
```

### Running the Orchestrator
```bash
python3 orchestrator.py --url https://ctf.example.com --categories "Web,Crypto" --parallel 2
```

### Advanced Options
- `--venv`: Path to a virtual environment containing specialized tools (e.g., `~/CTF-env`).
- `--plan`: Enables the pre-solving planning phase for more effective agents.
- `--timeout`: Sets the maximum runtime (seconds) for each model call.
- `--flag-format`: Provides a regex pattern to improve flag detection accuracy.

## Utilities

### First Blood Utility
The `first_blood.py` script is designed to be executed immediately before a competition starts. It continuously polls the CTFd API and, as soon as challenges are released, automatically extracts and submits flags for introductory and social challenges.

**Key Features:**
- **Continuous Polling**: Monitors the API until it becomes public.
- **Flag Override**: Submit a known flag (e.g., from Rules/Discord) to all matching challenges automatically.
- **Auto-Extraction**: Scans descriptions for flag patterns if no override is provided.

```bash
# Standard usage (polls every 10s)
python3 first_blood.py

# High-frequency polling with a known override flag
python3 first_blood.py --flag "ctf{welcome_2026}" --interval 2
```

## Directory Structure

- `challenges/`: Workspace for each challenge, containing artifacts and round logs.
- `prompts/`: System instructions for different challenge categories.
- `runners/`: Shell wrappers for the underlying LLM CLIs.
- `state/`: Persistent database (`db.json`) tracking solves and errors.

## Execution Environment
The orchestrator supports a dedicated execution environment. When a `--venv` is provided, all generated scripts and shell commands are executed with the virtual environment's `bin` directory prepended to the `PATH`. This allows agents to seamlessly utilize libraries like `pwntools`, `pycryptodome`, and `requests`.
