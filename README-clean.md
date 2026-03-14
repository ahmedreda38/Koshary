
# Workspace Cleanup Script

clean_workspace.py resets the project workspace so you can start a new CTF run.

---

# Purpose

Removes generated directories such as:

challenges/
state/
logs
cache

while optionally keeping configuration and scripts.

---

# Basic Usage

python3 clean_workspace.py

The script will show a cleanup plan and ask for confirmation.

---

# Example Output

[*] Cleanup plan
 - challenges/
 - state/

Proceed? [y/N]

---

# Non‑interactive Mode

python3 clean_workspace.py --yes

---

# Preview Mode

python3 clean_workspace.py --dry-run

Shows what would be removed without deleting anything.

---

# Keep Important Files

Keep configuration

python3 clean_workspace.py --keep-config

Keep prompts

python3 clean_workspace.py --keep-prompts

Keep runners

python3 clean_workspace.py --keep-runners

---

# Recommended Reset Command

python3 clean_workspace.py \
  --keep-config \
  --keep-prompts \
  --keep-runners \
  --yes

Removes:

challenges  
state  
logs

Keeps:

config.json  
prompts/  
runners/

---

# When To Use

Use the cleanup script when:

- starting a new CTF
- restarting experiments
- clearing corrupted workspace
- resetting AI solving runs

---

# Warning

Cleanup permanently deletes directories.

Always run with --dry-run first if unsure.
