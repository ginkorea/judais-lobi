# core/cognition/graph/events.py — the log a graph is, and its own version

"""Every mutating call is one plain dict, and the graph is their sum.

The same discipline as :mod:`core.cognition.events`, deliberately close enough
in shape that a shadow lane writing both logs writes them the same way: an
ordered list of plain dicts, each carrying its position and its ``op``, under a
version key that names the schema.  Indexes, degrees and revisions are a cache
of this list; the list is the record.

**Its own version, again.**  :data:`GRAPH_EVENT_SCHEMA_VERSION` is not the
kernel's :data:`~core.cognition.events.EVENT_SCHEMA_VERSION` and neither of
them is :data:`core.runtime.contract.SCHEMA_VERSION`.  Three numbers because
three things change for three reasons: the wire is a promise to a platform,
the kernel log is an experiment in what a belief store holds, and this log is
an experiment in what a topology store holds.  Collapsing any two of them
makes one experiment a break in the other.

**Its own key, too.**  A graph snapshot states :data:`SCHEMA_KEY` —
``"graph_event_schema"`` — so that a reader handed a naked dict can tell a
graph log from a kernel log without being told which it asked for.  The event
list lives under the kernel's :data:`~core.cognition.events.EVENTS_KEY`,
imported rather than re-spelled: that key is one fact and the kernel owns it.

**The sequence is checked, the same way the kernel checks its own.**  Every
event carries ``n``, counting from one, and :func:`check_snapshot` refuses a
log whose ``n`` values are not exactly ``1..len``.  It catches a log
*reordered*, cut in the *middle*, or *duplicated* — three corruptions that
leave every individual event perfectly well-formed.  Here it bites twice,
because ids are assigned by insertion order: a log with one line missing
rebuilds a graph whose edge ``e7`` is a *different edge* from the original's
under the same name, silently, and every read afterwards is wrong in a way
nothing downstream can detect.  A JSONL file with a truncated middle is the
ordinary way that happens, and JSONL is the shadow lane's ordinary format.

:data:`COUNT_KEY` catches the fourth, which ``n`` cannot: a cut at the
**tail**.  Drop the last three events and ``1..k-1`` still number perfectly,
so the log reads as a complete, shorter session — and a prefix is the most
plausible-looking corruption there is, because it is what a truncated write, a
partial upload and a half-read file all produce.  A graph is the worst place
for it: the missing edges are not missing *rows*, they are relationships that
a working set will simply not contain, and a working set that does not contain
an edge looks exactly like a graph that never had one.  That is the failure
this package's truncation flag exists to make impossible from the *inside*;
the count closes the same hole from the outside.

**Three things in the header, and each answers a question the others cannot.**
:data:`GRAPH_EVENT_SCHEMA_VERSION` is the shape of an event — can this reader
parse the log at all.  :data:`GRAPH_PACKAGE_VERSION` is the semantics of the
package that wrote it — is the graph it rebuilds the graph the writer had.
:data:`COUNT_KEY` is how much of it there was — did all of it arrive.  None of
the three is inferred from another, and all three are in every snapshot.

**Compatibility, stated now so the next lane does not have to invent it.**
Adding an optional field to an event, or a new ``op``, raises the schema
number.  **Ops are append-only, forever**: no op is ever renamed or removed,
so a log this package could read once it can read the same way always.  A
replay refuses a schema higher than the one it knows rather than skipping what
it does not recognise — see
:class:`~core.cognition.types.ReplayRefused` for why that is the opposite rule
from the wire contract's.  A *package* version higher than ours is not refused
on sight: append-only ops mean a newer package's log of ops we know still
replays, and when it carries one we do not, the refusal names the version that
wrote it rather than leaving somebody to guess.

**Ids are not in the log, except as references.**  ``add_edge`` carries the
triple and not the edge id; insertion order determines the id, so writing it
down would be a second owner of the same fact and the two would disagree the
first time a log was edited by hand.
"""

from __future__ import annotations

from collections.abc import Mapping as _MappingABC
from typing import Any, List, Tuple

from core.cognition.events import EVENTS_KEY, decode_evidence, encode_evidence
from core.cognition.types import ReplayRefused

#: Bump on any change to the shape of an event or the set of ops.
#:
#: 1 — the first shape.
#: 2 — the snapshot states its :data:`COUNT_KEY`. No event changed; what
#:     changed is what a reader is entitled to assume arrived.
GRAPH_EVENT_SCHEMA_VERSION = 2

#: Bump when what an op *means* changes — a merge rule, an ordering, what a
#: read is entitled to assume — even when the dict on the wire is untouched.
#: The sharpest case, and the kernel's reason for the same number: **a change
#: that alters which id a given sequence of writes produces**.  Ids here come
#: from insertion order, so a consumer holding a persisted ``e7`` can compare
#: this against the one in the log it came from and tell whether that name
#: still points at the same edge.
#:
#: 1 — the first shape.
#:
#: A replay does not refuse a newer one, because ops are append-only; it
#: carries it into the message when something else goes wrong.
GRAPH_PACKAGE_VERSION = 1

#: Every ``op`` this graph writes and can read back. A log carrying anything
#: else is refused rather than partially applied — the same rule as the
#: kernel's, for the same reason: a graph rebuilt from a log with an event
#: skipped is a graph nobody can name.
GRAPH_EVENT_OPS = (
    "add_edge",
    "node_kind",
)

#: The key a graph snapshot puts its event schema under. Not the kernel's.
SCHEMA_KEY = "graph_event_schema"

#: The key a graph snapshot puts the writing package's version under.
PACKAGE_KEY = "graph_package_version"

#: The key a snapshot puts its event count under. Required from schema 2; a
#: schema-1 log never carried it and is not asked for it.
COUNT_KEY = "count"

__all__ = [
    "COUNT_KEY",
    "EVENTS_KEY",
    "GRAPH_EVENT_OPS",
    "GRAPH_EVENT_SCHEMA_VERSION",
    "GRAPH_PACKAGE_VERSION",
    "PACKAGE_KEY",
    "SCHEMA_KEY",
    "check_snapshot",
    "decode_evidence",
    "encode_evidence",
]


def check_snapshot(raw: Any) -> "Tuple[int, List[dict]]":
    """Validate a graph snapshot and return its events, or refuse.

    **A versioned mapping, and nothing else** — the same rule the kernel
    settled on, and it is worth restating rather than quietly following.  The
    convenience of taking a bare list is aimed at a reader holding lines off a
    disk, out of a file some other release wrote: precisely the reader most in
    need of the version, handed the one shape that has none.  Wrapping the
    lines is one expression.

    A mapping carrying the *kernel's* version key instead of this one is
    refused by the missing key, and that is the intended reading: a kernel log
    fed to a graph should be named as the mistake it is, not walked until it
    happens to find no ops it knows.

    **The events key is required and must be a list**, and the reason is the
    worst failure this function can have.  ``raw.get(EVENTS_KEY) or []`` reads
    an absent key, a ``None``, a ``0``, an empty string and an empty mapping
    all as "no events" — and a replay of no events is an *empty graph*, which
    is a perfectly well-formed answer that nothing downstream can distinguish
    from a graph that was genuinely never written to.  A truncated file, a
    renamed key, a half-written envelope: every one of them would come back as
    a graph with no edges and no complaint, and every read afterwards would
    honestly report that nothing is connected to anything.  An empty list is
    the one way to say "no events", because it is the only one somebody wrote
    on purpose.

    A ``tuple`` is accepted beside a ``list``, matching the kernel's rule
    exactly: both are ordered sequences somebody wrote on purpose, and
    :attr:`~core.cognition.graph.store.KnowledgeGraph.events` hands back a
    tuple, so refusing one would refuse this package's own accessor wrapped in
    an envelope by hand.  What is refused is *sequence-shaped by accident* —
    the string, the mapping, the zero, the ``None``.

    Returns ``(version, events)``.  The version is handed back rather than
    checked and dropped, matching the kernel's signature exactly: replay
    semantics here are version-aware in principle even where they do not yet
    differ, and a caller that reads both logs should not have to remember
    which of the two siblings tells it what it read a log *as*.
    """
    wrote = GRAPH_PACKAGE_VERSION
    if not isinstance(raw, _MappingABC):
        raise ReplayRefused(
            f"a graph snapshot is a mapping stating its {SCHEMA_KEY!r}, not a "
            f"bare {type(raw).__name__}; wrap the events as "
            f"{{{SCHEMA_KEY!r}: N, {EVENTS_KEY!r}: [...]}} so that the version "
            "this log was written under is part of what is read")
    if SCHEMA_KEY not in raw:
        raise ReplayRefused(
            f"a graph snapshot states its {SCHEMA_KEY!r}; this one does "
            "not, and an unversioned log cannot be trusted to mean what "
            "this graph would read into it")
    version = raw[SCHEMA_KEY]
    if not isinstance(version, int) or isinstance(version, bool) \
            or version > GRAPH_EVENT_SCHEMA_VERSION:
        raise ReplayRefused(
            f"graph event schema {version!r} is newer than this package's "
            f"{GRAPH_EVENT_SCHEMA_VERSION}")
    if PACKAGE_KEY in raw:
        wrote = raw[PACKAGE_KEY]
        if not isinstance(wrote, int) or isinstance(wrote, bool) \
                or wrote < 1:
            raise ReplayRefused(
                f"{PACKAGE_KEY} is a version number, not {wrote!r}")
    if EVENTS_KEY not in raw:
        raise ReplayRefused(
            f"a graph snapshot carries its events under {EVENTS_KEY!r}; this "
            "one has no such key, and reading that as an empty log would "
            "rebuild an empty graph that nothing downstream could tell from a "
            "graph nobody ever wrote to")
    events = raw[EVENTS_KEY]
    if not isinstance(events, (list, tuple)):
        raise ReplayRefused(
            f"{EVENTS_KEY!r} is an ordered list of events, not "
            f"{type(events).__name__} ({events!r}); an empty list is how a log "
            "with nothing in it says so, and it is the only spelling somebody "
            "wrote on purpose")
    if COUNT_KEY in raw:
        stated = raw[COUNT_KEY]
        if not isinstance(stated, int) or isinstance(stated, bool) \
                or stated != len(events):
            raise ReplayRefused(
                f"the log says it holds {stated!r} events and carries "
                f"{len(events)}; a log cut at the tail numbers perfectly and "
                "reads as a complete, shorter graph, with the edges it lost "
                "indistinguishable from edges that were never there")
    elif version >= 2:
        raise ReplayRefused(
            f"a schema-{version} graph log states its {COUNT_KEY!r}; without "
            "it a cut at the tail cannot be told from a shorter session")
    out: List[dict] = []
    for index, event in enumerate(events):
        if not isinstance(event, _MappingABC):
            raise ReplayRefused(f"event {index} is not a record: {event!r}")
        op = event.get("op")
        if op not in GRAPH_EVENT_OPS:
            raise ReplayRefused(
                f"event {index} is a {op!r}, which this graph cannot "
                "reconstruct; a replay that skipped it would build a "
                f"topology nobody can name (the log says package version "
                f"{wrote}, this package is {GRAPH_PACKAGE_VERSION})")
        number = event.get("n")
        if not isinstance(number, int) or isinstance(number, bool) \
                or number != index + 1:
            raise ReplayRefused(
                f"event {index} is numbered {number!r} where the log's own "
                f"count says {index + 1}; ids here come from insertion order, "
                "so a log with a line missing rebuilds different edges under "
                "the same names and nothing downstream could tell")
        out.append(dict(event))
    return version, out
