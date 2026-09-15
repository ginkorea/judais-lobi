# ablation — suite `benchmark`

- **commit** `831d39e757755dc31da0e1fc33b2a909c47bbf48`
- **date** 2026-09-15
- **provider / model** `local` / `openai/gpt-oss-20b`
- **endpoint** `http://127.0.0.1:8000/v1`
- **repeats** 3, per-mission bound 600.0 s

Every arm ran the SAME missions, in the same order, under the same spawn line. The only difference between two arms is the flag delta printed beside its name.

## The arms

| arm | flag delta | state | why / why not |
|---|---|---|---|
| `baseline` | `(none)` | ran | the spawn line exactly as the caller wrote it. Every other arm is a paired reading against this one, so it is the only arm that must always be able to run |
| `shadow` | `--cognition` | ran | ROADMAP §2.9.4: the epistemic prototype attached in shadow — it emits state and guidance and never gates the answer path. The question this arm answers is whether holding the problem beside the model changes what the model does with it |
| `compiled-context` | `--compiled-context` | ran | ROADMAP §2.9.5: the context compiled from the epistemic state rather than accumulated as a transcript — one block a step, holding the facts with their receipts, both sides of every conflict and what is only claimed. The question this arm answers is whether a model told what the runtime believes spends fewer calls finding it out again |
| `graph` | `--graph-context` | ran | ROADMAP §2.9.7: the run's links kept as a topology and the compiled block's RELATED section hydrated around what is owed. The question this arm answers is whether telling a model what is connected to the question changes how it spends its calls. Declared before the flag existed; graduated with Phase 20a |
| `swarm-steering` | `--swarm-steering` | ran | ROADMAP §2.9.7: the derived swarm's first half — a staged turn's planner is offered the independent groups of what is still owed, and plans whatever it plans. The question this arm answers is whether a planner told what does NOT depend on what writes a better plan. It is a CONDITIONAL reading: the delta can only show on a mission the router staged and whose frontier had two independent groups, so a suite of direct missions will report this arm as a faithful null. Which missions those were is the suite's business and not this table's |

Paired deltas below are against **`baseline`** — the first arm that ran.

### The design arms

- `shadow`: 0 subject link(s) across 36 reasoning log(s)
- `compiled-context`: 0 subject link(s) across 36 reasoning log(s)
- `graph`: 0 subject link(s) across 36 reasoning log(s)
- `swarm-steering`: 0 subject link(s) across 36 reasoning log(s)

**The subject spine (the design's A3) is not a flag.** `--compiled-context` shows subject lines exactly where the plane declares identifiers (a server's `outputSchema`, a skill's `tools:` block), so which design arm the `compiled-context` column IS here is a fact about the plane, read off the runs' own reasoning logs above: zero links means this plane declares nothing and the column is the design's **A2** (the view without subjects); links mean it is **A3**. The A3−A2 delta is therefore a paired reading of this same table run twice — once against the declaring plane, once with the declarations withheld — and never of two arms within one table. Read A2−A0 as the view, A3−A2 as the spine, A4−A3 as extraction, and NEVER A4−A0 as one number.

## train

| arm | model | missions (all repeats) | runs k/n | rate | 95% Wilson | infra | chars/call | view share |
|---|---|---|---|---|---|---|---|---|
| `baseline` | `local/openai/gpt-oss-20b` | 5/8 | 17/24 | 71% | 51%–85% | 0 | 11,241 | 0.0% |
| `shadow` | `local/openai/gpt-oss-20b` | 2/8 | 10/24 | 42% | 24%–61% | 0 | 11,255 | 0.0% |
| `compiled-context` | `local/openai/gpt-oss-20b` | 3/8 | 13/24 | 54% | 35%–72% | 0 | 11,484 | 1.6% |
| `graph` | `local/openai/gpt-oss-20b` | 4/8 | 15/24 | 62% | 43%–79% | 0 | 11,449 | 1.6% |
| `swarm-steering` | `local/openai/gpt-oss-20b` | 2/8 | 12/24 | 50% | 31%–69% | 0 | 11,293 | 0.0% |

*missions* is all-must-pass: a mission counts for an arm only where every repeat passed it. *runs k/n* is every mission of every repeat, which is the n the interval is computed over. *infra* is the repeats that never reached a model: they are out of k, out of n and out of the interval, and listed below — a flag delta cannot be credited or blamed for a run the endpoint ate.

*chars/call* is the mean size (in characters, not bytes) of the requests this arm's runs actually sent, and *view share* the compiled view's **raw** part of them — the view against this arm's own requests, which is not the same quantity as the marginal `Δ chars/call` below and can be larger than it: an arm whose block replaces transcript the baseline was carrying shows a share without having cost that much. Both come out of the recordings themselves — `python -m core.eval context --runs <the directory below>` prints the whole profile, including the growth curve and whether the pinned prefix held. `—` is an arm whose runs recorded no model log, which is not the same fact as a cheap one.

### train — what the runs spent

| arm | calls/run | extraction | tokens/run | wall s/run | unsupported/run | dead ends/run | calls→chain | premature |
|---|---|---|---|---|---|---|---|---|
| `baseline` | 4.2 | 0 | 11,316 | 6.2 | 0.00 | 0.08 | 3.00 | 2/24 |
| `shadow` | 4.5 | 0 | 12,752 | 13.5 | 0.04 | 0.17 | 3.00 | 7/24 |
| `compiled-context` | 4.5 | 0 | 12,416 | 7.5 | 0.04 | 0.08 | 3.00 | 4/24 |
| `graph` | 4.4 | 0 | 11,858 | 5.7 | 0.00 | 0.12 | 3.00 | 4/24 |
| `swarm-steering` | 4.5 | 0 | 11,893 | 6.1 | 0.12 | 0.00 | 3.00 | 5/24 |

Means are per graded run, unreported figures out of the denominator. *extraction* is the RECORDED breakout — model calls the extraction door made, counted off the recordings by their own `kind` — and reads 0 until `--extract` exists, which is the true count and not a placeholder. *unsupported/run* is what the grounding verdict could not find a receipt for; *dead ends/run* is dispatches off the mission's declared obligation path, *calls→chain* the price of the first completed carried-chain, and *premature* the runs that answered with that path unwalked, over the runs the question applied to — each defined once, in `core.eval.score`, and read here rather than recomputed.

### train — by class

| class | `baseline` | `shadow` | `compiled-context` | `graph` | `swarm-steering` |
|---|---|---|---|---|---|
| multi_hop | 1/1 (100%) | 0/1 (0%) | 1/1 (100%) | 1/1 (100%) | 1/1 (100%) |
| missing | 0/1 (0%) | 0/1 (0%) | 0/1 (0%) | 0/1 (0%) | 0/1 (0%) |
| contradictory | 0/1 (0%) | 0/1 (0%) | 0/1 (0%) | 0/1 (0%) | 0/1 (0%) |
| dependency | 2/2 (100%) | 2/2 (100%) | 1/2 (50%) | 2/2 (100%) | 1/2 (50%) |
| recovery | 0/1 (0%) | 0/1 (0%) | 1/1 (100%) | 1/1 (100%) | 0/1 (0%) |
| misleading | 2/2 (100%) | 0/2 (0%) | 0/2 (0%) | 0/2 (0%) | 0/2 (0%) |

All cells above: `local/openai/gpt-oss-20b`, all-must-pass over 3 repeat(s). **A class tally can hide a fix-and-break swap** — an arm that repairs one mission of a class and breaks another leaves the tally where it was; the paired table below is where that shows.

### train — per mission × arm

| mission | flag | `baseline` | `shadow` | `compiled-context` | `graph` | `swarm-steering` |
|---|---|---|---|---|---|---|
| `three_receipts_one_total` | chaining | PASS 3/3 | FAIL 2/3 | PASS 3/3 | PASS 3/3 | PASS 3/3 |
| `who_owns_that_entry` | absence | FAIL 0/3 | FAIL 0/3 | FAIL 0/3 | FAIL 0/3 | FAIL 0/3 |
| `two_counts_for_one_entry` | partial_synthesis | FAIL 0/3 | FAIL 0/3 | FAIL 0/3 | FAIL 0/3 | FAIL 0/3 |
| `release_the_entry_you_were_given` | chaining | PASS 3/3 | PASS 3/3 | FAIL 2/3 | PASS 3/3 | FAIL 2/3 |
| `release_whichever_one_came_back` | chaining | PASS 3/3 | PASS 3/3 | PASS 3/3 | PASS 3/3 | PASS 3/3 |
| `the_operation_is_not_called_subtract` | orientation | FAIL 2/3 | FAIL 1/3 | PASS 3/3 | PASS 3/3 | FAIL 2/3 |
| `how_much_settled_not_how_long` | synthesis | PASS 3/3 | FAIL 0/3 | FAIL 1/3 | FAIL 2/3 | FAIL 1/3 |
| `settled_is_not_outstanding` | synthesis | PASS 3/3 | FAIL 1/3 | FAIL 1/3 | FAIL 1/3 | FAIL 1/3 |

All cells above: `local/openai/gpt-oss-20b` at commit `831d39e757755dc31da0e1fc33b2a909c47bbf48`.

### train — paired against `baseline`

| arm | flag delta | fixed | broke | unchanged | Δ chars/call | which fixed | which broke |
|---|---|---|---|---|---|---|---|
| `shadow` | `--cognition` | +0 | -3 | 5 | +14 | — | `how_much_settled_not_how_long`, `settled_is_not_outstanding`, `three_receipts_one_total` |
| `compiled-context` | `--compiled-context` | +1 | -3 | 4 | +243 | `the_operation_is_not_called_subtract` | `how_much_settled_not_how_long`, `release_the_entry_you_were_given`, `settled_is_not_outstanding` |
| `graph` | `--graph-context` | +1 | -2 | 5 | +208 | `the_operation_is_not_called_subtract` | `how_much_settled_not_how_long`, `settled_is_not_outstanding` |
| `swarm-steering` | `--swarm-steering` | +0 | -3 | 5 | +52 | — | `how_much_settled_not_how_long`, `release_the_entry_you_were_given`, `settled_is_not_outstanding` |

Paired, mission by mission, `local/openai/gpt-oss-20b`: the same prompt and the same plane on both sides, one flag delta between them. **Δ chars/call is the price of that delta** — what the arm added to the mean model call against `baseline` — so what an arm bought and what it cost are one line.

#### train — capability vs cost

**`shadow` added context and no capability.** Against `baseline` it moved the missions passed by -3 while adding 14 characters to the mean model call (11,241 → 11,255). The owner's criterion — *does not make the context bloated and the agent less capable* — is not met by this arm on this run. Flagged, not judged: one ablation is one run.
**`compiled-context` added context and no capability.** Against `baseline` it moved the missions passed by -2 while adding 243 characters to the mean model call (11,241 → 11,484). The owner's criterion — *does not make the context bloated and the agent less capable* — is not met by this arm on this run. Flagged, not judged: one ablation is one run.
**`graph` added context and no capability.** Against `baseline` it moved the missions passed by -1 while adding 208 characters to the mean model call (11,241 → 11,449). The owner's criterion — *does not make the context bloated and the agent less capable* — is not met by this arm on this run. Flagged, not judged: one ablation is one run.
**`swarm-steering` added context and no capability.** Against `baseline` it moved the missions passed by -3 while adding 52 characters to the mean model call (11,241 → 11,293). The owner's criterion — *does not make the context bloated and the agent less capable* — is not met by this arm on this run. Flagged, not judged: one ablation is one run.

## test

| arm | model | missions (all repeats) | runs k/n | rate | 95% Wilson | infra | chars/call | view share |
|---|---|---|---|---|---|---|---|---|
| `baseline` | `local/openai/gpt-oss-20b` | 2/4 | 8/12 | 67% | 39%–86% | 0 | 11,294 | 0.0% |
| `shadow` | `local/openai/gpt-oss-20b` | 2/4 | 7/12 | 58% | 32%–81% | 0 | 11,640 | 0.0% |
| `compiled-context` | `local/openai/gpt-oss-20b` | 3/4 | 9/12 | 75% | 47%–91% | 0 | 11,530 | 1.4% |
| `graph` | `local/openai/gpt-oss-20b` | 2/4 | 6/12 | 50% | 25%–75% | 0 | 11,368 | 1.0% |
| `swarm-steering` | `local/openai/gpt-oss-20b` | 2/4 | 7/12 | 58% | 32%–81% | 0 | 11,407 | 0.0% |

*missions* is all-must-pass: a mission counts for an arm only where every repeat passed it. *runs k/n* is every mission of every repeat, which is the n the interval is computed over. *infra* is the repeats that never reached a model: they are out of k, out of n and out of the interval, and listed below — a flag delta cannot be credited or blamed for a run the endpoint ate.

*chars/call* is the mean size (in characters, not bytes) of the requests this arm's runs actually sent, and *view share* the compiled view's **raw** part of them — the view against this arm's own requests, which is not the same quantity as the marginal `Δ chars/call` below and can be larger than it: an arm whose block replaces transcript the baseline was carrying shows a share without having cost that much. Both come out of the recordings themselves — `python -m core.eval context --runs <the directory below>` prints the whole profile, including the growth curve and whether the pinned prefix held. `—` is an arm whose runs recorded no model log, which is not the same fact as a cheap one.

### test — what the runs spent

| arm | calls/run | extraction | tokens/run | wall s/run | unsupported/run | dead ends/run | calls→chain | premature |
|---|---|---|---|---|---|---|---|---|
| `baseline` | 4.6 | 0 | 12,639 | 10.1 | 0.00 | 0.25 | — | 1/12 |
| `shadow` | 6.0 | 0 | 17,514 | 15.7 | 0.00 | 0.92 | — | 1/12 |
| `compiled-context` | 5.1 | 0 | 14,371 | 10.5 | 0.00 | 0.50 | — | 1/12 |
| `graph` | 4.6 | 0 | 12,697 | 9.5 | 0.00 | 0.50 | — | 3/12 |
| `swarm-steering` | 5.0 | 0 | 13,691 | 8.6 | 0.08 | 0.42 | — | 2/12 |

Means are per graded run, unreported figures out of the denominator. *extraction* is the RECORDED breakout — model calls the extraction door made, counted off the recordings by their own `kind` — and reads 0 until `--extract` exists, which is the true count and not a placeholder. *unsupported/run* is what the grounding verdict could not find a receipt for; *dead ends/run* is dispatches off the mission's declared obligation path, *calls→chain* the price of the first completed carried-chain, and *premature* the runs that answered with that path unwalked, over the runs the question applied to — each defined once, in `core.eval.score`, and read here rather than recomputed.

### test — by class

| class | `baseline` | `shadow` | `compiled-context` | `graph` | `swarm-steering` |
|---|---|---|---|---|---|
| multi_hop | 0/1 (0%) | 0/1 (0%) | 1/1 (100%) | 0/1 (0%) | 0/1 (0%) |
| missing | 0/1 (0%) | 0/1 (0%) | 0/1 (0%) | 0/1 (0%) | 0/1 (0%) |
| contradictory | 1/1 (100%) | 1/1 (100%) | 1/1 (100%) | 1/1 (100%) | 1/1 (100%) |
| dependency | — | — | — | — | — |
| recovery | 1/1 (100%) | 1/1 (100%) | 1/1 (100%) | 1/1 (100%) | 1/1 (100%) |
| misleading | — | — | — | — | — |

All cells above: `local/openai/gpt-oss-20b`, all-must-pass over 3 repeat(s). **A class tally can hide a fix-and-break swap** — an arm that repairs one mission of a class and breaks another leaves the tally where it was; the paired table below is where that shows.

### test — per mission × arm

| mission | flag | `baseline` | `shadow` | `compiled-context` | `graph` | `swarm-steering` |
|---|---|---|---|---|---|---|
| `out_and_back_on_one_route` | synthesis | FAIL 2/3 | FAIL 1/3 | PASS 3/3 | FAIL 0/3 | FAIL 1/3 |
| `which_route_ran_that_window` | absence | FAIL 0/3 | FAIL 0/3 | FAIL 0/3 | FAIL 0/3 | FAIL 0/3 |
| `the_count_will_not_settle` | partial_synthesis | PASS 3/3 | PASS 3/3 | PASS 3/3 | PASS 3/3 | PASS 3/3 |
| `the_kinds_are_not_the_words` | orientation | PASS 3/3 | PASS 3/3 | PASS 3/3 | PASS 3/3 | PASS 3/3 |

All cells above: `local/openai/gpt-oss-20b` at commit `831d39e757755dc31da0e1fc33b2a909c47bbf48`.

### test — paired against `baseline`

| arm | flag delta | fixed | broke | unchanged | Δ chars/call | which fixed | which broke |
|---|---|---|---|---|---|---|---|
| `shadow` | `--cognition` | +0 | -0 | 4 | +346 | — | — |
| `compiled-context` | `--compiled-context` | +1 | -0 | 3 | +236 | `out_and_back_on_one_route` | — |
| `graph` | `--graph-context` | +0 | -0 | 4 | +74 | — | — |
| `swarm-steering` | `--swarm-steering` | +0 | -0 | 4 | +113 | — | — |

Paired, mission by mission, `local/openai/gpt-oss-20b`: the same prompt and the same plane on both sides, one flag delta between them. **Δ chars/call is the price of that delta** — what the arm added to the mean model call against `baseline` — so what an arm bought and what it cost are one line.

#### test — capability vs cost

**`shadow` added context and no capability.** Against `baseline` it moved the missions passed by +0 while adding 346 characters to the mean model call (11,294 → 11,640). The owner's criterion — *does not make the context bloated and the agent less capable* — is not met by this arm on this run. Flagged, not judged: one ablation is one run.
**`graph` added context and no capability.** Against `baseline` it moved the missions passed by +0 while adding 74 characters to the mean model call (11,294 → 11,368). The owner's criterion — *does not make the context bloated and the agent less capable* — is not met by this arm on this run. Flagged, not judged: one ablation is one run.
**`swarm-steering` added context and no capability.** Against `baseline` it moved the missions passed by +0 while adding 113 characters to the mean model call (11,294 → 11,407). The owner's criterion — *does not make the context bloated and the agent less capable* — is not met by this arm on this run. Flagged, not judged: one ablation is one run.

Train and test are reported apart, always.

Every arm is reproducible without an endpoint: `python -m core.eval score --runs <dir>` over the directory beside it produces the same verdicts.

| arm | runs recorded in |
|---|---|
| `baseline` | `/home/gompert/bench/ablation-v1.5.0/baseline/rep1`, `/home/gompert/bench/ablation-v1.5.0/baseline/rep2`, `/home/gompert/bench/ablation-v1.5.0/baseline/rep3` |
| `shadow` | `/home/gompert/bench/ablation-v1.5.0/shadow/rep1`, `/home/gompert/bench/ablation-v1.5.0/shadow/rep2`, `/home/gompert/bench/ablation-v1.5.0/shadow/rep3` |
| `compiled-context` | `/home/gompert/bench/ablation-v1.5.0/compiled-context/rep1`, `/home/gompert/bench/ablation-v1.5.0/compiled-context/rep2`, `/home/gompert/bench/ablation-v1.5.0/compiled-context/rep3` |
| `graph` | `/home/gompert/bench/ablation-v1.5.0/graph/rep1`, `/home/gompert/bench/ablation-v1.5.0/graph/rep2`, `/home/gompert/bench/ablation-v1.5.0/graph/rep3` |
| `swarm-steering` | `/home/gompert/bench/ablation-v1.5.0/swarm-steering/rep1`, `/home/gompert/bench/ablation-v1.5.0/swarm-steering/rep2`, `/home/gompert/bench/ablation-v1.5.0/swarm-steering/rep3` |

The spawn line each arm ran, with `--mcp-url` and `--mcp-stdio` values withheld — either can carry a token and a report outlives the run:

- `baseline`: judais --provider local --model openai/gpt-oss-20b --mcp-stdio <withheld> --skill tests/fixtures/eval/bench_skill.md --mcp-timeout 120 --temperature 0.2
- `shadow`: judais --provider local --model openai/gpt-oss-20b --mcp-stdio <withheld> --skill tests/fixtures/eval/bench_skill.md --mcp-timeout 120 --temperature 0.2 --cognition
- `compiled-context`: judais --provider local --model openai/gpt-oss-20b --mcp-stdio <withheld> --skill tests/fixtures/eval/bench_skill.md --mcp-timeout 120 --temperature 0.2 --compiled-context
- `graph`: judais --provider local --model openai/gpt-oss-20b --mcp-stdio <withheld> --skill tests/fixtures/eval/bench_skill.md --mcp-timeout 120 --temperature 0.2 --graph-context
- `swarm-steering`: judais --provider local --model openai/gpt-oss-20b --mcp-stdio <withheld> --skill tests/fixtures/eval/bench_skill.md --mcp-timeout 120 --temperature 0.2 --swarm-steering