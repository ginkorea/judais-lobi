# tests/test_cognition_graph.py — the topology store: identity, the boundary, the walks

"""What the graph promises about edges, and the wall it keeps while it does.

**That an edge has one identity and accumulates.**  ``(src, relation, dst)``
is the edge; re-adding it unions evidence and takes the strongest authority
offered, writing a revision rather than editing one.  The direction of that
last rule is the whole test: an edge a model guessed and a reference later
confirmed is deterministic, and the reverse re-statement does not undo the
reference.

**That the trust boundary holds at every read.**  ROADMAP §2.9.7 —
*graph edges enter with authority, never as silent truth*.  So every read that
returns edges is asked, here, to floor on ``min_authority``, and a
``MODEL_EXTRACTION`` edge is asked to stay out of a ``SOURCE`` answer at every
depth of every walk.

**That the order is the log's and nothing else's.**  Neighbours, paths and
working sets are insertion-ordered, and the same log under a different
``PYTHONHASHSEED`` is the same answer — asserted in a subprocess, because the
seed is fixed before the interpreter this test is running in started.

**That a budget that bit says so.**  A working set that quietly dropped the
edge the answer needed is indistinguishable downstream from a graph that never
had it, and the failure lands as the model "not knowing".  Truncation is
flagged and counted, and both are asserted.

**That the kernel projection is derived.**  ``as_propositions`` is a view
computed on call.  Nothing writes it into a store, and editing what it returns
edits a copy — the one shape that would give two owners to one fact.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from core.cognition.graph import (DIGEST_KEYS, EDGE_KEYS, KIND_KEYS, NAME_CAP,
                                  STATS_KEYS, KnowledgeGraph, WorkingSet,
                                  hydrate)
from core.cognition.types import (CognitionError, EvidenceAuthority,
                                  EvidenceRef, UnknownId)

REPO = Path(__file__).resolve().parent.parent

RECEIPT = EvidenceRef(kind="receipt", locator="seq:1")
OTHER = EvidenceRef(kind="receipt", locator="seq:2")
GUESS = EvidenceRef(kind="extraction", locator="turn:1")

SOURCE = EvidenceAuthority.SOURCE
DETERMINISTIC = EvidenceAuthority.DETERMINISTIC
EXTRACTED = EvidenceAuthority.MODEL_EXTRACTION
GUESSED = EvidenceAuthority.MODEL_HYPOTHESIS


def _graph(*edges):
    """A graph from ``(src, relation, dst, authority)`` tuples, in order."""
    graph = KnowledgeGraph()
    for src, relation, dst, authority in edges:
        evidence = [GUESS] if authority in (EXTRACTED, GUESSED) else [RECEIPT]
        graph.add_edge(src, relation, dst, authority=authority,
                       evidence=evidence)
    return graph


def _company():
    """A small worked graph reused by the walk tests.

    ``alice`` reports to ``bob`` who owns ``acct-1``; ``alice`` is *said* to
    know ``carol`` by a model, and ``carol`` owns ``acct-2`` on a receipt.
    The model edge is the only weak link between alice and acct-2, which is
    what makes the authority floor visible as a change in reachability.
    """
    return _graph(
        ("alice", "reports_to", "bob", SOURCE),
        ("bob", "owns", "acct-1", DETERMINISTIC),
        ("alice", "knows", "carol", EXTRACTED),
        ("carol", "owns", "acct-2", SOURCE),
    )


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------

class TestAnEdgeIsItsTriple:
    def test_re_adding_the_same_edge_is_the_same_edge(self):
        graph = KnowledgeGraph()
        first = graph.add_edge("alice", "knows", "bob", authority=SOURCE,
                               evidence=[RECEIPT])
        again = graph.add_edge("alice", "knows", "bob", authority=SOURCE,
                               evidence=[RECEIPT])
        assert first == again
        assert len(graph.edges()) == 1

    def test_the_same_pair_under_another_relation_is_another_edge(self):
        graph = KnowledgeGraph()
        graph.add_edge("alice", "knows", "bob", authority=SOURCE,
                       evidence=[RECEIPT])
        graph.add_edge("alice", "reports_to", "bob", authority=SOURCE,
                       evidence=[RECEIPT])
        assert len(graph.edges()) == 2

    def test_a_relation_is_not_single_valued(self):
        """The point of having a graph at all. The kernel would contest these
        two as one field with two values; here they are two edges and neither
        is news about the other."""
        graph = _graph(("alice", "knows", "bob", SOURCE),
                       ("alice", "knows", "carol", SOURCE))
        assert [edge.dst for edge in graph.neighbors("alice")] == \
            ["bob", "carol"]
        assert graph.stats()["relations"] == {"knows": 2}

    def test_direction_is_part_of_the_identity(self):
        graph = _graph(("alice", "knows", "bob", SOURCE),
                       ("bob", "knows", "alice", SOURCE))
        assert len(graph.edges()) == 2
        assert graph.node("alice").out_degree == 1
        assert graph.node("alice").in_degree == 1

    def test_re_adding_unions_the_evidence(self):
        graph = KnowledgeGraph()
        eid = graph.add_edge("alice", "knows", "bob", authority=SOURCE,
                             evidence=[RECEIPT])
        graph.add_edge("alice", "knows", "bob", authority=SOURCE,
                       evidence=[OTHER, RECEIPT])
        assert graph.edge(eid).evidence == (RECEIPT.stamped(SOURCE),
                                            OTHER.stamped(SOURCE))
        assert graph.edge(eid).revision == 2

    def test_re_adding_takes_the_strongest_authority(self):
        """The direction is the test. A model's guess later confirmed by a
        reference is a deterministic edge; the same re-statement the other way
        round does not unseat the reference."""
        graph = KnowledgeGraph()
        eid = graph.add_edge("alice", "knows", "bob", authority=EXTRACTED,
                             evidence=[GUESS])
        graph.add_edge("alice", "knows", "bob", authority=DETERMINISTIC,
                       evidence=[RECEIPT])
        assert graph.edge(eid).authority is DETERMINISTIC
        graph.add_edge("alice", "knows", "bob", authority=GUESSED,
                       evidence=[GUESS])
        assert graph.edge(eid).authority is DETERMINISTIC

    def test_the_weaker_evidence_stays_on_the_record(self):
        """Upgrading the authority is not forgetting how it first arrived."""
        graph = KnowledgeGraph()
        eid = graph.add_edge("alice", "knows", "bob", authority=EXTRACTED,
                             evidence=[GUESS])
        graph.add_edge("alice", "knows", "bob", authority=DETERMINISTIC,
                       evidence=[RECEIPT])
        assert graph.edge(eid).evidence == (GUESS.stamped(EXTRACTED),
                                            RECEIPT.stamped(DETERMINISTIC))
        assert [item.authority for item in graph.history(eid)] == \
            [EXTRACTED, DETERMINISTIC]
        assert graph.history(eid)[1].previous == "e1@1"

    def test_the_union_does_not_erase_which_ref_the_model_produced(self):
        """The wall the merge would otherwise rub out. One authority now
        stands over the edge; each ref still says the word it arrived on, so
        "how do we know this" survives any number of merges — which is what a
        working set compiled from here is eventually asked."""
        graph = KnowledgeGraph()
        eid = graph.add_edge("alice", "knows", "bob", authority=EXTRACTED,
                             evidence=[GUESS])
        graph.add_edge("alice", "knows", "bob", authority=DETERMINISTIC,
                       evidence=[RECEIPT])
        edge = graph.edge(eid)
        assert edge.authority is DETERMINISTIC
        assert [ref.authority for ref in edge.evidence] == \
            [EXTRACTED, DETERMINISTIC]
        assert [ref.locator for ref in edge.evidence
                if ref.authority in (EXTRACTED, GUESSED)] == [GUESS.locator]

    def test_the_stamp_is_the_calls_word_not_the_callers(self):
        """A caller that pre-filled the field does not get to keep it: what
        is recorded is the door the ref came through."""
        graph = KnowledgeGraph()
        lying = EvidenceRef(kind="extraction", locator="turn:9",
                            authority=DETERMINISTIC)
        eid = graph.add_edge("alice", "knows", "bob", authority=EXTRACTED,
                             evidence=[lying])
        assert graph.edge(eid).evidence[0].authority is EXTRACTED

    def test_the_same_locator_on_two_words_is_two_refs(self):
        """Cited once by a model and once by a receipt is two statements of
        support, not one deduplicated into whichever arrived first."""
        graph = KnowledgeGraph()
        eid = graph.add_edge("alice", "knows", "bob", authority=EXTRACTED,
                             evidence=[RECEIPT])
        graph.add_edge("alice", "knows", "bob", authority=SOURCE,
                       evidence=[RECEIPT])
        assert [ref.authority for ref in graph.edge(eid).evidence] == \
            [EXTRACTED, SOURCE]

    def test_a_re_add_that_changes_nothing_writes_no_revision(self):
        """The event happened and is logged; the belief did not move."""
        graph = KnowledgeGraph()
        eid = graph.add_edge("alice", "knows", "bob", authority=SOURCE,
                             evidence=[RECEIPT])
        graph.add_edge("alice", "knows", "bob", authority=SOURCE,
                       evidence=[RECEIPT])
        assert graph.edge(eid).revision == 1
        assert len(graph.events) == 2

    def test_a_self_loop_is_an_edge_and_counts_at_both_ends(self):
        graph = _graph(("alice", "knows", "alice", SOURCE))
        assert graph.node("alice").degree == 2
        assert [edge.id for edge in graph.neighbors("alice")] == ["e1"], \
            "a self-loop is in both buckets and must still come back once"


class TestNothingEntersWithoutAReceipt:
    def test_an_edge_with_no_evidence_is_refused(self):
        graph = KnowledgeGraph()
        with pytest.raises(CognitionError):
            graph.add_edge("alice", "knows", "bob", authority=SOURCE,
                           evidence=[])
        assert graph.events == ()

    def test_authority_has_no_default(self):
        """The one line of code that would turn a guess into a
        deterministic-looking edge is the default value this call does not
        have."""
        graph = KnowledgeGraph()
        with pytest.raises(TypeError):
            graph.add_edge("alice", "knows", "bob", evidence=[RECEIPT])

    def test_an_authority_from_somewhere_else_is_refused(self):
        graph = KnowledgeGraph()
        with pytest.raises(CognitionError):
            graph.add_edge("alice", "knows", "bob", authority="source",
                           evidence=[RECEIPT])

    def test_an_empty_name_is_refused(self):
        graph = KnowledgeGraph()
        for triple in (("", "knows", "bob"), ("alice", "", "bob"),
                       ("alice", "knows", "")):
            with pytest.raises(CognitionError):
                graph.add_edge(*triple, authority=SOURCE, evidence=[RECEIPT])
        assert graph.events == ()


class TestANameIsAName:
    """Four refusals beyond "non-empty string", each for a failure that would
    otherwise be silent rather than loud."""

    @pytest.mark.parametrize("position", [0, 1, 2])
    def test_the_kernels_variable_spelling_is_refused(self, position):
        """``as_propositions`` projects these names into triples, so an edge
        stored under ``?who`` would arrive at a kernel door looking like a
        pattern — refused there, one door too late, in a message that can no
        longer say which edge."""
        graph = KnowledgeGraph()
        triple = ["alice", "knows", "bob"]
        triple[position] = "?who"
        with pytest.raises(CognitionError, match=r"\?"):
            graph.add_edge(*triple, authority=SOURCE, evidence=[RECEIPT])
        assert graph.events == ()

    def test_the_refusal_says_why_it_is_this_packages_business(self):
        graph = KnowledgeGraph()
        with pytest.raises(CognitionError, match="as_propositions"):
            graph.add_edge("?who", "knows", "bob", authority=SOURCE,
                           evidence=[RECEIPT])

    @pytest.mark.parametrize("name", ["two\nlines", "a\tb", "bell\x07",
                                      "null\x00byte", "del\x7f"])
    def test_a_control_character_is_refused(self, name):
        """A newline in a node name breaks every line-oriented rendering of a
        working set, and a compiled context is line-oriented."""
        graph = KnowledgeGraph()
        with pytest.raises(CognitionError):
            graph.add_edge(name, "knows", "bob", authority=SOURCE,
                           evidence=[RECEIPT])
        assert graph.events == ()

    def test_a_lone_surrogate_is_refused(self):
        """Python holds it and ``json.dumps`` writes it; ``json.loads`` will
        not read it back. A graph that snapshots and never replays is the one
        corruption the whole log discipline exists to make impossible — so the
        refusal is checked *and* the round trip it protects."""
        graph = KnowledgeGraph()
        with pytest.raises(CognitionError):
            graph.add_edge("bad\ud800name", "knows", "bob", authority=SOURCE,
                           evidence=[RECEIPT])
        assert graph.events == ()
        graph.add_edge("平文", "knows", "bob", authority=SOURCE,
                       evidence=[RECEIPT])
        again = KnowledgeGraph.replay(
            json.loads(json.dumps(graph.snapshot())))
        assert again.digest_json() == graph.digest_json()

    def test_a_name_longer_than_the_cap_is_refused(self):
        graph = KnowledgeGraph()
        assert NAME_CAP > 0
        graph.add_edge("x" * NAME_CAP, "knows", "bob", authority=SOURCE,
                       evidence=[RECEIPT])
        with pytest.raises(CognitionError, match=str(NAME_CAP)):
            graph.add_edge("x" * (NAME_CAP + 1), "knows", "bob",
                           authority=SOURCE, evidence=[RECEIPT])

    def test_the_rest_of_unicode_is_welcome(self):
        """Entities in the world have names, and this package has no opinion
        about which alphabet they are in."""
        graph = KnowledgeGraph()
        graph.add_edge("Ελλάδα", "γειτονεύει", "Ιταλία", authority=SOURCE,
                       evidence=[RECEIPT])
        graph.add_edge("naïve café", "serves", "☕", authority=SOURCE,
                       evidence=[RECEIPT])
        assert len(graph.edges()) == 2
        assert graph.node("Ελλάδα").degree == 1

    def test_a_kind_statement_is_held_to_the_same_names(self):
        graph = KnowledgeGraph()
        for pair in (("?who", "person"), ("alice", "?kind"),
                     ("two\nlines", "person"), ("alice", "x" * 9999)):
            with pytest.raises(CognitionError):
                graph.node_kind(*pair, authority=SOURCE, evidence=[RECEIPT])
        assert graph.events == ()


class TestTheOneNodeLevelStatement:
    def test_a_kind_is_stored_with_its_authority(self):
        graph = KnowledgeGraph()
        graph.node_kind("alice", "person", authority=EXTRACTED,
                        evidence=[GUESS])
        assert graph.node("alice").kinds == ("person",)
        assert graph.kinds("alice")[0].authority is EXTRACTED

    def test_a_node_may_be_two_kinds(self):
        """Kinds do not collide here. If two of them are genuinely
        incompatible that is a claim about the world, and the kernel is where
        claims about the world are contested."""
        graph = KnowledgeGraph()
        graph.node_kind("alice", "person", authority=SOURCE,
                        evidence=[RECEIPT])
        graph.node_kind("alice", "employee", authority=SOURCE,
                        evidence=[RECEIPT])
        assert graph.node("alice").kinds == ("person", "employee")

    def test_re_stating_a_kind_merges_like_an_edge(self):
        graph = KnowledgeGraph()
        kid = graph.node_kind("alice", "person", authority=EXTRACTED,
                              evidence=[GUESS])
        graph.node_kind("alice", "person", authority=SOURCE,
                        evidence=[RECEIPT])
        held = graph.kinds("alice")[0]
        assert held.id == kid
        assert held.authority is SOURCE
        assert held.evidence == (GUESS.stamped(EXTRACTED),
                                 RECEIPT.stamped(SOURCE))
        assert held.revision == 2

    def test_a_kind_makes_a_node_the_graph_did_not_have(self):
        graph = KnowledgeGraph()
        graph.node_kind("acct-1", "account", authority=SOURCE,
                        evidence=[RECEIPT])
        assert graph.nodes() == ("acct-1",)
        assert graph.node("acct-1").degree == 0


# ---------------------------------------------------------------------------
# The trust boundary
# ---------------------------------------------------------------------------

class TestAModelEdgeNeverPassesForAReference:
    """ROADMAP §2.9.7: graph edges enter with authority, never as silent
    truth. Both kinds are storable; no read confuses them."""

    def test_both_kinds_are_storable(self):
        graph = _company()
        assert graph.stats()["edge_authorities"]["model_extraction"] == 1
        assert graph.stats()["edge_authorities"]["source"] == 2

    def test_every_returned_edge_carries_its_authority(self):
        graph = _company()
        for edge in graph.neighbors("alice"):
            assert isinstance(edge.authority, EvidenceAuthority)

    def test_the_floor_drops_the_weaker_edge(self):
        graph = _company()
        assert [edge.relation for edge in graph.neighbors("alice")] == \
            ["reports_to", "knows"]
        assert [edge.relation
                for edge in graph.neighbors("alice", min_authority=SOURCE)] \
            == ["reports_to"]

    def test_the_floor_is_a_rank_and_not_an_equality(self):
        """``SOURCE`` keeps everything at least as strong, so a
        ``DETERMINISTIC`` edge stays; only the model's is dropped."""
        graph = _company()
        strong = graph.neighbors("bob", min_authority=SOURCE)
        assert [edge.authority for edge in strong] == [DETERMINISTIC, SOURCE]
        assert graph.neighbors("alice", min_authority=DETERMINISTIC) == ()

    def test_a_path_through_a_model_edge_is_not_reachable_at_source(self):
        """The floor travels the whole walk, not just its first step."""
        graph = _company()
        assert graph.reachable("alice", "acct-2", max_depth=4) is not None
        assert graph.reachable("alice", "acct-2", max_depth=4,
                               min_authority=SOURCE) is None

    def test_a_working_set_floored_at_source_holds_no_guess(self):
        graph = _company()
        loose = hydrate(graph, ["alice"], max_nodes=20, max_edges=20,
                        radius=3)
        assert "carol" in loose.nodes
        strict = hydrate(graph, ["alice"], max_nodes=20, max_edges=20,
                         radius=3, min_authority=SOURCE)
        assert "carol" not in strict.nodes
        assert all(edge.authority is not EXTRACTED for edge in strict.edges)

    def test_a_degree_is_a_summary_and_is_floored_too(self):
        """The quietest way for a guess to reach a decision. "How connected is
        this node" answered at ``SOURCE`` has to mean connected by things the
        caller would accept, or the number is about a graph nobody asked for —
        and a number needs no reading of the edges to be believed."""
        graph = _graph(("alice", "reports_to", "bob", SOURCE),
                       ("alice", "knows", "carol", EXTRACTED),
                       ("dave", "knows", "alice", EXTRACTED))
        assert graph.node("alice").degree == 3
        floored = graph.node("alice", min_authority=SOURCE)
        assert (floored.out_degree, floored.in_degree) == (1, 0)
        assert floored.degree == 1
        assert floored.relations == ("reports_to",)

    def test_the_floored_relations_are_a_subsequence_of_the_others(self):
        """A filter that also reordered would be read as a reordering."""
        graph = _graph(("hub", "a_rel", "x", EXTRACTED),
                       ("y", "b_rel", "hub", SOURCE),
                       ("hub", "c_rel", "z", SOURCE))
        loose = list(graph.node("hub").relations)
        strict = list(graph.node("hub", min_authority=SOURCE).relations)
        assert loose == ["a_rel", "b_rel", "c_rel"]
        assert strict == ["b_rel", "c_rel"]
        assert [item for item in loose if item in strict] == strict

    def test_a_kind_is_floored_with_everything_else(self):
        graph = KnowledgeGraph()
        graph.node_kind("alice", "person", authority=SOURCE,
                        evidence=[RECEIPT])
        graph.node_kind("alice", "suspect", authority=EXTRACTED,
                        evidence=[GUESS])
        assert graph.node("alice").kinds == ("person", "suspect")
        assert graph.node("alice", min_authority=SOURCE).kinds == ("person",)

    def test_an_upgraded_edge_passes_the_floor_it_used_to_fail(self):
        """The floor reads the live revision, which is the only reading that
        makes confirming an extraction worth doing."""
        graph = _graph(("alice", "knows", "bob", EXTRACTED))
        assert graph.neighbors("alice", min_authority=SOURCE) == ()
        graph.add_edge("alice", "knows", "bob", authority=SOURCE,
                       evidence=[RECEIPT])
        assert len(graph.neighbors("alice", min_authority=SOURCE)) == 1


# ---------------------------------------------------------------------------
# The walks
# ---------------------------------------------------------------------------

class TestNeighboursAreTheLogsOrder:
    def test_out_then_in_each_in_insertion_order(self):
        graph = _graph(("alice", "knows", "bob", SOURCE),
                       ("carol", "knows", "alice", SOURCE),
                       ("alice", "owns", "acct-1", SOURCE))
        assert [edge.id for edge in graph.neighbors("alice")] == \
            ["e1", "e3", "e2"]
        assert [edge.id for edge in graph.neighbors("alice",
                                                    direction="out")] == \
            ["e1", "e3"]
        assert [edge.id for edge in graph.neighbors("alice",
                                                    direction="in")] == ["e2"]

    def test_a_relation_filter_does_not_reorder_the_answer(self):
        """One relation and two relations are ordered by the same rule —
        insertion — rather than by the caller's argument list, which is the
        difference nobody would notice until the two disagreed."""
        graph = _graph(("alice", "knows", "bob", SOURCE),
                       ("alice", "owns", "acct-1", SOURCE),
                       ("alice", "knows", "carol", SOURCE))
        assert [edge.id for edge in
                graph.neighbors("alice", relations=["owns", "knows"])] == \
            ["e1", "e2", "e3"]
        assert [edge.id for edge in
                graph.neighbors("alice", relations=["knows"])] == ["e1", "e3"]
        assert graph.neighbors("alice", relations=[]) == ()

    def test_an_unknown_node_is_refused_not_answered_empty(self):
        graph = _company()
        with pytest.raises(UnknownId):
            graph.neighbors("nobody")
        with pytest.raises(UnknownId):
            graph.node("nobody")

    def test_a_direction_this_package_has_no_name_for_is_refused(self):
        graph = _company()
        with pytest.raises(CognitionError):
            graph.neighbors("alice", direction="upward")


class TestReachableIsABoundedBreadthFirstWalk:
    def test_it_finds_a_path_and_returns_the_edges(self):
        graph = _company()
        path = graph.reachable("alice", "acct-1", max_depth=3)
        assert [edge.id for edge in path] == ["e1", "e2"]

    def test_depth_counts_edges(self):
        graph = _company()
        assert graph.reachable("alice", "acct-1", max_depth=1) is None
        assert graph.reachable("alice", "acct-1", max_depth=2) is not None

    def test_a_node_reaches_itself_over_no_edges(self):
        """An empty tuple is a real answer here; `is None` is the test, and
        a caller reading this for truthiness reads it wrong."""
        graph = _company()
        assert graph.reachable("alice", "alice", max_depth=0) == ()
        assert graph.reachable("alice", "alice", max_depth=0) is not None

    def test_the_walk_is_undirected(self):
        graph = _company()
        assert graph.reachable("acct-1", "alice", max_depth=3) is not None

    def test_it_takes_the_shortest_and_then_the_earliest(self):
        """Two paths of two edges; the one whose first edge was inserted
        first is the one that comes back, every time."""
        graph = _graph(("alice", "via", "long", SOURCE),
                       ("long", "via", "target", SOURCE),
                       ("alice", "via", "short", SOURCE),
                       ("short", "via", "target", SOURCE))
        assert [edge.id for edge in
                graph.reachable("alice", "target", max_depth=4)] == \
            ["e1", "e2"]

    def test_a_relation_filter_can_cut_the_only_path(self):
        graph = _company()
        assert graph.reachable("alice", "acct-1", max_depth=3,
                               relations=["reports_to"]) is None

    def test_a_negative_depth_is_refused(self):
        graph = _company()
        with pytest.raises(CognitionError):
            graph.reachable("alice", "bob", max_depth=-1)

    def test_a_cycle_does_not_hang_the_walk(self):
        graph = _graph(("a", "next", "b", SOURCE), ("b", "next", "c", SOURCE),
                       ("c", "next", "a", SOURCE),
                       ("island", "next", "island", SOURCE))
        assert graph.reachable("a", "c", max_depth=9) is not None
        assert graph.reachable("a", "island", max_depth=99) is None


# ---------------------------------------------------------------------------
# Hydrate
# ---------------------------------------------------------------------------

def _chain(length, authority=SOURCE):
    """``n0 -next-> n1 -next-> …``, one edge per link."""
    return _graph(*[(f"n{i}", "next", f"n{i + 1}", authority)
                    for i in range(length)])


class TestAWorkingSetIsNearestFirst:
    def test_the_rings_are_the_distance_from_the_seed(self):
        graph = _chain(4)
        workset = hydrate(graph, ["n0"], max_nodes=10, max_edges=10, radius=3)
        assert workset.rings == (("n0",), ("n1",), ("n2",), ("n3",))
        assert workset.nodes == ("n0", "n1", "n2", "n3")
        assert workset.depth_of("n2") == 2
        assert workset.depth_of("n4") is None

    def test_within_a_ring_the_order_is_the_logs(self):
        graph = _graph(("seed", "knows", "second", SOURCE),
                       ("seed", "knows", "first", SOURCE),
                       ("first", "knows", "deep", SOURCE))
        workset = hydrate(graph, ["seed"], max_nodes=10, max_edges=10,
                          radius=2)
        assert workset.rings == (("seed",), ("second", "first"), ("deep",))

    def test_several_seeds_are_all_of_ring_zero(self):
        graph = _graph(("a", "knows", "b", SOURCE), ("c", "knows", "d", SOURCE))
        workset = hydrate(graph, ["c", "a"], max_nodes=10, max_edges=10,
                          radius=1)
        assert workset.rings[0] == ("c", "a")
        assert workset.nodes == ("c", "a", "d", "b")

    def test_a_seed_the_graph_never_heard_of_is_named_not_ignored(self):
        graph = _chain(2)
        workset = hydrate(graph, ["n0", "ghost"], max_nodes=10, max_edges=10,
                          radius=1)
        assert workset.missing_seeds == ("ghost",)
        assert workset.seeds == ("n0", "ghost")
        assert "ghost" not in workset.nodes

    def test_radius_zero_is_the_seeds_and_nothing_else(self):
        graph = _chain(3)
        workset = hydrate(graph, ["n0"], max_nodes=10, max_edges=10, radius=0)
        assert workset.nodes == ("n0",)
        assert workset.edges == ()
        assert not workset.truncated, \
            "a walk that stopped where it was told to stop left nothing out"

    def test_the_set_is_the_subgraph_induced_on_its_nodes(self):
        """The edge between two outermost-ring nodes is the one a plain
        ring-by-ring walk misses, and leaving it out would read downstream as
        two nodes that are unrelated. The closing pass is for exactly it."""
        graph = _graph(("seed", "knows", "a", SOURCE),
                       ("seed", "knows", "b", SOURCE),
                       ("a", "knows", "b", SOURCE))
        workset = hydrate(graph, ["seed"], max_nodes=10, max_edges=10,
                          radius=1)
        assert [edge.id for edge in workset.edges] == ["e1", "e2", "e3"]
        assert workset.rings == (("seed",), ("a", "b"))
        assert not workset.truncated

    def test_the_closing_pass_admits_no_nodes(self):
        """A node beyond the radius is outside what was asked for, not
        something the budgets left out."""
        graph = _graph(("seed", "knows", "a", SOURCE),
                       ("a", "knows", "deep", SOURCE))
        workset = hydrate(graph, ["seed"], max_nodes=10, max_edges=10,
                          radius=1)
        assert workset.nodes == ("seed", "a")
        assert [edge.id for edge in workset.edges] == ["e1"]
        assert not workset.truncated

    def test_two_connected_seeds_keep_their_edge_at_radius_zero(self):
        graph = _graph(("a", "knows", "b", SOURCE))
        workset = hydrate(graph, ["a", "b"], max_nodes=9, max_edges=9,
                          radius=0)
        assert [edge.id for edge in workset.edges] == ["e1"]

    def test_the_closing_pass_honours_the_authority_floor(self):
        """The pass runs after the walk and is the last place an edge can
        enter a working set. An arm that compiled at ``SOURCE`` and got a
        model's guess in through the back door would have the floor defeated
        by the feature that makes the set a graph."""
        graph = _graph(("seed", "knows", "a", SOURCE),
                       ("seed", "knows", "b", SOURCE),
                       ("a", "rumour", "b", EXTRACTED))
        loose = hydrate(graph, ["seed"], max_nodes=10, max_edges=10, radius=1)
        assert [edge.id for edge in loose.edges] == ["e1", "e2", "e3"]
        strict = hydrate(graph, ["seed"], max_nodes=10, max_edges=10,
                         radius=1, min_authority=SOURCE)
        assert [edge.id for edge in strict.edges] == ["e1", "e2"]
        assert strict.nodes == ("seed", "a", "b"), \
            "the two ends are still in; only the guess between them is not"
        assert all(edge.authority is not EXTRACTED for edge in strict.edges)

    def test_the_closing_pass_honours_the_relation_filter(self):
        """Same hazard, the other argument: a relation the caller excluded
        cannot re-enter between two outermost-ring nodes."""
        graph = _graph(("seed", "knows", "a", SOURCE),
                       ("seed", "knows", "b", SOURCE),
                       ("a", "billed", "b", SOURCE))
        loose = hydrate(graph, ["seed"], max_nodes=10, max_edges=10, radius=1)
        assert [edge.id for edge in loose.edges] == ["e1", "e2", "e3"]
        filtered = hydrate(graph, ["seed"], max_nodes=10, max_edges=10,
                           radius=1, relations=["knows"])
        assert [edge.id for edge in filtered.edges] == ["e1", "e2"]
        assert filtered.nodes == ("seed", "a", "b")

    def test_the_edges_carry_their_authority(self):
        graph = _company()
        workset = hydrate(graph, ["alice"], max_nodes=10, max_edges=10,
                          radius=2)
        assert {edge.authority for edge in workset.edges} == \
            {SOURCE, DETERMINISTIC, EXTRACTED}


class TestABudgetThatBitSaysSo:
    def test_the_node_budget_is_a_hard_cap(self):
        graph = _chain(6)
        workset = hydrate(graph, ["n0"], max_nodes=3, max_edges=99, radius=6)
        assert len(workset.nodes) == 3
        assert workset.truncated
        assert workset.nodes_omitted >= 1

    def test_the_edge_budget_is_a_hard_cap(self):
        graph = _chain(6)
        workset = hydrate(graph, ["n0"], max_nodes=99, max_edges=2, radius=6)
        assert len(workset.edges) == 2
        assert workset.truncated
        assert workset.edges_omitted >= 1

    def test_the_edge_budget_stops_the_nodes_too(self):
        """A node admitted over an edge that did not fit is a node the set
        cannot say how it reached."""
        graph = _chain(6)
        workset = hydrate(graph, ["n0"], max_nodes=99, max_edges=2, radius=6)
        assert workset.nodes == ("n0", "n1", "n2")
        assert workset.nodes_omitted >= 1

    def test_a_node_past_the_seeds_is_an_end_of_an_edge_in_the_set(self):
        graph = _chain(8)
        for nodes, edges in ((99, 3), (4, 99), (3, 3), (5, 2)):
            workset = hydrate(graph, ["n0"], max_nodes=nodes,
                              max_edges=edges, radius=8)
            ends = {name for edge in workset.edges
                    for name in (edge.src, edge.dst)}
            assert all(name in ends or name in workset.rings[0]
                       for name in workset.nodes)

    def test_more_seeds_than_the_node_budget_is_truncation_at_ring_zero(self):
        graph = _graph(("a", "knows", "b", SOURCE), ("c", "knows", "d", SOURCE))
        workset = hydrate(graph, ["a", "c"], max_nodes=1, max_edges=9,
                          radius=1)
        assert workset.rings[0] == ("a",)
        assert workset.truncated
        assert workset.nodes_omitted == 2, \
            "the seed it could not take, and the neighbour it then could not"

    def test_an_edge_whose_far_end_was_refused_is_an_omitted_edge(self):
        """It did not make it, and which budget stopped it is not the
        caller's problem to reconstruct."""
        graph = _chain(3)
        workset = hydrate(graph, ["n0"], max_nodes=2, max_edges=99, radius=3)
        assert [edge.id for edge in workset.edges] == ["e1"]
        assert workset.edges_omitted == 1
        assert workset.nodes_omitted == 1

    def test_an_untruncated_set_says_so_and_counts_nothing(self):
        graph = _chain(3)
        workset = hydrate(graph, ["n0"], max_nodes=99, max_edges=99, radius=9)
        assert not workset.truncated
        assert (workset.nodes_omitted, workset.edges_omitted) == (0, 0)

    def test_every_edge_in_the_set_has_both_ends_in_the_set(self):
        graph = _chain(8)
        for cap in (1, 2, 3, 5):
            workset = hydrate(graph, ["n0"], max_nodes=cap, max_edges=99,
                              radius=8)
            held = set(workset.nodes)
            assert all(edge.src in held and edge.dst in held
                       for edge in workset.edges)

    def test_a_negative_budget_is_refused(self):
        graph = _chain(2)
        for kwargs in ({"max_nodes": -1}, {"max_edges": -1}, {"radius": -1}):
            args = {"max_nodes": 5, "max_edges": 5, "radius": 1}
            args.update(kwargs)
            with pytest.raises(CognitionError):
                hydrate(graph, ["n0"], **args)

    def test_the_working_set_digest_is_stable_and_json_safe(self):
        graph = _company()
        workset = hydrate(graph, ["alice"], max_nodes=3, max_edges=3,
                          radius=3)
        assert json.loads(workset.digest_json()) == workset.digest()
        again = hydrate(graph, ["alice"], max_nodes=3, max_edges=3, radius=3)
        assert again.digest_json() == workset.digest_json()
        assert workset.digest()["truncated"] is workset.truncated


# ---------------------------------------------------------------------------
# The projection
# ---------------------------------------------------------------------------

class TestTheKernelProjectionIsDerived:
    def test_it_is_the_edges_as_triples(self):
        graph = _company()
        projected = graph.as_propositions()
        assert [item["triple"] for item in projected] == \
            [edge.triple for edge in graph.edges()]
        assert projected[0]["authority"] is SOURCE
        assert projected[0]["evidence"] == (RECEIPT.stamped(SOURCE),)

    def test_editing_what_comes_back_edits_a_copy(self):
        """The mutation this exists for: a projection *stored* would be a
        second owner of every edge, and the day the two disagreed there would
        be no way to say which one was the graph."""
        graph = _company()
        first = graph.as_propositions()
        first[0]["triple"] = ("nonsense", "nonsense", "nonsense")
        first[0]["authority"] = DETERMINISTIC
        second = graph.as_propositions()
        assert second[0]["triple"] == ("alice", "reports_to", "bob")
        assert second[0]["authority"] is SOURCE

    def test_it_projects_whatever_edges_it_is_handed(self):
        graph = _company()
        workset = hydrate(graph, ["alice"], max_nodes=2, max_edges=1,
                          radius=1)
        assert [item["triple"]
                for item in graph.as_propositions(workset.edges)] == \
            [edge.triple for edge in workset.edges]

    def test_it_follows_the_live_revision(self):
        graph = _graph(("alice", "knows", "bob", EXTRACTED))
        graph.add_edge("alice", "knows", "bob", authority=SOURCE,
                       evidence=[RECEIPT])
        assert graph.as_propositions()[0]["authority"] is SOURCE

    def test_node_kinds_are_not_projected(self):
        """Kinds are many-valued here and every field is single-valued there,
        so projecting them would manufacture a contradiction the world never
        had."""
        graph = KnowledgeGraph()
        graph.node_kind("alice", "person", authority=SOURCE,
                        evidence=[RECEIPT])
        graph.node_kind("alice", "employee", authority=SOURCE,
                        evidence=[RECEIPT])
        assert graph.as_propositions() == ()

    def test_a_projected_edge_can_be_asserted_into_the_kernel(self):
        """The seam, exercised end to end — including which door each
        authority goes through, which is the kernel's rule and not this
        package's."""
        from core.cognition import CognitiveState
        from core.cognition.types import OBSERVATION_AUTHORITIES

        graph = _company()
        state = CognitiveState()
        for item in graph.as_propositions():
            door = (state.assert_observation
                    if item["authority"] in OBSERVATION_AUTHORITIES
                    else state.assert_hypothesis)
            door(item["triple"], authority=item["authority"],
                 evidence=item["evidence"])
        held = {prop.triple: prop.status.value
                for prop in state.propositions()}
        assert held[("alice", "reports_to", "bob")] == "observed"
        assert held[("alice", "knows", "carol")] == "hypothesized"


# ---------------------------------------------------------------------------
# Counting
# ---------------------------------------------------------------------------

class TestTheShapeOfTheWholeThing:
    def test_stats_counts_what_is_there(self):
        graph = _company()
        graph.node_kind("alice", "person", authority=SOURCE,
                        evidence=[RECEIPT])
        stats = graph.stats()
        assert tuple(stats) == STATS_KEYS
        assert stats["nodes"] == 5
        assert stats["edges"] == 4
        assert stats["kinds"] == 1
        assert stats["relations"] == {"reports_to": 1, "owns": 2, "knows": 1}

    def test_every_authority_is_in_the_table_including_the_zeros(self):
        stats = _graph(("a", "knows", "b", SOURCE)).stats()
        assert list(stats["edge_authorities"]) == \
            [item.value for item in EvidenceAuthority]
        assert stats["edge_authorities"]["model_hypothesis"] == 0

    def test_a_re_add_does_not_double_count_a_relation(self):
        graph = KnowledgeGraph()
        graph.add_edge("a", "knows", "b", authority=SOURCE, evidence=[RECEIPT])
        graph.add_edge("a", "knows", "b", authority=SOURCE, evidence=[OTHER])
        assert graph.stats()["relations"] == {"knows": 1}
        assert graph.stats()["edges"] == 1

    def test_the_degrees_add_up_to_twice_the_edges(self):
        graph = _company()
        total = sum(graph.node(name).degree for name in graph.nodes())
        assert total == 2 * len(graph.edges())

    def test_the_digest_keys_are_declared(self):
        """Growing the digest changes what "the same graph" means, so it is a
        deliberate act with a constant to update."""
        graph = _company()
        assert tuple(graph.digest()) == DIGEST_KEYS
        assert json.loads(graph.digest_json()) == graph.digest()

    def test_every_row_of_the_digest_is_declared_too(self):
        """The sharper half, and the reason the top-level tuple is not enough:
        a key *dropped* from a row breaks nothing. The comparison simply stops
        looking at the authority, or the evidence, or the revision chain, and
        every replay test goes on passing while the property it was written to
        prove is no longer checked. The row is still there; it is just less of
        an answer than it was."""
        graph = _company()
        graph.node_kind("alice", "person", authority=SOURCE,
                        evidence=[RECEIPT])
        digest = graph.digest()
        assert digest["edges"], "nothing to check"
        assert digest["kinds"], "nothing to check"
        for row in digest["edges"]:
            assert tuple(row) == EDGE_KEYS
        for row in digest["kinds"]:
            assert tuple(row) == KIND_KEYS
        assert "authority" in EDGE_KEYS and "evidence" in EDGE_KEYS
        assert "previous" in EDGE_KEYS and "history" in EDGE_KEYS

    def test_the_row_carries_what_the_trust_boundary_needs(self):
        """Named one by one, because these are the four a comparison would
        stop making without failing: which word the edge is on, what backs it,
        and the chain that says when either of those changed."""
        graph = _graph(("alice", "knows", "bob", EXTRACTED))
        graph.add_edge("alice", "knows", "bob", authority=DETERMINISTIC,
                       evidence=[RECEIPT])
        row = graph.digest()["edges"][0]
        assert row["authority"] == "deterministic"
        assert [ref["authority"] for ref in row["evidence"]] == \
            ["model_extraction", "deterministic"]
        assert row["previous"] == "e1@1"
        assert row["history"] == ["e1@1", "e1@2"]


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

class TestTheAnswerIsAFunctionOfTheLog:
    def test_two_insertion_orders_hold_the_same_edges(self):
        """What is order-*independent* is which relationships are held; what
        is order-dependent is the ids and the order every read returns them
        in. Both are pinned, because both are relied on."""
        forward = _graph(("a", "knows", "b", SOURCE),
                         ("a", "knows", "c", SOURCE))
        backward = _graph(("a", "knows", "c", SOURCE),
                          ("a", "knows", "b", SOURCE))
        assert {edge.triple for edge in forward.edges()} == \
            {edge.triple for edge in backward.edges()}
        assert forward.find("a", "knows", "b").id == "e1"
        assert backward.find("a", "knows", "b").id == "e2"
        assert [edge.dst for edge in forward.neighbors("a")] == ["b", "c"]
        assert [edge.dst for edge in backward.neighbors("a")] == ["c", "b"]

    def test_the_same_log_under_another_hash_seed_is_the_same_graph(self):
        """``PYTHONHASHSEED`` is fixed before this interpreter started, so the
        claim can only be made in subprocesses. Ids, neighbours, a path, the
        stats table and a working set, all compared as text across three
        seeds. A stand-in ``core`` package keeps the run to this package, the
        same way the kernel's own standalone test does.
        """
        script = f"""
import json, sys, types
pkg = types.ModuleType('core')
pkg.__path__ = [{str(REPO / 'core')!r}]
sys.modules['core'] = pkg
from core.cognition.graph import KnowledgeGraph, hydrate
from core.cognition.types import EvidenceAuthority as A, EvidenceRef as R
g = KnowledgeGraph()
r = R(kind='receipt', locator='seq:1')
for i in range(40):
    g.add_edge('n{{}}'.format(i % 7), 'rel{{}}'.format(i % 3),
               'n{{}}'.format((i * 5 + 1) % 11),
               authority=A.SOURCE, evidence=[r])
    g.node_kind('n{{}}'.format(i % 7), 'k{{}}'.format(i % 2),
                authority=A.SOURCE, evidence=[r])
w = hydrate(g, ['n0', 'n3'], max_nodes=6, max_edges=9, radius=3)
path = g.reachable('n0', 'n6', max_depth=4)
print(json.dumps([g.digest(), w.digest(),
                  [e.id for e in path or ()],
                  [e.id for e in g.neighbors('n1')]]))
"""
        answers = []
        for seed in ("0", "1", "12345"):
            result = subprocess.run(
                [sys.executable, "-c", script], capture_output=True,
                text=True, cwd=str(REPO), timeout=120,
                env={"PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin"})
            assert result.returncode == 0, result.stderr
            answers.append(result.stdout)
        assert len(set(answers)) == 1, "the hash seed moved an answer"
        assert json.loads(answers[0])[0]["stats"]["edges"] > 5, \
            "the probe built nothing worth comparing"

    def test_a_working_set_is_a_frozen_record(self):
        graph = _company()
        workset = hydrate(graph, ["alice"], max_nodes=9, max_edges=9,
                          radius=2)
        assert isinstance(workset, WorkingSet)
        with pytest.raises(Exception):
            workset.truncated = True
