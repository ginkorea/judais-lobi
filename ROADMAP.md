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

**v0.15.0**, 17 Aug 2026. 3,939 tests collected (`pytest --collect-only -q`);
39,224 lines in `core/`+`judais/`+`lobi/` and 45,067 lines of tests (`wc -l`
over `*.py`, so blanks and docstrings are in both numbers — this repository
writes a lot of both on purpose).

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
run unattended. Six releases in three days closed most of it: 0.9.0 safe by
default, 0.10.0 durable and bounded, 0.11.0 native tool calling behind a flag,
0.12.0 the answer streamed at the source and a channel back into a running run,
0.13.0 the eval harness, recorded-run replay and the three grounding tiers
wired off by default, 0.14.0 what that harness found (an offered set that
follows the bus, a code gate about this host), staged `--resume`, and
`--provider anthropic`. What is left is §2 — and the largest piece of it is now
not that measurement is *impossible* but that it has not been *done*: the
harness exists and nothing has been scored with it yet.

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

Written 15 Aug 2026; **every row re-verified against `master` at 0.13.0 on
17 Aug 2026**, with 0.14.0's closures added the same day, by grep rather than by memory. A struck row is closed: it names
the release that closed it and, where one survives, the residual. An unstruck
row is open today. Re-verify before acting on any of it.

| Gap | Where it lives | Property |
|---|---|---|
| ~~**No sandbox by default.**~~ Closed 0.9.0: `select_sandbox` picks bwrap wherever it exists, the child env is an allow-list, and the choice rides `mission_started.sandbox`. **Still open:** the `fs` tool is in-process pathlib and no sandbox bounds it. | `core/tools/sandbox.py`, `core/tools/fs_tools.py` | 1 |
| ~~**Allow-everything policy by default.**~~ Closed 0.9.0: `Tools()` builds `SAFE`, `--profile`/`JUDAIS_LOBI_PROFILE` opt up, refusals name the scope and the profile that grants it, and `AuditLogger` is on every default bus (`audit_ref`). **Still open:** the kernel path governs through `set_scope_constraints`, a second surface. (God-mode and the preflight hook were the other half of this row and were **deleted in 0.13.0** rather than wired.) | `core/tools/__init__.py`, `core/policy/`, `core/kernel/orchestrator.py` | 1 |
| ~~**Tracebacks leak absolute paths.**~~ Closed 0.9.0: one redactor at the emitter. **Still open:** it covers the mission stream and mission-mode stderr, not the kernel/campaign/chat error prints. | `core/redact.py`, `core/cli.py` | 1 |
| ~~**The real agent path persists nothing.**~~ Closed 0.10.0: `core/durable.py` `RunStore` is the mission's transcript store (fsync'd, monotonic `seq`, atomic meta), `--resume` replays it, orphans are reconciled, every `core/` store write is atomic (guard test), audit is fsync'd. **Closed 0.14.0:** staged-run resume (`StagedResumption`). **Still open:** the kernel path's `SessionManager` is atomic but still its own layout; nothing locks against two resumes of one run. | `core/durable.py`, `core/runtime/resume.py` | 2 |
| ~~**No wall-clock bound, no cancellation.**~~ Closed 0.10.0: `--mission-seconds`, one clock per mission shared by every stage, `budget` names which budget, cooperative cancel + SIGTERM winds up cleanly. **Still open:** `bytes`/`tokens` budgets declared, not enforced. | `core/budgets.py` | 3 |
| ~~**No usage or cost accounting.**~~ Closed 0.10.0: `Backend.last_usage` on every backend, one `Ledger`, `usage` per call and per run on the stream, `cost` from a `pricing:` table, `elapsed_s` on `mission_finished`. **Still open:** it is reported, never enforced — there is no dollar or token budget that stops a run, and the `tokens` budget in `core/budgets.WHICH` is still declared and unwired. | `core/runtime/usage.py`, `core/budgets.py` | 3, 4 |
| ~~**No reproducible eval.**~~ Closed 0.13.0: `core/eval/` is a suite of missions × behavioural flags with a mechanical held-out split, scored **only from the recorded stream** (`check`/`run`/`score`); `tests/fixtures/eval/` holds a real stream per mission — a good agent for each and a bad one for every regression case; `core/runtime/replay.py` records `model.jsonl`/`tools.jsonl` beside `events.jsonl` and `--replay` re-runs a finished mission with no server and no GPU, so a grounding change is scored on yesterday's runs. `EVAL.md` is the guide. **Still open:** the *measurements themselves* — swarm versus direct, `json` versus `native`, each grounding tier on versus off. The harness exists; nothing has been scored with it yet, and every one of those defaults waits on it. | `core/eval/`, `core/runtime/replay.py`, `tests/fixtures/eval/`, `tests/fixtures/runs/` | 4 |
| **Two agent runtimes**, and the gap widened. `MissionRunner`/`SwarmRunner` and the kernel `Orchestrator`+roles still do not share sessions, budgets or governance. Shared owners keep arriving — `core/bounding.py` (0.8.2), the context window (0.9.0), `core/budgets.py` and `core/durable.py` (0.10.0) — but the run store, `--resume`, the wall clock, the usage ledger, the native protocol and the control channel all landed on the **mission** path only, so the kernel path has none of them. | `core/runtime/mission.py` vs `core/kernel/` | 5 |
| ~~**No token streaming or constrained decoding in agentic runs.**~~ Closed 0.11.0 and 0.12.0: `--protocol native` asks for `tool_choice=required` over the declared functions and validates arguments against each tool's schema before dispatch (`core/runtime/schema_check.py`, both protocols); the answer streams by default and its fragments go out as `answer_delta` (`core/runtime/answer_stream.py`), with `--no-stream` to turn it off. **Still open:** `native` is off by default until the harness (0.13.0) actually scores it, and the *kernel* path streams nothing and constrains nothing. | `core/runtime/answer_stream.py`, `core/runtime/backends/` | 4, 6 |
| **Thin provider layer.** Unchanged at 0.12.0: three backends (`openai`, `mistral`, `local`), retry only on a refused connect, and `mistral_backend.py` still imports the timeout/retry policy from the local backend rather than from somewhere neutral — its own docstring says so. What 0.11.0/0.12.0 added is a capability declaration per backend (`supports_streaming`, `supports_tool_calls`, `supports_tool_choice_required`) that the door refuses against, which is a seam and not a provider layer. | `core/runtime/backends/` | 6 |
| **Built, tested, unreachable.** Re-verified by importer scan at 0.13.0, and the row shrank: `Agent.run_task` still has no caller in `core/`; ~~`ApprovalStore.reconcile(live_run_ids)` is still uncalled~~ (called from the CLI since 0.14.0, "live" derived from the orphan sweep); and the critic's **coding-tier** orchestrator is still reached only through an injected `critic=`, which nothing in `core/` passes. **Wired 0.13.0:** `runtime/reading.py` is the `reading` grounding tier and `critic/triggers.py` + the new `critic/mission.py` are the `critic` tier — reachable, off by default, and measurable. **Deleted rather than wired:** `kv_prefix.py`, `runtime/gpu.py` (0.9.0); `policy/god_mode.py` and the bus's `preflight_hook`/`god_mode` parameters (0.13.0 — nothing ever passed either, and `--profile god` is the reachable form). **Closed 0.9.0:** `policy/audit` is on every default bus. | importer scans | 4 |

None of this is a design flaw. It is the honest shape of a framework whose
production fortnight was spent making one deployment truthful. The work in §2
is making the *default* deployment trustworthy — and, from Phase 10 on,
provable rather than asserted.

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
| 4 | MCP-style tool bus, sandboxing & capability gating | ✅ `ToolBus`, `CapabilityEngine`, `BwrapSandbox`, profiles, audit (the god-mode *session* it also built was deleted at 0.13.0; `--profile god` is what survives) |
| 5 | The repo map (context compression) | ✅ 3-tier extraction, dependency graph, ranked excerpts, caching |
| 6 | Repository-native patch engine | ✅ parser, exact-match matcher, path-jailed applicator, worktree isolation |
| 7 | Pluggable workflows, campaign orchestrator, composite judge & external critic | ✅ 7.0–7.4 |
| 8 | Retrieval, context discipline & local inference | ✅ closed 0.9.0 — disposition in §5.10 |
| — | *Release 0.8.0 — the separation* | ✅ contract as data, `tai` entry point, `mission` extra, SIGTERM close, `PLATFORMS.md` |
| — | *Release 0.8.2 — the honest stream* | ✅ swarm silence, mission window, one bounder, httpx Mistral, a bwrap that runs |
| — | *Release 0.9.0 — safe by default* | ✅ property 1, less its residuals (§1.2) |
| ~~9~~ | ~~Performance optimisation (TRT-LLM / vLLM tuning)~~ | **Retired** — §2.3 |
| 9 | Durable and bounded (0.10) | ✅ 0.10.0 — properties 2 and 3, less the residuals in §2.4; "bounded" re-read at 0.15.0 as bounded by the operator, supervised by the framework (§2.6a) |
| — | *Release 0.11.0 — native tool calling* | ✅ Phase 12's constrained-decoding bullet, pulled forward on evidence; **off by default** |
| — | *Release 0.12.0 — streamed and steerable* | ✅ Phase 12's `answer_delta` and AG-UI bullets and Phase 13's control channel, likewise pulled forward |
| — | *Release 0.14.0 — what the harness found* | ✅ the two eval findings closed, staged `--resume`, the swarm critic and corpus, Phase 12's provider bullet, `ApprovalStore.reconcile` called |
| 10 | Measurable (0.11) | ✅ 0.13.0 — the harness, recording + `--replay`, the tiers wired off-by-default; the *measurements* (swarm, native, tiers on/off) are what remains, and they gate every default |
| 11 | One runtime (0.12) | ⏳ property 5. Not started; §1.2's "two agent runtimes" is its whole case |
| 12 | Providers and streaming (0.13) | ✅ properties 4 and 6 — constrained decoding (0.11.0), `answer_delta` + the AG-UI translator + the control channel (0.12.0), and the provider work — one HTTP policy owner and `--provider anthropic` (0.14.0) |
| 13 | Embeddable (1.0) | ⏳ property 6. The control channel came out of its list early; the library API has not started |
| 14 | The step budget is gone (0.15) | ✅ 0.15.0 — no framework step budget; operator ceilings only; `core/runtime/supervisor.py` catches repetition (§2.6a) |

The release numbers in the second column are February's guesses at which
version a phase would land in, kept so the phase numbers do not move. They are
now wrong in both directions — Phase 12's work partly shipped in 0.11.0 and
0.12.0, and Phase 10 landed in 0.13.0 rather than 0.11 — and the version a
phase actually lands in is decided when it lands.

### 2.2 As built

February's Phases 0–8 are detailed in §5.4, with Phase 8's milestone-by-
milestone disposition in §5.10. They keep their numbers, so the docstrings that
cite "ROADMAP Phase 8" stay true.

Eight releases of August 2026 did phase-sized work in three days.
`NEXT_STEPS.md` numbered the first three 0, 0.5 and 1; that numbering is
retired here so no reader meets a second Phase 1. Two of the eight *are*
phases — 0.10.0 is Phase 9 (§2.4) and 0.13.0 is Phase 10 (§2.5); the other
six took no number.

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

**0.10.0 — durable and bounded (16 Aug 2026).** Phase 9; the bullet-by-bullet
account is §2.4. A run now survives the process: `core/durable.py` is the durability primitive the whole
tree writes through — atomic replace, `fsync_append`, and a `RunStore` of one
directory per run holding an fsync'd `events.jsonl` of `{seq, at, record}`
envelopes. Every record is appended there *before* it reaches the `--events`
sink, so the sink is a client of the log rather than a second copy, and
`--resume <run-id>` reads it back: the door refuses the wrong run, the replay
rebuilds the loop through the runner's own renderer, and the orphans nobody
else will close get closed. `--mission-seconds` gave the run a wall clock and
`budget_exhausted` learned to name *which* budget; a cooperative cancellation
and a `SIGTERM` that gets to finish let a stopped turn close its own stream.
Every backend reports what a call cost, one `Ledger` adds it up, and `usage`
rides the record it belongs to with `elapsed_s` beside the run's total. A gate
became a durable record with an `approval_id` a later run carries. And the
thirteen stores `core/` still truncated in place were swept onto the atomic
write, with a guard test that keeps them there.

**0.11.0 — native tool calling behind a flag (16 Aug 2026).** Phase 12's
constrained-decoding bullet, pulled forward on the reference deployment's own
evidence: two of four turns in a measured suite were spent on a malformed tool
name and invalid JSON — a quarter of the budget on protocol rather than on the
question. `--protocol native` removes the two mistakes instead of catching
them: the request declares the mission's tools as functions plus a synthetic
`mission_answer`, asks for `tool_choice=required` with
`parallel_tool_calls=true`, and reads the decision out of the provider's own
`tool_calls`, so an unparseable reply and a name nobody offers are
unrepresentable. One turn may then dispatch several tools, told apart by a
`call` ordinal under one `index`. Arguments are checked against each tool's own
JSON Schema before dispatch in **both** protocols. Two things came with it and
are not the flag: one assembler for every system turn, giving a byte-stable
most-constant-first prefix that a server can cache, and a context window that
evicts tool round trips before the turns somebody actually said. **The default
stays `json`** — the flag is measured before it is anybody's default, and
Phase 10 is what measures it.

**0.12.0 — streamed and steerable (16 Aug 2026).** Two Phase 12 bullets and one
of Phase 13's, all pulled forward for the same reason: a minutes-long mission on
a local model has nothing to show for its last turn, and nothing anybody can say
to it. `answer_delta` is the tenth event — decoded out of the half-written reply
**at the source**, bounded at 64 characters or a newline, and provisional: the
`answer` record always follows, carries the whole text and is the authority,
because only it has been through the grounding path. `--control` is the first
channel *into* a run: NDJSON commands on a descriptor, a FIFO, a path or stdin,
with a closed vocabulary — `inject` (a user turn before the next model call,
reported back as `step_started.injected`), `cancel`, `cancel_step`, and
`gate_decision`, which answers a gate **while the run is still standing at it**
through the same approval store the `--approval` path reads. Nothing on that
channel is an event and nothing times out into a yes. And `core/runtime/agui.py`
speaks the stream as AG-UI — import-free, dicts only, `translate()` for a replay
and `Translator.feed/close` for a live follower — so the next browser does not
rewrite the mapping, with the design lesson kept: the grounding verdict rides
the answer's own frames and never a sibling event a reconnect could separate
from it.

**0.13.0 — measurable (17 Aug 2026).** Phase 10, and it is the release that
makes every deferred default decidable. `core/eval/` is a suite of missions ×
behavioural flags with a mechanical held-out split, a rubric-change log, and a
verdict computed **only from the recorded stream** — `python -m core.eval
check|run|score`, eleven in-repo missions over the MCP stub, and a committed
stream per mission (a good agent for each, a bad one for every regression case)
so the corpus cannot drift away from the harness quietly. `core/runtime/replay.py`
is the other half: every run with a store on now writes `model.jsonl` (each
model call, its request, its reply and its side channels) and `tools.jsonl`
(each dispatch with the typed payload the event stream never carried) beside
`events.jsonl`, scrubbed for credentials and nothing else because the rest is
the model's input; `--replay <run-id>` (`MISSION_REPLAY`) runs a finished
mission again out of that recording — the real loop, the real validator, no
server and no GPU — into a **new** run directory carrying `replay_of` and any
prompt `drift`. That is what makes "if the grounding grammar had been stricter
yesterday, what would yesterday's ten missions have said?" an answerable
question. Three grounding tiers were wired to go with it, all **off by
default**: `reading` (the field-misreading reader, needs `claim_table`),
`planes` (an answer claiming a tool family nothing on it was called from), and
`critic` (a second model, local first via `LOCAL_API_BASE`, its verdict an
`advisory: true` row **beside** `grounded` and never inside it). And two things
were deleted rather than wired: `core/policy/god_mode.py` and the bus's
`preflight_hook`/`god_mode` parameters — nothing ever passed either, and a
control nobody passes is a safety story a deployment can tell and not have.
`EVAL.md` is the guide. What is *not* in this release is any number: the
harness exists, and the measurements it was built for are still owed.

**0.14.0 — what the harness found, and the Phase 12 remainder (17 Aug 2026).**
The two framework findings the eval suite surfaced are closed: the loop's
offered set follows a bus that grows mid-run (reconciled after every dispatch
and at every step boundary, admitted through the manifest's `admits`, announced
as `step_started.catalogue`, the system turn re-rendered), and the manifest code
gate is `tool_key` equality — a bridged `mcp.run_shell_command` is the server's
and is governed by the closed set and `--gate-tool`, not by a `bwrap` claim this
host cannot make. The swarm's synthesizer gets the same `second_opinion()` the
direct loop has; `ApprovalStore.reconcile` is finally called, on the way into
every mission, with "live" derived from the orphan sweep. Phase 12's remaining
bullet closed: `core/runtime/backends/policy.py` is the one neutral owner of the
HTTP timeout, connect retries and per-error-class policy, and `--provider
anthropic` is a first-class SDK backend (default `claude-opus-5`, streaming and
native tools, `supports_json_mode=False`, never fallen back from). Phase 9's
last residual closed: a staged (`--swarm`) run **resumes as a staged run** —
the checkpointed plan carries all five step fields, `resumed` rides the first
new `step_started`, settled steps are not re-run and the router and planner are
not re-asked; the swarm has its own replay fixture and a CLI end-to-end suite,
which found and fixed a gate that failed every native sub-mission of a staged
turn. Still owed: the measurements.

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
`mission_finished` as an optional field, next to tokens and cost. The hardware bullets stay as
history in §5.11, where the reference-profile notes are kept verbatim for
whoever stands the serving layer up.

### 2.4 Phase 9 — durable and bounded (0.10) — done 15–16 Aug 2026 (0.10.0)

Properties 2 and 3. Every bullet below shipped in 0.10.0 (lanes O/O2/P/Q/R/S).
What it did *not* close, carried forward: ~~a **staged** (`--swarm`) run
checkpoints its plan and steps but `--resume` refuses it~~ (**closed 0.14.0**:
a staged run resumes as a staged run, see `core/runtime/resume.StagedResumption`;
what remains is that no lock stops two resumes of one run — nothing in
`core.durable` locks); the `bytes`
and `tokens` budgets are declared in `core/budgets.WHICH` and not yet enforced
(the ledger exposes `transcript.usage.total` for a `tokens` budget to read);
`elapsed_s` rides `mission_finished` top-level. One residual has since closed:
`Cancellation` was process-local, and 0.12.0's `--control` channel delivers one
from outside the process (`{"control": "cancel"}`), which was on Phase 12's
list.

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
  carries it. First-class **field**, not a first-class event as this bullet
  originally said: the reference consumer asserts `set(contract.EVENTS)` equals
  the set it reads, so a tenth event would force a lockstep release on both
  sides for a number that fits in frames that already exist — while an optional
  field is read with a default by a platform that meters and ignored by one
  that does not. So `usage` rides `tool_call`, `answer` and `reply_rejected`
  per call and `mission_finished` as the run's totals, absent (never zero) when
  the provider reported nothing. This is where February's Phase 9 telemetry
  lands (§2.3).
- **Approvals as durable records.** Core has the ask half — `--gate-tool`,
  `gate_requested`, the `AWAITING_APPROVAL` outcome. Add the resume half: a
  decision arrives on a later turn as a durable record and widens the closed
  set by exactly one tool for exactly one turn. Nothing defaults or expires
  into a yes.
- Fsync the audit file while the durability primitive is being written; it is
  the same lesson in the same week.

### 2.5 Phase 10 — measurable (0.11) — shipped 17 Aug 2026 (0.13.0)

Property 4. The *instruments* shipped in 0.13.0 (lanes AA/AB/AC): the harness,
recording + replay, and the three grounding tiers wired off by default. The
*measurements* are the residual — running the stub suite twice with `--swarm`,
with `--protocol native`, and with the tiers on, and reading the deltas — and
they gate every default the roadmap has deferred. Two framework findings the
harness surfaced, for Phase 11: the offered tool set is fixed at mission start
although the bus can grow mid-run (`the_plane_grew_mid_run`); and the manifest
code gate fires on a bridged `mcp.run_shell_command` NAME, so a manifest that
gates a bridged shell tool needs bwrap even though the shell is on the server.
 **This phase absorbs February's Phase 10 (Evaluation &
Benchmarks).** February wanted an internal task suite scored on success rate,
iteration count, wall time, token usage and human interventions, compared
against the Phase 0 baseline. That is the same document as an eval harness, and
it is written once, here — with the addition February could not have known it
needed: the score must come from the *recorded stream*, not from the agent's
self-report.

- ~~**An eval harness in-repo.**~~ **Shipped** — `core/eval/`: `suite.py`
  (`Mission`, `FLAGS`, `Split`/`SPLITS`/`TEST_SHARE`/`MIN_TEST_MISSIONS`,
  `RUBRIC_CHANGES`, `Suite`/`load_suite`, `check_the_suite_is_gradeable`),
  `stub_suite.py` (eleven missions over `tests/mcp_stub_server.py`, one per
  flag, four held out at 36%), `score.py` (`score_run`/`score_suite` →
  `Verdict`/`Report`, computed **only** from the recorded stream — tools
  called, forbidden tools reached for, outcome, the grounding verdict read off
  the last non-interim `grounding` record, `reply_rejected`, staged?, and the
  answer's prose only where a mission names a regex), and `run.py` /
  `python -m core.eval run|score|check`. February's KPI columns —  success
  rate, iterations, wall time, tokens, **human interventions**
  (`gate_requested` + `step_started.injected`) and rejected replies — per flag
  and overall, **train and test never blended**. The eight February flags plus
  three this repository needed: `routing` and `partial_synthesis` (the two
  regression cases at the end of this section) and `protocol_shape`, which is
  the column §2.7's json-versus-native default is waiting on. `EVAL.md` is the
  guide; a platform keeps its own suite in its own repository as YAML/JSON
  (`load_suite`). No GPU: `score` reads recorded run directories (RunStore
  layout, envelopes or bare NDJSON alike), and `tests/fixtures/eval/` holds a
  real stream per mission — a good agent for each and a bad one for every
  regression case — produced in-process against the stub by
  `tests/test_eval_stub_suite.py`.
- ~~**Recorded-run replay.**~~ **Shipped 0.13.0** — `core/runtime/replay.py`:
  every run with a store on writes `model.jsonl` (each model call: request,
  reply, side channels) and `tools.jsonl` (each dispatch with its typed
  payload) beside `events.jsonl`; `--replay <run-id>` (`MISSION_REPLAY`)
  re-runs a finished run with the recorded model and recorded tools — no
  server, no GPU — into a NEW run dir carrying `replay_of` and any `drift`,
  so grounding runs fresh over yesterday's answer and `python -m core.eval
  score` scores it like a live run. `tests/fixtures/runs/` holds two recorded
  corpus runs (json + native). See EVAL.md §"Recording and replay".
- ~~**Wire what is built.**~~ **Shipped 0.13.0, off by default** —
  `grounding: reading: true` (needs `claim_table: true`) runs `reading.py` as
  a grounding tier; `grounding: critic: true` asks a second model on
  `answered_with_caveat` (local first via `LOCAL_API_BASE`, then a keyed
  provider), its verdict a `critic` row in `grounding.checks` marked
  `advisory: true` beside `grounded`, never inside it. Measured by the harness
  before either goes on by default — that measurement is still owed.
- ~~**Plane-claim grounding check.**~~ **Shipped 0.13.0, off by default** —
  `grounding: planes: {name: {tools: [...], claims: [...]}}`; a claim phrase
  with no call to that plane's tools this run fails the check; "what was called
  this run" has one owner (`MissionResultStore.called_tools`).
- ~~Decide `god_mode` and the preflight hook.~~ **Deleted in 0.13.0**: nothing
  ever passed either; the bus's capability check, `runtime/schema_check` and
  `--profile god` are their reachable forms. `GodModeGrant`/`HIGH_RISK_ACTIONS`
  remain in the schemas without a consumer.
- **First regression cases, from the reference deployment's A/B of 16 Aug
  2026** (same pane, same 10-scenario behavioural driver, 0.9.0): direct 10/10,
  `--swarm` 9/10. The one failure was the suite's simplest prompt — a
  "[quick web] give me 5 short bullets" listing — and it names two swarm
  defects the harness must catch: (1) the **router staged a request one tool
  call answers** (documented as biased to DIRECT; on a 20B model it was not),
  so "a `[quick web]` listing must not be staged" is a case; (2) the
  **synthesizer refused with partial results in hand** ("cannot provide …
  steps were halted") where the direct loop would have answered with a caveat
  — the staged path's answer-with-caveat posture must be at least as strong as
  the direct one's. Both belong to the swarm; staged-run `--resume` shipped 0.14.0.
  The two framework findings the suite recorded for Phase 11 (the offered set
  did not follow a growing bus; the code gate caught bridged shells) are
  **closed 0.14.0** — see §2.2. What the swarm still lacks is one view of the
  plane: its own `_offered` and the planner's catalogue are the set the turn
  started with, only its sub-runners learn, and a sub-mission started after the
  growth treats the new tool as baseline. Phase 11's one runtime is where that
  stops being two views. Three more swarm findings from a live staged run and
  its resume on a hosted model (17 Aug 2026, `gemini-3.6-flash` over the
  OpenAI-compatible endpoint, real stub, real store — the resume continued at
  index 8 with `resumed={from_seq: 25, steps_replayed: 8}` and finished
  `answered_with_caveat`): (1) `step_budget=4` is too small for the plans a
  real planner writes — one step meaning "fetch details for two runs" is four
  turns before it can answer, so a working step exhausts its slice and fails
  its gate; either the planner prompt says a step is one fetch or the budget
  scales with the plan; (2) after a redraw, `_synthesize` is handed the
  *original* plan on the live path and the *checkpointed* (redrawn) one on a
  resume, so each drops the other's step results — one owner is needed, the
  union of results in plan order then arrival; (3) compaction did exactly what
  it was built for, twice in one step (two 34 kB views, 17,194 → 9,080 tokens
  against a 14,000 limit, the whole result kept in the store). **Closed
  0.14.1** (lane AI, proved live on `gemini-3.6-flash` with the window probed
  at 1,048,576 tokens): the swarm's one `MissionWindow` bounds the router,
  planner, gates and synthesizer as well as the sub-missions (`_fit`); the
  step budget defaults to the mission's remainder, `max_plan_steps` to
  `max(2, max_steps // 2)`, and `summary_chars` to "the window decides" —
  the synthesizer is given every settled step's whole tool output and drops
  oldest-first only when the window says so; `_settled_order` is the one
  owner of the union after a redraw (a plan/queue aliasing bug fell out of
  the mutation check); the executor is told the objective as context; the
  figure check reads the answer with the same `FIGURE` boundary rule as the
  evidence, so `a.0000` is an actor and not the number zero. Still open: a
  resumed turn's evidence is the log's bounded `tool_result.output`; one
  greedy step can spend the whole mission budget (by design, documented);
  the planner may tag a step `code` on a plane with no code tool (prose
  clause, not a gate — a generic gate would withhold the rung from a bridged
  code tool).

### 2.6 Phase 11 — one runtime (0.16) — approved and in progress, 17 Aug 2026

Property 5. §1.2's "two agent runtimes" row is the whole case, and it has grown
a third claimant since it was written: `MissionRunner` (2,858 lines),
`SwarmRunner` (1,547, of which roughly 300 are a second copy of the first),
and the kernel `Orchestrator` + `LLMRoleDispatcher`. The run store, `--resume`,
the wall clock, the usage ledger, the native protocol, recording/replay and the
control channel all landed on the mission path only.

The measure of this phase is not lines removed. It is that **every duplicated
fact loses its second emitter**, which is the principle §3 states and which the
swarm has already violated once at a cost (six of ten `grounding` fields).

#### 2.6.1 The one loop object

`Run` is the loop. Its constructor is **data** — six cohesive objects, each the
one owner of a class of fact, and nothing else:

```python
Run(personality, plane, bounds, store, observer, model)

    def run(self, objective: str, resumption=None) -> Transcript      # façade
    async def arun(self, objective: str, resumption=None) -> Transcript
    def child(self, *, personality=None, bounds=None, branch="") -> "Run"
```

```python
@dataclass(frozen=True)
class Personality:              # what the model is told, and what it is held to
    system_message: str = ""            # cli.py — persona + manifest.prompt
    history: Sequence[Mapping[str, str]] = ()
    grounding: Optional[GroundingValidator] = None
    critic: Any = None
    sdk_import: str = ""

@dataclass(frozen=True)
class ToolPlane:                # the only way out, and who may say yes to it
    bus: Any
    offered: Sequence[str] = ()
    store_tool: str = RESULT_TOOL
    gated: FrozenSet[str] = frozenset()
    schemas: Sequence[Mapping[str, Any]] = ()
    # sandbox / audit_ref / profile are PROPERTIES read off the bus, never
    # fields: mission.py's sandbox_of/audit_ref_of/_profile_field are already
    # the one owner of each, and the swarm already reads all three from there.
    def lease(self, branch: str = "") -> "ToolPlane": ...
    def narrow(self, scopes: Sequence[str]) -> "ToolPlane": ...

@dataclass(frozen=True)
class Bounds:                   # everything that can stop a run, in one place
    max_steps: int = 0                  # 0 = no ceiling; an OPERATOR's --mission-steps only (0.15.0)
    deadline: Optional[Deadline] = None
    cancel: Any = None
    control: Any = None
    gate_wait_s: float = GATE_WAIT_S
    max_result_bytes: int = MAX_RESULT_BYTES
    started_at: Optional[float] = None
    supervisor: Optional[Supervisor] = None            # 0.15.0: what watches a run instead of a budget
    def stop(self) -> Optional[Stop]: ...              # mission._stop, once
    # (0.15.0) there is no portion(): the step budget is gone, a child shares
    # the same Bounds — one clock, one review budget — and the Supervisor is
    # what a child inherits.

@dataclass(frozen=True)
class Store:                    # what survives the process
    runs: Optional[RunStore] = None
    run_id: str = ""
    recorder: Optional[Recorder] = None
    approvals: Optional[ApprovalStore] = None
    ticket: Optional[ApprovalTicket] = None

class Observer:                 # every record out, and the redaction choke point
    def __init__(self, *sinks, branch: str = ""): ...  # cli `_watchers`
    def emit(self, event: str, **fields) -> None: ...
    def branch(self, name: str) -> "Observer": ...     # what `_StageObserver` was

@dataclass
class Model:                    # the client, the protocol, and the side channels
    ask: Callable[..., Any]                            # cli chat_fn
    plain: Optional[Callable[..., Any]] = None         # cli plain_chat_fn
    protocol: str = JSON_PROTOCOL
    window: Optional[MissionWindow] = None
    streaming: bool = True
    json_mode: bool = False
    usage_fn: Optional[Callable] = None
    tool_calls_fn: Optional[Callable] = None
    rate: Optional[Rate] = None
    ledger: Ledger = field(default_factory=Ledger)
    def spend(self) -> Dict[str, Any]: ...             # mission._spent, once
```

Note what is **not** a field. `audit_ref` stays a property of `ToolPlane`
because `mission.py`'s `audit_ref_of` already argues, at length, why a second
resolver of "where the audit log is" is worse than none. `sandbox` and
`profile` likewise. Six objects is the count; six *owners* is the point.

Deleted as duplicates the moment `Run` exists — the second emitter named for
each fact:

| Fact | The one owner, kept | The second emitter, deleted |
|---|---|---|
| `mission_finished` | `_finished_record` (mission.py), called from `arun`'s `finally` | three more call sites in swarm.py |
| `mission_started` | the opening built in `MissionRunner.run` | `SwarmRunner._opening`, whose own comment admits it is a hand-written copy |
| the grounding loop | `_answered`/`_ground`/`_second_opinion` (mission.py) | `SwarmRunner._ground` — and it had already drifted: no `critic=` on `SwarmRunner` until lane AF |
| the ledger fold | `Model.spend()`, from `MissionRunner._spent` | `SwarmRunner._spent`, `_usage_kw`, `_totals` — the same four lines twice |
| the deadline start | `Bounds`, over `Deadline.start` (first start wins) | the second `if self._deadline is not None: start()` in swarm.py |
| the stop verdict | `Bounds.stop()` (mission.py `_stop`) | `SwarmRunner._stop` and `_stopped`, line-for-line the mission's |
| the catalogue | `ToolPlane.offered` + `Run.catalogue()` | `SwarmRunner._offered`; `_short_catalogue` survives as a *rendering* |
| emit + redaction | `Observer.emit` (mission.py `_emit`) | `SwarmRunner._emit`/`_recording` |
| a child's records | `Observer.branch()` | `_OpenedAlready` and `_StageObserver` collapse into it |
| bounding a summary | `core.bounding.bound_result` | `SwarmRunner._bound_summary` |

Two Phase 10 findings (§2.5) were closed in 0.14.0 on `MissionRunner`
(`_relearn_the_plane` + `admits`/`plane_changed`; the `tool_key` gate rule) and
move into `ToolPlane` here: `lease()` is the refresh made data, and the gate
rule is `ToolPlane`'s question now that there is an object to ask.

#### 2.6.2 The four modes compose

They stop being four loops and become four ways of *withholding* a collaborator.

* **chat** — `Run(personality, ToolPlane.none(), Bounds(max_steps=1),
  Store.none(), Observer.none(), model)`. No tools, so `stacked` drops the
  catalogue section and the seed is persona + objective; no validator, so
  `_ground` returns `None`; no observer and no store, so `_emit` returns at its
  first line and chat emits exactly the nothing it emits today. `Agent.chat` is
  the caller, and the second window owner it uses — `ContextWindowManager`
  beside the `MissionWindow` every other path uses — becomes one.
* **mission** — tools + grounding. This is today's `MissionRunner`, unchanged
  on the wire.
* **swarm** — a `PlannerRole` that spawns child `Run`s via `Run.child()`,
  sharing **one** `Bounds` (one clock, one supervisor review budget — the
  per-step slice went in 0.15.0), one `Store`,
  one `Observer`, one `Model` (therefore one `Ledger`). `_direct` and `_runner`
  become one `child()`. The renumbering is the Observer's: `Observer.branch()`
  allocates the global `index` at emit time and carries the pending `plan` onto
  the next `step_started`, which is what `_StageObserver.__call__` does by hand.
* **coding kernel** — roles that are `Run`s with a judge. `RoleWindow` **is** a
  `MissionWindow` already (`class RoleWindow(MissionWindow)`), and
  `RoleContext.ask` is a hand-rolled `Model`+`Bounds`. `Orchestrator` stays
  above `Run` — see §2.6.5.

**Parallel child runs are the first new capability this buys**, and are the
reason to do the work rather than a reward for having done it. What parallel
needs, concretely:

1. *Per-child result stores, merged.* Each `Run` already owns one, but
   `MissionResultStore.register_on` raises `ResultStoreConflict` when the name
   is taken, so two children on one bus collide on `mission_result`.
   `ToolPlane.lease(branch)` returns a plane whose store tool is namespaced; the
   synthesizer reads the union, which the swarm already does by hand for
   `called_tools` (`_note_calls`).
2. *One ledger.* `Ledger.absorb` exists, is tested, and has **no caller in
   `core/`**. Children fold at join through it; `_fold` needs a lock or the join
   must be single-threaded. Prefer the join.
3. *One clock.* `Deadline` is shared and first-start-wins already.
4. *The audit column.* `bus.audit_context["step"]` is a mutable dict on a
   shared bus. Two children interleaving make that column *wrong* rather than
   absent. The step rides `dispatch` as a bus-named keyword, exactly as
   `deadline_s` already does.
5. *Ordering on the wire.* `RunStore.append` is already locked and monotonic.
   What is new is that `index` can no longer be the child's own: the `Observer`
   allocates it under a lock, and each record carries a new **OPTIONAL**
   `branch` so a consumer can demultiplex. An added optional field is a minor
   release; a consumer that never heard of `branch` reads a correctly-ordered
   single sequence.

#### 2.6.3 Async core, sync façade

`McpClient` already owns one background thread running one event loop and
every dispatch is an `asyncio.run_coroutine_threadsafe` into it. So the async
is already here; what is missing is a caller that can await it.

* `async def Run.arun(...)` is the loop. `def Run.run(...)` is
  `asyncio.run`/`run_until_complete` and nothing else, and it is what `judais`
  calls.
* **Natural, once it is async:** parallel children (`asyncio.gather` over
  `Run.child`); streaming as an async iterator instead of `drain_answer`'s
  callback; the control channel as a queue instead of a reader thread plus
  `poll()`; cancellation as `CancelledError` at the same drain points the loop
  already chose.
* **Must not change, and there is a test for each:** the wire (`contract.py`,
  `tests/test_contract.py`); byte-identical json-mode messages — `seed`'s
  most-constant-first order and `stacked`'s whitespace are a *served endpoint's
  KV cache key*, so an `await` that moves one byte of the prompt costs a
  deployment money; `contract.CLI_FLAGS` and the exit contract.
* The MCP client's own loop thread stays for the sync façade. Under `arun` the
  plane awaits the session directly and the second loop disappears — a lane-C
  refinement, not a precondition.

#### 2.6.4 Migration in lanes

Five lanes, each shippable and green alone, ordered so the wire is
byte-identical at every step.

**Lane A — the extraction. No behaviour change.** Lift the six objects out of
`mission.py` into `core/runtime/run.py`; `MissionRunner.__init__`'s parameters
become an adapter that builds the six and delegates. `SwarmRunner` is not
touched. **Guard: the corpus diff.** A new `tests/test_run_corpus.py` replays
every fixture in `tests/fixtures/runs/` and every stream in
`tests/fixtures/eval/` through the new `Run` via `--replay`'s own machinery and
asserts the emitted records are equal, in order, field for field, to the
recorded ones. Lane A ships when that diff is empty.

**Lane B — the swarm becomes a `Run` client.** Delete the ten second emitters
in the table above; `_StageObserver`/`_OpenedAlready` → `Observer.branch`;
`_runner`/`_direct` → `Run.child`. The staged corpus fixture
`run_corpusswarm-0001` exists (0.14.0, lane AH) and is lane B's guard beside
the other two. The supervisor's `review_gate`/`replan` (0.15.0) and the
synthesizer over whole evidence (0.14.1) are swarm behaviours that stay.

**Lane C — async core, sync façade.** `arun` is the loop, `run` is the wrapper,
the corpus diff runs again unchanged.

**Lane D — parallel children.** The five items of §2.6.2, the OPTIONAL `branch`
field, and the first eval-harness column that can show it: a staged suite run
serial vs parallel, same score, less wall time. Minor bump.

**Lane E — chat and the roles.** `Agent.chat` through `Run`; `RoleContext.ask`
through `Model` + `Bounds`; `set_scope_constraints` through `ToolPlane.narrow`,
which closes §1.2's "two governance surfaces" residual without moving the
state machine.

**Which tests move.** None, for four lanes. `tests/test_contract.py`,
`tests/test_cli_mission_skill.py`, `tests/test_mission_end_to_end.py`,
`tests/test_agui.py`, `tests/test_record_replay.py` and `tests/test_eval_*`
stay untouched and green throughout — if one of them needs editing, the lane
changed the seam and is wrong. `tests/test_mission.py` stays on
`MissionRunner`: it is the adapter's conformance suite, and it is the reason the
adapter exists. New `Run`-shaped tests go in a new file. `tests/test_swarm.py`
stays on `SwarmRunner` through lane B — the class becomes a composition, its
tests do not move.

**Mutation-checking a refactor.** The usual rule — every new assertion must be
shown to fail — is unsatisfiable here, because a correct refactor's assertions
pass against the old code too. **The corpus diff is the mutation check**, and it
is mutated at the *implementation*: drop `verified` from `_grounding_record`;
swap the `grounding`-before-`answer` order; drop `elapsed_s` from
`_finished_record`. Each must turn the diff red, and each must be reverted with
`__pycache__` cleared — a same-size same-second revert keeps stale bytecode and
lies.

#### 2.6.5 Risks and non-goals

* **The kernel path is a `Run` client, not a `Run`.** Phase 11 makes the
  *roles* `Run`s (lane E) and leaves `Orchestrator`, `CampaignOrchestrator`,
  the judge and the patch engine above it. Folding the state machine into `Run`
  would put phase transitions inside the loop the model drives, which §3's
  "Static Graphs, Adaptive Phases" forbids in as many words. What Phase 11 owes
  the kernel is that its roles get the run store, the clock, the ledger and the
  control channel by construction — not that its graph disappears.
  `core/kernel/budgets.py` keeps `PhaseRetriesExhausted` (`which="retries"`,
  the one budget the mission has no word for) and folds the other two into
  `Bounds`.
* **`Agent.run_task` — delete, in lane E.** No caller in `core/` or `main.py`;
  `run_campaign` keeps `_make_task_dispatcher` alive. Put the six lines a caller
  would write in `PLATFORMS.md`.
* **`wip/web-research-fetcher` is irrelevant.** Do not rebase Phase 11 onto it,
  do not merge it first, do not let it decide `ToolPlane`'s shape.
* **The reference deployment is frozen on 0.12.2 and nothing here may reach it.**
  No `SCHEMA_VERSION` bump, no required field added or renamed, no flag removed
  from `contract.CLI_FLAGS`, no change to `EXIT_CONTRACT`. Lane D's `branch` is
  the only wire addition in the whole phase and it is OPTIONAL.
  `tests/test_contract.py` is the tripwire; the reference platform's bridge and
  pin tests are run against the tree before every tag, even though nobody is
  being told about the release.

#### 2.6.6 What Phase 13 becomes once `Run` exists

* `Run(personality, plane, bounds, store, observer, model)` **is** the API.
  `_mission` in `core/cli.py` becomes argparse building six objects — the CLI
  as a client of the library, which is what "library API first, the CLI second"
  was asking for.
* **The import path, without a fourth top-level package.** The wheel's
  top-level names are `core`, `judais`, `lobi`, and `tests/test_packaging.py`
  pins exactly that set. Ship `judais_lobi.py` at the root as a single
  **module** via `py_modules=["judais_lobi"]`: `find_packages()` never sees it,
  the pinned set is unchanged, and `from judais_lobi import Run` works. Grow
  `test_packaging.py` a companion assertion over `py_modules` in the same
  commit. A fourth top-level *package* is warranted only when the façade needs
  submodules — a decision to take then, on that evidence.
* **Model-state events** (`cold`, `asking`, `queued`, `loading`, `loaded`,
  `failed`, `absent`) get exactly one emitter for free: after Phase 11,
  `Model.ask` is the only place a run touches a backend. Today those words would
  need emitting from `chat_fn`, `plain_chat_fn`, the critic and the reading tier.
* **The `[server]` extra** needs nothing from `Run`. It follows
  `RunStore.follow`, so it is a `Store` client and can ship on its own schedule.

#### 2.6.7 Still to delete or promote

- Delete or promote what is left vestigial: the second vector index, if FAISS
  is required at all. (`curl`-Mistral went in 0.8.2; `tools/recon/*` and
  `bootstrap.py` are gone — nothing imported either, and the recon pair wanted
  selenium and undetected_chromedriver that no extra declared. `kv_prefix.py`
  and `runtime/gpu.py` went in 0.9.0.)

### 2.6a Phase 14 — the step budget is gone (0.15.0, shipped 17 Aug 2026)

Owner's words: "sometimes tasks take more budget. instead we should only
worry about catching an endless loop where it is stuck … if it just needs
more thinking. Let it think. just seriously kill this concept completely."

The framework no longer decides how many turns a question is worth.
`--mission-steps` and `--mission-seconds` are now the same kind of thing — an
operator's optional ceiling, unset by default, `max_steps: 0` on the wire (the
required `steps`/`max_steps` fields stay, so the pinned consumer reads them
unchanged) — and the job the eight-step default was actually doing is done by
`core/runtime/supervisor.py`: mechanical signals that watch for *repetition*
(the same call returning the same result three times within six, three
rejected replies running, four steps with no new evidence, an A-B-A-B
oscillation), each putting one plain-chat question to the same model, which
answers `progressing`, `nudge` (a note injected at the next step boundary, on
the record as `step_started.review` beside `injected`) or `stuck` (the run is
asked for its best answer and ends `reason: "stuck"`). Three reviews a run and
the last cannot say `progressing` — that is the endless-loop catch, and it is
arithmetic rather than judgement. Nothing counts tokens, output length or
thinking time. The swarm's `step_budget`, `retries_per_step` and one-redraw
counter are deleted: a failed gate is put to the supervisor, which may also
say `replan`. `review` is a new OPTIONAL field; SCHEMA_VERSION stays 1.
Proved live on `gemini-3.6-flash`: an 11-step run that the old default would
have killed at 8 finished `answered_with_caveat` after a `progressing` review
(the reviewer read the operator's polling instruction correctly); three
identical failing calls drew a `nudge` and the run recovered to `answered`.
Unproven live (proved against the stub): the `stuck` wind-up and the swarm's
`failed_gate`/`replan` — the live model declines to repeat itself a third time
on a plainly broken tool. Open: a resumed run starts watching afresh (the
nudge never travelled as a message — the gap operator injections have too).
Phase 9's "bounded" now reads: bounded by the operator, supervised by the
framework.

### 2.7 Phase 12 — providers and streaming (0.13)

Properties 4 and 6.

- ~~One HTTP client for every hosted provider; a retry/backoff policy per
  error class in one neutral place; Anthropic as a first-class backend.~~
  **Shipped 0.14.0**: one client per provider (the SDK for OpenAI and
  Anthropic, `requests`/`httpx` for local and Mistral) behind
  `core/runtime/backends/policy.py` — `CHAT_TIMEOUT`, `CONNECT_RETRIES`,
  `ERROR_POLICY` as data (connect → retry, timeout/4xx/5xx → not, each with its
  reason); `anthropic_backend.py` translates both directions, streams, carries
  native tools, reports `supports_json_mode=False`, defaults to `claude-opus-5`
  and is never fallen back from. Phase 12 is closed.
- ~~**`answer_delta` at the source.**~~ **Shipped 0.12.0**: the tenth event,
  `answer_delta` (`index`, `part`, `text`), emitted while the answer streams
  from the model (json: the `"answer"` value; native: `mission_answer.text`),
  bounded at 64 chars/newline; the `answer` record ALWAYS follows and is
  authoritative, grounding rides right after it as before; streaming is on by
  default (`--no-stream`/`MISSION_STREAM=off`). Also shipped 0.12.0, from
  Phase 13's list: a **control channel INTO the run** — `--control fd:N|path`
  (`MISSION_CONTROL`), NDJSON commands `inject` (a user instruction before the
  next model call, `injected` on `step_started`), `cancel`, `cancel_step`, and
  `gate_decision` (a gate waits in-turn, bounded, when a channel is open;
  approve dispatches that one call now through the same approval store; refuse
  tells the model; timeout ends `awaiting_approval` as before). Keep the design
  lesson: the grounding verdict rides the answer's own frames, never a sibling
  event. ~~Ship the AG-UI translator as an optional
  `core.runtime.agui` so the next browser does not rewrite it.~~ **Shipped:**
  `core/runtime/agui.py` — `translate()` over a whole run or a `RunStore`
  replay, `Translator.feed/close` for a live follower, dicts only and no AG-UI
  SDK. Every event of `contract.EVENTS` is mapped and a test fails when the
  contract grows one that is not; the verdict rides the answer's frames and
  names the `messageId` it judges; an interim `repairing` report does not close
  the message; `answer_delta` is relayed when the contract declares it and
  fanned out from the `answer` record when it does not. `PLATFORMS.md`
  §"AG-UI" is the driver's copy.
- **Reply-rejection buffering.** A rejected reply is mechanics, not content;
  a consumer must be able to render it as such. **The marking shipped** with
  the translator (`CUSTOM mission.reply_rejected`, `mechanics: true`, never a
  `TEXT_MESSAGE`); holding a rejection back until the turn's fate is known
  stays the consumer's policy, which is the half this repo must not decide.
- ~~Wire the probed constrained-decoding path (`response_format`,
  `tool_choice=required`) behind a capability flag, measured by Phase 10.~~
  **Pulled forward and shipped in 0.11.0** on the reference deployment's
  evidence (2 of 4 turns burned on shape errors): `--protocol native` /
  `MISSION_PROTOCOL` — `tool_choice="required"` over the declared tools plus a
  synthetic `mission_answer` function, so an unknown name or unparseable
  arguments are unrepresentable; several calls per step (`call` ordinal on
  `tool_call`/`tool_result`); JSON-schema validation of arguments before
  dispatch (`core/runtime/schema_check.py`, both protocols); OpenAI message
  shapes; native runs resume; `protocol` on `mission_started`. Every backend
  exposes `last_tool_calls`; the swarm's router/planner/gates ask for
  `response_format=json_object` where the backend has JSON mode; the prompt
  prefix is byte-stable and most-constant-first, and the window evicts tool
  round trips before user turns. **Default stays `json`** until Phase 10's
  harness scores the two — that measurement, not this bullet, flips it.

### 2.8 Phase 13 — embeddable (1.0)

Property 6.

- **Library API first**: `from judais_lobi import Run, Personality, Skill,
  Tools`, speaking the same contract the CLI speaks; the CLI becomes a thin
  client of it.
- **Model-state events** as a first-class channel — `cold`, `asking`, `queued`,
  `loading`, `loaded`, `failed`, `absent`. A deployment learned that "queued"
  is not "loading" and that a browser must be able to say which.
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
different words. Merged, deduplicated, and still true at 0.12.0. The eight the
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

*The **coding-tier** critic described above still has no production caller — it is reached only when an `Orchestrator` is constructed with `critic=`, and nothing in `core/` does that. The **mission-tier** critic got one at 0.13.0: `core/critic/mission.py`, switched on by `grounding: critic: true`, local first via `LOCAL_API_BASE`, its verdict an `advisory: true` row in `grounding.checks`.*

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
