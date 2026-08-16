# ROADMAP.md — where judais-lobi is going

**This is the only roadmap.** Until 15 Aug 2026 the repository carried three
overlapping plans: this file (Feb 2026, Phases 0–10), `PHASE_8.md` (the Feb
Phase 8 plan plus its closing disposition) and `NEXT_STEPS.md` (Aug 2026,
Phases 0–6). Two of them numbered their phases from zero, so the repository had
two "Phase 1"s and two "Phase 3"s that meant different things. All three are
folded in here, under **one** numbering that only ever moves forward:
February's Phases 0–8 are the past, and the plan continues at **Phase 9**.
`NEXT_STEPS.md` and `PHASE_8.md` are deleted; git keeps the originals.

Sections 1–4 are live. Section 5 is history, marked as such, and kept because
docstrings and the README quote it.

---

## 1. Where we are

**v0.9.0**, 15 Aug 2026. 2,338 tests collected; ~23.2k non-test lines in
`core/`+`judais/`+`lobi/`, ~26k lines of tests.

For two weeks this framework ran in production as **Tai**, the mission agent
inside a separate platform: a 20B local model, an MCP tool plane of ~20
governed tools, a browser pane reading the NDJSON mission stream, real
analysts, a recorded bake-off against a second harness, and a behavioural eval
that went from 6-of-10 missions reporting `0/0 … grounded` to 10/10 with 0%
error. That pressure produced the best parts of what is here — the grounding
validator, the mission stream and its contract, the MCP client, the skill
manifest as the only content channel, the swarm's failure containment — and it
is recorded in §5.9. What it also exposed is that a framework can make *one*
deployment truthful while its *default* deployment is still not one you would
run unattended. 0.9.0 closed the first half of that gap. The rest is §2.

### 1.1 The six properties

"Capable, not a toy" is not a feeling. It is six properties, and a framework
has them **by default, not by injection**. Every phase in §2 exists to finish
one of them.

1. **Safe by default** — code and shell run isolated; tools are deny-by-default
   with scopes; every action is audited; a human gate is a durable record.
2. **Durable** — a run survives the process: resumable, replayable, exact.
3. **Bounded** — steps, wall-clock, bytes, tokens, dollars — each a recorded
   outcome, never a silent truncation.
4. **Observable and measurable** — one event stream, one usage ledger, one
   eval harness that replays recorded runs and scores them the same way twice.
5. **One runtime** — a single loop that every mode (chat, mission, swarm,
   coding kernel) composes, so a fix lands once.
6. **Embeddable** — a library API first, the CLI second; a platform integrates
   it in fifty lines and pins a contract version.

### 1.2 The honest gap table

Written 15 Aug 2026 against `master` at 0.9.0. Every row was re-checked in the
tree on the day it was written; struck rows are what 0.8.2 and 0.9.0 closed.
Re-verify before acting on any of it.

| Gap | Where it lives | Property |
|---|---|---|
| ~~**No sandbox by default.**~~ Closed 0.9.0: `select_sandbox` picks bwrap wherever it exists, the child env is an allow-list, and the choice rides `mission_started.sandbox`. **Still open:** the `fs` tool is in-process pathlib and no sandbox bounds it. | `core/tools/sandbox.py`, `core/tools/fs_tools.py` | 1 |
| ~~**Allow-everything policy by default.**~~ Closed 0.9.0: `Tools()` builds `SAFE`, `--profile`/`JUDAIS_LOBI_PROFILE` opt up, refusals name the scope and the profile that grants it, and `AuditLogger` is on every default bus (`audit_ref`). **Still open:** god-mode and the preflight hook are constructor parameters nothing passes; the kernel path governs through `set_scope_constraints`, a second surface. | `core/tools/__init__.py`, `core/policy/`, `core/kernel/orchestrator.py` | 1 |
| ~~**Tracebacks leak absolute paths.**~~ Closed 0.9.0: one redactor at the emitter. **Still open:** it covers the mission stream and mission-mode stderr, not the kernel/campaign/chat error prints. | `core/redact.py`, `core/cli.py` | 1 |
| **The real agent path persists nothing.** A CLI mission writes only the optional NDJSON; `SessionManager` (non-atomic `write_text`) serves only the kernel path the CLI does not reach. The audit file is append-only but never fsync'd. | `core/sessions/manager.py`, `core/policy/audit.py` | 2 |
| **No wall-clock bound, no cancellation.** Step count and per-tool timeouts only; a contended local model can hang a turn forever. | `core/runtime/mission.py` (`max_steps`) | 3 |
| **No usage or cost accounting.** Only char/4 estimates for compaction — `prompt_tokens`/`completion_tokens` appear nowhere in `core/`. | grep | 3, 4 |
| **No reproducible eval.** The Aug 2026 measurements live in docstrings; in-repo there is one recorded-fabrication fixture and an MCP stub. | `tests/fixtures/`, `tests/mcp_stub_server.py` | 4 |
| **Two agent runtimes.** `MissionRunner`/`SwarmRunner` (JSON protocol, MCP, CLI) and the kernel `Orchestrator`+roles (state machine, sessions, judge, patch) do not share sessions, budgets or governance. 0.8.2 gave result bounding one owner (`core/bounding.py`) and windowed the mission's conversation; 0.9.0 put the kernel's role prompts through the same window owner. The *runtimes* are still two. | `core/runtime/mission.py` vs `core/kernel/` | 5 |
| **No token streaming or constrained decoding in agentic runs.** Missions call `chat(stream=False)`; the probed grammar/tool-choice path is deliberately unwired. | `core/cli.py` | 4, 6 |
| **Thin provider layer.** Three providers; retry only on refused connect, and the timeout/retry policy is imported by Mistral from the local backend rather than owned somewhere neutral. (0.8.2 took Mistral off `curl` and onto httpx.) | `core/runtime/backends/` | 6 |
| **Built, tested, unreachable.** `runtime/reading.py` (no production importer), `policy/god_mode.py` (`GodModeSession` is exported and never constructed), `Agent.run_task` (no caller). The external critic and `critic/triggers.py` are reached only from `Orchestrator`, and only when a `critic=` is injected — nothing in `core/` injects one. **Closed 0.9.0:** `policy/audit` is on every default bus. **Deleted rather than wired, 0.9.0:** `kv_prefix.py`, `runtime/gpu.py`. | importer scans | 4 |

None of this is a design flaw. It is the honest shape of a framework whose
production fortnight was spent making one deployment truthful. The work in §2
is making the *default* deployment trustworthy.

---

## 2. The plan

One numbering, forward only. February's Phases 0–8 are the as-built past;
Phases 9–13 are the work. Each phase names the seam it touches and, where the
answer already exists somewhere, where to take it from. Lane it: builder in a
worktree, tests in the file's idiom, mutation-checked, reviewer lane, conductor
merges. Version bump every phase.

### 2.1 The index

| Phase | What | State |
|---|---|---|
| 0 | Dependency injection, test harness & baseline | ✅ 73 tests, DI seams |
| 1 | Extract runtime & stabilise the spine | ✅ runtime extracted, `elf.py` provider-free |
| 2 | Kernel state machine & hard budgets | ✅ state machine, budgets, orchestrator |
| 3 | Session artifacts, contracts & KV prefixing | ✅ `elf.py` deleted, Agent class, Pydantic contracts, `SessionManager` (the KV-prefix builder was deleted unused at 0.9.0) |
| 4 | MCP-style tool bus, sandboxing & capability gating | ✅ `ToolBus`, `CapabilityEngine`, `BwrapSandbox`, profiles, god mode, audit |
| 5 | The repo map (context compression) | ✅ 3-tier extraction, dependency graph, ranked excerpts, caching |
| 6 | Repository-native patch engine | ✅ parser, exact-match matcher, path-jailed applicator, worktree isolation |
| 7 | Pluggable workflows, campaign orchestrator, composite judge & external critic | ✅ 7.0–7.4 |
| 8 | Retrieval, context discipline & local inference | ✅ closed 0.9.0 — disposition in §5.10 |
| — | *Release 0.8.0 — the separation* | ✅ contract as data, `tai` entry point, `mission` extra, SIGTERM close, `PLATFORMS.md` |
| — | *Release 0.8.2 — the honest stream* | ✅ swarm silence, mission window, one bounder, httpx Mistral, a bwrap that runs |
| — | *Release 0.9.0 — safe by default* | ✅ property 1, less its residuals (§1.2) |
| ~~9~~ | ~~Performance optimisation (TRT-LLM / vLLM tuning)~~ | **Retired** — §2.3 |
| 9 | Durable and bounded (0.10) | properties 2 and 3 |
| 10 | Measurable (0.11) | property 4; absorbs February's Phase 10 |
| 11 | One runtime (0.12) | property 5 |
| 12 | Providers and streaming (0.13) | properties 4 and 6 |
| 13 | Embeddable (1.0) | property 6 |

### 2.2 As built

February's Phases 0–8 are detailed in §5.4, with Phase 8's milestone-by-
milestone disposition in §5.10. They keep their numbers, so the docstrings that
cite "ROADMAP Phase 8" stay true.

Three releases of August 2026 did phase-sized work without taking a phase
number. `NEXT_STEPS.md` numbered them 0, 0.5 and 1; that numbering is retired
here so no reader meets a second Phase 1.

**0.8.0 — the separation (15 Aug 2026).** Contract as data
(`core/runtime/contract.py`: `SCHEMA_VERSION`, `EVENTS`, `FIELDS`, `OPTIONAL`,
`OUTCOMES`, `CLI_FLAGS`, `ENV_VARS`, `EXIT_CONTRACT`, `conforms`); every
platform particular removed from `core/`; the `tai` entry point and the
`mission` extra; `close_on_sigterm`; swarm grounding routed through the shared
renderer; `PLATFORMS.md`; the reference platform pinning the release by tag and
asserting against `contract`.

**0.8.2 — the honest stream (15 Aug 2026).** The mission stream opens before
triage, so a slow `--swarm` router no longer looks like a dead harness, and a
repair turn stops being spent in silence. The mission's conversation is
windowed, not only each result. One owner for the tool-result cut
(`core/bounding.py`) and three callers that stopped having opinions. Mistral
off `curl` and onto httpx — the key leaves `argv`, the call gets a timeout, the
stream closes itself. The bwrap backend run against reality: a network the
profile decides, rlimits it actually applies, and a `run_python` whose program
exists inside the sandbox. `faiss-cpu` became an extra; `core/bootstrap.py` and
`core/tools/recon/` — two corners nothing had imported since Phase 3 — were
deleted.

**0.9.0 — safe by default (15 Aug 2026).** Property 1, minus the residuals
listed in §1.2. Sandbox on by default: `select_sandbox` is the one owner of the
choice, `bwrap` wherever bubblewrap exists, `NoneSandbox` only under an
explicit `--unsandboxed`/env opt-out that is *announced* as
`mission_started.sandbox`, with a stripped child env and `run_python` off
`argv`. Deny-by-default policy: `Tools()` builds `SAFE`, not an
allow-everything bus; `--profile dev|ops|god` opts up; every refusal names the
scope and the profile that grants it. Audit on the default bus: append-only
JSONL, secret-redacted, and the stream names the file (`audit_ref`). The
manifest code gate: a skill that names a code-plane tool is refused unless the
manifest declares isolation and the bus provides it. One redactor at the
emitter, so the contract clause warning that tracebacks leak absolute paths
became false. The kernel's role prompts joined the same context-window owner
the mission uses, and their compactions became a phase artifact rather than a
shrug. `kv_prefix.py` and `runtime/gpu.py` were deleted rather than wired.

### 2.3 Retired: February's Phase 9 (TRT-LLM / vLLM tuning)

February's Phase 9 asked this repository to auto-detect GPU profiles, adopt FP8
KV cache, batch candidate generation across devices, and publish tuning
profiles for three reference machines. **That work is not this repository's.**
The local backend talks to an OpenAI-compatible *serving endpoint*, and that
endpoint is routinely another box: tensor parallelism, quantisation, batching
and FP8 are decisions made where the weights are, by vLLM or TRT-LLM, and a
client that has opinions about them is a client answering from the wrong
machine. 0.9.0 acted on that: `core/runtime/gpu.py` and the client-side VRAM
cap it fed were deleted, and the context window is now sized by the endpoint's
own `max_model_len` probe.

What survives of it moves rather than dies. The **performance telemetry** bullet
— tokens/sec, time-to-first-token, tail latency — is the client's business
after all, because the client is what observes it; it becomes the usage/telemetry
**ledger** in the new Phase 9, measured per run and carried on
`mission_finished`, next to tokens and cost. The hardware bullets stay as
history in §5.11, where the reference-profile notes are kept verbatim for
whoever stands the serving layer up.

### 2.4 Phase 9 — durable and bounded (0.10)

Properties 2 and 3.

- **A thread durability primitive.** Monotonic per-thread `seq`, fsync'd
  append-only JSONL, atomic `os.replace` for metadata, `since(cursor)` +
  `follow()`. The reference platform has one and paid for the bug that teaches
  it: writing the whole thread back stamped a stale `last_seq`, and the next
  append reused sequence numbers. Carry that bug in as a test. Make the
  primitive the mission's transcript store; `SessionManager` becomes a client
  of it, not a second store, and stops writing artifacts with a non-atomic
  `write_text`.
- **Resume.** `judais --mission --resume <run-id>` replays the stream to the
  last step before a missing `mission_finished` and continues; the swarm's plan
  and step results are checkpointed per step. Restart and orphan reconciliation
  come with it — and the credential is deliberately not persisted.
- **Wall-clock budget and cooperative cancel.** `--mission-seconds`; a
  `budget_exhausted` outcome that names *which* budget (steps, seconds, bytes,
  tokens). The kernel's `budgets.py` already has the dataclass — one owner, not
  a second one for missions.
- **Usage ledger.** Every backend returns `usage`; the run accumulates prompt
  and completion tokens and, for hosted providers, cost; `mission_finished`
  carries it; the ledger is a first-class event so a platform can meter. This
  is where February's Phase 9 telemetry lands (§2.3).
- **Approvals as durable records.** Core has the ask half — `--gate-tool`,
  `gate_requested`, the `AWAITING_APPROVAL` outcome. Add the resume half: a
  decision arrives on a later turn as a durable record and widens the closed
  set by exactly one tool for exactly one turn. Nothing defaults or expires
  into a yes.
- Fsync the audit file while the durability primitive is being written; it is
  the same lesson in the same week.

### 2.5 Phase 10 — measurable (0.11)

Property 4. **This phase absorbs February's Phase 10 (Evaluation &
Benchmarks).** February wanted an internal task suite scored on success rate,
iteration count, wall time, token usage and human interventions, compared
against the Phase 0 baseline. That is the same document as an eval harness, and
it is written once, here — with the addition February could not have known it
needed: the score must come from the *recorded stream*, not from the agent's
self-report.

- **An eval harness in-repo.** Missions × behavioural flags (orientation,
  chaining, absence, state, boundary, disambiguation, submission, synthesis), a
  mechanically-held train/test split, a dated `RUBRIC_CHANGES` ledger, and
  scoring from the recorded stream. Run it against the MCP stub server so it
  needs no GPU; run it against a live endpoint when one is offered. Keep
  February's KPI list — success rate, iterations, wall time, tokens, and above
  all **human interventions required** — as the report's columns.
- **Recorded-run replay.** A recorder that captures model I/O and tool I/O so a
  mission can be replayed deterministically and a grounding change scored on
  yesterday's runs. Grow `tests/fixtures/` from one fabrication file into a
  corpus.
- **Wire what is built.** `runtime/reading.py` (the field-misreading tier — the
  `total_s: 80.847` lesson) becomes a grounding tier behind a manifest flag;
  `critic/triggers.py` fires the external critic on `answered_with_caveat` when
  a provider is configured, which also gives the critic its first production
  caller. Both measured by the harness before either is on by default.
- **Plane-claim grounding check.** `grounding.py` already carries
  `tools_offered` and uses it only to derive the ignore list. Refuse a claim of
  a plane whose tools were not offered *and called* this turn. The prompt-level
  version of this rule exists in a deployment's personality file and says in
  its own comment that it belongs here.
- Decide `god_mode` and the preflight hook: measured and wired, or deleted.

### 2.6 Phase 11 — one runtime (0.12)

Property 5.

- Collapse `MissionRunner`/`SwarmRunner` and the kernel `Orchestrator` onto one
  loop object: `Run(personality, tools, policy, budgets, store, observer)`.
  Modes become compositions — chat is no tools; mission is tools + grounding;
  swarm is a planner that spawns child `Run`s; coding is roles that are `Run`s
  with a judge. Result bounding, context management, budgets and governance are
  then written once, and the two governance surfaces (`PolicyPack` and the
  kernel's `set_scope_constraints`) become one.
- **Async core, sync façade.** The MCP client already runs a loop thread; make
  the run loop `async` so tool calls, streaming and cancellation are natural,
  and keep `judais` synchronous at the CLI edge.
- **Model state as first-class events** (`cold/asking/queued/loading/loaded/
  failed/absent`). A deployment learned that "queued" is not "loading" and that
  a browser must be able to say which; a single runtime is where that channel
  can exist once.
- Delete or promote what is left vestigial: the second vector index, if FAISS
  is required at all. (`curl`-Mistral went in 0.8.2; `tools/recon/*` and
  `bootstrap.py` are gone — nothing imported either, and the recon pair wanted
  selenium and undetected_chromedriver that no extra declared. `kv_prefix.py`
  and `runtime/gpu.py` went in 0.9.0.)

### 2.7 Phase 12 — providers and streaming (0.13)

Properties 4 and 6.

- One HTTP client (httpx) for every hosted provider; a retry/backoff policy per
  error class, owned in one neutral place instead of imported by Mistral from
  the local backend; Anthropic as a first-class backend — the critic already
  speaks it.
- **`answer_delta` at the source.** A deployment fans one `answer` record into
  bounded deltas client-side; emit real deltas here instead. Keep the design
  lesson that made that work: the grounding verdict rides the answer's own
  frames, never a sibling event. Ship the AG-UI translator as an optional
  `core.runtime.agui` so the next browser does not rewrite it.
- **Reply-rejection buffering.** A rejected reply is mechanics, not content;
  a consumer must be able to render it as such.
- Wire the probed constrained-decoding path (`response_format`,
  `tool_choice=required`) behind a capability flag, measured by Phase 10.

### 2.8 Phase 13 — embeddable (1.0)

Property 6.

- **Library API first**: `from judais_lobi import Run, Personality, Skill,
  Tools`, speaking the same contract the CLI speaks; the CLI becomes a thin
  client of it.
- A `judais-lobi[server]` extra: an SSE endpoint over the stream store, with
  the operational rules a real deployment paid for — stream cap below the
  connection ceiling, heartbeat inside the socket write timeout, no refusal
  after the first byte.
- Framework defaults for the prompt text that every deployment has had to write
  for itself: how to work a governed tool plane, and "if a number is not in the
  view, it is not in the draft."
- **1.0 means**: `SCHEMA_VERSION` frozen for a major, `PLATFORMS.md` sufficient
  to integrate without reading source, and the eval harness running in CI on
  every push.

---

## 3. Principles

The February design philosophy and the August lessons say the same things in
different words. Merged, deduplicated, and still true at 0.9.0. The eight the
README's closing section quotes are all here, under the same names.

- **Artifacts over Chat:** State is on disk, not in a sliding text window.
- **Capabilities over Trust:** The model is assumed hostile; the sandbox and
  network gates keep it safe. Scope is computed from the intersection of
  policy, workflow, step plan, and phase — never requested freely at runtime.
- **Capabilities over Tools:** The permission model uses stable capability tags
  (`repo.read`, `net.scan`, `verify.run`), not tool names. Tools are
  implementation details that change; capabilities are the API contract. A
  `StepPlan` declares it needs `repo.write`; the kernel maps that to whichever
  tool provides it. This keeps plans evolvable without breaking old sessions.
- **Determinism over Vibes:** Tests dictate success; LLMs only suggest code.
- **Budgets over Infinite Loops:** Everything has a timeout and a retry cap,
  and exhausting one is a recorded outcome that names the budget — never a
  silent truncation.
- **Dumb Tools, Smart Kernel:** Tools execute. They do not decide, retry,
  repair, or escalate. All intelligence lives in the kernel. If a tool contains
  an `if/else` about what to do next, it has too much agency.
- **Static Graphs, Adaptive Phases:** The workflow template (phase topology,
  transitions, schemas) is static and auditable. The LLM controls what happens
  *inside* a phase — which tools to call, what plan to propose, what patch to
  emit. The LLM never controls *which phase runs next.* This is three-tier
  orchestration: rigid campaign graph (Tier 0), rigid workflow graph (Tier 1),
  flexible phase-internal loop (Tier 2). If the LLM can rewrite any transition
  graph, every budget and safety constraint has a backdoor.
- **Plans over Prompts:** Complex missions are decomposed into a structured
  `CampaignPlan` artifact — a DAG of steps with explicit workflow assignments,
  artifact declarations, and capability requests. The human reviews and freezes
  this plan before a single tool call fires. The plan is the executable
  artifact.
- **Commit or Abort:** The greatest architectural risk is a partial refactor —
  a half-agentic, half-chatbot chimera where some paths use artifacts and
  others use `self.history`, where some tools go through the bus and others
  call subprocess directly. Each phase must fully replace the subsystem it
  targets. There will not be two systems of truth.
- **Migration over Rewrite:** Each phase must leave the system in a working
  state. No big-bang rewrites.
- **Air-Gap Ready:** Every external dependency (frontier critic, hosted
  backends, network tools) is optional and capability-gated. The system runs
  identically with or without network access. A `refused` response from any
  external service is a non-event, not a blocker.
- **Refusals name the reason and the fix.** Every refusal the production agent
  emitted in its demo was read aloud as a feature. Keep it that way.
- **One owner per fact.** The swarm once hand-listed six grounding fields where
  the direct path emitted ten. That is what a second emitter costs. Route
  through the renderer; derive the list.
- **The seam is data.** Add to `core/runtime/contract.py`, bump
  `SCHEMA_VERSION` when breaking, and keep the consumer test that cannot pass
  by absence.
- **Tests must be able to fail.** Mutation-check every new assertion; clear
  `__pycache__` between flips — a same-size, same-second revert keeps stale
  bytecode and lies.
- **Nothing platform-specific in core.** Env var, manifest field, or injection
  — never a path, a hostname, a tool name or an SDK name.
- **If a human can, an agent can — under the same governance.** The framework
  supplies content; the platform supplies every judgement about it. That
  division is what made the trust boundary safe, and it holds at 1.0.
- **Measure before default.** Nothing becomes on-by-default until the harness
  scores it against a held-out set.

**Constraints and non-goals.** No Docker: sandboxing uses native Linux
namespaces — `bwrap` is the backend that ships, and February's Tier-2 `nsjail`
would go behind the same `SandboxRunner` interface, not beside it. Hosted backends
(OpenAI, Mistral) remain supported alongside local serving — the system is not
local-only until the user chooses it, and it must be able to run fully offline
against a local endpoint when they do. Failures roll back cleanly. Network is
deny-by-default. This is not a chat product (though direct chat remains
available for simple queries), not a web-first IDE, not vendor-locked, and not
a framework where LLMs design their own execution pipelines. It is also not the
serving layer: GPU topology, quantisation and batching belong where the weights
are (§2.3).

---

## 4. How you know it is no longer a toy

- A fresh `pip install 'judais-lobi[mission]'` runs a mission with tools
  isolated, deny-by-default scopes, an audit file, a bounded budget, a
  resumable transcript, and a usage ledger — with zero flags.
- Killing the process mid-run and resuming produces the same stream suffix.
- The eval harness reports a score for a release, and that score is
  reproducible from recorded runs on a machine without a GPU.
- A second platform integrates in an afternoon from `PLATFORMS.md` alone, and
  its conformance test goes red the day the contract breaks.

---
---

## 5. History

**Everything below this line is history.** §5.1–§5.8 and §5.11 are the February
2026 document, kept because it is still the clearest statement of what this
system is for and because docstrings and the README quote it; where it is
stale, a note says so and the live answer is in §1–§4. §5.9 and §5.10 are
August 2026: what the production fortnight taught, and where each Phase 8
milestone actually landed.


### 5.1 Mission statement (Feb 2026)

*Still the objective, and kept verbatim. One bullet has since been contradicted by the tree: read "GPU-Aware Orchestration" against §2.3.*

Judais-lobi will evolve from a CLI assistant with tools into a local-first autonomous execution kernel with:

* **Artifact-Driven State:** Artifacts are the *only* source of truth. No conversational history drives execution.
* **Capability Gating:** Network and host access are deny-by-default, requested via structured artifacts, and powerful when explicitly granted.
* **Native Sandboxing:** Tool execution runs in native Linux namespaces (bwrap/nsjail) to maintain a microkernel architecture.
* **Hard Budgets:** Strict caps on retries, compute time, and context size prevent infinite loops.
* **Pluggable Workflows:** The state machine is parameterized by a `WorkflowTemplate` — a static, auditable definition of phases, transitions, schemas, and branch rules. The coding pipeline is the first workflow, not the only one. Red teaming, data analysis, optimization, and arbitrary structured tasks run on the same kernel with different templates. The LLM selects which template to use at INTAKE; it never rewrites the transition graph at runtime.
* **Campaign Orchestration:** Multi-step missions run as a hierarchical state machine — a `CampaignOrchestrator` (Tier 0) drafts a DAG of steps, each assigned a workflow template, gets human approval, then dispatches isolated child workflows with explicit artifact handoff. The campaign plan is immutable once approved. The system graduates from "task runner" to "mission manager" without adding a second orchestration universe — campaigns are workflow-of-workflows, reusing the entire existing stack.
* **Deterministic Workflows:** Repository-native patch workflows using Search/Replace blocks, governed by a rigid scoring hierarchy (Tests > Static Analysis > LLM).
* **GPU-Aware Orchestration:** VRAM-aware scheduling and KV cache prefixing that adapts to the available hardware — from a single RTX 5090 (32GB) to multi-GPU configurations (e.g., 4x L4, RTX 6000 Pro 96GB).

### 5.2 Architectural target state (Feb 2026)

*The diagram and the ten invariants describe the kernel path, which is one of the two runtimes §2.6 is collapsing. Invariant 3 ("all tool execution flows through `ToolBus -> SandboxRunner -> Subprocess`") became true by default only at 0.9.0, and the in-process `fs` tool is still the exception (§1.2).*


#### 5.2.1 System Overview

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

#### 5.2.2 Core Components
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

#### 5.2.3 Execution Model & Hard Budgets

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
3. **Execution Path:** All tool execution flows through `ToolBus -> SandboxRunner -> Subprocess`. No tool ever calls `subprocess` directly. This is non-negotiable — without it, capability gating is cosmetic. **Exception:** `HUMAN_REVIEW` opens `$EDITOR` directly (user-initiated TTY) and is outside the ToolBus.
4. **Dumb Tools, Smart Kernel:** Tools are pure executors. They run a command, return stdout/stderr/exit code, and nothing else. All retry logic, repair logic, and decision-making lives in the kernel. The current `RunPythonTool.repair_code()` and `RunSubprocessTool` retry loops must be extracted into the kernel's FIX phase. If a tool fails, it reports failure. The kernel decides what happens next.
5. **GPU Scheduling in Runtime, Not Kernel:** The kernel asks `runtime.get_parallelism_budget()` and receives a number. It does not know about VRAM, device counts, or compute capability. Clean separation — the kernel orchestrates phases, the runtime owns hardware awareness.
6. **One ToolBus, Both Modes:** Direct mode and agentic mode use the **same ToolBus and SandboxRunner**. The difference between modes is orchestration depth (direct mode skips the kernel state machine), not the execution path. If direct mode bypasses the bus, you build two security models that drift apart. Every `--shell`, `--python`, and `--search` call in direct mode goes through the bus with the same policy enforcement. The bus is the only door.
7. **Kernel Never Touches the Filesystem:** The kernel reads artifacts and dispatches to tools. It never reads from the working directory, never opens project files, never writes outside the session directory. All repository interaction goes through a `RepoServer` tool via the ToolBus. Even read-only access must be sandboxed — if the kernel can read files directly, that is an unsandboxed path to the repo that bypasses policy. Kernel orchestrates. Tools touch the world.
8. **Workflow Templates Are Static:** The `WorkflowTemplate` — its phases, transitions, and schema registry — is selected once at INTAKE and is immutable for the session. The LLM controls what happens *inside* a phase. The kernel controls *which phase runs next.* The LLM picks from a menu of templates; it never writes the menu. This is the one invariant that protects every budget and safety constraint from circumvention. Three-tier orchestration: static campaign graph (Tier 0), static workflow graph (Tier 1), adaptive phase-internal planning (Tier 2).
9. **Campaign Plans Are Static Once Approved:** After the human approves a `CampaignPlan` at HUMAN_REVIEW, the step DAG is frozen. Steps can only be **(a)** retried, **(b)** skipped, or **(c)** aborted. No inserting new steps, no reordering, no changing workflow assignments — unless the campaign returns to HUMAN_REVIEW for re-approval. This prevents "LLM silently expands scope" and ensures the human-approved plan is the plan that executes.
10. **Least Privilege by Intersection:** Every tool call passes through a scope intersection that computes `EffectiveScope = GlobalPolicy ∩ WorkflowScope ∩ StepScope ∩ PhaseScope`. GlobalPolicy is the deny-by-default `CapabilityEngine`. WorkflowScope is `workflow.required_scopes`. StepScope is `step_plan.capabilities_required` (campaign mode) or the full workflow scope (single-task mode). PhaseScope is `workflow.phase_capabilities[current_phase]`. The LLM can never escalate through any layer — it can only narrow. Even if a prompt injection forces a capability request for `net.http` in a coding workflow, WorkflowScope blocks it before it reaches the ToolBus. This is capability-based security: the scope is computed from the plan, not requested at runtime.


### 5.3 System inventory & migration map (Feb 2026)

*The "current codebase" below is v0.7.2. Every migration named in it has since happened; `core/elf.py` was deleted at the end of Phase 3.*


Before building forward, the roadmap must account for every existing subsystem. The current codebase (v0.7.2, ~1,100 LOC) provides:

#### 5.3.1 What Exists Today

| Subsystem | Files | Status in Target Architecture |
| --- | --- | --- |
| **Elf base class** (`core/elf.py`) | Provider selection, history mgmt, memory enrichment, web search, code gen, system prompt assembly, streaming chat | **Decomposed** across `core/runtime/`, `core/kernel/`, `core/context/`, `core/roles/`. Deleted once extraction is complete. |
| **CLI** (`core/cli.py`) | Arg parsing, tool registration, RAG ops, memory mgmt, code execution hooks, output formatting | **Gutted and thinned.** In agentic mode, CLI becomes: `submit_task()` -> `wait_for_kernel()` -> `print_result()`. Current logic (tool registration, code execution hooks, inline sudo, summarization) moves into the kernel and ToolBus. Direct mode retains current behavior for simple chat/search/RAG queries. See Section 8. |
| **UnifiedClient** (`core/unified_client.py`) | OpenAI SDK + Mistral cURL/SSE backends | **Moved** to `core/runtime/backends/`. Becomes `openai_backend.py` and `mistral_backend.py`. |
| **Memory system** (`core/memory/memory.py`) | SQLite + FAISS vectors, short-term/long-term/RAG/adventures | **Retained** under `core/memory/` with modifications. Short-term history is replaced by session artifacts. Long-term semantic memory and adventure tracking persist as cross-session knowledge. **Requires embedding backend abstraction** — current code hardcodes `OpenAI("text-embedding-3-large")` inside `UnifiedMemory`, which breaks offline/local-first operation. Must support local embedding models (e.g., sentence-transformers) as an alternative. |
| **Tool registry** (`core/tools/`) | Base class, subprocess template, shell/python/web/fetch/RAG/install/voice/recon | **Migrated** to `tools/bus/` registry. Existing tools become tool servers. Voice and recon remain optional. |
| **Agent personalities** (`lobi/lobi.py`, `judais/judais.py`) | System prompts, few-shot examples, character voice, color schemes | **Preserved** as personality layers in `core/roles/`. The Coder role loads a personality overlay (Lobi or JudAIs) that shapes tone and style. Agent identity is not discarded. |

#### 5.3.2 What Is Deliberately Cut

* **Conversational history as execution state.** Short-term memory (`load_short`/`add_short`) no longer drives the LLM context. Session artifacts replace it.
* **Implicit tool invocation via prompt patterns.** Tools are invoked structurally through the ToolBus, not by LLM free-text matching.

#### 5.3.3 What Is Carried Forward

* **FAISS + SQLite long-term memory.** Semantic recall across sessions remains valuable for the Planner and Reviewer roles.
* **RAG archive system.** Crawling, chunking, and embedding of project docs feeds into the `ContextPack` artifact.
* **Adventure tracking.** Past code execution history (prompt, code, result, success) informs the Coder role's retry strategy.
* **Web search and page fetch.** Available as capability-gated tools via the ToolBus.
* **Voice (optional).** Remains an output mode, loaded lazily.
* **Dual-agent identity.** Lobi and JudAIs remain distinct CLI entry points with personality-specific system prompts and behavior.

---

### 5.4 Phases 0–8 as February planned them

*All eight are done. They keep their numbers — the docstrings in `core/context/spans.py`, `core/kernel/roles.py` and `tests/test_symbol_retrieval.py` that cite "ROADMAP Phase 8" still point at Phase 8 here. Phase 7's February text ran to ~490 lines of plan; it is condensed below to the decisions that outlived it, and git has the original.*

#### Phase 0 – Dependency Injection, Test Harness & Baseline

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

#### Phase 1 – Extract Runtime & Stabilize the Spine

**Goal:** Pull provider backends and message building out of `elf.py` into a clean runtime layer.

**Tasks:**

* Create `core/runtime/backends/openai_backend.py` (extract from `unified_client.py`).
* Create `core/runtime/backends/mistral_backend.py` (extract cURL/SSE logic from `unified_client.py`).
* Create `core/runtime/backends/local_backend.py` as a **stub** — local inference is not deployed until Phase 8, but the interface is defined now. The interface must be GPU-topology-agnostic: it talks to a serving endpoint (vLLM/TRT-LLM), not directly to devices. Single-GPU vs. multi-GPU is a serving-layer concern, not a backend concern.
* Create `core/runtime/messages.py` for one canonical message builder (extract from `elf._system_with_examples()` and `elf.chat()`).
* Define provider capability flags per backend (supports JSON mode, supports tool calls, supports streaming).
* `unified_client.py` becomes a thin router delegating to backends.
**Definition of Done:** All golden transcript tests still pass. Message assembly is centralized. `elf.py` no longer contains provider-specific logic.

#### Phase 2 – Kernel State Machine & Hard Budgets

**Goal:** Implement the orchestration core that governs phase transitions and enforces limits.

**Tasks:**

* Implement `core/kernel/state.py` (Phase enum, session state, transition rules).
* Implement `core/kernel/budgets.py` (configuration for all hard budget parameters).
* Implement `core/kernel/orchestrator.py` (the main loop: read artifacts, select phase, dispatch to role, enforce budgets).
* `elf.py` is reduced to a thin adapter that delegates to the kernel for agentic tasks, while still supporting direct chat for simple queries. This is `elf.py`'s last phase as a living file — see Section 10.
**Definition of Done:** The state machine can be driven through all phases with mock artifacts. Budget enforcement is tested (exceeding `max_phase_retries` halts the phase, exceeding `max_total_iterations` halts the session).

#### Phase 3 – Session Artifacts, Contracts & KV Prefixing

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

#### Phase 4 – MCP-Style Tool Bus, Sandboxing & Capability Gating

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

#### Phase 5 – The Repo Map (Context Compression) ✅

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

#### Phase 6 – Repository-Native Patch Engine ✅

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

#### Phase 7 – Pluggable Workflows, Campaign Orchestrator, Composite Judge & External Critic ✅

**Goal:** Abstract the state machine into pluggable `WorkflowTemplate` objects, add a Campaign Orchestrator for multi-step missions with HITL approval, implement role dispatchers per domain, and add a deterministic scoring hierarchy with an optional external critic.

*Condensed. The February section carried the full `WorkflowTemplate` dataclass, the `CampaignPlan` and `StepPlan` schemas, and a numbered implementation order; those are now the code, in `core/kernel/workflows.py`, `core/contracts/campaign.py` and `core/campaign/`.*

##### 7.0 WorkflowTemplate & state machine abstraction ✅

The kernel hardcoded a coding pipeline: the `Phase` enum, the `TRANSITIONS` dict, `_PHASE_ORDER` and `PHASE_SCHEMAS` were static globals. 7.0 made them parameters of a `WorkflowTemplate` that the `Orchestrator` and `SessionState` consume. `CODING_WORKFLOW = WorkflowTemplate(...)` reproduced the old behaviour exactly — zero existing tests broke. The design points that still govern:

* **Phases are strings, not enum members**, so a template can declare domain phases (`RECON`, `VULN_MAP`, `EXPLOIT`) without touching a global enum.
* **`branch_rules`** replace the hardcoded `if current == Phase.RUN: …` in `_select_next_phase()`; each workflow declares its own branching.
* **`phase_schemas`** replace the global `PHASE_SCHEMAS`; a workflow registers its own Pydantic models.
* **`phase_capabilities`** create a *temporal sandbox*: PLAN can read the repo but not write it; EXECUTE writes only through the patch engine. The LLM cannot execute while it is supposed to be planning.
* **`default_budget_overrides`** let a workflow tune budgets — red teaming may need more iterations than coding.

**Status: complete.** 86 new tests (974 total). `GENERIC_WORKFLOW` proven end-to-end with an evaluate-failure loop, budget halting and phase retry. Domain workflows (red team, data analysis) and their tool packages and dispatchers were explicitly *not* Phase 7 deliverables — 7.0 delivered the mechanism, and content is addable without kernel changes.

##### 7.1 Composite Judge ✅

Hard policy, not vibes:

1. `pytest`/`stdout` (hard pass/fail — stops everything).
2. `pyright`/`lint` (static analysis — blocks promotion unless explicitly waived by policy).
3. `LLM Reviewer` (qualitative — breaks ties only, flags risks). *LLM never overrides green/red tests.*
4. `External Critic` (optional — frontier-model logic auditor, see 7.3). *Never blocks if unavailable or refuses. Never overrides green/red tests.*

##### 7.2 Candidate sampling ✅

`CandidateManager` evaluates N candidate patches in isolated worktrees and the Composite Judge selects the winner. **Deterministic candidate ordering** is the rule that survives: candidate IDs (`candidate_0`, `candidate_1`, …) are assigned *before dispatch* and scored in ID order, not completion order — otherwise the winner depends on which GPU returns first, which is a race condition dressed as a result.

February also made `N` a function of an auto-detected `gpu_profile`, with a per-hardware VRAM table. That table is in §5.11 and the mechanism is retired: the client does not size the server (§2.3).

##### 7.3 External Critic (optional frontier-model auditor) ✅

Local models are effective builders and vulnerable to "confident wrong". The split: **local model = builder**, **deterministic judge = truth oracle**, **external frontier model = critic**. The critic does not write code, does not get tools, does not get repo access. It is a judge in the balcony, not a player on the field.

* **Air-gap design.** The whole subsystem is optional. Critic calls are *interceptors on phase transitions*, not phases in the state machine, so when there is no key, no network, or `external_critic.enabled: false`, the checkpoints are no-ops and the pipeline runs identically.
* **A redactor runs before any external call** — nothing leaves without passing it.
* **Verdict policy — the critic never kneecaps the pipeline.** `approve` logs and continues; `caution` logs, surfaces and does not halt; `block` requires plan revision *or* an explicit user override recorded as an artifact; `refused` is logged and **ignored**; `unavailable` is a silent no-op. The `refused` rule is the load-bearing one: a frontier model that refuses a legitimate pentesting task must be a non-event. The deterministic judge remains the only hard gate.
* **Capability-gated and cost-capped** through `TaskContract`: `enabled`, `provider`, `max_calls_per_session`, `max_tokens_per_call`, `redaction_level`, `allowed_artifact_fields`; reports cached by `sha256(redacted_payload)`.

*As built at 0.9.0 the critic has no production caller — it is reached only when an `Orchestrator` is constructed with `critic=`, and nothing in `core/` does that. Phase 10 (§2.5) gives it one.*

##### 7.4 Campaign Orchestrator (Tier 0 — workflow of workflows) ✅

A thin macro loop that decomposes a mission into a DAG of steps, gets human sign-off, and dispatches each step as an isolated workflow with explicit artifact handoff. Lifecycle: `MISSION_ANALYSIS → OPTION_DEVELOPMENT → PLAN_DRAFTING → HUMAN_REVIEW → DISPATCH → SYNTHESIS`. Pre-authored plan execution, per-step dispatch and artifact handoff all work; deeper MISSION_ANALYSIS / OPTION_DEVELOPMENT refinement remains planned.

* **DAG validation in code, nudged in prompts:** acyclicity, unique `step_id`s, declared artifacts. An invalid plan is rejected at PLAN_DRAFTING and returned to the model.
* **Artifact handoff, not chat transfer:** a step exports to `handoff_out/`, and the next step's `handoff_in/` is materialised from it. No shared state, no chat log crossing a step boundary.
* **`StepPlan` is a contract, not a script.** It declares intent and boundaries — objective, `inputs`, `outputs_expected`, `capabilities_required` (tags, not tool names), success criteria — and not individual tool calls; the workflow's phases handle sequencing, the ToolBus handles access, the kernel handles retries. Its **ActionDigest** is a SHA256 of the ordered fields, used for caching retried steps, replay detection, and audit: deterministic proof that the agent executed what was approved.
* **EffectiveScope — least privilege by intersection.** `GlobalPolicy ∩ WorkflowScope ∩ StepScope ∩ PhaseScope`, computed per tool call. GlobalPolicy is the deny-by-default `CapabilityEngine`; WorkflowScope is `workflow.required_scopes`; StepScope is `step_plan.capabilities_required` (campaign) or the full workflow scope (single task); PhaseScope is `workflow.phase_capabilities[current_phase]`. The LLM can only narrow, never escalate: a coding workflow cannot gain `net.scan` even if a prompt injection asks for it, and a PLAN phase cannot write files even where EXECUTE may.
* **HUMAN_REVIEW** serialises the plan into `$EDITOR`, revalidates on save, and locks capability grants per step at approval time.
* **Campaigns do not violate "workflow templates are static":** they *select* from installed templates, they do not rewrite graphs. The campaign layer is a workflow router and an artifact courier with a human checkpoint. It is not a second, less-audited orchestrator (it has exactly six deterministic phases), not an LLM execution loop, and not a replacement for `--task` — single tasks bypass Tier 0 entirely.

**Definition of Done (Phase 7):** the state machine is parameterised by `WorkflowTemplate` with `phase_capabilities` enforcing temporal sandboxing; `CODING_WORKFLOW` reproduces Phase 6 behaviour with every existing test unchanged; `GENERIC_WORKFLOW` executes a non-coding task end to end; `WorkflowSelector` picks the template at INTAKE; EffectiveScope is computed and enforced on every tool call; competing patches are graded deterministically and the proven winner selected; the external critic is fully operational when configured and fully absent when not, and its refusals never halt the pipeline; the Campaign Orchestrator executes a `CampaignPlan` DAG with per-step `StepPlan` contracts, HITL approval, computed scope grants, artifact handoff and a synthesised final report.

#### Phase 8 – Retrieval, Context Discipline & Local Inference

**Goal:** Prevent KV cache overflow and bring up local model serving.

This phase combines retrieval engineering with the transition from API-based inference to local GPU inference, since both directly affect context management and VRAM budgeting.

**Tasks:**

* ✅ Implement symbol-aware retrieval (fetching specific function spans, not whole files) — `core/context/spans.py`, reached as `repo_map symbol`.
* ✅ Implement **rolling summarization** for tool traces: full logs stream to disk, but only capped summaries enter the LLM context (`max_tool_output_bytes_in_context`). When output exceeds the budget, do not blindly truncate — prompt the model with a structured message: *"Output exceeded budget (N bytes). Full log at `<artifact_path>`. Use targeted retrieval (grep, tail, symbol lookup) to find specific information."*
* ✅ **Local inference bring-up:** Deploy and validate vLLM or TRT-LLM serving the target model on the available GPU(s). Wire `local_backend.py` (stubbed in Phase 1) to the local server. For multi-GPU setups, configure tensor parallelism via the serving layer (vLLM `--tensor-parallel-size`, TRT-LLM TP config). — `--provider local` is a real backend: streaming, retries, and a `GET /models` probe.
* ~~Define the **model selection criteria** for local inference: minimum coding benchmark scores, context window requirements, quantization compatibility.~~ **Superseded** by the eval harness (the new Phase 10, §2.5): a score from recorded runs, not a criteria document.
* Validate that all golden transcript tests pass against the local backend.
* ✅ Add **context window manager** with endpoint-probed caps (the server's `max_model_len`, not the client's VRAM), instance-aware limits, and auto-compaction.
**Definition of Done:** Context size is strictly bounded. Tool output never causes a token overflow crash. The system can run fully offline against the local backend on at least one GPU profile.

---

### 5.5 Failure mode matrix (Feb 2026)


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

### 5.6 User interface contract (Feb 2026)

*Written before mission mode existed. `--mission`, `--swarm`, `--skill`, `--events`, `--history`, `--gate-tool`, `--profile` and `--unsandboxed` are the surface a consumer spawns today; they are published as data in `core/runtime/contract.py` and documented in `README.md` and `CONTRACT.md`. What follows is the kernel-path CLI as February drew it.*


The system is invoked via the existing CLI entry points (`lobi`, `judais`). The agentic workflow is an additional execution mode, not a replacement for direct chat.

#### Direct Mode (Preserved)
```bash
lobi "explain this function"          # Chat
lobi --shell "list large files"       # Code generation + execution
lobi --search "rust async patterns"   # Web search enrichment
lobi --rag crawl ./docs               # RAG indexing
lobi --recall 5                       # Adventure history
```

#### Agentic Mode — Single Task (New)
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

#### Campaign Mode — Multi-Step Missions (Current + Planned)
```bash
lobi --campaign "migrate auth system to JWT"       # Draft plan (implemented)
lobi --campaign-plan ./mission.json                # Pre-authored plan (implemented)
```

* `--campaign` drafts a `CampaignPlan` from the mission description, then enters HUMAN_REVIEW → DISPATCH → SYNTHESIS.
* `--campaign-plan <file>` loads a pre-authored `CampaignPlan` JSON and enters HUMAN_REVIEW → DISPATCH → SYNTHESIS.
* `--workflow-override <step>=<template>` forces a specific workflow for a named step (overrides LLM's assignment).
* At HUMAN_REVIEW, the plan is serialized and opened in `$EDITOR`. The user approves, modifies, or rejects. Capability grants are locked per step at approval time.
* Campaign sessions are written to `sessions/<campaign_id>/` with per-step child sessions under `steps/<step_id>/`.
* Each step runs in isolation with explicit artifact handoff — no shared state, no chat log transfer.

**Capability grant UX** — three modes, from most manual to most automated:
1. **Interactive approval:** Kernel pauses, CLI prompts the user: `"Tool 'git_fetch' requests scope 'net.any'. Allow? [y/N/y+60s]"`. User can grant permanently, for a duration, or deny.
2. **CLI pre-authorization:** `--grant net.any,git.fetch` pre-signs scopes for the session. No interactive prompts for covered scopes.
3. **Policy file:** `--policy ./policy.json` loads a `PolicyPack` artifact that auto-approves matching scopes. Useful for CI, unattended runs, or project-standard policies.

---

### 5.7 Phase dependencies (Feb 2026)

*The graph below ends at February's Phase 9 and Phase 10. Phase 9 is retired (§2.3) and Phase 10 is absorbed into the new Phase 10 (§2.5); read those two nodes as "the serving layer" and "the eval harness".*


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

---

### 5.8 Point of no return: the deletion of `elf.py` (Feb 2026)

*Done. `core/elf.py` was deleted at the end of Phase 3 and `core/agent.py` replaced it.*


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

---

### 5.9 What two weeks in production taught (Aug 2026)

For two weeks judais-lobi ran as **Tai**, the mission agent inside a separate platform: a 20B local model, an MCP tool plane of ~20 governed tools, a browser pane reading the NDJSON mission stream, real analysts, a recorded bake-off against a second harness, and a behavioural eval that went from 6-of-10 missions reporting `0/0 … grounded` to 10/10 with 0% error. Every row below is a lesson the platform taught and the shape it took in `core/`.

| Lesson the platform taught | What it became in core |
|---|---|
| A grounding check that considers nothing must not report a pass | three verdicts `ran / grounded / verified` (`core/runtime/grounding.py`) |
| "Write no numbers" was a winning move against a substring check | the claim table — `{value, path}` verified by walking the payload |
| A fenced code block is a proposed computation, not an assertion | `prose_only` before every prose check |
| The same tool spelled three ways cost two turns and deleted a true sentence | one `tool_key`/`same_tool`, a *derived* ignore list, a refusal that names the near-miss |
| Three copies of one 33 kB view was a context problem that was not about context | byte-level result dedup + the per-mission result store |
| History folded into the objective was ignored; "#2" was web-searched literally | `--history` as role-tagged chat turns |
| A killed harness lost its last events | `close_on_sigterm` flushes and closes the sink |
| A 20B model does not obey a rule stated 2,000 tokens upstream | swarm rungs explained at the moment they act |
| The consumer's assumptions lived in convention | `core/runtime/contract.py` — the seam as data, `SCHEMA_VERSION`, `conforms()` |

It also exposed what stayed in the platform's wrapper — the durability, presentation and trust layer. That is what Phases 9–13 are.

---

### 5.10 Phase 8 disposition (Aug 2026)

**Phase 8 closed 15 Aug 2026 (0.9.0).** The February plan is in §5.4 as written. What actually shipped rarely used the file names it proposed, so this table says where each milestone landed instead. Two rows are deliberately not code in this repo: D1 became an eval question (Phase 10, §2.5) and B3 became a durability question (Phase 9, §2.4).

| Milestone | Where it landed |
| --- | --- |
| **A** — symbol-aware retrieval | `core/context/spans.py`, reached as the `symbol` action of the `repo_map` tool (`core/tools/descriptors.py`) and asked for by name by the RETRIEVE role (`core/kernel/roles.py`), which settles with `("repo_map", "symbol")`. Tests: `tests/test_symbol_retrieval.py`. No `symbol_lookup` tool and no `span_index.py`: an action on the tool that already owns the map beat a sixth tool. |
| **B1** — global context accounting | `core/runtime/context_window.py` — `resolve_profile` is the one cascade that answers how big the window is (backend probe → config → model default → provider default), and one estimator serves every caller. There is no `context_budget.py`; a second module would have been a second opinion. |
| **B2** — context management at every prompt build | Chat: `Agent.chat` (`core/agent.py`) routes through `ContextWindowManager`. Mission: `MissionWindow` (0.8.2), with the compaction reported on the stream as `compacted` on `step_started` rather than written to a side file. Kernel roles: 0.9.0 — the roles route through the same owner, and their compactions are recorded as a phase artifact. |
| **B3** — tool-log routing | Partial, and deferred on purpose. `core/tools/tool_output.py` writes full logs under `.judais-lobi/tool_logs` and puts a bounded summary plus a retrieval hint in context; putting those logs *beside the run's durable transcript* waits on there being one — the new Phase 9, §2.4 (thread primitive, `SessionManager` as its client). |
| **C** — local inference bring-up | `core/runtime/backends/local_backend.py`: OpenAI-compatible chat completions, SSE streaming, a `GET /models` probe that yields `max_model_len` as `BackendCapabilities.max_context_tokens`, and connect-refused retries. Resolution and `LOCAL_API_BASE`/`LOCAL_MODEL` in `core/runtime/provider_config.py`. |
| **C4** — offline golden tests | `tests/test_local_backend.py` against a stub server, plus `tests/mcp_stub_server.py` for the tool plane, so the whole path runs with no GPU and no network. |
| **D1** — model selection criteria | Superseded. A criteria document would have been an opinion; the new Phase 10 (§2.5) puts an eval harness in the repo and answers the same question with a score that is reproducible from recorded runs. No `docs/model_selection.md`. |
| **D2** — config schema | `.judais-lobi.yml` carries the `context:` keys (`max_context_tokens`, `max_output_tokens`, `provider_defaults`, `model_overrides`, …) — see `ContextConfig.from_project`. The endpoint probe deliberately outranks them: `max_model_len` is measured and a config line is declared. |
| **E** — documentation | README: `--provider local` setup, the context/compaction behaviour, the `context:` block, and the retrieval tooling. This table and the ROADMAP checklist close the loop. |

Two things named in that plan were removed rather than finished, both in 0.9.0. The baseline's `core/runtime/gpu.py` stub is gone with the VRAM cap it fed: the client's device list never described the server's window, and the local backend talks to a serving endpoint that is routinely another machine. And `core/kv_prefix.py` — from Phase 3, never imported by anything but its test — went with it.

---

### 5.11 February's Phase 9 — TRT-LLM / vLLM tuning (retired)

*Retired as a phase of this repository (§2.3): the serving endpoint is another box, and a client with opinions about tensor parallelism is a client answering from the wrong machine. The telemetry bullet moved into the new Phase 9's usage ledger (§2.4). The notes are kept here for whoever stands the serving layer up.*


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

And the candidate-sampling VRAM table from 7.2, on the same footing:

**VRAM Budget Note:** Candidate sampling concurrency is dictated by the GPU profile, not hardcoded. The system must query available VRAM at startup and select a strategy accordingly:

| GPU Profile | VRAM | 7B FP8 (~8-10GB/gen) | 13B+ FP8 (~16-20GB/gen) | Strategy |
| --- | --- | --- | --- | --- |
| 1x RTX 5090 | 32GB | Concurrent N=2 feasible | Sequential only | Shared KV prefix, sequential fallback |
| 1x RTX 6000 Pro | 96GB | Concurrent N=3+ | Concurrent N=2-3 | Full parallel candidate generation |
| 4x L4 | 4x 24GB | N=1 per GPU, 4 parallel | N=1 per GPU (tight) | Tensor-parallel or pipeline-parallel serving; candidates distributed across GPUs |
| 1x consumer (16-24GB) | 16-24GB | Sequential N=2 | Not feasible | Sequential with aggressive KV eviction |

February's Phase 10, *Evaluation & Benchmarks*, is not retired — it is absorbed. Its task suite (rename refactor, bug fix, add test, API extension), its metrics (success rate, iteration count, wall time, token usage) and its key KPI (**human interventions required**) are the columns of the harness in §2.5.
