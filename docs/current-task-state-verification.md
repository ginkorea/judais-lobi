# Current-task state verification

Base: `b7d1db9410142b424f9c6571dd9e782e6e024d20`.

The interpreter is `/home/gompert/.conda/envs/iq/bin/python`, Python 3.13.14,
pytest 9.1.1. Each comparison sets an absolute `PYTHONPATH` to its own checkout;
recon verified `core.runtime.run.__file__` points into that checkout. These are
scripted-model/local-fixture tests, not live Mission Pane acceptance.

## Frozen baseline

The 15-module affected set returned **1,295 passed, 1 failed**, no skips, in
326.02 seconds. The existing failure was
`test_facade.py::TestTheCLIIsAClientOfThis::test_the_two_streams_are_the_same_stream`:
the CLI fixture enabled durable receipt storage while its library peer did not.
Random receipt locators therefore differed before this task-state change.

The separate facade test repair configures equivalent storage and context
windows, checks each archive's bytes/digest/source identity and trust flags,
and compares the recovered payloads. It normalizes only verified random
locators and validated request clocks using the existing telemetry helper.
Disabled-storage/no-state parity remains a separate comparison.

## Commands

From each checkout, with that checkout's absolute path in `PYTHONPATH`:

```sh
/home/gompert/.conda/envs/iq/bin/python -m pytest \
  tests/test_resume.py tests/test_history_checkpoint.py tests/test_history_recall.py \
  tests/test_contract.py tests/test_mission_results.py tests/test_result_paging.py \
  tests/test_swarm.py tests/test_run_swarm.py tests/test_run.py \
  tests/test_cli_mission_skill.py tests/test_receipt_checkpoint.py tests/test_mission.py \
  tests/test_facade.py tests/test_conversation_compaction.py tests/test_run_parallel.py \
  -q -rs --tb=short -p no:cacheprovider -o addopts= \
  --basetemp=<private-unique-comparison-directory>
```

The candidate additionally includes `tests/test_task_state.py`. The shell
wrapper removes platform credential and output-profile environment variables
and bounds each broad process to 600 seconds. Local execution requires normal
asyncio/socket support: the restricted sandbox diagnostic hung in the selector
despite a completed worker and terminated at its 40-second bound. That is
recorded separately, not counted as a product regression or a passing test.

## Focused checks and limitations

The first focused task-state/facade pass returned **57 passed, 3 failed** in
7.56 seconds: all 39 task-state cases passed, while facade comparisons exposed
unequal window/telemetry fixtures and an old CLI catalogue expectation. Those
fixture differences were corrected rather than dropping receipt or telemetry
fields. Subsequent review also found and corrected native CLI namespace
notification when the task tool registers; dedicated first-request and rollback
regressions cover it.

The first broad candidate returned **1,331 passed, 8 failed**, no skips, in
337.79 seconds. All eight failures were CLI expectations for the newly offered
task tool or the separate assistant state projection. Updated assertions retain
literal-user ordering and identify native assistant tool-call messages by their
actual `tool_calls` field; they do not disable task state. The eight-case
targeted repeat passed in 16.74 seconds.

Review then identified a real active-selection ordering gap: historical
references were being used as the new selection's ordinal list. Three new
characterizations failed before correction (1.28 seconds): switching tasks,
explicit multi-batch accumulation, and retaining an earlier bound list after
an unstaged answer. The corrected focused suite passed **71 tests** in 10.26
seconds, including generic empty/scalar/single/nested-array/whole-array
selection, refresh, deduplication, task switching and private handoff cases.
Recorded CLI mode compatibility then added ten cases, including actual CLI
interruption/resume in both modes and explicit-opt-out/legacy recorded replay
without a live model call. The focused task-state/facade set passed **81 tests**
in 11.33 seconds, with no skips.

## Final frozen candidate

The final 16-module run passed **1,358 tests**, with zero failures, errors or
skips, in **339.639 seconds** (JUnit suite elapsed time). The complete private
JUnit report is `.operator/task-state-pytest/final-repeat.xml` in the parent
TAIPAN workspace. Both the bounded pytest process and its timeout parent were
verified exited before releasing the sequential test slot. The comparison is
1,296 baseline cases (including the recorded facade fixture failure), 60 new
task-state cases and two additional facade cases. No baseline test was removed.

The final command uses the affected set above plus `tests/test_task_state.py`,
with `-q -ra --tb=short --show-capture=no -p no:cacheprovider -o addopts=` and a
private JUnit path and unique basetemp. The source stayed frozen throughout.
Focused Ruff passed again, and `task_state.py` plus `results.py` passed the
two-module mypy check again. `git diff --check` was clean.

This evidence does not claim deployment, cross-host handoff, signing, semantic
truth of model-written item prose, or a hard in-memory allocation bound.
Private host storage and caller-supplied scope remain application obligations.

The bounded static comparison explicitly checks `results.py`, `run.py`,
`mission.py`, and `swarm.py`, plus the new `task_state.py` on the candidate,
with `mypy --follow-imports=skip --ignore-missing-imports --no-incremental`.
Both sides report the same 21 existing errors in run/mission/swarm; the new
task-state and changed result-store modules independently report no issues.
This is no new static error, not a claim that the whole harness is type-clean.
Ruff over all changed existing production modules and tests reports the same
34 pre-existing findings on baseline and candidate (CLI exception chaining,
unused names and existing run/swarm constructs). New task-state/result-store
checks and changed test modules pass their focused Ruff checks. No existing
rule is disabled or allowlisted for this change.
