"""
Flag and candidate-answer extraction shared by all platforms.

Standard CTF flags are matched by regex. HTB challenges occasionally accept a
non-standard answer (a CVE id, a password, a number); the solver can surface
those with a ``FINAL_ANSWER_CANDIDATE:`` line which we parse separately and only
act on when explicitly allowed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List

# Default HTB flag patterns. Kept conservative to avoid matching prose.
# The leading boundary stops ``HTB{...}`` from also matching inside ``CHTB{...}``.
HTB_DEFAULT_PATTERNS = [
    r"(?<![A-Za-z])HTB\{[^}\n\r]{1,300}\}",
    r"(?<![A-Za-z])CHTB\{[^}\n\r]{1,300}\}",
]


# Obvious example/placeholder flags that models echo from prompts or templates.
_PLACEHOLDER_INNER = {
    "...", "…", "..", ".", "flag", "flag_here", "flag_goes_here", "your_flag",
    "example", "redacted", "xxx", "xxxx", "text", "...}",
}


def is_placeholder_flag(flag: str) -> bool:
    """True for example flags like ``HTB{...}`` / ``flag{FLAG_HERE}``."""
    m = re.match(r"^[A-Za-z0-9]+\{(.*)\}$", flag, re.DOTALL)
    inner = (m.group(1) if m else flag).strip().lower()
    if not inner:
        return True
    if inner in _PLACEHOLDER_INNER:
        return True
    # Inner consists only of dots / ellipses / placeholder punctuation.
    if re.fullmatch(r"[.…\s_]+", inner):
        return True
    return False


def extract_flags(text: str, patterns: List[str]) -> List[str]:
    """Return de-duplicated flags found in ``text`` (order preserved).

    Obvious placeholder/example flags are dropped so they never get submitted.
    """
    found: List[str] = []
    for pat in patterns:
        try:
            found.extend(re.findall(pat, text, flags=re.IGNORECASE))
        except re.error:
            # Skip a malformed user-supplied pattern rather than crash.
            continue
    # findall with groups may return tuples; normalize to strings.
    flat: List[str] = []
    for item in found:
        if isinstance(item, tuple):
            item = next((p for p in item if p), "")
        if item and not is_placeholder_flag(item):
            flat.append(item)
    return list(dict.fromkeys(flat))


@dataclass
class CandidateAnswer:
    value: str
    confidence: str = "unknown"
    evidence: str = ""


def extract_candidate_answers(text: str) -> List[CandidateAnswer]:
    """Parse ``FINAL_ANSWER_CANDIDATE:`` blocks emitted by the solver.

    Recognised lines (case-insensitive)::

        FINAL_ANSWER_CANDIDATE: CVE-2024-1234
        CONFIDENCE: high
        EVIDENCE: ...
    """
    candidates: List[CandidateAnswer] = []
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        m = re.match(r"\s*FINAL_ANSWER_CANDIDATE\s*:\s*(.+?)\s*$", line, re.IGNORECASE)
        if not m:
            continue
        value = m.group(1).strip().strip("`'\"")
        confidence = "unknown"
        evidence = ""
        # Look at the next few lines for metadata.
        for follow in lines[idx + 1 : idx + 5]:
            cm = re.match(r"\s*CONFIDENCE\s*:\s*(.+?)\s*$", follow, re.IGNORECASE)
            em = re.match(r"\s*EVIDENCE\s*:\s*(.+?)\s*$", follow, re.IGNORECASE)
            if cm:
                confidence = cm.group(1).strip().lower()
            elif em:
                evidence = em.group(1).strip()
        if value:
            candidates.append(CandidateAnswer(value=value, confidence=confidence, evidence=evidence))
    # De-duplicate by value, keeping first occurrence.
    seen: set[str] = set()
    out: List[CandidateAnswer] = []
    for c in candidates:
        if c.value not in seen:
            seen.add(c.value)
            out.append(c)
    return out
