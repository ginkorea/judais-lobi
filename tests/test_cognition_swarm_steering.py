# tests/test_cognition_swarm_steering.py — the planner is told, and decides

"""``--swarm-steering`` on, and the planner is *offered* the frontier.

``tests/test_cognition_kernel.py`` owns the partition itself — what joins
two obligations, and that a link is what says two names are one thing.  This
file owns everything above it: the rendering, the shadow's read, the one
``append`` into a planning prompt, and the flag.  It is
``tests/test_cognition_compiled_context.py``'s argument one reader further
on, and the constitutional half is the larger half, because Phase 20b is the
first thing in this package that speaks to a **planner**:

* **advisory means advisory** — there is no path from the hint to a refused
  plan, a forced child, a reordered step or a supervisor signal.  The plan
  validator is handed a plan that ignores every word of the hint and
  accepts it, which is the assertion that would go red the day somebody
  "helpfully" made the hint binding;
* **flag off is byte-identical** — and the comparison is of the whole
  planning request, not of a substring: a run with ``--cognition`` on and
  this off asks the planner the same bytes as a run with neither;
* **replaced, never accumulated** — a redraw builds a fresh prompt, so the
  planner reads one frontier and not a log of them.  This is the 19b bug
  shape and it is cheap to reintroduce;
* **what it costs when it breaks** — nothing.  A partition that raises
  stops the hint for the run, writes one note, and the turn plans the
  prompt it would have planned with the flag off;
* **bounded, and the overflow is named** — four groups, three owed lines
  each, both said out loud, and a frontier walk that was itself cut short
  says the stronger thing: the *independence* is what the cap put in doubt.

The renderer lives here rather than in ``tests/test_cognition_compile.py``
on purpose: :func:`~core.cognition.compile.steering_hint` is not a section
of the compiled view and never rides in a mission step — it is this arm's
own block, and its owner is this arm.
"""

import json

import pytest

from core.cognition import (CognitiveState, EvidenceRef, RuleAuthority,
                            owed_line)
from core.cognition.compile import (STEERING_CAPPED, STEERING_GROUP,
                                    STEERING_MORE, STEERING_OVERFLOW,
                                    STEERING_SENTENCE, STEERING_TITLE,
                                    steering_hint)
from core.runtime import contract as c
from core.runtime.cognition import (NOTE_KEY, REASONING_LOG, STEERING_NOTE,
                                    UNSTEERED_NOTE, ShadowCognition)
from tests.test_cli_mission_skill import elf  # noqa: F401
from tests.test_cognition_shadow import lines
from tests.test_swarm import DIRECT, STAGED, ScriptedModel, bus, calls  # noqa: F401
from tests.test_swarm import plan, swarm, tool_call

RECEIPT = EvidenceRef(kind="receipt", locator="run-1/r1/mcp.jobs")


def two_groups():
    """A store owing two things that share no subject.

    Two goals about two jobs: the smallest frontier a planner can be told
    anything useful about, and the shape every wiring test below wants.
    """
    state = CognitiveState()
    state.add_goal(("job:one", "state", "?s"))
    state.add_goal(("job:two", "state", "?s"))
    return state


def one_group():
    state = CognitiveState()
    state.add_goal(("job:one", "state", "?s"))
    state.add_goal(("job:one", "owner", "?o"))
    return state


def shadow_for(tmp_path, state, **kw):
    kw.setdefault("steering", True)
    return ShadowCognition(tmp_path / REASONING_LOG, "run-1", state=state,
                           **kw)


# ── the rendering ────────────────────────────────────────────────────────────


class TestOneGroupIsNotAHint:
    """A frontier that is all one problem has nothing independent in it, and
    rendering it here would be the second emitter of the OWED section that
    ``--compiled-context`` already owns."""

    def test_no_groups_is_nothing(self):
        assert steering_hint(()) == ""

    def test_one_group_is_nothing(self):
        assert steering_hint(one_group().independent_frontier()) == ""

    def test_two_groups_is_a_hint(self):
        assert STEERING_TITLE in steering_hint(
            two_groups().independent_frontier())


class TestTheHintQuotesTheOneOwedSpelling:
    @pytest.fixture
    def rendered(self):
        return steering_hint(two_groups().independent_frontier())

    def test_every_owed_line_is_owed_lines(self, rendered):
        owed = [item for group in two_groups().independent_frontier()
                for item in group]
        for item in owed:
            assert owed_line(item) in rendered

    def test_the_groups_are_numbered_from_one(self, rendered):
        assert STEERING_GROUP.format(number=1) in rendered
        assert STEERING_GROUP.format(number=2) in rendered

    def test_it_states_a_fact_rather_than_giving_an_order(self, rendered):
        """The constitutional half of the *rendering*. The hint says what is
        true of the partition; it never tells the planner what to write, and
        a sentence in the imperative would be the cognitive layer planning
        rather than reporting (the owner's ruling of 13 September 2026)."""
        assert STEERING_SENTENCE in rendered
        body = rendered.lower()
        for order in ("you must", "you should", "write one step",
                      "plan a step", "create a child", "do not"):
            assert order not in body, f"the hint gives an order: {order!r}"


class TestTheHintIsBoundedAndSaysWhatItCut:
    def _many(self, count):
        state = CognitiveState()
        for index in range(count):
            state.add_goal((f"job:{index}", "state", "?s"))
        return state.independent_frontier()

    def test_only_the_first_groups_are_shown(self):
        rendered = steering_hint(self._many(9), max_groups=4)
        assert STEERING_GROUP.format(number=4) in rendered
        assert STEERING_GROUP.format(number=5) not in rendered

    def test_and_the_rest_are_named(self):
        rendered = steering_hint(self._many(9), max_groups=4)
        assert STEERING_OVERFLOW.format(count=5) in rendered

    def test_a_group_shows_only_so_many_owed_lines(self):
        state = CognitiveState()
        for field in ("state", "owner", "size", "region"):
            state.add_goal(("job:one", field, "?v"))
        state.add_goal(("job:two", "state", "?s"))
        groups = state.independent_frontier()
        rendered = steering_hint(groups, max_lines=3)
        assert STEERING_MORE.format(count=1) in rendered

    def test_nothing_is_cut_when_nothing_overflows(self):
        rendered = steering_hint(two_groups().independent_frontier())
        assert STEERING_OVERFLOW.format(count=0) not in rendered
        assert "more owed in this group" not in rendered

    def test_a_capped_walk_says_the_independence_is_in_doubt(self):
        """Stronger than the OWED section's own truncation line, and
        deliberately: an obligation the walk never reached could have been
        the one that joined two of the groups shown."""
        state = CognitiveState()
        state.add_rule("wide", ("?a", "wide", "?c"),
                       [("?a", "seen", "?b"), ("?b", "needs", "?c")],
                       RuleAuthority.DOMAIN)
        for index in range(300):
            state.assert_observation(("alice", "seen", f"n{index}"),
                                     evidence=[RECEIPT])
        state.add_goal(("alice", "wide", "acct-9"))
        state.add_goal(("job:two", "state", "?s"))
        groups = state.independent_frontier()
        assert len(groups) > 1, "this fixture must partition"
        assert STEERING_CAPPED in steering_hint(groups)

    def test_an_uncapped_walk_does_not(self):
        assert STEERING_CAPPED not in steering_hint(
            two_groups().independent_frontier())


# ── the shadow's read ────────────────────────────────────────────────────────


class TestTheShadowOffersNothingUnlessAsked:
    def test_the_default_is_off(self, tmp_path):
        assert shadow_for(tmp_path, two_groups(),
                          steering=False).planning_hint() == ""

    def test_asked_for_it_offers(self, tmp_path):
        assert STEERING_TITLE in shadow_for(
            tmp_path, two_groups()).planning_hint()

    def test_one_group_offers_nothing(self, tmp_path):
        assert shadow_for(tmp_path, one_group()).planning_hint() == ""

    def test_an_empty_store_offers_nothing(self, tmp_path):
        assert shadow_for(tmp_path, CognitiveState()).planning_hint() == ""

    def test_a_stopped_shadow_offers_nothing(self, tmp_path):
        shadow = shadow_for(tmp_path, two_groups())
        shadow.on = False
        assert shadow.planning_hint() == ""


class TestTheLogSaysThePlannerWasOffered:
    def test_one_note_per_offer(self, tmp_path):
        shadow = shadow_for(tmp_path, two_groups())
        shadow.planning_hint()
        shadow.planning_hint()
        notes = [line for line in lines(shadow.path) if NOTE_KEY in line]
        assert [note[NOTE_KEY] for note in notes] == [STEERING_NOTE] * 2
        assert shadow.steers == 2

    def test_the_note_counts_what_was_found_and_what_was_shown(self, tmp_path):
        """Two numbers and not one: the cap makes them different, and a
        reader asking what the planner was actually told needs both."""
        state = CognitiveState()
        for index in range(9):
            state.add_goal((f"job:{index}", "state", "?s"))
        shadow = shadow_for(tmp_path, state)
        shadow.planning_hint()
        note, = [line for line in lines(shadow.path) if NOTE_KEY in line]
        assert note["groups"] == 9
        assert note["shown"] == 4

    def test_nothing_is_written_when_nothing_is_offered(self, tmp_path):
        shadow = shadow_for(tmp_path, one_group())
        shadow.planning_hint()
        assert [line for line in lines(shadow.path) if NOTE_KEY in line] == []
        assert shadow.steers == 0

    def test_the_hint_is_not_a_kernel_event(self, tmp_path):
        """A statement *about* the store, not part of it — so a replay of
        this log rebuilds the store this run held and nothing else."""
        shadow = shadow_for(tmp_path, two_groups())
        before = len(shadow.state.events)
        shadow.planning_hint()
        shadow.planning_hint()
        assert len(shadow.state.events) == before


class _Boom(Exception):
    pass


def _boom(*_args, **_kwargs):
    raise _Boom("Boom")


class TestAPartitionThatRaisesCostsTheHintAndNothingElse:
    """The narrowest failure in the package, one step past the progress
    signal's: what stops is one optional paragraph offered to one kind of
    turn, at one moment in it."""

    @pytest.fixture
    def stopped(self, tmp_path, monkeypatch):
        shadow = shadow_for(tmp_path, two_groups())
        monkeypatch.setattr(type(shadow.state), "independent_frontier", _boom)
        assert shadow.planning_hint() == ""
        return shadow

    def test_the_switch_goes_and_nothing_else_does(self, stopped):
        assert stopped.steer_failures == 1
        assert stopped.steering is False
        assert stopped.on is True

    def test_the_store_goes_on_believing(self, stopped, monkeypatch):
        monkeypatch.undo()
        stopped.receipt("mcp.jobs", "r1", json.dumps({"runtime_s": 4}))
        stopped.close_step()
        assert stopped.state.propositions()

    def test_it_stops_for_the_rest_of_the_run(self, stopped, monkeypatch):
        monkeypatch.undo()
        assert stopped.planning_hint() == ""

    def test_the_log_says_which_half_stopped(self, stopped):
        notes = [line for line in lines(stopped.path) if NOTE_KEY in line]
        assert [note[NOTE_KEY] for note in notes] == [UNSTEERED_NOTE]
        assert "Boom" in notes[0]["error"]

    def test_the_progress_signal_is_untouched(self, stopped, monkeypatch):
        monkeypatch.undo()
        assert stopped.progress() is not None


# ── the planner ──────────────────────────────────────────────────────────────


def planning_turn(model):
    """The user content of the FIRST planning request *model* was shown.

    The planner's request is the second one a staged turn makes — the router
    asks first — and it is the only one this arm can change.
    """
    return model.seen[1][-1]["content"]


def staged(plain_replies, executor_replies, bus, **kw):
    """One staged turn, run to its answer.

    Returns ``(the planner's model, the transcript)``: the first is what the
    assertions about the *prompt* read, the second is what the assertions
    about the turn having actually worked read.
    """
    plain = ScriptedModel(*plain_replies)
    runner = swarm(plain, ScriptedModel(*executor_replies), bus, **kw)
    return plain, runner.run("Two jobs need looking at")


ONE_STEP = plan({"id": "s1", "goal": "look at job one", "rung": "tool",
                 "needs": [], "done": "a state"})
STEP_RESULT = json.dumps({"answer": "job one is running"})
GATE_OK = json.dumps({"pass": True})
FINAL = "both jobs were looked at"
#: A one-step plan answers with its step's own answer — there is no second
#: result for a synthesizer to compose — so this is what the turn returns.
ANSWERED = "job one is running"
SCRIPT = (STAGED, ONE_STEP, GATE_OK, FINAL)
WORK = (tool_call("catalog.search", q="one"), STEP_RESULT)


class TestThePlannerIsToldWhatIsIndependent:
    def test_the_hint_is_in_the_planning_turn(self, tmp_path, bus):
        shadow = shadow_for(tmp_path, two_groups())
        plain, _ = staged(SCRIPT, WORK, bus, cognition=shadow)
        assert STEERING_TITLE in planning_turn(plain)

    def test_it_rides_last(self, tmp_path, bus):
        """State and not instruction, so it displaces nobody's last word —
        and rc4 measured that the reference 20B binds what it reads last."""
        shadow = shadow_for(tmp_path, two_groups())
        plain, _ = staged(SCRIPT, WORK, bus, cognition=shadow)
        content = planning_turn(plain)
        assert content.index(STEERING_TITLE) > content.index(
            "Two jobs need looking at")
        assert content.rstrip().endswith(
            steering_hint(two_groups().independent_frontier()).rstrip())

    def test_the_system_turn_is_untouched(self, tmp_path, bus):
        """The cached prefix — persona, the planner's instruction, the
        catalogue — does not move for this."""
        shadow = shadow_for(tmp_path, two_groups())
        with_hint, _ = staged(SCRIPT, WORK, bus, cognition=shadow)
        without, _ = staged(SCRIPT, WORK, bus)
        assert with_hint.seen[1][0] == without.seen[1][0]


class TestWithNothingToOfferThePromptIsTheSameBytes:
    """The floor: a run that is not offered a hint asks the question it
    would have asked with the flag off, byte for byte."""

    def _asked(self, bus, **kw):
        return planning_turn(staged(SCRIPT, WORK, bus, **kw)[0])

    def test_cognition_on_and_steering_off_is_the_flagless_prompt(
            self, tmp_path, bus):
        shadow = shadow_for(tmp_path, two_groups(), steering=False)
        assert self._asked(bus, cognition=shadow) == self._asked(bus)

    def test_a_one_group_frontier_is_the_flagless_prompt(self, tmp_path, bus):
        shadow = shadow_for(tmp_path, one_group())
        assert self._asked(bus, cognition=shadow) == self._asked(bus)

    def test_an_empty_store_is_the_flagless_prompt(self, tmp_path, bus):
        shadow = shadow_for(tmp_path, CognitiveState())
        assert self._asked(bus, cognition=shadow) == self._asked(bus)

    def test_a_direct_route_never_plans_at_all(self, tmp_path, bus):
        """A turn the router sent DIRECT has no planning request to change,
        which is most turns."""
        shadow = shadow_for(tmp_path, two_groups())
        plain = ScriptedModel(DIRECT)
        runner = swarm(plain, ScriptedModel(FINAL), bus, cognition=shadow)
        runner.run("one small question")
        assert all(STEERING_TITLE not in json.dumps(seen)
                   for seen in plain.seen)
        assert shadow.steers == 0


class TestTheHintIsReplacedAndNeverAccumulated:
    def test_a_redraw_carries_exactly_one(self, tmp_path, bus):
        """A planning round builds its prompt fresh, so a second round
        reads one frontier rather than a log of them — the accumulating
        block is the defect ``--compiled-context`` was built around."""
        shadow = shadow_for(tmp_path, two_groups())
        bad = plan({"id": "s1", "goal": "look", "rung": "nonsense",
                    "needs": [], "done": "x"})
        plain = ScriptedModel(STAGED, bad, ONE_STEP, GATE_OK, FINAL)
        runner = swarm(plain, ScriptedModel(
            tool_call("catalog.search", q="one"), STEP_RESULT), bus,
            cognition=shadow)
        runner.run("Two jobs need looking at")
        retry = plain.seen[2]
        assert json.dumps(retry).count(STEERING_TITLE) == 1


class TestAdvisoryMeansAdvisory:
    """No path from the hint to a refused plan, a forced child, or a
    supervisor signal.  The whole constitutional claim of the phase."""

    def test_a_plan_that_ignores_every_group_is_accepted(self, tmp_path, bus):
        """One step for a two-group frontier: accepted, run, answered."""
        shadow = shadow_for(tmp_path, two_groups())
        _plain, transcript = staged(SCRIPT, WORK, bus, cognition=shadow)
        assert transcript.answer == ANSWERED
        assert transcript.outcome == "answered"

    def test_the_plan_validator_has_never_heard_of_a_group(self, tmp_path,
                                                           bus):
        shadow = shadow_for(tmp_path, two_groups())
        runner = swarm(ScriptedModel(), ScriptedModel(), bus,
                       cognition=shadow)
        steps, problem = runner._read_plan(json.loads(ONE_STEP))
        assert problem == ""
        assert [step.id for step in steps] == ["s1"]

    def test_the_supervisor_is_told_nothing(self, tmp_path, bus):
        """The hint is read between the router and the planner and reaches
        no reviewer: a turn with a scripted supervisor spends no review on
        it."""
        from core.runtime.supervisor import Supervisor

        reviews = ScriptedModel()
        shadow = shadow_for(tmp_path, two_groups())
        plain = ScriptedModel(STAGED, ONE_STEP, GATE_OK, FINAL)
        runner = swarm(plain, ScriptedModel(
            tool_call("catalog.search", q="one"), STEP_RESULT), bus,
            cognition=shadow, supervisor=Supervisor(reviews))
        runner.run("Two jobs need looking at")
        assert reviews.calls == 0


class TestAShadowThatCannotBeAskedCostsTheTurnNothing:
    """Duck-typed on purpose: the runner holds the fact that there is a
    shadow and not its type, so a stand-in without the method and a
    stand-in whose method raises are the same event — a turn that plans
    without a hint."""

    class _Older:
        """A shadow written against the methods that existed before 20b."""

        def receipt(self, *_a, **_kw):
            pass

        def close_step(self):
            pass

        def compiled_block(self):
            return ""

        def progress(self):
            return None

    class _Angry(_Older):
        def planning_hint(self):
            raise _Boom("Boom")

    @pytest.mark.parametrize("stand_in", [_Older, _Angry, lambda: None])
    def test_the_turn_plans_and_answers(self, bus, stand_in):
        plain, transcript = staged(SCRIPT, WORK, bus, cognition=stand_in())
        assert STEERING_TITLE not in planning_turn(plain)
        assert transcript.answer == ANSWERED


# ── the flag ─────────────────────────────────────────────────────────────────


def _parsed(*argv):
    from tests.test_contract import _mission_parser

    return _mission_parser().parse_args(["go", *argv])


class TestTheFlagIsOffUntilSomebodyAsks:
    """The second switch in this package that changes a prompt, held to the
    first one's rules: off unless somebody asks, and the environment is the
    flag's argparse default so that "the flag wins" needs no second
    resolution step anywhere."""

    def test_the_default_is_off(self, monkeypatch):
        monkeypatch.delenv("JUDAIS_LOBI_SWARM_STEERING", raising=False)
        assert _parsed().swarm_steering is False

    def test_the_flag_turns_it_on(self, monkeypatch):
        monkeypatch.delenv("JUDAIS_LOBI_SWARM_STEERING", raising=False)
        assert _parsed("--swarm-steering").swarm_steering is True

    def test_the_variable_turns_it_on(self, monkeypatch):
        monkeypatch.setenv("JUDAIS_LOBI_SWARM_STEERING", "1")
        assert _parsed().swarm_steering is True

    def test_a_blank_variable_is_not_a_request(self, monkeypatch):
        monkeypatch.setenv("JUDAIS_LOBI_SWARM_STEERING", "   ")
        assert _parsed().swarm_steering is False

    def test_the_flag_wins_where_the_variable_is_silent(self, monkeypatch):
        monkeypatch.setenv("JUDAIS_LOBI_SWARM_STEERING", "")
        assert _parsed("--swarm-steering").swarm_steering is True

    def test_the_help_says_it_implies_cognition(self):
        """Read off the action rather than out of the formatted page, for
        the compiled-context file's reason: argparse wraps, and a substring
        search over the wrapped text finds the usage line."""
        from tests.test_contract import _mission_parser

        action = [option for option in _mission_parser()._actions
                  if "--swarm-steering" in option.option_strings][0]
        assert "--cognition" in action.help
        assert "IMPLIES" in action.help

    def test_the_flag_is_published(self):
        assert "--swarm-steering" in c.CLI_FLAGS
        assert "JUDAIS_LOBI_SWARM_STEERING" in c.ENV_VARS


# ── the doors ────────────────────────────────────────────────────────────────


class TestAskingForTheHintAsksForTheState:
    """``--swarm-steering`` implies ``--cognition`` and does not refuse.

    ``TestAskingForTheViewAsksForTheState``'s argument, for the second
    switch: the groups are computed from the shadow's own frontier, so the
    two are one request, and a harness that made an operator type both
    would be charging them for an implementation detail.
    """

    def test_the_hint_alone_still_opens_the_shadow(self, elf, tmp_path):
        from core.durable import RunStore
        from tests.test_cognition_compiled_context import run, script

        MockClass, agent = elf
        script(agent)
        run(MockClass, tmp_path, "--swarm-steering")
        store = RunStore(tmp_path / "runs")
        run_id = store.list()[0].run_id
        assert (store.directory(run_id) / REASONING_LOG).exists()


class TestTheSwitchIsTheCallersOnBothDoors:
    """`open_shadow` resolves *steering* once and carries it on both paths.

    The compiled-context door's rule, word for word: a door that resolved
    it on the fresh path only is a resumed run that quietly stopped
    offering its planner the frontier.
    """

    def test_a_fresh_shadow_carries_it(self, tmp_path):
        from core.durable import RunStore
        from core.runtime.cognition import open_shadow

        store = RunStore(tmp_path / "store")
        assert open_shadow(store, store.create().run_id,
                           steering=True).steering is True

    def test_a_reopened_shadow_carries_it(self, tmp_path):
        from core.durable import RunStore
        from core.runtime.cognition import open_shadow

        store = RunStore(tmp_path / "store")
        run_id = store.create().run_id
        first = open_shadow(store, run_id, steering=True)
        first.receipt("t", "r1", json.dumps({"records": 12481}))
        first.close_step()
        assert open_shadow(store, run_id, steering=True).steering is True

    def test_a_reopened_shadow_that_was_not_asked_offers_nothing(
            self, tmp_path):
        from core.durable import RunStore
        from core.runtime.cognition import open_shadow

        store = RunStore(tmp_path / "store")
        run_id = store.create().run_id
        open_shadow(store, run_id, steering=True)
        assert open_shadow(store, run_id).steering is False

    def test_a_library_caller_gets_the_same_switch(self):
        """A parameter the constructor could not take would be a feature
        only the CLI has — and its default is off on both doors."""
        import inspect

        from core.runtime.cognition import open_shadow

        built = inspect.signature(ShadowCognition.__init__).parameters
        assert built["steering"].default is False
        opened = inspect.signature(open_shadow).parameters
        assert opened["steering"].default is False
