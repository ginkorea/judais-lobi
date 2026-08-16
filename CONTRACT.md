# The mission contract

**Schema version 1.**

This is what a program that runs `judais --mission` may rely on. It is the
human rendering of `core/runtime/contract.py`, which is the authority; a test
(`tests/test_contract.py`) fails if the two disagree, so this file cannot quietly
go stale.

It exists because the halves now move separately. TAIPAN pins a release of this
repo, spawns the CLI, and reads NDJSON off an inherited descriptor. Everything
below used to be convention — names in a docstring, outcome words scattered
through the loop, a `repairing` field the consumer indexed and this repo had
never written down. Convention is fine while one person holds both halves. It
is not fine once they ship on different days.

## Reading the stream

One JSON object per line, flushed as it happens, UTF-8 and not escaped.

```
--events -        stdout, for a person with jq
--events fd:N     an inherited descriptor — what a harness uses
--events PATH     a file, opened for append
```

Switch on `event`. **Drop record types you do not know**: this repo may add one
in a minor release, and a consumer that fails on an unrecognised name would turn
every addition into a breaking change. Assert your ignorance in a test rather
than in production — TAIPAN's `bridge.READS` is a frozenset with a test that
fails when this repo declares something new, which is how "no opinion" stays a
decision somebody made.

## Events

Every field listed is present on **every** emission of that event, from the
direct loop and from `--swarm` alike. Index them without a default.

| event | required fields |
| --- | --- |
| `mission_started` | `schema_version`, `objective`, `catalogue`, `gated`, `max_steps`, `history` |
| `step_started` | `index` |
| `reply_rejected` | `index`, `problem` |
| `tool_call` | `index`, `tool`, `arguments` |
| `tool_result` | `index`, `tool`, `arguments`, `ok`, `exit_code`, `output`, `error`, `handle`, `truncated` |
| `gate_requested` | `index`, `tool`, `arguments`, `reason` |
| `answer` | `text`, `outcome` |
| `grounding` | `ran`, `grounded`, `verified`, `repairs`, `repairing`, `caveat`, `unsupported`, `silent`, `uncited`, `checks` |
| `mission_finished` | `outcome`, `steps`, `max_steps` |

Optional, and therefore to be read with a default: `audit_ref`, `run_id` and
`protocol` on
`mission_started`, `call` on `tool_call` and `tool_result`, `plan` on `step_started`
(`[{id, goal, rung}]`, on the first step of a staged `--swarm` plan and again
on the first step of a redrawn one), `tool` on `reply_rejected` (present
only when the model got as far as naming one), `compacted` and `resumed` on
`step_started`, `approval_id` on `gate_requested`, `sandbox` and `profile` on
`mission_started`, `usage` on `tool_call`, `answer`, `reply_rejected` and
`mission_finished`, and `budget`, `reason` and `elapsed_s` on `mission_finished`. `plan`
rode `mission_started` until 0.8.x: that record is now emitted before triage —
which is itself a call to the model — so at the time it is written there is no
plan and there may never be one.

`sandbox` is `"bwrap"` or `"none"`: the isolation the mission's tool
subprocesses ran under. `"bwrap"` is write isolation with the network denied
unless a tool declared it and the child environment stripped to a small
allow-list; `"none"` is no isolation, reached only by an explicit opt-out
(`--unsandboxed`, `JUDAIS_LOBI_SANDBOX=none`) or a host without bubblewrap.
It describes the subprocess plane only — an in-process MCP tool dispatches
inside the harness process and touches no sandbox whatever this says — and it
rides both the direct and the staged path.

`protocol` says how the model was asked to decide, and it is present **only
when that is not the default**: `"native"` on a run started with
`--protocol native`, and absent on every other run, which a consumer reads as
`"json"`. The absence is the point — it is what keeps every stream recorded
before this field existed byte-identical — and it is the same rule `reason`
and `budget` follow: a field states a fact only when there is one to state.

Under `json` the model writes one JSON object per reply and this harness
parses it; a reply that does not parse is a `reply_rejected` and costs a
turn. Under `native` the request declares the mission's tools as functions,
declares a synthetic `mission_answer(text)` beside them, and asks for
`tool_choice=required` with `parallel_tool_calls=true` — so an unparseable
reply and a tool name nobody offers are *unrepresentable* rather than caught,
and finishing is a call to `mission_answer`. What changes for a consumer:
**one model turn may produce several `tool_call`/`tool_result` pairs under one
`index`**, told apart by `call`.

`call` is which call of the step this is, 0-based, in the order the model
emitted them. **Absent on the first call of a turn and absent for every call
of a `json` run**, so a consumer that never heard of it reads the stream it
always read. `index` still numbers the *model turn* and is what
`--mission-steps` counts, in both protocols: two records with the same `index`
and different `call` are two dispatches asked for in one breath, not two
steps. A call the harness refused before dispatching it — a schema violation,
a name nobody offers — still uses up its ordinal, because the number describes
what the model emitted rather than what ran. `usage` rides the **first** record
of a turn only: it is the cost of one model call, and a turn that dispatched
three tools did not pay for it three times.

A gated tool under `native` ends the turn on **that** call: the calls before it
have already run and are on the record, the calls after it are not dispatched,
and `gate_requested.reason` says how many were dropped with it.

`profile` is the capability profile the run is governed by — one of `safe`,
`dev`, `ops`, `god`. Deny-by-default means `safe` unless `--profile` (or
`JUDAIS_LOBI_PROFILE`) opted up, and a watcher reading the opening frame can
tell a read-only mission from one that can write, execute or reach the open
network. Absent, rather than `null`, when the bus was built from a raw
capability engine that never recorded a profile name.

`audit_ref` is a **string or `null`**: the path of the append-only JSONL file
this run's tool dispatches are being recorded in, or `null` when auditing was
turned off explicitly with `JUDAIS_LOBI_AUDIT=none|off`. The default is
`.judais-lobi/audit/<run-id>.jsonl` under the harness's working directory, one
file per process, and `JUDAIS_LOBI_AUDIT=<path>` moves it. The null matters as
much as the path: a consumer that simply finds no audit file cannot tell a
harness that failed to write one from a harness that was told not to, and only
one of those is a decision somebody made. It is a path on the spawning host,
not a URL, and the same string arrives on every mission that process runs.

`run_id` is the durable transcript of this mission: one directory per run
under `.judais-lobi/runs/<run_id>/`, holding an fsync'd append-only
`events.jsonl` and a `meta.json` replaced atomically. Every record on this
stream is appended to that log *before* it reaches the event sink — the sink
is a client of the log, not a second copy of it — each wrapped in a
`{seq, at, record}` envelope. The envelope is the store's numbering and never
travels on the wire, so the records a consumer reads are byte-identical
whether they came off the pipe or off the disk; `seq` is the cursor a replay
resumes from. A log whose records include `mission_finished` is a run that
closed; a log without one is an orphan, which is how a restart tells a mission
that died from a mission that is still going. **Absent, not `null`**, when
nothing is being recorded — `JUDAIS_LOBI_RUNS=none|off`, or a library caller
that passed no store. It is a run id and not a path: the directory is
`<runs root>/<run_id>`, and the runs root is the harness's own
`.judais-lobi/runs/` unless `JUDAIS_LOBI_RUNS` moved it. No credential is
written there — not the value of `MCP_TOKEN`, and not a transport that might
carry one.

`resumed` is `{from_seq, steps_replayed}` and rides the **first**
`step_started` of a stretch that continues an earlier one
(`--mission --resume <run-id>`), and no other record of the run.

**A resumed run does not emit a second `mission_started`.** It is the same
mission: one objective, one catalogue, one `run_id`, one log. A consumer
reading the whole log of a run that was resumed twice would otherwise find
three openings for one mission and render three of them; and a follower
holding a cursor is already past the opening, so the frame would be one it
never receives. `step_started` is the next record such a follower *will*
receive and the first moment at which the resumption is true.

`from_seq` is the envelope `seq` the log had reached when the run was
reopened — where the earlier half ends, so a consumer that joined late can
fetch exactly that half and nothing twice. `steps_replayed` is how many steps
were rebuilt out of it, so the `index` on this record — which continues the
earlier numbering rather than starting again — is not read as a gap. A run
resumed with nothing left of its step budget emits no `step_started` at all
and therefore no `resumed`: it goes straight to `mission_finished` with
`budget_exhausted`.

A resumed run's log may therefore hold **more than one**
`mission_finished`. The earlier ones are where a previous process stopped —
`incomplete`, emitted from its `finally`, or written by the orphan
reconciliation below — and `resumed` on the `step_started` that follows is
what says the run went on. Only two recorded outcomes can be picked back up
(`incomplete` and `awaiting_approval`) plus a log with no `mission_finished`
at all; `answered`, `answered_with_caveat` and `budget_exhausted` are
conclusions and are refused, naming the word the run ended on.

**Orphan reconciliation.** Every mission, on the way in, closes the logs of
runs nobody else will: a run in the same store with no `mission_finished`
whose `meta.json` has not been written for 60 seconds gets one appended,
`incomplete`, with `steps` counted off its `step_started` records and
`max_steps` off its opening frame. A follower's stream therefore ends rather
than stopping mid-sentence. The staleness is a guard and not an optimisation
— a mission merely thinking has no `mission_finished` either, and closing its
log out from under it would send the answer it is about to give to nobody —
and the run the closing process is itself working on is excluded outright.
That the run was reconciled is recorded as `orphaned_at` in its metadata and
not as a field on the stream: it is a fact about the run, not about the
mission, and a consumer that had to learn a word to read this ending would be
learning one about the reconciler.

`max_steps` counts the **whole run** across a resume, recorded steps
included, and `mission_finished.steps` likewise — so the two stay comparable.
Without `--mission-steps` the resumed stretch is held to the total the run was
started with; with it, the number is read as that many *further* steps and the
total becomes what was spent plus what was asked for. A resume cannot buy a
fresh budget by omission.

Not everything replays. The typed payload of a tool result
(`structuredContent`) never travelled on this stream, so a replayed result has
its text and not its parsed fields: grounding still sees the text, and
`mission_result(handle=…, path=…)` refuses a field path into a replayed
result. The text of a rejected reply is not carried either — `reply_rejected`
carries the refusal, and the reply is precisely the thing that did not parse.
The harness says which of these applied on the console rather than replaying
in silence.

`compacted` is `{dropped_turns, dropped_messages, freed_chars, tokens_before,
tokens_after, limit_tokens, profile, dropped_results}` and is present only on
the steps where older tool round-trips had to be dropped from the conversation
to keep it inside the model's context window. The persona, the tool catalogue,
the seeded history turns, the objective and the newest round trip are never
dropped. The counts describe that one step, not a running total.

`dropped_results` — a key added after `profile`, so a consumer that predates it
reads the record exactly as before — is how many of `dropped_turns` were TOOL
round trips: one model decision and the output that answered it, whether that
answer arrived as one rendered result or as several `tool` messages. It is
named separately because those are what go **first**. Tool output is the bulk
of a long mission and it is the only part of the conversation that is also
somewhere else — the mission's result store still holds every byte of it under
a handle the model can still read — while a turn somebody actually said is
cheap and is what a follow-up question refers back to. So the eviction order is
stale notice, stranded half round trip, tool round trip oldest-first, and only
then the oldest said turn.

It is on the stream because the alternative is the failure it prevents: an
agent whose earlier evidence quietly left its prompt looks, from outside,
exactly like an agent that had it all along. Nothing is lost to the run —
`tool_result` already carried the whole of every result, the mission's result
store still holds them, and the grounding verdict is computed from that store
rather than from the conversation.

`usage` is **what the provider said a model call cost**, and it appears in
two forms.

On `tool_call`, `answer` and `reply_rejected` — the three records that follow
a call to the model — it is *that one call*:
`{prompt_tokens, completion_tokens, total_tokens}`, plus verbatim whatever else
that provider's own `usage` object carried (`prompt_tokens_details` with its
cached-token breakdown, say). On `answer` after a grounding repair it is the
repair turn's call, not the draft's: the per-call field is always the cost of
the call that produced the record it rides on.

On `mission_finished` it is the **run's ledger**:
`{prompt_tokens, completion_tokens, total_tokens, calls}`, where `calls` counts
the model calls that *reported* usage rather than the calls that were made. On
`--swarm` that is one number for the whole turn — the router, the planner,
every gate, the synthesizer and every sub-mission's own steps — and not the
last sub-mission's.

**It is absent, never zero, when the provider reported nothing.** Local
endpoints frequently report nothing, and three zeros would be a claim about a
call rather than the absence of one. Read it with a default and do not treat a
missing field as free. Nothing in it is estimated: the harness's other token
number is a characters-over-four estimate used to keep a prompt inside a
context window, and it deliberately never reaches this stream.

`cost` — `{amount, currency}` — appears inside the `mission_finished` form only
when the deployment configured a price for the provider and model that ran, in
a `pricing:` block of `.judais-lobi.yml`:

```yaml
pricing:
  openai:
    gpt-4o-mini: {prompt_per_1k: 0.15, completion_per_1k: 0.6}
    "*":         {prompt_per_1k: 1.0,  completion_per_1k: 2.0, currency: USD}
```

This repo ships no price list and must not: prices move, they differ per
account, and a framework that quoted one would be quoting a figure it cannot
know. Absent is the normal case, and a `local` endpoint has no cost unless
somebody priced it.

A **field and not an event**, which was a decision rather than an oversight. A
ledger is exactly the kind of thing that wants a record type of its own, and a
new record type is the one additive change a consumer cannot absorb quietly:
TAIPAN's `bridge.READS` is asserted *equal* to `contract.EVENTS`, so a tenth
event is a lockstep release on both sides for a number that fits in frames that
already exist. An optional field is read with a default by a consumer that
wants it and ignored by one that does not — the same route `compacted` and
`plan` took.

`elapsed_s` is wall-clock seconds from the mission's first record to its
`mission_finished`, on the harness's own clock — the one `--mission-seconds`
runs against. It is on every `mission_finished` this harness emits, direct and
staged alike, and it is deliberately **not** inside `usage`: `usage` is absent
when the provider reported nothing, and elapsed time is known regardless. Print
it beside `usage.total_tokens`; read both with a default.

Six of these carry more meaning than their names suggest:

- **`tool_call` is emitted before the call is made.** That is what lets a
  watcher show what is about to happen rather than only what happened.
- **`tool_result.output` is the whole result**, not the bounded rendering the
  model was shown. The bound exists because a *model's* context is finite.
- **`gate_requested` is terminal**, and `arguments` travels verbatim. The
  mission stops holding the exact call it proposed, because what a person
  approves has to be the bytes that would run. It carries `approval_id`
  whenever the deployment keeps durable approval records, which it does
  unless `JUDAIS_LOBI_APPROVALS` says otherwise.
- **`grounding` is emitted twice when a repair happens**, on `--swarm` as on
  the direct path. The interim record has `repairing: true` and is work in
  progress — show it, do not latch it. The record with `repairing: false` is
  the verdict. `grounded` says nothing unsupported was found; `verified` says
  something was found to check at all, and a consumer reading only the first
  cannot tell a well-cited answer from one that cited nothing.
- **`step_started` carries the plan on a staged mission**, on the first step of
  each plan drawn. It is the first thing a watcher hears after the planner has
  finished, because the record that opens the stream is written before the
  planner is asked.
- **`mission_finished` says which budget ran out.** `budget` —
  `{which, limit, spent}` — is present **exactly when** `outcome` is
  `budget_exhausted`, and absent on every other outcome, so a consumer may
  branch on the outcome and index the field. `which` is one of `steps`,
  `seconds`, `bytes`, `tokens`; `spent` is not always equal to `limit`, because
  a wall clock is noticed a little after it runs out and reporting the limit as
  the spend would hide by how much. `bytes` and `tokens` are declared and not
  yet emitted by anything: the vocabulary is closed now so that the day
  something spends them, it fills in a field you were already told to expect.
  `reason` is present when the outcome word does not say why — today, only
  `"cancelled"` beside `incomplete`.

`approval_id` names the durable record this request was written to:
`.judais-lobi/approvals/<id>.json` under the harness's working directory by
default, moved or silenced by `JUDAIS_LOBI_APPROVALS`. A gate is answered from
**outside** the run that asked — a different process, sometimes a different
day, always after this one has exited — so the request needs a name that
outlives the process, and this is it. Show it beside the proposed call; carry
it back on the turn that resumes, as `--approval <id>`.

The decision is not made on this stream and is not made by this harness.
Nothing times out into a yes; the record is answered once, by somebody who is
named on it, through the library (`core.runtime.approvals.ApprovalStore.decide`)
or the operator command `judais --mission --approve <id> --decided-by <who>`.
An approved, unspent record then widens exactly one run's gated set by exactly
one tool, and it is spent at the moment that tool is dispatched. **A consumer
sees the widening as that tool's absence from `mission_started.gated`** — there
is no second field announcing it, because the gated list already is the
statement of what this run will not call.

`approval_id` is absent, not `null`, when nothing was written: either an
explicit opt-out, or a directory the harness could not write — and the second
says so in `reason`, because a request with no record is one nobody can ever
answer.

`grounding` is absent altogether when no grounding grammar was configured. An
absent report and a clean one are different facts.

## Outcomes

Carried by `mission_finished`, and by `answer` when there is one.

- `answered` — an answer, and nothing unsupported in it.
- `answered_with_caveat` — an answer that says in its own text what it could not
  support. The caveat is already appended to `answer.text`.
- `awaiting_approval` — the mission reached a gated tool. Nothing was called and
  nothing further happens until a person decides.
- `budget_exhausted` — the run hit a hard bound. Never "the model gave up".
  **Which** bound is on the record, as `budget` — `{which, limit, spent}`, with
  `which` one of `steps`, `seconds`, `bytes`, `tokens` — and reading the word
  without it is reading half a sentence: a mission out of `steps` needs a
  narrower question, a mission out of `seconds` needs a faster endpoint, and
  the word alone does not say which you have.
- `incomplete` — the transcript's default, and therefore the word a mission ends
  on when it ended by raising. `mission_finished` comes out of a `finally`, so a
  crash still closes the stream; the reason is on stderr.

  It is also the word a **cancelled** run ends on — a caller threw the switch,
  or the process was sent `SIGTERM` — and there the reason is on the record
  rather than on stderr, as `reason: "cancelled"`. Cancellation is a field and
  not a sixth word here on purpose: this list is the closed set a consumer
  asserts it knows, widening it is a cost every consumer pays, and a cancelled
  run really is a run that stopped without an answer. A consumer that ignores
  `reason` renders it exactly as it rendered one before the field existed.

## Command line

The mission-mode flags. The rest of the CLI is a person's surface and may move.

- `--mission` — run as a mission rather than a chat turn.
- `--mcp-url` — the tool plane.
- `--mission-steps` — the tool-turn budget; arrives back as `max_steps`.
- `--mission-seconds` — the wall-clock budget for the whole run. Unset is
  **unbounded**. Checked between steps and before each model call, and shared by
  every stage of a `--swarm` turn; a call already in flight is not interrupted,
  so the real bound is this plus one round trip. Running out arrives back as
  `budget_exhausted` with `budget.which == "seconds"`.
- `--provider` — which backend.
- `--model` — which model on it.
- `--profile` — the capability profile: deny-by-default `safe`, then `dev`, `ops`, `god`. Arrives back as `profile`.
- `--unsandboxed` — run tool subprocesses with no isolation. Without it, `bwrap` wherever bubblewrap exists. Arrives back as `sandbox`.
- `--skill` — the skill manifest: tool subset, prompt, grounding grammar.
- `--swarm` — triage first, then stage the mission if it needs staging.
- `--events` — where the NDJSON goes. See above.
- `--history` — prior turns, seeded as chat messages ahead of the objective.
- `--gate-tool` — offer a tool and refuse to call it. Repeatable.
- `--approval` — an approval id somebody has already decided. Lifts that one tool out of the gated set, for this run only, and is spent when the tool is dispatched. A pending, refused, spent or abandoned record is refused at the door, naming the state.
- `--temperature` — sampling, when it must be stated rather than the server's.
- `--top-p` — likewise.
- `--seed` — likewise, for a run somebody intends to reproduce.
- `--resume` — carry on a recorded mission by its `run_id`. The objective comes off that run, so the positional message may be omitted; a different one is refused. A finished run is refused, except one that ended `awaiting_approval`.
- `--protocol` — `json` (the default) or `native`. Arrives back as `protocol` on `mission_started`, and only when it is `native`. Refused at the door on a backend that does not declare `supports_tool_calls` and `supports_tool_choice_required`, because a run that asked for the constrained decoder and silently got prose would be measured as the protocol it was not running. On `--resume` it comes off the recorded run; stating one that disagrees with the record is refused, naming both.

## Environment

- `MCP_TOKEN` — the tool plane's credential.
- `MCP_CLIENT_NAME` — the name this client is announced under.
- `MCP_URL` — the environment form of `--mcp-url`.
- `MCP_STDIO` — the environment form of `--mcp-stdio`, as a command line.
- `ELF_PERSONALITY` — a persona file, on any entry point.
- `TAI_PERSONALITY` — the same, on any entry point, and it wins over `ELF_PERSONALITY`.
- `LOCAL_API_BASE` — where the local backend answers.
- `LOCAL_MODEL` — which model it is serving.
- `MISSION_SKILL` — the environment form of `--skill`.
- `MISSION_SWARM` — the environment form of `--swarm`.
- `MISSION_EVENTS` — the environment form of `--events`.
- `MISSION_HISTORY` — the environment form of `--history`.
- `MISSION_SECONDS` — the environment form of `--mission-seconds`; the flag wins. Unset, blank, unparseable or ≤ 0 all mean unbounded, because a mistyped budget that killed the run before its first step would look like a broken harness.
- `MISSION_RESUME` — the environment form of `--resume`.
- `MISSION_PROTOCOL` — the environment form of `--protocol`; the flag wins. Unset and blank both mean `json`, which is what every mission ran under until now.
- `JUDAIS_LOBI_PROFILE` — the environment form of `--profile`; the flag wins.
- `JUDAIS_LOBI_SANDBOX` — `none` is the environment form of `--unsandboxed`; `bwrap` forces it and refuses on a host without it. The flag wins.
- `JUDAIS_LOBI_AUDIT` — a path moves the audit file; `none`/`off` silences it. Either way `audit_ref` on `mission_started` says which.
- `JUDAIS_LOBI_RUNS` — a path moves the durable run directories; `none`/`off` keeps none at all. Either way `run_id` on `mission_started` is present exactly when there is a transcript to name.
- `JUDAIS_LOBI_APPROVALS` — a path moves the durable approval records; `none`/`off` keeps none, and then a gate carries no `approval_id`.
- `MISSION_APPROVAL` — the environment form of `--approval`; the flag wins.

The flags that *answer* a gate — `--approve`, `--refuse`, `--decided-by`,
`--note` — are deliberately **not** in the list above. They are an operator's
command and not a spawning surface: a platform that integrates these approvals
calls `core.runtime.approvals.ApprovalStore.decide` from its own process, where
it knows who the person is. Core enforces only that somebody is named.

## The exit contract

- **stdout is prose for a person.** Panels, emoji, the transcript printed after
  the fact. Do not parse it. It changes whenever somebody improves the console
  rendering, which is often.
- **The event sink is the only machine channel.** A consumer uses `fd:` or a
  path, never `-`, so that the rendering and the records never share bytes.
- **Zero events is a failure.** `mission_started` is emitted before the model is
  asked and before the tool plane is touched — before the *first* call, which
  under `--swarm` is the router's and not the first step's — so an empty stream
  means the harness never got that far: a cold model server, a refused token, an
  unreachable endpoint. It is never an empty answer. Report it as a failure
  rather than rendering a blank reply.
- **`mission_finished` always arrives.** It is emitted from a `finally`, so a
  mission killed by an exception still closes its own stream. A stream that
  simply stops is indistinguishable from an agent that is thinking.
- **SIGTERM asks a run to wind up, and it gets to.** The first signal throws the
  mission's cancellation: the loop stops at its next step, keeps its transcript,
  and writes its own `mission_finished` — `incomplete` with
  `reason: "cancelled"` — and only then is the sink flushed and closed. So a
  stopped turn closes its stream with the record that says it is over, rather
  than with the record before it. The default disposition is then restored and
  the signal re-raised, so the exit status is still the signal's rather than a
  spurious clean exit. A **second** SIGTERM does not wait: it flushes, closes and
  dies, so a run stuck in a model call or a subprocess can still be stopped.
- **stderr carries the diagnostic**, and its tail is what to show when a mission
  produced no events or stopped without an answer. It is a traceback, and it is
  **scrubbed before it is written** — home directories, this host's name,
  credentials held in the harness's environment and absolute frame paths become
  `<home>`, `<host>`, `<cwd>`, `<site-packages>`, `<stdlib>` and
  `<redacted:NAME>`. You may show it to somebody who is not an operator. It is
  still prose for a person, never a machine channel.
- **Free text on the stream is scrubbed by the same redactor.** `error`,
  `problem`, `reason`, `text`, `caveat`, `detail` and `unsupported` pass through
  `core.redact` at the emitter. `output`, `arguments`, `objective`, `catalogue`,
  `gated`, `tool`, `handle`, `outcome` and `plan` do **not**: they are the
  evidence, the call and the request, and the mission store holds the same bytes
  as `output`. A pane that diffed the two would find them equal, which is the
  point.

## Compatibility

`SCHEMA_VERSION` is carried on every `mission_started`.

- Adding an event, or adding an optional field to an existing event, is a
  **minor** change and does not bump it. That is safe because consumers drop
  record types they do not know.
- Renaming a field, removing one, moving one out of the required set, or
  changing what an existing required field means is a **breaking** change and
  **bumps** it.

## How to pin

```python
from core.runtime import contract

assert contract.SCHEMA_VERSION == 1        # fails at import, which is cheap

for line in stream:
    record = json.loads(line)
    problems = contract.conforms(record)   # [] when the record is fine
    if problems:
        log.warning("harness contract: %s", "; ".join(problems))
    if record["event"] not in MY_EVENTS:
        continue                           # unknown types are dropped
```

`conforms` is pure and standard-library only. It checks that the record names a
declared event, that every required field for that event is present, and that
any `schema_version` it carries is one this contract understands. It does not
check types and does not object to extra keys — an added optional field is a
minor change, and a checker that failed on one would make every additive release
a breaking one.
