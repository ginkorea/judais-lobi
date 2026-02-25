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

### Up Next

* ⏳ Phase 6 — Repository-Native Patch Engine
* ⏳ Phase 7 — Multi-Role Orchestrator, Composite Judge & External Critic

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

11 tool descriptors. 221 new tests. tree-sitter is optional — the system works without it and gains rich multi-language AST parsing when installed.

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
* `core/kernel/` — state machine, budgets, orchestrator
* `core/cli.py`  — CLI interface layer
* `core/memory/memory.py`  — FAISS-backed long-term memory
* `core/tools/` — ToolBus, capability engine, sandbox, consolidated tools (fs, git, verify, repo_map)
* `core/policy/` — profiles, god mode, audit logging
* `core/context/` — repo map extraction, dependency graph, symbol extractors (Python ast + tree-sitter + regex), formatting, caching, visualization
* `lobi/`  and `judais/`  — personality configs extending Agent

If you want to understand the **entry point**, see:

* `main.py` 
* `setup.py` 

---

# 🏗 Architectural Direction

The target architecture (from the roadmap) is:

* Artifact-driven state (no conversational drift)
* Deterministic state machine
* Capability-gated tool execution
* Sandbox isolation (bwrap / nsjail)
* Tests > Lint > LLM scoring hierarchy
* GPU-aware orchestration (vLLM / TRT-LLM)
* Optional external critic (frontier logic auditor)

The system is moving toward:

```
CLI
  ↓
Kernel State Machine
  ↓
Roles (Planner / Coder / Reviewer)
  ↓
ToolBus → Sandbox → Subprocess
  ↓
Deterministic Judge
```

As of Phase 5:

* Tools are dumb executors behind a sandboxed, capability-gated bus.
* Every tool call flows through `ToolBus → CapabilityEngine → SandboxRunner → Subprocess`.
* Deny-by-default. No scope = no execution.
* God mode exists for emergencies — TTL-limited, panic-revocable, fully audited.
* 4 consolidated multi-action tools (fs, git, verify, repo_map) cover 25 operations under 13 scopes.
* The agent sees repo structure via a token-budgeted excerpt — file paths, symbol signatures, and dependency-ranked relevance — without loading full source.
* 3-tier symbol extraction: Python `ast` → tree-sitter (7 languages) → regex fallback. Multi-language dependency graph with import resolution.

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

# 🔮 What This Is Becoming

Judais-Lobi is not trying to be:

* Another chat wrapper
* Another SaaS IDE
* Another prompt toy

It is attempting to become:

* A local-first agentic developer kernel
* Deterministic and replayable
* Hardware-aware
* Capability-constrained
* Air-gap ready

The design philosophy is explicit in `ROADMAP.md` :

* Artifacts over chat
* Budgets over infinite loops
* Capabilities over trust
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
