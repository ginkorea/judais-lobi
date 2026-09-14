# core/cognition/graph/harvest.py — the kernel's links, read as a topology

"""What a store already believes, entered into a graph. **Deterministically.**

:mod:`core.cognition.graph.store` holds edges and :mod:`core.cognition.graph
.hydrate` chooses a bounded slice of them.  Neither of them knows where an
edge *comes from*, and this module is the one answer this release ships:
**the kernel's own links**.  ``ROADMAP.md`` §2.9.7's graph arm asks for a
working set around what is owed, and a working set is only worth compiling if
the edges in it were not guessed.

**One source, and it is already a claim with two premises.**  A
:class:`~core.cognition.types.Link` says a receipt entity is *about* a
subject, it was made from a platform's declaration and a receipt value (see
:meth:`core.runtime.cognition.ShadowCognition._identify`), and it carries the
``SOURCE`` authority and the evidence that says so.  Every edge this module
writes is one of those links, with **the link's own authority and the link's
own evidence** — nothing is upgraded, nothing is invented, and no edge in a
graph built by this module rests on anything a model said.

**Why there is exactly one relation.**  The obvious second candidate is the
*projection*: the kernel concludes ``job:jl-731 · state`` from
``mcp.job_status#r5 · state`` under
:data:`~core.cognition.state.PROJECTION_RULE_ID`, and one could write a
``read_from`` edge for it.  It would connect the same two nodes the link
already connects, in the other direction, and it would therefore add no
reachability, no new node and no new hop — while making "this receipt is
about this subject" a fact with two owners in one store, which is the defect
the whole graph/kernel division exists to prevent.  So the projection is what
makes the link edge *worth having* and is not itself an edge.  The
field-level question a projection answers — which figure joined — is answered
in the compiled view's FACTS section, where the handle is already on the line.

**Nothing here re-derives or re-spells anything.**  The links come from
:meth:`~core.cognition.state.CognitiveState.links`, the subject's kind from
:attr:`~core.cognition.types.Link.kind`, and the seeds from a
:class:`~core.cognition.types.Frontier` the kernel ranked.  This module owns
no fact; it owns a *translation*, and the translation is total and
order-free: the same store produces the same graph, whatever order anything
was read in.

**Pure, like both its neighbours.**  No I/O, no clock, no randomness, and
nothing imported from :mod:`core.runtime` — the attachment that writes the
log and hydrates for a prompt is up there, and it passes what it has down
here.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional, Sequence, Tuple

from core.cognition.graph.hydrate import WorkingSet, hydrate
from core.cognition.graph.store import KnowledgeGraph
from core.cognition.types import (EvidenceAuthority, is_variable,
                                  subject_parts)

__all__ = [
    "HOP_BOUND", "LINK_RELATION", "MAX_EDGES", "MAX_NODES",
    "LinkHarvest", "seeds_from", "working_set",
]

#: The one relation this release harvests: a receipt entity is *about* a
#: subject.  A word and not a symbol, because it is rendered into a line a
#: person reads, and the same word the kernel's own :meth:`Link.render` uses.
LINK_RELATION = "about"

#: How many edges out from a seed a working set reaches.
#:
#: **Two, and the number is a property of the graph this module builds.**
#: With one relation the topology is bipartite — receipts on one side,
#: subjects on the other — so from a subject that something is owed about:
#: hop 1 is *the calls that named it*, and hop 2 is *the other subjects those
#: same calls also named* (the job and the asset one receipt was about).  That
#: second ring is the whole reason a graph is here rather than a list of
#: links: it is the only part of the answer the FACTS section cannot already
#: show, because a subject nothing has been established about has no facts to
#: render.
#:
#: A third hop is the receipts of *those* subjects, and it is where the cost
#: stops being bounded by the question: it grows with the fan-out of the
#: second ring, and every line it adds is a call two removes from what is
#: owed.  The context-budget doctrine binds here as it does everywhere in
#: this arc — what we add must not bloat the context — and RELATED is the
#: section that drops first, so a hop that is usually cut is a hop that costs
#: compute and buys nothing.  Raising it is a one-constant change with an
#: ablation arm already pointed at it.
HOP_BOUND = 2

#: The working set's hard caps, in nodes and in edges.  ``MAX_EDGES`` is also
#: the most RELATED lines a block can carry, and the two numbers are chosen
#: together: twelve lines is a section a reader takes in, and twenty-four
#: nodes is enough for those twelve edges to be a connected picture rather
#: than a fringe.  Both are caps and not targets — a walk that bites one says
#: so, through :attr:`~core.cognition.graph.hydrate.WorkingSet.truncated`,
#: and the view renders that rather than swallowing it.
MAX_NODES = 24
MAX_EDGES = 12


class LinkHarvest:
    """The kernel's links, written into a graph **once each**.

    Stateful on purpose, and the state is one cursor: ``{link id: the record
    key that was harvested}``.  Without it a harvest at every step boundary
    would call :meth:`~core.cognition.graph.store.KnowledgeGraph.add_edge`
    for every link the store has ever held, every step — and ``add_edge``
    appends an event whether or not it changes anything, which is right for
    a log a replay applies and wrong for a caller that has nothing new to
    say.  A thirty-step run would write a log quadratic in its own links.

    Keyed on :attr:`~core.cognition.types.Link.key` (``l3@2``) rather than on
    the link id, so a link whose evidence unioned or whose authority rose
    since the last step is harvested **again** — which is exactly what
    ``add_edge``'s merge is for, and the one case where re-stating an edge
    is not a no-op.

    Idempotent in the property that matters: harvesting a store twice with
    the same instance writes nothing the second time, and harvesting it twice
    with two instances produces the same graph (the second pass merges into
    edges that already carry everything it offers).
    """

    def __init__(self) -> None:
        self._seen: Dict[str, str] = {}

    @property
    def harvested(self) -> int:
        """How many links this harvest has written an edge for."""
        return len(self._seen)

    def into(self, state: Any, graph: KnowledgeGraph) -> int:
        """Every link *state* holds and this harvest has not, as edges.

        Returns how many links were written this time.  Two writes per link
        and both carry the link's own authority and evidence: the edge
        itself, and the subject's **kind** — which is a declaration the
        platform made (``job``), not a reading of the name, and is the one
        node-level statement the graph package owns.

        The receipt end gets no kind.  Nobody declared one: a receipt entity
        is the harness's own spelling of "this call, in this run", and
        stamping a kind on it would be this module inventing a statement to
        make the graph look symmetrical.
        """
        written = 0
        for link in state.links():
            if self._seen.get(link.id) == link.key:
                continue
            graph.add_edge(link.entity, LINK_RELATION, link.subject,
                           authority=link.authority, evidence=link.evidence)
            graph.node_kind(link.subject, link.kind,
                            authority=link.authority, evidence=link.evidence)
            self._seen[link.id] = link.key
            written += 1
        return written

    def seed_from(self, state: Any, graph: KnowledgeGraph) -> int:
        """Mark the links *graph* already holds an edge for as harvested.

        The resume door, and it exists because the two logs are written by
        the same process at the same points: a run that stopped has a
        ``reasoning.jsonl`` holding its links and a ``graph.jsonl`` holding
        the edges made from them, and the process that picks both up must
        not re-state every one of those edges into the log it just replayed.

        Presence of the edge is the test, and the cursor is set to the
        link's **current** key — so a link whose record changed while the
        file was closed is treated as harvested rather than re-merged.  That
        is the one inexactness here and it is bounded: the two logs were
        written together, so a link can only have moved if one of them was
        edited by hand, and the cost is a merge that would have changed
        nothing.
        """
        found = 0
        for link in state.links():
            if graph.find(link.entity, LINK_RELATION, link.subject) is None:
                continue
            self._seen[link.id] = link.key
            found += 1
        return found


def seeds_from(frontier: Iterable[Any]) -> Tuple[str, ...]:
    """The node names a frontier's obligations name, nearest-ranked first.

    An obligation is a pattern — ``(job:jl-731, state, ?v)`` — and what a
    working set can be hydrated around is the parts of it that are **names
    of things**: the entity term, and the value term where it is spelled
    like a subject.  A field is never a node, and a variable is the hole the
    obligation is *about* rather than a name to walk from.

    The value term is admitted only when :func:`~core.cognition.types
    .subject_parts` recognises it, and the reason is the failure the looser
    rule has: an obligation whose value is the literal ``"completed"`` would
    seed a walk at a node called ``completed``, which is a *value* that two
    unrelated subjects share — value coincidence, arriving through the seed
    list rather than through an edge, which is precisely what the link
    discipline refuses one layer down.  The entity term needs no such guard:
    the entity position of a store's triple is a name by construction.

    Order is the frontier's own — the order the runtime would work the
    obligations in — and duplicates collapse to their first appearance, so a
    walk's rings are a function of the ranking and not of how many goals
    mention one subject.
    """
    out: Dict[str, None] = {}
    for obligation in frontier:
        pattern = getattr(obligation, "pattern", ())
        if len(pattern) != 3:                   # pragma: no cover - defensive
            continue
        entity, _field, value = pattern
        if isinstance(entity, str) and entity and not is_variable(entity):
            out.setdefault(entity, None)
        if (isinstance(value, str) and value and not is_variable(value)
                and subject_parts(value) is not None):
            out.setdefault(value, None)
    return tuple(out)


def working_set(graph: KnowledgeGraph, seeds: Sequence[str], *,
                radius: int = HOP_BOUND, max_nodes: int = MAX_NODES,
                max_edges: int = MAX_EDGES,
                min_authority: Optional[EvidenceAuthority] = None
                ) -> WorkingSet:
    """:func:`~core.cognition.graph.hydrate.hydrate` at this arm's bounds.

    One owner of "how far, and how much", so the number a docstring argues
    and the number a run walks are the same number.  Everything else is
    ``hydrate``'s, unchanged and unwrapped: the walk, the induced-subgraph
    rule, the truncation flags.

    No authority floor by default, and that is not a gap: every edge a
    :class:`LinkHarvest` writes carries the authority of the link it came
    from, and this release makes links from declarations only.  The
    parameter is here because the day a graph holds an edge from somewhere
    else, a caller compiling a prompt must be able to floor the whole
    working set in one place rather than filtering a result it has already
    paid to compute.
    """
    return hydrate(graph, seeds, max_nodes=max_nodes, max_edges=max_edges,
                   radius=radius, min_authority=min_authority)
