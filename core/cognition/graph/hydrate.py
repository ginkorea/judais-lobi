# core/cognition/graph/hydrate.py — huge graph, small working graph, tiny context

"""The load-bearing read: a bounded working set around a handful of seeds.

ROADMAP §2.9.7 states the shape in one line — *huge corpus graph → small
working graph → tiny context* — and this module is the middle arrow.  A
context compiler downstream turns a :class:`WorkingSet` into tokens; what
happens here is only the choosing, and the choosing is a walk with hard caps.

**A function, not a method, and that is a decision.**  The store owns storage
and adjacency; which slice of it is worth compiling is a *policy*, and the
policy is the part this arc expects to replace — nearest-first today, an
obligation-weighted walk when the frontier can say what it is missing, a
learned one after Phase 21.  Keeping it out of :class:`KnowledgeGraph` means
that replacement is a new function beside this one rather than a method
somebody has to subclass around, and it makes the ablation honest: an arm that
hydrates differently changes this call and nothing about what is stored.

**Truncation is never silent.**  Every budget in here is a hard cap, and every
cap that bit says so on the way out — :attr:`WorkingSet.truncated`, with
counts.  A working set that quietly dropped the edge the answer needed would
be indistinguishable from a graph that never had it, and the failure would
land downstream as the model "not knowing", which is the single most expensive
way for this arc to be wrong.

**The authority floor travels.**  ``min_authority`` is passed straight into
every :meth:`~core.cognition.graph.store.KnowledgeGraph.neighbors` call the
walk makes, so a working set compiled at ``SOURCE`` cannot contain a model's
guess at any depth.  There is no second filtering pass here to get out of step
with the store's.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import (Any, Dict, Iterable, List, Optional, Sequence, Tuple)

from core.cognition.graph.store import Edge, KnowledgeGraph
from core.cognition.types import CognitionError, EvidenceAuthority


@dataclass(frozen=True)
class WorkingSet:
    """A slice of a graph, with its edges, its rings, and what it left out.

    ``rings`` is the answer's shape: ring 0 is the seeds that were present,
    ring *k* is what a ``k``-edge walk reached first, and within a ring the
    order is the order the walk admitted nodes — which is the store's
    insertion order, expanded seed by seed.  :attr:`nodes` is the flattened
    reading of exactly that, derived rather than stored, so there is one owner
    of "which nodes are in here and in what order".

    ``edges`` carries every edge whole, authority included.  A working set of
    bare node names would be the place the trust boundary got lost, since a
    context compiler reading it has no way back to the store.

    ``truncated`` is true when a budget bit.  ``nodes_omitted`` and
    ``edges_omitted`` count the distinct nodes and edges the walk reached and
    refused — they are what the *bounded* walk saw, not a census of everything
    beyond the wall, because counting that would mean doing the unbounded walk
    this call exists to avoid.
    """

    seeds: Tuple[str, ...]
    missing_seeds: Tuple[str, ...]
    rings: Tuple[Tuple[str, ...], ...]
    edges: Tuple[Edge, ...]
    radius: int
    max_nodes: int
    max_edges: int
    truncated: bool = False
    nodes_omitted: int = 0
    edges_omitted: int = 0

    @property
    def nodes(self) -> Tuple[str, ...]:
        """Every node in the set, nearest first. Derived from ``rings``."""
        return tuple(node for ring in self.rings for node in ring)

    def depth_of(self, node: str) -> Optional[int]:
        """How many edges from the nearest seed, or ``None`` if not in here."""
        for depth, ring in enumerate(self.rings):
            if node in ring:
                return depth
        return None

    def digest(self) -> Dict[str, Any]:
        """A JSON-safe rendering, stable across runs of the same graph."""
        return {
            "seeds": list(self.seeds),
            "missing_seeds": list(self.missing_seeds),
            "rings": [list(ring) for ring in self.rings],
            "edges": [{"id": edge.id, "src": edge.src,
                       "relation": edge.relation, "dst": edge.dst,
                       "authority": edge.authority.value,
                       "revision": edge.revision}
                      for edge in self.edges],
            "radius": self.radius,
            "budgets": {"max_nodes": self.max_nodes,
                        "max_edges": self.max_edges},
            "truncated": self.truncated,
            "nodes_omitted": self.nodes_omitted,
            "edges_omitted": self.edges_omitted,
        }

    def digest_json(self) -> str:
        return json.dumps(self.digest(), sort_keys=True)


def hydrate(graph: KnowledgeGraph, seeds: Iterable[str], *,
            max_nodes: int, max_edges: int, radius: int,
            relations: Optional[Sequence[str]] = None,
            min_authority: Optional[EvidenceAuthority] = None) -> WorkingSet:
    """A bounded working set around ``seeds``. Deterministic, nearest-first.

    The walk is breadth-first and **undirected** — an edge is followed from
    either end, because the reference that names the seed is as much a part of
    the seed's neighbourhood as the one it names.  Ring by ring, node by node
    in admission order, and for each node its edges in the store's insertion
    order: the result is a function of the log, the seeds and the budgets, and
    of nothing else.

    **An edge is in the set only when both its ends are, and a node past the
    seeds is in it only as an end of an edge that is.**  Together those make
    the result a graph rather than a fringe of dangling arrows on one side and
    unreachable names on the other, and they are why either budget biting
    refuses *both* the edge and the node it would have brought: a node
    admitted over an edge that did not fit is a node the working set cannot
    say how it reached.  Edges *between* nodes already admitted come in as the
    walk meets them, and a closing pass picks up the ones between two nodes of
    the outermost ring — the only edges a ring-by-ring walk can miss — so the
    set is the subgraph *induced* on its nodes rather than a tree with a
    fringe.  Two nodes in a working set with the edge between them left out
    would read, to whatever compiles it, as two nodes that are unrelated.

    Budgets are hard caps on the whole set, not per ring, and seeds are
    admitted first: a caller who asks for five nodes and hands over six seeds
    gets five seeds and ``truncated``.  ``radius`` counts edges and is the
    caller's own bound rather than a budget, so exhausting it is not
    truncation — a walk that stopped where it was told to stop left nothing
    out that was asked for.
    """
    if max_nodes < 0 or max_edges < 0 or radius < 0:
        raise CognitionError(
            "max_nodes, max_edges and radius are counts and none of them may "
            f"be negative (got {max_nodes!r}, {max_edges!r}, {radius!r})")

    wanted = tuple(dict.fromkeys(seeds))
    for seed in wanted:
        if not isinstance(seed, str) or not seed:
            raise CognitionError(
                f"a seed is a non-empty node name, not {seed!r}")
    missing = tuple(seed for seed in wanted if not graph.has_node(seed))

    admitted: Dict[str, None] = {}
    omitted_nodes: Dict[str, None] = {}
    omitted_edges: Dict[str, None] = {}
    kept: Dict[str, Edge] = {}

    ring: List[str] = []
    for seed in wanted:
        if not graph.has_node(seed):
            continue
        if len(admitted) >= max_nodes:
            omitted_nodes.setdefault(seed, None)
            continue
        admitted[seed] = None
        ring.append(seed)
    rings: List[Tuple[str, ...]] = [tuple(ring)]

    for _depth in range(radius):
        if not ring:
            break
        nxt: List[str] = []
        for node in ring:
            for edge in graph.neighbors(node, relations=relations,
                                        min_authority=min_authority):
                far = edge.other(node)
                new_node = far not in admitted
                new_edge = edge.id not in kept
                if new_node and len(admitted) >= max_nodes:
                    omitted_nodes.setdefault(far, None)
                    if new_edge:
                        omitted_edges.setdefault(edge.id, None)
                    continue
                if new_edge and len(kept) >= max_edges:
                    omitted_edges.setdefault(edge.id, None)
                    if new_node:
                        omitted_nodes.setdefault(far, None)
                    continue
                if new_node:
                    admitted[far] = None
                    nxt.append(far)
                if new_edge:
                    kept[edge.id] = edge
        rings.append(tuple(nxt))
        ring = nxt

    while rings and not rings[-1]:
        rings.pop()

    # The closing pass: the outermost ring's edges *to nodes already in the
    # set*. Every inner ring was scanned on the way out, so the only edges the
    # walk can have missed are the ones between two nodes of the last ring —
    # and a working set that held two nodes and not the known edge between
    # them would read, to whatever compiles it, as "these two are unrelated".
    # It admits no nodes: a node beyond the radius is not omitted, it is
    # outside what was asked for.
    if rings and len(rings) - 1 == radius:
        for node in rings[-1]:
            for edge in graph.neighbors(node, relations=relations,
                                        min_authority=min_authority):
                if edge.other(node) not in admitted or edge.id in kept:
                    continue
                if len(kept) >= max_edges:
                    omitted_edges.setdefault(edge.id, None)
                    continue
                kept[edge.id] = edge

    return WorkingSet(
        seeds=wanted,
        missing_seeds=missing,
        rings=tuple(rings),
        edges=tuple(kept.values()),
        radius=radius,
        max_nodes=max_nodes,
        max_edges=max_edges,
        truncated=bool(omitted_nodes or omitted_edges),
        nodes_omitted=len(omitted_nodes),
        edges_omitted=len(omitted_edges),
    )
