"""Long answers continue as text; work already executed is never replayed."""

import json
from dataclasses import replace
from threading import Event
from types import SimpleNamespace

import pytest

from core.contracts.schemas import PolicyPack
from core.budgets import Deadline
from core.runtime.backends.base import Usage
from core.runtime.completion import AnswerContinuation, answer_fragment
from core.runtime.context_window import ContextConfig, MissionWindow
from core.runtime.run import Bounds, Model, NO_SUPERVISOR, Observer, Personality, Run, Store, ToolPlane
from core.tools.bus import ToolBus
from core.tools.capability import CapabilityEngine
from core.tools.descriptors import ToolDescriptor


@pytest.mark.parametrize("wire,expected", [
    ('{"answer":"First section', "First section"),
    ('{"answer":"First\\nsection', "First\nsection"),
    ('{"answer":"讀到這裡', "讀到這裡"),
    ('{"answer":"Done\\u12', "Done"),
    ('{"answer":"Done\\', "Done"),
    ('{"answer":"One\\"quoted\\"', 'One"quoted"'),
    ('{"answer":"Complete", "other":', "Complete"),
    ('{"tool":"delete", "arguments":', None),
    ('[ {"title": "unfinished', None),
    (' plain prose ', " plain prose "),
    ('```json\n{"answer":"First section. ', "First section. "),
    ('final {"answer":"First section. ', "First section. "),
    ('{"answer":"Done\\ud83d', "Done"),
    ('{"answer":"Done\\ud83d\\ude', "Done"),
    ('{"answer":"Done\\ud83d\\ude00', "Done😀"),
])
def test_only_answer_text_is_salvaged(wire, expected):
    assert answer_fragment(wire, []) == expected


def test_native_partial_answer_arguments_are_text_not_a_dispatch():
    call = {"name": "mission_answer", "arguments": {}, "raw": '{"text":"Section 1'}
    assert answer_fragment("", [call]) == "Section 1"
    assert answer_fragment("", [{**call, "name": "write_file"}]) is None


def test_duplicate_prefix_is_not_appended_twice():
    pending = AnswerContinuation()
    assert pending.append("First section. ")
    assert pending.append("First section. Second section.")
    assert pending.text == "First section. Second section."
    assert not pending.append("Second section.")


def runner(replies, *, protocol="json", steps=8, streaming=False):
    events, requests, executions = [], [], []
    usage = None
    calls = []
    script = iter(replies)

    def ask(messages):
        nonlocal usage, calls
        requests.append([dict(row) for row in messages])
        item = next(script)
        if isinstance(item, Exception):
            raise item
        reply, finish, calls = item
        usage = Usage(100, 20, 120, finish_reason=finish)
        if streaming:
            return iter([SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(
                content=reply[pos:pos + 7], tool_calls=None))]) for pos in range(0, len(reply), 7)])
        return reply

    bus = ToolBus(capability_engine=CapabilityEngine(PolicyPack(allowed_scopes=["*"])))
    bus.register(ToolDescriptor(tool_name="make_chart", description="Create a chart."),
                 lambda **kw: (executions.append(kw) or 0, "Chart saved.", ""))
    run = Run(Personality(), ToolPlane(bus=bus, offered=["make_chart"]),
              Bounds(max_steps=steps, supervisor=NO_SUPERVISOR), Store(), Observer(events.append),
              Model(ask=ask, protocol=protocol, usage_fn=lambda: usage,
                    tool_calls_fn=lambda: calls,
                    window=MissionWindow(config=ContextConfig(max_context_tokens=32768, max_output_tokens=8192))))
    return run, events, requests, executions


@pytest.mark.parametrize("protocol", ["json", "native"])
def test_two_fragments_form_one_answer_and_are_counted_once(protocol):
    run, events, requests, _ = runner([
        ('{"answer":"Section 1. ', "length", []),
        ('{"answer":"Section 2."}', None, []),
    ], protocol=protocol)
    result = run.run("Explain both sections.")
    assert result.answer == "Section 1. Section 2."
    assert result.outcome == "answered"
    assert result.usage.total == 240
    assert len(requests) == 2
    assert "Do not call tools" in requests[1][-1]["content"]
    answers = [r for r in events if r["event"] == "answer"]
    assert len(answers) == 1
    assert not answers[0]["text"].startswith('{"answer"')


def test_plain_prose_preserves_whitespace_at_the_boundary():
    run, _, _, _ = runner([("Part one. ", "length", []), ("Part two.", None, [])])
    assert run.run("Explain").answer == "Part one. Part two."


def test_native_answer_envelope_can_continue_after_partial_arguments():
    run, _, _, _ = runner([
        ("", "length", [{"id": "a", "name": "mission_answer", "arguments": "invalid",
                          "arguments_raw": '{"text":"Part one. '}]),
        ("", None, [{"id": "b", "name": "mission_answer", "arguments": {"text": "Part two."}}]),
    ], protocol="native")
    result = run.run("Explain")
    assert result.outcome == "answered"
    assert result.answer == "Part one. Part two."


def test_recovery_exhaustion_keeps_partial_text_instead_of_json():
    run, events, requests, _ = runner([
        ('{"answer":"A. ', "length", []),
        ('{"answer":"B. ', "length", []),
        ('{"answer":"C. ', "length", []),
    ])
    result = run.run("Explain")
    assert len(requests) == 3
    assert result.outcome == "incomplete"
    assert result.answer == "A. B. C. "
    assert result.delivered_draft
    assert next(r for r in events if r["event"] == "answer")["draft"] is True


def test_step_budget_keeps_the_partial_answer():
    run, _, requests, _ = runner([('{"answer":"One useful section', "length", [])], steps=1)
    result = run.run("Explain")
    assert len(requests) == 1
    assert result.outcome == "budget_exhausted"
    assert result.answer == "One useful section"


def test_a_repeated_fragment_stops_without_erasing_it():
    run, _, requests, _ = runner([
        ('{"answer":"Section one', "length", []),
        ('{"answer":"Section one"}', None, []),
    ])
    result = run.run("Explain")
    assert result.outcome == "incomplete"
    assert result.answer == "Section one"
    assert len(requests) == 2


@pytest.mark.parametrize("protocol", ["json", "native"])
def test_continuation_does_not_replay_a_completed_tool(protocol):
    call = {"id": "chart", "name": "make_chart", "arguments": {}}
    run, _, requests, executions = runner([
        (json.dumps({"tool": "make_chart", "arguments": {}}), None, [call] if protocol == "native" else []),
        ('{"answer":"The chart shows ', "length", []),
        (json.dumps({"tool": "make_chart", "arguments": {}}), None, [call] if protocol == "native" else []),
    ], protocol=protocol)
    result = run.run("Create and explain a chart.")
    assert len(executions) == 1
    assert len(requests) == 3
    assert result.outcome == "incomplete"
    assert result.answer == "The chart shows "


def test_backend_failure_during_continuation_keeps_text_not_exception_details():
    run, events, _, _ = runner([
        ('{"answer":"Useful finding', "length", []), RuntimeError("private-url")])
    result = run.run("Explain")
    assert result.outcome == "incomplete"
    assert result.answer == "Useful finding"
    assert "private-url" not in str(events)


def test_truncated_action_is_never_invented_or_run():
    run, _, _, executions = runner([('{"tool":"make_chart","arguments":', "length", [])])
    result = run.run("Create a chart")
    assert executions == []
    assert result.outcome == "incomplete"
    assert result.answer is None


@pytest.mark.parametrize("finish", [None, "length"])
def test_empty_continuation_keeps_partial_work_without_retry_loop(finish):
    run, _, requests, _ = runner([('{"answer":"Useful text', "length", []), ("", finish, [])])
    result = run.run("Explain")
    assert result.answer == "Useful text"
    assert result.outcome == "incomplete"
    assert len(requests) == 2
    assert len(result.steps) == 2


def test_cancellation_stops_continuation_without_delivering_a_draft():
    run, events, requests, _ = runner([('{"answer":"Partial', "length", [])])
    cancel = Event()
    run.bounds = replace(run.bounds, cancel=cancel)

    def observe(event):
        events.append(event)
        if event["event"] == "reply_rejected":
            cancel.set()

    run.observer = Observer(observe)
    result = run.run("Explain")
    assert len(requests) == 1
    assert result.answer is None
    assert not result.delivered_draft
    assert result.draft == "Partial"


def test_deadline_stops_continuation_and_retains_partial_work():
    run, events, requests, _ = runner([('{"answer":"Partial', "length", [])])
    clock = [0.0]
    run.bounds = replace(run.bounds, deadline=Deadline(10, monotonic=lambda: clock[0]))

    def observe(event):
        events.append(event)
        if event["event"] == "reply_rejected":
            clock[0] = 11.0

    run.observer = Observer(observe)
    result = run.run("Explain")
    assert len(requests) == 1
    assert result.answer == "Partial"
    assert result.outcome == "budget_exhausted"
    assert result.budget.which == "seconds"


def test_completed_continuation_still_passes_through_grounding():
    from core.runtime.grounding import GroundingConfig, GroundingValidator

    run, _, _, _ = runner([('{"answer":"The unsupported total is ', "length", []),
                            ('{"answer":"987654."}', None, [])])
    run.personality = replace(run.personality, grounding=GroundingValidator.from_config(
        GroundingConfig(number_pattern=r"\d+", max_repairs=0)))
    result = run.run("Explain")
    assert result.grounding is not None
    assert not result.grounding.grounded
    assert result.outcome == "answered_with_caveat"


def test_streamed_fragments_end_in_one_complete_authoritative_answer():
    run, events, _, _ = runner([('{"answer":"First section. ', "length", []),
                                ('{"answer":"Second section."}', None, [])], streaming=True)
    result = run.run("Explain")
    assert result.answer == "First section. Second section."
    assert any(e["event"] == "answer_delta" for e in events)
    answers = [e for e in events if e["event"] == "answer"]
    assert [e["text"] for e in answers] == [result.answer]
    assert result.usage.calls == 2


def test_replaying_a_continuation_has_no_prompt_drift_or_double_billing():
    from core.runtime.replay import ReplayModel

    script = [('{"answer":"First section. ', "length", []),
              ('{"answer":"Second section."}', None, [])]
    live, _, requests, _ = runner(script)
    original = live.run("Explain")
    rows = [{"call": index + 1, "at": "2026-09-19T00:00:00+00:00", "kind": "mission",
             "request": {"messages": request, "extra": {}},
             "reply": {"content": reply, "tool_calls": calls,
                       "usage": Usage(100, 20, 120, finish_reason=finish).as_record()}}
            for index, (request, (reply, finish, calls)) in enumerate(zip(requests, script, strict=True))]
    replay = ReplayModel(rows)
    again, _, _, _ = runner([])
    again.model.ask = replay.serving("mission")
    again.model.usage_fn = lambda: replay.last_usage
    again.model.tool_calls_fn = lambda: replay.last_tool_calls
    result = again.run("Explain")
    assert result.answer == original.answer
    assert result.usage.calls == original.usage.calls == 2
    assert result.usage.total == original.usage.total == 240
    assert replay.as_record()["first"] is None
