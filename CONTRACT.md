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

Optional, and therefore to be read with a default: `audit_ref` and `run_id` on
`mission_started`, `plan` on `step_started`
(`[{id, goal, rung}]`, on the first step of a staged `--swarm` plan and again
on the first step of a redrawn one), `tool` on `reply_rejected` (present
only when the model got as far as naming one), `compacted` and `resumed` on
`step_started`, and `sandbox` and `profile` on `mission_started`. `plan` rode
`mission_started` until 0.8.x: that record is now emitted before triage —
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
tokens_after, limit_tokens, profile}` and is present only on the steps where
older tool round-trips had to be dropped from the conversation to keep it
inside the model's context window. The persona, the tool catalogue, the seeded
history turns, the objective and the newest round trip are never dropped. The
counts describe that one step, not a running total.

It is on the stream because the alternative is the failure it prevents: an
agent whose earlier evidence quietly left its prompt looks, from outside,
exactly like an agent that had it all along. Nothing is lost to the run —
`tool_result` already carried the whole of every result, the mission's result
store still holds them, and the grounding verdict is computed from that store
rather than from the conversation.

Five of these carry more meaning than their names suggest:

- **`tool_call` is emitted before the call is made.** That is what lets a
  watcher show what is about to happen rather than only what happened.
- **`tool_result.output` is the whole result**, not the bounded rendering the
  model was shown. The bound exists because a *model's* context is finite.
- **`gate_requested` is terminal**, and `arguments` travels verbatim. The
  mission stops holding the exact call it proposed, because what a person
  approves has to be the bytes that would run.
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

`grounding` is absent altogether when no grounding grammar was configured. An
absent report and a clean one are different facts.

## Outcomes

Carried by `mission_finished`, and by `answer` when there is one.

- `answered` — an answer, and nothing unsupported in it.
- `answered_with_caveat` — an answer that says in its own text what it could not
  support. The caveat is already appended to `answer.text`.
- `awaiting_approval` — the mission reached a gated tool. Nothing was called and
  nothing further happens until a person decides.
- `budget_exhausted` — `max_steps` tool turns spent without reaching an answer.
  Read it against `max_steps`, never alone.
- `incomplete` — the transcript's default, and therefore the word a mission ends
  on when it ended by raising. `mission_finished` comes out of a `finally`, so a
  crash still closes the stream; the reason is on stderr.

## Command line

The mission-mode flags. The rest of the CLI is a person's surface and may move.

- `--mission` — run as a mission rather than a chat turn.
- `--mcp-url` — the tool plane.
- `--mission-steps` — the tool-turn budget; arrives back as `max_steps`.
- `--provider` — which backend.
- `--model` — which model on it.
- `--profile` — the capability profile: deny-by-default `safe`, then `dev`, `ops`, `god`. Arrives back as `profile`.
- `--unsandboxed` — run tool subprocesses with no isolation. Without it, `bwrap` wherever bubblewrap exists. Arrives back as `sandbox`.
- `--skill` — the skill manifest: tool subset, prompt, grounding grammar.
- `--swarm` — triage first, then stage the mission if it needs staging.
- `--events` — where the NDJSON goes. See above.
- `--history` — prior turns, seeded as chat messages ahead of the objective.
- `--gate-tool` — offer a tool and refuse to call it. Repeatable.
- `--temperature` — sampling, when it must be stated rather than the server's.
- `--top-p` — likewise.
- `--seed` — likewise, for a run somebody intends to reproduce.
- `--resume` — carry on a recorded mission by its `run_id`. The objective comes off that run, so the positional message may be omitted; a different one is refused. A finished run is refused, except one that ended `awaiting_approval`.

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
- `MISSION_RESUME` — the environment form of `--resume`.
- `JUDAIS_LOBI_PROFILE` — the environment form of `--profile`; the flag wins.
- `JUDAIS_LOBI_SANDBOX` — `none` is the environment form of `--unsandboxed`; `bwrap` forces it and refuses on a host without it. The flag wins.
- `JUDAIS_LOBI_AUDIT` — a path moves the audit file; `none`/`off` silences it. Either way `audit_ref` on `mission_started` says which.
- `JUDAIS_LOBI_RUNS` — a path moves the durable run directories; `none`/`off` keeps none at all. Either way `run_id` on `mission_started` is present exactly when there is a transcript to name.

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
- **SIGTERM is honoured.** The sink is flushed and closed, then the default
  disposition is restored and the signal re-raised — so what was already written
  survives, and the exit status is still the signal's rather than a spurious
  clean exit.
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
