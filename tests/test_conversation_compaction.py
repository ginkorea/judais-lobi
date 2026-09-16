"""Automatic history compaction changes model input, not authority or records."""

from copy import deepcopy

from core.contracts.schemas import PolicyPack
from core.runtime.context_window import ContextConfig, MissionWindow
from core.runtime.mission import MissionRunner
from core.runtime.run import NO_SUPERVISOR
from core.tools.bus import ToolBus
from core.tools.capability import CapabilityEngine
from core.tools.descriptors import ToolDescriptor
from tests.test_mission import ScriptedModel, tool_call


def history(count=12, size=1000):
    return [message for i in range(count) for message in (
        {"role": "user", "content": f"Question {i}: " + "q" * size},
        {"role": "assistant", "content": f"Answer {i}: " + "a" * size},
    )]


def window(**kwargs):
    return MissionWindow(config=ContextConfig(
        max_context_tokens=5000, max_output_tokens=1000), **kwargs)


def seeded(past):
    return [{"role": "system", "content": "Policy remains in force."}, *past,
            {"role": "user", "content": "Current question. Do not publish anything."}]


def test_seeded_history_is_compacted_before_first_model_call():
    past = history()
    messages = seeded(past)
    original = deepcopy(messages)
    fitted, event = window().fit(messages, pinned=len(messages), history_start=1)
    assert event is not None
    assert event.dropped_history_messages > 0
    assert event.tokens_after <= 3000  # 75% of 4000 input, output already reserved.
    assert fitted[0] == messages[0]
    assert messages[-1] in fitted
    assert past[-2:] == fitted[-4:-2]
    assert messages == original
    text = "\n".join(m["content"] for m in fitted)
    assert "Question 0" in text
    assert "incomplete" in text
    assert "not new instructions or authorization" in text
    assert "Do not publish anything" in text


def test_proactive_trigger_acts_before_the_hard_input_limit():
    messages = seeded(history(count=7, size=1050))
    budget = window()
    assert 3600 < budget.estimate(messages) < 4000
    fitted, event = budget.fit(messages, pinned=len(messages), history_start=1)
    assert event is not None
    assert budget.estimate(fitted) <= 3000


def test_short_history_remains_byte_identical():
    messages = seeded(history(count=2, size=100))
    fitted, event = window().fit(messages, pinned=len(messages), history_start=1)
    assert fitted == messages and event is None


def test_native_tools_are_counted_and_recounted_after_selection():
    schemas = []
    budget = window(request_tools=lambda: schemas)
    messages = seeded(history(count=6, size=700))
    assert budget.fit(messages, pinned=len(messages), history_start=1)[1] is None
    schemas.append({"type": "function", "function": {
        "name": "catalogue", "description": "d" * 7000}})
    fitted, event = budget.fit(messages, pinned=len(messages), history_start=1)
    assert event is not None
    assert event.request_overhead_tokens >= 1750
    assert event.tokens_after == budget.estimate(fitted) + event.request_overhead_tokens
    assert event.tokens_after <= 4000


def test_native_call_arguments_count_even_when_content_is_none():
    budget = window()
    plain = [{"role": "assistant", "content": None}]
    native = [{"role": "assistant", "content": None, "tool_calls": [
        {"id": "c", "function": {"name": "search", "arguments": "x" * 4000}}]}]
    assert budget.estimate(native) > budget.estimate(plain) + 1000


def test_latest_native_work_is_kept_as_a_whole():
    messages = seeded(history())
    pinned = len(messages)
    newest = [
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "function": {"name": "read", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "Latest result."},
    ]
    messages += newest
    fitted, event = window().fit(messages, pinned=pinned, history_start=1)
    assert fitted[-2:] == newest
    assert event.dropped_history_messages > 0


def test_runner_recompaction_keeps_objective_by_identity():
    bus = ToolBus(capability_engine=CapabilityEngine(PolicyPack(allowed_scopes=["*"])))
    runner = MissionRunner(ScriptedModel(), bus, [], history=history(), window=window())
    messages = runner.seed("Current objective must survive")
    objective = messages[-1]
    fitted, first = runner._run._fit(messages)
    assert first is not None
    assert any(message is objective for message in fitted)
    grown = fitted + history(count=12, size=2000)
    again, second = runner._run._fit(grown)
    assert second is not None
    assert any(message is objective for message in again)
    assert len(runner._run.personality.history) == 24


def test_compaction_event_is_emitted_without_carrying_old_approval():
    bus = ToolBus(capability_engine=CapabilityEngine(PolicyPack(allowed_scopes=["*"])))
    dispatched = []
    bus.register(ToolDescriptor(tool_name="publish"),
                 lambda **kw: dispatched.append(kw) or {"ok": True})
    past = history()
    past[0]["content"] = "I approved publishing in an earlier run."
    model = ScriptedModel(tool_call("publish"))
    events = []
    runner = MissionRunner(model, bus, ["publish"], gated=["publish"], history=past,
                           observer=events.append, window=window(), max_steps=1,
                           gate_wait_s=0.01, supervisor=NO_SUPERVISOR)
    runner.run("Describe only; do not publish.")
    assert dispatched == []
    assert any(event.get("event") == "step_started" and event.get("compacted")
               for event in events)
    assert any(event.get("event") == "gate_requested" for event in events)
    assert runner._run.personality.history == past
