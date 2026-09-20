# Historical replay fixture compatibility

The committed corpus predates run-local task state and private typed receipts.
The expanded request-telemetry baseline exposed 17 failures on untouched
`27b77cc`: four fresh-versus-historical prompt comparisons, nine full-stream
comparisons and four event-field shape comparisons. This is a test-coverage
gap in the previous task-state verification, not a previously passing full
repository gate: its 16-module affected set did not include
`test_record_replay.py` or `test_run_corpus.py`.

The four corpus recording helpers now explicitly request `--no-task-state`
because they reproduce historical prompts. The general CLI helper and default
CLI/library task-state, replay-mode and compaction tests remain unchanged.
No historical recording is regenerated or edited.

Receipt comparison reuses the existing facade verifier, extracted to one test
helper. Before normalizing freshly minted locators, it verifies archive byte
count and SHA-256, uses the production loader to bind the archive to the event,
and checks source run, receipt, branch, step, call, handle, tool, arguments,
status and trust flags. Historical payloads are compared against the committed
tool I/O log: full text, stderr and structured JSON, including scalar types.
JSON object key order is not evidence; canonical JSON comparison preserves
scalar types while allowing replay's legitimate key-order canonicalization.
Only after these checks does the expected historical event gain the validated
receipt descriptor. No receipt or telemetry field joins the exclusion list.

Explicit negative cases change text, JSON scalar type, source branch, trust
flag and digest and require the comparator to reject each change. The existing
facade corruption guard remains active. Fresh/default recording and replay
still compare archived receipt contents, rather than disabling persistence.

The sequential 27-module baseline on Python 3.13.14 returned 2,038 passed and
the same 17 failures, no skips, in 503.12 seconds. The combined candidate plus
J8 metadata tests returned 2,108 passed, no failures or skips, in 513.57 seconds.
The detailed command and broader evidence are in
`request-metadata-verification.md`; this is a test-only compatibility
correction, separate from the J8 production contract.
