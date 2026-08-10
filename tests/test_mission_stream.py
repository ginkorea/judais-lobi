"""The mission's streaming account of itself, and the gate that stops it.

Two things a harness on the far end of a pipe needs and neither of which
``run()`` could give it:

**A mission narrates itself while it runs.** ``MissionRunner.run`` returns a
transcript when it is over; a mission on a local model is minutes long, and a
caller with only the return value has nothing to show for any of them. So the
loop takes an observer and :mod:`core.runtime.mission_stream` is the published
vocabulary it speaks — asserted here against the names rather than against the
dataclass fields, because the names are the interface.

**A gated tool is proposed and not called.** The whole value of a gate is that
what a person approves is the bytes that would have run, which means the call
has to be made in full and stopped, never withheld from the catalogue and
guessed at afterwards. These tests hold both halves: nothing dispatches, and
the arguments survive.
"""

from __future__ import annotations

import io
import json

import pytest

from core.runtime import mission_stream as ms
from core.runtime.mission import AWAITING_APPROVAL, MissionRunner


class _Result:
    def __init__(self, stdout="", stderr="", exit_code=0):
        self.stdout, self.stderr, self.exit_code = stdout, stderr, exit_code
        self.evidence = stdout


class _Bus:
    """A bus that records what it was actually asked to run."""

    def __init__(self, answers=None):
        self.calls = []
        self.answers = answers or {}
        self.registered = []

    def describe_tool(self, name):
        return {"description": f"does {name}", "input_schema": {
            "type": "object", "properties": {"q": {"type": "string"}}}}

    def dispatch(self, name, **kwargs):
        self.calls.append((name, kwargs))
        return self.answers.get(name, _Result(stdout=f"{name} said so"))

    def register_tool(self, name, tool):
        self.registered.append(name)
        return name

    def unregister(self, name):
        return None


def _replies(*texts):
    queue = list(texts)

    def chat(messages):
        return queue.pop(0) if queue else json.dumps({"answer": "done"})
    return chat


def _run(replies, *, gated=(), tools=("catalog_search_assets",), max_steps=4):
    seen = []
    bus = _Bus()
    runner = MissionRunner(
        _replies(*replies), bus, list(tools), max_steps=max_steps,
        gated=gated, observer=seen.append, store_tool="",
    )
    transcript = runner.run("what do we hold")
    return transcript, seen, bus


def _kinds(records):
    return [r["event"] for r in records]


def _first(records, kind):
    return next(r for r in records if r["event"] == kind)


class TestTheStreamIsAPublishedVocabulary:
    def test_every_emitted_event_is_a_declared_one(self):
        """A consumer switches on ``event`` exhaustively or it cannot be
        written at all. An undeclared name is a frame somebody's frontend
        silently drops."""
        _, seen, _ = _run([
            json.dumps({"tool": "catalog_search_assets", "arguments": {"q": "x"}}),
            json.dumps({"answer": "three assets"}),
        ])
        assert seen
        for record in seen:
            assert record["event"] in ms.EVENTS, record

    def test_a_mission_says_when_it_starts_and_when_it_is_over(self):
        _, seen, _ = _run([json.dumps({"answer": "nothing to do"})])
        kinds = _kinds(seen)
        assert kinds[0] == ms.MISSION_STARTED
        assert kinds[-1] == ms.MISSION_FINISHED
        assert _first(seen, ms.MISSION_FINISHED)["outcome"] == "answered"

    def test_a_mission_that_raises_still_says_it_is_over(self):
        """A stream that just stops is indistinguishable from an agent that is
        thinking, and a pane showing a spinner forever is the state an analyst
        cannot get out of."""
        seen = []

        def explode(messages):
            raise RuntimeError("the model server went away")

        runner = MissionRunner(explode, _Bus(), ["catalog_search_assets"],
                               observer=seen.append, store_tool="")
        with pytest.raises(RuntimeError):
            runner.run("go")
        assert _kinds(seen)[-1] == ms.MISSION_FINISHED

    def test_the_call_is_announced_before_it_is_made(self):
        """What lets a watcher show what is ABOUT to happen, which is the whole
        basis of a usable approval prompt."""
        _, seen, _ = _run([
            json.dumps({"tool": "catalog_search_assets", "arguments": {"q": "taiwan"}}),
            json.dumps({"answer": "found"}),
        ])
        kinds = _kinds(seen)
        assert kinds.index(ms.TOOL_CALL) < kinds.index(ms.TOOL_RESULT)
        assert _first(seen, ms.TOOL_CALL)["arguments"] == {"q": "taiwan"}

    def test_the_watcher_gets_the_whole_result_not_the_bounded_one(self):
        """The bound exists because the MODEL's context is finite. A pane
        showing an analyst 60% of a governed listing would be inventing a limit
        nobody imposed."""
        bus = _Bus(answers={"catalog_search_assets": _Result(stdout="A" * 5000)})
        seen = []
        runner = MissionRunner(
            _replies(json.dumps({"tool": "catalog_search_assets", "arguments": {}}),
                     json.dumps({"answer": "done"})),
            bus, ["catalog_search_assets"], observer=seen.append,
            max_result_bytes=100, store_tool="")
        runner.run("go")
        result = _first(seen, ms.TOOL_RESULT)
        assert len(result["output"]) == 5000
        assert result["truncated"] is True

    def test_a_rejected_reply_is_reported_rather_than_swallowed(self):
        _, seen, _ = _run([
            "I think I will search the catalogue.",
            json.dumps({"answer": "done"}),
        ])
        rejected = _first(seen, ms.REPLY_REJECTED)
        assert "JSON" in rejected["problem"]

    def test_an_invented_tool_is_reported_with_the_name_it_invented(self):
        _, seen, _ = _run([
            json.dumps({"tool": "catalog_delete_everything", "arguments": {}}),
            json.dumps({"answer": "done"}),
        ])
        rejected = _first(seen, ms.REPLY_REJECTED)
        assert rejected["tool"] == "catalog_delete_everything"

    def test_no_observer_runs_exactly_as_before(self):
        bus = _Bus()
        runner = MissionRunner(
            _replies(json.dumps({"answer": "fine"})), bus,
            ["catalog_search_assets"], store_tool="")
        assert runner.run("go").outcome == "answered"

    def test_an_observer_that_throws_does_not_fail_the_mission(self):
        """A mission must not fail because somebody was watching it."""
        def hostile(record):
            raise ValueError("nope")

        runner = MissionRunner(
            _replies(json.dumps({"answer": "fine"})), _Bus(),
            ["catalog_search_assets"], observer=hostile, store_tool="")
        assert runner.run("go").outcome == "answered"


class TestAGatedToolIsProposedAndNotCalled:
    def test_the_bus_never_sees_it(self):
        transcript, seen, bus = _run(
            [json.dumps({"tool": "compute_cancel_job",
                         "arguments": {"job_id": "job_7f3"}})],
            gated=("compute_cancel_job",),
            tools=("catalog_search_assets", "compute_cancel_job"))
        assert bus.calls == [], "a gated tool was dispatched"
        assert transcript.outcome == AWAITING_APPROVAL

    def test_the_proposed_arguments_survive_verbatim(self):
        """What a person approves has to be the bytes that would run."""
        transcript, seen, _ = _run(
            [json.dumps({"tool": "compute_cancel_job",
                         "arguments": {"job_id": "job_7f3", "why": "wrong pack"}})],
            gated=("compute_cancel_job",),
            tools=("catalog_search_assets", "compute_cancel_job"))
        gate = _first(seen, ms.GATE_REQUESTED)
        assert gate["tool"] == "compute_cancel_job"
        assert gate["arguments"] == {"job_id": "job_7f3", "why": "wrong pack"}
        assert transcript.awaiting["arguments"]["why"] == "wrong pack"

    def test_the_mission_stops_rather_than_working_around_it(self):
        """The model is not handed the refusal to route around. Three more
        replies are queued and none of them is read."""
        transcript, seen, bus = _run(
            [json.dumps({"tool": "compute_cancel_job", "arguments": {}}),
             json.dumps({"tool": "catalog_search_assets", "arguments": {}}),
             json.dumps({"answer": "cancelled it anyway"})],
            gated=("compute_cancel_job",),
            tools=("catalog_search_assets", "compute_cancel_job"))
        assert transcript.answer is None
        assert bus.calls == []
        assert ms.ANSWER not in _kinds(seen)

    def test_a_gated_tool_is_offered_and_marked_not_hidden(self):
        """'There is no tool named X' is FALSE — it exists and this deployment
        serves it. A model told the false version reroutes around a capability
        it has; a model told the true one asks."""
        runner = MissionRunner(_replies(), _Bus(),
                               ["catalog_search_assets", "compute_cancel_job"],
                               gated=("compute_cancel_job",), store_tool="")
        catalogue = runner.catalogue()
        assert "compute_cancel_job" in catalogue
        assert "NEEDS APPROVAL" in catalogue
        # and the ungated one is not decorated
        recon = [l for l in catalogue.splitlines()
                 if l.startswith("- catalog_search_assets")][0]
        assert "NEEDS APPROVAL" not in recon

    def test_there_is_no_parameter_that_answers_a_gate(self):
        """The absence is the control. A flag like this is reached for under
        deadline and is exactly how a gate stops being one."""
        import inspect
        names = set(inspect.signature(MissionRunner.__init__).parameters)
        assert not names & {"approve", "auto_approve", "approve_if",
                            "allow_gated", "default_decision"}


class TestTheGroundingVerdictReachesAWatcher:
    def test_a_repair_turn_is_visible_rather_than_looking_like_a_stall(self):
        """A repair turn is a whole extra round-trip to the model. From
        outside, silence during one is indistinguishable from a hung server."""
        from core.runtime.grounding import GroundingConfig, GroundingValidator

        validator = GroundingValidator.from_config(GroundingConfig.from_mapping(
            {"number_pattern": r"\d+\.\d{2,}", "max_repairs": 1}))
        seen = []
        runner = MissionRunner(
            _replies(json.dumps({"tool": "catalog_search_assets", "arguments": {}}),
                     json.dumps({"answer": "the score is 80.847"}),
                     json.dumps({"answer": "the tools do not support a score"})),
            _Bus(), ["catalog_search_assets"], validator=validator,
            observer=seen.append, store_tool="")
        runner.run("go")
        repairs = [r for r in seen if r["event"] == ms.GROUNDING
                   and r.get("repairing")]
        assert repairs, "the repair turn was silent"
        assert "80.847" in repairs[0]["unsupported"]

    def test_the_caveat_arrives_before_the_answer_it_qualifies(self):
        """A caveat that arrives after the prose can be rendered separately
        from it, which is the failure the marking exists to prevent."""
        from core.runtime.grounding import GroundingConfig, GroundingValidator

        validator = GroundingValidator.from_config(GroundingConfig.from_mapping(
            {"number_pattern": r"\d+\.\d{2,}", "max_repairs": 0}))
        seen = []
        runner = MissionRunner(
            _replies(json.dumps({"answer": "the score is 80.847"})),
            _Bus(), ["catalog_search_assets"], validator=validator,
            observer=seen.append, store_tool="")
        transcript = runner.run("go")
        assert transcript.outcome == "answered_with_caveat"
        kinds = _kinds(seen)
        assert kinds.index(ms.GROUNDING) < kinds.index(ms.ANSWER)
        assert _first(seen, ms.GROUNDING)["caveat"]
        # and the answer that goes out already carries it in its own text
        assert _first(seen, ms.ANSWER)["text"].endswith(
            _first(seen, ms.GROUNDING)["caveat"])

    def test_no_grammar_means_no_grounding_event_rather_than_a_clean_one(self):
        """An absent report and a passing one are different facts."""
        _, seen, _ = _run([json.dumps({"answer": "whatever"})])
        assert ms.GROUNDING not in _kinds(seen)


class TestTheSink:
    def test_one_line_one_event(self):
        stream = io.StringIO()
        sink = ms.NdjsonSink(stream)
        sink({"event": ms.ANSWER, "text": "hello"})
        sink({"event": ms.MISSION_FINISHED, "outcome": "answered"})
        lines = stream.getvalue().strip().splitlines()
        assert [json.loads(l)["event"] for l in lines] == [
            ms.ANSWER, ms.MISSION_FINISHED]

    def test_chinese_text_is_not_escaped_so_a_leak_scan_still_works(self):
        stream = io.StringIO()
        ms.NdjsonSink(stream)({"event": ms.ANSWER, "text": "台湾"})
        assert "台湾" in stream.getvalue()

    def test_a_closed_stream_does_not_raise_into_the_loop(self):
        stream = io.StringIO()
        stream.close()
        ms.NdjsonSink(stream)({"event": ms.ANSWER, "text": "hello"})

    def test_a_non_finite_number_becomes_a_marker_not_a_fact(self):
        """`NaN` is not JSON. A strict reader fails on the whole line and a
        lenient one renders it as a number; neither is what it deserves."""
        stream = io.StringIO()
        ms.NdjsonSink(stream)({"event": ms.TOOL_RESULT, "output": float("nan")})
        assert json.loads(stream.getvalue())["unserializable"] is True

    def test_an_ordinary_object_is_stringified_rather_than_dropped(self):
        """`default=str`: a Path or a dataclass in a payload is still worth
        showing, and losing the whole frame over it is not a trade."""
        from pathlib import Path

        stream = io.StringIO()
        ms.NdjsonSink(stream)({"event": ms.TOOL_RESULT, "output": Path("/tmp/x")})
        assert "/tmp/x" in json.loads(stream.getvalue())["output"]

    def test_no_spec_is_no_sink(self):
        assert ms.open_sink("") is None

    def test_a_path_sink_appends(self, tmp_path):
        target = tmp_path / "events.ndjson"
        sink = ms.open_sink(str(target))
        sink({"event": ms.MISSION_STARTED, "objective": "go"})
        sink.close()
        again = ms.open_sink(str(target))
        again({"event": ms.MISSION_FINISHED, "outcome": "answered"})
        again.close()
        assert len(target.read_text().strip().splitlines()) == 2

    def test_a_bad_fd_spec_says_so(self):
        with pytest.raises(ValueError, match="needs a number"):
            ms.open_sink("fd:stdout")
