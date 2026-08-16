# tests/test_swarm.py — staged decomposition over one mission backend

import json

import pytest

from core.contracts.schemas import PolicyPack
from core.runtime.grounding import GroundingConfig, GroundingValidator
from core.runtime.mission import AWAITING_APPROVAL, MissionRunner
from core.runtime.swarm import SwarmRunner
from core.tools.bus import ToolBus
from core.tools.capability import CapabilityEngine
from core.tools.descriptors import ToolDescriptor


class ScriptedModel:
    """Replays canned replies and records exactly what it was shown."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.seen = []

    def __call__(self, messages):
        self.seen.append([dict(m) for m in messages])
        return self.replies.pop(0) if self.replies else '{"answer": "done"}'

    @property
    def calls(self):
        return len(self.seen)


def tool_call(name, **arguments):
    return json.dumps({"tool": name, "arguments": arguments})


def plan(*steps):
    return json.dumps({"steps": list(steps)})


DIRECT = '{"route": "direct"}'
STAGED = '{"route": "staged"}'


@pytest.fixture
def calls():
    """Every dispatch the bus actually made, in order."""
    return []


@pytest.fixture
def bus(calls):
    b = ToolBus(capability_engine=CapabilityEngine(PolicyPack(allowed_scopes=["*"])))

    def tool(name, reply):
        def execute(**kw):
            calls.append((name, dict(kw)))
            return (0, reply, "")
        b.register(ToolDescriptor(tool_name=name, description=f"{name} tool. Second sentence."),
                   execute)

    tool("catalog.search", "corpus abc123 (id corpus.abc123)")
    tool("run_code", "wrote chart.png; printed 42")
    return b


def swarm(plain, executor, bus, **kw):
    kw.setdefault("system_message", "You are Tai.")
    return SwarmRunner(executor, bus, ["catalog.search", "run_code"],
                       plain_chat_fn=plain, **kw)


def _paging_bus():
    """One tool that returns a fresh, sizeable page every time.

    Fresh because the mission store collapses a byte-identical re-fetch to
    one line, and a run whose every result is the same never grows the
    conversation a window exists to bound.
    """
    b = ToolBus(capability_engine=CapabilityEngine(
        PolicyPack(allowed_scopes=["*"])))
    pages = {"n": 0}

    def page(**_kw):
        pages["n"] += 1
        return (0, f"page {pages['n']} — corpus.abc{pages['n']:03d} "
                   + "z" * 800, "")

    b.register(ToolDescriptor(tool_name="catalog.page",
                              description="One page. Second sentence."), page)
    return b


def _tiny_window():
    from core.runtime.context_window import ContextConfig, MissionWindow
    return MissionWindow(config=ContextConfig(
        max_context_tokens=1100, max_output_tokens=200))


class Sink:
    def __init__(self):
        self.records = []

    def __call__(self, record):
        self.records.append(dict(record))

    def of(self, event):
        return [r for r in self.records if r.get("event") == event]


# ── the stream opens before anything is asked ────────────────────────────


class TestTheStreamOpensFirst:
    """`mission_started` before the router's own call, not after it.

    The contract's silence clause says the opening record is emitted before
    the model is asked, and triage IS a call to the model.  A staged turn
    used to spend a router round-trip and a planner round-trip with nothing
    at all on the wire — minutes of it against a cold endpoint — and an
    empty stream is the one thing a consumer is told to report as a harness
    that never started.  It reported it that way because the contract said
    to, about a harness that had in fact run and asked.
    """

    def test_the_router_is_asked_only_after_the_mission_is_announced(self, bus):
        sink = Sink()
        heard = []

        def plain(messages):
            heard.append([r["event"] for r in sink.records])
            return DIRECT

        executor = ScriptedModel('{"answer": "done"}')
        swarm(plain, executor, bus, observer=sink).run("what is trending?")
        assert heard[0] == ["mission_started"]

    def test_a_router_killed_mid_call_leaves_a_stream_that_opened_and_closed(
            self, bus):
        """An ordinary exception out of the router is caught and falls open to
        the direct path, which announces the mission itself; what reaches here
        is the failure that cannot be caught.  The stream is opened before it
        and closed after it — announcing early and never closing would trade
        an honest silence for the spinner an analyst cannot leave.
        """
        sink = Sink()

        def plain(messages):
            raise KeyboardInterrupt("the endpoint went away mid-call")

        executor = ScriptedModel('{"answer": "never reached"}')
        with pytest.raises(KeyboardInterrupt):
            swarm(plain, executor, bus, observer=sink).run("anything")
        assert [r["event"] for r in sink.records] == ["mission_started",
                                                      "mission_finished"]
        assert sink.records[-1]["outcome"] == "incomplete"

    def test_the_direct_route_does_not_announce_the_mission_twice(self, bus):
        """The direct path is a whole `MissionRunner` and used to open the
        stream itself.  Two openings for one turn is two missions in a pane.
        """
        sink = Sink()
        swarm(ScriptedModel(DIRECT), ScriptedModel('{"answer": "done"}'),
              bus, observer=sink).run("what is trending?")
        assert len(sink.of("mission_started")) == 1
        assert len(sink.of("mission_finished")) == 1
        assert sink.records[-1]["event"] == "mission_finished"

    def test_the_opening_record_is_the_one_a_plain_mission_would_have_sent(
            self, bus):
        """Same record whichever way the router went.

        A consumer able to tell the two routes apart from the opening frame
        would be reading an internal decision of this harness off a contract
        that promises it one vocabulary — and the staged path's record did
        differ: `gated` was every name the caller passed rather than the
        offered ones in catalogue order.
        """
        history = [{"role": "user", "content": "headlines?"},
                   {"role": "assistant", "content": "#1, #2"}]
        gated = ["run_code", "a.tool.nobody.offers"]
        swarmed, plain_mission = Sink(), Sink()
        swarm(ScriptedModel(DIRECT), ScriptedModel('{"answer": "a"}'), bus,
              gated=gated, history=history, max_steps=5,
              observer=swarmed).run("q")
        MissionRunner(ScriptedModel('{"answer": "a"}'), bus,
                      ["catalog.search", "run_code"],
                      system_message="You are Tai.", max_steps=5,
                      gated=gated, history=history,
                      observer=plain_mission).run("q")
        assert (swarmed.of("mission_started")[0]
                == plain_mission.of("mission_started")[0])

    def test_the_opening_record_announces_the_sandbox(self, bus):
        """The staged path reads the same bus property the direct path does,
        so both announce the same isolation and neither invents its own."""
        sink = Sink()
        swarm(ScriptedModel(DIRECT), ScriptedModel('{"answer": "done"}'),
              bus, observer=sink).run("what is trending?")
        started = sink.of("mission_started")[0]
        assert started["sandbox"] == bus.sandbox_name
        assert started["sandbox"] in ("bwrap", "none")


# ── TRIAGE: small stays small ────────────────────────────────────────────


class TestTriage:
    def test_a_small_question_runs_direct_with_no_planner_call(self, bus):
        plain = ScriptedModel(DIRECT)
        executor = ScriptedModel(tool_call("catalog.search", q="trending"),
                                 '{"answer": "abc123 is trending"}')
        transcript = swarm(plain, executor, bus).run("what is trending?")
        assert transcript.completed
        assert transcript.answer == "abc123 is trending"
        # The router was the ONLY staged-role call: no plan, no gate, no
        # synthesis. Ceremony on a small question is the regression this
        # test exists to catch.
        assert plain.calls == 1

    def test_the_direct_path_carries_the_full_system_message_and_history(self, bus):
        plain = ScriptedModel(DIRECT)
        executor = ScriptedModel('{"answer": "the cable cut"}')
        history = [{"role": "user", "content": "headlines?"},
                   {"role": "assistant", "content": "#1 exercises, #2 cable cut"}]
        swarm(plain, executor, bus, history=history).run("more on #2")
        seeded = executor.seen[0]
        assert seeded[0]["content"].startswith("You are Tai.")
        assert seeded[1:3] == history

    def test_triage_that_answers_garbage_falls_open_to_direct(self, bus):
        plain = ScriptedModel("hmm, tricky one")
        executor = ScriptedModel('{"answer": "done directly"}')
        transcript = swarm(plain, executor, bus).run("anything")
        assert transcript.answer == "done directly"
        assert plain.calls == 1

    def test_triage_that_raises_falls_open_to_direct(self, bus):
        def broken(messages):
            raise RuntimeError("backend hiccup")
        executor = ScriptedModel('{"answer": "still answered"}')
        transcript = swarm(broken, executor, bus).run("anything")
        assert transcript.answer == "still answered"

    def test_the_router_sees_recent_history_so_follow_ups_read_as_follow_ups(self, bus):
        plain = ScriptedModel(DIRECT)
        executor = ScriptedModel('{"answer": "x"}')
        history = [{"role": "user", "content": "headlines?"},
                   {"role": "assistant", "content": "#1, #2, #3"}]
        swarm(plain, executor, bus, history=history).run("more on #2")
        triage_messages = plain.seen[0]
        assert {"role": "assistant", "content": "#1, #2, #3"} in triage_messages


# ── PLAN: validated mechanically, and failure is the direct path ─────────


class TestPlan:
    def test_an_unparseable_plan_twice_falls_back_to_direct(self, bus):
        plain = ScriptedModel(STAGED, "no json here", "still prose")
        executor = ScriptedModel('{"answer": "answered the slow way"}')
        transcript = swarm(plain, executor, bus).run("complex thing")
        assert transcript.answer == "answered the slow way"
        assert plain.calls == 3          # triage + two plan attempts

    def test_a_single_step_plan_collapses_to_direct(self, bus):
        plain = ScriptedModel(
            STAGED,
            plan({"id": "s1", "goal": "just search", "rung": "tool"}))
        executor = ScriptedModel(tool_call("catalog.search", q="x"),
                                 '{"answer": "found"}')
        transcript = swarm(plain, executor, bus).run("simple after all")
        assert transcript.answer == "found"
        assert plain.calls == 2          # triage + plan; no gate, no synth

    def _bad_rung_repair(self, bus, **kw):
        plain = ScriptedModel(
            STAGED,
            plan({"id": "s1", "goal": "search", "rung": "magic"},
                 {"id": "s2", "goal": "count", "rung": "code"}),
            plan({"id": "s1", "goal": "search", "rung": "tool"},
                 {"id": "s2", "goal": "count", "rung": "code",
                  "needs": ["s1"]}),
            "the final answer")
        executor = ScriptedModel(
            tool_call("catalog.search", q="x"), '{"answer": "abc123"}',
            tool_call("run_code", code="print(1)"), '{"answer": "counted 1"}')
        transcript = swarm(plain, executor, bus, **kw).run("search then count")
        assert transcript.completed
        return plain.seen[2][-1]["content"]

    def test_a_bad_rung_is_reprompted_with_the_problem_named(self, bus):
        """The repair lists the rungs this run OFFERS, not every rung that
        exists: with no SDK declared, `code+sdk` is not one of them, and
        naming it here would send the planner back down a route the same
        validator would refuse again."""
        repair = self._bad_rung_repair(bus)
        assert "'magic'" in repair and "tool, code." in repair
        assert "code+sdk" not in repair

    def test_the_repair_names_the_sdk_rung_once_one_is_declared(self, bus):
        repair = self._bad_rung_repair(bus, sdk_import="acme")
        assert "'magic'" in repair and "tool, code, code+sdk" in repair

    def test_needs_may_only_name_earlier_steps(self, bus):
        plain = ScriptedModel(
            STAGED,
            plan({"id": "s1", "goal": "a", "rung": "tool", "needs": ["s2"]},
                 {"id": "s2", "goal": "b", "rung": "tool"}),
            "not json either")
        executor = ScriptedModel('{"answer": "direct fallback"}')
        transcript = swarm(plain, executor, bus).run("x")
        assert transcript.answer == "direct fallback"
        assert "EARLIER" in plain.seen[2][-1]["content"]

    def test_the_planner_sees_tool_names_but_not_argument_schemas(self, bus):
        plain = ScriptedModel(STAGED, "x", "y")
        executor = ScriptedModel('{"answer": "d"}')
        swarm(plain, executor, bus).run("q")
        planner_system = plain.seen[1][0]["content"]
        assert "catalog.search" in planner_system
        assert "Second sentence" not in planner_system


# ── STAGED: the happy path ───────────────────────────────────────────────


TWO_STEP_PLAN = plan(
    {"id": "s1", "goal": "find the corpus", "rung": "tool",
     "done": "an asset id is named"},
    {"id": "s2", "goal": "chart the counts", "rung": "code",
     "needs": ["s1"]})


class TestStagedHappyPath:
    def run_it(self, bus, calls, sink=None):
        plain = ScriptedModel(
            STAGED, TWO_STEP_PLAN,
            '{"pass": true}',                       # LLM gate over s1's done
            "Final: corpus.abc123 charted in chart.png")
        executor = ScriptedModel(
            tool_call("catalog.search", q="corpus"),
            '{"answer": "found corpus.abc123"}',
            tool_call("run_code", code="plot()"),
            '{"answer": "chart.png written"}')
        runner = swarm(plain, executor, bus, observer=sink)
        return runner.run("find the corpus and chart it"), plain, executor

    def test_the_answer_is_synthesized_from_both_step_results(self, bus, calls):
        transcript, plain, _ = self.run_it(bus, calls)
        assert transcript.outcome == "answered"
        assert transcript.answer == "Final: corpus.abc123 charted in chart.png"
        synth_request = plain.seen[-1][-1]["content"]
        assert "found corpus.abc123" in synth_request
        assert "chart.png written" in synth_request

    def test_both_tools_were_dispatched_in_plan_order(self, bus, calls):
        self.run_it(bus, calls)
        assert [name for name, _ in calls] == ["catalog.search", "run_code"]

    def test_a_code_step_is_told_to_do_it_by_running_code(self, bus, calls):
        _, _, executor = self.run_it(bus, calls)
        step2 = executor.seen[2][-1]["content"]
        assert "code-execution tool" in step2
        assert "print the values" in step2

    def test_a_step_sees_only_the_summaries_it_declared_it_needs(self, bus, calls):
        _, _, executor = self.run_it(bus, calls)
        step2 = executor.seen[2][-1]["content"]
        assert "s1: found corpus.abc123" in step2
        # The RAW tool output of s1 does not travel — only the executor's
        # own stated result does.
        assert "(id corpus.abc123)" not in step2

    def test_the_transcript_records_every_sub_step_renumbered(self, bus, calls):
        transcript, _, _ = self.run_it(bus, calls)
        assert [s.index for s in transcript.steps] == list(range(len(transcript.steps)))
        assert [s.tool for s in transcript.steps if s.tool] == [
            "catalog.search", "run_code"]

    def test_the_event_stream_reads_as_one_mission(self, bus, calls):
        sink = Sink()
        self.run_it(bus, calls, sink=sink)
        assert len(sink.of("mission_started")) == 1
        assert len(sink.of("mission_finished")) == 1
        assert len(sink.of("answer")) == 1
        indexes = [r["index"] for r in sink.of("tool_call")]
        assert indexes == sorted(indexes)
        assert sink.records[-1]["event"] == "mission_finished"

    def test_the_plan_rides_on_the_first_step_started_for_a_watcher(
            self, bus, calls):
        """It cannot ride `mission_started` any more: that record is written
        before triage, and at that moment there is no plan and there may never
        be one.  The first `step_started` is the next thing a watcher hears
        and the moment the plan starts being true."""
        sink = Sink()
        self.run_it(bus, calls, sink=sink)
        assert "plan" not in sink.of("mission_started")[0]
        first_step = sink.of("step_started")[0]
        assert [s["id"] for s in first_step["plan"]] == ["s1", "s2"]
        assert [s["rung"] for s in first_step["plan"]] == ["tool", "code"]

    def test_no_later_step_repeats_the_plan(self, bus, calls):
        """Once, on the step it belongs to. A field that arrived on every
        step would be a plan a watcher had to diff to notice a redraw."""
        sink = Sink()
        self.run_it(bus, calls, sink=sink)
        assert [i for i, r in enumerate(sink.of("step_started"))
                if "plan" in r] == [0]


class TestThePlanWaitsForAStep:
    """`plan` is declared optional on `step_started` and on nothing else.

    Every sub-mission emits its `step_started` before anything else, so on
    every path that runs today the plan lands on one and the rule is
    invisible.  It is asserted here against the filter itself rather than
    left to that ordering: a field an event does not declare is a field a
    consumer meets and has no sentence for, and the ordering is a property
    of the runner underneath, which is not this object's to promise.
    """

    def _observer(self, emitted):
        from core.runtime.swarm import _StageObserver

        return _StageObserver(
            lambda event, **fields: emitted.append((event, fields)))

    def test_a_record_that_is_not_a_step_does_not_take_the_plan(self):
        from core.runtime.swarm import PlanStep

        emitted = []
        stage = self._observer(emitted)
        stage.announce([PlanStep(id="s1", goal="find it", rung="tool")])
        stage({"event": "tool_call", "index": 0, "tool": "catalog.search",
               "arguments": {}})
        stage({"event": "step_started", "index": 1})
        assert [event for event, _ in emitted] == ["tool_call", "step_started"]
        assert "plan" not in emitted[0][1]
        assert [s["id"] for s in emitted[1][1]["plan"]] == ["s1"]


class TestRungSdk:
    """The `code+sdk` rung names the platform, so the platform names it.

    This rung used to carry a constant reading `import taipan` — one
    deployment's module name, in the framework that is supposed to drive
    any of them, and the module docstring two screens above promising that
    a role never names a platform's particulars. The name now arrives from
    the skill manifest's `sdk_import`, and where no manifest declares one
    the rung is withheld rather than offered with a blank in it: a step
    told to "import the platform SDK" with no SDK named is an invitation
    to invent a module, and a 20B accepts it.
    """

    SDK_PLAN = staticmethod(lambda: plan(
        {"id": "s1", "goal": "fetch run numbers and plot them",
         "rung": "code+sdk"},
        {"id": "s2", "goal": "report", "rung": "tool", "needs": ["s1"]},
    ))

    def _run_sdk_plan(self, bus, **kw):
        plain = ScriptedModel(STAGED, self.SDK_PLAN(), "final")
        executor = ScriptedModel(
            tool_call("run_code", code="import acme"),
            '{"answer": "plotted"}',
            tool_call("catalog.search", q="x"),
            '{"answer": "reported"}')
        swarm(plain, executor, bus, **kw).run("plot a run")
        return plain, executor

    def test_a_declared_sdk_is_the_name_the_executor_is_given(self, bus):
        _plain, executor = self._run_sdk_plan(bus, sdk_import="acme")
        step1 = executor.seen[0][-1]["content"]
        assert "import acme" in step1
        assert "credential is already in the execution environment" in step1

    def test_the_declared_name_is_the_only_one_that_appears(self, bus):
        """No deployment's module name survives in the framework."""
        _plain, executor = self._run_sdk_plan(bus, sdk_import="acme")
        assert "taipan" not in executor.seen[0][-1]["content"]

    def test_a_declared_sdk_is_offered_to_the_planner_by_name(self, bus):
        plain, _executor = self._run_sdk_plan(bus, sdk_import="acme")
        planner_prompt = plain.seen[1][0]["content"]
        assert '"code+sdk"' in planner_prompt
        assert "import acme" in planner_prompt

    def test_no_declared_sdk_withholds_the_rung_from_the_planner(self, bus):
        plain = ScriptedModel(STAGED, self.SDK_PLAN(), plan(
            {"id": "s1", "goal": "count", "rung": "code"}), "final")
        executor = ScriptedModel(tool_call("run_code", code="c"),
                                 '{"answer": "counted"}')
        swarm(plain, executor, bus).run("plot a run")
        planner_prompt = plain.seen[1][0]["content"]
        assert '"code+sdk"' not in planner_prompt
        assert '"tool"' in planner_prompt and '"code"' in planner_prompt

    def test_no_declared_sdk_never_says_taipan_anywhere(self, bus):
        """The literal that was in the source, gone from every surface."""
        plain = ScriptedModel(STAGED, plan(
            {"id": "s1", "goal": "count", "rung": "code"}), "final")
        executor = ScriptedModel(tool_call("run_code", code="c"),
                                 '{"answer": "counted"}')
        swarm(plain, executor, bus).run("count things")
        shown = [m["content"] for seen in (*plain.seen, *executor.seen)
                 for m in seen]
        assert not any("taipan" in text.lower() for text in shown)

    def test_a_plan_using_the_withheld_rung_is_refused_by_name(self, bus):
        """The planner is corrected with the rungs it may actually use."""
        plain = ScriptedModel(STAGED, self.SDK_PLAN(), plan(
            {"id": "s1", "goal": "count", "rung": "code"}), "final")
        executor = ScriptedModel(tool_call("run_code", code="c"),
                                 '{"answer": "counted"}')
        swarm(plain, executor, bus).run("plot a run")
        correction = plain.seen[2][-1]["content"]
        assert "code+sdk" in correction
        assert "tool, code" in correction

    def test_the_rung_set_shrinks_by_exactly_the_sdk_rung(self):
        from core.runtime.swarm import RUNGS, RUNGS_WITHOUT_SDK, SDK_RUNG

        assert set(RUNGS) - set(RUNGS_WITHOUT_SDK) == {SDK_RUNG}


# ── GATE and ITERATE: mechanical first, bounded retries, one re-plan ─────


class TestGateAndRetry:
    def test_a_step_that_never_called_a_tool_fails_the_mechanical_gate_and_retries(self, bus, calls):
        plain = ScriptedModel(
            STAGED,
            plan({"id": "s1", "goal": "search", "rung": "tool"},
                 {"id": "s2", "goal": "count", "rung": "code", "needs": ["s1"]}),
            "final answer")
        executor = ScriptedModel(
            '{"answer": "I remember abc123"}',       # attempt 1: no tool call
            tool_call("catalog.search", q="x"),      # retry: does the work
            '{"answer": "found abc123"}',
            tool_call("run_code", code="c"),
            '{"answer": "counted"}')
        transcript = swarm(plain, executor, bus).run("search then count")
        assert transcript.completed
        retry_objective = executor.seen[1][-1]["content"]
        assert "previous attempt at this step failed" in retry_objective
        assert "no successful tool call" in retry_objective
        assert [name for name, _ in calls] == ["catalog.search", "run_code"]

    def test_an_llm_gate_failure_names_its_why_on_the_retry(self, bus):
        plain = ScriptedModel(
            STAGED,
            plan({"id": "s1", "goal": "search", "rung": "tool",
                  "done": "an asset id is named"},
                 {"id": "s2", "goal": "b", "rung": "tool", "needs": ["s1"]}),
            '{"pass": false, "why": "no asset id in the result"}',
            '{"pass": true}',
            "final")
        executor = ScriptedModel(
            tool_call("catalog.search", q="x"), '{"answer": "many results"}',
            tool_call("catalog.search", q="x id"), '{"answer": "corpus.abc123"}',
            tool_call("catalog.search", q="y"), '{"answer": "b done"}')
        transcript = swarm(plain, executor, bus).run("q")
        assert transcript.completed
        # Attempt 1 cost two model calls (tool, answer); the retry's fresh
        # seed is therefore the third, and its objective carries the why.
        assert "no asset id in the result" in executor.seen[2][-1]["content"]

    def test_retries_exhausted_triggers_exactly_one_replan(self, bus):
        plain = ScriptedModel(
            STAGED,
            plan({"id": "s1", "goal": "search", "rung": "tool"},
                 {"id": "s2", "goal": "count", "rung": "code", "needs": ["s1"]}),
            plan({"id": "r1", "goal": "search another way", "rung": "tool"}),
            "final after replan")
        executor = ScriptedModel(
            '{"answer": "no tool 1"}',               # s1 attempt 1: gate fails
            '{"answer": "no tool 2"}',               # s1 retry: gate fails
            tool_call("catalog.search", q="other"),  # r1 from the new plan
            '{"answer": "found it"}')
        transcript = swarm(plain, executor, bus).run("q")
        assert transcript.answer == "final after replan"
        # triage, plan, re-plan, synth — and the re-plan request names the
        # failed step so the planner can route around it.
        assert plain.calls == 4
        replan_request = plain.seen[2][-1]["content"]
        assert "The previous plan failed" in replan_request
        assert "s1" in replan_request

    def test_a_redrawn_plan_is_announced_on_the_step_it_starts(self, bus):
        """A watcher still holding the abandoned plan renders the steps of the
        new one against the goals of the old."""
        sink = Sink()
        plain = ScriptedModel(
            STAGED,
            plan({"id": "s1", "goal": "search", "rung": "tool"},
                 {"id": "s2", "goal": "count", "rung": "code", "needs": ["s1"]}),
            plan({"id": "r1", "goal": "search another way", "rung": "tool"}),
            "final after replan")
        executor = ScriptedModel(
            '{"answer": "no tool 1"}',               # s1 attempt 1: gate fails
            '{"answer": "no tool 2"}',               # s1 retry: gate fails
            tool_call("catalog.search", q="other"),  # r1 from the new plan
            '{"answer": "found it"}')
        swarm(plain, executor, bus, observer=sink).run("q")
        announced = [[s["id"] for s in r["plan"]]
                     for r in sink.of("step_started") if "plan" in r]
        assert announced == [["s1", "s2"], ["r1"]]

    def test_a_replanned_failure_surfaces_as_an_honest_partial_answer(self, bus):
        plain = ScriptedModel(
            STAGED,
            plan({"id": "s1", "goal": "search", "rung": "tool"},
                 {"id": "s2", "goal": "chart it", "rung": "code",
                  "needs": ["s1"]}),
            plan({"id": "r1", "goal": "chart another way", "rung": "code"}),
            "Partial: found corpus.abc123; the chart step failed.")
        executor = ScriptedModel(
            tool_call("catalog.search", q="x"),
            '{"answer": "found corpus.abc123"}',
            '{"answer": "cannot run code 1"}',       # s2 attempt: no tool
            '{"answer": "cannot run code 2"}',       # s2 retry: no tool
            '{"answer": "cannot run code 3"}',       # r1 attempt: no tool
            '{"answer": "cannot run code 4"}')       # r1 retry: no tool
        transcript = swarm(plain, executor, bus).run("search then chart")
        assert transcript.outcome == "answered_with_caveat"
        synth_request = plain.seen[-1][-1]["content"]
        assert "FAILED" in synth_request
        assert "found corpus.abc123" in synth_request
        # Nothing stalls and nothing pretends: the answer is the synthesis
        # the failure was reported into.
        assert transcript.answer.startswith("Partial:")

    def test_a_gate_that_cannot_parse_does_not_fail_mechanically_sound_work(self, bus):
        plain = ScriptedModel(
            STAGED,
            plan({"id": "s1", "goal": "search", "rung": "tool",
                  "done": "an id"},
                 {"id": "s2", "goal": "b", "rung": "tool", "needs": ["s1"]}),
            "gate says words, not json",
            "final")
        executor = ScriptedModel(
            tool_call("catalog.search", q="x"), '{"answer": "corpus.abc123"}',
            tool_call("catalog.search", q="y"), '{"answer": "done"}')
        transcript = swarm(plain, executor, bus).run("q")
        assert transcript.outcome == "answered"


# ── grounding: a repair turn is work, and work is said out loud ──────────


class TestTheRepairTurnIsVisible:
    """A repair turn is a whole extra round-trip to the model and, from
    outside, looks exactly like a stall.  The direct path has said so since
    `repairing` was written down; the staged path spent its repair turns in
    silence and emitted only the verdict, minutes later, with nothing in
    between to tell a watcher the wait from a hang.
    """

    def _repairing_run(self, bus, sink):
        validator = GroundingValidator.from_config(
            GroundingConfig.from_mapping(
                {"number_pattern": r"\d+\.\d{2,}", "max_repairs": 1}))
        plain = ScriptedModel(
            STAGED, TWO_STEP_PLAN,
            '{"pass": true}',                       # LLM gate over s1's done
            "the score is 80.847",                  # synthesis: unsupported
            "the score is 80.848")                  # the repair turn: still is
        executor = ScriptedModel(
            tool_call("catalog.search", q="corpus"),
            '{"answer": "found corpus.abc123"}',
            tool_call("run_code", code="plot()"),
            '{"answer": "chart.png written"}')
        return swarm(plain, executor, bus, validator=validator,
                     observer=sink).run("score the corpus")

    def test_the_interim_report_says_it_is_repairing_and_the_verdict_does_not(
            self, bus):
        sink = Sink()
        transcript = self._repairing_run(bus, sink)
        assert transcript.outcome == "answered_with_caveat"
        assert [r["repairing"] for r in sink.of("grounding")] == [True, False]

    def test_the_interim_report_names_what_it_caught(self, bus):
        """`80.847` rather than "1 figure was unsupported": the count sends a
        reader looking, the token tells them where."""
        sink = Sink()
        self._repairing_run(bus, sink)
        interim = sink.of("grounding")[0]
        assert interim["unsupported"] == ["80.847"]
        assert interim["repairs"] == 1

    def test_the_interim_report_arrives_before_the_answer_it_delayed(self, bus):
        sink = Sink()
        self._repairing_run(bus, sink)
        events = [r["event"] for r in sink.records]
        assert events.index("grounding") < events.index("answer")


# ── the approval gate ends the whole turn, holding the proposed call ─────


class TestApprovalGate:
    def test_a_gated_tool_in_a_sub_step_stops_the_swarm_awaiting_a_person(self, bus):
        sink = Sink()
        plain = ScriptedModel(
            STAGED,
            plan({"id": "s1", "goal": "cancel the job", "rung": "tool"},
                 {"id": "s2", "goal": "report", "rung": "tool",
                  "needs": ["s1"]}))
        executor = ScriptedModel(
            tool_call("run_code", job="j1"))
        runner = swarm(plain, executor, bus, gated=["run_code"],
                       observer=sink)
        transcript = runner.run("cancel it")
        assert transcript.outcome == AWAITING_APPROVAL
        assert transcript.awaiting == {"tool": "run_code",
                                       "arguments": {"job": "j1"}}
        assert len(sink.of("gate_requested")) == 1
        assert sink.of("mission_finished")[0]["outcome"] == AWAITING_APPROVAL
        # No synthesis happened over an act nobody approved.
        assert transcript.answer is None


# ── context discipline: the whole point ──────────────────────────────────


class TestContextIsBounded:
    def test_a_steps_long_answer_reaches_the_next_step_cut_to_the_bound(self, bus):
        long_answer = "corpus.abc123 " + "x" * 10_000
        plain = ScriptedModel(
            STAGED,
            plan({"id": "s1", "goal": "search", "rung": "tool"},
                 {"id": "s2", "goal": "count", "rung": "code",
                  "needs": ["s1"]}),
            "final")
        executor = ScriptedModel(
            tool_call("catalog.search", q="x"),
            json.dumps({"answer": long_answer}),
            tool_call("run_code", code="c"),
            '{"answer": "counted"}')
        swarm(plain, executor, bus).run("q")
        step2 = executor.seen[2][-1]["content"]
        assert "[cut at 1200 characters]" in step2
        assert len(step2) < 3_000

    def test_raw_tool_output_never_reaches_the_planner_or_the_synthesizer(self, calls):
        marker = "RAW_OUTPUT_MARKER_" + "z" * 50_000
        b = ToolBus(capability_engine=CapabilityEngine(PolicyPack(allowed_scopes=["*"])))
        b.register(ToolDescriptor(tool_name="catalog.search", description="Search."),
                   lambda **kw: (0, marker, ""))
        b.register(ToolDescriptor(tool_name="run_code", description="Run code."),
                   lambda **kw: (0, "ok", ""))
        plain = ScriptedModel(
            STAGED,
            plan({"id": "s1", "goal": "search", "rung": "tool"},
                 {"id": "s2", "goal": "count", "rung": "code",
                  "needs": ["s1"]}),
            "final")
        executor = ScriptedModel(
            tool_call("catalog.search", q="x"), '{"answer": "got the listing"}',
            tool_call("run_code", code="c"), '{"answer": "counted"}')
        runner = SwarmRunner(executor, b, ["catalog.search", "run_code"],
                             plain_chat_fn=plain, system_message="Tai.")
        runner.run("q")
        for call in plain.seen:
            for message in call:
                assert "RAW_OUTPUT_MARKER" not in message["content"]
        step2 = executor.seen[2][-1]["content"]
        assert "RAW_OUTPUT_MARKER" not in step2

    def test_the_window_reaches_the_direct_path(self):
        """The direct path IS a mission loop, and a window handed to the
        swarm that stopped at the swarm would bound nothing at all."""
        window = _tiny_window()
        plain = ScriptedModel(DIRECT)
        executor = ScriptedModel(*([tool_call("catalog.page")] * 6),
                                 '{"answer": "ok"}')
        sink = Sink()
        SwarmRunner(executor, _paging_bus(), ["catalog.page"],
                    plain_chat_fn=plain, system_message="Tai.",
                    observer=sink, window=window).run("q")
        assert any("compacted" in r for r in sink.of("step_started"))
        assert max(window.estimate(sent) for sent in executor.seen) \
            <= window.limit_tokens

    def test_the_window_reaches_the_steps_of_a_staged_mission(self):
        """A staged mission runs more steps than a direct one, not fewer."""
        window = _tiny_window()
        plain = ScriptedModel(
            STAGED,
            plan({"id": "s1", "goal": "page", "rung": "tool"},
                 {"id": "s2", "goal": "page again", "rung": "tool",
                  "needs": ["s1"]}),
            "final")
        executor = ScriptedModel(*([tool_call("catalog.page")] * 3),
                                 '{"answer": "one"}',
                                 *([tool_call("catalog.page")] * 3),
                                 '{"answer": "two"}')
        sink = Sink()
        SwarmRunner(executor, _paging_bus(), ["catalog.page"],
                    plain_chat_fn=plain, system_message="Tai.",
                    observer=sink, window=window).run("q")
        assert any("compacted" in r for r in sink.of("step_started"))
        assert max(window.estimate(sent) for sent in executor.seen) \
            <= window.limit_tokens

    def test_every_role_prompt_is_short(self):
        from core.runtime import swarm as module
        for name in ("TRIAGE_PROMPT", "PLAN_PROMPT", "EXECUTE_PROMPT",
                     "GATE_PROMPT", "SYNTHESIZE_PROMPT"):
            prompt = getattr(module, name)
            assert len(prompt.splitlines()) <= 20, name
            assert len(prompt) < 1_600, name


# ── the budget is a hard stop, said out loud ─────────────────────────────


class TestBudget:
    def test_budget_exhaustion_becomes_a_named_failure_not_a_stall(self, bus):
        plain = ScriptedModel(
            STAGED,
            plan({"id": "s1", "goal": "a", "rung": "tool"},
                 {"id": "s2", "goal": "b", "rung": "tool", "needs": ["s1"]},
                 {"id": "s3", "goal": "c", "rung": "tool", "needs": ["s2"]}),
            "partial answer")
        executor = ScriptedModel(
            tool_call("catalog.search", q="a"), '{"answer": "a done"}',
            tool_call("catalog.search", q="b"), '{"answer": "b done"}')
        runner = swarm(plain, executor, bus, max_steps=4)
        transcript = runner.run("three things")
        assert transcript.outcome == "answered_with_caveat"
        synth_request = plain.seen[-1][-1]["content"]
        assert "budget was exhausted" in synth_request


# ── what the swarm says about the host it ran on ─────────────────────────


LEAK_PATH = "/home/testuser/data/mission.log"
LEAK_TOKEN = "hunter2-hunter2-hunter2"


@pytest.fixture
def leaky_env(monkeypatch):
    monkeypatch.setenv("MISSION_API_KEY", LEAK_TOKEN)
    return "MISSION_API_KEY"


@pytest.fixture
def leaky_bus(calls):
    """The ordinary two-tool bus, except that ``catalog.search`` warns about
    a file in somebody's home directory with a credential in the message —
    and still returns the identifier an answer will cite."""
    b = ToolBus(capability_engine=CapabilityEngine(PolicyPack(allowed_scopes=["*"])))

    def search(**kw):
        calls.append(("catalog.search", dict(kw)))
        return (0, "corpus abc123 (id corpus.abc123)",
                f"warn: cache {LEAK_PATH} unreadable, key {LEAK_TOKEN}")

    def run_code(**kw):
        calls.append(("run_code", dict(kw)))
        return (0, "wrote chart.png; printed 42", "")

    b.register(ToolDescriptor(tool_name="catalog.search",
                              description="Search. Second sentence."), search)
    b.register(ToolDescriptor(tool_name="run_code",
                              description="Run. Second sentence."), run_code)
    return b


class TestTheSwarmStreamDoesNotNameTheHost:
    """The swarm has two emitters — its own and every sub-mission's — and a
    redactor installed at one of them covers half a turn.  The sub-missions
    go out through `MissionRunner._emit`; the opening, the synthesized answer
    and the swarm's own grounding verdict do not, and those are exactly the
    records a pane renders largest.
    """

    def test_a_sub_missions_tool_error_arrives_scrubbed(self, leaky_bus, leaky_env):
        sink = Sink()
        plain = ScriptedModel(
            STAGED,
            plan({"id": "s1", "goal": "find the corpus", "rung": "tool"},
                 {"id": "s2", "goal": "chart it", "rung": "tool",
                  "needs": ["s1"]}),
            "corpus.abc123 was charted")
        executor = ScriptedModel(
            tool_call("catalog.search", q="corpus"),
            '{"answer": "found corpus.abc123"}',
            tool_call("run_code", code="plot()"),
            '{"answer": "chart.png written"}')
        swarm(plain, executor, leaky_bus, observer=sink).run("chart the corpus")
        error = sink.of("tool_result")[0]["error"]
        assert "<home>/data/mission.log" in error
        assert f"<redacted:{leaky_env}>" in error
        assert LEAK_PATH not in json.dumps(sink.records)
        assert LEAK_TOKEN not in json.dumps(sink.records)

    def test_the_evidence_survives_the_stage_observer(self, leaky_bus, leaky_env):
        """The staged path renumbers every record on its way through
        `_StageObserver` and emits it again.  `output` has to come out the far
        end byte for byte or the pane and the mission store disagree about
        what the model was given."""
        sink = Sink()
        plain = ScriptedModel(
            STAGED,
            plan({"id": "s1", "goal": "find the corpus", "rung": "tool"},
                 {"id": "s2", "goal": "chart it", "rung": "tool",
                  "needs": ["s1"]}),
            "corpus.abc123 was charted")
        executor = ScriptedModel(
            tool_call("catalog.search", q="corpus"),
            '{"answer": "found corpus.abc123"}',
            tool_call("run_code", code="plot()"),
            '{"answer": "chart.png written"}')
        transcript = swarm(plain, executor, leaky_bus,
                           observer=sink).run("chart the corpus")
        assert sink.of("tool_result")[0]["output"] == \
            "corpus abc123 (id corpus.abc123)"
        assert sink.of("tool_result")[0]["arguments"] == {"q": "corpus"}
        assert "corpus.abc123" in transcript.answer

    def test_the_swarms_own_answer_is_scrubbed(self, bus, leaky_env):
        """The synthesized answer never passes through a `MissionRunner`, so
        it is the record a redactor installed only on the direct path would
        miss."""
        sink = Sink()
        plain = ScriptedModel(
            STAGED,
            plan({"id": "s1", "goal": "a", "rung": "tool"},
                 {"id": "s2", "goal": "b", "rung": "tool", "needs": ["s1"]}),
            f"the run failed: {LEAK_PATH} ({LEAK_TOKEN})")
        executor = ScriptedModel(
            tool_call("catalog.search", q="a"), '{"answer": "a done"}',
            tool_call("run_code", code="b"), '{"answer": "b done"}')
        swarm(plain, executor, bus, observer=sink).run("q")
        assert sink.of("answer")[0]["text"] == (
            f"the run failed: <home>/data/mission.log (<redacted:{leaky_env}>)")

    def test_the_direct_route_under_the_swarm_is_scrubbed_once(
            self, leaky_bus, leaky_env):
        """A direct sub-mission's records are scrubbed by its own runner and
        again by the swarm's `_emit`.  Scrubbing has to be idempotent or the
        second pass eats the first one's tokens."""
        sink = Sink()
        swarm(ScriptedModel(DIRECT),
              ScriptedModel(tool_call("catalog.search", q="a"),
                            '{"answer": "found corpus.abc123"}'),
              leaky_bus, observer=sink).run("q")
        error = sink.of("tool_result")[0]["error"]
        assert error.count("<home>") == 1
        assert error == ("warn: cache <home>/data/mission.log unreadable, "
                         f"key <redacted:{leaky_env}>")




# ── the opening record names this run's audit file, whichever way it goes ────


class TestTheOpeningNamesTheAuditFile:
    """A staged mission is a second emitter of ``mission_started``.

    It builds that record by hand from ``_opening`` — which is exactly the
    arrangement that once shipped six grounding fields where the direct path
    emitted ten — so ``audit_ref`` comes out of the same
    :func:`core.runtime.mission.audit_ref_of` the direct loop uses, reading
    the value off the **bus** rather than resolving a second path of its own.
    A stream naming a file nothing wrote to would be worse than no
    ``audit_ref`` at all, because a consumer would believe it.
    """

    @pytest.fixture
    def audited_bus(self, tmp_path, calls):
        from core.policy.audit import AuditLogger

        b = ToolBus(
            capability_engine=CapabilityEngine(PolicyPack(allowed_scopes=["*"])),
            audit=AuditLogger(path=tmp_path / "audit.jsonl"),
        )

        def execute(**kw):
            calls.append(("catalog.search", dict(kw)))
            return (0, "corpus abc123", "")

        b.register(ToolDescriptor(tool_name="catalog.search",
                                  description="search. Second sentence."),
                   execute)
        return b

    def _openings(self, plain, executor, bus_):
        seen = []
        SwarmRunner(executor, bus_, ["catalog.search"],
                    system_message="You are Tai.", plain_chat_fn=plain,
                    observer=seen.append).run("go")
        return [r for r in seen if r["event"] == "mission_started"]

    def test_the_staged_path_names_it(self, audited_bus, tmp_path):
        plain = ScriptedModel(
            STAGED,
            plan({"id": "s1", "goal": "a", "rung": "tool"},
                 {"id": "s2", "goal": "b", "rung": "tool", "needs": ["s1"]}),
            "the answer")
        executor = ScriptedModel(
            tool_call("catalog.search", q="a"), '{"answer": "a done"}',
            tool_call("catalog.search", q="b"), '{"answer": "b done"}')
        openings = self._openings(plain, executor, audited_bus)
        assert [o["audit_ref"] for o in openings] == \
            [str(tmp_path / "audit.jsonl")]

    def test_the_direct_path_through_the_swarm_names_it_once(
            self, audited_bus, tmp_path):
        """One turn, one opening. The sub-runner underneath is a whole
        ``MissionRunner`` and its own ``mission_started`` is dropped, so this
        also says the surviving record is the one carrying the reference."""
        openings = self._openings(
            ScriptedModel(DIRECT), ScriptedModel('{"answer": "ok"}'),
            audited_bus)
        assert [o["audit_ref"] for o in openings] == \
            [str(tmp_path / "audit.jsonl")]

    def test_it_is_null_when_the_bus_is_not_audited(self, bus):
        openings = self._openings(
            ScriptedModel(DIRECT), ScriptedModel('{"answer": "ok"}'), bus)
        assert [o["audit_ref"] for o in openings] == [None]

    def test_the_opening_is_the_record_the_direct_runner_would_have_emitted(
            self, audited_bus):
        """A consumer that could tell from the opening frame which way the
        router went would be reading an internal decision off a contract that
        promises it one vocabulary — ``audit_ref`` included."""
        staged_plain = ScriptedModel(
            STAGED,
            plan({"id": "s1", "goal": "a", "rung": "tool"},
                 {"id": "s2", "goal": "b", "rung": "tool", "needs": ["s1"]}),
            "the answer")
        staged_executor = ScriptedModel(
            tool_call("catalog.search", q="a"), '{"answer": "a done"}',
            tool_call("catalog.search", q="b"), '{"answer": "b done"}')
        staged = self._openings(staged_plain, staged_executor, audited_bus)[0]
        direct = self._openings(ScriptedModel(DIRECT),
                                ScriptedModel('{"answer": "ok"}'),
                                audited_bus)[0]
        assert staged == direct

    def test_the_staged_path_audits_every_dispatch_with_its_step(
            self, audited_bus, tmp_path):
        """Renumbering the stream's ``index`` is the swarm's business; the
        audit reads whatever the sub-runner set, which is that sub-mission's
        own step."""
        import json

        plain = ScriptedModel(
            STAGED,
            plan({"id": "s1", "goal": "a", "rung": "tool"},
                 {"id": "s2", "goal": "b", "rung": "tool", "needs": ["s1"]}),
            "the answer")
        executor = ScriptedModel(
            tool_call("catalog.search", q="a"), '{"answer": "a done"}',
            tool_call("catalog.search", q="b"), '{"answer": "b done"}')
        self._openings(plain, executor, audited_bus)
        lines = [json.loads(line) for line
                 in (tmp_path / "audit.jsonl").read_text().splitlines()]
        dispatched = [entry for entry in lines
                      if entry["tool_name"] == "catalog.search"]
        assert len(dispatched) == 2
        assert all("step" in json.loads(entry["detail"]) for entry in dispatched)


# ── the durable transcript, on both routes ───────────────────────────────────


class TestTheRunIsRecorded:
    """One turn is one run, whichever way the router sends it.

    The staged path's sub-missions reach this runner's ``_emit`` to be
    renumbered, and the direct path's now reach it too — a sub-runner handed
    a store of its own would write every step twice, once under its own index
    and once under the global one, and a direct path that went around the
    choke point would put a mission's answer on a pane and not in its log.
    """

    def store(self, tmp_path):
        from core.durable import RunStore
        return RunStore(tmp_path / "runs")

    def direct(self, bus, sink, store, run_id):
        plain = ScriptedModel(DIRECT)
        executor = ScriptedModel(tool_call("catalog.search", q="corpus"),
                                 '{"answer": "found corpus.abc123"}')
        return swarm(plain, executor, bus, observer=sink,
                     run_store=store, run_id=run_id).run("what is trending?")

    def staged(self, bus, sink, store, run_id):
        plain = ScriptedModel(
            STAGED, TWO_STEP_PLAN, '{"pass": true}',
            "Final: corpus.abc123 charted in chart.png")
        executor = ScriptedModel(
            tool_call("catalog.search", q="corpus"),
            '{"answer": "found corpus.abc123"}',
            tool_call("run_code", code="plot()"),
            '{"answer": "chart.png written"}')
        return swarm(plain, executor, bus, observer=sink,
                     run_store=store, run_id=run_id).run("find it and chart it")

    @pytest.mark.parametrize("route", ["direct", "staged"])
    def test_the_stream_and_the_log_hold_the_same_records(self, bus, tmp_path,
                                                          route):
        store = self.store(tmp_path)
        run_id = store.create().run_id
        sink = Sink()
        getattr(self, route)(bus, sink, store, run_id)
        assert store.records(run_id) == sink.records

    @pytest.mark.parametrize("route", ["direct", "staged"])
    def test_nothing_is_written_twice(self, bus, tmp_path, route):
        store = self.store(tmp_path)
        run_id = store.create().run_id
        getattr(self, route)(bus, Sink(), store, run_id)
        written = [r["event"] for r in store.records(run_id)]
        assert written.count("mission_started") == 1
        assert written.count("mission_finished") == 1
        assert written.count("answer") == 1
        seqs = [e["seq"] for e in store.since(run_id)]
        assert seqs == list(range(1, len(written) + 1))

    @pytest.mark.parametrize("route", ["direct", "staged"])
    def test_the_opening_frame_names_the_run(self, bus, tmp_path, route):
        from core.runtime.contract import conforms

        store = self.store(tmp_path)
        run_id = store.create().run_id
        sink = Sink()
        getattr(self, route)(bus, sink, store, run_id)
        opening = sink.of("mission_started")[0]
        assert opening["run_id"] == run_id
        assert conforms(opening) == []

    @pytest.mark.parametrize("route", ["direct", "staged"])
    def test_it_records_with_nobody_watching(self, bus, tmp_path, route):
        store = self.store(tmp_path)
        run_id = store.create().run_id
        getattr(self, route)(bus, None, store, run_id)
        assert [r["event"] for r in store.records(run_id)][-1] == \
            "mission_finished"

    def test_a_swarm_with_neither_says_nothing_about_a_run(self, bus):
        sink = Sink()
        plain = ScriptedModel(DIRECT)
        executor = ScriptedModel('{"answer": "ok"}')
        swarm(plain, executor, bus, observer=sink).run("q")
        assert "run_id" not in sink.of("mission_started")[0]

    def test_a_sub_mission_is_not_handed_the_store(self, bus, tmp_path):
        """One writer per run. The sub-runner's records arrive here to be
        renumbered; a store on the sub-runner would log the pre-renumbered
        copy as well."""
        store = self.store(tmp_path)
        run_id = store.create().run_id
        runner = swarm(ScriptedModel(DIRECT), ScriptedModel('{"answer": "ok"}'),
                       bus, run_store=store, run_id=run_id)
        built = runner._runner(system_message="x", max_steps=2)
        assert built._run_store is None and built.run_id == ""

    def test_the_id_is_readable_off_the_runner(self, bus, tmp_path):
        store = self.store(tmp_path)
        run_id = store.create().run_id
        assert swarm(ScriptedModel(), ScriptedModel(), bus,
                     run_store=store, run_id=run_id).run_id == run_id


class TestTheStagedRunIsCheckpointed:
    """The plan and each step's outcome, in the run's metadata, as it goes.

    A checkpoint written when the plan *finishes* is a checkpoint that never
    exists for the run that needed one. So: the plan before the first step
    runs, and each step's verdict the moment it is reached — which is what a
    restart reads instead of replaying the whole log, and what the resume
    door reads to refuse a staged run by name rather than half-continuing it.
    """

    def store(self, tmp_path):
        from core.durable import RunStore
        return RunStore(tmp_path / "runs")

    def staged(self, bus, store, run_id):
        plain = ScriptedModel(
            STAGED, TWO_STEP_PLAN, '{"pass": true}',
            "Final: corpus.abc123 charted in chart.png")
        executor = ScriptedModel(
            tool_call("catalog.search", q="corpus"),
            '{"answer": "found corpus.abc123"}',
            tool_call("run_code", code="plot()"),
            '{"answer": "chart.png written"}')
        return swarm(plain, executor, bus,
                     run_store=store, run_id=run_id).run("find it and chart it")

    def test_the_plan_is_written_before_any_step_of_it_runs(self, bus,
                                                            tmp_path):
        """Asserted with an executor that kills the run: the checkpoint has
        to be there even though no step ever completed."""
        store = self.store(tmp_path)
        run_id = store.create().run_id
        plain = ScriptedModel(STAGED, TWO_STEP_PLAN)

        def dies(messages):
            raise RuntimeError("the model server went away")

        with pytest.raises(RuntimeError):
            swarm(plain, dies, bus, run_store=store,
                  run_id=run_id).run("find it and chart it")
        assert [s["id"] for s in store.meta(run_id).meta["plan"]] == \
            ["s1", "s2"]
        assert store.meta(run_id).meta["steps_done"] == []

    def test_each_step_lands_as_it_finishes(self, bus, tmp_path):
        store = self.store(tmp_path)
        run_id = store.create().run_id
        self.staged(bus, store, run_id)
        assert store.meta(run_id).meta["steps_done"] == [
            {"id": "s1", "outcome": "ok", "summary": "found corpus.abc123"},
            {"id": "s2", "outcome": "ok", "summary": "chart.png written"},
        ]

    def test_a_failed_step_records_why_in_the_same_field(self, bus, tmp_path):
        """One field answering "what came of this step". Two fields only one
        of which is ever populated is two fields to read wrong."""
        store = self.store(tmp_path)
        run_id = store.create().run_id
        plain = ScriptedModel(
            STAGED,
            plan({"id": "s1", "goal": "search", "rung": "tool"},
                 {"id": "s2", "goal": "count", "rung": "code",
                  "needs": ["s1"]}),
            "final answer")
        executor = ScriptedModel(
            '{"answer": "I remember abc123"}',      # no tool call: gate fails
            '{"answer": "still remembering"}')      # and the retry does not
        swarm(plain, executor, bus, run_store=store,
              run_id=run_id).run("search then count")
        done = store.meta(run_id).meta["steps_done"]
        assert done[0]["id"] == "s1"
        assert done[0]["outcome"] == "failed"
        assert "no successful tool call" in done[0]["summary"]

    def test_a_step_stopped_for_a_person_is_checkpointed_too(self, bus,
                                                             tmp_path):
        store = self.store(tmp_path)
        run_id = store.create().run_id
        plain = ScriptedModel(STAGED, TWO_STEP_PLAN)
        executor = ScriptedModel(tool_call("catalog.search", q="corpus"))
        transcript = swarm(plain, executor, bus, gated=["catalog.search"],
                           run_store=store, run_id=run_id).run("find it")
        assert transcript.outcome == AWAITING_APPROVAL
        assert store.meta(run_id).meta["steps_done"] == [
            {"id": "s1", "outcome": AWAITING_APPROVAL,
             "summary": "awaiting a person's decision"}]

    def test_a_redraw_replaces_the_plan_rather_than_appending_to_it(
            self, bus, tmp_path):
        """What is checkpointed has to be the plan the steps arriving next
        belong to — the same reason ``_StageObserver.announce`` is called
        again on a redraw."""
        store = self.store(tmp_path)
        run_id = store.create().run_id
        plain = ScriptedModel(
            STAGED,
            plan({"id": "s1", "goal": "search", "rung": "tool"},
                 {"id": "s2", "goal": "count", "rung": "code",
                  "needs": ["s1"]}),
            plan({"id": "r1", "goal": "search again", "rung": "tool"}),
            "final answer")
        executor = ScriptedModel(
            '{"answer": "no tool"}', '{"answer": "still no tool"}',
            tool_call("catalog.search", q="x"), '{"answer": "found abc123"}')
        swarm(plain, executor, bus, run_store=store,
              run_id=run_id).run("search then count")
        assert [s["id"] for s in store.meta(run_id).meta["plan"]] == ["r1"]

    def test_the_checkpoint_never_rewinds_the_sequence_counter(self, bus,
                                                               tmp_path):
        """``update_meta`` and never ``save``.

        This runner holds no ``Run`` and must not start: saving a record read
        before a step would stamp a ``last_seq`` the step's own records have
        moved on, the next append would reuse numbers a reader had already
        passed, and the transcript would render blank. That is the bug
        ``core.durable`` was written around, and the checkpoint is the one
        caller most likely to reproduce it.
        """
        store = self.store(tmp_path)
        run_id = store.create().run_id
        self.staged(bus, store, run_id)
        seqs = [e["seq"] for e in store.since(run_id)]
        assert seqs == sorted(set(seqs)) == list(range(1, len(seqs) + 1))
        assert store.meta(run_id).last_seq == seqs[-1]

    def test_the_checkpoint_never_calls_save(self, bus):
        """The structural half of the rule above, because the arithmetic half
        cannot see it.

        A ``save`` that re-reads immediately before writing keeps the counter
        right, so a sequence assertion passes over one — and then the next
        author moves the read up to where the plan is drawn, holds the record
        across two sub-missions, and the counter rewinds. ``save`` is a
        method for a caller that is already holding a ``Run``; this runner
        holds none and must never become one that does.
        """
        class Watched:
            def __init__(self):
                self.facts = {}

            def append(self, run_id, record):
                return {"seq": 1}

            def update_meta(self, run_id, **facts):
                self.facts.update(facts)

            def meta(self, run_id):
                raise AssertionError(
                    "the swarm read a Run it would then have to write back")

            def save(self, run):
                raise AssertionError(
                    "the swarm saved a held Run; that is the reused-sequence "
                    "bug core.durable was written around")

        store = Watched()
        plain = ScriptedModel(
            STAGED, TWO_STEP_PLAN, '{"pass": true}', "Final: done")
        executor = ScriptedModel(
            tool_call("catalog.search", q="corpus"),
            '{"answer": "found corpus.abc123"}',
            tool_call("run_code", code="plot()"),
            '{"answer": "chart.png written"}')
        assert swarm(plain, executor, bus, run_store=store,
                     run_id="run_abcd1234").run("find it").completed
        assert [e["id"] for e in store.facts["steps_done"]] == ["s1", "s2"]

    def test_a_direct_route_checkpoints_no_plan_because_it_has_none(
            self, bus, tmp_path):
        """And that absence is what the resume door reads: a run with a
        checkpointed plan is a staged run and is refused; one without is an
        ordinary loop and replays."""
        store = self.store(tmp_path)
        run_id = store.create().run_id
        swarm(ScriptedModel(DIRECT), ScriptedModel('{"answer": "ok"}'),
              bus, run_store=store, run_id=run_id).run("q")
        assert "plan" not in store.meta(run_id).meta

    def test_a_swarm_with_no_store_checkpoints_nothing_and_still_runs(
            self, bus):
        plain = ScriptedModel(
            STAGED, TWO_STEP_PLAN, '{"pass": true}', "Final: done")
        executor = ScriptedModel(
            tool_call("catalog.search", q="corpus"),
            '{"answer": "found corpus.abc123"}',
            tool_call("run_code", code="plot()"),
            '{"answer": "chart.png written"}')
        assert swarm(plain, executor, bus).run("find it").completed

    def test_a_store_that_cannot_write_does_not_fail_the_mission(self, bus):
        """The same promise ``persist_record`` makes. A staged mission must
        not die because the disk it was being indexed on filled up."""
        class Broken:
            def update_meta(self, run_id, **facts):
                raise OSError("no space left on device")

            def append(self, run_id, record):
                return {"seq": 1}

        plain = ScriptedModel(
            STAGED, TWO_STEP_PLAN, '{"pass": true}', "Final: done")
        executor = ScriptedModel(
            tool_call("catalog.search", q="corpus"),
            '{"answer": "found corpus.abc123"}',
            tool_call("run_code", code="plot()"),
            '{"answer": "chart.png written"}')
        assert swarm(plain, executor, bus, run_store=Broken(),
                     run_id="run_abcd1234").run("find it").completed
