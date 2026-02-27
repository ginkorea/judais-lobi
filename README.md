# 🧠 judais-lobi

> Artifact-driven. Capability-gated. GPU-aware.
> Not a chatbot. A kernel.

---

[![PyPI](https://img.shields.io/pypi/v/judais-lobi?color=blue\&label=PyPI)](https://pypi.org/project/judais-lobi/)
[![Python](https://img.shields.io/pypi/pyversions/judais-lobi.svg)](https://pypi.org/project/judais-lobi/)
[![License](https://img.shields.io/github/license/ginkorea/judais-lobi)](https://github.com/ginkorea/judais-lobi/blob/main/LICENSE)
[![Last Commit](https://img.shields.io/github/last-commit/ginkorea/judais-lobi)](https://github.com/ginkorea/judais-lobi/commits/main)
[![Repo Size](https://img.shields.io/github/repo-size/ginkorea/judais-lobi)](https://github.com/ginkorea/judais-lobi)
[![Code Size](https://img.shields.io/github/languages/code-size/ginkorea/judais-lobi)](https://github.com/ginkorea/judais-lobi)
[![Issues](https://img.shields.io/github/issues/ginkorea/judais-lobi)](https://github.com/ginkorea/judais-lobi/issues)
[![Stars](https://img.shields.io/github/stars/ginkorea/judais-lobi?style=social)](https://github.com/ginkorea/judais-lobi/stargazers)

---

## 🔴 JudAIs & 🔵 Lobi

<p align="center">
  <img src="https://raw.githubusercontent.com/ginkorea/judais-lobi/master/images/judais-lobi.png" alt="JudAIs & Lobi" width="420">
</p>

Two agents. One spine.

* 🧝 **Lobi** — whimsical Linux elf, creative, narrative, curious.
* 🧠 **JudAIs** — strategic adversarial twin, efficient, ruthless, execution-first.

They are no longer just terminal personalities.

They are evolving into a **local-first, contract-driven autonomous developer system**.

To find out why read the [Manifesto](https://github.com/ginkorea/judais-lobi/blob/master/MANIFESTO.md)!
---

# 🚧 Current Status

See: `ROADMAP.md` 

### Completed

* ✅ Phase 0 — Dependency Injection & Test Harness (73 tests)
* ✅ Phase 1 — Runtime extraction (provider separation, 107 tests)
* ✅ Phase 2 — Kernel State Machine & Hard Budgets (164 tests)
* ✅ Phase 3 — Session Artifacts, Contracts & KV Prefixing (269 tests)
* ✅ Phase 4 — MCP-Style Tool Bus, Sandboxing & Capability Gating (562 tests)
* ✅ Phase 5 — Repo Map & Context Compression (783 tests)
* ✅ Phase 6 — Repository-Native Patch Engine (888 tests)
* ✅ Phase 7.0 — Pluggable Workflows & State Machine Abstraction (974 tests)
* ✅ Phase 7.1-7.2 — Composite Judge & Candidate Sampling (1059 tests)
* ✅ Phase 7.3 — External Critic (1259 tests)
* ✅ Phase 7.4 — Campaign Orchestrator + StepPlan + EffectiveScope (1269 tests)

### Up Next

* ⏳ Phase 8 — Retrieval, Context Discipline & Local Inference

### Phase 7.1-7.2 Highlights

The kernel now has a deterministic scoring pipeline. Patches are evaluated by a multi-tier CompositeJudge, and N candidate patches can be generated and compared in isolated worktrees with automatic winner selection.

* **`core/judge/models.py`** — `TierVerdict` (str,Enum: pass/fail/waived/skipped), `TierResult`, `JudgeReport` (CRITIQUE phase schema), `CandidateScore`, `CandidateReport`. All Pydantic v2 models with full serialization roundtrip.
* **`core/judge/tiers.py`** — Three scoring tiers: `TestTier` (weight 0.6, hard pass/fail, short-circuits on failure), `LintTier` (weight 0.25, supports waive), `LLMReviewTier` (weight 0.15, stub returning 0.5). All tiers are pure logic — no subprocess, no ToolBus dependency.
* **`core/judge/judge.py`** — `CompositeJudge` sequences tiers, computes weighted score, determines verdict (pass/fail/needs_fix). Short-circuit: test failure skips remaining tiers. Verdict: `score >= 0.6 AND test_passed → pass`, `test_failed → fail`, else `needs_fix`. Injectable tier list for custom scoring hierarchies.
* **`core/judge/candidates.py`** — `CandidateManager` evaluates N candidate PatchSets, each in an isolated worktree via `PatchEngine`. Runs test/lint, scores via `CompositeJudge`, picks the highest-scoring non-failing candidate. Worktrees cleaned up after each evaluation. `max_candidates` cap from `BudgetConfig`.
* **`core/judge/gpu_profile.py`** — `GPUProfile` stub (cpu_only, max_concurrent=1). Hook for future hardware-aware concurrency budgeting.
* **`core/kernel/budgets.py`** — `BudgetConfig.max_candidates` (default 5) caps candidate count per task.
* **`core/contracts/schemas.py`** — `PHASE_SCHEMAS["CRITIQUE"]` now maps to `JudgeReport`.

85 new tests (1059 total). Scoring formula: `test(0.6) + lint(0.25) + llm_review(0.15)`. All-pass score: 0.925. CompositeJudge is pure logic — zero mocks needed for core scoring tests.

### Phase 7.0 Highlights

The kernel state machine is now parameterized by pluggable `WorkflowTemplate` objects. The coding pipeline becomes one template among many — custom workflows define their own phases, transitions, schemas, branching rules, and per-phase capability profiles without modifying any kernel code.

* **`core/kernel/workflows.py`** — `WorkflowTemplate` dataclass defining phases, transitions, phase_schemas, branch_rules, terminal_phases, phase_capabilities, and required_scopes. Two built-in constants: `CODING_WORKFLOW` (identical to Phase 6 behavior) and `GENERIC_WORKFLOW` (INTAKE → PLAN → EXECUTE → EVALUATE loop → FINALIZE). `select_workflow()` resolves by CLI flag, policy, or default.
* **`core/kernel/state.py`** — `Phase` is now `str, Enum` — members compare equal to their name strings (`Phase.INTAKE == "INTAKE"`). `SessionState.current_phase` is `str`, accepting both Phase enum members and plain strings. Custom workflows use domain-specific phase names as strings without modifying a global enum.
* **`core/kernel/orchestrator.py`** — Accepts a `WorkflowTemplate` parameter (defaults to `CODING_WORKFLOW`). All phase logic reads from the template: `phase_order` for linear progression, `branch_rules` for conditional branching, `terminal_phases` for loop termination. Zero hardcoded phase names.
* **`phase_capabilities`** — Per-phase capability allowlists creating temporal sandboxes. PLAN can read but not write. PATCH can write but only through the patch engine. RUN can verify but not modify. The capability engine computes `EffectiveScope` per tool call as the intersection of all applicable layers (Invariant 10).

12 tool descriptors. 86 new tests (974 total). CODING_WORKFLOW produces identical behavior to Phase 6 — zero existing tests break. GENERIC_WORKFLOW proven end-to-end with evaluate-failure loop and budget halting.

### Phase 6 Highlights

The agent can now reliably modify repository files through a deterministic, exact-match patch protocol with git worktree isolation and automatic rollback.

* **`core/patch/parser.py`** — Extracts `<<<< SEARCH / ==== / >>>> REPLACE`, `<<<< CREATE / >>>> CREATE`, and `<<<< DELETE >>>>` blocks from raw LLM text output. Delimiter-safe (only recognizes markers at line start). Path validation rejects absolute paths and `..` traversal at parse time.
* **`core/patch/matcher.py`** — Exact byte-match with byte offsets and SHA256 context hashes. On zero matches: 3-stage similarity narrowing pipeline (indent filter → token overlap → `SequenceMatcher` ratio) returns top 3 candidate regions. On multiple matches: returns all offsets + context hashes for LLM disambiguation.
* **`core/patch/applicator.py`** — File writes with strict preconditions. Path jailing (symlink-escape resistant). `\r\n → \n` canonicalization. `st_mode` preservation (executables stay executable). Create fails if file exists; delete fails if file doesn't exist.
* **`core/patch/worktree.py`** — `PatchWorktree` manages git worktree lifecycle: `create` (explicit `-b` + `HEAD`), `merge_back` (`--no-ff` + branch cleanup), `discard` (force remove + branch delete). Writes `.judais-lobi/worktrees/active.json` for crash recovery of orphaned worktrees.
* **`core/patch/engine.py`** — `PatchEngine` orchestrates validate → apply → diff → merge/rollback. Stops at first file failure, leaving worktree intact for diagnostics. `diff()` returns real `git diff` from the worktree.
* **`core/tools/patch_tool.py`** — ToolBus-compatible 6-action tool (validate, apply, diff, merge, rollback, status). All actions return JSON stdout for machine-friendly kernel orchestration. exit_code=0 only on success.

12 tool descriptors. 105 new tests (888 total). 3 integration tests with real git repos. Worktree isolation means cross-file patches land atomically — all succeed or discard for zero-cost rollback.

### Phase 5 Highlights

The agent is now repo-aware. It understands structure, relationships, and what's irrelevant — without eating the entire repo in context.

* **`core/context/repo_map.py`** — Top-level `RepoMap` orchestrator. Dual-use: overview mode (centrality-ranked for REPO_MAP phase) and focused mode (relevance-ranked by `target_files` for RETRIEVE phase). Lazy build with git-commit-keyed caching and dirty-file overlay.
* **`core/context/symbols/`** — 3-tier symbol extraction: Python `ast` (full import + signature extraction), tree-sitter (7 languages: C, C++, Rust, Go, JS, TS, Java), regex fallback. `get_extractor(language)` factory auto-selects the best available.
* **`core/context/graph.py`** — `DependencyGraph` with multi-language module resolution (Python dotted paths, C `#include`, Rust `use crate::`, Go package imports, JS/TS relative imports with extension guessing). Relevance ranking (1.0/0.8/0.6/0.4/0.1 scoring by hop distance) and centrality ranking with barrel file damping (`__init__.py`, `index.js`, `mod.rs`).
* **`core/context/formatter.py`** — Compact tree-style formatting with token budget, optional char cap, whitespace normalization for deterministic output, and metadata header (file/symbol counts, languages, ranking mode).
* **`core/context/visualize.py`** — DOT (Graphviz) and Mermaid graph export with highlight styling and node cap.
* **`core/context/cache.py`** — Git-commit-keyed persistent cache at `.judais-lobi/cache/repo_map/<hash>.json`. Clean commit = full cache hit; dirty state = cache + re-extract only modified files.
* **`core/tools/repo_map_tool.py`** — ToolBus-compatible multi-action tool (build, excerpt, status, visualize).
* **`setup.py`** — `pip install judais-lobi[treesitter]` adds optional tree-sitter support via individual grammar packages.

11 tool descriptors (now 12 with Phase 6). 221 new tests. tree-sitter is optional — the system works without it and gains rich multi-language AST parsing when installed.

### Phase 4 Highlights

Tools are dumb executors behind a capability-gated bus. The kernel decides everything.

* **`core/tools/bus.py`** — Action-aware `ToolBus` with preflight hooks, panic switch integration, and JSONL audit logging. Structured JSON denial errors replace plain text.
* **`core/tools/fs_tools.py`** — Consolidated `FsTool` with 5 actions (read, write, delete, list, stat). Pure `pathlib` I/O, no subprocess.
* **`core/tools/git_tools.py`** — Consolidated `GitTool` with 12 actions (status, diff, log, add, commit, branch, push, pull, fetch, stash, tag, reset) via `run_subprocess`.
* **`core/tools/verify_tools.py`** — Config-driven `VerifyTool` (lint, test, typecheck, format). Reads `.judais-lobi.yml` for project-specific commands, falls back to sensible defaults.
* **`core/tools/descriptors.py`** — 11 tool descriptors, 13 named scopes + wildcard. Per-action scope resolution via `action_scopes` map.
* **`core/tools/capability.py`** — Deny-by-default `CapabilityEngine` with wildcard `"*"` support, profile switching, and grant revocation.
* **`core/policy/profiles.py`** — Four cumulative profiles: `SAFE` (read-only) → `DEV` (+ write) → `OPS` (+ deploy/network) → `GOD` (wildcard).
* **`core/policy/god_mode.py`** — `GodModeSession` with TTL auto-downgrade, panic switch (instant revocation to SAFE), and full audit trail.
* **`core/policy/audit.py`** — Append-only JSONL `AuditLogger` with regex-based secret redaction (OpenAI, GitHub, AWS, Slack tokens).
* **`core/tools/sandbox.py`** — `NoneSandbox` (dev/debug) and `BwrapSandbox` (Tier-1 production) behind a common `SandboxRunner` interface.

3 consolidated multi-action tools replaced 21 separate descriptors. Git is the spine, not nice-to-have.

---

# 🧭 Where To Look

If you want to understand the **future**, read:

* 📜 `ROADMAP.md` — architectural blueprint 

If you want to understand the **current implementation**, inspect:

* `core/agent.py` — concrete Agent class (replaced `elf.py` in Phase 3)
* `core/contracts/` — Pydantic v2 contract models for all session data
* `core/sessions/` — SessionManager for disk artifact persistence
* `core/kernel/` — state machine, budgets, orchestrator, workflow templates (`workflows.py`)
* `core/cli.py`  — CLI interface layer
* `core/memory/memory.py`  — FAISS-backed long-term memory
* `core/tools/` — ToolBus, capability engine, sandbox, consolidated tools (fs, git, verify, repo_map, patch)
* `core/policy/` — profiles, god mode, audit logging
* `core/context/` — repo map extraction, dependency graph, symbol extractors (Python ast + tree-sitter + regex), formatting, caching, visualization
* `core/patch/` — patch engine: parser, matcher, applicator, worktree manager, engine orchestrator
* `core/judge/` — composite judge: tier scoring, candidate sampling, GPU profile stub
* `lobi/`  and `judais/`  — personality configs extending Agent

If you want to understand the **entry point**, see:

* `main.py` 
* `setup.py` 

---

# 🏗 Architectural Direction

The target architecture (from the roadmap) is:

* Artifact-driven state (no conversational drift)
* Three-tier orchestration: Campaign graph (Tier 0) → Workflow graph (Tier 1) → Phase-internal planning (Tier 2)
* Pluggable workflows — static templates for coding, red teaming, data analysis, and arbitrary tasks
* Campaign orchestration — multi-step missions with DAG decomposition, HITL approval gates, and artifact handoff
* Capability-gated tool execution with least-privilege by intersection (Global ∩ Workflow ∩ Step ∩ Phase)
* Sandbox isolation (bwrap / nsjail)
* Tests > Lint > LLM scoring hierarchy
* GPU-aware orchestration (vLLM / TRT-LLM)
* Optional external critic (frontier logic auditor)

The system is moving toward:

```
CLI (--task / --campaign / --workflow)
  ↓
Campaign Orchestrator (Tier 0 — optional, multi-step missions)
  ↓  plan → HITL approve → dispatch → synthesis
Workflow Selector → WorkflowTemplate (Tier 1 — static graph)
  ↓
Kernel State Machine (phases, transitions, budgets)
  ↓
Roles (Planner / Coder / Reviewer)
  ↓
ToolBus → EffectiveScope check → Sandbox → Subprocess
  ↓
Deterministic Judge (Tests > Lint > LLM)
```

As of Phase 7.4:

* The kernel state machine is parameterized by `WorkflowTemplate` objects — no hardcoded phase names, transitions, or branching rules. The coding pipeline is one template; custom domains define their own.
* `CODING_WORKFLOW` and `GENERIC_WORKFLOW` are built-in templates. `select_workflow()` resolves by CLI flag, policy, or default.
* Per-phase capability profiles (`phase_capabilities`) create temporal sandboxes — PLAN can read but not write, PATCH can write but only through the patch engine.
* Tools are dumb executors behind a sandboxed, capability-gated bus.
* Every tool call flows through `ToolBus → CapabilityEngine → SandboxRunner → Subprocess`.
* Deny-by-default. No scope = no execution.
* God mode exists for emergencies — TTL-limited, panic-revocable, fully audited.
* 5 consolidated multi-action tools (fs, git, verify, repo_map, patch) cover 31 operations under 13 scopes.
* The agent sees repo structure via a token-budgeted excerpt — file paths, symbol signatures, and dependency-ranked relevance — without loading full source.
* 3-tier symbol extraction: Python `ast` → tree-sitter (7 languages) → regex fallback. Multi-language dependency graph with import resolution.
* Code modifications use an exact-match patch protocol with git worktree isolation. Cross-file changes land atomically. Failed patches roll back at zero cost.
* Patches are scored by a deterministic `CompositeJudge` (Tests > Lint > LLM review). `CandidateManager` evaluates N candidate patches in isolated worktrees and selects the winner by composite score.
* **Campaign Orchestrator** provides a Tier 0 macro loop with HITL approval, step DAG execution, and explicit artifact handoff.
* **StepPlan contracts** lock intent, boundaries, and capability needs per step with a SHA256 ActionDigest.
* **EffectiveScope intersection** (`Global ∩ Workflow ∩ Step ∩ Phase`) is enforced per tool call.

Phase 8+ (in design) focuses on retrieval discipline and local inference. See `ROADMAP.md`.

The kernel is the only intelligence. Tools report. The kernel decides.

---

# 🧠 Memory System (Current)

Long-term memory uses:

* SQLite-backed JSON persistence
* FAISS vector index
* OpenAI embeddings (currently)

See: `core/memory/memory.py` 

This will be abstracted for local embeddings in later phases.

Short-term history remains for direct chat mode.
Agentic mode uses session artifacts as the sole source of truth (Phase 3).

---

# 🛠 Current Capabilities

Direct mode still works.

```bash
lobi "explain this function"
lobi --shell "list files"
lobi --python "plot sine wave"
lobi --search "latest linux kernel"
lobi --install-project
```

JudAIs:

```bash
judais "analyze this target" --shell
```

Voice (optional extra):

```bash
pip install judais-lobi[voice]
lobi "sing" --voice
```

---

# 🧪 Install

```bash
pip install judais-lobi
```

Requires:

* Python 3.10+
* OpenAI API key (for now)
* Linux recommended

Set API key:

```bash
export OPENAI_API_KEY=sk-...
```

Or create:

```
~/.elf_env
```

---

# 🔐 API Keys & Model APIs

Judais-Lobi uses API keys from your environment or your system keyring. Keys are never stored in config files.

Environment variables (fallbacks):

* `OPENAI_API_KEY` — OpenAI (builder + optional critic)
* `ANTHROPIC_API_KEY` — Anthropic critic (optional)
* `GOOGLE_API_KEY` — Google/Gemini critic (optional)

Keyring (preferred, optional):

* Service: `judais-lobi`
* Keys: `openai_api_key`, `anthropic_api_key`, `google_api_key`

Model API configuration (critic only):

* User defaults: `~/.judais-lobi/critic.yml`
* Project overrides: `.judais-lobi.yml` under `critic:`

Example `critic.yml`:

```yaml
enabled: true
providers:
  - provider: openai
    model: gpt-4o
  - provider: anthropic
    model: claude-sonnet-4-20250514
```

---

# 🔮 What This Is Becoming

Judais-Lobi is not trying to be:

* Another chat wrapper
* Another SaaS IDE
* Another prompt toy

It is attempting to become:

* A local-first agentic execution kernel (not just developer — any structured task domain)
* Deterministic and replayable
* Hardware-aware
* Capability-constrained (least-privilege by intersection)
* Mission-capable (campaign orchestration with HITL approval gates)
* Air-gap ready

The design philosophy is explicit in `ROADMAP.md` :

* Artifacts over chat
* Budgets over infinite loops
* Capabilities over trust
* Capabilities over tools (stable tags, not tool names)
* Plans over prompts (structured DAGs, not freestyle LLM loops)
* Static graphs, adaptive phases (three-tier orchestration)
* Dumb tools, smart kernel
* Commit or abort

That last one matters.

There will not be two systems of truth.

---

# 🧠 Philosophy

Lobi sings.
JudAIs calculates.

But the system beneath them is becoming something else:

A disciplined orchestration engine for machine reasoning.

The aesthetic may be mythic.
The architecture is not.

---

# ⭐ Contributing

If you are contributing:

1. Read the roadmap.
2. Understand the phase ordering.
3. Do not bypass tool execution through direct subprocess calls.
4. Every structural change must preserve deterministic replay.
5. New functionality goes through `Agent` + contracts, not ad-hoc methods.

This is an architectural project, not a feature factory.

---

# 🧾 License

GPLv3 — see LICENSE.
