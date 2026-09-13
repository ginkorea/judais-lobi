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

**Compatibility, stated now so the next lane does not have to invent it.**
Adding an optional field to an event, or a new ``op``, raises this number.
A replay refuses a log whose version is higher than the one it knows
(:class:`~core.cognition.types.ReplayRefused`) rather than skipping what it
does not recognise — see that exception for why this is the opposite rule from
the wire's.

**Ids are not in the log, except as references.**  ``assert_observation``
carries no proposition id: ids are assigned by insertion order, so the log
*determines* them and writing them down would be a second owner of the same
fact.  ``refute`` and ``promote_rule`` do carry ids, because by then the id
exists and naming it is the only way to say which one.
"""

from __future__ import annotations

from collections.abc import Mapping as _MappingABC
from typing import Any, Iterable, List, Mapping, Sequence

from core.cognition.types import EvidenceRef, ReplayRefused

#: Bump on any change to the shape of an event or the set of ops.
EVENT_SCHEMA_VERSION = 1

#: Every ``op`` this kernel writes and can read back. A log carrying anything
#: else is refused rather than partially applied.
EVENT_OPS = (
    "assert_observation",
    "assert_hypothesis",
    "add_rule",
    "promote_rule",
    "add_goal",
    "refute",
    "derive",
)

#: The key a snapshot puts its version under.
SCHEMA_KEY = "event_schema"

#: The key a snapshot puts the ordered event list under.
EVENTS_KEY = "events"


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
    return tuple(EvidenceRef.from_dict(item) for item in raw or ())


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


def check_snapshot(raw: Any) -> List[dict]:
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
    It is the only thing in the record that can catch a log *reordered*,
    *truncated* or *duplicated* in transit — three corruptions that leave
    every individual event perfectly well-formed, and each of which replays
    into a plausible store that is not the one that was written.
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
    events = raw.get(EVENTS_KEY) or []
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
    return out
