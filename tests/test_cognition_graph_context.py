# tests/test_cognition_graph_context.py — the topology beside the store

"""``--graph-context`` on, and the run gains one file and one section.

``tests/test_cognition_graph.py`` owns the graph package — store, walks,
budgets, pure.  ``tests/test_cognition_compile.py`` owns what a handed-over
edge renders as.  This file owns everything **between** them, which is Phase
20a's actual claim (``ROADMAP.md`` §2.9.7):

* **the flag** — off unless somebody asks, and asking for the section asks
  for the block and the state (it implies ``--compiled-context`` and through
  it ``--cognition``, rather than refusing);
* **the harvest** — the edges are the kernel's own links, translated once
  each with the link's own authority and evidence, and nothing else: no
  second reading of receipts, no model proposal, no value coincidence;
* **the log** — ``graph.jsonl`` beside ``reasoning.jsonl``, with a versioned
  header of its own, replaying to the graph the run held, and resuming
  without a byte re-stated;
* **the walk** — seeded from what is owed and from nothing else, bounded at
  :data:`~core.cognition.graph.harvest.HOP_BOUND` hops and the working-set
  caps, with the walk's own truncation rendered as its own sentence;
* **what it costs when it breaks** — the section and a note, never the
  harvest, the view or the mission.

The corpus half is the *negative*: the committed fixtures hold no
``graph.jsonl``, and a run that did not ask for the topology writes none —
the same argument the shadow and compiled-context files each make one flag
earlier.
"""

import json
from pathlib import Path

import pytest

from core.cognition import CognitiveState, EvidenceAuthority, EvidenceRef
from core.cognition.compile import (RELATED, RELATED_CAPPED, RELATED_HEADING,
                                    TITLE)
from core.cognition.graph import (GRAPH_EVENT_SCHEMA_VERSION,
                                  GRAPH_PACKAGE_KEY, GRAPH_PACKAGE_VERSION,
                                  HOP_BOUND, LINK_RELATION, MAX_EDGES,
                                  KnowledgeGraph, LinkHarvest, seeds_from,
                                  working_set)
from core.cognition.graph import GRAPH_SCHEMA_KEY as GRAPH_EVENT_SCHEMA_KEY
from core.cognition.types import ReplayRefused, RuleAuthority
from core.durable import RunStore
from core.runtime.cognition import (GRAPH_LOG, GRAPH_SCHEMA_KEY,
                                    GRAPH_SCHEMA_VERSION, NOTE_KEY,
                                    REASONING_LOG, UNGRAPHED_NOTE,
                                    ShadowCognition, graph_header_record,
                                    open_shadow, read_graph, related_rows,
                                    replay_graph)
from tests.test_cli_mission_skill import elf                       # noqa: F401
from tests.test_cognition_compiled_context import (VIEW, blocks_in, run,
                                                   script)
from tests.test_cognition_shadow import CORPUS, CORPUS_RUNS, lines
from tests.test_cognition_subjects import STATUS, plane


def _shadow(tmp_path, *, goal: bool = False) -> ShadowCognition:
    """A graphing, compiling shadow over a real store, with a link in it.

    :data:`~tests.test_cognition_subjects.STATUS` is the design's own
    motivating receipt — ``job_status`` returning ``data.job_id`` beside a
    figure — so one ``close_step`` leaves one link and therefore one edge.
    *goal* adds a rule and a goal whose premise names the linked subject,
    which is the one way a store is ever owed anything.
    """
    store = RunStore(tmp_path / "store")
    made = open_shadow(store, store.create().run_id, compiling=True,
                       graphing=True)
    made.declare_plane(plane())
    made.receipt("job_status", "r5", STATUS)
    made.close_step()
    if goal:
        made.state.add_rule("done", ("job:jl-731", "done", True),
                            [("job:jl-731", "state", "?v")],
                            authority=RuleAuthority.SKILL)
        made.state.add_goal(("job:jl-731", "done", True))
    return made


def _receipt(name: str) -> EvidenceRef:
    return EvidenceRef(kind="receipt", locator=f"run-1/{name}")


def _about(graph: KnowledgeGraph, src: str, dst: str,
           authority=EvidenceAuthority.SOURCE) -> str:
    return graph.add_edge(src, LINK_RELATION, dst, authority=authority,
                          evidence=(_receipt(src),))


def _owed(*premises) -> CognitiveState:
    """A state owed exactly *premises* — one rule, one goal, no facts."""
    state = CognitiveState()
    state.add_rule("done", ("job:jl-1", "done", True), list(premises),
                   authority=RuleAuthority.SKILL)
    state.add_goal(("job:jl-1", "done", True))
    return state


# ── the flag ─────────────────────────────────────────────────────────────────


def _parsed(*argv):
    from tests.test_contract import _mission_parser

    return _mission_parser().parse_args(["go", *argv])


class TestTheFlagIsOffUntilSomebodyAsks:
    """The ``--compiled-context`` idiom, one flag further on: the
    environment is the argparse default, so the flag wins without a second
    resolution step anywhere."""

    def test_the_default_is_off(self, monkeypatch):
        monkeypatch.delenv("JUDAIS_LOBI_GRAPH_CONTEXT", raising=False)
        assert _parsed().graph_context is False

    def test_the_flag_turns_it_on(self, monkeypatch):
        monkeypatch.delenv("JUDAIS_LOBI_GRAPH_CONTEXT", raising=False)
        assert _parsed("--graph-context").graph_context is True

    def test_the_variable_turns_it_on(self, monkeypatch):
        monkeypatch.setenv("JUDAIS_LOBI_GRAPH_CONTEXT", "1")
        assert _parsed().graph_context is True

    def test_a_blank_variable_is_not_a_request(self, monkeypatch):
        monkeypatch.setenv("JUDAIS_LOBI_GRAPH_CONTEXT", "   ")
        assert _parsed().graph_context is False

    def test_the_help_says_it_implies_the_block(self):
        from tests.test_contract import _mission_parser

        action = [option for option in _mission_parser()._actions
                  if "--graph-context" in option.option_strings][0]
        assert "--compiled-context" in action.help
        assert "IMPLIES" in action.help

    def test_the_flag_is_published(self):
        from core.runtime import contract

        assert "--graph-context" in contract.CLI_FLAGS
        assert "JUDAIS_LOBI_GRAPH_CONTEXT" in contract.ENV_VARS


class TestAskingForTheSectionAsksForTheBlock:
    """One flag typed, three switches on — resolved at the mission door and
    never written back onto what the operator typed."""

    def test_the_flag_alone_opens_the_shadow_and_the_graph(self, elf,
                                                           tmp_path):
        MockClass, agent = elf
        script(agent, VIEW)
        run(MockClass, tmp_path, "--graph-context")
        store = RunStore(tmp_path / "runs")
        directory = store.directory(store.list()[0].run_id)
        assert (directory / REASONING_LOG).exists()
        assert (directory / GRAPH_LOG).exists()

    def test_and_the_block_is_in_the_input(self, elf, tmp_path):
        MockClass, agent = elf
        script(agent, VIEW)
        run(MockClass, tmp_path, "--graph-context")
        assert any(blocks_in(seed) for seed in agent.seeds)


# ── the log ──────────────────────────────────────────────────────────────────


class TestTheTopologyHasItsOwnLog:
    """``graph.jsonl``: its own file, its own header, its own versions.

    Three version numbers because three things change for three reasons —
    this file's shape, the graph's event vocabulary, and the package whose
    counters assigned the edge ids — and none of them is the wire's
    ``schema_version`` or the reasoning log's.
    """

    def test_line_one_states_three_versions_and_nothing_else(self, tmp_path):
        made = _shadow(tmp_path)
        first = json.loads(
            Path(made.graph_path).read_text(encoding="utf-8").splitlines()[0])
        assert first == {GRAPH_SCHEMA_KEY: GRAPH_SCHEMA_VERSION,
                         GRAPH_EVENT_SCHEMA_KEY: GRAPH_EVENT_SCHEMA_VERSION,
                         GRAPH_PACKAGE_KEY: GRAPH_PACKAGE_VERSION}
        assert first == graph_header_record()

    def test_the_header_key_is_nobody_else_s(self):
        """A naked line must say which of the three logs it fell out of."""
        from core.runtime.cognition import SCHEMA_KEY

        assert len({GRAPH_SCHEMA_KEY, SCHEMA_KEY,
                    GRAPH_EVENT_SCHEMA_KEY}) == 3

    def test_an_unversioned_log_is_refused(self, tmp_path):
        target = tmp_path / GRAPH_LOG
        target.write_text('{"op": "add_edge", "n": 1}\n', encoding="utf-8")
        with pytest.raises(ReplayRefused):
            read_graph(target)

    def test_a_log_from_the_future_is_refused(self, tmp_path):
        target = tmp_path / GRAPH_LOG
        target.write_text(json.dumps(
            {GRAPH_SCHEMA_KEY: GRAPH_SCHEMA_VERSION + 1}) + "\n",
            encoding="utf-8")
        with pytest.raises(ReplayRefused):
            read_graph(target)

    def test_a_torn_last_line_is_the_ordinary_state_of_a_killed_run(
            self, tmp_path):
        made = _shadow(tmp_path)
        whole = replay_graph(made.graph_path).digest_json()
        with open(made.graph_path, "a", encoding="utf-8") as handle:
            handle.write('\n{"op": "add_ed')
        assert replay_graph(made.graph_path).digest_json() == whole


class TestTheLogReplaysToTheGraphItWas:
    """Replay-exact, in the graph package's own digest.

    The digest covers edges, kinds, the node index and the stats — the
    cache included, because a replay that rebuilt the edges correctly and
    the adjacency wrongly is exactly the bug the comparison exists to
    catch.
    """

    def test_the_file_replays_to_the_live_graph(self, tmp_path):
        made = _shadow(tmp_path)
        assert replay_graph(made.graph_path).digest_json() == \
            made.graph.digest_json()

    def test_step_boundaries_are_not_in_the_graph(self, tmp_path):
        """Determinism across the one thing the runtime adds: the same
        receipts, split across steps two different ways, are the same
        topology byte for byte."""
        def build(root, steps):
            root.mkdir()
            made = ShadowCognition(root / REASONING_LOG, "run-1",
                                   graphing=True)
            made.declare_plane(plane())
            for step in steps:
                for handle in step:
                    made.receipt("job_status", handle, STATUS)
                made.close_step()
            return made

        one = build(tmp_path / "one", [("r1", "r2")])
        two = build(tmp_path / "two", [("r1",), ("r2",)])
        assert one.graph.stats()["edges"] == 2
        assert one.graph.digest_json() == two.graph.digest_json()
        assert Path(one.graph_path).read_bytes() == \
            Path(two.graph_path).read_bytes()

    def test_a_second_harvest_states_nothing_twice(self, tmp_path):
        """Idempotence in the property that matters, both ways: the same
        instance writes nothing the second time, and a fresh instance
        merges into edges that already carry everything it offers."""
        made = _shadow(tmp_path)
        before = made.graph.digest_json()
        assert LinkHarvest().into(made.state, made.graph) == 1
        assert made.graph.digest_json() == before
        assert made._harvest.into(made.state, made.graph) == 0


class TestResumePicksTheTopologyUpWhereItStopped:
    """The graph log's resume is the reasoning log's: replayed, never
    rebuilt — a rebuild would re-state every edge into the file that
    already holds it."""

    def test_a_second_open_replays_rather_than_restarts(self, tmp_path):
        made = _shadow(tmp_path)
        store = RunStore(tmp_path / "store")
        again = open_shadow(store, store.list()[0].run_id, graphing=True)
        assert again.graph.digest_json() == made.graph.digest_json()

    def test_a_second_open_appends_nothing(self, tmp_path):
        made = _shadow(tmp_path)
        before = Path(made.graph_path).read_bytes()
        store = RunStore(tmp_path / "store")
        again = open_shadow(store, store.list()[0].run_id, graphing=True)
        again.close_step()
        assert Path(made.graph_path).read_bytes() == before

    def test_the_resumed_log_has_no_duplicate_events(self, tmp_path):
        made = _shadow(tmp_path)
        store = RunStore(tmp_path / "store")
        again = open_shadow(store, store.list()[0].run_id, graphing=True)
        again.declare_plane(plane())
        again.receipt("narrative_discovery", "r9",
                      json.dumps({"data": {"job_id": "jl-9"},
                                  "records": 1}))
        again.close_step()
        _header, events, _notes = read_graph(made.graph_path)
        assert [event["n"] for event in events] == \
            list(range(1, len(events) + 1))

    def test_a_run_that_gained_the_flag_resumes_a_store_and_starts_a_graph(
            self, tmp_path):
        """A perfectly ordinary state rather than a case to refuse: the
        reasoning log says the store is resumed, the absent graph log says
        the topology is new — and the new graph holds the replayed store's
        links, not an empty fringe, because the resume seeds the cursor
        AFTER the topology door answered."""
        store = RunStore(tmp_path / "store")
        run_id = store.create().run_id
        first = open_shadow(store, run_id)
        first.declare_plane(plane())
        first.receipt("job_status", "r5", STATUS)
        first.close_step()
        assert not (store.directory(run_id) / GRAPH_LOG).exists()
        again = open_shadow(store, run_id, graphing=True)
        again.close_step()
        assert (store.directory(run_id) / GRAPH_LOG).exists()
        found = replay_graph(store.directory(run_id) / GRAPH_LOG)
        assert found.find("job_status#r5", LINK_RELATION,
                          "job:jl-731") is not None


# ── the harvest ──────────────────────────────────────────────────────────────


class TestTheHarvestIsTheStoresOwnLinks:
    """One source, translated — never a second reading of anything.

    Every edge is one of the kernel's links, with the link's own authority
    and the link's own evidence; the subject's kind is the platform's
    declaration; and the receipt end gets no kind, because nobody declared
    one.
    """

    def test_one_link_is_one_edge_with_the_link_s_own_word(self, tmp_path):
        made = _shadow(tmp_path)
        link, = made.state.links()
        edge = made.graph.find(link.entity, LINK_RELATION, link.subject)
        assert edge is not None
        assert edge.authority is link.authority
        assert {ref.locator for ref in edge.evidence} == \
            {ref.locator for ref in link.evidence}

    def test_the_subject_carries_its_declared_kind(self, tmp_path):
        made = _shadow(tmp_path)
        assert "job" in made.graph.node("job:jl-731").kinds

    def test_the_receipt_end_carries_none(self, tmp_path):
        """Stamping one would be the harvest inventing a statement to make
        the graph look symmetrical."""
        made = _shadow(tmp_path)
        link, = made.state.links()
        assert made.graph.node(link.entity).kinds == ()

    def test_a_store_with_no_links_grows_no_graph(self, tmp_path):
        """No declarations, no links, no edges — the harvest never reads
        receipts on its own."""
        store = RunStore(tmp_path / "store")
        made = open_shadow(store, store.create().run_id, graphing=True)
        made.receipt("job_status", "r5", STATUS)
        made.close_step()
        assert made.graph.stats()["edges"] == 0
        assert made.harvested == 0


# ── the seeds and the walk ───────────────────────────────────────────────────


class TestSeedsComeFromWhatIsOwed:
    """The frontier and nothing else: the graph is hydrated around a
    question, and a run nobody gave one to has nothing to hydrate
    around."""

    def test_the_entity_term_of_an_obligation_is_a_seed(self):
        state = _owed(("job:jl-1", "state", "?v"))
        assert seeds_from(state.ranked_frontier()) == ("job:jl-1",)

    def test_a_subject_spelled_value_term_is_a_seed_too(self):
        state = _owed(("job:jl-1", "input", "asset:a1"))
        assert "asset:a1" in seeds_from(state.ranked_frontier())

    def test_a_bare_literal_value_is_not(self):
        """``"completed"`` is a value two unrelated subjects share — value
        coincidence arriving through the seed list, which is precisely what
        the link discipline refuses one layer down."""
        state = _owed(("job:jl-1", "state", "completed"))
        assert seeds_from(state.ranked_frontier()) == ("job:jl-1",)

    def test_a_variable_is_the_hole_and_not_a_name(self):
        state = _owed(("?e", "state", "?v"))
        assert seeds_from(state.ranked_frontier()) == ()

    def test_duplicates_collapse_to_their_first_appearance(self):
        state = _owed(("job:jl-1", "state", "?v"),
                      ("job:jl-1", "records", "?n"),
                      ("asset:a1", "bytes", "?b"))
        assert seeds_from(state.ranked_frontier()) == ("job:jl-1",
                                                       "asset:a1")


class TestTheWalkIsBoundedAtTheArmSOwnNumbers:
    """:data:`HOP_BOUND` hops and the working-set caps, argued in
    ``harvest.py`` and decided here.

    The topology is bipartite — receipts one side, subjects the other — so
    hop one from an owed subject is the calls that named it and hop two is
    the other subjects those calls also named.  Hop three is where the cost
    stops being bounded by the question.
    """

    @pytest.fixture
    def chain(self) -> KnowledgeGraph:
        """``job:jl-1 ← r1 → asset:a1 ← r2 → asset:a2``: nodes at hops
        one, two and three of the seed."""
        graph = KnowledgeGraph()
        _about(graph, "mcp.a#r1", "job:jl-1")
        _about(graph, "mcp.a#r1", "asset:a1")
        _about(graph, "mcp.b#r2", "asset:a1")
        _about(graph, "mcp.b#r2", "asset:a2")
        return graph

    def test_the_second_ring_is_reached(self, chain):
        """The whole reason a graph is here rather than a list of links:
        the co-subject is the one part of the answer FACTS cannot show."""
        found = working_set(chain, ("job:jl-1",))
        assert "asset:a1" in found.nodes

    def test_the_third_hop_is_not(self, chain):
        """The bound decides: `mcp.b#r2` is three edges out and stays
        outside, and the same walk asked one hop further finds it — so this
        is the constant biting, not the walk failing."""
        found = working_set(chain, ("job:jl-1",))
        assert found.radius == HOP_BOUND
        assert "mcp.b#r2" not in found.nodes
        wider = working_set(chain, ("job:jl-1",), radius=HOP_BOUND + 1)
        assert "mcp.b#r2" in wider.nodes

    def test_the_shipped_bounds_are_the_argued_ones(self):
        """The numbers the module docstring argues, pinned as data — the
        same shape as ``DROP_ORDER``'s test: the one constant an ablation
        is allowed to move must be moved in a commit that says so, not in
        a drive-by.  ``MAX_EDGES`` is also the most RELATED lines a block
        can carry, so this is a prompt-size promise as much as a walk
        bound."""
        from core.cognition.graph import MAX_NODES

        assert (HOP_BOUND, MAX_NODES, MAX_EDGES) == (2, 24, 12)

    def test_the_edge_budget_bites_and_says_so(self):
        graph = KnowledgeGraph()
        for index in range(MAX_EDGES + 1):
            _about(graph, f"mcp.a#r{index}", "job:jl-1")
        found = working_set(graph, ("job:jl-1",))
        assert len(found.edges) == MAX_EDGES
        assert found.truncated

    def test_the_walk_s_cap_is_its_own_sentence_in_the_block(self, tmp_path):
        """Wired through: a working set that hit its own budget renders
        :data:`RELATED_CAPPED` — the graph's cap, not the block's."""
        made = _shadow(tmp_path, goal=True)
        for index in range(MAX_EDGES + 1):
            made.graph.add_edge(f"mcp.audit#x{index}", LINK_RELATION,
                                "job:jl-731",
                                authority=EvidenceAuthority.SOURCE,
                                evidence=(_receipt(f"x{index}"),))
        assert RELATED_CAPPED in made.compiled_block()


# ── the section, through the runtime ─────────────────────────────────────────


class TestTheRelatedSectionThroughTheRuntime:
    """The two packages meet four fields wide, in the runtime that holds
    both — the compiler never imports the graph."""

    def test_an_owed_subject_s_neighbourhood_is_in_the_block(self, tmp_path):
        made = _shadow(tmp_path, goal=True)
        block = made.compiled_block()
        assert RELATED_HEADING in block
        assert f"{RELATED}job_status#r5 —{LINK_RELATION}→ job:jl-731" in block

    def test_no_goals_means_no_section(self, tmp_path):
        """The honest behaviour: nothing is owed, so there is nothing to
        hydrate around — not a gap, and not "recent subjects", which would
        be the runtime deciding what is interesting."""
        made = _shadow(tmp_path)
        block = made.compiled_block()
        assert TITLE in block
        assert RELATED_HEADING not in block

    def test_the_rows_are_the_working_set_s_edges_in_its_order(self,
                                                               tmp_path):
        made = _shadow(tmp_path, goal=True)
        found = working_set(made.graph,
                            seeds_from(made.state.ranked_frontier()))
        rows = related_rows(found)
        assert [(row.src, row.relation, row.dst, row.authority)
                for row in rows] == \
            [(edge.src, edge.relation, edge.dst, edge.authority)
             for edge in found.edges]


# ── the negative ─────────────────────────────────────────────────────────────


class TestGraphOffChangesNothingAtAll:
    """The committed corpus holds no ``graph.jsonl``, and a run that did
    not ask for the topology writes none — with either of the two flags
    below it on."""

    @pytest.mark.parametrize("run_id", CORPUS_RUNS)
    def test_the_committed_fixtures_hold_no_graph_log(self, run_id):
        assert not (CORPUS / run_id / GRAPH_LOG).exists()

    def test_a_compiling_shadow_without_the_flag_writes_none(self, tmp_path):
        store = RunStore(tmp_path / "store")
        made = open_shadow(store, store.create().run_id, compiling=True)
        made.declare_plane(plane())
        made.receipt("job_status", "r5", STATUS)
        made.close_step()
        assert made.compiled_block()
        assert not Path(made.graph_path).exists()
        assert made.graph is None
        assert made.graphing is False

    def test_a_compiled_context_mission_leaves_no_graph_log(self, elf,
                                                            tmp_path):
        MockClass, agent = elf
        script(agent, VIEW)
        run(MockClass, tmp_path, "--compiled-context")
        store = RunStore(tmp_path / "runs")
        directory = store.directory(store.list()[0].run_id)
        assert (directory / REASONING_LOG).exists()
        assert not (directory / GRAPH_LOG).exists()


# ── when it breaks ───────────────────────────────────────────────────────────


class _Boom(Exception):
    pass


def _boom(*_args, **_kwargs):
    raise _Boom("Boom")


class TestAFailingGraphDoesNotMarkTheRun:
    """The constitutional floor, at the newest place it could crack: a
    topology this run cannot keep is not a view it cannot render and is
    certainly not a store it cannot hold."""

    def test_a_failing_harvest_costs_the_graph_and_nothing_else(
            self, tmp_path, monkeypatch):
        made = _shadow(tmp_path)
        monkeypatch.setattr(LinkHarvest, "into", _boom)
        made.receipt("job_status", "r6", STATUS)
        made.close_step()
        assert made.on is True
        assert made.graphing is False
        assert made.graph is None
        assert made.graph_failures == 1
        # The store went on believing: the second receipt landed.
        assert any(prop.entity == "job_status#r6"
                   for prop in made.state.propositions())

    def test_the_log_says_which_part_stopped(self, tmp_path, monkeypatch):
        made = _shadow(tmp_path)
        monkeypatch.setattr(LinkHarvest, "into", _boom)
        made.receipt("job_status", "r6", STATUS)
        made.close_step()
        notes = [line for line in lines(made.path) if NOTE_KEY in line]
        assert [note[NOTE_KEY] for note in notes] == [UNGRAPHED_NOTE]
        assert "Boom" in notes[0]["error"]

    def test_it_stops_for_the_rest_of_the_run(self, tmp_path, monkeypatch):
        """Counted once and off: a graph retried every step would write a
        note a step and spend the failure again and again."""
        made = _shadow(tmp_path)
        monkeypatch.setattr(LinkHarvest, "into", _boom)
        made.receipt("job_status", "r6", STATUS)
        made.close_step()
        monkeypatch.undo()
        made.receipt("job_status", "r7", STATUS)
        made.close_step()
        assert made.graph_failures == 1
        assert made.graph is None
        assert len([line for line in lines(made.path)
                    if line.get(NOTE_KEY) == UNGRAPHED_NOTE]) == 1

    def test_a_failing_walk_costs_the_section_and_the_block_renders(
            self, tmp_path, monkeypatch):
        """The two failures stay separate: a graph that cannot be walked
        costs RELATED, and the block still renders everything else."""
        made = _shadow(tmp_path, goal=True)
        assert RELATED_HEADING in made.compiled_block()
        monkeypatch.setattr("core.runtime.cognition.working_set", _boom)
        block = made.compiled_block()
        assert TITLE in block
        assert RELATED_HEADING not in block
        assert made.on is True
        assert made.compiling is True
        assert made.graphing is False

    def test_the_mission_answers_anyway(self, elf, tmp_path, monkeypatch):
        monkeypatch.setattr(LinkHarvest, "into", _boom)
        MockClass, agent = elf
        script(agent, VIEW)
        run(MockClass, tmp_path, "--graph-context")
        assert agent.seeds
        store = RunStore(tmp_path / "runs")
        listed = store.list()
        assert len(listed) == 1
