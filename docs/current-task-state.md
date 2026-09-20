# Current task state and private handoff

The CLI tracks a task locally by default. `mission_task` lets the model declare
an interpreted plan, select an ordered set from actual structured tool results,
stage source-bound items, and reread references after compaction. It cannot
declare a completed count or turn quoted conversation history into evidence.
`--no-task-state` retains the old no-state CLI path. Existing library callers
remain unchanged unless they provide a `TaskContext`.

## Public library boundary

```python
from judais_lobi import Store, TaskContext, TaskScope, TaskIntent, TaskHandoff

# The application obtains these identifiers from its authenticated session,
# not from an agent message or an instruction embedded in conversation text.
scope = TaskScope(owner=authenticated_owner, thread=private_thread_id)
prior = TaskHandoff.from_record(private_pointer) if private_pointer else None
task = TaskContext(scope=scope, handoff=prior)
store = Store(runs=run_store, run_id=run_id, task=task)
# Pass store to the existing Run constructor, or task_context=task to
# MissionRunner/SwarmRunner. Run.run(latest_literal_input) owns execution.
pointer = task.export_handoff().as_record()  # after the run has settled
```

Scope equality binds state to the caller's selected owner/thread. It is **not
authentication**, a signature, a permission grant, or a substitute for private
application storage. A caller holding an explicit structured requirement may
pass `TaskIntent(deliverable="measured items", requested_count=10,
provenance="caller")`. Never label a model's interpretation as caller input.
`TaskContext.local()` needs no scope or durable store and still supports in-run
tracking and compaction. Without durable receipts, references cannot survive
a process restart.

New CLI run metadata records the enabled/disabled task-state mode. Resume and
replay retain that mode; recordings without the field use the legacy no-state
namespace and seed. An explicit `--no-task-state` cannot silently alter a
recorded enabled run. Metadata never supplies scope or authorization. This
preserves legacy/opt-out replay behavior; it does not claim byte-identical
replay of a scoped cross-turn handoff with dynamic source-reference identities.

## CLI integration

Use the existing `JUDAIS_LOBI_RUNS` environment variable for a stable, private
run-store directory independent of a versioned deployment working directory.
Add these options to the normal mission invocation:

```text
--task-owner <authenticated-owner> --task-thread <private-thread-id>
--task-state-in <private-prior-pointer.json>
--task-state-out <private-this-turn-pointer.json>
```

Omit `--task-state-in` for the first turn. Both scope options are required for
input or output. The input pointer is bounded to 4096 bytes and has this exact
version-1 shape:

```json
{"version":1,"scope":{"owner":"owner-id","thread":"thread-id"},"source_run_id":"run-id","sha256":"64-lowercase-hex-characters"}
```

Only identifiers and a digest travel in the handoff; no receipt payloads or
task prose travel there. The receiving process resolves it through the same
host's private RunStore. This does not implement cross-host export or signing.
Each turn should have its own pointer file. A hosted application must choose
eligible prior turns using its private admission order, so an older turn that
finishes late cannot overwrite a newer objective.

The CLI exports in its run-finalization path. During execution, checkpoints
update `task-state.json` in the run directory. Exports retain immutable
`task-states/<sha256>.json` snapshots: a later dispatch or resume cannot silently
rebind an already exported pointer. Existing atomic 0600 writers are reused;
there is no additional directory-fsync guarantee.

## What the model can do

- `plan`: record model-interpreted deliverable, requested count and remaining
  work descriptions. These are attributed interpretation, not new instructions.
- `select`: provide an actual result handle and an explicit JSON path. An array
  expands in source order by default; `expand=false` binds the selected value
  as one item. There is no guessing of platform-specific keys or row identities.
  The default `mode=replace` replaces the active ordered selection, not the
  archived references or their receipts. `mode=append` deliberately accumulates
  another batch, deduplicating identical bound references in first-selected
  order. Empty, scalar and array selections follow the same rule.
- `stage`: associate item text with an available reference ID. Replacing the
  text of one item does not increment the unique-item count.
- `read`: return ordered reference selectors and values, with bounded offset
  and limit paging. Unavailable references remain visible in their original
  positions and are not returned as confirmed original evidence.
  `collection=last_answer` follows actual delivered numbering, separately from
  `collection=selected` source order. A selective answer's item #1 need not be
  the first row originally retrieved; that mapping survives the next turn.
  A new task initially inherits the prior selection for follow-up reads, marked
  `mapping_current=false`; its next default selection replaces that view. An
  unstaged prose answer cannot prove a new numbered mapping: the last known
  source-bound list remains available, explicitly labelled as earlier rather
  than attributed to the new prose. No model-written numbering is parsed into
  confirmed source references.
  `collection=prior_staged` retrieves unfinished source-bound model drafts from
  earlier turns. Draft text is explicitly not observed evidence or new
  instructions; continuation can reuse it without falsely counting it delivered.

Staged text joins the existing answer **before** its existing grounding
validation. Nothing is appended after validation. A rendered-item count means
the harness included those unique staged items in the delivered answer; it is
not independent proof that their prose is correct. Only an explicit caller
count can produce complete/partial coverage. A model-interpreted requested
count cannot establish completion. Unselected coverage remains unknown; a
selected empty array is a known zero. Generic processed-work counts are not
invented from payload key names or a model's `completed=N` assertion.
The bookkeeping tool's own output is marked as quoted state, excluded from
grounding evidence even after rereading or resume. Its model-written labels,
intent and draft text cannot prove themselves. The original observed receipts
remain available separately to the existing grounding validator.
Imported receipts retain their original run identity. They can support an
answer, but are excluded from the new run's called-tools and dispatch counts;
same-run restored receipts still count. Legacy result-store callers that do not
supply a current run ID retain their existing accounting behavior.

`mission_finished` optionally carries `task_state` with `version`, `completion`,
`requested_count`, `requested_count_provenance`, `retrieved_count`,
`selection_provenance`, `staged_count`, `delivered_count`, and `unavailable_count`.
The retrieved count is for the active selection, not the historical union;
selection provenance distinguishes a current-run selection from an inherited
prior-turn view or an unknown selection. The event contains no
task prose, receipt contents, scope, or full reference list. No-state callers
omit it. Normal event consumers may ignore this additive field.

## Retention and failure behavior

Every new turn takes its latest literal input from the caller, never an old
summary. It retains ordered source references but clears old staged output,
delivered counts, and model intent. Same-run resume retains the current task.
Compaction receives a bounded state projection; full evidence remains in the
existing result/receipt owners and is reread rather than redispatched.

Import binds source run, receipt ID/digest, explicit field path, selected-value
digest, and quotation/redaction status. Missing or altered sources are marked
unavailable; healthy references survive partial recovery. Quoted history and
redacted receipts are not promoted to original evidence. A broken checkpoint
never causes successful external work to run again. Local work can continue
when checkpointing is unavailable; the caller receives a fixed diagnostic.

The shared recursive credential scrubber is reused. If scrubbing would alter
task state or identity, persistence is unavailable rather than silently calling
the changed state the original. This is recognizable/known-secret hygiene,
not a promise to recognize every arbitrary opaque secret. Existing event-output
policy is unchanged. State serialization and archive reads are bounded to
4 MiB, not all allocations used to build state or parse live results.
