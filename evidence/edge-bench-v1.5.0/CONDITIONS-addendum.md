# CONDITIONS addendum — session notes (benchmark agent, 2026-09-15)

Facts observed by the benchmark session that the main CONDITIONS.md does not carry:

- **Serve-line deviation from the brief**: `--disable-log-requests` was dropped —
  removed in vLLM 0.25.0 (`--help` does not declare it; request logging is now
  opt-in via `--enable-log-requests`, so the deleted flag's intent — logging off —
  is the 0.25 default). Every other flag of the briefed launch line verified
  declared by `vllm.entrypoints.openai.api_server --help` before serving.
- **Weights provenance**: the original unauthenticated HF download
  (HF_HOME=~/bench/models, snapshot 6cee5e81) rate-limit-stalled twice
  (~15 min with zero blob growth, self-recovered once, stalled again) and was
  replaced by an rsync of the pool's served snapshot from jl-i into
  ~/bench/models/gpt-oss-20b/ (root files only, 13,761,316,904 bytes across
  three shards, source mtimes preserved). Same digest production serves —
  a conditions improvement over the HF pull. The partial HF cache remains at
  ~/bench/models/hub/ (incomplete; not used).
- **Endpoint overlap, stated**: a PATH-fix smoke rerun
  (`~/bench/smoke2`, mission `three_receipts_one_total`, baseline arm, exit=0)
  ran against the same endpoint from ~14:31:50Z to 14:32:39Z, overlapping the
  final ~1–2 minutes of the full ablation (done marker 14:33:28Z). At
  `--max-num-seqs 8` this can only have added queueing latency to a handful of
  the last arm's wall-clock readings; pass/fail verdicts are unaffected. The
  first smoke attempt (~/bench/smoke, exit=1, "could not spawn 'judais'" —
  PATH did not carry the venv bin) never reached the model.
- **GPU release**: verified 14:39:22Z — 4 MiB used, 0% util, P8/10W, zero
  listeners on :8000, no compute processes.
- **Node is pool-joined**: taipan-edge rejoined the TAIPAN pool during this
  window; no foreign compute process was ever observed on the card (checked
  before serve and at teardown).
- **Interpreter caveat, restated**: this whole table is the EDGE interpreter
  row — RTX 5090 / py3.12.14 / vLLM 0.25.0 / edge venv resolver set (47 pkgs,
  ~/bench/venv-freeze.txt), NOT production's 58 pins. Arms are internally
  paired and valid against each other; never read beside the pool's L4 rows.
