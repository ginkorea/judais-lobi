# Portable checkpoint capture and validation (source candidate)

`core.runtime.portable_checkpoint.PortableCheckpointValidator` validates a
captured run bundle without opening the filesystem, resuming a run, calling a
tool, or minting replacement receipts. It belongs to judais-lobi because this
package owns the checkpoint schemas. Integrators should not copy those schemas
into a platform-specific exporter.

Call `validate(scope, handoffs, files)`, where `scope` is the authenticated
caller's `TaskScope`, `handoffs` contains the `TaskHandoff` pointers being kept,
and `files` maps paths relative to the runs directory to immutable bytes. The
result contains the original bytes and their SHA-256 digests. Existing receipt
IDs, receipt hashes, ordered references and immutable checkpoint hashes do not
change. Stored configuration is historical information, not execution authority.

Validation requires each source run's metadata, contiguous complete event log,
mutable task state, all supplied immutable task states, event-bound receipts,
and history when declared by metadata. Every run must be reachable from a
supplied handoff through source references. References must resolve to the
original successful, unquoted, unredacted receipt and the exact selected value.
Scope is checked on every task state, including earlier source runs.

Duplicate JSON keys, non-finite numbers, unknown paths, traversal, locks,
heartbeats, orphan receipts, missing evidence and mismatched hashes refuse the
whole bundle. Aggregate byte, file and run limits apply before parsing. No
component is silently omitted. Newly recognized credentials also refuse: a
redacted rewrite cannot retain the original receipt's identity. This is a
strict validator; refusal is not an instruction to repeat earlier tool actions.

Existing local readers now share their detached parsers:

- `ReceiptCheckpoint.decode(run_id, event_record, raw)` keeps normal local
  receipt redaction behavior; it is not by itself clearance to export raw bytes.
- `TaskCheckpoint.decode(run_id, raw, digest=...)` validates the envelope;
  `decode_task_state(document, scope)` validates state without importing sources.
- `history_checkpoint.decode(run_id, run_meta, raw)` verifies history binding.

## Native capture and separate-runtime command

`NativeCheckpointCapture(runs_root, limits).capture(scope, handoffs)` in
`core.runtime.checkpoint_capture` captures the closure using descriptor-relative,
bounded reads. It refuses symlinks, nonregular or multiply linked files,
foreign-owned/group-writable data, unexpected selected-run files, changed
contents and replaced directories. It holds existing native run locks without
blocking; released locks are not exported, and missing locks are not created.
Run locks alone are insufficient: the caller must exclude new workers for the
selected conversation throughout the call. Unrelated conversations may add runs
without invalidating capture. Enrolled parent directories and the service account
remain trusted. The result is validated by the same detached validator above.

Where the platform and harness use different Python environments, invoke
`python -m core.runtime.checkpoint_export` using the explicitly enrolled harness
interpreter. Pass this versioned JSON request through a **private stdin pipe**:

```json
{
  "version": 1,
  "root": "/absolute/private/runs",
  "scope": {"owner": "authenticated-principal", "thread": "conversation-id"},
  "handoffs": [],
  "limits": {"max_bytes": 67108864, "max_files": 4096, "max_runs": 256}
}
```

Replace the empty example `handoffs` with the actual source-owned pointer
records; an empty selection refuses. Request input is bounded to 2 MiB and limits
cannot exceed the defaults shown. The host must deduct transcript and pointer
bytes from its overall budget before selecting the run-byte bound. Successful
stdout is one JSON object: `version`, matching `scope`, and `parts` containing
`path`, `content_b64`, and `sha256`. These are private captured bytes, **not log
output**. The caller must bound response reads and subprocess duration, check
scope/digests/paths, and keep admission excluded until its whole snapshot is
complete. No partial success is emitted for a validation refusal (exit 2 and a
fixed error on stderr). No network, credentials or destination are used by this
command. Unknown/new run files require a source-owned schema update, not omission.

## Integration responsibilities still outside capture

The caller must capture transcript and pointer files coherently with the native
run closure, preserving pointer filenames and bytes and checking their admission
sequences against the captured conversation frontier. A detached validator
cannot detect a file the caller never supplied, and scope labels do not
authenticate the caller. Current identity, source-data handling restrictions,
local-only policy, destination authorization, transport, durable publication and
cold recovery remain the platform's responsibilities. It does not activate a
restored run or establish S3 durability. No deployment or pin update accompanies
this source candidate.
