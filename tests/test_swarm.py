# tests/test_swarm.py — staged decomposition over one mission backend

import json

import pytest

from core.contracts.schemas import PolicyPack
from core.runtime.mission import AWAITING_APPROVAL
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


class Sink:
    def __init__(self):
        self.records = []

    def __call__(self, record):
        self.records.append(dict(record))

    def of(self, event):
        return [r for r in self.records if r.get("event") == event]


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

    def test_a_bad_rung_is_reprompted_with_the_problem_named(self, bus):
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
        transcript = swarm(plain, executor, bus).run("search then count")
        assert transcript.completed
        repair = plain.seen[2][-1]["content"]
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

    def test_the_plan_rides_on_mission_started_for_a_watcher(self, bus, calls):
        sink = Sink()
        self.run_it(bus, calls, sink=sink)
        started = sink.of("mission_started")[0]
        assert [s["id"] for s in started["plan"]] == ["s1", "s2"]


class TestRungSdk:
    def test_a_code_sdk_step_is_told_to_import_taipan(self, bus):
        plain = ScriptedModel(
            STAGED,
            plan({"id": "s1", "goal": "fetch run numbers and plot them",
                  "rung": "code+sdk"},
                 {"id": "s2", "goal": "report", "rung": "tool",
                  "needs": ["s1"]}),
            "final")
        executor = ScriptedModel(
            tool_call("run_code", code="import taipan"),
            '{"answer": "plotted"}',
            tool_call("catalog.search", q="x"),
            '{"answer": "reported"}')
        swarm(plain, executor, bus).run("plot a run")
        step1 = executor.seen[0][-1]["content"]
        assert "import taipan" in step1
        assert "credential is already in the execution environment" in step1


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
