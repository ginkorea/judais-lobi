# judais-lobi v1.1.3 vs v1.2.0 — head to head

Generated 2026-09-13T19:10:49-10:00 from 6 eval run(s).

The Mission Agent behind TAIPAN's Mission Pane, on the pool, over the
same mission set, against one served `openai/gpt-oss-20b` shared by
both panes. Only the judais-lobi source differs: the two venvs'
entire transitive dependency set was pinned to the same versions, and
one copy of `mission_eval.py` drove both arms. v1.2.0 ran with
`--cognition` OFF unless a row says otherwise.

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

**v1.2.0**, on 2 of the three criteria to v1.1.3's 0.

* **accuracy — v1.2.0.** v1.1.3 80.0% (24/30) vs v1.2.0 96.7% (29/30); 16.7 pt to v1.2.0.
* **completion — v1.2.0.** v1.1.3 96.7% vs v1.2.0 100.0% of missions ran every turn to `finished`; 3.3 pt to v1.2.0.
* **wall clock — tie.** v1.1.3 55.41 s vs v1.2.0 48.47 s per mission: a 6.94 s gap inside the 38.43 s spread the arms showed across their own runs, which is not a difference this measurement can see.

## Aggregate, per version

| version | runs | accuracy | passed | completion | mean wall/mission | spread | mean total |
|---|---|---|---|---|---|---|---|
| v1.1.3 | 3 | 80.0% | 24/30 | 96.7% | 55.41 s | ±38.43 s | 554.1 s |
| v1.2.0 | 3 | 96.7% | 29/30 | 100.0% | 48.47 s | ±22.03 s | 484.7 s |

## Per run

| label | version | tier | passed | accuracy | completed | completion | mean wall | median wall | sum elapsed | start→finish |
|---|---|---|---|---|---|---|---|---|---|---|
| v1.1.3-run1 | v1.1.3 | baseline | 6/10 | 60.0% | 9/10 | 90.0% | 75.69 s | 52.07 s | 756.86 s | 757.0 s |
| v1.1.3-run2 | v1.1.3 | baseline | 10/10 | 100.0% | 10/10 | 100.0% | 53.27 s | 40.06 s | 532.75 s | 533.0 s |
| v1.1.3-run3 | v1.1.3 | baseline | 8/10 | 80.0% | 10/10 | 100.0% | 37.26 s | 42.05 s | 372.59 s | 373.0 s |
| v1.2.0-run1 | v1.2.0 | baseline | 10/10 | 100.0% | 10/10 | 100.0% | 60.49 s | 54.07 s | 604.87 s | 605.0 s |
| v1.2.0-run2 | v1.2.0 | baseline | 9/10 | 90.0% | 10/10 | 100.0% | 46.47 s | 50.05 s | 464.71 s | 464.0 s |
| v1.2.0-run3 | v1.2.0 | baseline | 10/10 | 100.0% | 10/10 | 100.0% | 38.46 s | 38.06 s | 384.63 s | 384.0 s |

`sum elapsed` is the scenarios only. `start→finish` additionally
carries whatever the harness did around them, and on the first eval
of a session that includes waiting for a cold model — which is why
the wall-clock verdict above is taken on `elapsed_s` and not on this
column.

## Per mission, per run

| scenario | v1.1.3-run1 | v1.1.3-run2 | v1.1.3-run3 | v1.2.0-run1 | v1.2.0-run2 | v1.2.0-run3 |
|---|---|---|---|---|---|---|
| coref | FAIL 44s | PASS 68s | PASS 64s | PASS 72s | PASS 56s | PASS 52s |
| correction | PASS 32s | PASS 28s | FAIL 8s | PASS 36s | PASS 24s | PASS 28s |
| deepresearch | FAIL 20s | PASS 16s | PASS 16s | PASS 20s | PASS 52s | PASS 8s |
| empty | PASS 96s | PASS 12s | PASS 48s | PASS 20s | PASS 12s | PASS 20s |
| followup_plot | FAIL 224s ! | PASS 180s | FAIL 8s | PASS 80s | FAIL 56s | PASS 72s |
| governed | FAIL 132s | PASS 60s | PASS 36s | PASS 112s | PASS 36s | PASS 52s |
| install | PASS 28s | PASS 40s | PASS 52s | PASS 32s | PASS 48s | PASS 40s |
| pivot | PASS 92s | PASS 40s | PASS 56s | PASS 128s | PASS 84s | PASS 36s |
| plot | PASS 60s | PASS 52s | PASS 56s | PASS 72s | PASS 76s | PASS 44s |
| web | PASS 28s | PASS 36s | PASS 28s | PASS 32s | PASS 20s | PASS 32s |

Each cell is `outcome elapsed_s`, with `!` where a turn did not end
`finished`.

## Provenance

* `v1.1.3-run1` — http://127.0.0.1:8770, /home/gompert/data/tmp-pytest-conductor/head-to-head/results/2026-09-14T04-16-28Z/v1.1.3-run1/summary.json
* `v1.1.3-run2` — http://127.0.0.1:8770, /home/gompert/data/tmp-pytest-conductor/head-to-head/results/2026-09-14T04-16-28Z/v1.1.3-run2/summary.json
* `v1.1.3-run3` — http://127.0.0.1:8770, /home/gompert/data/tmp-pytest-conductor/head-to-head/results/2026-09-14T04-16-28Z/v1.1.3-run3/summary.json
* `v1.2.0-run1` — http://127.0.0.1:8771, /home/gompert/data/tmp-pytest-conductor/head-to-head/results/2026-09-14T04-16-28Z/v1.2.0-run1/summary.json
* `v1.2.0-run2` — http://127.0.0.1:8771, /home/gompert/data/tmp-pytest-conductor/head-to-head/results/2026-09-14T04-16-28Z/v1.2.0-run2/summary.json
* `v1.2.0-run3` — http://127.0.0.1:8771, /home/gompert/data/tmp-pytest-conductor/head-to-head/results/2026-09-14T04-16-28Z/v1.2.0-run3/summary.json

Every number above is derived from those files and from
nothing else.
