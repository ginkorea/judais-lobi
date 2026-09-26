# Portable checkpoint candidate verification — 26 September 2026

Owning repository: judais-lobi; branch `codex/portable-checkpoint-20260926`,
based on `d0b5cdf`. Not vendored into TAIPAN or deployed.

Interpreter `/home/gompert/.venvs/taipan/bin/python`, Python **3.13.14**,
pytest **9.1.1**. `core.__file__` resolved to the original repository's linked
worktree at
`/home/gompert/data/workspace/TAIPAN/.worktrees/judais-portable-checkpoint/core/__init__.py`.
Absolute `PYTHONPATH` and `python -m pytest` were used; TAIPAN credentials were
unset. No live model, pool, S3 or service was contacted.

Final six-module gate: **284 passed, zero skips, 31.40 seconds**:

```
tests/test_portable_checkpoint.py
tests/test_receipt_checkpoint.py
tests/test_history_checkpoint.py
tests/test_task_state.py
tests/test_resume.py
tests/test_history_recall.py
```

The new module contributes **45 cases**: exact original receipt bytes/identities,
single/multiple source runs, history, detached/no-side-effect validation,
corruption and omission, scope, unreferenced material, bounds, malformed task
collections, late-known credentials on receipt/history surfaces, credential
fields in metadata/events, and equivalence with existing local readers.
Ruff, diff whitespace checks and mypy on all four changed production modules
passed. This is targeted harness regression coverage, not the full platform gate.

Two process-local negative controls independently bypassed source scope and
receipt hash binding. Each produced the expected `DID NOT RAISE ValueError`
failure in its corresponding corruption test. Source files were not mutated.

Local evidence (TAIPAN workspace, ignored test artifacts):
`test-artifacts/judais-portable-checkpoint-final.xml`,
`test-artifacts/judais-portable-mutation-scope.xml`, and
`test-artifacts/judais-portable-mutation-hash.xml`.

Two initial sandbox runs stalled at the existing scripted-model restart test.
The diagnostic stack showed an asyncio selector wait; both were explicitly
stopped (exit 130), not counted as passing. Outside the sandbox, the same
four-module selection passed 168 cases in 21.67 seconds, followed by the final
expanded gate above. No test was skipped to obtain the final result.

## Native capture and cross-runtime command — 26 September follow-up

The same interpreter (Python 3.13.14 at
`/home/gompert/.venvs/taipan/bin/python`) and absolute source import passed
**323 cases, zero skips**, across the six modules above plus
`test_checkpoint_capture.py` and `test_checkpoint_export.py` (41.09 seconds).
Receipt bytes remain unchanged and are excluded from dataclass representations.
Ruff and changed-source mypy passed before the final test run.

The new filesystem adapter captures scoped dependency closures with byte/file/run
bounds, non-following descriptor reads, change detection and nonblocking native
run locks. It creates nothing. Unknown selected-run files refuse; unrelated
conversation runs can be admitted without invalidating the selected capture.
The private-pipe command makes the same collector usable from another runtime,
with strict request fields, input bounds, a fixed refusal and no partial-success
stdout. Current policy, authentication and transcript admission exclusion remain
the caller's responsibility.

Both additional process-local mutations were detected by an expected
`DID NOT RAISE ValueError`: removing final identity verification and removing
native run-lock acquisition. No production source was rewritten for mutations.
Local evidence: `.operator/native-capture-final.xml`; mutation runner:
`.operator/native_capture_mutations.py`.

An actual synthetic Mission-to-harness subprocess acceptance imported both
candidate worktrees and captured **14 exact original parts**, across two turns
and two dependent runs, including history and released native locks excluded
from the bundle. A fresh ThreadStore returned an identical snapshot. The
reproducer is `.operator/mission_checkpoint_acceptance.py` in this worktree.
No live model, platform service, network, credentials or deployment was involved.

One sandbox regression run was interrupted (exit 130) after stalling in an
existing local model fixture. The bounded final run allowed synthetic loopback
networking and passed without deselection or skip. It is not evidence of a
deployed runtime or completed replication.

Still required: current export-governance checks, publication/recovery and
offline conflict handling, plus integration release/pin verification. See
[integration boundaries](portable-checkpoints.md).
