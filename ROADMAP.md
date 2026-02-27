# ROADMAP.md
**Project:** judais-lobi
**Objective:** Transform judais-lobi into a local-first, contract-driven, autonomous execution kernel — starting with software development, generalizable to any structured task domain.

## Implementation Status

- [x] **Phase 0** – Dependency Injection, Test Harness & Baseline (73 tests, DI seams, pytest harness)
- [x] **Phase 1** – Extract Runtime & Stabilize the Spine (runtime extracted, 107 tests, `elf.py` provider-free)
- [x] **Phase 2** – Kernel State Machine & Hard Budgets (state machine, budgets, orchestrator, 164 tests)
- [x] **Phase 3** – Session Artifacts, Contracts & KV Prefixing (`elf.py` deleted, Agent class, Pydantic contracts, SessionManager, 269 tests)
- [x] **Phase 4** – MCP-Style Tool Bus, Sandboxing & Capability Gating (ToolBus, CapabilityEngine, BwrapSandbox, 3 consolidated tools, profiles, god mode, audit, 562 tests)
- [x] **Phase 5** – The Repo Map & Context Compression (3-tier extraction: Python ast + tree-sitter + regex, multi-language dependency graph, relevance ranking, token-budgeted excerpts, DOT/Mermaid visualization, git-commit-keyed caching, 783 tests)
- [x] **Phase 6** – Repository-Native Patch Engine (parser, exact-match matcher with similarity diagnostics, path-jailed applicator, git worktree isolation with crash recovery, PatchEngine orchestrator, ToolBus-integrated PatchTool with 6 actions, 888 tests)
- [x] **Phase 7** – Pluggable Workflows, Campaign Orchestrator, Composite Judge & External Critic (7.0–7.4 complete)
- [ ] **Phase 8** – Retrieval, Context Discipline & Local Inference
- [ ] **Phase 9** – Performance Optimization (TRT-LLM / vLLM Tuning)
- [ ] **Phase 10** – Evaluation & Benchmarks

---

## 1. Mission Statement
Judais-lobi will evolve from a CLI assistant with tools into a local-first autonomous execution kernel with:

* **Artifact-Driven State:** Artifacts are the *only* source of truth. No conversational history drives execution.
* **Capability Gating:** Network and host access are deny-by-default, requested via structured artifacts, and powerful when explicitly granted.
* **Native Sandboxing:** Tool execution runs in native Linux namespaces (bwrap/nsjail) to maintain a microkernel architecture.
* **Hard Budgets:** Strict caps on retries, compute time, and context size prevent infinite loops.
* **Pluggable Workflows:** The state machine is parameterized by a `WorkflowTemplate` — a static, auditable definition of phases, transitions, schemas, and branch rules. The coding pipeline is the first workflow, not the only one. Red teaming, data analysis, optimization, and arbitrary structured tasks run on the same kernel with different templates. The LLM selects which template to use at INTAKE; it never rewrites the transition graph at runtime.
* **Campaign Orchestration:** Multi-step missions run as a hierarchical state machine — a `CampaignOrchestrator` (Tier 0) drafts a DAG of steps, each assigned a workflow template, gets human approval, then dispatches isolated child workflows with explicit artifact handoff. The campaign plan is immutable once approved. The system graduates from "task runner" to "mission manager" without adding a second orchestration universe — campaigns are workflow-of-workflows, reusing the entire existing stack.
* **Deterministic Workflows:** Repository-native patch workflows using Search/Replace blocks, governed by a rigid scoring hierarchy (Tests > Static Analysis > LLM).
* **GPU-Aware Orchestration:** VRAM-aware scheduling and KV cache prefixing that adapts to the available hardware — from a single RTX 5090 (32GB) to multi-GPU configurations (e.g., 4x L4, RTX 6000 Pro 96GB).

## 2. Architectural Target State

### 2.1 System Overview

```text
                          ┌─────────────────────────┐
                          │     CLI / Task Input     │
                          │  (lobi/judais commands)  │
                          │  --task / --campaign      │
                          │  --workflow               │
                          └────────────┬────────────┘
                                       │
                            ┌──────────▼──────────┐
                            │  --campaign?         │
                            │  ┌────────────────┐  │
                            │  │ Campaign       │  │  Tier 0: DAG of steps
                            │  │ Orchestrator   │  │  HITL approval gate
                            │  │ (plan→approve  │  │  artifact handoff
                            │  │  →dispatch     │  │
                            │  │  →synthesis)   │  │
                            │  └───────┬────────┘  │
                            │          │ per step  │
                            └──────────┼──────────┘
                                       │
                          ┌────────────▼────────────┐
                          │  WorkflowSelector        │
                          │  (picks template from    │
                          │   INTAKE artifact or CLI) │
                          └────────────┬────────────┘
                                       │
                          ┌────────────▼────────────┐  Tier 1: static
                          │     core/kernel/         │  workflow graph
                          │  Orchestrator + Budgets  │
                          │  WorkflowTemplate drives │  Tier 2: adaptive
                          │  phases & transitions    │  phase-internal
                          └──┬───────────────────┬──┘
                             │                   │
              ┌──────────────▼──────┐   ┌───────▼──────────────┐
              │  core/contracts/    │   │  core/roles/          │
              │  Workflow-scoped    │   │  Dispatchers per      │
              │  Pydantic schemas   │   │  workflow domain      │
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
   │ tools/ (domain packages)        │
   │ repo, git, patch, verify, fs    │
   │ web_search, rag, voice (opt)    │
   │ + future: redteam/, data/, ...  │
   └─────────────────────────────────┘
```

### 2.2 Core Components
```text
core/
  kernel/                # Orchestrator, budgets, workflow engine
    state.py             # Phase, SessionState, transition validation
    orchestrator.py      # Main loop (parameterized by WorkflowTemplate)
    budgets.py           # Hard budget enforcement
    workflows.py         # WorkflowTemplate, WorkflowSelector, built-in templates
  campaign/              # Campaign orchestrator (Tier 0)
    orchestrator.py      # CampaignOrchestrator: plan → approve → dispatch → synthesis
    models.py            # CampaignPlan, MissionStep, StepPlan, CampaignState
    validator.py         # DAG acyclicity, artifact declarations, step_id uniqueness
    scope.py             # EffectiveScope intersection: Global ∩ Workflow ∩ Step ∩ Phase
    hitl.py              # HUMAN_REVIEW: $EDITOR file-edit loop + Pydantic revalidation
    handoff.py           # Artifact materialization: handoff_out/ → handoff_in/
  contracts/             # JSON schemas + Pydantic validation
    schemas.py           # All Pydantic models (workflow-registered, not hardcoded)
    campaign.py          # CampaignPlan, MissionStep, CampaignLimits, ArtifactRef
    validation.py        # Schema lookup via workflow.phase_schemas
  runtime/               # LLM provider backends (OpenAI/Mistral API + Local HTTP/vLLM/TRT-LLM)
  capabilities/          # PermissionRequest and PermissionGrant engine
  context/               # Repo-map, Retrieval + compression
  patch/                 # Patch engine: parser, matcher, applicator, worktree
  memory/                # Unified memory (SQLite + FAISS vectors, carried forward)
  roles/                 # Domain-specific role dispatchers
    dispatchers/         # CodeDispatcher, GenericDispatcher, future RedTeamDispatcher...
    personalities/       # lobi.yaml, judais.yaml — persona overlays
  scoring/               # Composite judge (Tests > Lint > LLM)

tools/
  bus/                   # MCP-style tool registry + Policy enforcement
  sandbox/               # SandboxRunner backends (bwrap, nsjail, none)
  (domain packages)      # fs, git, patch, verify, repo_map + future: redteam/, data/

sessions/
  # Single-task session (workflow mode):
  <timestamp_taskid>/
    artifacts/           # The ONLY source of truth for the session
    workflow.json        # Which WorkflowTemplate was used (for replay)

  # Multi-step campaign session (campaign mode):
  <campaign_id>/
    campaign.json        # CampaignPlan + current state (frozen after HUMAN_REVIEW)
    synthesis/           # Final compiled outputs from all steps
    steps/
      <step_id>/
        workflow.json    # Selected WorkflowTemplate for this step
        artifacts/       # Step-local artifacts (isolated from other steps)
        handoff_in/      # Materialized imports from upstream steps
        handoff_out/     # Exports declared by this step (available to downstream)

```

### 2.3 Execution Model & Hard Budgets

Execution operates at three tiers. Each tier has a strict boundary: the layer above dispatches, the layer below executes. No tier reaches into another's internals.

* **Tier 0 — Campaign graph** (DAG of steps). A `CampaignOrchestrator` decomposes a complex mission into isolated steps, each assigned a workflow template. The plan is human-approved and immutable. Artifact handoff between steps is explicit. Campaigns are optional — single tasks bypass Tier 0 entirely.
* **Tier 1 — Workflow graph** (static template). Each task (or campaign step) follows a strict state machine defined by a `WorkflowTemplate`. The template is selected at INTAKE (by CLI flag, policy, or LLM classification) and is **immutable for the session**. The LLM never modifies the transition graph at runtime.
* **Tier 2 — Phase-internal planning** (adaptive, tool-gated). The LLM controls what happens *inside* a phase — which tools to call, what plan to propose, what patch to emit. Bounded by budgets and capability gates.

The **Coding Workflow** (default, current):
`INTAKE` -> `CONTRACT` -> `REPO_MAP` -> `PLAN` -> `RETRIEVE` -> `PATCH` -> `CRITIQUE` -> `RUN` -> `FIX (loop)` -> `FINALIZE`

The **Generic Workflow** (for tasks that don't fit a named template):
`INTAKE` -> `PLAN` -> `EXECUTE` -> `EVALUATE` -> `(loop to PLAN or EXECUTE)` -> `FINALIZE`

The **Campaign Lifecycle** (Tier 0, for multi-step missions):
`MISSION_ANALYSIS` -> `OPTION_DEVELOPMENT` -> `PLAN_DRAFTING` -> `HUMAN_REVIEW` -> `DISPATCH` -> `SYNTHESIS`

Future named workflows (Red Team, Data Analysis, etc.) define their own phases but share the same kernel, budgets, ToolBus, and artifact system. Campaigns compose any combination of workflows into a mission.

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
8. **Workflow Templates Are Static:** The `WorkflowTemplate` — its phases, transitions, and schema registry — is selected once at INTAKE and is immutable for the session. The LLM controls what happens *inside* a phase. The kernel controls *which phase runs next.* The LLM picks from a menu of templates; it never writes the menu. This is the one invariant that protects every budget and safety constraint from circumvention. Three-tier orchestration: static campaign graph (Tier 0), static workflow graph (Tier 1), adaptive phase-internal planning (Tier 2).
9. **Campaign Plans Are Static Once Approved:** After the human approves a `CampaignPlan` at HUMAN_REVIEW, the step DAG is frozen. Steps can only be **(a)** retried, **(b)** skipped, or **(c)** aborted. No inserting new steps, no reordering, no changing workflow assignments — unless the campaign returns to HUMAN_REVIEW for re-approval. This prevents "LLM silently expands scope" and ensures the human-approved plan is the plan that executes.
10. **Least Privilege by Intersection:** Every tool call passes through a scope intersection that computes `EffectiveScope = GlobalPolicy ∩ WorkflowScope ∩ StepScope ∩ PhaseScope`. GlobalPolicy is the deny-by-default `CapabilityEngine`. WorkflowScope is `workflow.required_scopes`. StepScope is `step_plan.capabilities_required` (campaign mode) or the full workflow scope (single-task mode). PhaseScope is `workflow.phase_capabilities[current_phase]`. The LLM can never escalate through any layer — it can only narrow. Even if a prompt injection forces a capability request for `net.http` in a coding workflow, WorkflowScope blocks it before it reaches the ToolBus. This is capability-based security: the scope is computed from the plan, not requested at runtime.



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

### Phase 5 – The Repo Map (Context Compression) ✅

**Goal:** Feed the model the project structure deterministically without blowing the context limit.

**Implementation (Phase 5a — Core Infrastructure):**

* **`core/context/models.py`** — `SymbolDef`, `ImportEdge`, `FileSymbols`, `RepoMapData` (dataclasses) + `RepoMapResult` (Pydantic, registered in `PHASE_SCHEMAS`).
* **`core/context/file_discovery.py`** — `git ls-files` + pathlib walk fallback. 50+ extension→language mappings, binary filtering, configurable ignore patterns.
* **`core/context/symbols/`** — `SymbolExtractor` protocol with 3 implementations:
  * `PythonExtractor` — `ast`-based. Full import/signature extraction with type annotations, decorators, constants, async support.
  * `GenericExtractor` — Regex fallback for unknown languages. 9 patterns covering JS/TS/Go/Rust/C/C++/Java.
  * `get_extractor(language)` factory — auto-selects best available extractor per language.
* **`core/context/graph.py`** — `DependencyGraph` with multi-language module resolution (Python dotted paths, C `#include`, Rust `use crate::`, Go package imports, JS/TS relative imports with extension guessing). Relevance ranking (1.0/0.8/0.6/0.4/0.1 by hop distance from targets) and centrality ranking with barrel file damping. Edge resolution stats tracking.
* **`core/context/formatter.py`** — Compact tree-style formatting. Token budget (default 4096) + optional char cap. Whitespace normalization for deterministic output. Metadata header (file/symbol counts, languages, ranking mode).
* **`core/context/visualize.py`** — DOT (Graphviz) and Mermaid graph export with highlight styling and max-node cap.
* **`core/context/cache.py`** — Git-commit-keyed persistent cache (`.judais-lobi/cache/repo_map/<hash>.json`). Clean commit = full cache hit. Dirty state = cache + re-extract only modified files.
* **`core/context/repo_map.py`** — `RepoMap` orchestrator. `build()` → `excerpt_for_task()` → `visualize()`. Dual-use: REPO_MAP phase (overview/centrality) and RETRIEVE phase (focused/relevance by `target_files`).
* **`core/tools/repo_map_tool.py`** — ToolBus-compatible tool with 4 actions: `build`, `excerpt`, `status`, `visualize`.

**Implementation (Phase 5b — tree-sitter Multi-Language Support):**

* **`core/context/symbols/treesitter_extractor.py`** — `TreeSitterExtractor` using modern individual grammar packages (tree-sitter-c, tree-sitter-cpp, tree-sitter-rust, tree-sitter-go, tree-sitter-javascript, tree-sitter-typescript, tree-sitter-java). Full AST symbol + import extraction for 7 languages. Optional dependency: `pip install judais-lobi[treesitter]`.
* **Multi-language graph resolution** — C `#include` path matching, Rust `crate::` → `src/module.rs` resolution, Go package→directory matching, JS/TS relative path resolution with extension guessing (`.js`/`.ts`/`.tsx`/`.jsx`, index files).

**Quality improvements from review feedback:**

* Deterministic output: whitespace normalization in signatures and formatted entries.
* Char cap: hard character limit alongside token budget.
* Edge resolution stats: `edges_resolved`/`edges_unresolved` tracked in graph, wired to `RepoMapResult`.
* Barrel file penalty: `__init__.py`, `index.js`, `mod.rs` etc. damped in centrality ranking (0.3x factor).
* Excerpt header: 3-line metadata header (file/symbol counts, languages, ranking mode, budget).

**Test coverage:** 221 new tests (783 total). 25 tree-sitter tests skip gracefully when tree-sitter is not installed (758 pass on base install, 783 pass with `[treesitter]` extra).

**Definition of Done:** ✅ The Planner role can ingest a 100+ file, multi-language repository architecture in under ~4k tokens. Dependency graph ranks files by relevance to target files. Visualization exports support human inspection. Cache prevents redundant extraction.

### Phase 6 – Repository-Native Patch Engine ✅

**Goal:** Reliable code modification using exact-match constraints.

**Implementation:**

* **`core/patch/parser.py`** — Extracts three block types from raw LLM text: `<<<< SEARCH / ==== / >>>> REPLACE` (modify), `<<<< CREATE / >>>> CREATE` (create), `<<<< DELETE path >>>>` (delete). Delimiters recognized only at line start (after optional whitespace). Path validation rejects absolute paths, `..` traversal, and empty paths at parse time. Produces `List[FilePatch]` (Pydantic models from `core/contracts/schemas.py`).
* **`core/patch/matcher.py`** — Exact byte-match returning `(start_byte, end_byte)` offsets. SHA256 context hash of ±5 lines around each match for disambiguation. On zero matches: 3-stage similarity narrowing pipeline — filter by indent depth (±1 level, hard cap 200 windows), score by token overlap (`re.findall(r'\w+')` set intersection, top 30), rank by `difflib.SequenceMatcher.ratio()` (return top 3 `SimilarRegion` objects). On multiple matches: return all offsets + context hashes. `\r\n → \n` canonicalization before matching, no other normalization.
* **`core/patch/applicator.py`** — Path jailing via `jail_path()`: rejects absolute paths, `..` traversal, and symlink escapes (resolved path must be under repo root). Modify: read UTF-8 with `errors="replace"`, canonicalize, exact-match, replace, preserve `st_mode` bits. Create: strict precondition (fails if file exists), creates parent directories. Delete: strict precondition (fails if file doesn't exist).
* **`core/patch/worktree.py`** — `PatchWorktree` manages one worktree per PatchSet (atomic transaction boundary). Create: `git worktree add -b patch-<name> <path> HEAD`. Merge: `git merge --no-ff patch-<name>` + branch cleanup. Discard: `git worktree remove --force` + `git branch -D`. Writes `.judais-lobi/worktrees/active.json` on create (worktree path, branch name, timestamp). Deleted on discard/merge. Fresh instances recover state from this file, preventing orphaned worktrees after process restart.
* **`core/patch/engine.py`** — `PatchEngine` orchestrates validate (dry-run match), apply (worktree + write), diff (real `git diff`), merge, rollback, status. Apply stops at first file failure, leaving worktree intact for diagnostics.
* **`core/tools/patch_tool.py`** — ToolBus-compatible 6-action tool (validate, apply, diff, merge, rollback, status). All actions serialize results as JSON to stdout. `PatchResult` and `FileMatchResult` provide `to_dict()` helpers. exit_code=0 only on success. Registered as `PATCH_DESCRIPTOR` with per-action scopes.

**Design decisions (reviewed by GPT and Gemini, both converged):**

* Parser is a first-class module — LLMs cannot reliably emit multi-line code inside JSON.
* One worktree per PatchSet — cross-file changes must land atomically.
* `validate` optional in tool, mandatory in kernel — tool stays stateless, kernel sequences policy.
* Similarity budget: 3 candidates, static, narrowing pipeline — diagnostics, not matching.
* Byte-precise match diagnostics (offsets + context hashes) for LLM disambiguation.
* Path jailing in applicator — prevents `<<<< SEARCH ../../../etc/passwd` attacks.
* Delimiters at line-start only — delimiter-like text inside code blocks is never misinterpreted.
* UTF-8 with `errors="replace"` and preserve file mode — consistent with Phase 5 convention.
* Integration tests gated on `shutil.which("git")`, marked `@pytest.mark.integration`.

**Test coverage:** 105 new tests (888 total). 3 integration tests with real git repos.

**Definition of Done:** ✅ Patch protocol produces reproducible edits. Exact-match validation with structured diagnostics. Git worktree isolation for atomic cross-file changes. Automatic rollback on failure. 12 tool descriptors, 31 operations under 13 scopes.

### Phase 7 – Pluggable Workflows, Campaign Orchestrator, Composite Judge & External Critic

**Goal:** Abstract the state machine into pluggable `WorkflowTemplate` objects, add a Campaign Orchestrator for multi-step missions with HITL approval, implement role dispatchers per domain, and add a deterministic scoring hierarchy with an optional external critic.

#### 7.0 WorkflowTemplate & State Machine Abstraction

The kernel currently hardcodes a coding pipeline: `Phase` enum, `TRANSITIONS` dict, `_PHASE_ORDER` list, and `PHASE_SCHEMAS` mapping are all static globals. To support multiple task domains without duplicating kernel logic, these must become parameters of a `WorkflowTemplate` that the `Orchestrator` and `SessionState` consume.

**The refactor is surgical and backward-compatible.** The coding workflow becomes `CODING_WORKFLOW = WorkflowTemplate(...)` — a constant that produces identical behavior to the current hardcoded enum. Zero existing tests break.

**`WorkflowTemplate` dataclass:**

```python
@dataclass(frozen=True)
class WorkflowTemplate:
    name: str                                           # "coding", "generic", "redteam", ...
    phases: Tuple[str, ...]                             # Ordered phase names (strings, not enum)
    transitions: Dict[str, FrozenSet[str]]              # phase -> set of valid next phases
    phase_schemas: Dict[str, Type[BaseModel]]           # phase -> Pydantic model for artifact validation
    phase_order: Tuple[str, ...]                        # Linear progression (excludes branch targets)
    branch_rules: Dict[str, Callable]                   # phase -> function(result) -> next_phase_name
    terminal_phases: FrozenSet[str]                     # {"HALTED", "COMPLETED"}
    phase_capabilities: Dict[str, FrozenSet[str]]       # phase -> allowed capability tags for that phase
    default_budget_overrides: Dict[str, Any] = field(default_factory=dict)
    required_scopes: List[str] = field(default_factory=list)  # Scopes needed by this workflow
    description: str = ""
```

**Key design points:**

* **Phases are strings, not enum members.** This allows workflow templates to define domain-specific phase names (`RECON`, `VULN_MAP`, `EXPLOIT`) without modifying a global enum. `SessionState.current_phase` becomes `str`. Transition validation uses `workflow.transitions[current]`.
* **`branch_rules`** replace the hardcoded `if current == Phase.RUN: ...` logic in `_select_next_phase()`. Each workflow declares its own branching — e.g., coding says "RUN success → FINALIZE, RUN failure → FIX"; generic says "EVALUATE success → FINALIZE, EVALUATE failure → PLAN".
* **`phase_schemas`** replace the global `PHASE_SCHEMAS` dict. `validate_phase_output()` looks up `workflow.phase_schemas[phase_name]`. A workflow can register domain-specific Pydantic models (e.g., `ReconReport`, `ExploitPlan`) for its phases.
* **`phase_capabilities`** define which capability tags are available in each phase, creating a **temporal sandbox**. PLAN can read the repo but not write it. EXECUTE can write but only through the patch engine. The LLM cannot execute while it's supposed to be planning. The CapabilityEngine computes `EffectiveScope` per tool call as the intersection of all applicable layers (see Invariant 10).
* **`default_budget_overrides`** allow workflows to tune budgets — red teaming may need more iterations than coding, data analysis may need longer phase timeouts for large datasets.

**Built-in templates:**

```python
CODING_WORKFLOW = WorkflowTemplate(
    name="coding",
    phases=("INTAKE", "CONTRACT", "REPO_MAP", "PLAN", "RETRIEVE",
            "PATCH", "CRITIQUE", "RUN", "FIX", "FINALIZE", "HALTED", "COMPLETED"),
    transitions={...},      # Identical to current TRANSITIONS dict
    phase_schemas={...},    # Identical to current PHASE_SCHEMAS dict
    phase_order=("INTAKE", "CONTRACT", "REPO_MAP", "PLAN",
                 "RETRIEVE", "PATCH", "CRITIQUE", "RUN"),
    branch_rules={
        "RUN": lambda result: "FINALIZE" if result.success else "FIX",
        "FIX": lambda result: "PATCH",
        "FINALIZE": lambda result: "COMPLETED",
    },
    terminal_phases=frozenset({"HALTED", "COMPLETED"}),
    phase_capabilities={
        "INTAKE":   frozenset({"fs.read"}),
        "CONTRACT": frozenset({"fs.read"}),
        "REPO_MAP": frozenset({"fs.read", "git.read"}),
        "PLAN":     frozenset({"fs.read", "git.read"}),           # Read-only: no execution during planning
        "RETRIEVE": frozenset({"fs.read", "git.read"}),
        "PATCH":    frozenset({"fs.read", "fs.write", "git.write"}),  # Write only through patch engine
        "CRITIQUE": frozenset({"fs.read", "git.read"}),
        "RUN":      frozenset({"fs.read", "verify.run"}),
        "FIX":      frozenset({"fs.read", "git.read"}),
        "FINALIZE": frozenset({"fs.read", "git.read"}),
    },
    description="Full software development pipeline with repo map, patching, and test loop.",
)

GENERIC_WORKFLOW = WorkflowTemplate(
    name="generic",
    phases=("INTAKE", "PLAN", "EXECUTE", "EVALUATE", "FINALIZE", "HALTED", "COMPLETED"),
    transitions={
        "INTAKE":   frozenset({"PLAN", "HALTED"}),
        "PLAN":     frozenset({"EXECUTE", "HALTED"}),
        "EXECUTE":  frozenset({"EVALUATE", "HALTED"}),
        "EVALUATE": frozenset({"PLAN", "EXECUTE", "FINALIZE", "HALTED"}),
        "FINALIZE": frozenset({"COMPLETED", "HALTED"}),
        "HALTED":   frozenset(),
        "COMPLETED": frozenset(),
    },
    phase_schemas={...},    # INTAKE -> TaskContract, PLAN -> ChangePlan, FINALIZE -> FinalReport
    phase_order=("INTAKE", "PLAN", "EXECUTE", "EVALUATE"),
    branch_rules={
        "EVALUATE": lambda result: "FINALIZE" if result.success else "PLAN",
        "FINALIZE": lambda result: "COMPLETED",
    },
    terminal_phases=frozenset({"HALTED", "COMPLETED"}),
    description="Flexible pipeline for arbitrary structured tasks. EXECUTE dispatches to any tool on the bus.",
)
```

**`WorkflowSelector`:**

A function (not a class) that reads the INTAKE artifact and returns a `WorkflowTemplate`. Selection hierarchy:
1. CLI flag: `--workflow coding` → hardcoded choice, no LLM involved.
2. Policy file: `workflow: "generic"` in `PolicyPack` → deterministic.
3. LLM classification: Given the task description, classify into a known template name. If no match → `GENERIC_WORKFLOW`. The LLM picks from a fixed menu; it cannot invent a template.

**Refactored `SessionState`:**

* `current_phase: str` (was `Phase` enum)
* `workflow: WorkflowTemplate` (new field, passed at construction)
* `enter_phase()` validates against `workflow.transitions`

**Refactored `Orchestrator`:**

* `__init__(..., workflow: WorkflowTemplate = CODING_WORKFLOW)`
* `_select_next_phase()` reads `workflow.phase_order` and `workflow.branch_rules`
* `_is_terminal()` checks `workflow.terminal_phases`
* `_validate_and_record()` looks up `workflow.phase_schemas`

**Refactored `validation.py`:**

* `get_schema_for_phase(phase, workflow)` instead of reading the global `PHASE_SCHEMAS`

**Implementation order:**

1. ~~Create `core/kernel/workflows.py` with `WorkflowTemplate` dataclass and `CODING_WORKFLOW` constant.~~ ✅
2. ~~Refactor `SessionState`: `current_phase` becomes `str`, accept `workflow` parameter, validate against `workflow.transitions`.~~ ✅
3. ~~Refactor `Orchestrator`: accept `workflow` parameter, replace hardcoded phase logic with `workflow.branch_rules` and `workflow.phase_order`.~~ ✅
4. ~~Refactor `validation.py`: accept workflow parameter for schema lookup.~~ ✅
5. ~~Update all existing tests to pass `CODING_WORKFLOW` (or default to it). **Zero behavioral change at this step.**~~ ✅
6. ~~Create `GENERIC_WORKFLOW` constant.~~ ✅
7. ~~Proof-of-concept: run a non-coding task through `GENERIC_WORKFLOW` with a stub dispatcher.~~ ✅
8. ~~Write `WorkflowSelector` function.~~ ✅

**Phase 7.0 status: COMPLETE.** 86 new tests (974 total). `Phase` is now `str, Enum`. CODING_WORKFLOW produces identical behavior to Phase 6 — zero existing tests broken. GENERIC_WORKFLOW proven end-to-end with evaluate-failure loop, budget halting, and phase retry.

**What this enables (future, not Phase 7 scope):**

Domain-specific workflows are defined as additional `WorkflowTemplate` constants with their own phases, schemas, tools, and capability profiles. Examples:

* **Red Team Workflow:** `INTAKE → RECON → VULN_MAP → EXPLOIT_PLAN → EXECUTE → EVALUATE → FINALIZE`. Registers `ReconReport`, `ExploitPlan`, `ExploitResult` schemas. Requires `net.scan`, `net.exploit` scopes. `BwrapSandbox` drops `--unshare-net` when these scopes are granted. Uses `RedTeamDispatcher` for role prompts.
* **Data Analysis Workflow:** `INTAKE → DATA_MAP → PLAN → TRANSFORM → ANALYZE → FINALIZE`. Registers `DataProfile`, `TransformPlan`, `AnalysisResult` schemas. Uses `DATA_SCI` capability profile (`fs.read`, `fs.write`, `python.exec` with pandas/numpy venv). Uses `DataDispatcher` for role prompts.
* **Domain-specific tool packages:** `core/tools/redteam/` (nmap, gobuster, metasploit_rpc), `core/tools/data/` (sql_query, pandas_exec, plot_generator). Same ToolBus, same capability gating.
* **Domain-specific role dispatchers:** `CodeDispatcher` (Planner/Coder/Reviewer), `RedTeamDispatcher` (OSINT_Analyst/Exploit_Dev/Vuln_Assessor), `DataDispatcher` (Data_Engineer/Statistician/Visualizer). JudAIs and Lobi remain persona overlays applied to any dispatcher.

These are **not Phase 7 deliverables** — they are future workflow templates that the Phase 7 abstraction makes trivially addable. Phase 7 delivers the mechanism (`WorkflowTemplate`, `CODING_WORKFLOW`, `GENERIC_WORKFLOW`, `WorkflowSelector`). Future phases deliver the content.

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
**Status:** ✅ COMPLETE.

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

#### 7.4 Campaign Orchestrator (Tier 0 — Workflow of Workflows)
**Status:** ✅ COMPLETE.

**Motivation:** A single workflow handles one task. Real missions require multiple coordinated tasks — analyzing data *then* building a model, mapping an attack surface *then* exploiting vulnerabilities, refactoring a module *then* updating all callers. The Campaign Orchestrator is a thin macro loop that decomposes complex missions into a DAG of steps, gets human sign-off, and dispatches each step as an isolated workflow with explicit artifact handoff.

The key insight: campaigns are **orchestration of artifacts and permissions**, not "a smarter agent." The kernel stays deterministic; the plan becomes the executable artifact; the human owns the moment where risk and scope get locked.

**Campaign Lifecycle:**

```text
MISSION_ANALYSIS       Ingest raw user prompt. Identify constraints, domains, success criteria.
        │
OPTION_DEVELOPMENT     Generate potential approaches (strategies, not implementations).
        │
PLAN_DRAFTING          Break chosen approach into a DAG of MissionSteps.
        │               Assign a WorkflowTemplate to each step.
        │               Declare artifact handoff between steps.
        │
HUMAN_REVIEW           *** Execution halts. ***
        │               Present plan to human ($EDITOR file-edit loop).
        │               Human approves, rejects, or modifies.
        │               Capability grants locked per step.
        │               Plan frozen on approval (Invariant 9).
        │
DISPATCH               Loop through approved steps in DAG order.
        │               For each step: spawn Orchestrator with assigned workflow,
        │               materialized handoff_in/ bundle, budgets, capabilities.
        │               Each step runs in an isolated child session.
        │
SYNTHESIS              Compile declared exports from all steps into campaign report.
```

**`CampaignPlan` Schema:**

```python
class ArtifactRef(BaseModel):
    step_id: str                    # Source step
    artifact_name: str              # e.g., "cleaned_data.csv", "recon_report.json"

class CampaignLimits(BaseModel):
    max_steps: int = 10
    max_total_tool_calls: int = 500
    max_total_tokens: int = 2_000_000
    deadline_seconds: Optional[int] = None

class MissionStep(BaseModel):
    step_id: str
    description: str
    target_workflow: str            # Template ID: "coding", "generic", "redteam", "datasci"
    capabilities_required: List[str]  # Hard requirement: ["net.scan", "fs.write"]
    capabilities_optional: List[str] = []  # Nice-to-have
    risk_flags: List[str] = []      # ["network-active", "writes-repo", "installs-deps"]
    inputs_from: List[str] = []     # step_ids this step depends on (DAG edges)
    handoff_artifacts: List[ArtifactRef] = []  # Explicit artifact imports from upstream
    exports: List[str] = []         # Artifact names this step declares as output
    success_criteria: str
    budget_overrides: Dict[str, Any] = {}

class CampaignPlan(BaseModel):
    campaign_id: str
    objective: str
    assumptions: List[str]
    steps: List[MissionStep]
    limits: CampaignLimits = CampaignLimits()
```

**DAG Validation (enforced in code, nudged in prompts):**

* All `step_id` values unique
* All `inputs_from` references point to existing `step_id` values
* DAG is acyclic (topological sort succeeds)
* Every step has at least one success criterion with a measurable outcome
* Every step declares its exports
* `target_workflow` matches an installed template name

**Artifact Handoff — Artifacts Over Chat:**

Each workflow step starts with a clean slate, seeded only with the crystallized artifacts of upstream steps. No conversation history, no chat log teleportation, no mystery meat context.

The handoff is literal file operations:
1. Step N finishes, writes outputs to `handoff_out/`
2. `CampaignOrchestrator` marks Step N complete
3. `CampaignOrchestrator` initializes Step N+1
4. Parent copies declared `ArtifactRef` items from Step N's `handoff_out/` into Step N+1's `handoff_in/`
5. Step N+1's `INTAKE` phase reads from `handoff_in/` — not from Step N's session

**Session Namespace Design:**

```text
sessions/<campaign_id>/
  campaign.json          # CampaignPlan + current state (frozen after HUMAN_REVIEW)
  synthesis/             # Final compiled outputs
  steps/
    <step_id>/
      workflow.json      # Selected WorkflowTemplate
      step_plan.json     # StepPlan contract (intent, capabilities, success criteria, digest)
      scope_grant.json   # What was requested vs granted, with reasons
      artifacts/         # Step-local artifacts (standard session layout)
      handoff_in/        # Materialized imports from upstream steps
      handoff_out/       # Exports available to downstream steps
```

Three properties:
1. **Isolation:** Each step has its own session + artifacts. Steps cannot read each other's artifacts directly.
2. **Explicit handoff:** Only declared artifacts cross step boundaries, via `handoff_in/` / `handoff_out/`.
3. **Traceability:** Campaign report can cite exactly which step produced what, from which artifact.

**StepPlan — The Execution Contract:**

If `CampaignPlan` is "what and why," each step needs a `StepPlan` that is "how, with receipts." The StepPlan is generated in the step's PLAN phase (before EXECUTE) and declares the step's intent, boundaries, capabilities, and failure strategy. It is a **contract**, not a script — it declares what the step will accomplish and what it needs, not every individual API call.

```python
class StepPlan(BaseModel):
    step_id: str
    workflow_id: str                          # Must match an installed WorkflowTemplate
    objective: str
    inputs: List[ArtifactRef] = []            # What this step reads from handoff_in/
    outputs_expected: List[ArtifactRef] = []  # What this step will write to handoff_out/
    capabilities_required: List[str] = []     # Capability tags (not tool names) needed
    success_criteria: List[str]               # Measurable outcomes
    rollback_strategy: Literal["retry", "backtrack", "abort", "human_review"] = "backtrack"
    digest: str = ""                          # SHA256 of ordered fields — for caching + replay detection
```

**StepPlan is NOT a BPMN script.** It does not enumerate individual tool calls or action sequences. The workflow's phases handle sequencing; the ToolBus handles access control; the kernel handles retry logic. The StepPlan declares *intent and boundaries*. The existing phase artifacts (`ChangePlan`, `PatchSet`, `RunReport`) remain the action-level plans within each phase.

**StepPlan validation rules:**
* `workflow_id` must match an installed `WorkflowTemplate`
* `capabilities_required` must be a subset of `workflow.required_scopes` (can't request what the workflow doesn't offer)
* `outputs_expected` artifact paths must resolve under the step's `handoff_out/` or `artifacts/`
* Network/file capabilities require corresponding grants in the campaign's approval

**StepPlan stored as:** `sessions/<campaign_id>/steps/<step_id>/step_plan.json`

**ActionDigest** — the `digest` field is a SHA256 hash of the StepPlan's ordered fields (objective, inputs, outputs, capabilities, success criteria). Stored in the session and used for:
* **Caching:** If a step is retried with an identical digest, prior results can be reused.
* **Replay detection:** "This step executed under digest X, produced artifacts A/B/C."
* **Audit:** Deterministic proof that the agent executed what was approved.

**EffectiveScope — Least Privilege by Intersection:**

The CapabilityEngine computes the effective tool scope for every tool call as a strict intersection:

```
EffectiveScope = GlobalPolicy ∩ WorkflowScope ∩ StepScope ∩ PhaseScope
```

| Layer | Source | What it constrains |
|-------|--------|--------------------|
| **GlobalPolicy** | `CapabilityEngine` (deny-by-default, grants, god mode) | What the kernel allows at all |
| **WorkflowScope** | `workflow.required_scopes` | What the workflow template permits (coding gets repo tools, generic gets minimal I/O) |
| **StepScope** | `step_plan.capabilities_required` (campaign) or full WorkflowScope (single-task) | What this specific step declared it needs |
| **PhaseScope** | `workflow.phase_capabilities[current_phase]` | What the current phase allows (PLAN = read-only, EXECUTE = read+write) |

The intersection means the LLM can never escalate — it can only narrow. A coding workflow cannot gain `net.scan` even if a prompt injection requests it. A PLAN phase cannot write files even if the workflow allows writes in EXECUTE. Capabilities are the stable abstraction layer — tools change, capabilities are the API contract.

**HUMAN_REVIEW Gate:**

When the `CampaignOrchestrator` reaches HUMAN_REVIEW:

1. Serialize `CampaignPlan` to `campaign.plan.json` (or YAML) on disk
2. Open in `$EDITOR` (like `git rebase -i` or `git commit`)
3. On save/close: validate strictly via Pydantic. If invalid: show errors, reopen editor
4. If valid: freeze plan (Invariant 9) and proceed to DISPATCH

The approval UI also shows and locks **capability grants**:
* Step list + workflow assignments
* Capabilities requested per step (required vs. optional)
* Whether each capability is currently permitted by policy
* User can: approve all, approve but downgrade capabilities, approve with per-step overrides

**How Campaigns Preserve the "Static Workflows" Doctrine:**

Campaigns do not violate "Workflow Templates Are Static" because:
* Campaigns don't rewrite workflow graphs — they *select* from installed templates
* Step execution is bounded by the selected workflow's template, budgets, and transitions
* Adaptation happens inside phases (Tier 2), not in the campaign graph (Tier 0) or workflow graph (Tier 1)
* The Campaign layer is a **workflow router + artifact courier** with a human checkpoint

**What CampaignOrchestrator is NOT:**

* Not a second, less-audited orchestrator — it has exactly 6 phases, all deterministic
* Not an LLM execution loop — the LLM generates the plan, the human approves it, the system dispatches it
* Not a replacement for `--task` — single tasks bypass Tier 0 entirely

**Implementation tasks (Campaign + StepPlan + Scope Intersection):**

15. Namespace + session layout for parent/child steps (`campaign_id/step_id` dirs) in `SessionManager`
16. `CampaignPlan` + `MissionStep` + `CampaignLimits` + `ArtifactRef` schemas in `core/contracts/campaign.py`
17. `StepPlan` schema with ActionDigest (SHA256 hash of ordered fields for caching + replay)
18. DAG validator (acyclic, unique step_ids, artifact declarations, template existence)
19. StepPlan validator (workflow_id exists, capabilities ⊆ workflow.required_scopes, outputs under handoff_out/)
20. HUMAN_REVIEW file-edit loop (`$EDITOR` open + Pydantic revalidation on save)
21. `phase_capabilities` field on `WorkflowTemplate` — per-phase capability allowlists
22. EffectiveScope intersection in CapabilityEngine: `Global ∩ Workflow ∩ Step ∩ Phase` computed per tool call
23. `scope_grant.json` artifact per step: what was requested vs granted, with reasons
24. Step dispatcher: instantiate existing `Orchestrator` with selected workflow template, `handoff_in/` bundle, computed `EffectiveScope`, budget overrides
25. Artifact handoff: `handoff_out/` → `handoff_in/` materialization between steps
26. Synthesis step: compose final campaign report from declared step exports
27. `CampaignOrchestrator` macro loop: MISSION_ANALYSIS → OPTION_DEVELOPMENT → PLAN_DRAFTING → HUMAN_REVIEW → DISPATCH → SYNTHESIS
28. CLI: `--campaign "mission description"` flag, `--campaign-plan plan.json` for pre-authored plans
29. Contract-first planner prompt: explicitly forbid adding steps after approval, referencing chat history beyond user prompt + constraints, outputting anything except valid `CampaignPlan` JSON

**Other implementation tasks (Workflows, Judge, Critic):**

1. `WorkflowTemplate` dataclass + `CODING_WORKFLOW` + `GENERIC_WORKFLOW` (see 7.0)
2. Refactor `SessionState`, `Orchestrator`, `validation.py` to accept workflow parameter
3. `WorkflowSelector` function (CLI flag → policy → LLM classification → GENERIC fallback)
4. Proof-of-concept: non-coding task through `GENERIC_WORKFLOW` with stub dispatcher
5. `CodeDispatcher` (Planner/Coder/Reviewer prompts — extracted from future role system)
6. `GenericDispatcher` (PLAN/EXECUTE/EVALUATE prompts for arbitrary tasks)
7. `ExternalCriticBackend` interface (HTTP client to frontier API, uses `core/runtime/backends/` pattern)
8. `CritiquePack` builder (assembles minimal artifact payload from session state)
9. `Redactor` (strict by default, configurable per policy)
10. `ExternalCriticReport` schema + Pydantic validation
11. Critic trigger policy (when to call, what to send, what to do with verdicts)
12. Orchestrator interceptor hooks on phase transitions (workflow-aware, not hardcoded to coding phases)
13. CLI: `--workflow <name>` flag to select workflow, `--critic` flag to enable, `--no-critic` to force off
14. Manual invocation: `lobi critic --session <id>` for post-hoc review of any session

**Suggested implementation order (low drama, high leverage):**

Phase 7 breaks into four sub-phases that can be delivered incrementally:
1. **7.0** — ~~WorkflowTemplate abstraction + phase_capabilities + EffectiveScope intersection.~~ **COMPLETE** (974 tests). Pure refactor — `CODING_WORKFLOW` produces identical behavior to Phase 6. `GENERIC_WORKFLOW` proven end-to-end.
2. **7.1–7.2** — ~~Composite Judge + Candidate Sampling (tasks 5–6).~~ **COMPLETE** (1059 tests). `CompositeJudge` with 3-tier scoring (test/lint/LLM review). `CandidateManager` with worktree isolation. `JudgeReport` registered as CRITIQUE phase schema. `BudgetConfig.max_candidates` field. `GPUProfile` stub.
3. **7.3** — ~~External Critic (tasks 7–14).~~ **COMPLETE** (Phase 7.3 implemented).
4. **7.4** — ~~Campaign Orchestrator + StepPlan + scope grants (tasks 15–20, 23–29).~~ **COMPLETE**. Requires 7.0 (WorkflowTemplate registry + EffectiveScope). Independent of 7.1–7.3.

**Definition of Done:** State machine is parameterized by `WorkflowTemplate` with `phase_capabilities` enforcing temporal sandboxing. `CODING_WORKFLOW` produces identical behavior to Phase 6 (all 888+ tests pass unchanged). `GENERIC_WORKFLOW` can execute a non-coding task end-to-end. `WorkflowSelector` picks template at INTAKE. EffectiveScope intersection (`Global ∩ Workflow ∩ Step ∩ Phase`) is computed and enforced on every tool call. Generates competing patches (coding workflow), grades them deterministically, discards test failures, selects the proven winner. External critic is fully operational when configured, fully absent when not — system runs identically in both modes. Critic refusals never halt the pipeline. Campaign Orchestrator can decompose a multi-step mission into a `CampaignPlan` DAG with `StepPlan` contracts per step, present them for HITL approval, dispatch isolated child workflows with computed scope grants and artifact handoff, and synthesize a final report. ActionDigest hashes enable caching, replay detection, and audit. Single tasks (`--task`) bypass the campaign layer entirely — EffectiveScope still applies (Global ∩ Workflow ∩ Phase, with StepScope = WorkflowScope).

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
| **Workflow Mismatch** | Task requires phases not in selected template | Halt with diagnostic | `workflow_mismatch.json` | User re-runs with `--workflow <correct>` |
| **Unknown Workflow** | `--workflow <name>` not in registry | Reject at CLI parse time | N/A | User selects from known templates |
| **Campaign DAG Invalid** | Cyclic dependencies, missing step_ids, undeclared artifacts | Reject at PLAN_DRAFTING, return to LLM | `campaign_dag_error_<n>.json` | Burn 1 retry in PLAN_DRAFTING phase |
| **Campaign HITL Rejected** | Human rejects plan at HUMAN_REVIEW | Return to PLAN_DRAFTING or abort | `campaign_rejected.json` | Re-draft or user aborts campaign |
| **Campaign Step Failed** | Child workflow halts or exceeds budget | Mark step failed, continue or abort per policy | `step_<id>_failed.json` | Retry step, skip step, or abort campaign |
| **Handoff Artifact Missing** | Upstream step didn't produce declared export | Block downstream step, surface to user | `handoff_missing_<id>.json` | Retry upstream step or user intervenes |
| **Step Invalidates Downstream** | Step results contradict downstream assumptions | Halt dispatch, return to HUMAN_REVIEW (Invariant 9) | `campaign_replan_<n>.json` | Human re-approves modified plan or aborts |
| **Scope Overreach** | StepPlan requests capabilities outside WorkflowScope | Reject at StepPlan validation, before execution | `scope_denied_<id>.json` | Re-generate StepPlan with narrower scope |

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
  * Not a framework where LLMs design their own execution pipelines. The LLM operates within a phase; the kernel decides which phase runs next. Workflow templates are static, auditable, and human-authored. Campaign plans are LLM-proposed but human-approved and frozen — the LLM drafts the DAG, the human owns the approval gate, and no step can be inserted after HUMAN_REVIEW without returning for re-approval.

## 7. Design Philosophy

* **Artifacts over Chat:** State is on disk, not in a sliding text window.
* **Capabilities over Trust:** The model is assumed hostile; the sandbox and network gates keep it safe. Scope is computed from the intersection of policy, workflow, step plan, and phase — never requested freely at runtime.
* **Capabilities over Tools:** The permission model uses stable capability tags (`repo.read`, `net.scan`, `verify.run`), not tool names. Tools are implementation details that change; capabilities are the API contract. A `StepPlan` declares it needs `repo.write`; the kernel maps that to whichever tool provides it. This keeps plans evolvable without breaking old sessions.
* **Determinism over Vibes:** Tests dictate success; LLMs only suggest code.
* **Budgets over Infinite Loops:** Everything has a timeout and a retry cap.
* **Dumb Tools, Smart Kernel:** Tools execute. They do not decide, retry, repair, or escalate. All intelligence lives in the kernel. If a tool contains an `if/else` about what to do next, it has too much agency.
* **Static Graphs, Adaptive Phases:** The workflow template (phase topology, transitions, schemas) is static and auditable. The LLM controls what happens *inside* a phase — which tools to call, what plan to propose, what patch to emit. The LLM never controls *which phase runs next.* This is three-tier orchestration: rigid campaign graph (Tier 0), rigid workflow graph (Tier 1), flexible phase-internal loop (Tier 2). If the LLM can rewrite any transition graph, every budget and safety constraint has a backdoor.
* **Plans over Prompts:** Complex missions are decomposed into a structured `CampaignPlan` artifact — a DAG of steps with explicit workflow assignments, artifact declarations, and capability requests. The human reviews and freezes this plan before a single tool call fires. The plan is the executable artifact. The human owns the moment where risk and scope get locked. This is the difference between "run tasks" and "run missions."
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

### Agentic Mode — Single Task (New)
```bash
lobi --task "add pagination to the /users endpoint"
lobi --task "fix the race condition in worker.py" --grant net.any
lobi --task "analyze sales.csv and find outliers" --workflow generic
lobi --task "recon target.example.com" --workflow redteam --grant net.scan
```

* `--task` enters the full state machine (INTAKE through FINALIZE). Bypasses Tier 0 (campaign layer).
* `--workflow <name>` selects a `WorkflowTemplate` explicitly. If omitted, `WorkflowSelector` classifies at INTAKE (default: `coding` for repo-context tasks, `generic` for everything else).
* `--grant` pre-authorizes capability scopes for the session.
* Session artifacts are written to `sessions/<timestamp_taskid>/artifacts/`.
* `workflow.json` records which template was used (for deterministic replay).
* The user can inspect, resume, or replay any session from its artifacts.

### Campaign Mode — Multi-Step Missions (New)
```bash
lobi --campaign "migrate the auth system from sessions to JWT"
lobi --campaign "full red team assessment of example.com" --grant net.scan,net.exploit
lobi --campaign-plan ./mission.json                # Pre-authored plan, skip LLM drafting
judais --campaign "analyze sales data, build model, deploy API" --workflow-override step3=coding
```

* `--campaign` enters the Campaign Orchestrator (Tier 0): MISSION_ANALYSIS → OPTION_DEVELOPMENT → PLAN_DRAFTING → HUMAN_REVIEW → DISPATCH → SYNTHESIS.
* `--campaign-plan <file>` loads a pre-authored `CampaignPlan` JSON, skipping MISSION_ANALYSIS through PLAN_DRAFTING. Still requires HUMAN_REVIEW.
* `--workflow-override <step>=<template>` forces a specific workflow for a named step (overrides LLM's assignment).
* At HUMAN_REVIEW, the plan is serialized and opened in `$EDITOR`. The user approves, modifies, or rejects. Capability grants are locked per step at approval time.
* Campaign sessions are written to `sessions/<campaign_id>/` with per-step child sessions under `steps/<step_id>/`.
* Each step runs in isolation with explicit artifact handoff — no shared state, no chat log transfer.

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
  │       │                              Phase 7 (Workflows + Campaign + Judge)
  │       │                                ├── 7.0: WorkflowTemplate abstraction
  │       │                                ├── 7.1-7.2: Judge + Candidates
  │       │                                ├── 7.3: External Critic
  │       │                                └── 7.4: Campaign Orchestrator
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
* Phase 7.0 (WorkflowTemplate) is a prerequisite for 7.1–7.4 but can be implemented and tested independently.
* Phase 7.4 (Campaign Orchestrator) requires 7.0 (WorkflowTemplate registry) but is independent of 7.1–7.3 (Judge/Critic). Can ship before or after the critic subsystem.
* Phase 10 (Benchmarks) baseline capture starts in Phase 0; the full suite is built last but metrics collection is continuous.
* Local inference bring-up (Phase 8) can begin prototyping as soon as the runtime interface is defined (Phase 1), though full integration requires Phase 3 contracts.
* Domain-specific workflow templates (RedTeam, DataSci) can be added at any point after Phase 7.0 ships — they are content, not infrastructure. Campaign mode can compose any combination of installed templates.

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
