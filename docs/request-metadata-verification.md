# Request metadata verification

Base: `27b77ccb4614abab966d6b6550ccf7ab672275d8`.
Interpreter: `/home/gompert/.conda/envs/iq/bin/python`, Python 3.13.14,
pytest 9.1.1. Each invocation sets absolute `PYTHONPATH` to its checkout;
recon printed that checkout's `core.runtime.run.__file__`. Tests use scripted
models and local fixtures, not live providers, platform tokens or deployment.

## Discovery and comparison scope

The initial new 16-module baseline returned 1,038 passed, 17 failed, no skips,
in 176.74 seconds. A scheduling-message crossover briefly overlapped its early
execution with another lane's independent local SDK baseline. No shared files
were changed, but that elapsed time is not used as a sequential comparison.
The final comparison reruns the union sequentially.

All 17 failures were in `test_record_replay.py` and `test_run_corpus.py`, which
were absent from the earlier 1,358-pass task-state affected set. See
`replay-fixture-compatibility.md` for the separate test-only correction. That
earlier count was never a complete repository gate.

The first focused candidate returned 271 passed, one failed, no skips, in
127.90 seconds. Its remaining failure compared equivalent JSON evidence as
strings with different object-key order. The verifier now compares canonical
JSON after exact archive integrity checks, retaining JSON scalar distinctions
such as integer versus floating point. The focused replay/facade retry passed
22 tests in 4.71 seconds, no skips.

## Pre-review affected union

The final baseline and candidate include all modules from both earlier sets:

```sh
tests/test_resume.py tests/test_history_checkpoint.py tests/test_history_recall.py
tests/test_contract.py tests/test_mission_results.py tests/test_result_paging.py
tests/test_swarm.py tests/test_run_swarm.py tests/test_run.py
tests/test_cli_mission_skill.py tests/test_receipt_checkpoint.py tests/test_mission.py
tests/test_facade.py tests/test_conversation_compaction.py tests/test_run_parallel.py
tests/test_task_state.py tests/test_usage_telemetry.py tests/test_request_telemetry.py
tests/test_usage_channel.py tests/test_context_window.py tests/test_backends.py
tests/test_local_backend.py tests/test_record_replay.py tests/test_run_corpus.py
tests/test_answer_continuation.py tests/test_output_profiles.py tests/test_model_state.py
```

The candidate additionally includes `tests/test_call_metadata.py`. The command
is the named interpreter's `-m pytest`, with `-q -ra --tb=short
--show-capture=no -p no:cacheprovider -o addopts=`, a unique private basetemp
under TAIPAN's `.operator/request-telemetry-pytest`, and JUnit output there.
The shell removes ambient TAIPAN token and output-profile variables. Each
broad process has a 900-second bound. Local fixture sockets require ordinary
approved execution outside the restricted socket sandbox.

The sequential frozen baseline completed with **2,038 passed, 17 failed,
zero skips**, in **503.12 seconds**. The failure nodes exactly match the
historical fixture list above; none of the earlier task-state affected nodes
failed. The private report is `base-union.xml` under the directory above.
The final frozen candidate completed with **2,108 passed, zero failures,
zero skips**, in **513.57 seconds**. Its private report is
`candidate-union.xml`. All 2,055 baseline cases remain selected; the additional
53 are 48 metadata cases and five negative receipt-comparison cases. The
preceding final new-case preflight passed 54 tests in 5.19 seconds, including
the fresh review replay comparison. Both broad process handles terminated
before the sequential pytest slot was released to the next lane.

## Static comparison

The nine changed production modules were checked with
`mypy --follow-imports=skip --ignore-missing-imports --no-incremental` on each
checkout. The baseline reports 16 errors and candidate 14: the three existing
optional-plain-call warnings become one at the shared call owner. Existing
run/context typing and missing requests-stub warnings remain; this is not a
claim that the whole harness is type-clean. The base metadata and usage owners
independently pass mypy with no issues.

Ruff passes for the remaining changed production modules, new tests and
helpers. Run, swarm and the historical corpus test retain the same 19 baseline
diagnostics, identical after normalizing source line offsets. No existing
diagnostic was suppressed. `git diff --check` is clean.

## What these checks do not establish

No live model, Mission Pane rendering, all-provider retry visibility, measured
tokenizer occupancy, complete nested-tool usage, deployment, or release is
claimed. Coverage and unknowns are part of the additive record contract.

## Review correction — affected-path gate

Review found that Local's transport counter ran before header preparation, and
that the new staged request wrapper refitted initial synthesis output which the
existing assembler had already fitted. Both are corrected without changing the
fitting policy: headers resolve before counting an attempted transport, and the
initial synthesis records its existing prepared prompt without a second fit.
Preassembly compaction is explicitly unobserved. The all-green union above is
evidence for the pre-review source, not this corrective change.

Six new cases cover header preparation failure in streaming/nonstreaming modes,
and real synthesis assembly with/without a window and with/without grounding
repair. They check the exact prepared prompt, the number of fit calls, unchanged
repair fitting, request budget, one spend per call and repair parent identity.

The pre-review characterization substituted only `LocalBackend._post`,
`SwarmRunner._plain_call` and `SwarmRunner._synthesize` from `659258b` into the
loaded classes in memory, then selected the six new cases. No source file was
mutated. It produced **four expected failures and two passes**, no skips, in
**0.40 seconds**: both header cases counted an unattempted transport and both
windowed synthesis cases fitted twice. The no-window cases already passed.
The early module imports produced one harmless pytest assertion-rewrite warning
for anyio. Private report: `review-base.xml`.

The corrective source then passed **389 tests, zero failures, zero skips**, in
**11.79 seconds**, using the same Python 3.13.14 interpreter and absolute
worktree import verified above. The gate selected `test_call_metadata.py`,
`test_local_backend.py`, `test_swarm.py`, `test_run_swarm.py` and
`test_request_telemetry.py`, with the same pytest options above and a 360-second
process bound. Private report: `review-candidate.xml`. The full 2,108-case union
was not repeated for this bounded correction. Both handles were terminal before
the slot was released for paired platform integration.

Ruff and diff-whitespace checks pass for the corrective tests and Local source.
The two changed production modules retain their existing mypy diagnostics
(requests stubs, Local `last_tool_calls` annotation and the staged optional plan);
the correction adds no new type diagnostics. No deployment or live call occurred.
