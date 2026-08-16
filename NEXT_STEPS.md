# NEXT_STEPS.md — from Tai's lessons to a capable agentic framework

Written 15 Aug 2026, the day judais-lobi was separated from TAIPAN, against
`master` at 0.8.0. Every claim below was verified in the tree that day; the
file:line cites are the evidence, not decoration. Re-verify before acting.

## 1. Where we have been

For two weeks judais-lobi ran as **Tai**, the mission agent inside the TAIPAN
platform: a 20B local model, an MCP tool plane of ~20 governed tools, a browser
pane reading the NDJSON mission stream, real analysts, a recorded bake-off
against a second harness (Goose), and a behavioural eval that went from
6-of-10 missions reporting `0/0 … grounded` to 10/10 with 0% error.

That pressure produced the framework's best parts, and they are already here:

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

And it exposed what is still only in TAIPAN's wrapper — the durability,
presentation and trust layer. That list is in `CLAUDE.local.md` §Backlog and
is folded into the phases below.

## 2. Where the repository is (honest)

~20.5k non-test lines, ~20.3k test lines, 1,829 tests, one-owner discipline in
the new modules, docstrings that say what is not wired yet. Strengths: the
grounding validator, the mission stream and its contract, the MCP client, the
skill manifest as the only content channel, the swarm's failure containment.

What separates it from a framework you would trust unattended — each verified:

| Gap | Evidence |
|---|---|
| **No sandbox by default.** `NoneSandbox` is `subprocess.run(shell=True)` with the full inherited env; the working `BwrapSandbox` has no production caller. | `core/tools/sandbox.py:23-54, 149-156` |
| **Allow-everything policy by default.** `Tools()` builds the capability engine with `PolicyPack(allowed_scopes=["*"])`; audit, god-mode and preflight are never attached to the default bus. | `core/tools/__init__.py:60-69`, `bus.py:48-63` |
| **The real agent path persists nothing.** A CLI mission writes only the optional NDJSON; `SessionManager` (non-atomic `write_text`) serves only the kernel path the CLI does not reach. | `core/sessions/manager.py:53-146` |
| **No wall-clock bound, no cancellation.** Step count + tool timeouts only; a contended local model can hang a turn forever. | `core/runtime/mission.py:540` |
| **No usage or cost accounting.** Only char/4 estimates for compaction. | grep: no `usage`/`prompt_tokens` anywhere |
| **Two agent runtimes.** `MissionRunner`/`SwarmRunner` (JSON protocol, MCP, CLI) and the kernel `Orchestrator`+roles (state machine, sessions, judge, patch) do not share sessions, budgets or governance. Result-bounding and context caps are each implemented twice. | `core/runtime/mission.py` vs `core/kernel/` |
| **No token streaming or constrained decoding in agentic runs.** Missions call `chat(stream=False)`; the probed grammar/tool-choice path is deliberately unwired. | `core/cli.py:242-303` |
| **Thin provider layer.** Three providers; Mistral shells out to `curl`; retry only on the local backend and only on refused connect. | `core/runtime/backends/mistral_backend.py:25`, `local_backend.py:274` |
| **No reproducible eval.** The 10 Aug measurements live in docstrings; in-repo there is one recorded-fabrication fixture and an MCP stub. | `tests/fixtures/`, `tests/mcp_stub_server.py` |
| **Built, tested, unreachable.** External critic, `reading.py`, `kv_prefix.py`, `policy/audit`, `god_mode`, `Agent.run_task`. | importer scans |

None of this is a design flaw. It is the honest shape of a framework whose
last two weeks were spent making one deployment truthful. The next phase is
making the *default* deployment trustworthy.

## 3. What "capable, not a toy" means here

Six properties. A framework has them by default, not by injection:

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

## 4. Recommended next steps

Ordered so that each phase makes the next cheaper. Each item names the seam it
touches and, where the answer already exists somewhere, where to take it from.
Lane it: builder in a worktree, tests in the file's idiom, mutation-checked,
reviewer lane, conductor merges. Version bump every phase.

### Phase 0 — done 15 Aug (0.8.0)
Contract as data; de-TAIPAN; `tai` entry point; `mission` extra; SIGTERM
close; swarm grounding through the shared renderer; pool checkout by tag;
`PLATFORMS.md`; TAIPAN pins the release and asserts against `contract`.

### Phase 1 — safe by default (0.9)
- **Sandbox on by default.** `Tools()` selects `BwrapSandbox` when `bwrap` is
  present, `NoneSandbox` only under an explicit `--unsandboxed`/env opt-out
  that is *announced* on the stream. `SandboxProfile` honoured on both.
- **Deny-by-default policy.** Default `PolicyPack` = the `SAFE` profile
  (`core/policy/profiles.py`); the skill manifest's `allowed_tools` and the
  policy scopes compose (both must allow). `--profile dev|ops` opts up.
- **Audit on the default bus.** Attach `AuditLogger` (append-only JSONL, secret
  redaction) to every `ToolBus`; the mission stream gets an `audit_ref`.
- **`run_python`/`run_shell` never reach a hosted mission by accident**: a
  manifest that names them must also declare `sandbox: bwrap` or the resolve
  refuses. (TAIPAN's `HOSTED_SDK_CODE_PLANE_DESIGN.md` names this exact hazard.)
- **Scrubbed error surface.** Tracebacks that reach the stream/answer are
  passed through one redactor (home dirs, hostnames, tokens); TAIPAN's deferred
  "location sweep" exists only because core leaks absolute paths.

### Phase 2 — durable and bounded (0.10)
- **Port TAIPAN's thread primitive** (`TAIPAN/src/taipan/mission/threads.py`):
  monotonic `seq`, fsync'd append-only JSONL, atomic `os.replace` for metadata,
  `since(cursor)` + `follow()`; carry the recorded reused-`seq` bug as a test.
  Make it the mission's transcript store; `SessionManager` becomes a client of
  it, not a second store.
- **Resume.** `judais --mission --resume <run-id>` replays the stream to the
  last `mission_finished`-less step and continues; the swarm's plan and step
  results are checkpointed per step.
- **Wall-clock budget + cooperative cancel.** `--mission-seconds`; a
  `budget_exhausted` outcome names which budget (steps/seconds/bytes/tokens).
  Kernel `budgets.py` already has the dataclass — one owner.
- **Usage ledger.** Every backend returns `usage`; the run accumulates prompt/
  completion tokens and (for hosted providers) cost; `mission_finished` carries
  it; the ledger is a first-class event so a platform can meter.
- **Approvals as durable records.** Core has the ask half (`--gate-tool`,
  `gate_requested`, `AWAITING_APPROVAL`). Add the resume half from TAIPAN's
  `approvals.py`/`agent.py:255-267`: a decision arrives on a later turn as a
  record, and widens the closed set by exactly one tool for exactly one turn.
  Nothing defaults or expires into a yes.

### Phase 3 — measurable (0.11)
- **An eval harness in-repo.** Bring the *shape* of TAIPAN's bake-off
  (`TAIPAN/src/taipan/agent/bakeoff.py`): missions × behavioural flags
  (orientation, chaining, absence, state, boundary, disambiguation, submission,
  synthesis), a mechanically-held train/test split, a dated `RUBRIC_CHANGES`
  ledger, scoring from the *recorded stream* not the agent's self-report. Run
  it against the MCP stub server so it needs no GPU; run it against a live
  endpoint when one is offered.
- **Recorded-run replay.** A recorder (TAIPAN's `record_tai_mission.py` is
  the black-box shape) that captures model I/O + tool I/O so a mission can be
  replayed deterministically and a grounding change scored on yesterday's
  runs. Grow `tests/fixtures/` from one fabrication file into a corpus.
- **Wire what is built.** `reading.py` (field-misreading, the `total_s: 80.847`
  lesson) becomes a grounding tier behind a manifest flag; `critic/triggers.py`
  fires the external critic on `answered_with_caveat` when a provider is
  configured. Both measured by the harness before they are on by default.
- **Plane-claim check.** `grounding.py` already carries `tools_offered`; refuse
  a claim of a plane whose tools were not offered *and called* this turn (the
  strong form TAIPAN's `tai.toml:120-131` says belongs here).

### Phase 4 — one runtime (0.12)
- Collapse `MissionRunner`/`SwarmRunner` and the kernel `Orchestrator` onto one
  loop object: `Run(personality, tools, policy, budgets, store, observer)`.
  Modes are compositions: chat = no tools; mission = tools + grounding; swarm =
  a planner that spawns child `Run`s; coding = roles that are `Run`s with a
  judge. Result bounding, context management (`ContextWindowManager` is only on
  the chat path today), budgets and governance are then written once.
- **Async core, sync façade.** The MCP client already runs a loop thread; make
  the run loop `async` so tool calls, streaming and cancellation are natural,
  and keep `judais` sync at the CLI edge.
- Delete or promote the vestigial: `kv_prefix.py`, the second vector index if
  FAISS is required, `curl`-Mistral. (`tools/recon/*` and `bootstrap.py` are
  gone: nothing imported either, and the recon pair wanted selenium and
  undetected_chromedriver that no extra declared.)

### Phase 5 — providers and streaming (0.13)
- One HTTP client (httpx) for every hosted provider; retry/backoff policy per
  error class in one place; Anthropic as a first-class backend (the critic
  already speaks it).
- **`answer_delta` at the source** — TAIPAN fans one `answer` record into
  bounded deltas client-side (`bridge.py:741-780`); emit real deltas here, and
  keep the design lesson: the grounding verdict rides the answer's own frames.
  Ship the AG-UI translator TAIPAN wrote as an optional `core.runtime.agui`
  so the next browser does not rewrite it.
- Wire the probed constrained-decoding path (`response_format`,
  `tool_choice=required`) behind a capability flag, measured by Phase 3.

### Phase 6 — embeddable (1.0)
- **Library API first**: `from judais_lobi import Run, Personality, Skill,
  Tools` with the same contract the CLI speaks; the CLI becomes a thin client.
- Model-state events (`cold/asking/queued/loading/loaded/failed/absent`) as a
  first-class channel — TAIPAN's `model.py:121-292` learned that "queued" is
  not "loading" and a browser must be able to say so.
- A `judais-lobi[server]` extra: an SSE endpoint over the stream store, with
  the operational rules TAIPAN paid for (stream cap below connection ceiling,
  heartbeat inside the socket write timeout, no refusal after first byte).
- 1.0 = contract `SCHEMA_VERSION` frozen for a major, `PLATFORMS.md` is
  sufficient to integrate without reading source, and the eval harness runs in
  CI on every push.

## 5. Principles to keep (they are why the framework is worth continuing)

- **Refusals name the reason and the fix.** Every one Tai emitted in the demo
  was read aloud as a feature. Keep it that way.
- **One owner per fact.** The swarm's six-field grounding drift is what a
  second emitter costs. Route through the renderer, derive the list.
- **The seam is data.** Add to `contract.py`, bump `SCHEMA_VERSION` when
  breaking, keep the consumer test that cannot pass by absence.
- **Tests must be able to fail.** Mutation-check; clear `__pycache__`; a
  same-size same-second revert lies.
- **Nothing platform-specific in core.** Env, manifest field, or injection —
  never a path, hostname, tool name or SDK name.
- **If a human can, an agent can — under the same governance.** The framework
  supplies content; the platform supplies every judgement about it. That
  division is what made the trust boundary safe, and it holds at 1.0.
- **Measure before default.** Nothing becomes on-by-default until the harness
  scores it against a held-out set.

## 6. How you know it is no longer a toy

- A fresh `pip install 'judais-lobi[mission]'` runs a mission with tools
  isolated, deny-by-default scopes, an audit file, a bounded budget, a
  resumable transcript, and a usage ledger — with zero flags.
- Killing the process mid-run and resuming produces the same stream suffix.
- The eval harness reports a score for a release, and that score is
  reproducible from recorded runs on a machine without a GPU.
- A second platform integrates in an afternoon from `PLATFORMS.md` alone, and
  its conformance test goes red the day the contract breaks.
