# tests/test_cognition_graph_replay.py — the log is the graph, and the package stands alone

"""Three claims the graph makes that reading its answers cannot check.

**That the event log is the graph.**  Adjacency, degrees, revisions and the
relation table are a cache of the log; the log is the record.  So the strong
form is asserted here: seeded pseudo-random sequences of both mutating calls,
snapshotted, replayed into a fresh graph, and the two compared whole — the
digest, and a working set, because a working set is what the graph *says* and
it is computed rather than stored.

**That replay is exact rather than best-effort, and counted.**  An unknown op
is refused, an unversioned snapshot is refused, a kernel snapshot handed here
by mistake is refused — and so is a log whose ``n`` values are not exactly
``1..len``.  That last one is this package's own addition and the reason is
its ids: they come from insertion order, so a log with a line missing rebuilds
a graph whose ``e7`` is a *different edge* under the same name, silently, and
a JSONL file with a truncated last line is the ordinary way that happens.

**That the package stands alone and holds no state of its own.**  No I/O, no
clock, no randomness, no import of :mod:`core.runtime` — asserted against the
source, because the ablation arms depend on being able to construct this or
not and change nothing else in the process.  Two graphs in one process are two
graphs.
"""

import ast
import json
import random
import re
import subprocess
import sys
from pathlib import Path

import pytest

from core.cognition.events import EVENT_SCHEMA_VERSION
from core.cognition.events import SCHEMA_KEY as KERNEL_SCHEMA_KEY
from core.cognition.graph import (EVENTS_KEY, GRAPH_EVENT_OPS,
                                  GRAPH_EVENT_SCHEMA_VERSION,
                                  GRAPH_PACKAGE_VERSION, PACKAGE_KEY,
                                  SCHEMA_KEY, KnowledgeGraph, hydrate)
from core.cognition.types import EvidenceAuthority, EvidenceRef, ReplayRefused

PACKAGE = (Path(__file__).resolve().parent.parent / "core" / "cognition"
           / "graph")
MODULES = ["__init__", "events", "store", "hydrate"]

RECEIPT = EvidenceRef(kind="receipt", locator="seq:1")
OTHER = EvidenceRef(kind="receipt", locator="seq:2")
GUESS = EvidenceRef(kind="extraction", locator="turn:1")


def _imported(name):
    """Every ``module`` and ``module.symbol`` one of our modules imports.

    Read with :mod:`ast` rather than by regex over the text: these files argue
    for themselves at length and every constraint asserted against their
    source would otherwise be asserted against their prose.
    """
    tree = ast.parse((PACKAGE / f"{name}.py").read_text(encoding="utf-8"))
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            out.add(module)
            out.update(f"{module}.{alias.name}" for alias in node.names)
    return out


# ---------------------------------------------------------------------------
# The log
# ---------------------------------------------------------------------------

class TestEveryWriteIsOneEvent:
    def test_each_mutating_call_appends_exactly_one(self):
        graph = KnowledgeGraph()
        counts = []
        graph.add_edge("alice", "knows", "bob",
                       authority=EvidenceAuthority.SOURCE, evidence=[RECEIPT])
        counts.append(len(graph.events))
        graph.add_edge("alice", "knows", "bob",
                       authority=EvidenceAuthority.DETERMINISTIC,
                       evidence=[OTHER])
        counts.append(len(graph.events))
        graph.node_kind("alice", "person",
                        authority=EvidenceAuthority.MODEL_EXTRACTION,
                        evidence=[GUESS])
        counts.append(len(graph.events))
        assert counts == [1, 2, 3]
        assert [event["n"] for event in graph.events] == [1, 2, 3]

    def test_the_ops_are_append_only(self):
        """The compatibility rule as an assertion rather than a paragraph: an
        op is never renamed or removed, so a log this package could read once
        it can read always. New ones go on the end and raise the schema."""
        assert GRAPH_EVENT_OPS[:2] == ("add_edge", "node_kind")

    def test_the_ops_are_the_published_set(self):
        graph = KnowledgeGraph()
        graph.add_edge("alice", "knows", "bob",
                       authority=EvidenceAuthority.SOURCE, evidence=[RECEIPT])
        graph.node_kind("alice", "person", authority=EvidenceAuthority.SOURCE,
                        evidence=[RECEIPT])
        assert {event["op"] for event in graph.events} == set(GRAPH_EVENT_OPS)

    def test_a_refused_call_writes_nothing(self):
        """A log with a refusal in it would replay into a graph that accepted
        it, which is the one way an unevidenced edge could get in."""
        graph = KnowledgeGraph()
        with pytest.raises(Exception):
            graph.add_edge("alice", "knows", "bob",
                           authority=EvidenceAuthority.SOURCE, evidence=[])
        with pytest.raises(Exception):
            graph.add_edge("", "knows", "bob",
                           authority=EvidenceAuthority.SOURCE,
                           evidence=[RECEIPT])
        with pytest.raises(Exception):
            graph.node_kind("alice", "", authority=EvidenceAuthority.SOURCE,
                            evidence=[RECEIPT])
        assert graph.events == ()

    def test_reading_does_not_grow_the_log(self):
        """Unlike the kernel's, no read here writes at all: there is no
        staging area, so the log is a fact about who wrote and never about
        who looked."""
        graph = _script(1)
        settled = len(graph.events)
        for _ in range(3):
            graph.digest()
            graph.stats()
            graph.neighbors(graph.nodes()[0])
            hydrate(graph, [graph.nodes()[0]], max_nodes=5, max_edges=5,
                    radius=2)
        assert len(graph.events) == settled

    def test_no_id_is_written_into_the_log(self):
        """Ids come from insertion order, so writing one down would be a
        second owner of the same fact — and the two would disagree the first
        time a log was edited by hand."""
        graph = _script(2)
        for event in graph.events:
            flat = json.dumps(event)
            assert not re.search(r'"(e|k)\d+"', flat), flat

    def test_the_snapshot_states_both_of_its_versions(self):
        """The event schema says whether a reader can parse this; the package
        version says whether the graph it rebuilds means what the writer
        meant. Neither answers the other's question."""
        graph = KnowledgeGraph()
        graph.add_edge("alice", "knows", "bob",
                       authority=EvidenceAuthority.SOURCE, evidence=[RECEIPT])
        snapshot = graph.snapshot()
        assert snapshot[SCHEMA_KEY] == GRAPH_EVENT_SCHEMA_VERSION
        assert snapshot[PACKAGE_KEY] == GRAPH_PACKAGE_VERSION
        assert SCHEMA_KEY != PACKAGE_KEY
        assert [event["op"] for event in snapshot[EVENTS_KEY]] == ["add_edge"]

    def test_that_version_is_this_packages_own_number(self):
        """Three numbers — the wire contract's, the kernel's and this one —
        because three things change for three reasons. Asserted as
        *independence*: the constant is assigned here, not derived from
        either of the others, so they can move apart without knowing."""
        source = (PACKAGE / "events.py").read_text(encoding="utf-8")
        assigned = re.search(r"^GRAPH_EVENT_SCHEMA_VERSION\s*=\s*(\d+)\s*$",
                             source, re.MULTILINE)
        assert assigned, "the graph event schema version is not a literal here"
        assert int(assigned.group(1)) == GRAPH_EVENT_SCHEMA_VERSION
        assert SCHEMA_KEY != KERNEL_SCHEMA_KEY
        assert "core.cognition.events.EVENT_SCHEMA_VERSION" \
            not in _imported("events"), "this version is the kernel's"
        assert EVENT_SCHEMA_VERSION == 1  # today they agree; they need not

    def test_the_events_a_reader_gets_are_copies(self):
        graph = KnowledgeGraph()
        graph.add_edge("alice", "knows", "bob",
                       authority=EvidenceAuthority.SOURCE, evidence=[RECEIPT])
        graph.events[0]["op"] = "nonsense"
        assert graph.events[0]["op"] == "add_edge"


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------

def _script(seed, steps=60):
    """A seeded pseudo-random sequence of writes against one graph.

    Deliberately not a curated example: the divergences worth finding in a
    replay are combinations — an edge extracted, re-extracted, then confirmed
    by a reference while a third edge closes a cycle behind it — and nobody
    writes those down in advance.
    """
    rng = random.Random(seed)
    graph = KnowledgeGraph()
    nodes = ["alice", "bob", "carol", "acct-1", "acct-9", "org"]
    relations = ["knows", "reports_to", "owns", "member_of"]
    authorities = list(EvidenceAuthority)
    kinds = ["person", "account", "org"]
    for _ in range(steps):
        if rng.randrange(6):
            graph.add_edge(rng.choice(nodes), rng.choice(relations),
                           rng.choice(nodes),
                           authority=rng.choice(authorities),
                           evidence=[rng.choice([RECEIPT, OTHER, GUESS])])
        else:
            graph.node_kind(rng.choice(nodes), rng.choice(kinds),
                            authority=rng.choice(authorities),
                            evidence=[rng.choice([RECEIPT, GUESS])])
    return graph


class TestAGraphIsExactlyItsLog:
    @pytest.mark.parametrize("seed", range(12))
    def test_replay_reconstructs_the_whole_graph(self, seed):
        graph = _script(seed)
        again = KnowledgeGraph.replay(graph.snapshot())
        assert again.digest_json() == graph.digest_json()

    @pytest.mark.parametrize("seed", range(12))
    def test_replay_reconstructs_the_working_set(self, seed):
        """The digest is the graph; a working set is what the graph *says*,
        and it is computed rather than stored. Equal digests would not catch a
        walk that had become order-dependent on something the digest does not
        carry."""
        graph = _script(seed)
        again = KnowledgeGraph.replay(graph.snapshot())
        seeds = list(graph.nodes())[:2]
        one = hydrate(graph, seeds, max_nodes=5, max_edges=7, radius=3)
        two = hydrate(again, seeds, max_nodes=5, max_edges=7, radius=3)
        assert two.digest_json() == one.digest_json()
        assert [edge.id for edge in
                (again.reachable("alice", "org", max_depth=4) or ())] == \
            [edge.id for edge in
             (graph.reachable("alice", "org", max_depth=4) or ())]

    @pytest.mark.parametrize("seed", range(6))
    def test_the_script_is_worth_replaying(self, seed):
        """A property test over an empty graph proves nothing. This pins that
        the generator reaches revisions, several relations and both doors of
        the trust boundary."""
        digest = _script(seed).digest()
        assert any(edge["revision"] > 1 for edge in digest["edges"]), \
            "no edge was ever re-stated"
        assert len(digest["stats"]["relations"]) > 2
        table = digest["stats"]["edge_authorities"]
        assert table["source"] or table["deterministic"]
        assert table["model_extraction"] or table["model_hypothesis"]

    def test_a_bare_event_list_is_refused(self):
        """The convenience of taking one is aimed at the reader holding lines
        off a disk — precisely the reader most in need of the version, handed
        the one shape that has none. The kernel settled this rule; this
        package follows it rather than re-opening the bypass beside it."""
        graph = _script(1)
        with pytest.raises(ReplayRefused):
            KnowledgeGraph.replay(list(graph.events))
        wrapped = {SCHEMA_KEY: GRAPH_EVENT_SCHEMA_VERSION,
                   EVENTS_KEY: list(graph.events)}
        assert KnowledgeGraph.replay(wrapped).digest_json() == \
            graph.digest_json()

    def test_replaying_a_replay_is_the_same_graph(self):
        graph = _script(2)
        once = KnowledgeGraph.replay(graph.snapshot())
        twice = KnowledgeGraph.replay(once.snapshot())
        assert twice.digest_json() == graph.digest_json()
        assert [event["op"] for event in twice.events] == \
               [event["op"] for event in graph.events]

    def test_the_log_is_json_safe(self):
        graph = _script(3)
        round_tripped = json.loads(json.dumps(graph.snapshot()))
        again = KnowledgeGraph.replay(round_tripped)
        assert again.digest_json() == graph.digest_json()

    def test_an_unknown_op_is_refused_not_skipped(self):
        """The mutation this exists for: a replay that skipped what it did not
        recognise would build a plausible topology out of a log it did not
        understand, and nothing downstream could tell."""
        graph = _script(4)
        snapshot = graph.snapshot()
        snapshot[EVENTS_KEY].insert(2, {"op": "connect_harder"})
        for index, event in enumerate(snapshot[EVENTS_KEY]):
            event["n"] = index + 1
        with pytest.raises(ReplayRefused, match="connect_harder"):
            KnowledgeGraph.replay(snapshot)

    def test_an_unversioned_snapshot_is_refused(self):
        snapshot = _script(5).snapshot()
        del snapshot[SCHEMA_KEY]
        with pytest.raises(ReplayRefused):
            KnowledgeGraph.replay(snapshot)

    def test_a_newer_schema_is_refused(self):
        snapshot = _script(6).snapshot()
        snapshot[SCHEMA_KEY] = GRAPH_EVENT_SCHEMA_VERSION + 1
        with pytest.raises(ReplayRefused):
            KnowledgeGraph.replay(snapshot)

    def test_a_newer_package_writing_only_ops_we_know_still_replays(self):
        """What append-only ops buy. The package version is diagnosis, not a
        gate: refusing a log whose every op this package handles would make
        every semantic revision a break for readers that did not need one."""
        graph = _script(6)
        snapshot = graph.snapshot()
        snapshot[PACKAGE_KEY] = GRAPH_PACKAGE_VERSION + 3
        again = KnowledgeGraph.replay(snapshot)
        assert again.digest_json() == graph.digest_json()

    def test_the_refusal_names_the_package_that_wrote_the_log(self):
        """When a newer package *does* carry an op we do not have, the message
        says which version wrote it rather than leaving somebody to guess."""
        snapshot = _script(7).snapshot()
        snapshot[PACKAGE_KEY] = 9
        snapshot[EVENTS_KEY].append({"n": len(snapshot[EVENTS_KEY]) + 1,
                                     "op": "merge_nodes"})
        with pytest.raises(ReplayRefused, match="9"):
            KnowledgeGraph.replay(snapshot)

    def test_a_package_version_that_is_not_a_version_is_refused(self):
        snapshot = _script(8).snapshot()
        snapshot[PACKAGE_KEY] = "one"
        with pytest.raises(ReplayRefused):
            KnowledgeGraph.replay(snapshot)

    def test_a_snapshot_without_a_package_version_still_replays(self):
        """A hand-written log, or one from before this key existed. The event
        schema is the required one, because it is the one that says whether
        the parse is even possible."""
        graph = _script(9)
        snapshot = graph.snapshot()
        del snapshot[PACKAGE_KEY]
        assert KnowledgeGraph.replay(snapshot).digest_json() == \
            graph.digest_json()

    def test_a_kernel_snapshot_is_refused_by_its_key(self):
        """Two logs of plain dicts under one repository; the version key is
        what tells them apart, and a kernel log walked here would otherwise
        land as "no ops I know" rather than as the mistake it is."""
        from core.cognition import CognitiveState

        state = CognitiveState()
        state.assert_observation(("alice", "role", "admin"),
                                 evidence=[RECEIPT])
        with pytest.raises(ReplayRefused):
            KnowledgeGraph.replay(state.snapshot())

    def test_an_authority_this_package_has_no_name_for_is_refused(self):
        graph = KnowledgeGraph()
        graph.add_edge("alice", "knows", "bob",
                       authority=EvidenceAuthority.SOURCE, evidence=[RECEIPT])
        snapshot = graph.snapshot()
        snapshot[EVENTS_KEY][0]["authority"] = "vibes"
        with pytest.raises(ReplayRefused):
            KnowledgeGraph.replay(snapshot)


class TestTheSequenceIsCounted:
    """Ids come from insertion order, so a log that lost a line rebuilds a
    graph whose ``e7`` is a different edge under the same name. A truncated
    JSONL file is the ordinary way that happens, and it is why the count is
    checked here and not left as decoration."""

    def test_a_missing_line_is_refused(self):
        graph = _script(7)
        snapshot = graph.snapshot()
        del snapshot[EVENTS_KEY][3]
        with pytest.raises(ReplayRefused):
            KnowledgeGraph.replay(snapshot)

    def test_a_truncated_log_is_accepted_as_a_shorter_one(self):
        """Losing the *tail* is not the dangerous case: every id that remains
        still means what it meant. The graph is smaller and says nothing false
        about what it holds."""
        graph = _script(8)
        snapshot = graph.snapshot()
        snapshot[EVENTS_KEY] = snapshot[EVENTS_KEY][:10]
        shorter = KnowledgeGraph.replay(snapshot)
        assert len(shorter.events) == 10

    def test_a_reordered_log_is_refused(self):
        graph = _script(9)
        snapshot = graph.snapshot()
        events = snapshot[EVENTS_KEY]
        events[2], events[5] = events[5], events[2]
        with pytest.raises(ReplayRefused):
            KnowledgeGraph.replay(snapshot)

    def test_a_log_numbered_from_zero_is_refused(self):
        graph = _script(10)
        snapshot = graph.snapshot()
        for event in snapshot[EVENTS_KEY]:
            event["n"] -= 1
        with pytest.raises(ReplayRefused):
            KnowledgeGraph.replay(snapshot)

    def test_an_unnumbered_event_is_refused(self):
        graph = _script(11)
        snapshot = graph.snapshot()
        del snapshot[EVENTS_KEY][2]["n"]
        with pytest.raises(ReplayRefused):
            KnowledgeGraph.replay(snapshot)

    def test_a_duplicated_line_is_refused(self):
        """A duplicate leaves every event well-formed and would replay into a
        graph that merely looks busier than the one that was written."""
        graph = _script(12)
        snapshot = graph.snapshot()
        snapshot[EVENTS_KEY].insert(4, dict(snapshot[EVENTS_KEY][4]))
        with pytest.raises(ReplayRefused):
            KnowledgeGraph.replay(snapshot)


# ---------------------------------------------------------------------------
# The standing constraints
# ---------------------------------------------------------------------------

class TestThePackageStandsAlone:
    """The shadow-attachment lane depends on this package; this package
    depends on nothing of ours but the kernel's vocabulary."""

    @pytest.mark.parametrize("name", MODULES)
    def test_no_module_imports_the_runtime(self, name):
        source = (PACKAGE / f"{name}.py").read_text(encoding="utf-8")
        code = "\n".join(line for line in source.splitlines()
                         if not line.lstrip().startswith("#"))
        assert not re.search(r"^\s*(from|import)\s+core\.runtime", code,
                             re.MULTILINE), f"{name}.py reaches into the runtime"

    @pytest.mark.parametrize("name", MODULES)
    def test_no_io_and_no_clock(self, name):
        """Deterministic and replayable is a property of the whole package,
        not of the tests that happen to avoid these. ``json`` is allowed — it
        is a codec and not a file."""
        source = (PACKAGE / f"{name}.py").read_text(encoding="utf-8")
        code = "\n".join(line for line in source.splitlines()
                         if not line.lstrip().startswith("#"))
        for banned in (r"^\s*import\s+(os|time|random|socket|pathlib)\b",
                       r"^\s*from\s+(os|time|random|socket|pathlib|datetime)\b",
                       r"\bopen\(", r"\bdatetime\.", r"\btime\.time\("):
            assert not re.search(banned, code, re.MULTILINE), \
                f"{name}.py has {banned}"

    @pytest.mark.parametrize("name", MODULES)
    def test_no_module_level_mutable_state(self, name):
        """The ablation hook is the whole API surface: one constructor and
        calls on what it returns. A module-level list or dict is the thing
        that would make two arms in one process share something, and it is the
        kind of state that arrives as a cache somebody added in a hurry."""
        source = (PACKAGE / f"{name}.py").read_text(encoding="utf-8")
        offenders = [line for line in source.splitlines()
                     if re.match(r"^(?!__)[A-Za-z_][A-Za-z0-9_]*"
                                 r"(\s*:[^=]+)?\s*=\s*[\[{]", line)]
        assert offenders == [], offenders

    def test_two_graphs_in_one_process_are_two_graphs(self):
        one, two = KnowledgeGraph(), KnowledgeGraph()
        one.add_edge("alice", "knows", "bob",
                     authority=EvidenceAuthority.SOURCE, evidence=[RECEIPT])
        assert two.nodes() == ()
        assert two.events == ()
        assert two.stats()["edges"] == 0

    def test_the_package_imports_with_nothing_else_loaded(self):
        """The claim under its own steam, in a fresh interpreter.

        ``core/__init__.py`` imports the agent, which imports most of the
        repository, so plain ``import core.cognition.graph`` would prove
        nothing. A stand-in ``core`` package pointing at the same directory
        skips that file and leaves the question this test is for: with nothing
        else of ours loaded, does the graph come up?
        """
        root = PACKAGE.parent.parent
        script = (
            "import sys, types\n"
            "pkg = types.ModuleType('core')\n"
            f"pkg.__path__ = [{str(root)!r}]\n"
            "sys.modules['core'] = pkg\n"
            "import core.cognition.graph as g\n"
            "assert g.KnowledgeGraph().snapshot()['graph_event_schema']\n"
            "print(sorted(m for m in sys.modules if m.startswith('core.')))\n"
        )
        result = subprocess.run([sys.executable, "-c", script],
                                capture_output=True, text=True,
                                cwd=str(root.parent), timeout=60)
        assert result.returncode == 0, result.stderr
        loaded = result.stdout.strip()
        assert "core.runtime" not in loaded, loaded
        assert "core.tools" not in loaded, loaded
        assert "core.cognition.graph.store" in loaded, loaded

    def test_the_graph_never_writes_to_a_kernel(self):
        """Shadow and additive: the projection is offered, never applied. If
        this package could reach a ``CognitiveState`` it would have a way to
        change what a run believes, and the rule is that it has none."""
        for name in MODULES:
            imported = _imported(name)
            assert "core.cognition.state" not in imported, name
            assert not any(item.endswith("CognitiveState")
                           for item in imported), name
            tree = ast.parse(
                (PACKAGE / f"{name}.py").read_text(encoding="utf-8"))
            called = {node.func.attr for node in ast.walk(tree)
                      if isinstance(node, ast.Call)
                      and isinstance(node.func, ast.Attribute)}
            assert not called & {"assert_observation", "assert_hypothesis",
                                 "apply_delta", "refute"}, name
