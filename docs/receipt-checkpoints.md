# Private typed receipt checkpoints

A durable Mission run now checkpoints each dispatched tool result in the
existing RunStore directory, before emitting its `tool_result` record. The
record's optional `receipt` field is a reference, not another payload channel.
Consumers that do not use checkpoints may ignore it. Non-durable runs and
legacy logs without references retain their existing behavior.

The checkpoint keeps structured JSON types, complete output, arguments, exit
status, quotation provenance, and the original run/branch/step/call/handle
identity. A random receipt ID avoids collisions between staged children that
both called their first result `r1`. A staged replay can use new local handles;
`StoredResult.origin` preserves the original identity rather than pretending
the new handle was the source's identity.

Files are atomic replacements through `core.durable.atomic_write_text`, with
0600 mode, same-directory temporary files and file fsync. There is no new
directory-fsync guarantee. A ready reference is emitted only after replacement.
A failure leaves the live result usable in memory and an unavailable reference.
A file written before the process dies but never referenced by its event log
is not replayed. No file scan is used to infer execution or to repeat an action.

Credentials are removed before serialization, using the shared redactor.
String values are traversed recursively; credential-named scalar fields are
masked (numeric/boolean credentials become null). Other JSON types remain
unchanged. Changed paths are recorded privately, and restored origins identify
redacted receipts. A credential in a structural key or receipt identity makes
that checkpoint unavailable instead of silently renaming a field or handle.
This is recognizable/known-secret hygiene, not a claim to detect every arbitrary
opaque secret. Existing event `output`/`arguments` policy is unchanged.

Resume binds the event to its fixed-path file, byte count, SHA-256 digest and
embedded run/call identity. These checks detect corruption or mixed snapshots;
they do not authenticate a record against someone controlling both the event
log and run directory. Readers reject paths supplied in metadata. One receipt
is capped at 64 MiB for bounded archive reads: exceeding this degrades checkpoint
availability, never refuses the live tool call or shortens its in-memory result.
This bounds serialized archive output and archive reads, not allocations while
parsing an already-large in-memory result. It is not a hard memory guarantee.

Missing, malformed or incompatible checkpoints keep the event's existing text
available and explicitly report lost structured fields. Valid redacted copies
are not represented as byte-identical originals; a restored identity value at
a redacted path is unavailable, not the redaction marker. Quote reads remain
outside grounding evidence even after restart. Rebuilding never dispatches tools.
Rereading a redacted receipt retains that provenance in both its result and
checkpoint, including after another process restart. Partial recovery reports
only the count of unavailable receipts; healthy receipts remain retrievable.

This is a prerequisite for typed current-task/progress state, not that complete
feature. Passing reference sets between distinct hosted turns still needs the
thread/CLI handoff; requested/delivered counts and compaction state must later
refer to these source receipts, not model-reported completion totals.

## Next connected slice (not implemented here)

1. Add an immutable current-task value beside Run's existing objective, with
   the newest literal owner objective and separately attributed interpreted
   deliverable/count fields. Initialize it in the public runner; update it on
   the existing injected-objective path, not by parsing historical quotations.
2. Attach ordered reference sets to actual stored receipts through explicit
   record paths and source identities. Keep source-run/receipt identity separate
   from a new run's local r-handle. Derive retrieved/processed/delivered counts
   from the recorded sets and confirmed output, retaining unknown counts when
   coverage is not supplied. A model's asserted completion count is not evidence.
3. Give MissionWindow a bounded projection of that state: objective, unresolved
   work, selected skills, ordered references and receipt locators. Keep payloads
   in the existing result owner; compaction removes repeated prompt copies, not
   retrievable evidence. Test a follow-up to item #2 after forced compaction.
4. Extend the answer boundary with complete/partial/interrupted status and
   measured coverage when available. Missing delivery must yield continuation
   or an honest partial answer, never replay of successful side effects merely
   to recreate prose. Preserve public CLI behavior and older no-state callers.
5. Add an explicit owner/thread-bound state handoff in the hosted adapter and
   public CLI/library input. Each hosted follow-up currently starts a new run;
   resume within one run alone does not solve cross-turn retention. Validate
   source references and quotation trust before restoring, with no platform
   tool names or dataset-specific completion logic inside the harness.
