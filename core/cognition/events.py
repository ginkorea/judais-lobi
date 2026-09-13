# core/cognition/events.py — the log a cognitive state is, plus its own version

"""Every mutating call is one plain dict, and the store is their sum.

The store in :mod:`core.cognition.state` keeps indexes, derivations, revisions
and contradictions, and none of that is the state of record.  **The event list
is.**  Indexes are a cache of the log; a store rebuilt by
:meth:`~core.cognition.state.CognitiveState.replay` from the log is the same
store, and if it is ever not, the log wins and the engine has a bug.

**Its own version, deliberately.**  :data:`EVENT_SCHEMA_VERSION` is not
:data:`core.runtime.contract.SCHEMA_VERSION` and must never be confused with
it.  The wire contract is a promise to consumers a platform pins against: it
moves slowly and a rename there is a major event.  This log is internal to the
kernel — the shadow-attachment lane will carry it inside ``reasoning`` records,
but what a consumer *renders* is the record type, not this.  Two versions
because they change for different reasons and at different rates, and a single
number would have made every kernel experiment a wire break.

**Compatibility, in the shape ``CONTRACT.md`` states its own.**  Adding an
``op``, or an optional field to one, raises :data:`EVENT_SCHEMA_VERSION` by a
minor step; renaming, removing, or changing the meaning of a *required* field
is the kind of change that breaks a log, and nothing in this package may make
one.  **An op is never removed and never changes meaning** — that is the whole
of why a version-1 log still replays under version 2, and it is a promise and
not an implementation detail: ``declare_field`` and ``settle`` are new in 2,
every version-1 op reads exactly as it did, and the day one of them would have
to mean something else it gets a new name instead.

A replay refuses a log whose version is *higher* than the one it knows
(:class:`~core.cognition.types.ReplayRefused`) rather than skipping what it
does not recognise — see that exception for why this is the opposite rule from
the wire's.

**The kernel version travels beside the schema version**, and they answer
different questions.  The schema says what the records mean.
:data:`KERNEL_VERSION` says which *engine* wrote them — and that matters
because ids in this package are assigned by insertion order, so two engines
that agree about every claim can still hand out different names for them.  A
consumer that persisted a proposition id is holding something that belongs to
one engine's run; this field is how it finds out.  Replay does not refuse an
unfamiliar kernel version (that would make old logs unreplayable for a reason
that has nothing to do with reading them), it records it.

**Ids are not in the log, except as references.**  ``assert_observation``
carries no proposition id: ids are assigned by insertion order, so the log
*determines* them and writing them down would be a second owner of the same
fact.  ``refute`` and ``promote_rule`` do carry ids, because by then the id
exists and naming it is the only way to say which one.
"""

from __future__ import annotations

from collections.abc import Mapping as _MappingABC
from collections.abc import Sequence as _SequenceABC
from types import MappingProxyType
from typing import Any, Iterable, List, Mapping, Sequence, Tuple

from core.cognition.types import EvidenceRef, ReplayRefused

#: Bump on any change to the shape of an event or the set of ops.
#:
#: 1 — the first shape.
#: 2 — ``declare_field`` and ``settle``. Every version-1 op unchanged.
EVENT_SCHEMA_VERSION = 2

#: Which engine assigned the ids in a log. Not a distribution version and not
#: this package's public API version: it is bumped when a change alters what
#: ids a given sequence of writes produces, so that a consumer holding a
#: persisted proposition id can tell whether it still means anything.
#:
#: 1 — the first engine.
#: 2 — semi-naive closure evaluates the pinned delta premise first, which
#:     changes the order derived conclusions are enumerated in, and therefore
#:     which ``pN`` each one gets. Same claims, different names.
KERNEL_VERSION = 2

#: Every ``op`` this kernel writes and can read back, oldest first. **Append
#: only**: an op is never removed and never changes meaning, which is what
#: makes an older log replayable under a newer schema. A log carrying a name
#: that is not here is refused rather than partially applied.
EVENT_OPS = (
    # — schema 1 —
    "assert_observation",
    "assert_hypothesis",
    "add_rule",
    "promote_rule",
    "add_goal",
    "refute",
    "derive",
    # — schema 2 —
    "declare_field",
    "settle",
)

#: The key a snapshot puts its version under.
SCHEMA_KEY = "event_schema"

#: The key a snapshot puts the engine's version under. Absent in a version-1
#: log, and absent is the correct reading: an engine nobody recorded.
KERNEL_KEY = "kernel"

#: The key a snapshot puts the ordered event list under.
EVENTS_KEY = "events"

#: How many events the writer says it wrote. Schema 2 and later require
#: it, and it exists because `n` cannot catch a log cut at the TAIL: drop
#: the last three events and 1..k-1 still number perfectly. A prefix of a
#: log is the most plausible-looking corruption there is — it is what a
#: truncated write, a partial upload and a half-read file all produce.
COUNT_KEY = "count"


def _copy(value: Any, *, frozen: bool) -> Any:
    """The one recursive walker over a record, in both directions.

    **One owner, because a shallow copy is a forgery waiting to happen.**  An
    event is a dict of plain data — but its ``evidence`` is a list of dicts
    and its ``body`` is a list of lists, and every copy this package made
    stopped at the top level.  So ``snapshot()[…]["evidence"][0]["kind"] =
    …`` edited the store's own record through the copy it had just been
    handed, and ``state.events[0]["evidence"].append(…)`` wrote straight
    through a ``MappingProxyType`` that only froze the outermost mapping.
    Both look like reading.

    Two doors, one walk.  :func:`deep_copy` gives a mutable structure that
    shares no nested object with the original — what a snapshot needs, since
    a caller is expected to serialise it and may reasonably edit it first.
    :func:`freeze` gives the same structure read-only *all the way down* —
    tuples for sequences, ``MappingProxyType`` for mappings — which is what a
    reader of the live log gets, because there is no legitimate reason to
    write to history.

    Scalars are returned as they are: strings, numbers, booleans and ``None``
    are already immutable, and copying them would be work with no property
    attached to it.
    """
    if isinstance(value, _MappingABC):
        walked = {key: _copy(item, frozen=frozen)
                  for key, item in value.items()}
        return MappingProxyType(walked) if frozen else walked
    if isinstance(value, (list, tuple)):
        walked = [_copy(item, frozen=frozen) for item in value]
        return tuple(walked) if frozen else walked
    return value


def deep_copy(value: Any) -> Any:
    """A mutable copy sharing no nested object with its original."""
    return _copy(value, frozen=False)


def freeze(value: Any) -> Any:
    """The same structure, read-only to the leaves. See :func:`_copy`."""
    return _copy(value, frozen=True)


def encode_evidence(refs: Iterable[EvidenceRef]) -> List[dict]:
    """Evidence refs as dicts, the door's stamp included.

    **Migration note, for the day :data:`EVENT_SCHEMA_VERSION` moves.**  The
    ``authority`` key on a ref is the stamp the asserting door wrote, and it
    did not exist in the first shape of this log.  A ref decoded from an
    older record therefore has ``authority=None``, and that is the correct
    reading: *absent*, not "probably SOURCE" and not "whatever the event's
    own authority says."  Nothing downstream may infer a door from a
    locator's shape — the whole value of the stamp is that it was written by
    the door and by nothing else.  On replay the refs go back through that
    door and are stamped again from the event's own ``authority`` field, so
    an old log reconstructs a correctly stamped store without anybody
    guessing; a ref read out of a log by some other consumer does not.
    """
    return [ref.as_dict() for ref in refs]


def decode_evidence(raw: Sequence[Mapping[str, Any]]) -> tuple:
    """Evidence refs out of a log, or :class:`ReplayRefused`.

    The shapes are checked here rather than left to fail wherever they land,
    because the failure a caller is told to expect is the contract.
    ``CONTRACT.md``-style documentation says to catch
    :class:`~core.cognition.types.ReplayRefused` around a replay; a log with
    ``"evidence": "notalist"`` used to come back out as an ``AttributeError``
    from inside ``from_dict``, and ``[7]`` as a ``TypeError`` — both straight
    through a handler written exactly as documented, as a crash rather than a
    refusal.  A string is the nastiest of them: it is a ``Sequence``, so it
    iterates, and it iterates into *characters*.
    """
    if raw is None:
        return ()
    if isinstance(raw, (str, bytes)) or not isinstance(raw, _SequenceABC):
        raise ReplayRefused(
            f"evidence is a list of refs, not {type(raw).__name__} "
            f"({raw!r})")
    out = []
    for index, item in enumerate(raw):
        if not isinstance(item, _MappingABC):
            raise ReplayRefused(
                f"evidence[{index}] is a ref record, not "
                f"{type(item).__name__} ({item!r})")
        out.append(EvidenceRef.from_dict(item))
    return tuple(out)


def encode_pattern(pattern: Sequence[Any]) -> list:
    """A pattern is a list on the wire and a tuple in memory.

    ``json.loads`` gives back lists whatever went in, so the kernel normalises
    at the boundary rather than letting a replayed rule hold lists where a
    live one holds tuples — a difference that never shows up until something
    compares them.
    """
    return [pattern[0], pattern[1], pattern[2]]


def decode_pattern(raw: Sequence[Any]) -> tuple:
    if raw is None or len(raw) != 3:
        raise ReplayRefused(f"a pattern is three terms, got {raw!r}")
    return (raw[0], raw[1], raw[2])


def check_snapshot(raw: Any) -> "Tuple[int, List[dict]]":
    """Validate a snapshot and return its events, or refuse.

    **A versioned mapping, and nothing else.**  An earlier shape of this
    function also took a bare list, as a convenience for a consumer reading
    the log back out of a JSONL file line by line.  That convenience pointed
    the version bypass at precisely the reader most likely to need the
    version: the one holding lines off a disk, from a file some other release
    wrote.  Wrapping a list in ``{"event_schema": N, "events": [...]}`` is one
    expression, and stating which N it believes it is holding is the only
    work this function can actually check.

    ``n`` is checked too, and that is not fussiness about a redundant field.
    It catches a log *reordered*, cut in the *middle*, or *duplicated* — three
    corruptions that leave every individual event perfectly well-formed, and
    each of which replays into a plausible store that is not the one that was
    written.

    :data:`COUNT_KEY` catches the fourth, which ``n`` cannot: a cut at the
    **tail**.  Drop the last three events and 1..k-1 still number perfectly,
    so the log reads as a complete, shorter session — and a prefix is the
    most plausible-looking corruption there is, because it is what a truncated
    write, a partial upload and a half-read file all produce.  Required from
    schema 2; a schema-1 log never carried it and is not asked for it.

    Returns ``(version, events)``.  The version is handed back rather than
    checked and dropped because **replay semantics are version-aware**: see
    :meth:`~core.cognition.state.CognitiveState.replay`.
    """
    if not isinstance(raw, _MappingABC):
        raise ReplayRefused(
            f"a cognition snapshot is a mapping stating its {SCHEMA_KEY!r}, "
            f"not a bare {type(raw).__name__}; wrap the events as "
            f"{{{SCHEMA_KEY!r}: N, {EVENTS_KEY!r}: [...]}} so that the "
            "version this log was written under is part of what is read")
    if SCHEMA_KEY not in raw:
        raise ReplayRefused(
            f"a cognition snapshot states its {SCHEMA_KEY!r}; this one "
            "does not, and an unversioned log cannot be trusted to mean "
            "what this kernel would read into it")
    version = raw[SCHEMA_KEY]
    if not isinstance(version, int) or isinstance(version, bool) \
            or version > EVENT_SCHEMA_VERSION:
        raise ReplayRefused(
            f"event schema {version!r} is newer than this kernel's "
            f"{EVENT_SCHEMA_VERSION}")
    # `raw.get(EVENTS_KEY) or []` was the shape here, and it turned three
    # different broken snapshots — the key missing, the key `None`, the key
    # `0`/`""`/`{}` — into a silent, successful replay of an EMPTY store. A
    # store that reconstructs to nothing is the one result no consumer can
    # tell from a store that legitimately holds nothing, and the caller's
    # `except ReplayRefused` never fires. A snapshot without a list of events
    # is not a snapshot.
    if EVENTS_KEY not in raw:
        raise ReplayRefused(
            f"a cognition snapshot carries its {EVENTS_KEY!r}; this one has "
            f"only {sorted(raw)!r}, and replaying it would build an empty "
            "store that looks exactly like a store with nothing in it")
    events = raw[EVENTS_KEY]
    if not isinstance(events, (list, tuple)):
        raise ReplayRefused(
            f"{EVENTS_KEY!r} is an ordered list of events, not "
            f"{type(events).__name__} ({events!r})")
    if COUNT_KEY in raw:
        stated = raw[COUNT_KEY]
        if not isinstance(stated, int) or isinstance(stated, bool) \
                or stated != len(events):
            raise ReplayRefused(
                f"the log says it holds {stated!r} events and carries "
                f"{len(events)}; a log cut at the tail numbers perfectly and "
                "reads as a complete, shorter session")
    elif version >= 2:
        raise ReplayRefused(
            f"a schema-{version} log states its {COUNT_KEY!r}; without it a "
            "cut at the tail cannot be told from a shorter session")
    out: List[dict] = []
    for index, event in enumerate(events):
        if not isinstance(event, _MappingABC):
            raise ReplayRefused(f"event {index} is not a record: {event!r}")
        op = event.get("op")
        if op not in EVENT_OPS:
            raise ReplayRefused(
                f"event {index} is a {op!r}, which this kernel cannot "
                "reconstruct; a replay that skipped it would build a state "
                "nobody can name")
        if event.get("n") != index + 1:
            raise ReplayRefused(
                f"event at position {index} says it is number "
                f"{event.get('n')!r}; this log has been reordered, truncated "
                "or had something inserted, and every event in it still looks "
                "well-formed on its own")
        out.append(dict(event))
    return version, out
