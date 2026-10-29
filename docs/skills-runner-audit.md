# Skills and runner audit

Scope: repository category and HTB prompts, category routing, planning, Codex/Claude/Gemini runner scripts, prompt rendering, output and execution paths. This is a static review; solving effectiveness has not been benchmarked.

## Category guidance

| Category | Current guidance | Recommended on-demand reference |
| --- | --- | --- |
| Web | Map trust boundaries and test observed hypotheses | ctf-skills/ctf-web |
| Pwn | Mitigations, primitive and local validation | ctf-skills/ctf-pwn |
| Reverse | Trace input and validate using REA/IDA/Ghidra | REA plus ctf-skills/ctf-reverse |
| Crypto | Identify construction and test a mathematical hypothesis | ctf-skills/ctf-crypto |
| Forensics | Preserve original artifacts and trace evidence | ctf-skills/ctf-forensics |
| Mobile | Manifest, code, resources; runtime when needed | REA and ctf-skills/ctf-reverse |
| Misc | Triage before choosing a specialist | ctf-skills/ctf-misc |
| Fullpwn | Host-scoped enumeration, log attack path | Existing fullpwn instructions |
| Hardware/blockchain | Dedicated triage and verification guidance | Evaluate specialist references separately |

External reference candidate: https://github.com/ljagiello/ctf-skills at commit `2388a3bcd5f081836c9a038c54e26bc658d5b7d1`, MIT license. Category SKILL.md files are 16–42 KB and link to further material; they contain package installation commands. Six category directories of Markdown references are vendored under `references/ctf-skills` with the upstream MIT license. Scripts and non-Markdown files are not included; some upstream references may therefore point to unavailable helpers. The default `ctf.reference_root` exposes a category path to agent-owned runners without inlining the material. The collection has not been audited line by line; do not execute its installation commands automatically. REA 6.8.0 is already configured locally; no Koshary child-session integration test has been completed.

## Runner and prompt observations

- Category prompt selection is independent of provider; routing prefers the most specific configured substring. Category detection remains heuristic and ambiguous hybrid challenges need explicit routing support.
- Codex and Claude use agent-owned execution by default; generated commands and code are ignored unless the runner explicitly chooses orchestrator ownership. HTB system prompts no longer request incompatible RUN output.
- Runner model and effort are environment overrides, not per-category config. Both runners use one selected model and do not automatically retry a different one. Gemini remains a legacy runner but no default route selects it.
- Structured output is an agent assertion, not independent flag verification. Missing or malformed results are rejected for submission unless legacy fallback is explicitly enabled.
- Context is bounded to an inventory and the latest three structured results for agent-owned sessions. Older findings may be lost unless recorded in workspace files; output character bounds are not token budgets.
- Optional planning consumes an extra model call. Execution timeout stops a challenge without an automatic retry; error categories remain coarse.
- Existing runners grant broad agent execution permissions. Their working directory is not a security sandbox. Runtime dependencies and REA access depend on the user's environment.

## Next evaluation

Benchmark a pinned challenge set across categories and both runners, track solve rate, elapsed time, input/output tokens where available, and verify failures. Compare short prompts with selectively retrieved external sections before adopting them. Inspect every imported reference, pin its revision, and preserve its license. No claims of token savings or stronger solving are established without this evaluation.

## Alternatives reviewed

- `naravid19/claude-ctf-skills` packages the same upstream material as a Claude plugin, adding a solver agent. Koshary already orchestrates agents, so using the upstream references avoids another orchestration layer.
- `nonoleekr/CTF-Agent` uses separate auto-triggered skills and a methodology router. Its automatic discovery depends on agent session and working directory; Koshary uses explicit category paths instead.
- REA provides analysis tools rather than a replacement for category methodology. Its native integration is configured separately.

Public sources do not establish which specific skill packs top-ranked CTF teams use, or that these references improve solve rates. No such claim is made.

## Six-category selection review (2026-10-29)

Selected `ljagiello/ctf-skills` for each category as the strongest candidate for coverage and standalone reference structure, not as a benchmark-proven winner:

| Category | Installed entrypoint | Selection rationale |
| --- | --- | --- |
| Web | `ctf-web/SKILL.md` | Broad HTTP and browser vulnerability index with separate technique notes. |
| Pwn | `ctf-pwn/SKILL.md` | Covers protections, memory corruption, exploitation primitives and references. |
| Reverse | `ctf-reverse/SKILL.md` | Covers native binaries, bytecode and platform-specific reverse engineering; REA adds analysis tooling. |
| Crypto | `ctf-crypto/SKILL.md` | Covers asymmetric, symmetric, PRNG and mathematical approaches with references. |
| Forensics | `ctf-forensics/SKILL.md` | Covers disk, memory, captures and media analysis. |
| Misc | `ctf-misc/SKILL.md` | Covers puzzles, encodings, jails and other cross-category techniques. |

Compared with `naravid19/claude-ctf-skills` commit `d3096bc24d053dfe40f1ca4042004cfce46d0945`, which repackages the same upstream category material and adds Claude orchestration. `nonoleekr/CTF-Agent` commit `0cbb136429a499ee586da468425d0a45132970e2` has shorter entrypoints (~2–3 KB), but they depend on that project's `knowledge/` and tool scripts; its approach is useful for future prompt design. No independent head-to-head solving or token benchmarks were found. These facts are not proof that any option is best at solving.

The six installed entrypoints and all 162 vendored Markdown files were byte-compared with the upstream checkout at the pinned revision; there were no mismatches. The references are supplied to Koshary's agent-owned runners as explicit on-demand paths, not installed as global auto-discovered Claude or Codex skills. Source instructions are third-party content, and their installation commands and helpers are not automatically run.
