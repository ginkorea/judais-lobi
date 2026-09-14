# core/runtime/cognition.py — the shadow: what a run believed, beside
# what it did

"""A live :class:`~core.cognition.state.CognitiveState` fed from tool receipts.

:mod:`core.cognition` is the kernel — the store of what is believed and why
— and it has no I/O, no clock and no knowledge that a mission exists.  This
module is the **attachment**: the one place a mission's receipts become
propositions, and the one place those propositions reach a disk.  The
direction is deliberate and permanent: the kernel does not import anything
under :mod:`core.runtime`, so a different kernel can be dropped in behind
this file and nothing else in the harness learns about it.

**Shadow means shadow** (``ROADMAP.md`` §2.9.3–§2.9.4, the owner's ruling of
13 September 2026).  With ``--cognition`` off, every byte of every stream and
every store is what it was before this file existed — the run corpus is the
proof, and ``tests/test_cognition_shadow.py`` runs it with the flag on as
well.  With the flag on and **no goals in the store** — which is every run
until something loads a rule pack — the only difference a run makes is
:data:`REASONING_LOG` and the console line announcing it: no prompt changes,
no call is made or withheld, no gate is added, and nothing on the wire moves.
**Nothing in this module may fail a mission.**  Every public method is total:
an exception inside one is counted, stops cognition for the rest of the run,
writes one note into the log and returns.  A mission does not find out.

**The one thing a goal changes** (Phase 19, §2.9.6):
:meth:`ShadowCognition.progress` is read at each step boundary and handed to
:class:`core.runtime.supervisor.Supervisor`, which may raise its ordinary
advisory review when the frontier stops moving.  That is one review turn a
run might not otherwise have spent, on a field the stream already has, with
no new verdict and no ending that a repeated call could not already reach —
and it is still not a gate: nothing is held, checked or refused, and a
progress read that raises turns the signal off and leaves everything else
running.

**``--compiled-context`` is the one thing that changes a prompt**, and it is
a *second* switch on this same object (:attr:`ShadowCognition.compiling`)
rather than a second attachment: the state a view is compiled from is this
one, and a run that compiled from somewhere else would be showing the model
a belief the log does not hold.  It is still additive and still never a
gate — :meth:`ShadowCognition.compiled_block` adds a block to a turn, takes
nothing away, and holds, checks or refuses nothing — and it is still total:
a compiler that raises stops *compiling* for the rest of the run, leaves the
harvest running, writes one note and returns ``""``.  ``--cognition`` alone
is exactly the shadow it was; the two switches move in one direction each.

**It is not free, and "shadow" is a claim about *gating*, not about time.**
Nothing here is awaited for *permission* — no call in this module returns a
verdict a mission loop waits on — but the harvest and the flush run inside
the step, on the loop's own thread, and they cost wall clock.  Measured on
this tree, one step costs about one ``fsync``: **6.4 ms** for a step
harvesting twenty fields, 5.8 ms for two (see :meth:`ShadowCognition._flush`,
which states the numbers and what they were before the step's events were
batched into one append).  Against a model call that is seconds, that is
noise; against ``--mission-seconds`` set tight, or a very long run, it is a
real number, and a deployment that has budgeted its clock to the millisecond
should know it is there.  Saying so is the point: a cost nobody wrote down is
a cost somebody discovers.

**``--compiled-context`` adds a second cost and it grows with the store.**
:meth:`ShadowCognition.compiled_block` runs on the same thread, in the same
step, and it walks every live proposition: one
:meth:`~core.cognition.state.CognitiveState.support` per claim (a memoised
DAG walk), one line rendered per claim, and then a cut chosen against prefix
sums.  Measured on this tree (median of five, warm): **95 ms** for a store
of four thousand live facts and **244 ms** for eight thousand — roughly
2.6× for twice the store, which is the grading and not the cut — and a
fraction of a millisecond for the dozens a real mission holds.  It scales with **what the store believes**,
not with what the block shows, because a fact must be graded before it can
be ranked out: the four-thousand-character cap bounds what the model
reads, never what it costs to work out what to show it.  It was 482 ms
before the review: the cut used to re-render the whole block once per
dropped line, which is quadratic against a store that only grows.  A
deployment that intends to run thousands of receipts through one mission
should read that number as the one to watch, and Phase 19's measurement is
where it gets watched.

## Where it attaches, and why there is one place

:meth:`core.runtime.run.Run._dispatch` calls
:meth:`~core.runtime.results.MissionResultStore.record`, and that is the
single moment a receipt **this run dispatched** is durably known: the bus has
answered, the whole result is in the store under the handle the model can
quote, and every protocol and every child of a staged turn passes through it
— the JSON loop, the native turn, each gathered child, and a replayed run,
whose dispatches are real dispatches served out of ``tools.jsonl``.  The
alternatives were each partial.  ``tool_result`` on the observer carries the
*bounded* rendering's siblings but is emitted by the stream and not by the
run; ``RecordingBus.dispatch`` sees only the runs that are being recorded;
the grounding validator sees only the receipts an answer was checked
against.  One attachment point, one owner.

**It is not every ``record`` call in the repository, and the difference is
``--resume``.**  :mod:`core.runtime.resume` re-records a recorded run's
results into a fresh store — twice, at ``_rebuild_staged`` and at
``_replay_result`` — so that the handles keep addressing the same results and
the resumed model reads the transcript it was reading before.  Those are
**replays of receipts this process never took**, and they are deliberately
not attached to: harvesting there would be a second attachment point, and it
would double every observation of a run whose prior log this shadow has just
replayed.  What it costs is real and is stated rather than hidden — a run
recorded *without* the flag and resumed *with* it begins believing at the
resume, and :func:`open_shadow` writes :data:`RESUMED_NOTE` into the log as
line two so that a short log is never mistaken for a complete one.

## The rules, and where they come from

A shadow with no rules and no goals derives nothing and owes nothing: the
harvest fills a store and the frontier is empty because there is nothing to
be missing *from*.  :class:`RulePack` is the other half, and
``ROADMAP.md`` §2.9.4 says where it arrives from — **through the skill**.  A
manifest may carry a ``cognition:`` block (``cardinality:``, ``rules:``,
``goals:``); :mod:`core.runtime.skills` holds it raw exactly as it holds
``grounding:``, this module reads it, and :func:`open_shadow` writes it into
the store *before the first receipt* through the kernel's ordinary public
doors — so it is in ``reasoning.jsonl``, so a resume replays it rather than
loading it twice, and so a promoted rule's promotion is an event somebody
can read.  Rule authorship is then a **named cost of the architecture**
rather than an unexamined assumption, which is the gap the thought
experiment left.

Nothing about the floor changes: an unusable block is a refusal *at the
manifest door* (the ``--no-grounding`` precedent — parsed always, acted on
only when asked), a pack that fails to load at runtime turns cognition off
for the run and writes :data:`UNLOADED_NOTE`, and a mission under a pack
runs the mission it would have run.  Rules derive; they do not gate.

:meth:`~core.runtime.run.Run._loop` closes the step.  That is the kernel
review's M2 ruling written into the harness: :meth:`ShadowCognition.receipt`
stages, and :meth:`ShadowCognition.close_step` is the **one defined flush
point per turn** — one :meth:`~core.cognition.state.CognitiveState.derive`,
then the events it produced are appended.  The two readers that do walk the
frontier — :meth:`ShadowCognition.compiled_block` and
:meth:`ShadowCognition.progress` — are called **after** that boundary, which
is what keeps them free: every kernel read flushes, so a read after the one
defined flush appends nothing, and the log's shape stays a function of the
writes rather than of who happened to look.

## The v1 mapping, honest and dumb

One receipt, one entity.  ``entity`` is ``"{tool}#{seq}"`` — the receipt
itself — where ``seq`` is what names that receipt inside the run: the handle
the model quotes at ``mission_result`` (``r3``), with the branch in front of
it on a staged turn, because a handle is only unambiguous inside one store
and a staged turn has one per stage.  :meth:`core.runtime.run.Run
._receipt_seq` is the one owner of that spelling.
``field`` is the key the harvester found; ``value`` is the scalar under it.
Authority is :attr:`~core.cognition.types.EvidenceAuthority.DETERMINISTIC`
and the evidence is one
:class:`~core.cognition.types.EvidenceRef` of kind ``receipt`` locating
``"{run_id}/{seq}/{tool}"`` — nothing a model said reaches the observation
door, which is the wall the kernel's two doors exist to keep.

**And what the receipt is about**, where a platform said so: a declared
identifier makes the receipt entity a claim about a **subject**
(``job:jl-731``), the kernel projects the receipt's facts onto it, and two
receipts naming one job finally join — the thing an entity-per-receipt store
could never do.  The link is a claim like any other, with its two premises
named (the receipt and the declaration) and graded at the weaker of them;
the projection is the kernel's, not this module's.  See
:meth:`ShadowCognition._identify`, :meth:`core.cognition.state
.CognitiveState.link`, and the ``via`` mark in
:mod:`core.cognition.compile`, which is where a reader meets the result.

Six bounds, each stated because each is a thing the store does **not** know:

* **Non-JSON receipts contribute nothing.**  A receipt is parsed with
  :func:`core.runtime.grounding.json_blocks` — the harness's one reader of
  "is there JSON in this text" — and prose yields no blocks and therefore no
  propositions.  Turning a sentence into a claim is *extraction*, it is a
  model's job, and its reliability is Phase 16's number, not this file's
  assumption.
* **A declared identifier is the one string that is read** (and the bound
  below is otherwise unchanged).  Where the plane declared that a key holds
  an *identity* — :class:`core.runtime.declarations.PlaneDeclarations`,
  built at fleet-connect from the servers' ``outputSchema`` and the skill's
  ``tools:`` block — that key's string value is asserted as a fact on the
  receipt entity and the receipt is **linked** to the subject it names
  (``job:jl-731``).  See :meth:`ShadowCognition._identify`.  Nothing else
  about strings changes: a key nobody declared is still dropped, because a
  string that looks like an identifier is not one, and value coincidence
  alone would manufacture contradictions out of two tools that never
  disagreed.
* **A numeric string is not a number.**  ``{"count": "8"}`` is a receipt
  whose field holds a string, and a store that quietly made it ``8`` would
  have lost the fidelity it exists for.  It cannot be asserted *as* a
  string yet either (see the next bound), so it is dropped:
  :func:`_without_strings` takes string leaves off the payload before the
  harvester is asked, because ``as_decimal`` runs inside ``harvest_fields``
  and ``Decimal("8") == Decimal(8)`` — by the time any sink a caller can
  pass sees the figure, the source type is gone.  Losing a field is a gap;
  converting one is a lie.
* **Figures only, for now.**  :func:`core.runtime.grounding.harvest_fields`
  on this tree reports the *numbers* under each key, because the grounding
  checks that own it read figures.  **TODO on merge with
  ``lane/p16-extraction``**: that lane adds a ``scalars=`` sink to the same
  function — every scalar under its key, raw and in encounter order,
  strings, booleans and nulls included.  When the two lanes meet, pass
  ``scalars=`` here and assert those through this same mapping; the
  :func:`_scalar` conversion below then goes away with it.  Do **not** grow
  a second harvester in the meantime: the swarm's six-of-ten grounding
  fields is what a second emitter looks like a month later.
* **A key with more than one figure is not a single-valued fact.**  A
  payload listing forty rows with a ``score`` each gives one key forty
  numbers, and this kernel's store is single-valued per ``(entity, field)``
  unless a cardinality is declared — asserting them all would manufacture
  forty contradictions out of a list that contradicts nothing.  So such a
  key is skipped and counted.  **The harvest declares no field cardinality
  of its own** — no call to
  :meth:`~core.cognition.state.CognitiveState.declare_field` anywhere in
  it — and that is a decision rather than an omission: undeclared is
  ``many`` at event schema 2, so nothing the shadow asserts can contest
  anything on a receipt that legitimately lists ten runs, and a declaration
  made here would be this file guessing at a schema it is reading rather
  than writing.  **A rule pack that wants ``one`` for a field says so
  itself**, and that is the one door a declaration comes through — see
  :class:`RulePack`, which is a skill manifest's clauses and not this
  module's opinion.
  Lifting the skip above still needs the per-row entity that the flat
  harvester's missing path is holding up, which is the same merge as the
  sink.
* **The kernel's refusals are counted, never fatal.**  A value it will not
  take — a non-finite figure, a string spelled like the variable marker —
  is skipped and lands in :attr:`ShadowCognition.refused`.  A store that
  refuses a value is doing its job; a shadow that let that reach the
  mission would not be a shadow.

## The file

:data:`REASONING_LOG` sits in the run's directory beside ``events.jsonl``,
``model.jsonl`` and ``tools.jsonl``, under the same ``JUDAIS_LOBI_RUNS``
policy and written the same way — :func:`core.durable.fsync_append` of one
:func:`core.runtime.replay.canonical` line, because "the reasoning said so"
is a claim about a disk and not about a buffer.  Line one is a header
stating **three** versions: this file's shape, the kernel's event
vocabulary and the kernel *engine* that assigned the ids — see
:func:`header_record`, which argues the third.  None of them is
:data:`core.runtime.contract.SCHEMA_VERSION`, and this log is **not on the
wire**: no record type is added to the stream, so nothing here has any
bearing on what a platform pins.

Every line after the header is one kernel event, verbatim, so that
:func:`replay_reasoning` over the file rebuilds the state exactly — through
:meth:`~core.cognition.state.CognitiveState.replay`, which is the kernel's
own single application path.  Two kinds of line are not events and a replay
skips both: a ``note``, which says cognition stopped and why, and the
**declarations record** (:meth:`ShadowCognition.declare_plane`), which says
what the plane this run connected to declares about what its tools return.
The second is not a kernel event on purpose — the kernel knows nothing about
tools — and it is in this file rather than in a file of its own because a
resumed run reads one log to find out what the process before it steered
under, and a plane that has moved since then is then a difference two
records apart rather than a thing nobody wrote down.

**A log this reader cannot trust is refused, and a refusal disables
cognition rather than ending a mission.**  The kernel checks more than the
records: an event's ``n`` must be its position, so a log reordered,
truncated in the middle or duplicated is caught even though every line in
it is well-formed on its own, and malformed evidence is a
:class:`~core.cognition.types.ReplayRefused` rather than an
``AttributeError`` out of the middle of a decode.  Every one of those
arrives here as the same exception out of :func:`open_shadow`, which is the
one call in this module that is allowed to raise — see it, and see the
branch in ``core.cli`` that catches it and runs the mission with no shadow
at all.

**No clock and no ids in it.**  Kernel events carry neither, the header
carries neither, and that is what makes a replayed run's reasoning log
byte-identical to the recorded one's but for the ``run_id`` inside each
evidence locator — the same two exclusions ``core.runtime.replay`` already
states for a replay generally.

**Resume** reads the file, replays it, and appends from where it stopped:
:func:`open_shadow` is the one door, and it writes no second header.  A
resumed run that appended the events it had already written would build a
store with every observation twice.
"""

from __future__ import annotations

import hashlib
import json
import math
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from core.cognition import EVENTS_KEY as KERNEL_EVENTS_KEY
from core.cognition import SCHEMA_KEY as KERNEL_SCHEMA_KEY
from core.cognition import COUNT_KEY as KERNEL_COUNT_KEY
from core.cognition import (BUDGET_CHARS, CARDINALITIES, EVENT_SCHEMA_VERSION,
                            KERNEL_KEY, KERNEL_VERSION, CognitionError,
                            CognitiveState, EvidenceAuthority, EvidenceRef,
                            ReplayRefused, RuleAuthority, check_pattern,
                            compile_view, deep_copy, owed_line, subject_entity)

from core.durable import fsync_append
from core.runtime.declarations import DECLARATIONS_KEY as _DECLARATIONS_KEY
from core.runtime.declarations import IDENTIFIERS, values_at
from core.runtime.grounding import harvest_fields, json_blocks
from core.runtime.replay import canonical

__all__ = [
    "REASONING_LOG", "REASONING_SCHEMA_VERSION", "SCHEMA_KEY",
    "KERNEL_SCHEMA_KEY", "KERNEL_KEY", "KERNEL_EVENTS_KEY",
    "KERNEL_COUNT_KEY", "DECLARATIONS_KEY", "declarations_in",
    "DECLARATION_KIND", "Identity", "identities_of", "resolvers_of",
    "NOTE_KEY", "RECEIPT_KIND", "RESUMED_NOTE",
    "STOPPED_NOTE", "UNCOMPILED_NOTE", "UNLOADED_NOTE",
    "COGNITION_KEYS", "GOAL_KEYS", "PACK_AUTHORITY", "PROBLEM_SEP",
    "RULE_KEYS",
    "PackGoal", "PackRule", "RulePack",
    "ShadowCognition", "header_record", "observations_of", "open_shadow",
    "read_reasoning", "replay_reasoning",
    "UNWATCHED_NOTE", "Progress",
]

#: The shadow's file, in the run directory beside ``events.jsonl``.
REASONING_LOG = "reasoning.jsonl"

#: The shape of THIS file — the header, the note line, the declarations
#: record, which records are events.  Bumped when that shape changes.  Not
#: the kernel's version (the header carries that too, under
#: :data:`~core.cognition.events.SCHEMA_KEY`) and emphatically not
#: :data:`core.runtime.contract.SCHEMA_VERSION`: three numbers because three
#: things change for three different reasons.
#:
#: **2** adds the declarations record.  Bumped rather than added quietly,
#: even though a version-1 reader would skip the line as it skips a note and
#: rebuild the state correctly: it would also rebuild *fewer hints than the
#: log holds* and say nothing, which is this file's own definition of a log
#: misread exactly once.  A reader that refuses is a reader somebody fixes.
REASONING_SCHEMA_VERSION = 2

#: The key the header states :data:`REASONING_SCHEMA_VERSION` under, and the
#: key that identifies the header line.
SCHEMA_KEY = "reasoning_schema"

#: The key a note line carries.  A note is not an event and is never replayed.
NOTE_KEY = "note"

#: The key the declarations record carries, and the version it states under
#: it — :data:`~core.runtime.declarations.DECLARATIONS_KEY`, imported rather
#: than respelled, because the record is built by the module that owns what
#: is in it and a second spelling here is the second answer to *which line
#: is this*.
DECLARATIONS_KEY = _DECLARATIONS_KEY

#: What an :class:`~core.cognition.types.EvidenceRef` out of this module
#: calls itself.  The kernel never dereferences it; a reader of the log does.
RECEIPT_KIND = "receipt"

#: The **second** kind of evidence this module makes, and the only claim in
#: the harness that rests on something other than a receipt: a link's
#: premise that a key *is* an identity.
#:
#: It is its own kind because it is its own sort of thing.  A receipt ref
#: locates what a call returned; this one locates a sentence in a platform's
#: file (or in its server's schema) saying what a returned string means, and
#: a reader of ``reasoning.jsonl`` asking "why does the store think these two
#: receipts are about one job" must be able to tell the two apart without
#: parsing a locator.  It is also why a deterministic link is stamped
#: ``SOURCE`` and not ``DETERMINISTIC``: the weakest premise under it is this
#: ref, and a link graded above its weakest premise would launder a
#: platform's word into a measurement.
DECLARATION_KIND = "declaration"

#: The one sentence a note line says.  One spelling, so a reader can find
#: every run whose shadow stopped without matching on an exception message.
STOPPED_NOTE = "cognition stopped; the mission was not told"

#: The third note: ``--compiled-context`` was on and the compiler raised.
#: Its own sentence and not :data:`STOPPED_NOTE`, because the two are
#: different facts about the run — this one says the model stopped being
#: shown the view while the store went on believing, and a reader that
#: could not tell them apart would read a working shadow as a dead one.
UNCOMPILED_NOTE = ("the compiled context stopped; the harvest continued and "
                   "the mission was not told")

#: The fourth note: a skill carried a ``cognition:`` block and it did not
#: load.  Its own sentence, for :data:`UNCOMPILED_NOTE`'s reason — a reader
#: that could not tell this from a store that harvested badly would go
#: looking in the wrong file — and it says the mission was untouched because
#: that is the floor rule: a pack that will not load costs a run its
#: cognition and nothing else.
UNLOADED_NOTE = ("the skill's rule pack did not load; cognition is off for "
                 "this run and the mission was not told")
#: The fifth note: the epistemic-progress read raised, so the supervisor
#: stops being told whether this run's belief is moving.  Its own sentence
#: for :data:`UNCOMPILED_NOTE`'s reason — a store that goes on believing
#: while one reader of it stopped is not a dead shadow, and a reader that
#: could not tell the four apart would report the wrong one.
UNWATCHED_NOTE = ("the epistemic-progress signal stopped; the harvest "
                  "continued and the supervisor was not told")


#: The other note, and it is not an error: this log begins at a resume, so
#: the receipts the run took before it were never offered to this store.
#: See :func:`open_shadow` for why that is the correct behaviour and why it
#: has to be written down rather than inferred from a short log.
RESUMED_NOTE = ("this log begins at a resume; the receipts this run took "
                "before it were not harvested")


# ── the rule pack: a skill's clauses, as kernel writes ───────────────────────

#: What a ``cognition:`` block may say.  Closed, and refused by name like
#: :data:`core.runtime.grounding.GROUNDING_KEYS`: a key this reader has never
#: heard of is a key an author believed was doing something.
COGNITION_KEYS: Tuple[str, ...] = ("cardinality", "rules", "goals")

#: What one entry of ``rules:`` may say.
RULE_KEYS: Tuple[str, ...] = ("name", "head", "body")

#: What one entry of ``goals:`` may say.
GOAL_KEYS: Tuple[str, ...] = ("name", "pattern")

#: How :meth:`RulePack.from_mapping` lays out the problems in one refusal,
#: and it is **not** ``"; "``.
#:
#: Several of the messages carry a semicolon of their own — the kernel's own
#: ``"'two' is not a cardinality; 'one' or 'many'"`` among them — so a list
#: joined on a semicolon is a list nobody can take apart again: three faults
#: arrive looking like six half-sentences, and an author fixing a file has to
#: guess where each one ends.  A newline and a dash appear in none of them,
#: which is what makes this a separator rather than a decoration.
#:
#: Indented one level deeper than the refusal-list idiom
#: (:class:`~core.runtime.skills.SkillManifestError`'s ``"\n  - "``),
#: because that is where these lines land: a manifest refusal is a list, and
#: a pack's faults are a list *inside one of its items*.  Every caller of
#: this door ends its own sentence with a colon and lets the separator do
#: the rest.
PROBLEM_SEP = "\n    - "

#: The authority a pack's rules end up standing on, and the whole argument
#: for the two-step load below.
#:
#: :meth:`~core.cognition.state.CognitiveState.add_rule` defaults to
#: ``PROPOSED`` — the kernel's wall, where a clause nobody vouched for
#: derives nothing — and :meth:`~core.cognition.state.CognitiveState
#: .promote_rule` is the door through it.  A loader that passed ``SKILL``
#: straight to ``add_rule`` would work and would walk *round* the wall: the
#: log would hold one event where it should hold two, and the question
#: "who promoted this clause, and when" would have no answer in the file.
#: So a pack's rule arrives proposed and is promoted, in the log, in that
#: order — the same sequence a human operator's would take.
#:
#: ``SKILL`` and not ``DOMAIN``: the rules came out of a skill manifest, and
#: that is exactly what the authority says.
PACK_AUTHORITY = RuleAuthority.SKILL


@dataclass(frozen=True)
class PackRule:
    """One clause of a pack: a name, a head and a body, all validated."""

    name: str
    head: Tuple[Any, Any, Any]
    body: Tuple[Tuple[Any, Any, Any], ...]


@dataclass(frozen=True)
class PackGoal:
    """One target of a pack.  The *name* becomes the kernel goal's note.

    The kernel's :class:`~core.cognition.types.Goal` has no name field and
    should not grow one for this: a goal is identified by its pattern, and
    the word a pack author wrote is what a reader of the log wants to see
    beside it.  ``note`` is that field, and putting the name there is the
    honest landing rather than a second identity the kernel would have to
    keep unique.
    """

    name: str
    pattern: Tuple[Any, Any, Any]


@dataclass(frozen=True)
class RulePack:
    """A skill manifest's ``cognition:`` block, read once and applied once.

    **This is the frontier made real** (``ROADMAP.md`` §2.9.4: *rules arrive
    through skills*).  The shadow harvests receipts into propositions and,
    with no rules and no goals, that is where it stops: nothing derives,
    nothing is owed, and ``frontier()`` is empty by construction.  A pack is
    the other half — the clauses that turn observations into conclusions and
    the targets that turn what is missing into obligations — and it arrives
    where the rest of a mission's operational knowledge arrives, in the
    manifest, which is what makes rule authorship a **named cost** of this
    architecture rather than an assumption nobody budgeted for.

    **Read here and nowhere else.**  :mod:`core.runtime.skills` is the one
    reader of a manifest and holds this block raw, exactly as it holds
    ``grounding:``; what a block *means* is this module's, because this
    module is the attachment and the kernel is what it attaches to.  The
    same shape as grounding, for the same reason: two readers of one block
    is the defect that costs a field the day they disagree.

    **Refused at the door.**  :meth:`from_mapping` collects every problem in
    one message — the module idiom an author fixing a file wants — and then
    **dry-runs the whole pack through a throwaway kernel**, so a block the
    kernel would refuse is a manifest that does not load rather than a
    mission that dies at its first step.  The dry run is
    :meth:`load_into` itself, against a fresh
    :class:`~core.cognition.state.CognitiveState`: a second, simpler
    "would this work" would be the second owner, and the day it disagreed
    with the real load it would be the one that had been tested.
    """

    cardinality: Tuple[Tuple[str, str], ...] = ()
    rules: Tuple[PackRule, ...] = ()
    goals: Tuple[PackGoal, ...] = ()

    def __bool__(self) -> bool:
        """A pack that declares nothing is falsy, and is still a pack.

        ``cognition: {}`` is a manifest saying *this skill has a cognitive
        block and it is empty*, which composition has to keep (the
        key-presence invariant).  Loading it writes nothing, which is the
        correct amount.
        """
        return bool(self.cardinality or self.rules or self.goals)

    @classmethod
    def from_mapping(cls, raw: Any) -> "RulePack":
        """One ``cognition:`` block, or a ``ValueError`` naming every fault.

        ``ValueError`` and not a :class:`~core.cognition.types
        .CognitionError`, because the caller is a manifest loader and the
        fault is in a file somebody wrote — the same exception
        :meth:`~core.runtime.grounding.GroundingConfig.from_mapping` raises
        for the same reason, so ``skills.py`` refuses both blocks through
        one ``except``.

        **One problem per line**, on :data:`PROBLEM_SEP`, and that is not
        cosmetic: several of the messages below contain a semicolon of
        their own (``"{cardinality!r} is not a cardinality; 'one' or
        'many'"`` comes straight out of the kernel), so a list joined on
        ``"; "`` is a list a reader cannot take apart again — three faults
        arrive looking like six half-sentences. The newline-dash is the
        idiom every other refusing door in the harness already writes,
        including :meth:`~core.runtime.grounding.GroundingConfig
        .from_mapping` next door.
        """
        problems: List[str] = []
        if raw is None:
            raw = {}
        if not isinstance(raw, Mapping):
            raise ValueError(
                f"a `cognition:` block is a mapping "
                f"({', '.join(COGNITION_KEYS)}), not a "
                f"{type(raw).__name__}")

        unknown = sorted(set(map(str, raw)) - set(COGNITION_KEYS))
        if unknown:
            problems.append(
                f"unknown key(s): {', '.join(unknown)}. A cognition block "
                f"sets {', '.join(COGNITION_KEYS)}")

        cardinality = _read_cardinality(raw.get("cardinality"), problems)
        rules = _read_rules(raw.get("rules"), problems)
        goals = _read_goals(raw.get("goals"), problems)
        pack = cls(cardinality=cardinality, rules=rules, goals=goals)

        if not problems:
            # THE DRY RUN, and it is the real load against a store nobody
            # keeps. Everything the shape checks above cannot know lives in
            # here: a head variable the body never binds, an empty body, two
            # cardinalities for one field, a literal the kernel will not take
            # as a value. A mission that started on one of those would die at
            # its first derive, in a module whose whole promise is that it
            # cannot cost a mission anything.
            try:
                pack.load_into(CognitiveState())
            except CognitionError as exc:
                problems.append(f"the kernel refuses this pack: {exc}")

        if problems:
            raise ValueError(PROBLEM_SEP + PROBLEM_SEP.join(problems))
        return pack

    def load_into(self, state: CognitiveState) -> Tuple[int, int, int]:
        """Write this pack into *state*.  Returns ``(fields, rules, goals)``.

        **Deterministic order, and it is part of the file's meaning**:
        cardinality, then rules, then goals, each in the order the manifest
        wrote them.  A replayed reasoning log therefore holds the pack in the
        order an author reading their own file expects, and two runs of one
        manifest produce the same event sequence — which is what makes the
        log a determinism proof rather than a diary.

        Cardinality first because it is a statement about what the store is
        allowed to notice, and a declaration arriving after the observations
        it governs is a store whose ledger cannot be explained by its own
        rules.  (The kernel is careful here too — ``declare_field`` applies
        to what is already held — but an order that only works because the
        other end is forgiving is an order nobody chose.)

        Every write goes through the kernel's ordinary public doors, so every
        one of them is an event in ``reasoning.jsonl`` and a resume rebuilds
        the pack by replaying the log rather than by reading the manifest
        again.  That is the whole of resume for a pack, and it is why
        :func:`open_shadow` loads on the fresh path only.
        """
        for field, cardinality in self.cardinality:
            state.declare_field(field, cardinality)
        for rule in self.rules:
            rid = state.add_rule(rule.name, rule.head, rule.body)
            state.promote_rule(rid, PACK_AUTHORITY)
        for goal in self.goals:
            state.add_goal(goal.pattern, note=goal.name)
        return (len(self.cardinality), len(self.rules), len(self.goals))


def _read_cardinality(raw: Any, problems: List[str]) -> Tuple[Tuple[str, str], ...]:
    """``cardinality:`` as ``((field, "one"|"many"), …)`` in file order."""
    if raw is None:
        return ()
    if not isinstance(raw, Mapping):
        problems.append(
            f"`cardinality:` holds a {type(raw).__name__}; it is a mapping of "
            f"field name to {' or '.join(repr(c) for c in CARDINALITIES)}")
        return ()
    out: List[Tuple[str, str]] = []
    for field, cardinality in raw.items():
        name = str(field or "").strip()
        if not name:
            problems.append("`cardinality:` names a field with no name")
            continue
        if cardinality not in CARDINALITIES:
            problems.append(
                f"`cardinality: {name}` is {cardinality!r}; a field carries "
                f"{' or '.join(repr(c) for c in CARDINALITIES)} values, and "
                f"only {'one'!r} turns collision detection on")
            continue
        out.append((name, str(cardinality)))
    return tuple(out)


def _pattern(raw: Any, where: str, problems: List[str]
             ) -> Optional[Tuple[Any, Any, Any]]:
    """One triple pattern, through the kernel's own reader.

    :func:`core.cognition.types.check_pattern` is the owner of *what a
    pattern is* — three terms, a variable spelled ``?name``, a literal the
    store would take — and asking it here rather than re-deciding is what
    keeps a manifest and a rule agreeing about the ``?``.  It raises on the
    first fault, which is why it is called once per pattern and the message
    is collected: an author with three malformed rules fixes them once.
    """
    if raw is None:
        problems.append(f"{where} has no pattern")
        return None
    if isinstance(raw, str) or not isinstance(raw, Sequence):
        problems.append(
            f"{where} is a {type(raw).__name__}; a pattern is three terms "
            f"[entity, field, value], each a literal or a ?variable")
        return None
    try:
        return check_pattern(raw)
    except CognitionError as exc:
        problems.append(f"{where}: {exc}")
        return None


def _entries(raw: Any, key: str, keys: Tuple[str, ...],
             problems: List[str]) -> List[Tuple[str, Mapping]]:
    """``(name, entry)`` for every usable entry of ``rules:`` / ``goals:``.

    Names are required, non-empty and unique *within their own key*: a rule
    and a goal may share a word, because they are different kinds of thing
    and nothing composes them together, while two rules called one name are
    the conflict :func:`core.runtime.skills.compose_manifests` is about to
    have to reason over — and one that is already unanswerable inside a
    single file.
    """
    if raw is None:
        return []
    if isinstance(raw, Mapping) or isinstance(raw, str) \
            or not isinstance(raw, Sequence):
        problems.append(
            f"`{key}:` holds a {type(raw).__name__}; it is a list of "
            f"mappings ({', '.join(keys)})")
        return []
    out: List[Tuple[str, Mapping]] = []
    seen: List[str] = []
    for index, entry in enumerate(raw):
        where = f"`{key}:` entry {index + 1}"
        if not isinstance(entry, Mapping):
            problems.append(
                f"{where} is a {type(entry).__name__}; it is a mapping "
                f"({', '.join(keys)})")
            continue
        unknown = sorted(set(map(str, entry)) - set(keys))
        if unknown:
            problems.append(
                f"{where} sets unknown key(s): {', '.join(unknown)}. An entry "
                f"of `{key}:` sets {', '.join(keys)}")
        name = str(entry.get("name") or "").strip()
        if not name:
            problems.append(
                f"{where} has no `name`; a pack's clauses are named because "
                f"composition unions them by name and a refusal has to say "
                f"which one it means")
            continue
        if name in seen:
            problems.append(
                f"`{key}:` declares {name!r} twice in one manifest. Two "
                f"clauses under one name is one of them being talked about "
                f"and the other silently not")
            continue
        seen.append(name)
        out.append((name, entry))
    return out


def _read_rules(raw: Any, problems: List[str]) -> Tuple[PackRule, ...]:
    out: List[PackRule] = []
    for name, entry in _entries(raw, "rules", RULE_KEYS, problems):
        head = _pattern(entry.get("head"), f"rule {name!r} head", problems)
        body_raw = entry.get("body")
        if body_raw is None or isinstance(body_raw, (str, Mapping)) \
                or not isinstance(body_raw, Sequence) or not list(body_raw):
            problems.append(
                f"rule {name!r} has no `body`; a rule with no premises is an "
                f"observation, and observations come with evidence")
            continue
        body: List[Tuple[Any, Any, Any]] = []
        for index, item in enumerate(body_raw):
            pattern = _pattern(
                item, f"rule {name!r} body premise {index + 1}", problems)
            if pattern is not None:
                body.append(pattern)
        if head is None or len(body) != len(list(body_raw)):
            continue
        out.append(PackRule(name=name, head=head, body=tuple(body)))
    return tuple(out)


def _read_goals(raw: Any, problems: List[str]) -> Tuple[PackGoal, ...]:
    out: List[PackGoal] = []
    for name, entry in _entries(raw, "goals", GOAL_KEYS, problems):
        pattern = _pattern(entry.get("pattern"), f"goal {name!r}", problems)
        if pattern is not None:
            out.append(PackGoal(name=name, pattern=pattern))
    return tuple(out)


# ── a receipt, as propositions ───────────────────────────────────────────────


def _scalar(figure: Any) -> Optional[Any]:
    """One harvested figure as a JSON scalar the kernel will take, or ``None``.

    :data:`core.cognition.types.VALUE_TYPES` is the JSON scalars and a
    ``Decimal`` is not one of them, so the exact decimal the grounding
    harvester works in has to become an ``int`` or a ``float`` on the way
    through this door.  Integral first, because ``8`` read back as ``8.0``
    is a figure the store renders differently from the receipt it came from.

    ``None`` for anything that will not survive the trip: ``NaN`` and the
    infinities are spelled by ``Decimal`` and by a JSON parser that accepts
    them, they are not JSON, and a store holding one would compare unequal
    to itself.  The caller counts these rather than raising — see
    :attr:`ShadowCognition.refused`.

    **TODO on merge with ``lane/p16-extraction``**: with ``harvest_fields``'
    ``scalars=`` sink the raw value arrives already a JSON scalar and this
    function is deleted rather than extended.
    """
    try:
        if not figure.is_finite():
            return None
        if figure == figure.to_integral_value():
            return int(figure)
        number = float(figure)
    except (ArithmeticError, ValueError, TypeError, AttributeError):
        return None
    return number if math.isfinite(number) else None


def _without_strings(node: Any) -> Any:
    """*node* with every string leaf dropped, structure otherwise intact.

    **Why this exists, and why it is not a second harvester.**  ``"8"`` is
    not ``8`` at this door: a receipt that said the string is a receipt
    whose field holds a string, and a store that quietly converts it has
    lost the one thing it is for — fidelity to what the tool returned.  But
    :func:`core.runtime.grounding.harvest_fields` cannot be asked about
    that, because ``as_decimal`` runs *inside* it and
    ``Decimal("8") == Decimal(8)``: by the time any sink a caller can pass
    sees the figure, the source type is gone.  Verified, not assumed.

    So the type question is answered *before* the harvester is called, by a
    walk that knows nothing about fields and nothing about figures — it
    only drops strings.  ``harvest_fields`` remains the single owner of
    what a field is and what a figure is, which is the rule this shape
    exists to keep; a second walker that also decided those things is
    exactly what the swarm's six-of-ten grounding fields was.

    **TODO on merge with ``lane/p16-extraction``**: the ``scalars=`` sink
    hands over the raw value with its type, so a string can be *asserted as
    a string* instead of dropped, and this function goes away with the
    :func:`_scalar` conversion.  Until then a string field is on the
    receipt and not in the store — the same bound, and the same merge, as
    everything else non-numeric.

    ``bool`` is left where it is: ``as_decimal`` already refuses it, on the
    grounds that ``True == 1`` is a fact about Python and not a claim about
    a run, and dropping it here would be this function having a second
    opinion about that.
    """
    if isinstance(node, Mapping):
        return {key: _without_strings(value) for key, value in node.items()
                if not isinstance(value, str)}
    if isinstance(node, list):
        return [_without_strings(item) for item in node
                if not isinstance(item, str)]
    return node


def observations_of(text: Any) -> Tuple[Tuple[str, Any], ...]:
    """``((field, value), …)`` for one receipt's text — deterministic order.

    The whole of the v1 mapping's *what*, in one function, so that a test
    can state what a receipt is worth without running a mission.  Empty for
    text holding no JSON, which is the honest answer and not a failure: see
    the module docstring's bounds.

    Sorted by field, because the harvester's ``values`` is a dict of sets
    and neither one promises an order this file may write into a log twice.
    """
    # `keys` is the harvester's other output — every key name it met,
    # figure or not — and v1 has no use for it: a key whose value is an
    # object or a list is a key that exists and holds nothing this store can
    # hold. Collected because the signature wants a sink, dropped because
    # inventing a proposition for it would be this module reading meaning
    # into a shape.
    keys: set = set()
    values: Dict[str, set] = {}
    for block in json_blocks(text):
        harvest_fields(_without_strings(block), keys, values)
    out: List[Tuple[str, Any]] = []
    for field in sorted(values):
        figures = values[field]
        # One figure or nothing: see the module docstring. `len` and not a
        # `next`, because a key holding two numbers is a fact this store
        # cannot represent, not a fact whose first half is true.
        if len(figures) != 1:
            continue
        scalar = _scalar(next(iter(figures)))
        if scalar is None:
            continue
        out.append((field, scalar))
    return tuple(out)


# ── a receipt, as identities ─────────────────────────────────────────────────


@dataclass(frozen=True)
class Identity:
    """One declared identifier, found once in one receipt.

    Four strings and no cleverness: where it was declared (*path*), what the
    store will call it (*field*), what kind of subject it names (*kind*) and
    what the receipt said (*value*).  A dataclass rather than a tuple
    because three of the four are strings that would read the same in a
    positional call, and the one mistake this layer must not make is
    swapping a kind for a value.
    """

    path: str
    field: str
    kind: str
    value: str

    def subject(self) -> str:
        """``kind:value`` — spelled by the kernel's own owner of it.

        :func:`~core.cognition.types.subject_entity` checks the round trip,
        so a kind or a value that would spell a *different* subject when
        read back raises here rather than linking something nobody
        declared.  This module does not know what a subject is spelled
        like and must not learn.
        """
        return subject_entity(self.kind, self.value)


def _field_of(path: str) -> str:
    """The field name a declared key path lands under.

    The last segment, with ``[]`` off: ``data.job_id`` is the field
    ``job_id``, exactly as :func:`core.runtime.grounding.harvest_fields`
    would have named it had the value been a figure.  **One naming rule for
    the store**, and it matters in both directions: a pack declaring
    ``cardinality: {job_id: one}`` binds the identifier fact, and a rule
    joining on ``job_id`` joins the harvest's figures and the declared
    identifiers alike.  A field named by its whole path would be a second
    vocabulary inside one store, visible only to whoever wrote the
    declaration.
    """
    return path.rsplit(".", 1)[-1].removesuffix("[]")


def identities_of(text: Any, identifiers: Mapping[str, str]
                  ) -> Tuple[Tuple[Identity, ...], int]:
    """``((identity, …), ambiguous)`` for one receipt under *identifiers*.

    **The declared exception to the string bound**, and the whole of it.
    :func:`_without_strings` drops every string leaf before the harvester
    sees a payload, because a string is not a figure and a store that
    guessed would have lost the fidelity it exists for.  A *declared*
    identifier is the one string this layer may read: a platform has said,
    in a file or in its server's schema, that the value under this key is an
    identity — and identity is the one thing a receipt cannot say about
    itself.  Nothing widens: every other string is dropped exactly as
    before, and a key nobody declared is not an identifier because it looks
    like one.

    The rules, each of them a case this returns nothing for:

    * **the path, not the name.**  :func:`core.runtime.declarations
      .values_at` walks the declared path from the root of the payload, so
      ``data.job_id`` never reads ``meta.job_id``.  A flat name match would
      link on a same-named key somewhere else in a governed envelope, which
      is a wrong link, which is the one mistake here that manufactures
      contradictions;
    * **one value per key, or none.**  A declared key holding two different
      strings in one receipt identifies nothing — which of them is the
      subject is a question the receipt does not answer — so it links
      nothing and is *counted*, the same one-figure discipline the harvest
      already keeps for a key holding two numbers.  The count is the second
      element, because a caller that could not see it would read a receipt
      that declared nothing and a receipt that was ambiguous as one thing.

      **A ``[]`` path is plural by its own grammar, and in v1 it binds only
      at length one** — ``source_assets[]`` with three assets in it links
      nothing and is counted here, exactly as a scalar key holding three
      values would be.  The two cases are *not* the same fact and the
      difference is written down rather than left to be discovered: two
      values under a scalar key are two answers to one question, while
      three elements of a declared list are three **distinct subjects**,
      each of which the receipt is legitimately about.  Lifting it means
      one link per element, which needs :meth:`ShadowCognition._identify`'s
      cross-kind guard to cover a receipt linked to many subjects of one
      kind — v1.1 work, deliberately not smuggled into a fix round.  Until
      then a platform that wants list elements linked declares the element
      it means (``source_assets[0].id`` is not this grammar either; a
      per-row entity is the same v1.1 lift) or accepts that the list
      contributes provenance and no join;
    * **non-empty strings only** (the v1 bound).  A number under a declared
      key is not an identifier here: the harvest already asserts it as a
      figure, and spelling a subject from it would make ``job:5`` and the
      figure ``5`` two facts nobody can tell apart later.  A non-string
      value is not ambiguity either — it is simply not an identity this
      version reads — so it is skipped without a count.

    Deterministic: paths in sorted order, values in the payload's own, and
    the first value of a key is the one that stands.  Same receipt, same
    identities, same links, same log.
    """
    if not identifiers:
        return (), 0
    blocks = list(json_blocks(text))
    if not blocks:
        return (), 0
    found: List[Identity] = []
    ambiguous = 0
    for path in sorted(identifiers):
        seen: List[str] = []
        for block in blocks:
            for value in values_at(block, path):
                if (isinstance(value, str) and value.strip()
                        and value not in seen):
                    seen.append(value)
        if not seen:
            continue
        if len(seen) > 1:
            ambiguous += 1
            continue
        found.append(Identity(path=path, field=_field_of(path),
                              kind=str(identifiers[path]), value=seen[0]))
    return tuple(found), ambiguous


def resolvers_of(declarations: Any) -> Dict[str, Tuple[str, ...]]:
    """``{field: the tools that say they could establish it}``.

    What a plane's ``establishes`` and ``produces`` verbs are *for* on this
    tree: the OWED section's ``resolvable via:`` clause
    (:data:`core.cognition.compile.RESOLVABLE`), and nothing else.  They
    touch no store — no fact enters because a schema said it would — and
    they are read here, at compile time, rather than at the door.

    Both verbs answer the same question from two sides and both land in the
    same mapping: ``establishes`` says *this call can establish that field*,
    and ``produces`` says *the product arrives later, through ``via``* — so
    the tool named for a two-phase product is the one that carries it, not
    the one that returned the handle.  A reader of the line does not need to
    know which verb it came from; a reader of the declarations record can
    see both.

    Fields are named by :func:`_field_of`, so a plane writing
    ``establishes: [data.state]`` resolves the obligations the harvest
    spelled ``state``.  One naming rule, one store.

    Deterministic and bounded: tools in sorted order, first declaration
    first, no duplicates.  ``{}`` for no declarations at all, which is what
    every run before this feature had and what a line without the clause
    means.
    """
    out: Dict[str, List[str]] = {}

    def name(field: Any, tool: Any) -> None:
        key = _field_of(str(field or ""))
        if not key:
            return
        bucket = out.setdefault(key, [])
        if str(tool) not in bucket:
            bucket.append(str(tool))

    tools = getattr(declarations, "tools", None) or {}
    for tool in sorted(tools):
        declaration = tools[tool]
        for field in getattr(declaration, "establishes", ()):
            name(field, tool)
        for produced in getattr(declaration, "produces", ()):
            name(produced.field, produced.via)
    return {field: tuple(names) for field, names in out.items()}


# ── the file ─────────────────────────────────────────────────────────────────


def header_record() -> Dict[str, Any]:
    """Line one: this file's version and the kernel's, and nothing else.

    No run id and no clock, deliberately.  Both are properties of the run
    that is happening now, and putting either here would mean a replay of a
    recorded run could never produce the recorded bytes — which is the one
    property that makes this log a determinism proof rather than an
    artefact.

    **Three versions, because there are three questions.**  This file's
    shape (:data:`SCHEMA_KEY`); the kernel's event vocabulary
    (:data:`~core.cognition.events.EVENT_SCHEMA_VERSION`, under its own
    :data:`~core.cognition.events.SCHEMA_KEY`), which says what an ``op``
    means; and the *engine*
    (:data:`~core.cognition.events.KERNEL_VERSION`, under
    :data:`~core.cognition.events.KERNEL_KEY`), which says which
    implementation assigned the ids.  The third is the one that is easy to
    leave out and expensive to want later: a derived ``pN`` is an artefact
    of the enumeration order, that order changed between kernel 1 and
    kernel 2 for the same writes, and a consumer holding an id out of an
    older log has no way to know it now names something else unless the log
    says which engine wrote it.  None of the three is
    :data:`core.runtime.contract.SCHEMA_VERSION`.
    """
    return {SCHEMA_KEY: REASONING_SCHEMA_VERSION,
            KERNEL_SCHEMA_KEY: EVENT_SCHEMA_VERSION,
            KERNEL_KEY: KERNEL_VERSION}


def read_reasoning(path: Any) -> Tuple[Optional[dict], List[dict], List[dict]]:
    """``(header, events, notes)`` out of a :data:`REASONING_LOG`.

    Lines are told apart by what they carry rather than by position: the
    header states :data:`SCHEMA_KEY`, an event states an ``op`` (the
    kernel's own discriminator — see
    :data:`core.cognition.events.EVENT_OPS`), and anything else is a note.
    Position would be the wrong rule the first time a note lands between
    two events, which is exactly where a note lands.

    **The declarations record is among the notes**, and deliberately: it is
    the same kind of line — not the header, not an event, never replayed
    into the store — and a fourth return value would make every caller of
    this function unpack one.  :func:`declarations_in` is how a reader
    picks it out, on :data:`DECLARATIONS_KEY`.

    A header from a newer writer is **refused**, the way
    :func:`core.cognition.events.check_snapshot` refuses a newer kernel log
    and for the same reason: a log read by a reader that does not know what
    is in it is a log misread exactly once.  A file with no header at all is
    refused too — an unversioned log is the same problem without the clue.
    """
    target = Path(path)
    if not target.exists():
        return None, [], []
    header: Optional[dict] = None
    events: List[dict] = []
    notes: List[dict] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except ValueError:
            # A torn line, and by construction it is the last one: every
            # write here is one `fsync_append` of one line, so a process
            # killed mid-append leaves a prefix and nothing after it. Skipped
            # rather than refused, which is exactly the state the run would
            # have had if that write had not started — the same reading
            # `core.runtime.replay._read_log` does of the two logs beside
            # this one.
            #
            # And a torn line that is NOT the last one does not get through
            # on this leniency, which is the part worth stating: skipping it
            # leaves a gap in the kernel's `n`, and `check_snapshot` refuses
            # a log whose numbering is not its positions. So the generous
            # reading covers exactly the case it was written for — the tail
            # of a killed process — and the case it cannot be right about
            # still refuses, one layer down, in the kernel.
            continue
        if not isinstance(record, dict):
            raise ReplayRefused(f"a reasoning line is a record: {record!r}")
        if SCHEMA_KEY in record:
            # The FIRST header wins, and a second one is refused. Position
            # blindness is right for a note — one really does land between
            # two events — and wrong for the header, which is the thing
            # every other line is read under: two of them is two logs
            # concatenated, or a resume that wrote its own, and taking the
            # last would silently reinterpret every event before it.
            if header is not None:
                raise ReplayRefused(
                    f"{target} states {SCHEMA_KEY!r} twice; two headers are "
                    "two logs in one file, and every event before the "
                    "second would be read under a version it was not "
                    "written under")
            header = record
        elif "op" in record:
            events.append(record)
        else:
            notes.append(record)
    if header is None:
        raise ReplayRefused(
            f"{target} states no {SCHEMA_KEY!r}, and an unversioned log "
            "cannot be trusted to mean what this reader would read into it")
    version = header.get(SCHEMA_KEY)
    # `isinstance(version, bool)` refused explicitly, because `True` is an
    # `int` in Python and `True > 1` is `False`: a header saying
    # `{"reasoning_schema": true}` would otherwise read as version 1 and be
    # accepted. The kernel's `check_snapshot` guards the same thing on its
    # own version, and so does the graph lane; three readers, one rule.
    if (not isinstance(version, int) or isinstance(version, bool)
            or version > REASONING_SCHEMA_VERSION):
        raise ReplayRefused(
            f"reasoning schema {version!r} is newer than this reader's "
            f"{REASONING_SCHEMA_VERSION}")
    return header, events, notes


def declarations_in(records: Sequence[dict]) -> List[dict]:
    """The declarations records among *records*, in the order they were
    written.

    Plural, and that is the point: a resumed run resolves its plane again
    and writes what it found, so a log may hold several — and the
    difference between the first and the last is exactly *what changed
    about the plane while this run was away*.  A reader wanting what the
    run is steering under now takes the last; a reader wanting to know
    whether anything moved compares them.
    """
    return [record for record in records
            if isinstance(record, dict) and DECLARATIONS_KEY in record]


def replay_reasoning(path: Any) -> CognitiveState:
    """The state a :data:`REASONING_LOG` is, rebuilt.

    Through :meth:`~core.cognition.state.CognitiveState.replay` and the
    kernel's own envelope, so the kernel's version check runs on the version
    the header recorded rather than on this reader's opinion of it.  There is
    no second application path here for the reason there is none there: a
    rebuild that did its own bookkeeping would be a second engine, and the
    day the two disagreed the rebuild would be the one nobody checked.
    """
    return _state_of(*read_reasoning(path)[:2])


def _state_of(header: Optional[dict], events: List[dict]) -> CognitiveState:
    """The kernel's envelope around a log's events, and its own replay.

    One function because two callers need it — :func:`replay_reasoning` and
    :func:`open_shadow`'s resume branch — and a second spelling of "what
    version was this log written under" is a second answer to the question
    the header exists to settle.
    """
    version = (header or {}).get(KERNEL_SCHEMA_KEY, EVENT_SCHEMA_VERSION)
    # The version is PASSED THROUGH, not replaced with this kernel's: replay
    # semantics are version-aware, so a log written under schema 1 has to be
    # rebuilt under schema-1 rules, and handing the current number over would
    # be this reader claiming the log said something it did not.
    #
    # `count` because a schema-2 snapshot must state one — and it is honestly
    # vacuous HERE, which is worth saying rather than leaving to be noticed.
    # The kernel's count catches a log cut at the tail, a cut that numbers
    # perfectly and reads as a complete shorter session. This reader derives
    # the count from the lines it just read, so it can never disagree with
    # them; and a prefix of THIS file is not a corruption but the ordinary
    # state of a killed run, which is exactly what `open_shadow` resumes
    # from. The check the kernel needs is not the check this log needs, and
    # the field is filled in truthfully rather than faked or omitted.
    return CognitiveState.replay({KERNEL_SCHEMA_KEY: version,
                                  KERNEL_COUNT_KEY: len(events),
                                  KERNEL_EVENTS_KEY: events})


# ── what the supervisor is told ──────────────────────────────────────────────


@dataclass(frozen=True)
class Progress:
    """One step's worth of "has the run's belief moved", in four numbers.

    ``ROADMAP.md`` §2.9.6 (Phase 19) asks the supervisor to evolve from
    procedural repetition to **epistemic progress**: *frontier unchanged, no
    predicate resolved, no contradiction reduced* is the stall.  This is the
    reading, and it is deliberately tiny — four scalars and a line of prose,
    compared step to step by :class:`core.runtime.supervisor.Supervisor`,
    which never sees the store itself.

    A digest and not the frontier, for the reason
    :class:`core.runtime.supervisor._Act` holds one: a frontier of a hundred
    obligations is compared against the last one on every step boundary, and
    a comparison that walks two lists of records is a comparison somebody
    will be tempted to make cheaper by making it partial.

    ``owed`` is the **top** of the ranked frontier as the model reads it —
    through :func:`core.cognition.compile.owed_line`, which is the one owner
    of that spelling — so that a review quoting what has not moved quotes
    the same words the compiled block showed.
    """

    #: A stable fingerprint of the ranked frontier: every obligation's id
    #: and state, in order, plus whether the walk was cut short.
    frontier: str
    #: How many obligations are unresolved.
    obligations: int
    #: How many contradictions are open.
    contradictions: int
    #: How many propositions the store holds, live or not.
    propositions: int
    #: The first line of :data:`frontier`, rendered.  ``""`` when nothing
    #: is owed.
    owed: str = ""


def _frontier_digest(frontier: Any) -> str:
    """The ranked frontier as one short string.

    Over ``(id, state)`` per obligation **in order**, because all three move
    when the run learns something: an obligation resolved leaves the list,
    one whose premise was bound changes id (the id is content-addressed on
    the pattern as resolved so far), and one that stops being blocked
    changes state and position.  The truncation flag is in it too — a walk
    that starts hitting the store's cap is a different frontier from one
    that did not, and the honest thing is for the digest to say so.
    """
    body = "\n".join(f"{item.id}\t{item.state.value}" for item in frontier)
    flag = "+" if getattr(frontier, "truncated", False) else "-"
    return hashlib.blake2s(f"{flag}\n{body}".encode("utf-8", "replace"),
                           digest_size=8).hexdigest()


# ── the attachment ───────────────────────────────────────────────────────────


class ShadowCognition:
    """One run's cognitive state, fed by receipts and written down.

    Built by :func:`open_shadow` and carried on
    :attr:`core.runtime.run.Store.cognition`, which the loop duck-types for
    :attr:`~core.runtime.run.Store.recorder`'s reason: the run module holds
    the fact that there is one and does not need its type.

    A child run shares its parent's :class:`~core.runtime.run.Store` by
    identity and therefore shares this object — one state per *run*, which
    is what the kernel's single-writer rule wants and what makes a staged
    turn's stages one belief rather than five.  The lock below is not a
    licence to write from two threads: the gathered children of a turn
    reach this from one event loop, so the order is the order they
    finished in.  It is there because a torn file is worse than a
    surprising one.
    """

    def __init__(self, path: Any, run_id: str = "", *,
                 state: Optional[CognitiveState] = None,
                 written: int = 0, compiling: bool = False,
                 budget_chars: int = BUDGET_CHARS) -> None:
        #: Where the log is.
        self.path = Path(path)
        #: The run whose receipts these are — the first term of every
        #: evidence locator, and the one thing in this object that differs
        #: between a recorded run and a replay of it.
        self.run_id = str(run_id or "")
        #: The kernel's store.  Readable: a test, and one day a consumer,
        #: asks it what the run believes.
        self.state = state if state is not None else CognitiveState()
        #: How many of ``state.events`` are on the disk already.
        self._written = int(written)
        self._lock = threading.RLock()
        #: Receipts offered to :meth:`receipt`.
        self.receipts = 0
        #: Propositions asserted out of them.
        self.observations = 0
        #: Declared identifiers asserted as facts — the string exception.
        #: Counted apart from :attr:`observations` because they are the one
        #: thing in the store that is there on a platform's word that a key
        #: is an identity, and a deployment measuring what its declarations
        #: bought reads this against :attr:`links`.
        #:
        #: **Not one per link**: a receipt naming two kinds of subject
        #: writes no identifier fact at all and still links, which is
        #: :meth:`_identify`'s cross-kind guard.
        self.identifiers = 0
        #: Links made out of them.  Fewer than :attr:`identifiers` where a
        #: subject could not be spelled from a value the receipt carried.
        self.links = 0
        #: Identities this receipt named that could not be linked, because
        #: the receipt holds no fact for a link to be a claim about: a
        #: payload of nothing but handles of **several** kinds.  Its own
        #: counter and not :attr:`refused`, because nothing was refused —
        #: the runtime declined to manufacture a cross-kind fact, which is
        #: :meth:`_identify`'s stated bound rather than a value the store
        #: would not take.
        self.unlinked = 0
        #: Declared identifier keys that held **two** values in one receipt
        #: and therefore identified nothing.  The one-figure discipline,
        #: applied to identities: see :func:`identities_of`.
        self.ambiguous = 0
        #: Values the kernel would not take, or the harvest could not
        #: render.  A count and not a refusal — see the module docstring.
        self.refused = 0
        #: How many times something in here raised.  Never more than one:
        #: the first one turns cognition off.
        self.failures = 0
        #: Whether cognition is still running for this run.
        self.on = True
        #: Whether this run's model input carries the compiled view —
        #: ``--compiled-context``.  **Off unless somebody asked**, and the
        #: only switch in this package that changes a prompt.
        self.compiling = bool(compiling)
        #: The compiler's hard cap, in characters.
        self.budget_chars = int(budget_chars)
        #: How many blocks were handed to the loop.
        self.compiled = 0
        #: How many times the compiler raised.  Never more than one: the
        #: first one stops compiling and leaves the harvest running.
        self.compile_failures = 0
        #: The :class:`RulePack` this run's skill loaded, or ``None`` — for a
        #: run with no pack, and for one whose pack did not load.  A caller
        #: that wants to SAY a run is reasoning under rules reads this;
        #: nothing in the loop does.
        self.pack: Optional[RulePack] = None
        #: ``(fields, rules, goals)`` the pack wrote.  Zeroes until one does.
        self.loaded: Tuple[int, int, int] = (0, 0, 0)
        #: Whether :meth:`progress` is still answering.  Its own switch and
        #: not :attr:`on`: a frontier read that raises must cost the signal
        #: that reads it and nothing else.
        self.watching = True
        #: How many progress digests were handed out.
        self.watched = 0
        #: How many times :meth:`progress` raised.  Never more than one.
        self.watch_failures = 0
        #: What the plane this run connected to declares about what its
        #: tools return — a
        #: :class:`core.runtime.declarations.PlaneDeclarations`, or ``None``
        #: until :meth:`declare_plane` is called with one.  Two things read
        #: it: :meth:`_identify`, at every receipt, for the identifier keys
        #: of the dispatching tool; and :meth:`resolvers`, at every compiled
        #: block, for what the plane says would answer an owed line.
        self.declarations: Any = None
        #: :func:`resolvers_of` of them, worked out once.  ``None`` is *not
        #: yet asked*; an empty mapping is *asked, and this plane declares
        #: nothing that resolves anything*.  Both are quiet, and the
        #: difference is one walk of the declarations per run instead of one
        #: per step.
        self._resolvers: Optional[Dict[str, Tuple[str, ...]]] = None

    # ── what the door calls, once ───────────────────────────────────────

    def load_pack(self, block: Any) -> None:
        """A skill's ``cognition:`` block, into this store.  Never raises.

        **Before the first receipt**, which is the only moment it can happen
        at: a rule promoted after the observations it would have fired on
        still derives — the kernel joins a rule delta against the whole
        store — but a *goal* added late means a frontier that was empty
        while the mission was deciding what to do, and the obligations a
        pack exists to produce would arrive after the steps they were for.
        :func:`open_shadow` is the one caller, at the one moment.

        Total, like everything else a mission can reach: a pack that will
        not load **stops cognition for the run** and writes
        :data:`UNLOADED_NOTE`.  Stopping is right rather than carrying on
        without the rules — a shadow that harvested under a pack its author
        thinks is loaded would report an empty frontier as a finding — and
        stopping *the mission* would be wrong, which is the floor rule
        (``ROADMAP.md`` §2.9.3: cognition-on never blocks an answer).

        A block that is ``None`` is a skill that wrote no cognition, and a
        pack that declares nothing writes nothing: both leave this object
        exactly as it was, which is the shadow the flag alone has always
        been.
        """
        if block is None or not self.on:
            return
        with self._lock:
            try:
                pack = (block if isinstance(block, RulePack)
                        else RulePack.from_mapping(block))
                counts = pack.load_into(self.state)
                self._flush()
            except Exception as exc:                # noqa: BLE001 - the point
                self._unloaded(exc)
                return
            self.pack = pack
            self.loaded = counts

    def declare_plane(self, declarations: Any) -> None:
        """What the plane declares, written into the log.  Never raises.

        Called once, at fleet-connect: the moment both halves of a
        declaration are in hand (the server's ``outputSchema`` and the
        composed manifest's ``tools:`` block) and the first moment there is
        anything to write.  It lands after the header — and, on a fresh
        run, after the pack's own events, which is where a reader wants it:
        the pack is what this store believes before any receipt, and this
        is what the *plane* says about receipts that have not happened yet.

        **One record, not a merge.**  A resumed run resolves its plane
        again and appends its own, so a log may hold two — and two that
        differ is the honest rendering of a plane that changed while the
        run was away.  Rewriting the first would be this module deciding
        which of two true statements about two moments to keep.

        Nothing is written for declarations that declare nothing **and
        disagree about nothing**: a record saying a plane said nothing is a
        line a reader has to interpret, and an absent one already means it.
        A discrepancy alone is enough to write one — a server whose
        extension key this reader could not use has said something about
        the plane even though it declared nothing, and that is precisely
        the thing nobody would otherwise find out.

        Total, like every other call on this object: a log that cannot be
        written must not cost a mission, and a shadow that stopped stays
        stopped.
        """
        if declarations is None or not self.on:
            return
        with self._lock:
            try:
                if declarations or declarations.discrepancies:
                    fsync_append(self.path,
                                 canonical(declarations.as_record()))
            except Exception as exc:                # noqa: BLE001 - the point
                self._stopped(exc)
                return
            self.declarations = declarations
            # A second resolution — a resumed run's plane — replaces the
            # first, hints included. The record keeps both; what a run
            # STEERS under is what it last resolved, which is the same rule
            # `declarations_in`'s docstring states for its readers.
            self._resolvers = None

    def resolvers(self) -> Dict[str, Tuple[str, ...]]:
        """What this plane says would establish each field.  Never raises.

        :func:`resolvers_of` of :attr:`declarations`, worked out on the
        first ask and quoted afterwards — the declarations are immutable
        once built, so a second walk could only produce the same answer at
        the cost of one per step.

        Handed to :func:`~core.cognition.compile.compile_view` **and** to
        :func:`~core.cognition.compile.owed_line` in :meth:`progress`, which
        is the point of it being a method rather than a thing the compiler
        reaches for: the line the model reads and the line the supervisor's
        stall sentence quotes are then the same line, hint and all.
        """
        if self._resolvers is None:
            self._resolvers = resolvers_of(self.declarations)
        return self._resolvers

    # ── what the loop calls ─────────────────────────────────────────────

    def receipt(self, tool: str, seq: Any, text: Any = "",
                evidence: Any = "") -> None:
        """One tool result, harvested and asserted.  Never raises.

        *evidence* is the typed payload where a tool returned one —
        ``structuredContent`` from an MCP server, which is where the fields
        actually are — and *text* is what the tool wrote.  The typed half
        wins when there is one, because a rendering of a payload is not the
        payload: that is the same rule
        :meth:`core.runtime.replay.Recorder.dispatch` records under.

        Staging only.  No :meth:`~core.cognition.state.CognitiveState.derive`
        happens here even when a turn made one call, so that a native turn
        with four parallel calls and a JSON turn with one produce the same
        shape of log: one flush per step, at :meth:`close_step`.
        """
        if not self.on:
            return
        with self._lock:
            try:
                self._observe(str(tool or ""), seq, evidence or text)
            except Exception as exc:                # noqa: BLE001 - the point
                self._stopped(exc)

    def close_step(self) -> None:
        """The step is over: derive once, append what that produced.

        Idempotent by construction and that is load-bearing, because the
        loop has many exits and the last step's boundary is the ``finally``
        in :meth:`core.runtime.run.Run.arun` rather than the top of a
        further iteration.  A flush with nothing staged appends no kernel
        event — the kernel's own rule — so a second call writes nothing and
        the log stays a function of the writes and not of who closed it.
        """
        if not self.on:
            return
        with self._lock:
            try:
                self.state.derive()
                self._flush()
            except Exception as exc:                # noqa: BLE001 - the point
                self._stopped(exc)

    def compiled_block(self) -> str:
        """This step's compiled view, or ``""``.  Never raises.

        The **whole** of what ``--compiled-context`` adds to a mission, and
        it is one string: :func:`core.cognition.compile.compile_view` over
        the state this object already holds, rendered under
        :attr:`budget_chars`.  The loop appends it and nothing else
        happens — no record, no file, no gate, and no second copy of the
        state anywhere.

        ``""`` for every reason there is not to show one, and the caller
        cannot tell them apart because none of them is its business: the
        flag is off, cognition stopped, the state is empty (a mission that
        has taken no receipt has nothing to be shown), or the compiler
        raised.

        **Called after** :meth:`close_step`, which is what makes this a
        cheap read: the kernel flushes on every read, and the flush the
        step's own boundary already did leaves nothing staged for this one
        to write.  Compiling before the boundary would move a ``derive``
        event from the boundary to whoever looked first, which is the
        defect ``M2`` of the kernel review was about.
        """
        if not self.compiling or not self.on:
            return ""
        with self._lock:
            try:
                view = compile_view(self.state,
                                    budget_chars=self.budget_chars,
                                    resolvers=self.resolvers())
            except Exception as exc:                # noqa: BLE001 - the point
                self._uncompiled(exc)
                return ""
            if not view:
                return ""
            self.compiled += 1
            return view.text

    def progress(self) -> Optional["Progress"]:
        """This step's epistemic-progress digest, or ``None``.  Never raises.

        What the supervisor compares step to step (§2.9.6): the frontier's
        fingerprint, how much is owed, how much is contested and how much is
        believed.  It **decides nothing** — the whole of the deciding is
        :meth:`core.runtime.supervisor.Supervisor.look`, and the whole of
        what that can do is raise the advisory review it already raises for
        a repeated call.

        ``None`` for every reason there is not to have one, and the caller
        cannot tell them apart because none of them is its business:
        cognition is off, cognition stopped, or this read raised.  A
        supervisor handed ``None`` for a step simply has no window to
        compare, which is the failure isolation written as a return value —
        the signal stops, the supervisor's other four do not, and the
        mission never learns.

        **Called after** :meth:`close_step`, for
        :meth:`compiled_block`'s reason: every kernel read flushes, and the
        step's own boundary has already done that, so this one appends no
        event.
        """
        if not self.on or not self.watching:
            return None
        with self._lock:
            try:
                frontier = self.state.ranked_frontier()
                clashes = sum(1 for clash in self.state.contradictions()
                              if not clash.settled)
                digest = _frontier_digest(frontier)
                top = (owed_line(frontier[0], self.resolvers())
                       if frontier else "")
                held = len(self.state.propositions())
            except Exception as exc:            # noqa: BLE001 - the point
                self._unwatched(exc)
                return None
            self.watched += 1
            return Progress(frontier=digest, obligations=len(frontier),
                            contradictions=clashes, propositions=held,
                            owed=top)

    # ── the inside ──────────────────────────────────────────────────────

    def _observe(self, tool: str, seq: Any, text: Any) -> None:
        entity = f"{tool}#{seq}"
        ref = EvidenceRef(kind=RECEIPT_KIND,
                          locator=f"{self.run_id}/{seq}/{tool}")
        self.receipts += 1
        held = 0
        for field, value in observations_of(text):
            try:
                self.state.assert_observation(
                    (entity, field, value), evidence=(ref,),
                    authority=EvidenceAuthority.DETERMINISTIC)
            except CognitionError:
                # The store said no to one value. That is the store working,
                # and the receipt's other fields are still worth having.
                self.refused += 1
                continue
            self.observations += 1
            held += 1
        # `held` and not a second look at the store: whether this receipt
        # entity holds anything is what decides whether a link can be made
        # at all, and this loop is the only thing that put anything there.
        self._identify(tool, entity, ref, text, held)

    def _identify(self, tool: str, entity: str, ref: EvidenceRef,
                  text: Any, held: int = 0) -> None:
        """What this receipt is *about*, where the plane declared it.

        Two writes per identifier and they are in this order for a reason
        the kernel enforces: the **fact** first — the declared string as a
        claim on the receipt entity, which is what makes a handle-only
        receipt a receipt this store holds something about — and then the
        **link**, which :meth:`~core.cognition.state.CognitiveState.link`
        refuses for an entity it knows nothing about.  A store that linked
        first would refuse every two-phase handle in the design's own
        motivating example.  *held* is how many facts this receipt's own
        harvest already put there, so the order question is answered
        without asking the store twice.

        **An identifier fact is written to the receipt only where the
        receipt names ONE kind of subject**, and this is the guard that
        keeps the design's own red line.  The kernel projects every live
        triple of a linked entity onto **every** subject that entity is
        linked to — correctly, for figures: a call that read 12,481 records
        while naming a job and an asset read them about both.  An
        *identifier* is the one fact that is not about both.  A tool
        declaring ``job_id`` and ``asset_id`` would otherwise put
        ``job_id`` onto the asset and ``asset_id`` onto the job, and two
        such receipts sharing one asset would put two different ``job_id``
        values on it — a contradiction manufactured out of two calls that
        never disagreed, which is exactly what "no link on value
        coincidence" exists to prevent, arriving through the back door.

        The guard is here and **not** in the kernel on purpose: kinds are a
        *declaration*, the kernel knows nothing about tools or planes, and
        teaching its projection rule about them would put the plane's
        vocabulary inside the store's engine.  The runtime holds the
        declaration; the runtime decides what it writes.

        What that costs, stated rather than discovered: **a receipt that
        returns nothing but handles of several kinds is not linked at
        all** — it holds no fact for a link to be a claim about, and the
        alternative is the manufactured contest above.  It is counted in
        :attr:`unlinked`.  Its subjects are not lost: the call that
        *establishes* something about one of them (a status call naming one
        kind) links and projects normally, which is the two-phase flow the
        design is built on.  Lifting the bound means giving each kind its
        own receipt-scoped entity so that one link cannot carry another
        kind's identity — v1.1 work, with a spelling that keeps a handle
        quotable at the result store.

        The link's evidence is both premises, named: the receipt this value
        was read from, and the declaration that said the key was an
        identity (:data:`DECLARATION_KIND`).  Its authority is ``SOURCE``,
        which is the weaker of the two and therefore the honest one — the
        receipt is deterministic, the declaration is a platform's word, and
        a link is worth its weakest premise.  Every fact this link projects
        onto the subject is capped by it, in the kernel, which is where
        that cap belongs.

        **Deterministic links only, in v1.**  Nothing here guesses: no value
        coincidence, no key-name similarity, no model proposal.  A wrong
        link is therefore a wrong *declaration* — wrong for every receipt
        of that tool rather than at random — and it is fixed in the file
        that declared it.  See
        :meth:`~core.cognition.state.CognitiveState.link_history` for why
        that ruling is what makes the absence of an ``unlink`` liveable.

        Failure-isolated per identifier, in this module's one idiom: a
        value the kernel will not take — a subject that cannot be spelled
        from it, a string spelled like a rule variable — is counted in
        :attr:`refused` and the receipt's other identifiers still land.
        Anything else reaches :meth:`receipt`'s ``except``, where it costs
        the run its cognition and a note, and the mission is not told.
        """
        declarations = self.declarations
        if declarations is None:
            return
        identifiers = declarations.identifiers_for(tool)
        if not identifiers:
            return
        found, ambiguous = identities_of(text, identifiers)
        self.ambiguous += ambiguous
        if not found:
            return
        # THE CROSS-KIND GUARD. See the method docstring: an identifier
        # fact is asserted on the receipt only where this receipt names ONE
        # kind of subject, because the kernel projects every live triple of
        # a linked entity onto EVERY subject that entity is linked to.
        one_kind = len({identity.kind for identity in found}) == 1
        for identity in found:
            if one_kind:
                try:
                    self.state.assert_observation(
                        (entity, identity.field, identity.value),
                        evidence=(ref,),
                        authority=EvidenceAuthority.DETERMINISTIC)
                except CognitionError:
                    self.refused += 1
                    continue
                self.identifiers += 1
                held += 1
            if not held:
                # Nothing to be a claim about: a receipt that returned
                # nothing but handles of SEVERAL kinds. Counted, never
                # forced — see the docstring's bound.
                self.unlinked += 1
                continue
            try:
                self.state.link(
                    entity, identity.subject(),
                    evidence=(ref, self._declared(tool, identity)),
                    authority=EvidenceAuthority.SOURCE)
            except CognitionError:
                self.refused += 1
                continue
            self.links += 1

    def _declared(self, tool: str, identity: "Identity") -> EvidenceRef:
        """The link's other premise: the declaration, located and named.

        The locator says which door won the verb for this tool (``wire`` or
        ``manifest`` — :attr:`core.runtime.declarations.ToolDeclaration
        .sources`), the tool, and the key path as declared.  That is the
        sentence a reader of ``reasoning.jsonl`` needs to find the thing
        that has to change if a link turns out to be wrong; the kernel
        never dereferences it and has no opinion about its shape.
        """
        declaration = self.declarations.for_tool(tool)
        door = str((getattr(declaration, "sources", None) or {}).get(
            IDENTIFIERS) or "")
        locator = "/".join(part for part in (door, str(tool), identity.path)
                           if part)
        return EvidenceRef(kind=DECLARATION_KIND, locator=locator,
                           note=f"declared identifier of kind "
                                f"{identity.kind!r}")

    def _flush(self) -> None:
        """Everything the kernel has logged since the last flush, appended.

        Through :meth:`~core.cognition.state.CognitiveState.events_since`
        rather than by slicing :attr:`~core.cognition.state.CognitiveState
        .events`, which is the whole log.  This runs once a step, and a
        reader that walks the whole log to find its tail turns an append
        into an O(n) operation and a long mission into a quadratic one.
        The cursor is the kernel's own ``n`` — the number on the last event
        written — which is the same shape and the same argument as the run
        store's ``seq``, and it is taken from the event rather than counted
        here so that the two can never disagree about where the tail is.

        **One append per step, and what that costs.**  Measured on this
        tree (``scratchpad``, 30 steps, warm page cache): a step harvesting
        twenty fields costs a **median 6.4 ms** here, against 122 ms when
        each event was its own ``fsync_append`` — the per-event version
        paid one disk sync per figure, inside the loop's own turn.  A step
        harvesting two fields costs 5.8 ms against 19.9 ms.  The floor is
        one ``fsync``, so the number is about flat in the number of fields,
        which is the property worth having: a receipt with a hundred
        figures does not cost a hundred times a receipt with one.

        A step is the right unit to be durable at, and it is also the
        honest one: a crash mid-step loses that step's events, and that
        step had not been closed.
        """
        fresh = self.state.events_since(self._written)
        if not fresh:
            return
        # ONE append for the step, not one per event. The format is
        # unchanged — these are the same lines in the same order — and what
        # goes is the per-event `fsync`, which is the whole cost: a step
        # that harvested twenty fields used to pay twenty disk syncs inside
        # the loop's own turn. A step is the unit that is durable, which is
        # also the honest boundary: a crash mid-step loses that step's
        # events, and that step had not been closed.
        #
        # `deep_copy` and not `dict(event)`: the kernel hands back views
        # that are read-only ALL THE WAY DOWN — tuples for sequences,
        # `MappingProxyType` for mappings — so that a reader after every
        # write is not a copy of the whole log each time. Neither is JSON,
        # and under `canonical`'s `default=str` neither FAILS: a shallow
        # `dict` writes each evidence ref's *repr* as a JSON string, and
        # the file then replays as a log of records holding strings where
        # their evidence should be. Through the kernel's own copy owner,
        # which is the whole reason it has one — a second recursive walk
        # over a record here would be the next place the same bug lands.
        fsync_append(self.path, "\n".join(
            canonical(deep_copy(event)) for event in fresh))
        self._written = int(fresh[-1]["n"])

    def _uncompiled(self, exc: BaseException) -> None:
        """The view is over for this run; the store goes on believing.

        The narrower sibling of :meth:`_stopped`, and narrow on purpose: a
        compiler that cannot render is not a store that cannot hold.  The
        harvest keeps running, the log keeps growing, and the only thing
        that stops is the block the model was being shown — which is
        exactly the mission that would have run with the flag off.
        """
        self.compile_failures += 1
        self.compiling = False
        try:
            fsync_append(self.path, canonical({
                NOTE_KEY: UNCOMPILED_NOTE,
                "error": f"{type(exc).__name__}: {exc}",
                "written": self._written,
            }))
        except Exception:                           # pragma: no cover
            pass

    def _unloaded(self, exc: BaseException) -> None:
        """The pack did not load; this run has no cognition at all.

        The sibling of :meth:`_stopped` with its own sentence, and the wider
        of the two in what it turns off: a pack is the rules and the goals a
        run was meant to reason under, and harvesting on without them would
        leave a log whose empty frontier reads as a finding.  So the switch
        goes, the note says which half failed, and the mission — which has
        not started yet — is not told.

        The store may hold half a pack when this runs, and the log does not:
        the flush is what did not happen.  That is the honest pairing rather
        than a defect to repair, because the log is the state and a state
        nothing will read again is not worth reconciling; a reader that sees
        this note knows the file is not a pack and never became one.
        """
        self.failures += 1
        self.on = False
        try:
            fsync_append(self.path, canonical({
                NOTE_KEY: UNLOADED_NOTE,
                "error": f"{type(exc).__name__}: {exc}",
                "written": self._written,
            }))
        except Exception:                           # pragma: no cover
            pass

    def _unwatched(self, exc: BaseException) -> None:
        """The progress signal is over for this run; everything else runs.

        The narrowest of the three, and narrow for :meth:`_uncompiled`'s
        reason one step further: a frontier this run cannot read is not a
        view it cannot render and is certainly not a store it cannot hold.
        What stops is one input to one advisory signal; the supervisor keeps
        its four mechanical ones, the model keeps its block, and the mission
        is the mission it would have been.
        """
        self.watch_failures += 1
        self.watching = False
        try:
            fsync_append(self.path, canonical({
                NOTE_KEY: UNWATCHED_NOTE,
                "error": f"{type(exc).__name__}: {exc}",
                "written": self._written,
            }))
        except Exception:                           # pragma: no cover
            pass

    def _stopped(self, exc: BaseException) -> None:
        """Cognition is over for this run, and the log says so.

        The counter, the switch and the note, in that order, and then
        nothing: the caller returns to a mission that does not know this
        happened.  The note is written best-effort — a log that could not
        be written must not cost a mission, which is the rule
        :meth:`core.runtime.replay.RecordingBus.dispatch` already swallows
        its own failures under.
        """
        self.failures += 1
        self.on = False
        try:
            fsync_append(self.path, canonical({
                NOTE_KEY: STOPPED_NOTE,
                "error": f"{type(exc).__name__}: {exc}",
                "written": self._written,
            }))
        except Exception:                           # pragma: no cover
            pass


def open_shadow(store: Any, run_id: str, *,
                resumed: bool = False, compiling: bool = False,
                budget_chars: int = BUDGET_CHARS,
                cognition_block: Any = None) -> ShadowCognition:
    """The shadow for *run_id* in *store*: a new one, or the one on disk.

    *store* is a :class:`core.durable.RunStore`; it is asked for the run's
    directory and nothing else.  *compiling* and *budget_chars* are
    ``--compiled-context`` and its cap, carried straight onto the object on
    both paths below — a door that resolved them on one path only is a
    resumed run that quietly stopped showing the model its own view.  The
    one door, so that "does this run already have a reasoning log?" is
    answered once:

    * **no file** — a fresh state, and the header written now, so that a run
      whose first step harvests nothing still leaves a versioned log rather
      than an absent one a reader cannot tell from a run that never had
      cognition on;
    * **a file** — ``--resume``.  The events are replayed through the kernel,
      the write cursor is set past them, and no second header is written.
      Appending from zero would give the resumed store every observation
      twice, which is a store that contradicts itself about facts nobody
      disagreed about.  The header's engine version is **recorded and not
      enforced** on this path: a log written by an older engine replays
      into this one correctly — every op is applied through the same public
      method that wrote it — and what a different engine changes is which
      ``pN`` a *derived* conclusion gets.  A run under a
      :class:`RulePack` does derive, which is exactly why the field is
      written down; a consumer that persists an id out of one of these logs
      is the one that needs it.

    *cognition_block* is the composed manifest's ``cognition:`` block — a
    :class:`RulePack`, or the raw mapping one is read from — and it is
    loaded **on the fresh path only**, before the object is handed back and
    therefore before the first receipt.  On the resume path it is
    deliberately not loaded and not even compared: the log already holds
    the ``declare_field``/``add_rule``/``promote_rule``/``add_goal`` events
    of the process that loaded it, the replay above has just applied them,
    and loading again would give the resumed store two copies of every
    clause — a second rule id deriving the same conclusion a second way,
    and a frontier counting each obligation twice.  The pack is in the log
    because every write went through the kernel's ordinary doors, which is
    the whole reason those doors are the only ones used.

    **The one call in this module that raises**, and deliberately: a log
    this reader or the kernel cannot trust is a
    :class:`~core.cognition.types.ReplayRefused` — no header, a version from
    the future, an ``n`` that is not its position, evidence that is not a
    list of refs.  Refusing is right; the *mission* refusing for it would
    not be, so ``core.cli`` catches this one exception and runs with no
    shadow rather than half of one.  A library caller building
    :class:`~core.runtime.run.Store` by hand owes the same ``try``.
    """
    directory = Path(store.directory(run_id))
    path = directory / REASONING_LOG
    view = {"compiling": compiling, "budget_chars": budget_chars}
    if path.exists():
        header, events, _notes = read_reasoning(path)
        # Through `_state_of`, which exists so that "what version was this
        # log written under" is answered in one place; re-spelling the
        # envelope here would be the second owner the function was written
        # to prevent.
        #
        # And this is the whole of `--resume` for the compiled view: the
        # state comes back out of the log and the next block is compiled
        # from it, so a resumed run's model reads what the first process
        # believed. NOTHING extra is persisted for it — a view is a
        # rendering of the store, and a rendering written down is a second
        # copy of a fact that already has an owner.
        return ShadowCognition(path, run_id, state=_state_of(header, events),
                               written=(int(events[-1]["n"]) if events
                                        else 0), **view)
    fsync_append(path, canonical(header_record()))
    if resumed:
        # THE GAP, said out loud. A resumed run re-records its recorded
        # results into the result store (`core.runtime.resume`) rather than
        # dispatching them, and that path has no cognition in it and should
        # not — re-harvesting a receipt this run already holds would be a
        # second attachment point, which is the defect this module's one
        # attachment exists to avoid. So a run recorded WITHOUT the flag and
        # resumed WITH it starts believing at the resume, and the log that
        # results is complete-looking and partial.
        #
        # Silence is never the answer: the note is line two, before any
        # event, and a reader that sees it knows the receipts before the
        # resume were never offered to this store. It is the sibling of
        # `STOPPED_NOTE` and it is not an error — this is a working shadow
        # that started late, not a broken one.
        fsync_append(path, canonical({NOTE_KEY: RESUMED_NOTE}))
    shadow = ShadowCognition(path, run_id, **view)
    # The pack, after the header and the note and before anything else: the
    # notes are about the FILE and the pack is the first thing the STORE
    # believes. `load_pack` is total, so a block that will not load costs
    # this run its cognition and costs the caller nothing — the same
    # contract every other call on the object has.
    shadow.load_pack(cognition_block)
    return shadow
