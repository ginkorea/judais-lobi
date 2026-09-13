# EVAL.md — the eval harness

**The score comes from the recorded stream, not from the agent's self-report.**

Everything below is downstream of that sentence. A framework that asks an
agent how it did has measured its reporting; this harness reads the NDJSON the
run emitted — `core/runtime/contract.py`'s records, the same bytes a platform's
pane reads — and answers every question from that.

Modules: `core/eval/suite.py` (what a mission is), `core/eval/stub_suite.py`
(the eleven missions this repo ships), `core/eval/benchmark_suite.py` (twelve
more, chosen so the way they fail is the harness's job — §13),
`core/eval/score.py` (the verdict), `core/eval/run.py` + `python -m core.eval`
(the command line), `core/eval/measure.py` (the matrix — §12),
`core/eval/ablation.py` (the arms — §14). Tests:
`tests/test_eval_suite.py`, `tests/test_eval_score.py`,
`tests/test_eval_run.py`, `tests/test_eval_stub_suite.py`,
`tests/test_eval_benchmark_suite.py`, `tests/test_eval_ablation.py`,
`tests/test_eval_live.py`. Corpus: `tests/fixtures/eval/`.

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
| machine | `expects_tools`, `forbids_tools`, `expects_outcome`, `expects_grounded`, `answer_must_match`, `answer_must_not_match`, `max_reply_rejected`, `must_not_stage`, `expects_caveat_ok`, `expects_carried`, `expects_recovered` | the scorer, from the stream |
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
| `expects_carried` | a literal in a `tool_result`, and then in a **later** `tool_call.arguments` — the call was shaped by the evidence and not by the prompt. A call carrying it with no earlier receipt holding it is reported as *typed, not carried*, which is a different agent from one that never carried it at all |
| `expects_recovered` | a `tool_result` with `ok: false` for a name, and a later one with `ok: true` for the same. A run that never failed is reported as having had nothing to recover from, so a mission whose premise did not hold is not mistaken for an agent that gave up |

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

**A suite says which of these it claims.** `flags:` is an optional top-level
key listing the capabilities a suite measures. Leave it out and the suite
claims all eleven — the in-repo suite does, deliberately, because it is the one
suite that grades the whole harness and a flag added to the table tomorrow
should demand a mission there the same day. The coverage rule is then *every
**claimed** flag captured by at least one mission*, which is what lets a pack
grade one capability without inventing missions to satisfy a checker:
`core/skills/library/analyst/missions.yaml` claims nine and is held to exactly
those nine. Claiming a flag no mission captures is a refusal; so is claiming a
flag this table does not define; and a mission may still only name a flag this
table defines, claimed or not.

> Two different keys are spelled `flags:` in a suite file and they are not
> related. At the **top level** it is the list of capabilities above. Inside a
> **mission** it is the extra CLI flags that mission is spawned with (§9), and
> every one of those must be published in `contract.CLI_FLAGS`.

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
python -m core.eval check    [--suite stub|benchmark|PATH]
python -m core.eval score    (--runs DIR | --map KEY=PATH …) [--suite …] [--split train|test|all] [--json] [--allow-failures] [--report DIR]
python -m core.eval run      --out DIR [--suite …] [--split …] [--json] [--allow-failures] [--timeout 600] -- <spawn line>
python -m core.eval measure  --out DIR [--report PATH] [--config NAME …] [--only KEY …] [--repeat N] [--per-mission-seconds 600] -- <spawn line>
python -m core.eval ablation --out DIR [--report PATH] [--arms A,B] [--only KEY …] [--repeats N] [--per-mission-seconds 600] -- <spawn line>
```

`--suite` takes two in-repo names and otherwise a path. **`stub`** (the
default) is the harness grading itself — one mission per flag, §7.
**`benchmark`** is the harness-sensitive pack — twelve missions in six classes
whose failure modes are a runtime's job, §13, and the suite an `ablation` is
normally pointed at. `--split` defaults to `all` (both halves, reported apart)
and `--timeout` to 600 seconds — the bound on **one** mission, not on the
suite.

`check` refuses a suite that cannot be graded, before anybody spends a GPU on
it: exit 1 with every problem in one message. **Every subcommand runs that
check** — numbers produced against a suite that cannot be graded cannot be
compared to anything, and a `run` against one spends a model first. Where the
suite groups its missions into classes, `check` prints the per-class counts
beside the per-flag one.

`measure` is `run`, once per configuration, plus the table of the
differences — §12. `ablation` is `run`, once per arm, plus the **paired**
difference between arms — §14.

`score` scores run directories that already exist — **the no-GPU path**. A run
directory is a `RunStore` directory: one directory per run with an
`events.jsonl` in it, envelopes (`{seq, at, record}`) or bare records, both
read the same. `--runs DIR` maps each mission key to `DIR/<key>`; `--map
key=path` points at one explicitly, is repeatable, and beats `--runs`. One of
the two is required — `score` with neither exits 2 saying so. This is what a
recorded-run replay and a platform's archive feed, and it is how a grounding
change is scored on yesterday's runs.

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

That manifest has **no `policy:` block**, and its absence is a result rather
than an omission. It used to carry three lines — never invent an id or a
figure, "if a number is not in a view it is not in the answer", a refusal
names the reason and what would unblock it — which were the framework's own
conduct written out by hand. They moved to `core/runtime/prompts.py` and the
suite was re-recorded with every verdict unchanged, which is the evidence
that the framework's text does the work the fixture's did. A platform writing
its own manifest should read the stub the same way: `policy:` is for what is
true of *your* plane and nothing else.

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
closed in 0.14.0 and kept here as the record of what the harness found:

- **The bus grows mid-run and now so does the offered set.** `add_a_tool` makes
  the server register `late_arrival` and the bridge picks it up; since 0.14.0
  the loop reconciles its offered set against the bus after every dispatch, at
  every step boundary and once more before refusing a name, admits what the
  manifest allows, re-renders the catalogue and says so on `step_started.
  catalogue`. The `state` mission grades an agent for *noticing*, and an answer
  that sends the person away to start again fails it.
- **The code gate is about tools that run on THIS host.** The stub serves
  `run_shell_command` on purpose — a server must not be able to replace a local
  tool by choosing its name. The gate is `tool_key` equality: the bare name is
  this process's descriptor and needs `sandbox: bwrap`; `mcp.run_shell_command`
  executes on the server, is in the closed set, and `the_boundary_holds` is
  spawned with `--gate-tool` in front of it — so the boundary is a door with a
  person behind it rather than an absence. A mission may carry more than one
  bad agent (`<key>.invents.jsonl`).

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
flags: [chaining, absence, synthesis]                        # what this suite claims to measure
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

`flags` is what makes a *narrow* suite checkable. Omit it and the suite claims
every capability in §2 and must capture all of them; name a subset and it is
held to that subset, which is how a suite about three capabilities is graded
without two missions written to satisfy a checker. (The `flags:` beside
`expects_grounded` below is the other key of that name: a mission's extra CLI
flags. See the note in §2.)

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
`drift: {first: {call, kind, message, detail}|null, calls, served, recorded}`,
and **not refused** — a changed repair sentence or caveat is a prompt change worth
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
memory of a demo. §12 is where those three are put to a model.

---

## 12. Measuring a release locally

```
python -m core.eval measure --out DIR [--report PATH] [--config NAME …]
                            [--only KEY …] [--repeat N]
                            [--per-mission-seconds 600] -- <spawn line>
```

`run` answers *how did this configuration do*. `measure` answers the question
§11 leaves open, which is a **comparison**: it runs the same suite, against the
same endpoint, over a matrix of configurations, and prints the differences.
Nothing becomes a default off one number.

### The matrix is data

`core/eval/measure.py`'s `MEASUREMENTS` is a tuple of `Measurement` entries —
a name, a sentence saying which question the row is for, and the delta it
applies. Adding a configuration is one entry, and no branch anywhere knows
what `swarm` means.

| row | delta | the question |
|---|---|---|
| `direct` | nothing — every tier off | the baseline every other row is read against |
| `swarm` | `--swarm` | ROADMAP §2.5: should the staged path be the default? |
| `native` | `--protocol native` | ROADMAP §2.7: json or native? |
| `reading` | `grounding: reading: true` (+ `claim_table`) | is the field-misreading tier worth its model calls? |
| `planes` | the manifest's `grounding: planes:` block, kept | is the plane-claim check worth turning on? |
| `critic` | `grounding: critic: true` | is the advisory second opinion worth turning on? |

**How a tier is switched.** The harness writes a **manifest variant** per
configuration, next to that row's runs at `<out>/<name>/skill.md`, and
repoints the caller's `--skill` at it. Every variant starts from the same
place: the caller's manifest with all three tier keys *removed*. That is what
makes `direct` a baseline rather than "whatever the manifest happened to
ship"; each other row restores exactly one. The split and the write go through
`SkillManifest`'s own splitter, so what a manifest looks like still has one
owner.

`reading` and `critic` are **switches**, so the harness writes them (`reading`
also gets the `claim_table: true` it cannot run without). `planes` is a
**table** — which tools are a tool family here, and what an answer says when
it claims one — which is data a deployment owns. So the harness never writes a
`planes:` block; it keeps the one the manifest declares, and a manifest with
none gets the row **skipped with that sentence as the note**. In this
repository the manifest that declares one is
`tests/fixtures/eval/measure_skill.md` — `stub_skill.md` plus a `planes:`
block, and a test holds the two frontmatters identical apart from it.

A row whose endpoint cannot honour it is skipped the same way rather than run:
`native` needs `supports_tool_calls` and `supports_tool_choice_required`, and a
run that quietly fell back to prose would be recorded under `native` as the
protocol it was not running. A mission's own `flags` are never stripped — the
routing mission is spawned `--swarm` in every row, because that is the defect
it exists to catch.

### Pointing it at an endpoint

Everything about the model is **environment and flags**; `core/` names no
model, no host and no vendor. Three worked shapes:

```
# a local vLLM (or llama.cpp / LM Studio / Ollama's /v1 shim)
LOCAL_API_BASE=http://127.0.0.1:8000/v1 \
python -m core.eval measure --out /tmp/m --report /tmp/m/measure.md -- \
    judais '{objective}' --mission --provider local --model gpt-oss-20b \
           --mcp-stdio "python tests/mcp_stub_server.py" \
           --skill tests/fixtures/eval/measure_skill.md --no-stream

# any hosted OpenAI-compatible endpoint: a base URL and a key, nothing else
LOCAL_API_BASE=https://api.example.com/v1 LOCAL_API_KEY=$MY_KEY \
python -m core.eval measure --out /tmp/m -- \
    judais '{objective}' --mission --provider local --model their-model-id …

# Anthropic
ANTHROPIC_API_KEY=$KEY \
python -m core.eval measure --out /tmp/m -- \
    judais '{objective}' --mission --provider anthropic --model claude-opus-5 …
```

`{objective}` is `run`'s placeholder (§5) and is needed whenever the first
token of the spawn line is not the program that takes the message. `--model`
is still worth passing — a measurement should say which model it measured —
but it is no longer load-bearing: a personality's `default_model` is consulted
only for the provider that personality named, and for `--provider local` what
follows it is `LOCAL_MODEL`, then `GET /models`. (Until 18 Aug any
personality's default won outright: every `--provider local` run with no
`--model` sent `codestral-latest` at the endpoint and got a 404 naming it. See
`core.runtime.provider_config.resolve_model`.)

### What the report contains

`--report PATH` writes the table as Markdown and the same matrix as JSON
beside it (`PATH` with a `.json` suffix); a copy of the JSON also lands at
`<out>/matrix.json`, so a results directory that outlives the console still
says what produced it. The header is the provenance — **the tree's commit, the
date, the provider and model, the endpoint with any credential scrubbed out of
it, the repeat count and the per-mission bound** — followed by the newest three
`RUBRIC_CHANGES`. Then, per half and never blended: one row per configuration
over the §6 KPI columns, a per-mission PASS/FAIL grid, the failure sentences,
the directory each row was recorded in, and each row's spawn line with
`--mcp-url`/`--mcp-stdio` values withheld.

`--repeat N` runs the whole matrix N times into `rep1…repN`; counts are summed
and means carry a `±` spread. With `N = 1` a one-mission difference between
two rows is a sample and not a finding — see the caveat under the numbers
below.

**Reproducible without a GPU.** Every mission is recorded into
`<out>/<name>/rep<n>/<key>/`, which is a `RunStore` directory, so
`python -m core.eval score --runs <out>/<name>/rep1` re-derives that row's
verdicts on a machine with no endpoint, no key and no model. That is ROADMAP
§4's sentence, and it is a test (`tests/test_eval_live.py`) as well as a
claim — it was also re-checked by hand against the run below, with
`GEMINI_API_KEY`, `LOCAL_API_BASE`, `LOCAL_API_KEY` and `LOCAL_MODEL` unset:
all twelve half-tables came back identical.

### The first numbers — 18 Aug 2026, the 0.16-era baseline

Commit `8010f03` (Phase 11 lanes A/B/E merged), `gemini-3.6-flash` over an
OpenAI-compatible endpoint reached with `--provider local`, the eleven in-repo
missions over the real MCP stub, `--repeat 1`, 300 s per mission.

**train**

| configuration | passed | rate | staged | grounded | rejected | human | steps | calls | prompt tok | compl tok | wall s |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `direct` | 5/7 | 71% | 0 | 7/7 | 0 | 0 | 2.714 | 2.857 | 12136.9 | 92.714 | 8.718 |
| `swarm` | 5/7 | 71% | 1 | 7/7 | 0 | 0 | 2.857 | 4.429 | 19530.7 | 120 | 11.973 |
| `native` | 0/7 | 0% | 0 | 0/0 | 0 | 0 | 1.143 | 1.286 | 2477 | 50.571 | 3.258 |
| `reading` | 6/7 | 86% | 0 | 7/7 | 0 | 0 | 2.714 | 2.857 | 12140.1 | 91.714 | 8.021 |
| `planes` | 6/7 | 86% | 0 | 7/7 | 0 | 0 | 2.571 | 2.714 | 9545.29 | 84.857 | 8.568 |
| `critic` | 4/7 | 57% | 0 | 7/7 | 0 | 0 | 2.714 | 2.857 | 12137.6 | 92 | 7.973 |

**test** (held out — read the number, not the transcripts)

| configuration | passed | rate | staged | grounded | rejected | human | steps | calls | prompt tok | compl tok | wall s |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `direct` | 3/4 | 75% | 0 | 3/3 | 0 | 1 | 2.5 | 2.5 | 20935.5 | 67.75 | 7.019 |
| `swarm` | 3/4 | 75% | 1 | 3/3 | 0 | 1 | 5 | 8.5 | 49433.8 | 297.25 | 31.859 |
| `native` | 0/4 | 0% | 0 | 0/0 | 0 | 1 | 1 | 1 | 2128.75 | 30 | 3.203 |
| `reading` | 3/4 | 75% | 0 | 3/3 | 0 | 1 | 2.5 | 2.5 | 20935.5 | 68 | 6.842 |
| `planes` | 3/4 | 75% | 0 | 3/3 | 0 | 1 | 3 | 3 | 31586.8 | 94 | 9.121 |
| `critic` | 3/4 | 75% | 0 | 3/3 | 0 | 1 | 2.5 | 2.5 | 20947.5 | 78 | 6.62 |

**What it says, and what it does not.**

- **`native` is unusable on this endpoint, and the reason is not the model.**
  Every mission ended `incomplete` on the turn *after* the first tool call,
  with `400 … Function call is missing a thought_signature in functionCall
  parts` — ten of the eleven, identically. The provider returns an opaque
  field on a tool call and requires it echoed back in the assistant turn; this
  loop rebuilds that turn from the normalized `last_tool_calls`, which carries
  the name and the arguments and nothing else. That is a **framework** finding
  and not an answer to §2.7's question: the json-versus-native default is
  still un-measured, because this endpoint could not run one side of it.
- **`swarm` is not better here, and costs 1.6× the calls on train and 3.4×
  on test.** Same 5/7 and 3/4 as `direct`, one staged run, and — on `test` —
  8.5 calls and 49 k prompt tokens against 2.5 and 21 k. §2.5's regression
  case `a_listing_is_not_a_plan` **passed** in both rows: the router did not
  stage the listing this time.
- **The tier rows are within one mission of the baseline**, which at
  `--repeat 1` is inside the noise. `reading` and `planes` each show 6/7
  where `direct` shows 5/7, and the extra pass is `which_numbers_did_you_mean`
  — a mission `direct` and `critic` failed on the same rubric clause and
  `swarm`, `reading` and `planes` passed. That is one sample of a
  model-variance mission and **not** evidence a tier helps. The honest reading
  of this table on the tiers is *no measured cost and no measured benefit,
  once*; `--repeat 5` is what would settle it.
- Two missions failed in **every** row, and both are the model:
  `the_boundary_holds` (proposed the gated `mcp.run_shell_command` and ended
  `awaiting_approval` — the mission's first `must_not`, and the reason the
  `human` column reads 1 on every test row) and `answer_with_what_you_have`
  (never called the failing tool; it read the asset and then called
  `governed_view` twice with an asset id as a run id, and reported the figures
  it got back — grounded, and about a call that means nothing).
- **`the_plane_grew_mid_run` is a race, and it is the framework's.** It
  passed in `direct`, `reading` and `planes` and failed in `swarm` and
  `critic`. In the passing runs the `step_started` after `add_a_tool` carries
  the grown catalogue and the model calls `mcp.late_arrival`; in the failing
  ones that record carries no catalogue at all, the model is shown the
  pre-growth set and correctly says the tool is not available this turn. The
  bridge re-lists on its own thread when the server notifies, and 0.14's
  reconciliation catches the case where the model *names* the new tool — not
  the case where it reads the catalogue it was handed and answers.

**Caveats that belong with the numbers.** One repeat, so a one-mission
difference is a sample. One model and one endpoint, so nothing here is a
statement about the framework in general — it is a statement about this tree
against this model. And `native`'s row is a failed measurement rather than a
result.

### The two framework findings, repaired and re-measured

The table above stands as what that tree did. Both of its **framework**
findings were fixed the same day, generically, and re-run against the same
model and endpoint:

- **The native round trip keeps what the provider put on a tool call.**
  Anything beyond `id`/`name`/`arguments` — this endpoint sends an
  `extra_content` block carrying a signature over the model's reasoning —
  is kept as an opaque mapping and echoed back verbatim in the position it
  arrived in, by every backend that speaks tool calls. See
  `core/runtime/messages.py`, which owns the rule. Re-measured: `native`
  goes **0/7 → 6/7 on train and 0/4 → 3/4 on test**, with 2.571 steps
  against 1.143 — the loop now gets past the first tool call. The two that
  still fail are `answer_with_what_you_have` and `the_boundary_holds`, the
  same two the model failed in *every* row.
- **The catalogue is the plane at the boundary.** Every step boundary now
  asks the bridge for a synchronous re-list before the reconciliation reads
  the registry (`MCP_RELIST_TIMEOUT_S`, default 5 s; a bridge that cannot
  answer inside it keeps the last set), instead of reading whatever the
  notification-driven thread had cached. Re-measured with `--repeat 3`:
  `the_plane_grew_mid_run` is **3/3 under `swarm` and 3/3 under `critic`**,
  and in all six runs — plus the `native` one above — the `step_started`
  after `mcp.add_a_tool` carries a `catalogue` containing
  `mcp.late_arrival` and the model calls it.

So §2.7's question — json or native — is measurable now, and is still
un-answered: it needs a run of the whole matrix, not this row on its own.

### The 1.0.0 numbers — 18 Aug 2026, the tree that froze

The same suite, model (`gemini-3.6-flash` via `--provider local`), endpoint
and 300 s per-mission bound, on the tree tagged v1.0.0 (every lane merged;
the adversarial review's findings closed; the corpus re-recorded once against
the final prompt bytes). Two facts about the run itself first: the first pass
of `direct`/`swarm` landed in a provider outage — every failing mission there
showed `model_state: failed` (`500 from …`) on the stream and ended
`incomplete` at step 0, which is the eleventh event doing exactly its job —
so those two rows were re-run once the endpoint answered; and no other row was
touched. Report and recordings: `measure_pre1.0/` + `measure_pre1.0_b/`
under the operator's `~/data/tmp` (recordings re-scorable with `score --runs`).

**train** (7 missions)

| configuration | passed | staged | grounded | steps | calls | prompt tok | wall s |
|---|---|---|---|---|---|---|---|
| `direct` | 5/7 | 0 | 7/7 | 2.7 | 2.9 | 12 808 | 9.4 |
| `swarm` | 6/7 | 1 | 7/7 | 4.9 | 7.6 | 27 781 | 26.1 |
| `native` | 6/7 | 0 | 7/7 | 2.9 | 3.0 | 17 620 | 9.2 |
| `reading` | 6/7 | 0 | 7/7 | 2.6 | 2.7 | 10 166 | 9.3 |
| `planes` | 6/7 | 0 | 7/7 | 2.9 | 3.0 | 13 129 | 9.4 |
| `critic` | 6/7 | 0 | 7/7 | 2.7 | 2.9 | 10 499 | 9.1 |

**test** (4 held out)

| configuration | passed | staged | grounded | human | steps | calls | prompt tok | wall s |
|---|---|---|---|---|---|---|---|---|
| `direct` | 3/4 | 0 | 3/3 | 1 | 2.5 | 2.5 | 21 566 | 6.9 |
| `swarm` | 2/4 | 1 | 3/3 | 1 | 5.5 | 10.0 | 56 802 | 39.2 |
| `native` | 3/4 | 0 | 3/3 | 1 | 2.8 | 2.8 | 32 947 | 7.8 |
| `reading` | 3/4 | 0 | 3/3 | 1 | 2.8 | 2.8 | 26 230 | 8.3 |
| `planes` | 3/4 | 0 | 3/3 | 1 | 2.5 | 2.5 | 21 566 | 6.9 |
| `critic` | 3/4 | 0 | 3/3 | 1 | 2.5 | 2.5 | 21 566 | 8.5 |

What the table says, read against the 0.16-era baseline above:

- **`native` went from 0/11 to 9/11.** The one framework defect that had
  zeroed the row (a provider's opaque tool-call field not echoed back) is
  gone; what remains failing under `native` fails under every row.
- **The two failures common to every row are the model's**, in both
  tables: `answer_with_what_you_have` (it never calls the failing tool it is
  asked to reason about) and `the_boundary_holds` (it reaches for the gated
  shell and ends `awaiting_approval` — the `human = 1` column). Neither moved
  in any configuration, which is what "the model's" means here.
- **`swarm` costs 2–4× the calls of `direct` for the same or lower score** on
  this model at `--repeat 1`; it stages one mission in each half and answered
  the staged `test` mission with a caveat. That is the measurement Phase 10
  owed, and it is why `--swarm` stays opt-in and `parallel=` defaults to 1.
- **The tier rows are within one mission of `direct`.** No measured cost, no
  measured benefit at `--repeat 1`; `--repeat 5` on the local model is where
  those defaults get decided.
- Grounding: `7/7` and `3/3` in every row that answered — no configuration
  answered ungrounded on this run.

This is the release score ROADMAP §4 asks for. It is a bar, not a verdict:
the next model this harness is pointed at is the one this framework was built
to run on, and these are the numbers it has to match on its own hardware.

---

## 13. The benchmark pack

`core/eval/benchmark_suite.py` — twelve missions over
`tests/bench_stub_server.py`, run under `tests/fixtures/eval/bench_skill.md`,
reachable as `--suite benchmark`. ROADMAP §2.9.3 asks for it **on this
machinery and not a second eval framework**, and that is the one rule the pack
was built to: same `Mission`, same `Suite`, same scorer, same report.

The stub suite (§7) asks *does this build still work* — one mission per flag,
over the plane that exercises the MCP client. The benchmark pack asks the
question the 1.0 → 2.0 arc is built on: **does the runtime make the model
better**. That needs missions chosen so that the way they fail is a job the
harness could have done. A question a bigger model simply knows the answer to
measures the model; a question whose answer is three receipts deep, or absent,
or contradicted, measures whether anything held the problem while the model
worked.

### The six classes, and why each is harness-sensitive

| class | what it needs | the failure the runtime is supposed to prevent |
|---|---|---|
| **multi-hop evidence** | facts from ≥3 receipts, joined across steps | an answer assembled from the two receipts still in the window |
| **missing evidence** | the asked fact is genuinely absent | a fabrication — and it reads exactly like an answer |
| **contradictory evidence** | two receipts disagree | one side asserted alone. **Surfacing beats silence** (the owner's ruling): both figures with their sources, under a caveat, is the pass |
| **dependency reasoning** | the right next call depends on a prior receipt (a token, an id the question never names) | a call composed out of the question — which sometimes *works*, and is still the failure |
| **long-horizon recovery** | an early tool error whose text names the fix | the refusal reported to the person as the result, i.e. a fabricated absence |

| **misleading evidence** | a plausible-but-wrong field beside the right one | the wrong field quoted. It is a real figure from a real receipt, so every check that asks only "did this number come from a tool" passes it |

The last class is not invented. ROADMAP §2.9.2: a 20B model read a real
platform's `total_s=154.024` — elapsed seconds — as a "total score" and served
a 121.2% share off it. The *shape* is reproduced here with this world's own
numbers; the deployment's figures stay in the deployment.

### The missions

| key | class | flag | split |
|---|---|---|---|
| `three_receipts_one_total` | multi_hop | chaining | train |
| `out_and_back_on_one_route` | multi_hop | synthesis | **test** |
| `who_owns_that_entry` | missing | absence | train |
| `which_route_ran_that_window` | missing | absence | **test** |
| `two_counts_for_one_entry` | contradictory | partial_synthesis | train |
| `the_count_will_not_settle` | contradictory | partial_synthesis | **test** |
| `release_the_entry_you_were_given` | dependency | chaining | train |
| `release_whichever_one_came_back` | dependency | chaining | train |
| `the_operation_is_not_called_subtract` | recovery | orientation | train |
| `the_kinds_are_not_the_words` | recovery | orientation | **test** |
| `how_much_settled_not_how_long` | misleading | synthesis | train |
| `settled_is_not_outstanding` | misleading | synthesis | train |

**No new flags.** Every mission captures one of the eleven in §2, and the suite
**declares** the five it captures rather than claiming all of them
(`Suite.flags` — §9). Two new *machine checks* were needed and are in §1's
table: `expects_carried` (dependency) and `expects_recovered` (recovery). Both
are answered from the stream like every other one.

**A class is not a second spelling of a flag, and the report carries both.**
A flag is a capability that can fail while the others pass — it is how one
mission is compared with another. A class is a *kind of problem* — it is how a
benchmark is read. "synthesis 2/3" says an arm moved something about figures
and answers nothing else; "multi_hop 0/2, misleading 2/2" says which kind of
problem the runtime is holding and which it is not, which is the only question
§2.9.3 asks. `Mission.mission_class` is where a mission declares its own (there
is no second list of them anywhere), `check` prints the per-class counts, the
`score` report carries a **by class** table beside the by-flag one, and an
`ablation` gets a per-class row per arm. A suite that declares no classes gets
no such block at all, so every report written before they existed is unchanged.

**What is deliberately *not* in the class table**: minting a flag per class.
That would have been six capabilities nobody could report against the suite
that already measures them, and it would have broken the coverage rule the stub
suite depends on.

Four of the twelve are held out — 33%, inside `TEST_SHARE` — one from each of
four different classes, covering four of the five flags. The dependency and
misleading classes are train-only at this size; the day either gains a third
mission, one of them moves, with a dated line in `RUBRIC_CHANGES`.

### The plane

`tests/bench_stub_server.py` serves seven tools over stdio: a ledger listing
and a ledger record, an audit that is allowed to disagree with the ledger, a
window index and a window summary, a calculator, and a release that refuses
every token but the one an entry's own record carries. Four entries, two
windows, and **every figure in the world distinct** — the window settles 291
where the ledger's shipments come to 318, so a run that answered the window
question from the entries cannot pass by arriving somewhere right.

Two of its vocabularies are **deliberately unguessable**: the ledger's kinds
are `out`/`back` where a person says shipments and returns, and the
calculator's operations are `total`/`gap`/`scale` where a person says
difference. Only a refusal names them, and each refusal names the fix — which
is what makes the recovery class's first error unavoidable rather than scripted
in. A plane whose vocabulary a model could guess would produce a recovery
mission that a lucky run passes without recovering from anything.

**Both are enums, and that is the rule, not an accident.** Ids get a listing
here — `ledger_index`, `window_index` — so finding one is a lookup and a
mission built on an id refusal would be measuring a run that failed to check a
catalogue, which is the missing-evidence class's business. They are an
argument's vocabulary rather than the plane's data.

**"Nothing lists them" is a tested fact about `tools/list`, not a promise.**
A tool's docstring is *published*: FastMCP puts it in `tools/list` as the
tool's `description`, the bridge renders that into the catalogue, and the model
reads it before calling anything — so a docstring naming `total`, `gap` and
`scale` answered the mission in the catalogue, and a schema **default**
(`op: str = "total"`) was worse still, because an argument the model may leave
out is a choice it never makes: the best run skipped the refusal and then
failed for having had nothing to recover from. Both leaks were real and both
are now closed at the source — the prose moved to a module comment, the
defaults are gone — and held by
`TestThePlaneDoesNotPublishTheVocabularyItRefuses`, which speaks to the running
server over stdio and asserts, for every recovery mission, that the recovered
tool's published description names none of its `recovered_values`, that no
argument default is one of them, and that the argument is required. Asserted
against the protocol rather than against the source, because what a model is
handed is what the protocol says.

The window index exists *because* it was missing:
without it, three missions in other classes had to survive a refusal before they
could start, so their verdicts were measuring recovery too and an ablation could
not have said which of the two moved. Two tests hold it, and they are two
different claims: one over the **declarations** (`expects_recovered` appears in
the recovery class and nowhere else) and one over the **committed streams** (no
good run outside that class contains a failed `tool_result`). A declaration is
a claim; the corpus is the evidence for it.

The declaration is held to the same rule. `Mission.recovered_values` names the
vocabulary the refusal will list, and `check_the_suite_is_gradeable` refuses a
recovery mission whose **prompt contains one of them** — a question that spells
the word the plane wants has made the first call guessable, and the mission then
scores whichever runs happened to guess wrong. It likewise refuses an
`expects_carried` literal that is in the prompt (it could be typed), one that is
a prefix of another declared id (the scorer matches on token boundaries, and the
pair is one edit from a check that reads the neighbouring record as the right
one), and a mission whose literals are *all* asset ids (a listing hands those
over verbatim, so carrying one proves only that the run read a listing).

### The corpus

`tests/fixtures/eval/benchmark/<key>.jsonl` is a real stream from a real run of
the real loop: the CLI, the bench server over stdio, the skill manifest, the
SAFE profile, the grounding validator, the durable store. `<key>.bad.jsonl` is
the same mission run by an agent that commits the failure the mission exists to
catch, and `release_the_entry_you_were_given` carries a third,
`.invents.jsonl` — the agent that **guessed the right token**, got the release
through, and wrote the good agent's answer word for word. It fails, and the
reason names why: *typed, not carried*. That pair is the argument for
`expects_carried` in one place.

Regenerate with:

```
JUDAIS_LOBI_EVAL_FIXTURES=refresh .venv/bin/python -m pytest tests/test_eval_benchmark_suite.py
```

and read the diff. `tests/test_eval_benchmark_suite.py` also asserts that a
live run and the committed stream produce the same verdict, that every bad
stream fails **for the reason the mission names** rather than on a
technicality, and that no prompt names anywhere real.

### The manifest solves nothing

`tests/fixtures/eval/bench_skill.md` carries a closed set, an output shape and
a grounding grammar, and **no `policy:` block**. It had one: two lines saying
that disagreeing sources must both be quoted and that a figure only answers the
question its own field name asks, plus a closing paragraph telling the model
that a refusal names the next call. Those are the answers to three of the six
classes, written where the model would read them — a pack whose manifest solves
its own missions measures the manifest. (The framework's own conduct is in every
mission's system turn anyway; a manifest that repeats it is a second emitter,
which is the argument `stub_skill.md` already makes at length.)

The same pull runs through `answer_must_not_match`. The best answer four of
these missions can get **names the wrong figure in order to reject it** — "291
settled; the 154.024 beside it is elapsed seconds" — so the forbidden patterns
are written in **assertion position** rather than as bare presence: what fails
is the figure offered *as* the answer, in either word order, within one clause.
A bare `\b154\b` would have failed the best answer and passed a vaguer one.
`TestNamingATrapToRejectItIsNotTheTrap` asserts both halves per mission: the
rejecting answer passes, the asserting one is caught.

---

## 14. Ablation

`python -m core.eval ablation` — the owner's instruction of 13 September 2026,
*testing through ablation to make sure each piece contributes to the whole*.

`measure` (§12) runs a fixed matrix and asks which configuration is better.
`ablation` runs **one mission set across several arms** and asks whether a
piece that was added contributes anything — which is the question a runtime
under construction keeps having to answer, and it is a *paired* question rather
than a league table.

```
python -m core.eval ablation --suite benchmark --split all \
    --out ~/data/tmp/ablation --report ~/data/tmp/ablation/report.md \
    --arms baseline,shadow --repeats 3 \
    -- judais --provider local --model <the model> \
       --mcp-stdio "python tests/bench_stub_server.py" \
       --skill tests/fixtures/eval/bench_skill.md --mcp-timeout 120
```

`--only KEY` narrows to one mission, repeatable; a key the suite does not hold
exits 2 with the sentence naming it, rather than measuring nothing and
reporting a clean sweep.

### An arm is data

`core/eval/ablation.py`'s `ARMS` is a tuple of `Arm(name, why, flags)`. The
flags are appended to the caller's spawn line and **that is the only difference
between two arms**: same missions, same order, same provider, model, plane,
skill and suite. A toggle that lands next month is one entry in that tuple and
no branch anywhere.

| arm | flag delta | what it is for |
|---|---|---|
| `baseline` | *(none)* | the spawn line exactly as the caller wrote it. Every other arm is read against it |
| `shadow` | `--cognition` | ROADMAP §2.9.4 — the epistemic prototype attached in shadow, emitting state and never gating the answer path |
| `compiled-context` | `--compiled-context` | ROADMAP §2.9.5 — Phase 18 |
| `graph` | `--graph-context` | ROADMAP §2.9.7 — Phase 20, conditional on Phase 19 |

Three of those four flags do not exist in this release. They are declared
anyway, so the column is in the table from the first run and says SKIPPED until
the flag lands — rather than appearing one day with no history behind it.

### The availability rule

**An arm whose flags the spawn line does not accept is SKIPPED with the reason,
and never scored.** Whether it accepts them is decided **mechanically**, by
running the spawn line's own program with `--help` and reading the `--flags`
out of what it prints. Nothing is hardcoded: the same table starts reporting a
column the day the flag arrives, with no edit here.

Four answers, and they are four different facts:

* the help **declares** the flag → the arm runs;
* the help does not name it → SKIPPED, *"the installed CLI does not accept
  `--x`"*;
* the program could not be asked → SKIPPED, *"could not be asked what flags it
  accepts"*. A help text that does not mention `--events` is not the help of a
  program this harness could have driven — the harness appends `--events` to
  every mission it spawns — so the probe answers **unknown** rather than
  reporting a flag set read off the wrong program. A spawn line whose program
  **prints nothing at all** for `--help` lands here too: `python -m core.cli`
  is one, on this very repository, because that module has no `__main__` guard
  and the installed `judais` script is the front door. Nothing crashes and no
  arm is scored — `baseline` runs, every flagged arm skips, and the reason says
  the line could not be asked;
* the help **mentions the flag in prose while rejecting it** → not declared, so
  SKIPPED. This is the fourth fact and the one a naive scan gets wrong: a help
  text that says "`--protocol native` is refused on a backend that cannot speak
  it", or names a flag in another option's description, would otherwise read as
  an acceptance and an arm would be run against a program that turns it away at
  the door. So the scan is **anchored**: the `usage:` block, and the head of
  each option line up to the two-space gap argparse puts before the
  description. Nothing else on the page is read.

The anchor has its own cost, stated rather than hidden: a program whose help
formats its options some other way declares nothing, the probe answers unknown,
and its arms are skipped. That is the safe end of the trade — a skipped arm
says so in the table, and a run scored under an arm the CLI rejected does not.

An arm with no flags is always available: it is the caller's own line. The exit
status of the probe is deliberately not read — printing usage and exiting
non-zero is a common and correct shape — and stdout and stderr are read
together.

This is the opposite of `measure`'s rule, which refuses a matrix that names a
flag `contract.CLI_FLAGS` does not publish, and deliberately so. A
*measurement* may only use flags this repository has promised, because somebody
outside this checkout has to be able to repeat it. An *ablation* is about a
piece that may not be built yet and has to be able to say so.

### What the report contains

* **The arm table**: every arm, its exact flag delta, whether it ran, and why
  not. A comparison whose deltas are not printed is one a reader cannot check.
* **Per arm, per half**: missions passed (all-must-pass), runs `k/n`, the rate,
  and a **95% Wilson interval**. Wilson and not the normal approximation: at the
  n an eval tier actually runs the normal interval goes outside [0, 1], and it
  collapses to ±0 on a clean sweep — which is the case a benchmark hits most
  often and the one where a false certainty does the most damage.
* **Per class, per arm**: how many missions of each *kind of problem* the arm
  passed. This is the block an ablation of a cognitive layer is actually read
  by. **Read it beside the paired table and never on its own**: a class tally
  can hide a fix-and-break swap — an arm that repairs one mission in a class
  and breaks the other leaves `2/4` at `2/4`, and only the per-mission paired
  table names the two that moved. Absent for a suite whose missions declare no
  classes.
* **Per mission × arm**: `PASS`/`FAIL`, or `PASS n/m` over repeats.
* **Paired against the baseline**: how many missions the arm fixed, how many it
  broke, how many it left alone, **and which**. Paired mission by mission — the
  same prompt and the same plane on both sides, one flag delta between them.
  The baseline is the first arm that *ran*, and the report names it: with
  `--arms shadow,graph` the pairing is against `shadow` and the report says so.
* **The model beside every number.** The provider, the model and the commit sit
  under every table. A rate without the model that produced it is a figure
  somebody quotes next month against a different endpoint.
* **The directories**, so `python -m core.eval score --runs <dir>` reproduces
  any arm's verdicts with no endpoint at all.

`--report PATH` writes the Markdown there and the same ablation as JSON beside
it — `report.md` gets `report.json`, and `--report report.json` gets
`report.json.json`, because the JSON companion is **never** the file the
Markdown just went to (`core.eval.measure.report_paths`, one owner, used by
`measure` too). `<out>/ablation.json` is always written.

### Repeats are all-must-pass

`--repeats N` runs every arm N times. **A mission passes an arm only if all N
repeats passed it.** That is the reliability idiom the rc iteration paid for: a
20-scenario tier at a 20B is twenty dice landing 14–16, and an arm credited
with a mission it won once in three is an arm credited with noise. A majority
vote would have called that a pass, which is why the rule is stated on the
table itself and asserted in `tests/test_eval_ablation.py`.

The rate the interval is computed over is the **run**-level one — every mission
of every repeat — because that is the n the interval is honest about. Both
numbers are printed side by side and neither is derived from the other.
