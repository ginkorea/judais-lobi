# core/cognition/graph/store.py — the topology: what is connected to what, and on whose word

"""One class, :class:`KnowledgeGraph`, and the two records it keeps.

It changes in exactly two ways — :meth:`~KnowledgeGraph.add_edge` and
:meth:`~KnowledgeGraph.node_kind` — each of which appends exactly one event
and does nothing else a replay cannot reproduce.  Everything else on the class
is a read.

**Single writer, same as the kernel.**  There is no lock here and there is not
meant to be one: every id in this package comes from insertion order, and a
store two things write to is a store whose ids depend on scheduling.

**Nodes are implicit.**  There is no ``add_node``.  A node exists because an
edge or a kind names it, and it stops being interesting when nothing does.
That is not minimalism for its own sake — a node the graph can hold with no
statement attached is a node with no evidence behind it, and this package has
no door for an unevidenced anything.

**What an edge is allowed to change.**  Identity is ``(src, relation, dst)``.
Re-adding one unions its evidence and raises its authority to the strongest
offered, and that is the whole of it: an edge is never re-pointed, never
re-labelled, never removed.  Each change writes a *revision* naming the record
it replaced, exactly as a proposition does, so "when did this become
deterministic, and on what" is answerable rather than inferred.  There is no
retraction in v1, deliberately: retracting an edge means deciding what happens
to the working sets already compiled from it, and that decision belongs with
the lane that compiles them.

**No collide rule, and this is the whole point of having a graph.**  The
kernel treats every field as single-valued: ``(alice, controls, acct-1)`` and
``(alice, controls, acct-2)`` contradict there, which is right for ``total_s``
and wrong for ``controls``.  The workaround its docstring offers — put the
multi-valued end in the entity position — is a workaround for not having this
module.  Here ``(alice, knows, bob)`` and ``(alice, knows, carol)`` are two
edges and neither is news about the other.  Multi-edges between one pair under
different relations are likewise distinct.  Nothing in this module ever raises
a contradiction, because deciding that two relationships cannot both hold is a
claim about the world and the kernel is where claims about the world live.

**The division of labour is a convention, and the projection is where it is
enforced.**  Nothing inside this store stops a caller putting an attribute in
the ``dst`` position — ``(alice, role, "admin")`` is three strings and it will
be stored as an edge like any other, with a node called ``admin`` and a degree
to match.  The wall is at the door the two packages meet through:
:meth:`KnowledgeGraph.as_propositions` hands triples to a kernel assertion,
and everything the kernel enforces about them — the authority doors,
single-valued fields, ground terms, its own value rules — binds there.  Saying
so plainly is better than implying a structural guarantee this module does not
make: a caller that stores attributes here gets a graph that works and a
kernel that will contest them the moment they are projected, and that is the
honest reading of "the kernel owns claims, the graph owns topology".
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import (Any, Dict, Iterable, List, Mapping, Optional, Sequence,
                    Tuple)

from core.cognition.events import EVENTS_KEY
from core.cognition.graph.events import (GRAPH_EVENT_OPS,
                                         GRAPH_EVENT_SCHEMA_VERSION,
                                         GRAPH_PACKAGE_VERSION, PACKAGE_KEY,
                                         SCHEMA_KEY, check_snapshot,
                                         decode_evidence, encode_evidence)
from core.cognition.types import (AUTHORITY_RANK, CognitionError,
                                  EvidenceAuthority, EvidenceRef,
                                  ReplayRefused, UnknownId)

#: The directions :meth:`KnowledgeGraph.neighbors` accepts. ``"both"`` is the
#: default because a knowledge graph's useful question is almost never "what
#: does this point at" but "what is this involved in".
DIRECTIONS = ("out", "in", "both")

#: The top-level keys :meth:`KnowledgeGraph.digest` produces, declared so that
#: growing the digest is a deliberate act with a test to update rather than a
#: silent change to what "the same graph" means.
DIGEST_KEYS = ("edges", "kinds", "nodes", "stats")

#: The keys of one edge inside that digest, declared for a sharper reason than
#: the top level's.  A digest is what "these two graphs are the same one" means
#: and what a replay is checked against, so a key *dropped* from here does not
#: break anything: the comparison simply stops looking at ``authority``, or at
#: ``evidence``, or at the revision chain, and every replay test goes on
#: passing while the property it was written to prove is no longer being
#: checked. The top-level tuple cannot catch that — the row is still there.
EDGE_KEYS = ("id", "revision", "previous", "src", "relation", "dst",
             "authority", "evidence", "history")

#: The keys of one kind statement, for the same reason.
KIND_KEYS = ("id", "revision", "previous", "node", "kind", "authority",
             "evidence", "history")

#: The keys :meth:`KnowledgeGraph.stats` produces, for the same reason.
STATS_KEYS = ("nodes", "edges", "kinds", "relations", "edge_authorities")

#: The longest a node name, relation or kind may be.  A cap chosen rather than
#: discovered: nothing in this package needs a long one, ids are what get
#: passed around, and an unbounded name is an unbounded key in six indexes, an
#: unbounded string in every log line, and an unbounded row in a compiled
#: context.  Generous enough that a URI or a fully-qualified identifier fits;
#: small enough that a document pasted into the ``dst`` position is refused at
#: the door rather than discovered in a working set.
NAME_CAP = 512


@dataclass(frozen=True)
class Edge:
    """One relationship, at one revision.

    ``(src, relation, dst)`` is the identity of the *edge* and is stable
    across revisions; :attr:`key` (``"e3@2"``) is the identity of the record,
    and ``previous`` names the record this one replaced.  ``authority`` is
    where the relationship came from and it travels on the edge itself rather
    than being inferred from its shape — the trust boundary is only a boundary
    if every read can see it, and a read that had to look the authority up
    somewhere else is a read somebody will write without looking.

    ``evidence`` is the kernel's :class:`~core.cognition.types.EvidenceRef`,
    reused rather than re-invented: an edge extracted from the same receipt as
    a proposition should carry the same pointer, and two pointer types would
    mean two vocabularies for one fact.
    """

    id: str
    src: str
    relation: str
    dst: str
    authority: EvidenceAuthority
    evidence: Tuple[EvidenceRef, ...] = ()
    revision: int = 1
    previous: Optional[str] = None

    @property
    def key(self) -> str:
        """The identity of this record, as opposed to the relationship."""
        return f"{self.id}@{self.revision}"

    @property
    def triple(self) -> Tuple[str, str, str]:
        return (self.src, self.relation, self.dst)

    def other(self, node: str) -> str:
        """The end that is not ``node``. A self-loop's other end is itself."""
        if node == self.src:
            return self.dst
        if node == self.dst:
            return self.src
        raise CognitionError(
            f"{node!r} is not an end of {self.render()}")

    def render(self) -> str:
        return f"({self.src} -{self.relation}-> {self.dst})"


@dataclass(frozen=True)
class NodeKind:
    """What sort of thing a node is — the one node-level statement this
    package owns.

    Everything else about a node is the kernel's business, and the line is
    drawn here rather than by taste: a kind is a fact about the node's place
    in the *topology* (does an edge to it mean what an edge to a person
    means), while ``(alice, role, "admin")`` is a fact about the world.

    **Kinds are not single-valued and do not collide.**  A node may be a
    ``person`` and an ``employee``; identity is ``(node, kind)`` and re-stating
    one unions evidence and raises authority, exactly as an edge does.  If two
    kinds are genuinely incompatible, that is a claim about the world, and a
    kernel rule over :meth:`KnowledgeGraph.as_propositions` is where it goes.
    """

    id: str
    node: str
    kind: str
    authority: EvidenceAuthority
    evidence: Tuple[EvidenceRef, ...] = ()
    revision: int = 1
    previous: Optional[str] = None

    @property
    def key(self) -> str:
        return f"{self.id}@{self.revision}"


@dataclass(frozen=True)
class NodeView:
    """A node as the index holds it: degree, the relations it touches, its
    kinds. A read-only snapshot, so a caller cannot edit the index by holding
    one.

    ``relations`` and ``kinds`` are in first-appearance order, which is the
    same order every other iteration in this package uses.
    """

    node: str
    out_degree: int
    in_degree: int
    relations: Tuple[str, ...] = ()
    kinds: Tuple[str, ...] = ()

    @property
    def degree(self) -> int:
        """Edges touching this node. A self-loop counts once at each end,
        which is what makes ``sum(degree) == 2 * edges`` hold."""
        return self.out_degree + self.in_degree


class KnowledgeGraph:
    """The topology store. See the module docstring for the rules it keeps.

    Instantiate one per run, or none.  There is no module-level state, no
    registry and no singleton anywhere in this package, which is what lets an
    ablation arm construct a graph or not and change nothing else.
    """

    # ── construction ────────────────────────────────────────────────────────

    def __init__(self) -> None:
        self._events: List[dict] = []

        # Edges: `_edges` holds the live revision of every relationship,
        # `_history` every revision in order. Both keyed by the edge id, which
        # is stable across revisions — the record id is `Edge.key`.
        self._edges: Dict[str, Edge] = {}
        self._history: Dict[str, List[Edge]] = {}
        self._edge_key: Dict[Tuple[str, str, str], str] = {}

        self._kinds: Dict[str, NodeKind] = {}
        self._kind_history: Dict[str, List[NodeKind]] = {}
        self._kind_key: Dict[Tuple[str, str], str] = {}

        # Adjacency. Lists, not sets: an edge id enters each bucket exactly
        # once, and a list preserves the insertion order every deterministic
        # read in this file depends on. Dicts for the same reason — iteration
        # order is insertion order and owes nothing to PYTHONHASHSEED.
        self._out: Dict[str, List[str]] = {}
        self._in: Dict[str, List[str]] = {}
        self._out_rel: Dict[Tuple[str, str], List[str]] = {}
        self._in_rel: Dict[Tuple[str, str], List[str]] = {}

        # The node index, in first-appearance order.
        self._nodes: Dict[str, None] = {}
        self._node_relations: Dict[str, List[str]] = {}
        self._node_kinds: Dict[str, List[str]] = {}
        self._relations: Dict[str, int] = {}

        self._counters = {"e": 0, "k": 0}

    # ── the event log ───────────────────────────────────────────────────────

    def _append(self, op: str, **fields: Any) -> dict:
        assert op in GRAPH_EVENT_OPS, op  # a typo is a log nobody replays
        event = {"n": len(self._events) + 1, "op": op}
        event.update(fields)
        self._events.append(event)
        return event

    @property
    def events(self) -> Tuple[dict, ...]:
        """The log, oldest first. Copies, so a reader cannot edit history.

        **Copies all the way down**, which ``dict(event)`` is not.  An event
        carries its evidence as a list of dicts, so a shallow copy hands a
        reader the graph's own ref records under a new outer dict: editing
        ``events[0]["evidence"][0]["locator"]`` then edits the log itself,
        silently, and the next snapshot exports the forgery as the record.
        The top-level copy is the one anybody thinks to test, and it is not
        the one that matters.
        """
        return tuple(_copy(event) for event in self._events)

    def snapshot(self) -> dict:
        """The whole graph as one JSON-safe dict: two versions and the events.

        The event schema says whether a reader can parse this; the package
        version says whether the graph it rebuilds means what the writer
        meant.  Both, because neither answers the other's question.

        Deep-copied for the reason :attr:`events` gives: a snapshot is the
        thing most likely to be handed somewhere else and edited, and one that
        aliased the log would make every such edit a write to this graph.

        **Measured, because it is not free**: at 100k events the deep copy is
        ~1.9 s against ~0.16 s for the aliasing shape.  It is paid at
        persistence boundaries rather than per step — a mission-scale log is
        hundreds of events and the copy is sub-millisecond — and handing out a
        live log to save it would be trading a silent corruption for a number
        nobody is waiting on.  If a caller ever does need the cheap read, the
        honest shape is a separate accessor that says it aliases, not a
        quietly shallow copy of this one.
        """
        return {SCHEMA_KEY: GRAPH_EVENT_SCHEMA_VERSION,
                PACKAGE_KEY: GRAPH_PACKAGE_VERSION,
                EVENTS_KEY: [_copy(event) for event in self._events]}

    @classmethod
    def replay(cls, events: Any) -> "KnowledgeGraph":
        """Rebuild a graph from a snapshot — a versioned mapping, always.

        Every op is applied through the same public method that wrote it.
        There is no second application path — a replay that rebuilt the
        adjacency directly would be a second implementation of the index, and
        the day the two disagreed the replay would be the one nobody checked.
        """
        records = check_snapshot(events)
        graph = cls()
        for record in records:
            graph._apply_event(record)
        return graph

    def _apply_event(self, record: Mapping[str, Any]) -> None:
        op = record["op"]
        if op == "add_edge":
            self.add_edge(record.get("src"), record.get("relation"),
                          record.get("dst"),
                          authority=_authority(record.get("authority")),
                          evidence=decode_evidence(record.get("evidence", ())))
        elif op == "node_kind":
            self.node_kind(record.get("node"), record.get("kind"),
                           authority=_authority(record.get("authority")),
                           evidence=decode_evidence(record.get("evidence", ())))
        else:  # pragma: no cover — check_snapshot closed the set already
            raise ReplayRefused(f"no way to apply {op!r}")

    # ── writing ─────────────────────────────────────────────────────────────

    def add_edge(self, src: str, relation: str, dst: str, *,
                 authority: EvidenceAuthority,
                 evidence: Iterable[EvidenceRef]) -> str:
        """Record a relationship. Returns the edge id.

        ``authority`` has **no default**, on purpose and permanently.  A
        default would be the one line of code that turns a model's guess into
        a deterministic-looking edge — the caller that did not think about it
        would get whichever value seemed safe when this was written, and the
        whole trust boundary is that nobody gets to not think about it.
        Both sides of the wall are storable here; neither is confusable with
        the other, because every read that returns an edge returns its
        authority with it.

        Re-adding an existing ``(src, relation, dst)`` unions the evidence and
        raises the authority to the strongest offered so far, writing a new
        revision if either changed.  Raising and not lowering: an edge first
        extracted by a model and later confirmed by a reference is a
        deterministic edge, while the reverse re-statement does not undo the
        reference.  Evidence never leaves, so the model extraction is still on
        the record underneath.

        **Every ref is stamped with the authority it arrived on**, the way the
        kernel's doors stamp theirs, and for the same reason: without it the
        union erases the wall.  An edge a model guessed and a receipt later
        confirmed would hold both refs in one tuple with one authority over
        them, and nothing in the store could say which of them the model
        produced.  With the stamp, the upgrade is still an upgrade and "on
        whose word, ref by ref" survives any number of merges — which is the
        question a working set compiled from this graph is eventually asked.
        The caller's own value for the field is overwritten: it is the call
        that is being recorded, not the caller's opinion of it.
        """
        src = _node_name(src, "an edge's source")
        relation = _node_name(relation, "an edge's relation")
        dst = _node_name(dst, "an edge's destination")
        authority = _check_authority(authority)
        refs = _check_evidence(evidence, "an edge", authority)

        key = (src, relation, dst)
        self._append("add_edge", src=src, relation=relation, dst=dst,
                     authority=authority.value, evidence=encode_evidence(refs))
        held = self._edge_key.get(key)
        if held is not None:
            self._merge_edge(held, authority, refs)
            return held

        self._counters["e"] += 1
        eid = f"e{self._counters['e']}"
        edge = Edge(id=eid, src=src, relation=relation, dst=dst,
                    authority=authority, evidence=refs)
        self._edges[eid] = edge
        self._history[eid] = [edge]
        self._edge_key[key] = eid
        self._out.setdefault(src, []).append(eid)
        self._in.setdefault(dst, []).append(eid)
        self._out_rel.setdefault((src, relation), []).append(eid)
        self._in_rel.setdefault((dst, relation), []).append(eid)
        for node in (src, dst):
            self._touch(node)
            bucket = self._node_relations[node]
            if relation not in bucket:
                bucket.append(relation)
        self._relations[relation] = self._relations.get(relation, 0) + 1
        return eid

    def node_kind(self, node: str, kind: str, *,
                  authority: EvidenceAuthority,
                  evidence: Iterable[EvidenceRef]) -> str:
        """State what sort of thing a node is. Returns the statement's id.

        The one node-level statement this package owns, and it carries an
        authority for the same reason an edge does: "this is a person" is
        often the model's reading of a name, and a working set that could not
        tell that from a schema declaration would launder one into the other.
        """
        node = _node_name(node, "a node")
        kind = _node_name(kind, "a node kind")
        authority = _check_authority(authority)
        refs = _check_evidence(evidence, "a node kind", authority)

        key = (node, kind)
        self._append("node_kind", node=node, kind=kind,
                     authority=authority.value, evidence=encode_evidence(refs))
        held = self._kind_key.get(key)
        if held is not None:
            self._merge_kind(held, authority, refs)
            return held

        self._counters["k"] += 1
        kid = f"k{self._counters['k']}"
        record = NodeKind(id=kid, node=node, kind=kind, authority=authority,
                          evidence=refs)
        self._kinds[kid] = record
        self._kind_history[kid] = [record]
        self._kind_key[key] = kid
        self._touch(node)
        self._node_kinds[node].append(kid)
        return kid

    def _touch(self, node: str) -> None:
        if node not in self._nodes:
            self._nodes[node] = None
            self._node_relations[node] = []
            self._node_kinds[node] = []

    def _merge_edge(self, eid: str, authority: EvidenceAuthority,
                    refs: Tuple[EvidenceRef, ...]) -> None:
        """Union evidence, take the strongest authority, revise if changed."""
        held = self._edges[eid]
        merged = _merge_evidence(held.evidence, refs)
        stronger = (authority if AUTHORITY_RANK[authority]
                    > AUTHORITY_RANK[held.authority] else held.authority)
        if merged == held.evidence and stronger == held.authority:
            return
        fresh = Edge(id=held.id, src=held.src, relation=held.relation,
                     dst=held.dst, authority=stronger, evidence=merged,
                     revision=held.revision + 1, previous=held.key)
        self._edges[eid] = fresh
        self._history[eid].append(fresh)

    def _merge_kind(self, kid: str, authority: EvidenceAuthority,
                    refs: Tuple[EvidenceRef, ...]) -> None:
        held = self._kinds[kid]
        merged = _merge_evidence(held.evidence, refs)
        stronger = (authority if AUTHORITY_RANK[authority]
                    > AUTHORITY_RANK[held.authority] else held.authority)
        if merged == held.evidence and stronger == held.authority:
            return
        fresh = NodeKind(id=held.id, node=held.node, kind=held.kind,
                         authority=stronger, evidence=merged,
                         revision=held.revision + 1, previous=held.key)
        self._kinds[kid] = fresh
        self._kind_history[kid].append(fresh)

    # ── reading: the edges themselves ───────────────────────────────────────

    def has_node(self, node: str) -> bool:
        return node in self._nodes

    def nodes(self) -> Tuple[str, ...]:
        """Every node, in first-appearance order."""
        return tuple(self._nodes)

    def edges(self) -> Tuple[Edge, ...]:
        """Every edge at its live revision, in insertion order."""
        return tuple(self._edges.values())

    def edge(self, eid: str) -> Edge:
        edge = self._edges.get(eid)
        if edge is None:
            raise UnknownId(f"no edge {eid!r}")
        return edge

    def history(self, eid: str) -> Tuple[Edge, ...]:
        """Every revision of one edge, oldest first."""
        if eid not in self._history:
            raise UnknownId(f"no edge {eid!r}")
        return tuple(self._history[eid])

    def find(self, src: str, relation: str, dst: str) -> Optional[Edge]:
        """The edge with this identity, or ``None``."""
        eid = self._edge_key.get((src, relation, dst))
        return None if eid is None else self._edges[eid]

    def kinds(self, node: Optional[str] = None) -> Tuple[NodeKind, ...]:
        """Kind statements, all of them or one node's, in insertion order."""
        if node is None:
            return tuple(self._kinds.values())
        return tuple(self._kinds[kid] for kid in self._node_kinds.get(node, ()))

    def node(self, node: str, *,
             min_authority: Optional[EvidenceAuthority] = None) -> NodeView:
        """The index's view of one node. Refuses a node it has never seen —
        a degree of zero for a name nobody mentioned is an answer that reads
        as data and is really a typo.

        ``min_authority`` floors this read like every other one, and it has to:
        a degree, a relation list and a kind list are *summaries*, and a
        summary counted over edges a caller has said it will not trust is the
        quietest way for a model's guess to reach a decision.  "How connected
        is this node" answered at ``SOURCE`` must mean connected by things the
        caller would accept, or the number is about a graph nobody asked for.
        The floor applies to kinds too, for the same reason.
        """
        if node not in self._nodes:
            raise UnknownId(f"no node {node!r}")
        if min_authority is None:
            return NodeView(
                node=node,
                out_degree=len(self._out.get(node, ())),
                in_degree=len(self._in.get(node, ())),
                relations=tuple(self._node_relations[node]),
                kinds=tuple(self._kinds[kid].kind
                            for kid in self._node_kinds[node]))
        floor = AUTHORITY_RANK[_check_authority(min_authority)]
        out = [self._edges[eid] for eid in self._out.get(node, ())
               if AUTHORITY_RANK[self._edges[eid].authority] >= floor]
        into = [self._edges[eid] for eid in self._in.get(node, ())
                if AUTHORITY_RANK[self._edges[eid].authority] >= floor]
        # Order from the unfloored index, membership from what survived: the
        # floored list has to be a *subsequence* of the unfloored one, or a
        # caller comparing the two reads the filter as a reordering.
        surviving = {edge.relation for edge in out}
        surviving.update(edge.relation for edge in into)
        relations = tuple(relation for relation in self._node_relations[node]
                          if relation in surviving)
        return NodeView(
            node=node,
            out_degree=len(out),
            in_degree=len(into),
            relations=relations,
            kinds=tuple(self._kinds[kid].kind
                        for kid in self._node_kinds[node]
                        if AUTHORITY_RANK[self._kinds[kid].authority] >= floor))

    # ── reading: the walks ──────────────────────────────────────────────────

    def neighbors(self, node: str, *,
                  relations: Optional[Sequence[str]] = None,
                  direction: str = "both",
                  min_authority: Optional[EvidenceAuthority] = None
                  ) -> Tuple[Edge, ...]:
        """The edges touching ``node``, in insertion order.

        Edges rather than node names, because **every read that returns edges
        carries authority** and a bare list of names would drop it — the one
        place this package could quietly let a model's guess be read as a
        reference.  :meth:`Edge.other` gets the far end when that is all the
        caller wanted.

        ``direction="both"`` lists out-edges then in-edges, each in insertion
        order; a self-loop appears once, at its out-edge position.  That
        ordering is documented rather than natural, so a caller depending on
        it is depending on something written down.

        ``min_authority`` drops every edge weaker than it by
        :data:`~core.cognition.types.AUTHORITY_RANK`, and floors the walk for
        every read that calls through here — which is all of them.
        """
        if node not in self._nodes:
            raise UnknownId(f"no node {node!r}")
        if direction not in DIRECTIONS:
            raise CognitionError(
                f"direction is one of {', '.join(DIRECTIONS)}, not "
                f"{direction!r}")
        wanted = None if relations is None else tuple(dict.fromkeys(relations))
        floor = None if min_authority is None else \
            AUTHORITY_RANK[_check_authority(min_authority)]

        ids: Dict[str, None] = {}
        if direction in ("out", "both"):
            self._gather(ids, node, wanted, self._out, self._out_rel)
        if direction in ("in", "both"):
            self._gather(ids, node, wanted, self._in, self._in_rel)
        out = []
        for eid in ids:
            edge = self._edges[eid]
            if floor is not None and AUTHORITY_RANK[edge.authority] < floor:
                continue
            out.append(edge)
        return tuple(out)

    def _gather(self, into: Dict[str, None], node: str,
                wanted: Optional[Tuple[str, ...]],
                by_node: Dict[str, List[str]],
                by_relation: Dict[Tuple[str, str], List[str]]) -> None:
        """Edge ids touching ``node`` on one side, into an ordered dict-as-set.

        **Insertion order whatever the filter is**, which is why a filter of
        several relations reads the node's whole bucket and drops what it does
        not want rather than reading one relation bucket after another: the
        second shape would order the answer by the caller's argument list, so
        one relation and two relations would come back ordered by different
        rules and only the two-relation case would ever be noticed.  The
        single-relation shortcut is the same order by construction — a
        relation bucket is a subsequence of the node bucket.
        """
        if wanted is not None and len(wanted) == 1:
            for eid in by_relation.get((node, wanted[0]), ()):
                into.setdefault(eid, None)
            return
        keep = None if wanted is None else frozenset(wanted)
        for eid in by_node.get(node, ()):
            if keep is not None and self._edges[eid].relation not in keep:
                continue
            into.setdefault(eid, None)

    def reachable(self, src: str, dst: str, *, max_depth: int,
                  relations: Optional[Sequence[str]] = None,
                  min_authority: Optional[EvidenceAuthority] = None
                  ) -> Optional[Tuple[Edge, ...]]:
        """The first path from ``src`` to ``dst``, or ``None``.

        Breadth-first and undirected — an edge is walked from either end,
        because "is there a connection" is almost never a question about
        arrow direction, and a walk that only followed out-edges would miss
        the reference that names the seed.  ``max_depth`` counts *edges*.

        **First found under a deterministic walk**, which is a weaker promise
        than shortest-by-any-measure and the only one worth making: the
        frontier is expanded in insertion order at every ring, so the answer
        is a function of the log and nothing else.  It is shortest in edges,
        because breadth-first, and among equal-length paths it is the one the
        insertion order reaches first.

        ``src == dst`` returns an empty tuple — a path of no edges.  Test the
        result with ``is None``; a falsy answer here is a real answer.
        """
        if max_depth < 0:
            raise CognitionError(f"max_depth counts edges, not {max_depth!r}")
        if src not in self._nodes:
            raise UnknownId(f"no node {src!r}")
        if dst not in self._nodes:
            raise UnknownId(f"no node {dst!r}")
        if src == dst:
            return ()
        seen: Dict[str, None] = {src: None}
        paths: Dict[str, Tuple[Edge, ...]] = {src: ()}
        ring = [src]
        for _depth in range(max_depth):
            nxt: List[str] = []
            for node in ring:
                for edge in self.neighbors(node, relations=relations,
                                           min_authority=min_authority):
                    far = edge.other(node)
                    if far in seen:
                        continue
                    path = paths[node] + (edge,)
                    if far == dst:
                        return path
                    seen[far] = None
                    paths[far] = path
                    nxt.append(far)
            if not nxt:
                break
            ring = nxt
        return None

    # ── reading: the projection the kernel can hold ─────────────────────────

    def as_propositions(self, edges: Optional[Iterable[Edge]] = None
                        ) -> Tuple[Dict[str, Any], ...]:
        """Edges as the kernel's vocabulary. **Derived, never stored.**

        An edge lives in this package, once.  This is the view for the moment
        a kernel rule needs it as a triple, and it is computed on every call
        out of freshly built dicts, so a caller that edits what it gets back
        has edited its own copy and nothing else.  The alternative — writing
        the propositions into a :class:`~core.cognition.state.CognitiveState`
        when the edge is added — would make two owners of one fact, and the
        day they disagreed there would be no way to say which was the graph.

        Each item is ``{"triple", "authority", "evidence"}``, shaped to be
        splatted into an assertion.  **Which door it goes through is the
        caller's call and the kernel's rule**, not this package's: a
        ``DETERMINISTIC`` or ``SOURCE`` edge belongs at
        ``assert_observation`` and a ``MODEL_*`` one at ``assert_hypothesis``,
        and :data:`~core.cognition.types.OBSERVATION_AUTHORITIES` is where
        that is written down::

            for item in graph.as_propositions(workset.edges):
                door = (state.assert_observation
                        if item["authority"] in OBSERVATION_AUTHORITIES
                        else state.assert_hypothesis)
                door(item["triple"], authority=item["authority"],
                     evidence=item["evidence"])

        **Node kinds are deliberately not projected.**  Kinds are
        multi-valued here and every field is single-valued there, so a node
        that is both a ``person`` and an ``employee`` would arrive as two
        propositions that contest each other — a contradiction manufactured by
        the projection rather than found in the world.  A caller that wants
        kinds in the kernel picks a spelling that survives that rule, and it
        should have to pick it on purpose.
        """
        source = self._edges.values() if edges is None else edges
        return tuple({"triple": edge.triple,
                      "authority": edge.authority,
                      "evidence": tuple(edge.evidence)}
                     for edge in source)

    # ── reading: the shape of the whole thing ───────────────────────────────

    def stats(self) -> Dict[str, Any]:
        """Counts, JSON-safe and in a fixed shape.

        ``relations`` is in first-appearance order.  ``edge_authorities``
        lists all five, zeros included, in the enum's declaration order: a
        fixed shape diffs cleanly across runs, and a zero where an authority
        used to appear is exactly the thing worth seeing.
        """
        return {
            "nodes": len(self._nodes),
            "edges": len(self._edges),
            "kinds": len(self._kinds),
            "relations": dict(self._relations),
            "edge_authorities": {
                authority.value: sum(1 for edge in self._edges.values()
                                     if edge.authority is authority)
                for authority in EvidenceAuthority},
        }

    def digest(self) -> Dict[str, Any]:
        """A JSON-safe rendering of the whole graph, for comparison.

        Used by the replay tests and by anything that needs to say two graphs
        are the same one.  The node index is in here even though it is derived
        from the edges: it is a *cache* of the log, and a replay that rebuilt
        the edges correctly and the adjacency wrongly is exactly the bug this
        comparison exists to catch.
        """
        return {
            "edges": [_row(EDGE_KEYS, {
                "id": edge.id, "revision": edge.revision,
                "previous": edge.previous, "src": edge.src,
                "relation": edge.relation, "dst": edge.dst,
                "authority": edge.authority.value,
                "evidence": encode_evidence(edge.evidence),
                "history": [item.key for item in self._history[edge.id]]})
                for edge in self._edges.values()],
            "kinds": [_row(KIND_KEYS, {
                "id": item.id, "revision": item.revision,
                "previous": item.previous, "node": item.node,
                "kind": item.kind, "authority": item.authority.value,
                "evidence": encode_evidence(item.evidence),
                "history": [rev.key for rev in self._kind_history[item.id]]})
                for item in self._kinds.values()],
            "nodes": [{"node": view.node, "out": view.out_degree,
                       "in": view.in_degree, "relations": list(view.relations),
                       "kinds": list(view.kinds)}
                      for view in (self.node(name) for name in self._nodes)],
            "stats": self.stats(),
        }

    def digest_json(self) -> str:
        return json.dumps(self.digest(), sort_keys=True)


# ── small helpers ───────────────────────────────────────────────────────────

def _copy(value: Any) -> Any:
    """A deep copy of one JSON-shaped value.

    Written out rather than reached for from :mod:`copy`, because what is
    wanted is exactly the JSON shapes this package writes — dicts, lists and
    scalars — and ``deepcopy`` would also faithfully reproduce anything else
    somebody had managed to get into an event, which is not a thing to be
    helpful about in the one function that exports the log.
    """
    if isinstance(value, dict):
        return {key: _copy(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_copy(item) for item in value]
    return value


def _row(keys: Tuple[str, ...], built: Dict[str, Any]) -> Dict[str, Any]:
    """One digest row, checked against its declared key set.

    The declaration is only worth having if the code cannot drift from it, and
    a digest row is the one place where drifting *quietly* is the whole
    hazard: a key dropped from the rendering does not fail anything, it just
    stops the comparison looking at that property while every replay test goes
    on passing.  So the tuple is not documentation checked by a test — it is
    the thing the row is built against, and a mismatch in either direction is
    a programming error raised here.
    """
    if tuple(built) != keys:
        raise CognitionError(
            f"a digest row must carry exactly {keys}, not {tuple(built)}")
    return built


def _node_name(value: Any, what: str) -> str:
    """A name this package will store, or a refusal naming the reason.

    Four refusals beyond "non-empty string", each for a failure that is silent
    rather than loud:

    * **A leading ``?``.**  That spelling is the kernel's variable marker, and
      :meth:`KnowledgeGraph.as_propositions` hands these names straight into
      triples.  ``("?who", "knows", "bob")`` would arrive at a kernel door as
      something that looks like a pattern; the kernel refuses it there, which
      is one door too late — the edge is already in this graph, in six indexes
      and in the log, and the refusal names a call the caller has forgotten.
      Refusing at the door this package owns is the only place the message can
      still say which edge.
    * **Control characters.**  A newline in a node name is a name that breaks
      every line-oriented rendering of a working set, and a compiled context is
      line-oriented.  A name is a name, not a document.
    * **Lone surrogates.**  A string Python will hold and ``json.dumps`` will
      write but ``json.loads`` cannot read back is a graph that snapshots and
      never replays — the one corruption this package's whole event-log
      discipline is built to make impossible.
    * **Length.**  See :data:`NAME_CAP`.

    Unicode is otherwise welcome: entities in the world have names, and this
    package has no opinion about which alphabet they are in.
    """
    if not isinstance(value, str) or not value:
        raise CognitionError(f"{what} is a non-empty string, not {value!r}")
    if value.startswith("?"):
        raise CognitionError(
            f"{what} may not begin with '?' ({value!r}): that is the kernel's "
            "variable spelling, and as_propositions() projects these names "
            "into triples, so an edge stored under one would arrive at an "
            "assertion door looking like a pattern — refused there, where the "
            "message can no longer say which edge")
    if len(value) > NAME_CAP:
        raise CognitionError(
            f"{what} is {len(value)} characters; the cap is {NAME_CAP}, "
            "because a name is a key in six indexes, a string in every log "
            "line and a row in a compiled context, and none of those wants a "
            "document in it")
    for char in value:
        code = ord(char)
        if code < 0x20 or code == 0x7F:
            raise CognitionError(
                f"{what} carries the control character {char!r} ({value!r}); a "
                "newline or a tab in a name breaks every line-oriented "
                "rendering of a working set, and a compiled context is "
                "line-oriented")
        if 0xD800 <= code <= 0xDFFF:
            raise CognitionError(
                f"{what} carries a lone surrogate ({value!r}); Python will "
                "hold it and json.dumps will write it, but json.loads will "
                "not read it back — a graph that snapshots and never replays "
                "is the one corruption this package's log discipline exists "
                "to make impossible")
    return value


def _check_authority(authority: Any) -> EvidenceAuthority:
    if not isinstance(authority, EvidenceAuthority):
        raise CognitionError(
            "authority is an EvidenceAuthority, not "
            f"{type(authority).__name__}; the graph reuses the kernel's "
            "enum rather than minting a second one, so that an edge and the "
            "proposition beside it mean the same thing by the same word")
    return authority


def _check_evidence(evidence: Iterable[EvidenceRef], what: str,
                    authority: EvidenceAuthority) -> Tuple[EvidenceRef, ...]:
    """Validate the refs and stamp each with the authority it arrived on.

    The stamp is written here and nowhere else, so a ref in this store always
    says which call put it there — even after a merge has raised the edge's
    own authority above it.
    """
    refs = tuple(evidence)
    for ref in refs:
        if not isinstance(ref, EvidenceRef):
            raise CognitionError(
                f"evidence is EvidenceRef, not {type(ref).__name__}")
    if not refs:
        raise CognitionError(
            f"{what} with no evidence is a claim with no receipt; the graph "
            "exists so that every relationship traces to something, and "
            "there is no exception for an obvious one")
    return tuple(ref.stamped(authority) for ref in refs)


def _merge_evidence(held: Tuple[EvidenceRef, ...],
                    fresh: Iterable[EvidenceRef]) -> Tuple[EvidenceRef, ...]:
    """Union, order-preserving. Identical refs are one ref."""
    out = list(held)
    for ref in fresh:
        if ref not in out:
            out.append(ref)
    return tuple(out)


def _authority(raw: Any) -> EvidenceAuthority:
    try:
        return EvidenceAuthority(raw)
    except ValueError as exc:
        raise ReplayRefused(f"no evidence authority {raw!r}") from exc
