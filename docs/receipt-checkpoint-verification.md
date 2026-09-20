# Receipt checkpoint verification — 2026-09-19

Scope: private structured tool receipts and process-resume restoration only.
No live model, platform endpoint, deployment, publication or main-branch change
was used for these checks. The next task-state/handoff slice remains described
in [receipt-checkpoints.md](receipt-checkpoints.md).

## Frozen comparison

Interpreter: `/home/gompert/.conda/envs/iq/bin/python`, Python 3.13.14,
pytest 9.1.1. Interpreter/import reconnaissance confirmed `core.runtime.run`
resolved inside the respective checkout, not a sibling installation.

| Source | Checkout | Result |
| --- | --- | --- |
| Exact base `c3381a1` | `TAIPAN/.operator/judais-receipt-base` | 1,021 passed, no skips; 303.61 s |
| Corrected candidate `codex/receipt-checkpoint-sep19` | `TAIPAN/.worktrees/judais-receipt-checkpoint` | 1,066 passed, no skips; 305.43 s |
| Corrected candidate, resume + new receipt tests | Same candidate | 134 passed, no skips; 12.59 s |

Both checkouts are under `/home/gompert/data/workspace`. The candidate adds 45
receipt tests. The two existing loss-characterization tests now explicitly
simulate legacy records without checkpoint references; their loss expectations
remain asserted. Healthy and partially available checkpoints have separate tests.

The initial candidate comparison was 1,056 passed / 1 failed: the staged legacy
test expected raw-output loss even though its newly recorded receipts restored
successfully. The fixture correction above and mixed-recovery warning correction
preceded the final frozen comparison. One earlier restricted local attempt did
not finish within its enforced process timeout (exit 137); it is not counted as a
pass. All final comparison handles completed, and tests ran sequentially in the
team's reserved test slot.

## Reproduction

Run from the candidate checkout; the baseline used the identical list except
`tests/test_receipt_checkpoint.py`, which does not exist on the base. Use distinct
private `--basetemp` directories for base and candidate. These are local synthetic
fixtures, not live acceptance. The approved local test invocation removed live
TAIPAN credential/environment overrides:

```sh
env -u TAIPAN_TOKEN -u TAIPAN_COGNITO_ACCESS_TOKEN \
  -u TAIPAN_PRINCIPAL -u TAIPAN_ROLES -u TAIPAN_SHARING_TAGS \
  -u JUDAIS_LOBI_OUTPUT_PROFILE -u JUDAIS_LOBI_MAX_OUTPUT_TOKENS \
  PYTHONPATH="$PWD" timeout --signal=INT --kill-after=5s 600s \
  /home/gompert/.conda/envs/iq/bin/python -m pytest \
  tests/test_resume.py tests/test_history_checkpoint.py tests/test_history_recall.py \
  tests/test_contract.py tests/test_mission_results.py tests/test_result_paging.py \
  tests/test_swarm.py tests/test_run_swarm.py tests/test_durable.py \
  tests/test_redact.py tests/test_redact_credentials.py tests/test_run.py \
  tests/test_cli_mission_skill.py tests/test_receipt_checkpoint.py \
  -q -rs --tb=short -p no:cacheprovider -o addopts= \
  --basetemp=/home/gompert/data/workspace/TAIPAN/.operator/test-tmp/receipt-checkpoint/candidate-final
```

The baseline used `.../receipt-checkpoint/baseline`; the focused corrected run
used `.../receipt-checkpoint/corrected-focused` and a 90-second bound.

## Assertions exercised

- Ordinary JSON objects, arrays, scalar roots, numeric types, booleans and null
  survive restoration. Source run/receipt/branch/call/handle identity is retained.
- Files are mode 0600. References contain fixed metadata, not payloads, paths or
  credential values. Recognizable/known credentials are scrubbed recursively
  before serialization; unsafe structural keys/identities are not renamed.
- Digest, byte length, run/call binding, missing files, malformed data and wrong
  trust flags are checked. Legacy and mixed-recovery cases remain usable with
  explicit loss reporting, never invented structured evidence.
- Write, fsync, replace, redaction and size failures cannot claim a ready archive.
  A failed checkpoint write does not refuse or redispatch the live tool call.
- JSON/native restart restores field lookup without a second external call.
  Staged children retain distinct source identities despite both using local r1.
- Historical quotations remain excluded from grounding; redacted source data
  stays marked through a local reread and a second process restart.

## Static checks

Ruff is clean for `core/redact.py`, `core/runtime/receipt_checkpoint.py`,
`core/runtime/results.py`, `core/runtime/contract.py`, and the new test module.
The broader `run.py`, `resume.py`, and existing resume-test comparison has the
same five baseline findings (three F541, one B905, one B008); none was introduced.
`git diff --check` is clean.

`mypy --follow-imports=skip --ignore-missing-imports
core/runtime/receipt_checkpoint.py` passes. The same targeted command on the four
existing files `results.py`, `resume.py`, `run.py`, and `core/redact.py` reports the
same nine baseline findings in `run.py`/`resume.py` on base and candidate. This is
a scoped comparison, not a claim that the entire repository is type-clean.

Existing event output/arguments policy is unchanged. These tests establish the
new archive's credential hygiene, not universal secret detection or a rewrite
of historical event storage. The 64 MiB archive limit is not a hard bound on
memory used to parse an already-large in-memory tool result.

## Paired platform check

After fast-forwarding the canonical harness feature branch to `373db7b`, the
TAIPAN candidate `83dd2dc2` passed 393 targeted Mission bridge, boundary, BYOA,
slop and Python-floor checks, with no skips, in 50.38 seconds. Interpreter was
`/home/gompert/.conda/envs/iq/bin/python` 3.13.14; `JUDAIS_LOBI_HOME` pointed to
`.worktrees/judais-mission-reliability`, and reconnaissance resolved
`core.runtime.run` to that checkout. TAIPAN imports resolved to the candidate's
absolute `src` path. Process handle 25242 exited zero.

Modules: `test_mission_bridge.py`, `test_mission_boundary.py`,
`test_byoa_onboards_every_agent.py`, `test_byoa_context_states_what_we_enforce.py`,
`test_no_slop.py`, `test_python_floor.py`. These are local fixture contracts,
not authenticated live acceptance or a production version-pin change.
