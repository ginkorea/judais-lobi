# tests/test_run_swarm.py — the swarm as a client of Run, and the ten deletions

"""What a child run is, and what stopped being written twice.

``tests/test_swarm.py`` stays where it is: it is the staged path's
conformance suite and it tests ``SwarmRunner``, which is still a class with
the same constructor and the same behaviour.  ``tests/test_run_corpus.py``
is the guard that none of that behaviour moved — it replays
``run_corpusswarm-0001`` record for record, and an empty diff is the whole
of this lane's evidence that the wire is unchanged.

This file is the third thing, and it has two halves.

The first is the **shape** the staged path now has: an
:class:`~core.runtime.run.Observer` branch that numbers a child's records
under the parent's one sequence and carries the fields that become true
between two records; a child :class:`~core.runtime.run.Run` that shares its
parent's bounds, store, model and plane **by identity**; one ledger, so the
turn's totals are the roles' plus the sub-missions' and not either alone.

The second is a set of **tripwires**, one per row of ``ROADMAP.md``
§2.6.1's table.  Each reads ``core/runtime/swarm.py`` and asserts that a
name is gone.  That is a weak assertion about code and a strong one about
architecture: every one of those names was a *second emitter* of a fact
that already had an owner, and the swarm shipped six of ``grounding``'s ten
fields the last time one of them drifted.  A name coming back is a second
owner coming back, and the cheapest place to catch it is here.
"""

import inspect
import json
from pathlib import Path

import pytest

from core.budgets import Deadline
from core.contracts.schemas import PolicyPack
from core.durable import RunStore
from core.runtime.backends.base import Usage
from core.runtime.contract import SCHEMA_VERSION
from core.runtime.grounding import GroundingConfig, GroundingValidator
from core.runtime.mission_stream import STEP_STARTED
from core.runtime.run import Observer, Store
from core.tools.bus import ToolBus
from core.tools.capability import CapabilityEngine
from core.tools.descriptors import ToolDescriptor
# One owner of the staged fixtures: the swarm's own suite already has a
# scripted model, a bus with two tools and a `swarm(...)` builder, and a
# second set here would be a second idea of what a staged turn looks like.
from tests.test_swarm import (  # noqa: F401  (bus/calls are fixtures)
    DIRECT, STAGED, ScriptedModel, bus, calls, plan, swarm, tool_call,
)

#: The file the tripwires read.  Read once, as text, on purpose: what is
#: being asserted is that nobody wrote the name again, and importing the
#: module would only tell us it is not exported.
SWARM_SOURCE = Path(
    inspect.getsourcefile(__import__("core.runtime.swarm",
                                     fromlist=["x"]))).read_text(
    encoding="utf-8")


class _Watching:
    """A supervisor that never has anything to say.

    Duck-typed, as :class:`~core.runtime.run.Bounds` documents: what a run
    needs of one is ``look``, ``saw_call`` and ``saw_rejection``.  What is
    asserted about it here is only that every stage of the turn was handed
    the **same object** — five supervisors for one turn would be five
    review budgets, and a plan that loops across its steps is precisely
    the pattern no single sub-mission can see.
    """

    def look(self, objective, ledger=None):
        return None

    def saw_call(self, *args, **kwargs):
        pass

    def saw_rejection(self, *args, **kwargs):
        pass


def records(observer_calls, event):
    return [record for record in observer_calls if record["event"] == event]


# ── a branch numbers a child under the parent's sequence ────────────────────


class TestABranchNumbersAChildUnderTheParent:
    """``index`` is the run's, and a child counts its own steps from zero.

    Five sub-missions each open at ``index: 0``.  What a watcher must read
    is one mission with more steps, so the allocation happens at emit time
    and against a counter the parent holds — which is what
    ``_StageObserver`` did by hand, in the swarm, for one caller.
    """

    def observer(self, seen):
        return Observer(seen.append)

    def test_a_stages_indexes_continue_the_turns_own(self):
        seen = []
        parent = self.observer(seen)
        first = parent.branch("s1", stage=True)
        first.emit(STEP_STARTED, index=0)
        first.emit(STEP_STARTED, index=1)
        second = parent.branch("s2", stage=True)
        second.emit(STEP_STARTED, index=0)
        second.emit(STEP_STARTED, index=1)
        assert [record["index"] for record in seen] == [0, 1, 2, 3]

    def test_a_resumed_stretch_numbers_from_where_the_log_stopped(self):
        """Those records go into the log an earlier stretch wrote, and a
        numbering that started again would put two records with the same
        ``index`` in one run."""
        seen = []
        parent = self.observer(seen)
        stage = parent.branch("s2", stage=True, start_index=4)
        stage.emit(STEP_STARTED, index=0)
        stage.emit(STEP_STARTED, index=1)
        assert [record["index"] for record in seen] == [4, 5]

    def test_a_record_with_no_index_is_passed_through_untouched(self):
        seen = []
        stage = self.observer(seen).branch("s1", stage=True)
        stage.emit("tool_call", index=0, tool="catalog.search", arguments={})
        stage.emit("gate_requested", approval_id="a-1", tool="x",
                   arguments={})
        assert seen[1] == {"event": "gate_requested", "approval_id": "a-1",
                           "tool": "x", "arguments": {}}

    def test_the_branch_name_still_does_not_reach_the_wire(self):
        """An OPTIONAL ``branch`` field is the parallel-children lane's.
        A record carrying one now would be a contract change in the lane
        whose whole claim is that it makes none."""
        seen = []
        self.observer(seen).branch("s1", stage=True).emit(
            STEP_STARTED, index=0)
        assert seen == [{"event": "step_started", "index": 0}]


# ── what a branch drops, and what it does not ───────────────────────────────


class TestWhatAChildContributesToTheStream:
    """Two kinds of child, and the difference is a whole record type.

    ``_OpenedAlready`` and ``_StageObserver`` were two classes because a
    sub-runner was handed a *callback* and the two filters were the two
    shapes of that call.  They are one object with one flag now, and the
    flag is the honest distinction: is this child the mission continued,
    or one stage of it?
    """

    def events(self, **branch):
        seen = []
        child = Observer(seen.append).branch("c", **branch)
        for event in ("mission_started", "step_started", "tool_call",
                      "tool_result", "reply_rejected", "gate_requested",
                      "answer_delta", "grounding", "answer",
                      "mission_finished"):
            child.emit(event, index=0)
        return [record["event"] for record in seen]

    def test_a_stage_contributes_the_work_and_none_of_the_bookkeeping(self):
        assert self.events(stage=True) == [
            "step_started", "tool_call", "tool_result", "reply_rejected",
            "gate_requested"]

    def test_the_mission_continued_loses_only_its_opening(self):
        """The direct route is a whole agent answering the whole question:
        its ``answer`` and its ``mission_finished`` are the turn's, and the
        only thing the parent already said is ``mission_started``."""
        assert self.events() == [
            "step_started", "tool_call", "tool_result", "reply_rejected",
            "gate_requested", "answer_delta", "grounding", "answer",
            "mission_finished"]


# ── the fields that become true between two records ─────────────────────────


class TestTheCarriedFieldsRideTheNextStep:
    """``plan``, ``resumed`` and ``review`` wait on the PARENT.

    Each becomes true between records — a plan is drawn before the first
    sub-mission exists, a review of a failed gate happens after one ended
    and before the next begins — so the child that will carry it may not
    have been made yet.  ``_StageObserver`` got away with holding them
    because it was one object for the whole turn; a branch per child
    cannot, and the parent is where they belong anyway.
    """

    def test_they_ride_the_next_step_started_of_the_next_child(self):
        seen = []
        parent = Observer(seen.append)
        parent.carry(plan=[{"id": "s1"}], resumed={"from_seq": 4})
        stage = parent.branch("s1", stage=True)
        stage.emit(STEP_STARTED, index=0)
        assert seen[0] == {"event": "step_started", "index": 0,
                           "plan": [{"id": "s1"}], "resumed": {"from_seq": 4}}

    def test_they_drain_and_do_not_arrive_again(self):
        """A field that arrived on every step would be a state restated
        rather than an event announced."""
        seen = []
        parent = Observer(seen.append)
        parent.carry(plan=[{"id": "s1"}])
        stage = parent.branch("s1", stage=True)
        stage.emit(STEP_STARTED, index=0)
        stage.emit(STEP_STARTED, index=1)
        assert "plan" not in seen[1]

    def test_a_review_carried_between_stages_reaches_the_next_one(self):
        seen = []
        parent = Observer(seen.append)
        first = parent.branch("s1", stage=True)
        first.emit(STEP_STARTED, index=0)
        parent.carry(review={"verdict": "nudge"})
        second = parent.branch("s1", stage=True)
        second.emit(STEP_STARTED, index=0)
        assert "review" not in seen[0]
        assert seen[1] == {"event": "step_started", "index": 1,
                           "review": {"verdict": "nudge"}}

    def test_a_redrawn_plan_replaces_the_one_it_abandoned(self):
        seen = []
        parent = Observer(seen.append)
        parent.carry(plan=[{"id": "s1"}])
        parent.carry(plan=[{"id": "s9"}])
        parent.branch("s9", stage=True).emit(STEP_STARTED, index=0)
        assert seen[0]["plan"] == [{"id": "s9"}]

    def test_nothing_carried_is_a_record_with_nothing_added(self):
        seen = []
        Observer(seen.append).branch("s1", stage=True).emit(
            STEP_STARTED, index=0)
        assert seen[0] == {"event": "step_started", "index": 0}


# ── a branch is a caller of the parent, not a filter beside it ──────────────


class TestABranchEmitsThroughTheParent:
    """One scrub, one append, one stream — whichever child spoke.

    The property that matters is that there is no path from a child to a
    sink that does not pass through :meth:`Observer.emit`, which is where
    the redactor runs and where the durable log is written.  A staged path
    that handed its sub-missions the sink directly would put a step's
    output on a pane and not in its log.
    """

    def test_a_childs_record_is_redacted_by_the_parents_choke_point(
            self, monkeypatch):
        monkeypatch.setenv("HOME", "/home/testuser")
        seen = []
        Observer(seen.append).branch("s1", stage=True).emit(
            "reply_rejected", index=0,
            problem="failed at /home/testuser/secrets.txt")
        assert "/home/testuser" not in seen[0]["problem"]
        assert seen[0]["problem"] == "failed at <home>/secrets.txt"

    def test_a_childs_record_reaches_the_durable_log_once(self, tmp_path):
        runs = RunStore(tmp_path / "runs")
        run_id = runs.create().run_id
        parent = Observer(store=Store(runs=runs, run_id=run_id))
        parent.branch("s1", stage=True).emit(STEP_STARTED, index=0)
        assert [r["event"] for r in runs.records(run_id)] == ["step_started"]

    def test_a_branch_of_a_silent_observer_is_silent(self):
        """Zero sinks and no run store is the case that matters most: a
        turn nobody is watching must run exactly as it ran before either
        existed."""
        Observer().branch("s1", stage=True).emit(STEP_STARTED, index=0)


# ── a child run is the parent's collaborators, by identity ──────────────────


class TestTheSwarmsChildrenShareTheTurn:
    """One clock, one supervisor, one log, one ledger, one plane.

    Stated on the objects a real staged turn builds rather than on a
    hand-made ``Run``: ``tests/test_run.py`` already asserts what
    :meth:`Run.child` shares, and what is asserted here is that the swarm
    is *using* it — which is the whole of lane B.
    """

    @pytest.fixture
    def turn(self, bus):
        plain = ScriptedModel(
            STAGED,
            plan({"id": "s1", "goal": "search", "rung": "tool"},
                 {"id": "s2", "goal": "read", "rung": "tool"}),
            "corpus.abc123 is what both hold")
        executor = ScriptedModel(
            tool_call("catalog.search", q="a"), '{"answer": "a"}',
            tool_call("catalog.search", q="b"), '{"answer": "b"}')
        # A validator and a critic, so that "a stage is held to no
        # grammar of its own" is a claim about the child and not about a
        # turn that had none to hand down.
        validator = GroundingValidator.from_config(
            GroundingConfig.from_mapping({"identifier_pattern":
                                          r"corpus\.[a-z0-9]+"}))
        return swarm(plain, executor, bus, deadline=Deadline(60.0),
                     supervisor=_Watching(), validator=validator,
                     critic=object())

    def children(self, runner, objective="what do the two runs hold?"):
        made = []
        original = runner._run.child

        def watched(**kwargs):
            child = original(**kwargs)
            made.append(child)
            return child

        runner._run.child = watched
        runner.run(objective)
        return made

    def test_every_stage_is_a_child_of_the_one_run(self, turn):
        made = self.children(turn)
        assert len(made) == 2
        assert all(child.store is turn._run.store for child in made)
        assert all(child.model is turn._run.model for child in made)
        assert all(child.plane is turn._run.plane for child in made)

    def test_one_clock_and_one_supervisor_for_the_whole_turn(self, turn):
        """Shared by identity through the bounds a child is handed: five
        sub-missions of a minute each must not fit inside a one-minute
        budget, and a plan that loops ACROSS its steps is precisely the
        pattern no single sub-mission can see."""
        made = self.children(turn)
        parent = turn._run.bounds
        assert all(child.bounds.deadline is parent.deadline for child in made)
        assert all(child.bounds.supervisor is parent.supervisor
                   for child in made)

    def test_a_stage_counts_its_elapsed_time_from_the_turns_triage(
            self, turn):
        made = self.children(turn)
        assert all(child.bounds.started_at == turn._started_at
                   for child in made)

    def test_a_stage_is_held_to_no_grammar_of_its_own(self, turn):
        """The validator and the critic belong to the SYNTHESIZER: a
        step's summary is not an answer to the objective, so holding it to
        the objective's grammar would fail it for not being one."""
        made = self.children(turn)
        assert turn._run.personality.grounding is not None
        assert turn._run.personality.critic is not None
        assert all(child.personality.grounding is None for child in made)
        assert all(child.personality.critic is None for child in made)
        assert all(child.personality.history == [] for child in made)

    def test_the_persona_leads_every_stage(self, turn):
        """Every sub-mission of every staged turn opens with the same
        bytes the direct path opens with — which is what a served
        endpoint's prefix cache is keyed on."""
        made = self.children(turn)
        assert all(child.personality.system_message.startswith("You are Tai.")
                   for child in made)

    def test_a_stage_has_its_own_result_store(self, turn):
        """Handles are a run's own: ``r1`` in step two must not address
        step one's first result."""
        made = self.children(turn)
        assert made[0].results is not made[1].results
        assert made[0].results is not turn._run.results


class TestTheDirectRouteIsTheTurnContinued:
    def test_it_is_a_child_with_nothing_overridden_but_the_branch(self, bus):
        made = []
        runner = swarm(ScriptedModel(DIRECT),
                       ScriptedModel('{"answer": "ok"}'), bus)
        original = runner._run.child

        def watched(**kwargs):
            made.append(kwargs)
            return original(**kwargs)

        runner._run.child = watched
        runner.run("q")
        assert len(made) == 1
        assert "personality" not in made[0]
        assert made[0]["branch"] and not made[0].get("stage")


# ── one ledger, and it is the model's ───────────────────────────────────────


class FlatMeter:
    """The same provider report after every call, whoever made it."""

    def __init__(self):
        self.reads = 0

    def __call__(self):
        self.reads += 1
        return Usage(prompt_tokens=10, completion_tokens=2, total_tokens=12)


class TestOneLedgerForTheWholeTurn:
    """The roles' calls and the sub-missions' fold into the same object.

    Not because they are added up afterwards: there is one
    :class:`~core.runtime.run.Model`, every child shares it by identity,
    and :meth:`Model.spend` is the one place
    :meth:`~core.runtime.usage.Ledger.add` is called.  The swarm's four
    roles used to do that arithmetic themselves, in four lines that were
    the loop's four lines written a second time.
    """

    def turn(self, bus, meter):
        plain = ScriptedModel(
            STAGED,
            plan({"id": "s1", "goal": "search", "rung": "tool"},
                 {"id": "s2", "goal": "read", "rung": "tool"}),
            "corpus.abc123 is what both hold")
        executor = ScriptedModel(
            tool_call("catalog.search", q="a"), '{"answer": "a"}',
            tool_call("catalog.search", q="b"), '{"answer": "b"}')
        runner = swarm(plain, executor, bus, usage_fn=meter)
        seen = []
        runner._observer.sinks = (seen.append,)
        return runner, runner.run("q"), seen, plain, executor

    def test_the_totals_are_the_roles_plus_the_sub_missions(self, bus):
        meter = FlatMeter()
        runner, transcript, seen, plain, executor = self.turn(bus, meter)
        calls = plain.calls + executor.calls
        assert calls > 2
        assert transcript.usage.calls == calls
        assert transcript.usage.total == 12 * calls

    def test_the_ledger_is_the_models_and_the_transcripts_at_once(self, bus):
        meter = FlatMeter()
        runner, transcript, _seen, _p, _e = self.turn(bus, meter)
        assert transcript.usage is runner._run.model.ledger

    def test_the_finished_record_carries_those_totals(self, bus):
        meter = FlatMeter()
        runner, transcript, seen, _p, _e = self.turn(bus, meter)
        finished = records(seen, "mission_finished")[0]
        assert finished["usage"]["calls"] == transcript.usage.calls
        assert finished["usage"]["total_tokens"] == transcript.usage.total

    def test_a_second_turn_does_not_report_the_firsts_tokens(self, bus):
        meter = FlatMeter()
        runner, first, _seen, _p, _e = self.turn(bus, meter)
        second = runner.run("q")
        assert second.usage.calls < first.usage.calls + second.usage.calls
        assert second.usage is not first.usage


# ── the ten deletions ───────────────────────────────────────────────────────


#: ``ROADMAP.md`` §2.6.1's table, as the tripwire reads it: the fact, the
#: name that was deleted from ``core/runtime/swarm.py``, and the owner it
#: went to.  The owner is here to be read by a person: what a test can
#: check is the absence, and what a person needs beside it is where the
#: fact went instead.
DELETED = [
    ("mission_finished", "def _finish_early",
     "core.runtime.mission._finished_record, from run's one finally"),
    ("mission_started", "def _opening",
     "core.runtime.run.Run.opening"),
    ("the grounding loop", "def _ground",
     "Run._ground / _repairing_turn / _caveated / _verdict"),
    ("the ledger fold", "def _spent",
     "core.runtime.run.Model.spend"),
    ("the ledger fold, again", "def _usage_kw",
     "core.runtime.usage.Ledger.as_record"),
    ("the ledger fold, a third time", "def _totals",
     "core.runtime.usage.Ledger.as_record"),
    ("the deadline start", "self._deadline.start()",
     "core.runtime.run.Bounds.begin"),
    ("the stop verdict", "def _stop",
     "core.runtime.run.Bounds.stop"),
    ("the stop verdict, written down", "def _stopped",
     "core.runtime.run.Run._stopped"),
    ("the catalogue", "def _offered",
     "ToolPlane.offered, through Run.offered"),
    ("emit", "def _emit",
     "core.runtime.run.Observer.emit"),
    ("emit, and whether anyone is listening", "def _recording",
     "core.runtime.run.Observer.emit's first line"),
    ("a child's records", "class _StageObserver",
     "core.runtime.run.Observer.branch"),
    ("a child's opening", "class _OpenedAlready",
     "core.runtime.run.Observer.branch"),
    ("how a sub-mission is built", "def _runner",
     "core.runtime.run.Run.child"),
    ("bounding a summary", "def _bound_summary",
     "core.bounding.bound_result"),
]


class TestTheSecondEmittersAreGone:
    """One test per row of ``ROADMAP.md`` §2.6.1's table.

    A grep is a weak assertion about code and a strong one about
    architecture.  Every name below was a second emitter of a fact that
    already had an owner somewhere else, and the last time one of them
    drifted the swarm shipped a ``grounding`` record carrying six of the
    ten fields the contract requires — for weeks, silently, on a record a
    consumer switches on.  What this catches is somebody adding one back,
    which is a thing that happens under deadline and reads, in a diff,
    like four harmless lines.
    """

    @pytest.mark.parametrize(
        "fact,name,owner", DELETED,
        ids=[name.replace(" ", "_") for _fact, name, _owner in DELETED])
    def test_the_name_is_not_in_the_swarm(self, fact, name, owner):
        assert name not in SWARM_SOURCE, (
            f"{name!r} is back in core/runtime/swarm.py. {fact} has one "
            f"owner and it is {owner}.")

    def test_the_swarm_emits_exactly_three_kinds_of_record_itself(self):
        """Everything else a staged turn puts on the wire comes out of a
        child.  These three are the turn's own: it opens before triage
        because triage is a model call, it writes the synthesized answer,
        and it closes.  ``grounding`` is NOT among them any more — the
        synthesizer's verdict goes out through ``Run._verdict``.
        """
        emitted = {line.split("emit(")[1].split(",")[0].strip()
                   for line in SWARM_SOURCE.splitlines()
                   if "._observer.emit(" in line}
        assert emitted == {"MISSION_STARTED", "MISSION_FINISHED", "ANSWER"}

    def test_mission_finished_is_emitted_from_one_place(self):
        assert SWARM_SOURCE.count("MISSION_FINISHED") == 2  # import + emit

    def test_the_swarm_holds_no_second_copy_of_the_six(self):
        """The ceiling, the clock, the gated set, the window and the
        protocol are read off the ``Run`` that owns them.  A field here
        would be a copy that a child could disagree with.
        """
        for copy in ("self._max_steps =", "self._deadline =", "self._gated =",
                     "self._window =", "self._protocol =", "self._bus =",
                     "self._tool_names =", "self._validator =",
                     "self._supervisor =", "self._history ="):
            assert copy not in SWARM_SOURCE, copy


# ── the opening is the loop's own builder ───────────────────────────────────


class TestTheOpeningComesOutOfOneBuilder:
    """The staged path emits ``mission_started`` before triage — because
    triage is itself a call to the model — and the record is the loop's.

    ``tests/test_swarm.py`` already asserts that the two routes' openings
    are indistinguishable.  What is asserted here is *why* they cannot
    differ: there is one function, and the swarm calls it.
    """

    def test_the_swarm_calls_the_runs_own_builder(self, bus):
        runner = swarm(ScriptedModel(DIRECT),
                       ScriptedModel('{"answer": "ok"}'), bus,
                       gated=["run_code"])
        opening = runner._run.opening("q")
        assert opening == {
            "schema_version": SCHEMA_VERSION,
            "objective": "q",
            "catalogue": ["catalog.search", "run_code", "mission_result"],
            "gated": ["run_code"],
            "max_steps": 0,
            "history": 0,
            # Off the plane's own properties and not restated here: the
            # bus is the one owner of both, and a test that hard-coded
            # them would be a second reading of the same two facts.
            "sandbox": runner._run.plane.sandbox,
            "audit_ref": runner._run.plane.audit_ref,
        }

    def test_the_record_on_the_wire_is_that_dict(self, bus):
        seen = []
        runner = swarm(ScriptedModel(DIRECT),
                       ScriptedModel('{"answer": "ok"}'), bus,
                       observer=seen.append)
        expected = dict(runner._run.opening("q"))
        runner.run("q")
        opened = records(seen, "mission_started")[0]
        assert {k: v for k, v in opened.items() if k != "event"} == expected


# ── one plane for the turn ──────────────────────────────────────────────────


class TestOnePlaneForTheWholeTurn:
    """A tool the bus grows mid-turn is offered to every later stage.

    Each sub-mission used to build its own plane from the manifest's list,
    so a tool that arrived during step one was offered to step one and to
    no later step — two views of what may be called, which is the thing a
    closed set exists to be one of.
    """

    def _growing_bus(self):
        b = ToolBus(capability_engine=CapabilityEngine(
            PolicyPack(allowed_scopes=["*"])))
        b.register(ToolDescriptor(tool_name="catalog.search",
                                  description="Search. Second sentence."),
                   lambda **kw: (0, "corpus.abc123", ""))

        def grow(**_kw):
            b.register(ToolDescriptor(tool_name="mcp.late",
                                      description="Late. Second sentence."),
                       lambda **kw: (0, "late corpus.abc123", ""))
            return (0, "registered mcp.late", "")

        b.register(ToolDescriptor(tool_name="run_code",
                                  description="Run code. Second sentence."),
                   grow)
        return b

    def test_what_one_stage_learned_the_next_may_call(self):
        b = self._growing_bus()
        plain = ScriptedModel(
            STAGED,
            plan({"id": "s1", "goal": "grow the plane", "rung": "code"},
                 {"id": "s2", "goal": "use it", "rung": "tool"}),
            "corpus.abc123")
        executor = ScriptedModel(
            tool_call("run_code", code="c"), '{"answer": "grew"}',
            tool_call("mcp.late"), '{"answer": "used it"}')
        runner = swarm(plain, executor, b, admits=lambda grew, offered: grew)
        runner.run("grow then use")
        # The second stage called it and was not told there is no such tool.
        assert "mcp.late" in runner._run.plane.offered
        assert "no tool named" not in json.dumps(executor.seen)
