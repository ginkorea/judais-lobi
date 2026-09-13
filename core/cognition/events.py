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
    """Accept a snapshot dict or a bare event list; return the events.

    A bare list is accepted because the shadow lane will read events back out
    of a JSONL file one line at a time and should not have to rebuild the
    envelope to hand them here.  A dict without the version key is refused:
    an unversioned log is a log that will be misread exactly once.
    """
    if isinstance(raw, _MappingABC):
        if SCHEMA_KEY not in raw:
            raise ReplayRefused(
                f"a cognition snapshot states its {SCHEMA_KEY!r}; this one "
                "does not, and an unversioned log cannot be trusted to mean "
                "what this kernel would read into it")
        version = raw[SCHEMA_KEY]
        if not isinstance(version, int) or version > EVENT_SCHEMA_VERSION:
            raise ReplayRefused(
                f"event schema {version!r} is newer than this kernel's "
                f"{EVENT_SCHEMA_VERSION}")
        events = raw.get(EVENTS_KEY) or []
    else:
        events = list(raw or [])
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
        out.append(dict(event))
    return out
