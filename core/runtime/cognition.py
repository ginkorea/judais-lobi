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
well.  With the flag on, the only difference a run makes is
:data:`REASONING_LOG` and the console line announcing it: no prompt changes,
no call is made or withheld, no gate is added, and nothing on the wire moves.
**Nothing in this module may fail a mission.**  Every public method is total:
an exception inside one is counted, stops cognition for the rest of the run,
writes one note into the log and returns.  A mission does not find out.

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
sums.  Measured on this tree: **95 ms** for a store of four thousand live
facts, and a fraction of a millisecond for the dozens a real mission holds
— it is **linear in what the store believes**, not in what the block shows,
because a fact must be graded before it can be ranked out.  It was 482 ms
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

:meth:`~core.runtime.run.Run._loop` closes the step.  That is the kernel
review's M2 ruling written into the harness: :meth:`ShadowCognition.receipt`
stages, and :meth:`ShadowCognition.close_step` is the **one defined flush
point per turn** — one :meth:`~core.cognition.state.CognitiveState.derive`,
then the events it produced are appended.  Nothing here calls ``frontier`` or
``contradictions``: in v1 nothing consumes them, and a read that flushed the
staging area at an undefined moment would put the log's shape at the mercy of
who happened to look.

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

Five bounds, each stated because each is a thing the store does **not** know:

* **Non-JSON receipts contribute nothing.**  A receipt is parsed with
  :func:`core.runtime.grounding.json_blocks` — the harness's one reader of
  "is there JSON in this text" — and prose yields no blocks and therefore no
  propositions.  Turning a sentence into a claim is *extraction*, it is a
  model's job, and its reliability is Phase 16's number, not this file's
  assumption.
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
  key is skipped and counted.  **This module declares no field cardinality
  at all** — no call to
  :meth:`~core.cognition.state.CognitiveState.declare_field` anywhere — and
  that is a decision rather than an omission: undeclared is ``many`` at
  event schema 2, so nothing the shadow asserts can contest anything on a
  receipt that legitimately lists ten runs, and a declaration made here
  would be this file guessing at a schema it is reading rather than
  writing.  A rule pack that wants ``one`` for a field says so itself.
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
own single application path.  A ``note`` line is the one exception and it is
not an event: it says cognition stopped and why, and a reader skips it.

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

import json
import math
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.cognition import EVENTS_KEY as KERNEL_EVENTS_KEY
from core.cognition import SCHEMA_KEY as KERNEL_SCHEMA_KEY
from core.cognition import COUNT_KEY as KERNEL_COUNT_KEY
from core.cognition import (BUDGET_CHARS, EVENT_SCHEMA_VERSION, KERNEL_KEY,
                            KERNEL_VERSION, CognitionError, CognitiveState,
                            EvidenceAuthority, EvidenceRef, ReplayRefused,
                            compile_view, deep_copy)
from core.durable import fsync_append
from core.runtime.grounding import harvest_fields, json_blocks
from core.runtime.replay import canonical

__all__ = [
    "REASONING_LOG", "REASONING_SCHEMA_VERSION", "SCHEMA_KEY",
    "KERNEL_SCHEMA_KEY", "KERNEL_KEY", "KERNEL_EVENTS_KEY",
    "KERNEL_COUNT_KEY", "NOTE_KEY", "RECEIPT_KIND", "RESUMED_NOTE",
    "STOPPED_NOTE", "UNCOMPILED_NOTE",
    "ShadowCognition", "header_record", "observations_of", "open_shadow",
    "read_reasoning", "replay_reasoning",
]

#: The shadow's file, in the run directory beside ``events.jsonl``.
REASONING_LOG = "reasoning.jsonl"

#: The shape of THIS file — the header, the note line, which records are
#: events.  Bumped when that shape changes.  Not the kernel's version (the
#: header carries that too, under :data:`~core.cognition.events.SCHEMA_KEY`)
#: and emphatically not :data:`core.runtime.contract.SCHEMA_VERSION`: three
#: numbers because three things change for three different reasons.
REASONING_SCHEMA_VERSION = 1

#: The key the header states :data:`REASONING_SCHEMA_VERSION` under, and the
#: key that identifies the header line.
SCHEMA_KEY = "reasoning_schema"

#: The key a note line carries.  A note is not an event and is never replayed.
NOTE_KEY = "note"

#: What an :class:`~core.cognition.types.EvidenceRef` out of this module
#: calls itself.  The kernel never dereferences it; a reader of the log does.
RECEIPT_KIND = "receipt"

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

#: The other note, and it is not an error: this log begins at a resume, so
#: the receipts the run took before it were never offered to this store.
#: See :func:`open_shadow` for why that is the correct behaviour and why it
#: has to be written down rather than inferred from a short log.
RESUMED_NOTE = ("this log begins at a resume; the receipts this run took "
                "before it were not harvested")


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

    Three kinds of line and they are told apart by what they carry rather
    than by position: the header states :data:`SCHEMA_KEY`, an event states
    an ``op`` (the kernel's own discriminator — see
    :data:`core.cognition.events.EVENT_OPS`), and anything else is a note.
    Position would be the wrong rule the first time a note lands between
    two events, which is exactly where a note lands.

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
                                    budget_chars=self.budget_chars)
            except Exception as exc:                # noqa: BLE001 - the point
                self._uncompiled(exc)
                return ""
            if not view:
                return ""
            self.compiled += 1
            return view.text

    # ── the inside ──────────────────────────────────────────────────────

    def _observe(self, tool: str, seq: Any, text: Any) -> None:
        entity = f"{tool}#{seq}"
        ref = EvidenceRef(kind=RECEIPT_KIND,
                          locator=f"{self.run_id}/{seq}/{tool}")
        self.receipts += 1
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
                budget_chars: int = BUDGET_CHARS) -> ShadowCognition:
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
      ``pN`` a *derived* conclusion gets.  This module derives nothing,
      because it declares no rules, so there is nothing here for the
      difference to move; a consumer that persists an id out of one of
      these logs is the one that needs the field, which is why it is
      written down.

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
    return ShadowCognition(path, run_id, **view)
