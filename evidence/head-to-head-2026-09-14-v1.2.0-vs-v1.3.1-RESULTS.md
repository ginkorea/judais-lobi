# judais-lobi v1.3.1 — release ablation (benchmark: v1.2.0)

Generated 2026-09-14T01:39:06-10:00 from 3 eval run(s).

The Mission Agent behind TAIPAN's Mission Pane, on the pool, over
the same mission set, against a served `openai/gpt-oss-20b` the
pane leased itself. One release is measured here; the comparison
is against the ledger's champion row, which was measured in its
own session and is recorded in `LEDGER.md` beside the conditions
it ran under.

Held constant with the champion's run: the eval harness (one copy
of `mission_eval.py`), the pane's flags, the temperature, the
skills, the tool plane, the served model, the tier, and the whole
transitive dependency set — this arm's venv is production's own
`pip freeze`, every version pinned, with the tag installed
`--no-deps` so nothing could move. `--cognition` OFF unless a row
says otherwise.

**Wall clock across days is the weakest of the three criteria**
and is read as such below. Accuracy and completion are properties
of what the agent did. Wall clock is also a property of what else
the pool was doing, and these two runs did not share a pool.

Three criteria, the owner's: wall clock, completion, accuracy.

* **accuracy** — `mission_eval.py`'s own pass rate. A PASS is
  behavioural ("did the agent do the sensible thing"), never
  string-exact.
* **completion** — the share of missions in which every turn ended
  `finished` rather than `timeout` or `error`. Not the same question
  as accuracy: a turn can finish and still be graded FAIL.
* **wall clock** — mean seconds per mission (`elapsed_s`), with the
  run-to-run spread beside it so a gap can be read against the noise.

## Winner

**v1.3.1 improves on 0 of the three criteria and regresses on 2**, against the ledger's champion v1.2.0.

* **accuracy — regresses.** v1.2.0 96.7% (29/30) vs v1.3.1 86.7% (26/30); 10.0 pt to v1.2.0.
* **completion — regresses.** v1.2.0 100.0% vs v1.3.1 96.7% of missions ran every turn to `finished`; 3.3 pt to v1.2.0.
* **wall clock — no difference.** v1.2.0 48.47 s vs v1.3.1 61.14 s per mission: a 12.67 s gap inside the 35.22 s spread the runs showed within each version, which is not a difference this measurement can see. Measured on a different day from the champion's row, so this criterion is the weakest of the three here: pool load, card occupancy and the served model's warmth all move it and none of them is judais-lobi. The conditions of both runs are recorded in LEDGER.md.

## Aggregate, per version

| version | runs | accuracy | passed | completion | mean wall/mission | spread | mean total |
|---|---|---|---|---|---|---|---|
| v1.3.1 | 3 | 86.7% | 26/30 | 96.7% | 61.14 s | ±35.22 s | 611.4 s |

The benchmark row, from the ledger — v1.2.0, measured 2026-09-13T19:10:49-10:00:

| version | runs | accuracy | passed | completion | mean wall/mission | spread | mean total |
|---|---|---|---|---|---|---|---|
| v1.2.0 | 3 | 96.7% | 29/30 | 100.0% | 48.47 s | ±22.03 s | 484.7 s |

Source: `/home/gompert/data/tmp-pytest-conductor/head-to-head/../../workspace/TAIPAN/plan/RELEASE_EVIDENCE/judais-head-to-head/2026-09-14-v1.1.3-vs-v1.2.0-summary.json`. That row was not re-measured for this report and no number in it was edited.

## Conditions this run was measured under

* **date** — 2026-09-14T11:05:34Z
* **host** — jl-i (taipan-compute)
* **release** — v1.3.1
* **tier** — baseline
* **runs** — 3
* **arm_sha** — v1.3.1 @ 605f919
* **venv_parity** — 58 package(s) identical to production — only judais-lobi differs
* **harness** — mission_eval.py sha 3860e8cf730ea87a
* **service_tree** — newest file in the service tree: 2026-09-14T00:09:16Z
* **production** — production's pane is up (recorded as a condition; never an arm, never touched)
* **broker_before** — status ok, 0 running, 0 queued
* **cards_before** — all cards idle: 0, 0 MiB;1, 0 MiB;2, 0 MiB;3, 0 MiB
* **other_vllm** — no vLLM running; this pane's lease will be the only one
* **endpoint** — http://127.0.0.1:60037/v1
* **cards_during** — 0, 19544 MiB;1, 19544 MiB;2, 0 MiB;3, 0 MiB;
* **cards_after** — all cards released: 0, 0 MiB;1, 0 MiB;2, 0 MiB;3, 0 MiB

Recorded because wall clock is only readable against them.

## Per run

| label | version | tier | passed | accuracy | completed | completion | mean wall | median wall | sum elapsed | start→finish |
|---|---|---|---|---|---|---|---|---|---|---|
| v1.3.1-run1 | v1.3.1 | baseline | 8/10 | 80.0% | 9/10 | 90.0% | 82.09 s | 66.09 s | 820.87 s | 821.0 s |
| v1.3.1-run2 | v1.3.1 | baseline | 9/10 | 90.0% | 10/10 | 100.0% | 54.47 s | 42.05 s | 544.71 s | 544.0 s |
| v1.3.1-run3 | v1.3.1 | baseline | 9/10 | 90.0% | 10/10 | 100.0% | 46.87 s | 32.07 s | 468.73 s | 468.0 s |

`sum elapsed` is the scenarios only. `start→finish` additionally
carries whatever the harness did around them, and on the first eval
of a session that includes waiting for a cold model — which is why
the wall-clock verdict above is taken on `elapsed_s` and not on this
column.

## Per mission, per run

| scenario | v1.3.1-run1 | v1.3.1-run2 | v1.3.1-run3 |
|---|---|---|---|
| coref | PASS 116s | PASS 72s | PASS 80s |
| correction | PASS 140s | PASS 28s | PASS 24s |
| deepresearch | FAIL 20s | PASS 12s | PASS 12s |
| empty | PASS 16s | PASS 16s | PASS 16s |
| followup_plot | PASS 92s | PASS 128s | FAIL 128s |
| governed | FAIL 84s | FAIL 44s | PASS 64s |
| install | PASS 44s | PASS 40s | PASS 32s |
| pivot | PASS 48s | PASS 96s | PASS 32s |
| plot | PASS 220s ! | PASS 72s | PASS 48s |
| web | PASS 40s | PASS 36s | PASS 32s |

Each cell is `outcome elapsed_s`, with `!` where a turn did not end
`finished`.

## Provenance

* `v1.3.1-run1` — http://127.0.0.1:8771, /home/gompert/data/tmp-pytest-conductor/head-to-head/results/2026-09-14T11-05-28Z/v1.3.1-run1/summary.json
* `v1.3.1-run2` — http://127.0.0.1:8771, /home/gompert/data/tmp-pytest-conductor/head-to-head/results/2026-09-14T11-05-28Z/v1.3.1-run2/summary.json
* `v1.3.1-run3` — http://127.0.0.1:8771, /home/gompert/data/tmp-pytest-conductor/head-to-head/results/2026-09-14T11-05-28Z/v1.3.1-run3/summary.json

Every number above is derived from those files and from
nothing else.
