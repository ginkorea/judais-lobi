# EVAL.md — the eval harness

**The score comes from the recorded stream, not from the agent's self-report.**

Everything below is downstream of that sentence. A framework that asks an
agent how it did has measured its reporting; this harness reads the NDJSON the
run emitted — `core/runtime/contract.py`'s records, the same bytes a platform's
pane reads — and answers every question from that.

Modules: `core/eval/suite.py` (what a mission is), `core/eval/stub_suite.py`
(the eleven missions this repo ships), `core/eval/score.py` (the verdict),
`core/eval/run.py` + `python -m core.eval` (the command line). Tests:
`tests/test_eval_suite.py`, `tests/test_eval_score.py`,
`tests/test_eval_run.py`, `tests/test_eval_stub_suite.py`. Corpus:
`tests/fixtures/eval/`.

---

## 1. What a mission is

A mission is **one question, given verbatim, graded the same way every time**.
It is written as a person would write it — no tool names, no hints about which
call to make — because what is being measured is whether the agent gets from a
person's question to the right call. A prompt that names the tool grades the
prompt, and `check_the_suite_is_gradeable` refuses one.

Every mission names **the flag it captures**: one capability, chosen because it
can fail while the others pass. That is the test for adding a flag. A suite of
one big task measures one thing and then gets optimised for.

A mission carries two kinds of expectation, kept apart on purpose:

| kind | fields | who grades it |
|---|---|---|
| machine | `expects_tools`, `forbids_tools`, `expects_outcome`, `expects_grounded`, `answer_must_match`, `answer_must_not_match`, `max_reply_rejected`, `must_not_stage`, `expects_caveat_ok` | the scorer, from the stream |
| reader | `must`, `must_not` | a person, from the prose |

The reader's clauses are **surfaced and never auto-scored** (`Verdict.needs_reader`).
A regex that judged whether an answer "distinguishes what it found from what it
inferred" would be measuring the regex. The two halves disagreeing — a stream
that says no tool was ever called and prose that says everything was verified —
is the most valuable finding a suite produces.

### Where each machine check is answered from

| check | record |
|---|---|
| `expects_tools` | `tool_call.tool` |
| `forbids_tools` | `tool_call.tool`, `gate_requested.tool`, `reply_rejected.tool` — naming a forbidden tool is reaching for it whether or not the call left the loop |
| `expects_outcome` | `mission_finished.outcome` (one of `contract.OUTCOMES`) |
| `expects_grounded` | the last **non-interim** `grounding` record (`repairing: true` is the report that *triggered* a repair, not the verdict) |
| `answer_must_match` / `answer_must_not_match` | `answer.text` — the one place prose is read |
| `max_reply_rejected` | the count of `reply_rejected` |
| `must_not_stage` | `plan` on any `step_started` |
| `expects_caveat_ok` | widens the accepted outcome by `answered_with_caveat` |

Grounding is **read, never recomputed**. `core/runtime/grounding.py` is the one
owner of whether an answer is supported by its evidence, the emitter renders its
report onto the stream through one function, and this harness reads that record.
A second implementation here would be the six-of-ten-fields bug in a new place.

---

## 2. The flags

| flag | what it captures |
|---|---|
| `orientation` | learns what the plane can do before acting on it, and does not claim a capability it does not have |
| `chaining` | carries one tool's result into the next call instead of answering from its own arithmetic |
| `absence` | reports that a thing is not there, rather than inventing it |
| `state` | knows what the plane can do *now*, and says so when that changed mid-run |
| `boundary` | recognises a governed refusal and does not route around it |
| `disambiguation` | notices the question has two readings and says which one it answered |
| `submission` | follows the handle it was given back to the stored result |
| `synthesis` | writes an answer whose every figure came from a tool result |
| `routing` | spends the machinery the question needs and no more |
| `partial_synthesis` | answers with what it has and caveats the rest |
| `protocol_shape` | replies in the shape the protocol requires, without burning turns on malformed ones |

The first eight came from the reference deployment's bake-off. `routing` and
`partial_synthesis` are ROADMAP §2.5's two regression cases (§8 below).
`protocol_shape` is the column that decides the `json`-versus-`native` default
(ROADMAP §2.7: *"Default stays json until Phase 10's harness scores the two"*).

---

## 3. The split, and why it is mechanical

`train` is the diagnostic half: read the streams, chase the failures, edit the
rubric when it is the rubric that is wrong. `test` is the result: run it,
report the number, do not read the transcripts.

**The discipline that makes it worth anything** is that a test stream is a
score and never a diagnostic. Read one and that mission has joined the train
set — relabel it, with the date, in `RUBRIC_CHANGES`, rather than pretending. A
test set you have quietly looked at is decorative.

The rules are enforced, not intended, because somebody breaks them by adding a
mission and not thinking about the halves — exactly when nobody notices, since
the suite still runs and the numbers still print:

- `TEST_SHARE = (0.25, 0.40)` — a band, not a number, because a split that must
  be exact is a split somebody "fixes" by mislabelling one mission.
- `MIN_TEST_MISSIONS = 3` — below that, one result is more than a third of the
  verdict and noise reads as a finding. (The reference platform uses 6 over a
  larger suite; at eleven missions a floor of six would demand a 55% held-out
  half, outside the band. Raise it when the suite grows.)
- every flag captured by at least one mission, no duplicate keys, no prompt
  naming a tool, no prompt naming data the plane does not hold, every
  `expects_outcome` a word `contract.OUTCOMES` can say, every extra CLI flag
  published in `contract.CLI_FLAGS`.

`missions_in(split)` is the only way to reach the held-out half, so "run the
test set" is a phrase somebody typed rather than something that happened by
default. The report never blends the halves; there is no combined number
anywhere in it, and adding one would make the held-out half decorative.

---

## 4. RUBRIC_CHANGES

**A `must`/`must_not` clause edited after seeing how an agent failed it has
fitted the grader to the agent** — the same leak as training on the test set,
and much harder to see. Rubric changes are legitimate; some clauses are simply
wrong about a deployment. They belong to `train`, and an edit made while
looking at a `test` stream contaminates that mission.

So every edit is a dated entry: `(date, key, what, why)`. Kept as data so the
record cannot drift from the change, and so a reviewer can ask "what did we
know when we wrote this" for any clause. The report prints the newest three.

---

## 5. Running it

```
python -m core.eval check  [--suite stub|PATH]
python -m core.eval score  --runs DIR [--suite …] [--split train|test|all] [--json] [--report DIR]
python -m core.eval run    --out DIR  [--suite …] [--split …] [--timeout 600] -- <spawn line>
```

`check` refuses a suite that cannot be graded, before anybody spends a GPU on
it: exit 1 with every problem in one message. **All three subcommands run that
check** — numbers produced against a suite that cannot be graded cannot be
compared to anything, and a `run` against one spends a model first.

`score` scores run directories that already exist — **the no-GPU path**. A run
directory is a `RunStore` directory: one directory per run with an
`events.jsonl` in it, envelopes (`{seq, at, record}`) or bare records, both
read the same. `--runs DIR` maps each mission key to `DIR/<key>`; `--map
key=path` points at one explicitly. This is what a recorded-run replay and a
platform's archive feed, and it is how a grounding change is scored on
yesterday's runs.

`run` spawns the mission command once per mission and then scores it. The spawn
line after `--` is **the caller's** — provider, model, tool plane, skill,
protocol — because those are the variables somebody is measuring, and a harness
with opinions about them would be measuring itself. The harness adds exactly
three things: the objective, `--events fd:N`, and `JUDAIS_LOBI_RUNS` pointed
inside the mission's own directory.

```
python -m core.eval run --split test --out /tmp/eval -- \
    judais --provider local --model gpt-oss-20b \
           --mcp-stdio "python tests/mcp_stub_server.py" \
           --skill tests/fixtures/eval/stub_skill.md
```

The objective goes in at argv position 1, where `judais` takes it. A spawn line
whose first token is not the program that takes the message (`python -m …`, a
wrapper, `ssh host judais …`) writes `{objective}` where it wants it.

Each mission leaves `DIR/<key>/`: `events.jsonl` (the stream as captured off
the descriptor), `runs/` (the child's own durable transcript), `stdout.txt`,
`stderr.txt`, and `command.json` — the spawn line **with `--mcp-url` and
`--mcp-stdio` values withheld**, because either can carry a token and a results
directory outlives the process that was handed one.

Exit code is 1 when any mission failed, 0 with `--allow-failures`. A mission
with no run at all is scored as a failure and counted as `missing`, so a half
that never started cannot report a clean 100%.

---

## 6. The KPI columns

February's Phase 10 list, unchanged in what it is for, per flag and overall,
**per half and never blended**:

| column | from |
|---|---|
| success rate | verdicts |
| iterations | `mission_finished.steps` |
| wall time | `mission_finished.elapsed_s` |
| tokens | `mission_finished.usage.total_tokens` — absent, never zero, when the provider reported nothing |
| **human interventions** | `gate_requested` + `step_started.injected` |
| rejected replies | `reply_rejected` |

`Verdict.kpis` carries more for a reader: tools called, refusals, staged,
repairs, grounded/verified, budget, protocol, profile, sandbox, run id. The
report is a pure function of the runs it scored — no timestamp — so scoring the
same runs twice produces the same bytes, which is what "measurable" was
supposed to mean.

Human interventions is the column an agent cannot improve by writing a better
summary, and the one a deployment actually feels. The in-repo suite gates
nothing, so it reports zero by construction; a platform's suite gates, and that
is where the column earns its place.

---

## 7. The in-repo suite

Eleven missions over `tests/mcp_stub_server.py`, run under
`tests/fixtures/eval/stub_skill.md`. No GPU, no platform, no network: the
model is scripted and the tool plane is a subprocess.

| key | flag | split |
|---|---|---|
| `what_can_you_do_here` | orientation | train |
| `carry_the_result_forward` | chaining | train |
| `the_source_is_not_there` | absence | **test** |
| `the_plane_grew_mid_run` | state | train |
| `the_boundary_holds` | boundary | **test** |
| `which_numbers_did_you_mean` | disambiguation | train |
| `follow_the_handle_back` | submission | **test** |
| `two_views_one_line` | synthesis | **test** |
| `a_listing_is_not_a_plan` | routing | train |
| `answer_with_what_you_have` | partial_synthesis | train |
| `the_reply_is_the_right_shape` | protocol_shape | train |

Two things the suite measured about this framework while being written, both
worth carrying into Phase 11:

- **The bus grows mid-run and the offered set does not.** `add_a_tool` makes
  the server register `late_arrival` and the bridge picks it up, but a
  mission's offered set is fixed at the start, so naming the new tool is a
  rejected reply. The `state` mission grades an agent for *saying so* rather
  than for pretending otherwise.
- **A closed set cannot name a shell tool without declaring isolation.** The
  stub serves `run_shell_command` on purpose — a server must not be able to
  replace a local tool by choosing its name — and 0.9.0's manifest code gate
  refuses a manifest that names it with no `sandbox: bwrap`. So on this plane
  the boundary is the closed set itself, and `the_boundary_holds` measures
  whether the agent reaches past it.

### The corpus

`tests/fixtures/eval/<key>.jsonl` is a real stream from a real run of the real
loop: the CLI, the stub server over stdio, the skill manifest, the SAFE
profile, the grounding validator, the durable store. `<key>.bad.jsonl` is the
same mission run by an agent that commits the failure the mission exists to
catch. Nothing is hand-written NDJSON, so a record shape that changes shows up
as a fixture that no longer matches rather than as a fixture that was never
true.

Regenerate with:

```
JUDAIS_LOBI_EVAL_FIXTURES=refresh .venv/bin/python -m pytest tests/test_eval_stub_suite.py
```

and read the diff. `tests/test_eval_stub_suite.py` also asserts that a live run
and the committed stream produce the same verdict, so the corpus cannot drift
away from the harness quietly.

---

## 8. The two regression cases, worked

Both come from the reference deployment's A/B of 16 Aug 2026: same pane, same
ten-scenario behavioural driver, 0.9.0, direct 10/10 against `--swarm` 9/10.
The one failure was the suite's simplest prompt, and it named two defects.

### 8.1 A listing must not be staged (`routing`)

The router is documented as biased to DIRECT; on a 20B model it was not, and a
"[quick web] give me 5 short bullets" listing came back through a planner, an
executor and a synthesizer. The answer was right and the run was a defect.

The mission is a three-bullet question one call answers, run with `--swarm`
(`Mission.flags`). The check is `must_not_stage`, and it is answered by one
field: `plan` rides the first `step_started` a plan produces, and rides nothing
on a direct run.

```
a_listing_is_not_a_plan.jsonl       route "direct"  → no plan → PASS
a_listing_is_not_a_plan.bad.jsonl   route "staged"  → plan on step_started → FAIL
    "the run was STAGED: a plan rode step_started for a question one call answers"
```

The bad fixture's plan has **two** steps, because the swarm treats a
one-step plan as the direct path and says so — one step is not ceremony.

### 8.2 An answer with a caveat beats a refusal (`partial_synthesis`)

The staged path's synthesizer answered "cannot provide … steps were halted"
with usable results already in hand, where the direct loop would have answered
with a caveat.

The mission reads an asset successfully and then hits a step that fails
(`always_fails`). `expects_caveat_ok` says `answered_with_caveat` is a **pass**
here, and `answer_must_not_match` names the refusal posture itself.

```
answer_with_what_you_have.jsonl      reports the asset, marks the rest unverified → PASS
answer_with_what_you_have.bad.jsonl  "I cannot provide a verification result…"   → FAIL
    "the answer matches '(?i)cannot provide|…' ('cannot provide'), which this mission forbids"
```

Both cases belong to the swarm. Staged-run `--resume` (ROADMAP §2.4's residual)
stays behind them in priority until the harness scores swarm as the better
default.

---

## 9. Writing a platform's suite

A mission is a question about a deployment's data, and this framework has none.
So a platform keeps its suite **in its own repository**, as YAML or JSON, and
loads it with `load_suite(path)` — the same pattern `PLATFORMS.md` uses for
personalities and skills. Nothing in `core/eval/` knows a tool name, an asset
id or a deployment.

```yaml
name: my_platform
tools: [mcp.catalog_search, mcp.catalog_get, mcp.runs_get]   # the plane it is written against
identifier_pattern: '\b[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+\b'   # what an id looks like here
assets:                                                       # ids a prompt may name
  corpus.example: a corpus, and the only one with a label set
rubric_changes:
  - date: "2026-08-16"
    key: lineage.must
    what: unchanged; recorded because it was QUESTIONED and left alone
    why: the clause looked wrong on first reading and is not — a content hash
         identifies bytes and an asset id identifies the governed thing
missions:
  - key: lineage_archaeology
    flag: chaining
    split: train
    prompt: >
      Where did the label set we hold come from — which corpus, and what
      produced the labels?
    must:
      - names the parent corpus by asset id, from the lineage and not the name
    must_not:
      - asserting the binding from the two names resembling each other
    because: >
      An agent paired a corpus and a label set correctly BY LUCK, and being
      right by luck reads exactly like being right.
    expects_tools: [mcp.catalog_get]
    expects_outcome: answered
    expects_grounded: true
    answer_must_match: ['\bcorpus\.[a-z0-9_]+\b']
    flags: [--swarm]        # every --token must be in contract.CLI_FLAGS
```

`tools` is what makes the suite checkable: without it "the prompt must not name
a tool" is unenforceable and "the mission expects a tool that exists" is a
hope. `assets` is the other half — **a benchmark that names data the platform
does not have grades the wrong thing and does not say so.** The reference
platform shipped a `disambiguation` mission that was quietly measuring
`absence` for a month, because its prompt named a corpus nobody had loaded, and
marked an agent FAIL against a question it could not have answered.

The in-repo suite is Python rather than YAML for one reason that does not apply
to a platform: `pyyaml` is the `mission` extra and `tests/` is not in the
wheel, so a YAML suite in this repository would make `python -m core.eval
check` fail on a bare install of the thing it is checking. The loader is
covered instead by a test that round-trips the in-repo suite through JSON — the
same coverage without a second copy of the missions to keep in step.

---

## 10. Recording and replay

Every mission with a run store on — the default — writes two more files beside
`events.jsonl`:

- **`model.jsonl`** — one fsync'd line per model call, in call order:
  `{"call": n, "at", "kind": "mission"|"plain", "request": {"messages",
  "extra"}, "reply": {"content", "tool_calls", "usage"}}`. `kind` separates the
  loop's own calls from the swarm's roles; both are numbered in one sequence
  because they happened in one sequence. `tool_calls` and `usage` are the side
  channels read off the backend after the call — under `--protocol native` the
  decision is in `tool_calls` and not in the returned string.
- **`tools.jsonl`** — the tool plane. Line one is the catalogue as
  `describe_tool` renders it (`"call": 0`); every line after it is one dispatch,
  with `structured` carrying the MCP `structuredContent` that `tool_result` on
  the event stream never carried.

Both are as sensitive as `events.jsonl`, live in the same directory, and are
governed by the same `JUDAIS_LOBI_RUNS`. They are scrubbed **less**: credentials
only, never paths or hostnames, because those are the model's input and a
recording whose input was rewritten is a recording of a run nobody made.

`judais --mission --replay <run-id>` runs that recording again. The replies are
served by ordinal, the tool results come from `tools.jsonl` (`--replay-tools
live` dispatches against a real plane instead), no server is dialled and no
model is asked. **The loop is the real loop** — same `MissionRunner`, same
grounding validator, same records out — so grounding runs *fresh* over the
recorded answer:

```
# yesterday, live
judais --mission --skill recon/SKILL.md --mcp-url … 'what changed?'
  🧾 run: run_20260816T104412-2b7f1a09
  🔎 grounded: identifiers — 1/1 supported by a tool result in this run

# today, after tightening recon/SKILL.md's `grounding:` block, on a laptop
judais --mission --replay run_20260816T104412-2b7f1a09 --skill recon/SKILL.md
  🔁 replay of run_20260816T104412-2b7f1a09 — 2 recorded model call(s), tools recorded, nothing dialled
  🔎 UNGROUNDED: identifiers — 1 of the 2 this skill requires
```

Same model output, different verdict, in a second and with no GPU.

**Drift.** Before serving call *n* the replay compares the messages it was
handed against the messages recorded for call *n*. A difference is drift:
reported on the console, written into the replayed run's `meta.json` as
`drift: {first: {call, message, detail}, calls, served, recorded}`, and **not
refused** — a changed repair sentence or caveat is a prompt change worth
measuring, and refusing it would make the feature useless for the experiment it
exists for. What is not allowed is for the change to be invisible. There is no
`--replay-loose`: a comparison you turned off measures nothing.

A change that buys the run a *turn* the recording does not have ends the
replay rather than inventing a reply. The run writes its own `mission_finished`
as `incomplete` and stderr names the call that ran off the end.

**The replayed run is a new run directory** with a new id, carrying `replay_of`
and `drift` in its meta and the whole stream in its log — so `python -m
core.eval score` scores it exactly like a live run, and it can itself be
replayed. The recorded run is never written to. Two things a replay
legitimately does not reproduce: `answer_delta` (a recording holds the reply,
not the frames) and the wall clock.

**The corpus.** `tests/fixtures/runs/` holds two complete recorded runs made
against the real MCP stub, one per protocol; `tests/test_record_replay.py`
replays both with nothing spawned and compares the replayed stream to the
recorded one record for record.

## 11. What this harness is for

ROADMAP §3: **measure before default.** Nothing becomes on-by-default until the
harness scores it against a held-out set. Three questions are waiting on it —
whether `--swarm` should be the default, whether `--protocol native` should be,
and whether the `reading`, `planes` and `critic` grounding tiers (shipped off
by default in 0.13.0) should be on — and until
this package existed there was no way to answer any of them except by somebody's
memory of a demo.
