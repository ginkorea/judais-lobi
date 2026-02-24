# ROADMAP.md
**Project:** judais-lobi
**Objective:** Transform judais-lobi into a local-first, contract-driven, agentic open developer system.

## Implementation Status

- [x] **Phase 0** – Dependency Injection, Test Harness & Baseline (73 tests, DI seams, pytest harness)
- [x] **Phase 1** – Extract Runtime & Stabilize the Spine (runtime extracted, 107 tests, `elf.py` provider-free)
- [x] **Phase 2** – Kernel State Machine & Hard Budgets (state machine, budgets, orchestrator, 164 tests)
- [x] **Phase 3** – Session Artifacts, Contracts & KV Prefixing (`elf.py` deleted, Agent class, Pydantic contracts, SessionManager, 269 tests)
- [ ] **Phase 4** – MCP-Style Tool Bus, Sandboxing & Capability Gating
- [ ] **Phase 5** – The Repo Map (Context Compression)
- [ ] **Phase 6** – Repository-Native Patch Engine
- [ ] **Phase 7** – Multi-Role Orchestrator, Composite Judge & External Critic
- [ ] **Phase 8** – Retrieval, Context Discipline & Local Inference
- [ ] **Phase 9** – Performance Optimization (TRT-LLM / vLLM Tuning)
- [ ] **Phase 10** – Evaluation & Benchmarks

---

## 1. Mission Statement
Judais-lobi will evolve from a CLI assistant with tools into a local-first autonomous developer agent with:

* **Artifact-Driven State:** Artifacts are the *only* source of truth. No conversational history drives execution.
* **Capability Gating:** Network and host access are deny-by-default, requested via structured artifacts, and powerful when explicitly granted.
* **Native Sandboxing:** Tool execution runs in native Linux namespaces (bwrap/nsjail) to maintain a microkernel architecture.
* **Hard Budgets:** Strict caps on retries, compute time, and context size prevent infinite loops.
* **Deterministic Workflows:** Repository-native patch workflows using Search/Replace blocks, governed by a rigid scoring hierarchy (Tests > Static Analysis > LLM).
* **GPU-Aware Orchestration:** VRAM-aware scheduling and KV cache prefixing that adapts to the available hardware — from a single RTX 5090 (32GB) to multi-GPU configurations (e.g., 4x L4, RTX 6000 Pro 96GB).

## 2. Architectural Target State

### 2.1 System Overview

```text
                          ┌─────────────────────────┐
                          │     CLI / Task Input     │
                          │  (lobi/judais commands)  │
                          └────────────┬────────────┘
                                       │
                          ┌────────────▼────────────┐
                          │     core/kernel/         │
                          │  State Machine + Budgets │
                          │  INTAKE → ... → FINALIZE │
                          └──┬───────────────────┬──┘
                             │                   │
              ┌──────────────▼──────┐   ┌───────▼──────────────┐
              │  core/contracts/    │   │  core/roles/          │
              │  JSON Schemas +     │   │  Planner / Coder /    │
              │  Pydantic models    │   │  Reviewer prompts     │
              └──────────┬─────────┘   │  (+ Lobi/JudAIs       │
                         │             │   personality layers)  │
              ┌──────────▼─────────┐   └───────┬───────────────┘
              │  core/runtime/     │           │
              │  Provider backends │◄──────────┘
              │  OpenAI │ Mistral  │
              │  vLLM │ TRT-LLM   │
              └──────────┬─────────┘
                         │
          ┌──────────────┼──────────────┐
          │              │              │
   ┌──────▼──────┐ ┌────▼──────┐ ┌────▼──────────┐
   │ tools/bus/  │ │core/      │ │ core/scoring/ │
   │ Tool Reg +  │ │context/   │ │ Tests > Lint  │
   │ Policy      │ │Repo-map + │ │ > LLM Review  │
   └──────┬──────┘ │Retrieval  │ └───────────────┘
          │        └───────────┘
   ┌──────▼──────┐
   │ tools/      │
   │ sandbox/    │
   │ bwrap/nsjail│
   └──────┬──────┘
          │
   ┌──────▼──────────────────────────┐
   │ tools/servers/                  │
   │ repo, git, runner, test, memory │
   │ web_search, rag, voice (opt)   │
   └─────────────────────────────────┘
```

### 2.2 Core Components
```text
core/
  kernel/                # Orchestration state machine & hard budgets
  contracts/             # JSON schemas + Pydantic validation
  runtime/               # LLM provider backends (OpenAI/Mistral API + Local HTTP/vLLM/TRT-LLM)
  capabilities/          # PermissionRequest and PermissionGrant engine
  context/               # Repo-map, Retrieval + compression
  memory/                # Unified memory (SQLite + FAISS vectors, carried forward)
  roles/                 # Planner / Coder / Reviewer static prompts
  scoring/               # Composite judge (Tests > Lint > LLM)

tools/
  bus/                   # MCP-style tool registry + Policy enforcement
  sandbox/               # SandboxRunner backends (bwrap, nsjail, none)
  servers/               # repo, git, runner, test, memory, web_search, rag

sessions/
  <timestamp_taskid>/
    artifacts/           # The ONLY source of truth for the session

```

### 2.3 Execution Model & Hard Budgets

Every task follows a strict state machine:
`INTAKE` -> `CONTRACT` -> `REPO_MAP` -> `PLAN` -> `RETRIEVE` -> `PATCH` -> `CRITIQUE` -> `RUN` -> `FIX (loop)` -> `FINALIZE`

Note: `CAPABILITY_CHECK` is not a phase. It is an invariant enforced by the ToolBus on **every tool call**. Any tool invocation — in any phase — triggers a capability check. If the required scope is not granted, the ToolBus returns a structured error and the kernel prompts for a `PermissionRequest`. This happens inline, not as a discrete step in the state machine.

**The Invariants:**

1. **Artifacts Only:** Every phase reads *only* current session artifacts, retrieved repo context, and tool traces.
2. **Hard Budgets:** The system enforces strict limits to prevent runaway loops:
* `max_phase_retries`: (e.g., 3 retries for invalid schema or patch failure).
* `max_total_iterations`: Absolute cap per task.
* `max_tool_output_bytes_in_context`: Truncation threshold for stdout/stderr.
* `max_context_tokens_per_role`: Bounded context window.
* `max_time_per_phase_seconds`: Hard timeout.
3. **Execution Path:** All tool execution flows through `ToolBus -> SandboxRunner -> Subprocess`. No tool ever calls `subprocess` directly. This is non-negotiable — without it, capability gating is cosmetic.
4. **Dumb Tools, Smart Kernel:** Tools are pure executors. They run a command, return stdout/stderr/exit code, and nothing else. All retry logic, repair logic, and decision-making lives in the kernel. The current `RunPythonTool.repair_code()` and `RunSubprocessTool` retry loops must be extracted into the kernel's FIX phase. If a tool fails, it reports failure. The kernel decides what happens next.
5. **GPU Scheduling in Runtime, Not Kernel:** The kernel asks `runtime.get_parallelism_budget()` and receives a number. It does not know about VRAM, device counts, or compute capability. Clean separation — the kernel orchestrates phases, the runtime owns hardware awareness.
6. **One ToolBus, Both Modes:** Direct mode and agentic mode use the **same ToolBus and SandboxRunner**. The difference between modes is orchestration depth (direct mode skips the kernel state machine), not the execution path. If direct mode bypasses the bus, you build two security models that drift apart. Every `--shell`, `--python`, and `--search` call in direct mode goes through the bus with the same policy enforcement. The bus is the only door.
7. **Kernel Never Touches the Filesystem:** The kernel reads artifacts and dispatches to tools. It never reads from the working directory, never opens project files, never writes outside the session directory. All repository interaction goes through a `RepoServer` tool via the ToolBus. Even read-only access must be sandboxed — if the kernel can read files directly, that is an unsandboxed path to the repo that bypasses policy. Kernel orchestrates. Tools touch the world.



---

## 3. Current System Inventory & Migration Map

Before building forward, the roadmap must account for every existing subsystem. The current codebase (v0.7.2, ~1,100 LOC) provides:

### 3.1 What Exists Today

| Subsystem | Files | Status in Target Architecture |
| --- | --- | --- |
| **Elf base class** (`core/elf.py`) | Provider selection, history mgmt, memory enrichment, web search, code gen, system prompt assembly, streaming chat | **Decomposed** across `core/runtime/`, `core/kernel/`, `core/context/`, `core/roles/`. Deleted once extraction is complete. |
| **CLI** (`core/cli.py`) | Arg parsing, tool registration, RAG ops, memory mgmt, code execution hooks, output formatting | **Gutted and thinned.** In agentic mode, CLI becomes: `submit_task()` -> `wait_for_kernel()` -> `print_result()`. Current logic (tool registration, code execution hooks, inline sudo, summarization) moves into the kernel and ToolBus. Direct mode retains current behavior for simple chat/search/RAG queries. See Section 8. |
| **UnifiedClient** (`core/unified_client.py`) | OpenAI SDK + Mistral cURL/SSE backends | **Moved** to `core/runtime/backends/`. Becomes `openai_backend.py` and `mistral_backend.py`. |
| **Memory system** (`core/memory/memory.py`) | SQLite + FAISS vectors, short-term/long-term/RAG/adventures | **Retained** under `core/memory/` with modifications. Short-term history is replaced by session artifacts. Long-term semantic memory and adventure tracking persist as cross-session knowledge. **Requires embedding backend abstraction** — current code hardcodes `OpenAI("text-embedding-3-large")` inside `UnifiedMemory`, which breaks offline/local-first operation. Must support local embedding models (e.g., sentence-transformers) as an alternative. |
| **Tool registry** (`core/tools/`) | Base class, subprocess template, shell/python/web/fetch/RAG/install/voice/recon | **Migrated** to `tools/bus/` registry. Existing tools become tool servers. Voice and recon remain optional. |
| **Agent personalities** (`lobi/lobi.py`, `judais/judais.py`) | System prompts, few-shot examples, character voice, color schemes | **Preserved** as personality layers in `core/roles/`. The Coder role loads a personality overlay (Lobi or JudAIs) that shapes tone and style. Agent identity is not discarded. |

### 3.2 What Is Deliberately Cut

* **Conversational history as execution state.** Short-term memory (`load_short`/`add_short`) no longer drives the LLM context. Session artifacts replace it.
* **Implicit tool invocation via prompt patterns.** Tools are invoked structurally through the ToolBus, not by LLM free-text matching.

### 3.3 What Is Carried Forward

* **FAISS + SQLite long-term memory.** Semantic recall across sessions remains valuable for the Planner and Reviewer roles.
* **RAG archive system.** Crawling, chunking, and embedding of project docs feeds into the `ContextPack` artifact.
* **Adventure tracking.** Past code execution history (prompt, code, result, success) informs the Coder role's retry strategy.
* **Web search and page fetch.** Available as capability-gated tools via the ToolBus.
* **Voice (optional).** Remains an output mode, loaded lazily.
* **Dual-agent identity.** Lobi and JudAIs remain distinct CLI entry points with personality-specific system prompts and behavior.

---

## 4. Phase Plan

### Phase 0 – Dependency Injection, Test Harness & Baseline

**Goal:** Make the system testable, then test it. Establish the safety net required before any refactoring begins.

The current codebase has zero tests. But you cannot write meaningful tests against it as-is, because side effects are baked into constructors:
* `Elf.__init__()` directly instantiates `UnifiedClient`, `UnifiedMemory`, and `Tools` — no injection points.
* `UnifiedMemory.__init__()` directly instantiates `OpenAI()` for embeddings — cannot be mocked without monkeypatching.
* `RunSubprocessTool` calls `subprocess.run(cmd, shell=True)` directly — no seam for test interception.

Writing tests against live API calls, live subprocesses, and live FAISS indexes is not testing. It is praying.

**Tasks:**

* **Introduce dependency injection** into the core constructors:
  * `Elf(client=..., memory=..., tools=...)` — all three injectable, with current behavior as defaults.
  * `UnifiedMemory(embedding_client=...)` — abstract the embedding call behind an interface. Current `OpenAI("text-embedding-3-large")` becomes the default; tests inject a deterministic fake.
  * `RunSubprocessTool(executor=...)` — wrap `subprocess.run` behind a callable, injectable for tests.
* Set up `pytest` with a `tests/` directory and a `make test` target.
* Write **golden transcript tests** for each backend (OpenAI, Mistral): fixed input messages, expected response shape, streaming behavior. Use injected mock clients.
* Write integration smoke tests: CLI end-to-end (`lobi "hello"`, `lobi --shell "list files"`, `lobi --recall`). Mock at the client boundary.
* Write unit tests for `UnifiedClient`, `UnifiedMemory` (add/search/purge), and the subprocess tool base class.
* Capture **baseline metrics** (response latency, token usage per interaction) to measure against later phases.
**Definition of Done:** `make test` passes with zero network calls. Every existing feature has at least one test covering its happy path. DI seams exist for client, memory, and subprocess execution. Regressions from subsequent phases are immediately detectable.

### Phase 1 – Extract Runtime & Stabilize the Spine

**Goal:** Pull provider backends and message building out of `elf.py` into a clean runtime layer.

**Tasks:**

* Create `core/runtime/backends/openai_backend.py` (extract from `unified_client.py`).
* Create `core/runtime/backends/mistral_backend.py` (extract cURL/SSE logic from `unified_client.py`).
* Create `core/runtime/backends/local_backend.py` as a **stub** — local inference is not deployed until Phase 8, but the interface is defined now. The interface must be GPU-topology-agnostic: it talks to a serving endpoint (vLLM/TRT-LLM), not directly to devices. Single-GPU vs. multi-GPU is a serving-layer concern, not a backend concern.
* Create `core/runtime/messages.py` for one canonical message builder (extract from `elf._system_with_examples()` and `elf.chat()`).
* Define provider capability flags per backend (supports JSON mode, supports tool calls, supports streaming).
* `unified_client.py` becomes a thin router delegating to backends.
**Definition of Done:** All golden transcript tests still pass. Message assembly is centralized. `elf.py` no longer contains provider-specific logic.

### Phase 2 – Kernel State Machine & Hard Budgets

**Goal:** Implement the orchestration core that governs phase transitions and enforces limits.

**Tasks:**

* Implement `core/kernel/state.py` (Phase enum, session state, transition rules).
* Implement `core/kernel/budgets.py` (configuration for all hard budget parameters).
* Implement `core/kernel/orchestrator.py` (the main loop: read artifacts, select phase, dispatch to role, enforce budgets).
* `elf.py` is reduced to a thin adapter that delegates to the kernel for agentic tasks, while still supporting direct chat for simple queries. This is `elf.py`'s last phase as a living file — see Section 10.
**Definition of Done:** The state machine can be driven through all phases with mock artifacts. Budget enforcement is tested (exceeding `max_phase_retries` halts the phase, exceeding `max_total_iterations` halts the session).

### Phase 3 – Session Artifacts, Contracts & KV Prefixing

**Goal:** Establish artifacts as the sole driver of state and optimize for KV Cache reuse.

**Critical Decision:** This phase kills conversational state. `self.history = [...]` stops being the execution driver. If you keep both conversational state and artifact state running in parallel "just in case," you create hidden divergence — two sources of truth that will silently disagree. Rip the bandage off.

**Tasks:**

* Build `core/contracts/schemas/*.json` and corresponding Pydantic models (`TaskContract`, `ChangePlan`, `ContextPack`, `PatchSet`, `PermissionRequest`, `PermissionGrant`, `PolicyPack`, etc.).
* **`PolicyPack`** is a first-class artifact — not scattered config, not implicit defaults. It declares: allowed tools, allowed scopes, sandbox backend, budget overrides, allowed mounts, allowed network domains. It is the single auditable document that explains "why the system refused" or "why the system was allowed to." It ships with the session and can be version-controlled per project. **Scope boundary:** PolicyPack governs permissions and resource limits only. It is not a general config registry — runtime settings, model selection, role prompts, and retrieval parameters live elsewhere. If PolicyPack starts accumulating non-permission concerns, it has bloated.
* Implement `SessionManager` to create session directories, write artifacts, and load latest versions. Must support **checkpoint & rollback** — if a patch fails tests in the RUN phase, the session can be reset to the last known-good artifact set instantly, without replaying intermediate phases.
* **Disable short-term history loading for agentic mode.** Stub out `memory.load_short()` / `memory.add_short()` in the agentic code path. Replace with artifact read/write. Direct chat mode retains history for backward compatibility.
* Implement `validate-or-retry` loop with schema invalidation burning the `max_phase_retries` budget.
* Define `STATIC_PREFIX` for KV caching (System Prompt + Tool Schemas + Policy). Roles append only small deltas. The local backend should leverage vLLM's Automatic Prefix Caching (APC) so the Planner -> Coder -> Reviewer handoff reuses the cached prefix instead of reprocessing tokens.
* **Delete `elf.py`.** At this point, all of its responsibilities have been extracted: runtime (Phase 1), kernel (Phase 2), artifacts (this phase). The `Elf` class is replaced by the kernel + role system. Lobi and JudAIs become personality configs loaded by roles, not subclasses of a god object. See Section 10.
**Definition of Done:** Sessions are replayable entirely from disk artifacts. `elf.py` is deleted. Invalid outputs trigger structured, budget-constrained retries. `PermissionGrant` artifacts are recorded so that session replay can re-apply the same grants deterministically. Any retrieval from long-term memory pins its results in the session artifacts (embedding backend ID, model name, query, returned chunk IDs, similarity scores) so that replays reproduce the same retrieval results even if embeddings change over time.

### Phase 4 – MCP-Style Tool Bus, Sandboxing & Capability Gating

**Goal:** Implement strict execution isolation and deny-by-default capabilities.

**Architectural constraint:** The current tools (`RunShellTool`, `RunPythonTool`, etc.) call `subprocess.run(cmd, shell=True)` directly. That is wide open. After this phase, no tool touches subprocess. The execution path is always `ToolBus -> SandboxRunner -> Subprocess`. Tools become pure declarative units: they describe *what* to run, the SandboxRunner decides *how*.

**Tasks:**

* **Strip agency from tools.** Remove retry loops, `repair_code()`, dependency auto-install, and sudo fallback from `RunSubprocessTool`, `RunPythonTool`, and `RunShellTool`. These behaviors move to the kernel (retries, repair) and the ToolBus policy layer (dependency install, privilege escalation). Tools return `(stdout, stderr, exit_code)` and nothing else.
* **Migrate existing tools** to the new ToolBus registry format. Each tool from `core/tools/` declares its capabilities, network requirements, and required scopes.
* **SandboxRunner:** `bwrap` is the **Tier-1** backend — it ships as default, gets full test coverage, and is the only backend that must work on day one. `nsjail` is **Tier-2** — same interface, stronger seccomp policy, added when bwrap is stable. `none` exists for dev/debug only. Do not try to keep two sandbox backends fully working simultaneously early on. Enforce filesystem isolation (workspace RW, rest RO, explicit tool caches) and rlimits (CPU time, max procs). **Support mount caching** — project `node_modules`, `venv`, and other dependency directories should be bind-mounted RO into the sandbox to avoid cold-start latency on every tool call.
* **Capability Engine:** Implement `PermissionRequest` and `PermissionGrant` artifacts. Grants are persisted to the session artifact directory so that **session replay can re-apply identical grants** without manual intervention — this is critical for deterministic replay. Grants support **time-scoping** (e.g., `git.fetch` allowed for 60 seconds) and **invocation-scoping** (e.g., `net.any` for this single tool call only). A grant that outlives its scope expires automatically. This prevents a single interactive approval from becoming a permanent backdoor if the agent drifts. **Replay semantics:** grants store `grant_issued_at`, `grant_duration_seconds`, and `grant_scope`. During replay, the original grant is reapplied without re-evaluating wall clock — expiry only governs live execution. Without this rule, deterministic replay collapses the moment a time-scoped grant crosses its original wall-clock boundary.
* **Network Scopes:** Define `net.any`, `http.read`, `git.fetch`. Network is structurally denied at the namespace level unless a valid `PermissionGrant` artifact exists for the active tool.
* **ToolBus Registry:** Every tool declares `requires_network` and `required_scope`. If missing, the bus returns a structured error template forcing the LLM to generate a `PermissionRequest`. The kernel pauses and waits for a user signal (or a pre-signed policy file) before granting.
**Definition of Done:** All execution is sandboxed. No tool calls subprocess directly. Tools cannot hit the network or unauthorized filesystem paths without an explicit, auditable grant artifact. Grant artifacts are replayable.

### Phase 5 – The Repo Map (Context Compression)

**Goal:** Feed the model the project structure deterministically without blowing the context limit.

**Tasks:**

* Implement a Repository Map generator using `tree-sitter` or `ctags`.
* Emit a compact format: file paths, classes, functions/method signatures.
* Cache the map keyed by git commit hash.
* Integrate into the `ContextPack` artifact.
**Definition of Done:** The Planner role can ingest a 100-file repository architecture in under ~3k tokens.

### Phase 6 – Repository-Native Patch Engine

**Goal:** Reliable code modification using exact-match constraints.
**Tasks:**

* Implement **Search/Replace block parsing** (`<<<< SEARCH / ==== / >>>> REPLACE`).
* Enforce exact match strategy: The SEARCH block *must* match exactly once in the target file.
* **Canonicalization before matching:** normalize line endings to `\n` (strip `\r`), but **preserve indentation exactly** — tabs vs. spaces and indentation depth must match the file. Do not offer a "whitespace-insensitive mode" as default; it weakens determinism. If needed later, it can exist as a separate explicit tool variant, not a flag.
* If ambiguous (0 or >1 matches), the tool returns a structured failure with surrounding context hashes. On **zero matches**, additionally return the 3 most similar lines in the file — but do not brute-force edit distance against every line in large files. Narrow first: filter by matching indentation depth, then by shared token overlap, then compute edit distance on the short list. This keeps similarity search fast in large repos.
* Automatically sandbox changes in a git worktree.
* Implement automatic rollback on patch failure.
**Definition of Done:** Patch protocol produces reproducible edits. Edits failing exact-match validation automatically trigger a budget-constrained retry.

### Phase 7 – Multi-Role Orchestrator, Composite Judge & External Critic

**Goal:** Team-of-teams behavior via deterministic scoring hierarchy, with an optional external frontier-model critic for catching "confident wrong" failures from local models.

#### 7.1 Composite Judge

Implement the **Composite Judge** as hard policy, not vibes:

1. `pytest`/`stdout` (Hard Pass/Fail — stops everything).
2. `pyright`/`lint` (Static analysis — blocks promotion unless explicitly waived by policy).
3. `LLM Reviewer` (Qualitative — breaks ties only, flags risks). *LLM never overrides green/red tests.*
4. `External Critic` (Optional — frontier-model logic auditor, see 7.3). *Never blocks if unavailable or refuses. Never overrides green/red tests.*

#### 7.2 Candidate Sampling

Implement candidate sampling with hardware-adaptive concurrency (see VRAM Budget Note).

**VRAM Budget Note:** Candidate sampling concurrency is dictated by the GPU profile, not hardcoded. The system must query available VRAM at startup and select a strategy accordingly:

| GPU Profile | VRAM | 7B FP8 (~8-10GB/gen) | 13B+ FP8 (~16-20GB/gen) | Strategy |
| --- | --- | --- | --- | --- |
| 1x RTX 5090 | 32GB | Concurrent N=2 feasible | Sequential only | Shared KV prefix, sequential fallback |
| 1x RTX 6000 Pro | 96GB | Concurrent N=3+ | Concurrent N=2-3 | Full parallel candidate generation |
| 4x L4 | 4x 24GB | N=1 per GPU, 4 parallel | N=1 per GPU (tight) | Tensor-parallel or pipeline-parallel serving; candidates distributed across GPUs |
| 1x consumer (16-24GB) | 16-24GB | Sequential N=2 | Not feasible | Sequential with aggressive KV eviction |

The runtime must expose a `gpu_profile` configuration (auto-detected or user-specified) that feeds into the kernel's budget system. Candidate count `N` becomes a derived parameter, not a constant. Empirical validation is required per profile before committing to concurrent batching.

**Deterministic candidate ordering:** When candidates are generated in parallel (across GPUs or concurrent requests), assign deterministic candidate IDs (`candidate_0`, `candidate_1`, ...) **before dispatch**. The Composite Judge scores candidates in ID order, not completion order. Otherwise the winning candidate depends on which GPU returns first — a race condition that breaks reproducibility.

#### 7.3 External Critic (Optional Frontier-Model Auditor)

**Motivation:** Local models are effective builders but vulnerable to "confident wrong" — logically coherent plans that miss critical assumptions, patches that pass tests but violate deeper constraints, or review loops that converge on the wrong answer. An external frontier model provides an independent logic audit without replacing local execution.

**Architecture:**

* **Local model = builder** (Planner/Coder/Reviewer roles, patch generation, repo ops)
* **Deterministic judge = truth oracle** (tests/lint/bench — always authoritative)
* **External frontier model = critic** (logic auditor, risk assessor, plan sanity checker)

The critic does **not** write code. It does not get tools. It does not get repo access. It only critiques artifacts. It is a judge in the balcony, not a player on the field.

**Air-gap design:** The entire critic subsystem is optional. When disabled (no API key, no network, air-gapped environment, or `external_critic.enabled: false` in policy), the pipeline runs identically — the critic checkpoints become no-ops. This is enforced structurally: critic calls are **interceptors on phase transitions**, not phases in the state machine. The orchestrator checks "should I call the critic before entering this next phase?" and skips silently when the critic is unavailable.

**When to call the critic (trigger-based, not every loop):**

High-leverage checkpoints only:

1. **After PLAN (before RETRIEVE)** — catch missing assumptions, wrong file targets, untestable approach.
2. **After RUN passes (before FINALIZE)** — catch "green tests but wrong semantics", latent risk.

Escalation triggers (automatic, budget-permitting):

* \> N iterations without progress (FIX loop spinning)
* Patch touches security-sensitive surfaces (auth, crypto, permissions)
* Dependency changes (new packages, version bumps)
* Large refactor scope (> K files or > M lines changed)
* Local reviewer disagreement with local planner
* Planning uncertainty flagged by the local model itself

**What the critic sees (minimal, structured `CritiquePack`):**

* `TaskContract` (constraints, allowed commands, acceptance criteria)
* `ChangePlan` (steps, files targeted)
* `RepoMap excerpt` (only signatures + file paths, no full source)
* `PatchSet` summary (diff stats + snippets of changed regions only)
* `RunReport` (if tests ran: failures or pass summary)
* `LocalReviewerReport` (what the local reviewer thought)

No full repo. No secrets. No giant logs. No tool output dumps.

**Redactor (non-negotiable, runs before any external call):**

* Strip secrets (keys, tokens, passwords) by pattern matching
* Strip hostnames/IPs if redaction level is `strict`
* Replace file contents with diff snippets or function signatures only
* Clamp payload size hard (cost + leakage control)
* Log: `payload_size_bytes`, `redaction_ruleset_version`, `sha256(payload)`

**Critic response contract (`ExternalCriticReport`):**

* `verdict`: `approve` | `caution` | `block` | `refused`
* `top_risks`: list (severity, rationale)
* `missing_tests`: list
* `logic_concerns`: list
* `suggested_plan_adjustments`: list
* `suggested_patch_adjustments`: list
* `questions_for_builder`: list (bounded)
* `confidence`: 0–1

**Verdict policy — the critic never kneecaps the pipeline:**

| Verdict | Kernel response |
| --- | --- |
| `approve` | Logged, pipeline continues |
| `caution` | Logged, surfaced to user, does **not** halt |
| `block` | Requires plan revision **or** explicit user override recorded as artifact |
| `refused` | Logged, **ignored**, pipeline continues as if critic was not called |
| `unavailable` | Silent no-op, pipeline continues |

The `refused` verdict is the critical design constraint. If a frontier model returns a refusal (e.g., content policy triggers on a legitimate pentesting task), the system treats it as a non-event. The critic's system prompt frames all interactions as code review of existing artifacts, never as generation requests — this minimizes refusals. But when they happen, they must never block execution. The deterministic judge (tests/lint) remains the only hard gate.

**Capability gating (fits Phase 4 permission model):**

Critic access is a permissioned capability, same as network access. `TaskContract` declares:

* `external_critic.enabled: true|false`
* `external_critic.provider: <name>` (e.g., "openai", "anthropic")
* `external_critic.max_calls_per_session: k`
* `external_critic.max_tokens_per_call: n`
* `external_critic.redaction_level: strict|normal`
* `external_critic.allowed_artifact_fields: [...]`

Grants are logged to the session. All requests and payload hashes are recorded for auditability.

**Cost control:**

* Max calls per session (hard budget in `TaskContract`)
* Max tokens per call (input and output)
* Trigger-based invocation only (not every loop)
* **Critic caching:** Hash the `CritiquePack`. If the same content is reviewed again (e.g., after a no-op retry), reuse the prior report. Cache keyed by `sha256(redacted_payload)`.

**Implementation tasks:**

1. `ExternalCriticBackend` interface (HTTP client to frontier API, uses `core/runtime/backends/` pattern)
2. `CritiquePack` builder (assembles minimal artifact payload from session state)
3. `Redactor` (strict by default, configurable per policy)
4. `ExternalCriticReport` schema + Pydantic validation
5. Critic trigger policy (when to call, what to send, what to do with verdicts)
6. Orchestrator interceptor hooks on PLAN→RETRIEVE and RUN→FINALIZE transitions
7. CLI: `--critic` flag to enable, `--critic-provider <name>` to select, `--no-critic` to force off
8. Manual invocation: `lobi critic --session <id>` for post-hoc review of any session

**Definition of Done:** Generates competing patches, grades them deterministically, discards test failures, and selects the proven winner. External critic is fully operational when configured, fully absent when not — system runs identically in both modes. Critic refusals never halt the pipeline.

### Phase 8 – Retrieval, Context Discipline & Local Inference

**Goal:** Prevent KV cache overflow and bring up local model serving.

This phase combines retrieval engineering with the transition from API-based inference to local GPU inference, since both directly affect context management and VRAM budgeting.

**Tasks:**

* Implement symbol-aware retrieval (fetching specific function spans, not whole files).
* Implement **rolling summarization** for tool traces: full logs stream to disk, but only capped summaries enter the LLM context (`max_tool_output_bytes_in_context`). When output exceeds the budget, do not blindly truncate — prompt the model with a structured message: *"Output exceeded budget (N bytes). Full log at `<artifact_path>`. Use targeted retrieval (grep, tail, symbol lookup) to find specific information."* This forces the model to narrow its search rather than losing context to a dumb cutoff.
* **Local inference bring-up:** Deploy and validate vLLM or TRT-LLM serving the target model on the available GPU(s). Wire `local_backend.py` (stubbed in Phase 1) to the local server. For multi-GPU setups, configure tensor parallelism via the serving layer (vLLM `--tensor-parallel-size`, TRT-LLM TP config).
* Define the **model selection criteria** for local inference: minimum coding benchmark scores, context window requirements, quantization compatibility.
* Validate that all golden transcript tests pass against the local backend.
**Definition of Done:** Context size is strictly bounded. Tool output never causes a token overflow crash. The system can run fully offline against the local backend on at least one GPU profile.

### Phase 9 – Performance Optimization (TRT-LLM / vLLM Tuning)

**Goal:** Maximize throughput and minimize latency across all supported GPU profiles.
**Tasks:**

* Implement **GPU profile auto-detection** (`nvidia-smi` / `torch.cuda`): enumerate devices, total VRAM, compute capability. Expose as `gpu_profile` config that feeds into budget and concurrency decisions system-wide.
* Measure and adopt FP8 KV cache utilization (if stable on the stack; particularly beneficial on Ada/Blackwell architectures).
* Implement batched inference support for evaluating multiple patch candidates concurrently (contingent on VRAM budget validation from Phase 7). On multi-GPU setups, distribute candidates across devices.
* Add performance telemetry: `tokens/sec`, `time_to_first_token`, `VRAM_headroom`, `tail_latency`. Track per-device metrics for multi-GPU configurations.
* Validate and document tuning profiles for reference hardware:
  * **1x RTX 5090 (32GB)** — Primary development target. FP8 quantization, sequential or concurrent N=2 for 7B models.
  * **4x L4 (4x 24GB)** — Cloud/server target. Tensor-parallel serving, one candidate per device.
  * **1x RTX 6000 Pro (96GB)** — High-end workstation. Large models (30B+) or concurrent N=3 for smaller models.
**Definition of Done:** System runs continuously with stable VRAM usage on all tested profiles. Batched candidate generation fully saturates available GPU(s) (or is documented as infeasible per profile with justification).

### Phase 10 – Evaluation & Benchmarks

**Goal:** Objective measurement of agent capability.
**Tasks:**

* Create internal task suite: rename refactor, bug fix, add test, API extension.
* Track: Success rate, Iteration count, Wall time, Token usage.
* Track Key KPI: **Human Interventions Required**.
* Compare results against baseline metrics captured in Phase 0.
**Definition of Done:** Repeatable benchmark suite that proves the multi-role, capability-gated architecture outperforms a naive loop.

---

## 5. Failure Mode Matrix

To prevent system collapse under edge cases, the kernel must handle failures structurally:

| Failure Class | Detection | Response | Logging Artifact | Retry Rule |
| --- | --- | --- | --- | --- |
| **Invalid JSON** | Pydantic parse failure | Return schema error | `error_trace_<n>.json` | Burn 1 `max_phase_retries` |
| **Perms Denied** | ToolBus capability check | Return request template | `permission_denied_<n>.json` | Prompt LLM for `PermissionRequest` |
| **Patch Ambiguity** | SEARCH block != 1 match | Return context hashes | `patch_fail_<n>.json` | Burn 1 `max_phase_retries` |
| **Test Timeout** | SandboxRunner time limit | Kill proc, return `Timeout` | `run_report_<n>.json` | Pass to Reviewer to fix code |
| **Context Overflow** | Tokenizer length check | Truncate / Summarize | `context_warn_<n>.json` | Hard system rule, no retry |
| **Runaway Loop** | Iteration > `max_total` | Halt session | `final_report.json` | Abort to human |
| **VRAM OOM** | CUDA OOM exception | Kill inference, reduce batch/context | `vram_oom_<n>.json` | Retry with smaller context window |
| **Model Collapse** | Last 3 outputs >90% identical on **semantic content fields** (plan steps, patch blocks, review reasoning — not raw artifact JSON, which is naturally repetitive in structure) | Kill phase, inject prompt perturbation | `collapse_<n>.json` | Burn 1 `max_phase_retries` with forced prompt perturbation |
| **Critic Refusal** | External critic returns `refused` verdict | Log refusal, continue pipeline as if critic was not called | `critic_refused_<n>.json` | No retry consumed — refusal is a non-event |
| **Critic Unavailable** | Network error, timeout, or critic disabled | Silent no-op, continue pipeline | `critic_unavailable_<n>.json` | No retry consumed |

---

## 6. Constraints & Non-Goals

* **Constraints:**
  * Must run fully offline on local GPU(s). Primary development target is 1x RTX 5090 (32GB), but the system must not hardcode GPU assumptions. It must adapt to the detected hardware via `gpu_profile` — from a single 16GB consumer card (reduced concurrency, smaller models) up to multi-GPU server configurations (4x L4, RTX 6000 Pro 96GB, etc.).
  * Must fail safely and cleanly rollback.
  * Network is deny-by-default.
  * No Docker dependency — sandboxing uses native Linux namespaces (bwrap/nsjail). The current codebase has no Docker usage; this constraint ensures it stays that way.
  * API-based backends (OpenAI, Mistral) remain supported alongside local inference. The system is not local-only until the user chooses it.
* **Non-Goals:**
  * Not a chat product (though direct chat remains available for simple queries).
  * Not a web-first IDE.
  * Not dependent on vendor lock-in.

## 7. Design Philosophy

* **Artifacts over Chat:** State is on disk, not in a sliding text window.
* **Capabilities over Trust:** The model is assumed hostile; the sandbox and network gates keep it safe.
* **Determinism over Vibes:** Tests dictate success; LLMs only suggest code.
* **Budgets over Infinite Loops:** Everything has a timeout and a retry cap.
* **Dumb Tools, Smart Kernel:** Tools execute. They do not decide, retry, repair, or escalate. All intelligence lives in the kernel. If a tool contains an `if/else` about what to do next, it has too much agency.
* **Migration over Rewrite:** Each phase must leave the system in a working state. No big-bang rewrites.
* **Air-Gap Ready:** Every external dependency (frontier critic, API backends, network tools) is optional and capability-gated. The system must run identically with or without network access. External services add value when available but never gate execution. A `refused` response from any external service is a non-event, not a blocker.
* **Commit or Abort:** The greatest architectural risk is partial refactor — a half-agentic, half-chatbot chimera where some paths use artifacts and others use `self.history`, where some tools go through the bus and others call subprocess directly. Each phase must fully replace the subsystem it targets. Release 0.8 can break backward compatibility. That is allowed. What is not allowed is two systems of truth running in parallel.

## 8. User Interface Contract

The system is invoked via the existing CLI entry points (`lobi`, `judais`). The agentic workflow is an additional execution mode, not a replacement for direct chat.

### Direct Mode (Preserved)
```bash
lobi "explain this function"          # Chat
lobi --shell "list large files"       # Code generation + execution
lobi --search "rust async patterns"   # Web search enrichment
lobi --rag crawl ./docs               # RAG indexing
lobi --recall 5                       # Adventure history
```

### Agentic Mode (New)
```bash
lobi --task "add pagination to the /users endpoint"
lobi --task "fix the race condition in worker.py" --grant net.any
```

* `--task` enters the full state machine (INTAKE through FINALIZE).
* `--grant` pre-authorizes capability scopes for the session.
* Session artifacts are written to `sessions/<timestamp_taskid>/artifacts/`.
* The user can inspect, resume, or replay any session from its artifacts.

**Capability grant UX** — three modes, from most manual to most automated:
1. **Interactive approval:** Kernel pauses, CLI prompts the user: `"Tool 'git_fetch' requests scope 'net.any'. Allow? [y/N/y+60s]"`. User can grant permanently, for a duration, or deny.
2. **CLI pre-authorization:** `--grant net.any,git.fetch` pre-signs scopes for the session. No interactive prompts for covered scopes.
3. **Policy file:** `--policy ./policy.json` loads a `PolicyPack` artifact that auto-approves matching scopes. Useful for CI, unattended runs, or project-standard policies.

## 9. Phase Dependencies

Phases are not strictly linear. The dependency graph allows parallel work where inputs are independent:

```text
Phase 0 (Tests & Baseline)
  │
  ├──► Phase 1 (Extract Runtime)
  │       │
  │       ├──► Phase 2 (Kernel & Budgets)
  │       │       │
  │       │       └──► Phase 3 (Artifacts & Contracts)
  │       │               │
  │       │               ├──► Phase 4 (Tool Bus & Sandbox)
  │       │               │
  │       │               ├──► Phase 5 (Repo Map) ────────────┐
  │       │               │                                    │
  │       │               └──► Phase 6 (Patch Engine) ─────────┤
  │       │                                                    │
  │       │                                    ┌───────────────┘
  │       │                                    │
  │       │                              Phase 7 (Orchestrator & Judge)
  │       │                                    │
  │       │                              Phase 8 (Retrieval & Local Inference)
  │       │                                    │
  │       │                              Phase 9 (GPU Optimization)
  │       │                                    │
  │       │                              Phase 10 (Benchmarks)
  │       │
  │       └──► Phase 8 (local_backend.py stub is ready from Phase 1;
  │              local inference bring-up can begin once Phase 3 contracts
  │              define the interface)
  │
  └──► Phase 10 (Baseline metrics feed directly into final evaluation)
```

**Key parallelism opportunities:**
* Phase 5 (Repo Map) and Phase 6 (Patch Engine) are independent and can be built concurrently after Phase 3.
* Phase 10 (Benchmarks) baseline capture starts in Phase 0; the full suite is built last but metrics collection is continuous.
* Local inference bring-up (Phase 8) can begin prototyping as soon as the runtime interface is defined (Phase 1), though full integration requires Phase 3 contracts.

## 10. Point of No Return: The Deletion of `elf.py`

As long as `core/elf.py` exists in full power, the system will gravitate back toward conversational entropy. Every quick fix, every "just add it to Elf for now" shortcut, re-entrenches the god object.

**The deletion happens at the end of Phase 3.** By that point:

| Responsibility | Extracted To | Phase |
| --- | --- | --- |
| Provider selection & fallback | `core/runtime/backends/` | Phase 1 |
| Message assembly & system prompt | `core/runtime/messages.py` + `core/roles/` | Phase 1 |
| Streaming chat interface | `core/runtime/` (backend concern) | Phase 1 |
| History management | Replaced by session artifacts | Phase 3 |
| Memory enrichment | `core/context/` (reads from `core/memory/`) | Phase 3 |
| Web search enrichment | ToolBus-managed tool | Phase 4 |
| Code generation & execution | ToolBus-managed tool (kernel dispatches) | Phase 4 |
| Tool access & registration | `tools/bus/` | Phase 4 |

After Phase 3, `elf.py` has no unique responsibilities left. It is deleted. Not deprecated. Not commented out. **Deleted.**

`Lobi` and `JudAIs` stop being subclasses of `Elf`. They become personality configuration files loaded by `core/roles/`:

```text
core/roles/
  planner.py          # Static prompt for planning phase
  coder.py            # Static prompt for code generation
  reviewer.py         # Static prompt for critique/scoring
  personalities/
    lobi.yaml         # System prompt overlay, few-shot examples, tone, color
    judais.yaml       # System prompt overlay, few-shot examples, tone, color
```

The role system composes prompts as: `STATIC_PREFIX + RoleDirective + PersonalityOverlay + PhaseContext`.

This is the point of no return. After this, there is no going back to the chatbot architecture. The system is a kernel.
