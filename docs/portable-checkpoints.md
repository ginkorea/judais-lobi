# Portable checkpoint validation (source candidate)

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

## Integration responsibilities still outside this validator

The caller must capture a coherent, quiescent filesystem generation using
bounded reads that refuse symlinks and detect changes. It must inventory the
entire source layout before deciding what constitutes a bundle. This validator
cannot detect a file the caller never supplied, and scope labels do not
authenticate the caller. Current identity, source-data handling restrictions,
local-only policy, destination authorization, transport, durable publication and
cold recovery remain the platform's responsibilities. It does not activate a
restored run or establish S3 durability. No deployment or pin update accompanies
this source candidate.
