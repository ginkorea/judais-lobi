# judais-lobi v1.4.0 — release ablation (benchmark: v1.2.0)

Generated 2026-09-14T00:57:26-10:00 from 3 eval run(s).

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

**v1.4.0 improves on 0 of the three criteria and regresses on 3**, against the ledger's champion v1.2.0.

* **accuracy — regresses.** v1.2.0 96.7% (29/30) vs v1.4.0 83.3% (25/30); 13.4 pt to v1.2.0.
* **completion — regresses.** v1.2.0 100.0% vs v1.4.0 83.3% of missions ran every turn to `finished`; 16.7 pt to v1.2.0.
* **wall clock — regresses.** v1.2.0 48.47 s vs v1.4.0 77.16 s per mission; 28.69 s to v1.2.0, outside the 22.03 s run-to-run spread. Measured on a different day from the champion's row, so this criterion is the weakest of the three here: pool load, card occupancy and the served model's warmth all move it and none of them is judais-lobi. The conditions of both runs are recorded in LEDGER.md.

## Aggregate, per version

| version | runs | accuracy | passed | completion | mean wall/mission | spread | mean total |
|---|---|---|---|---|---|---|---|
| v1.4.0 | 3 | 83.3% | 25/30 | 83.3% | 77.16 s | ±9.6 s | 771.5 s |

The benchmark row, from the ledger — v1.2.0, measured 2026-09-13T19:10:49-10:00:

| version | runs | accuracy | passed | completion | mean wall/mission | spread | mean total |
|---|---|---|---|---|---|---|---|
| v1.2.0 | 3 | 96.7% | 29/30 | 100.0% | 48.47 s | ±22.03 s | 484.7 s |

Source: `/home/gompert/data/workspace/TAIPAN/plan/RELEASE_EVIDENCE/judais-head-to-head/2026-09-14-v1.1.3-vs-v1.2.0-summary.json`. That row was not re-measured for this report and no number in it was edited.

## Conditions this run was measured under

* **date** — 2026-09-14T10:14:11Z
* **host** — jl-i (taipan-compute)
* **release** — v1.4.0
* **tier** — baseline
* **runs** — 3
* **arm_sha** — v1.4.0 @ 98b597e
* **venv_parity** — 58 package(s) identical to production — only judais-lobi differs
* **harness** — mission_eval.py sha 3860e8cf730ea87a
* **service_tree** — newest file in the service tree: 2026-09-14T00:09:16Z
* **production** — production's pane is up (recorded as a condition; never an arm, never touched)
* **broker_before** — status ok, 0 running, 0 queued
* **cards_before** — all cards idle: 0, 0 MiB;1, 0 MiB;2, 0 MiB;3, 0 MiB
* **other_vllm** — no vLLM running; this pane's lease will be the only one
* **endpoint** — http://127.0.0.1:55181/v1
* **cards_during** — 0, 19544 MiB;1, 19544 MiB;2, 0 MiB;3, 0 MiB;
* **lease_verified** — the two cards are this arm's own lease, not production's: the broker went 0 running -> 1 running after this pane's POST /api/model; the vLLM process runs as tj-jgompert (a taipan-jobs principal); the endpoint was published to /var/lib/taipan/mission-1.4.0/model/model.url; production's /var/lib/taipan/mission/model/model.url is empty. The pane's own /api/model detail string reads "already serving - this pane took no lease of its own", which is its wording for finding the session up on the readiness probe and is NOT evidence of adoption.
* **cards_leased** — 0 and 1 of 4 L4s (the 2026-09-14 v1.1.3-vs-v1.2.0 row's candidate arm was reported on cards 2 and 3; same hardware, different pair)
* **release_at_stage3** — FAILED as first reported: :8771 still listening, 2 cards still at 19630 MiB, 1 vLLM up. Cause: the pane pid the runner holds is the micromamba WRAPPER, and killing it left `python -m taipan.mission` (3882283) and the loaner session (3882960) alive. ablate.sh's cleanup now signals the process group and sweeps by cmdline-guarded pid; the stage-3 check is what caught this and it was not silent.
* **release_confirmed** — released by hand immediately afterwards, by pid, each pid's /proc cmdline matched first (no pkill -f): 3882283 (--state /var/lib/taipan/mission-1.4.0) and 3882960 (loaner_session.py). After: :8771 closed, both pids gone, no vLLM process, nvidia-smi 0/0/0/0 MiB on all four L4s, broker 0 running / 0 queued / 0 sessions.
* **production_after** — untouched throughout; :8770 listening and /api/health answering, pids 2813859/2813863 never signalled

Recorded because wall clock is only readable against them.

## Per run

| label | version | tier | passed | accuracy | completed | completion | mean wall | median wall | sum elapsed | start→finish |
|---|---|---|---|---|---|---|---|---|---|---|
| v1.4.0-run1 | v1.4.0 | baseline | 7/10 | 70.0% | 8/10 | 80.0% | 81.69 s | 36.08 s | 816.85 s | 816.0 s |
| v1.4.0-run2 | v1.4.0 | baseline | 8/10 | 80.0% | 8/10 | 80.0% | 77.69 s | 38.08 s | 776.88 s | 777.0 s |
| v1.4.0-run3 | v1.4.0 | baseline | 10/10 | 100.0% | 9/10 | 90.0% | 72.09 s | 50.07 s | 720.87 s | 721.0 s |

`sum elapsed` is the scenarios only. `start→finish` additionally
carries whatever the harness did around them, and on the first eval
of a session that includes waiting for a cold model — which is why
the wall-clock verdict above is taken on `elapsed_s` and not on this
column.

## Per mission, per run

| scenario | v1.4.0-run1 | v1.4.0-run2 | v1.4.0-run3 |
|---|---|---|---|
| coref | FAIL 292s ! | FAIL 52s | PASS 84s |
| correction | PASS 28s | PASS 36s | PASS 32s |
| deepresearch | PASS 12s | PASS 24s | PASS 20s |
| empty | PASS 16s | PASS 16s | PASS 16s |
| followup_plot | PASS 92s | PASS 260s ! | PASS 152s |
| governed | FAIL 32s | PASS 40s | PASS 60s |
| install | PASS 52s | PASS 32s | PASS 32s |
| pivot | PASS 40s | PASS 64s | PASS 64s |
| plot | FAIL 220s ! | FAIL 220s ! | PASS 220s ! |
| web | PASS 32s | PASS 32s | PASS 40s |

Each cell is `outcome elapsed_s`, with `!` where a turn did not end
`finished`.

## Provenance

* `v1.4.0-run1` — http://127.0.0.1:8771, results/2026-09-14T10-14-05Z/v1.4.0-run1/summary.json
* `v1.4.0-run2` — http://127.0.0.1:8771, results/2026-09-14T10-14-05Z/v1.4.0-run2/summary.json
* `v1.4.0-run3` — http://127.0.0.1:8771, results/2026-09-14T10-14-05Z/v1.4.0-run3/summary.json

Every number above is derived from those files and from
nothing else.
