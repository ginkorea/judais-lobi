"""A selected bridged tool is usable under its unambiguous whole-tool name."""
from copy import deepcopy

import pytest

from core.contracts.schemas import PolicyPack
from core.runtime.mission import MissionRunner
from core.runtime.run import NO_SUPERVISOR
from core.tools.bus import ToolBus
from core.tools.capability import CapabilityEngine
from core.tools.descriptors import ToolDescriptor
from tests.test_mission import NativeModel, ScriptedModel, answer_call, native_call, native_runner, tool_call


def execute(protocol, proposed, registered, *, offered=None, gated=()):
    calls, events = [], []
    bus = ToolBus(capability_engine=CapabilityEngine(PolicyPack(allowed_scopes=["*"])))
    for name in registered:
        bus.register(ToolDescriptor(tool_name=name, input_schema={
            "type": "object", "properties": {"code": {"type": "string"}},
            "required": ["code"], "additionalProperties": False}),
            lambda _name=name, **kw: calls.append((_name, kw)) or "executed")
    offered = registered if offered is None else offered
    options = dict(max_steps=2, supervisor=NO_SUPERVISOR, gated=list(gated), gate_wait_s=0.01)
    if protocol == "native":
        supplied = native_call(proposed, code="print(1)")
        original = deepcopy(supplied)
        model = NativeModel(supplied, answer_call("done"))
        result = native_runner(bus, model, tools=offered, events=events, **options).run("test")
        assert supplied == original
    else:
        model = ScriptedModel(tool_call(proposed, code="print(1)"), '{"answer":"done"}')
        result = MissionRunner(model, bus, offered, observer=events.append,
                               store_tool="", **options).run("test")
    return calls, events, result


@pytest.mark.parametrize("protocol", ["json", "native"])
@pytest.mark.parametrize("spelling", ["run_code", "run.code", "mcp.run_code"])
def test_whole_tool_namespace_resolves_once_with_arguments_unchanged(protocol, spelling):
    calls, events, result = execute(protocol, spelling, ["mcp.run_code"])
    assert calls == [("mcp.run_code", {"code": "print(1)"})]
    assert next(e for e in events if e["event"] == "tool_call")["tool"] == "mcp.run_code"
    assert not any(e["event"] == "reply_rejected" for e in events)
    assert result.answer == "done"


@pytest.mark.parametrize("protocol", ["json", "native"])
@pytest.mark.parametrize("proposed,registered,offered", [
    ("Read", ["mcp.stamp_read"], None),
    ("get", ["mcp.runs_get"], None),
    ("other.run_code", ["mcp.run_code"], None),
    ("run_code", ["mcp.run_code", "other.run_code"], None),
    ("run_code", ["mcp.run_code", "mcp.runs_get"], ["mcp.runs_get"]),
])
def test_alias_cannot_guess_or_activate_an_unselected_tool(protocol, proposed, registered, offered):
    calls, events, _ = execute(protocol, proposed, registered, offered=offered)
    assert calls == []
    assert any(e["event"] == "reply_rejected" for e in events)


@pytest.mark.parametrize("protocol", ["json", "native"])
def test_exact_offered_name_wins_over_alias(protocol):
    calls, _, _ = execute(protocol, "run_code", ["run_code", "mcp.run_code"])
    assert calls == [("run_code", {"code": "print(1)"})]


@pytest.mark.parametrize("protocol", ["json", "native"])
def test_gate_is_not_bypassed_or_rewritten(protocol):
    calls, events, _ = execute(protocol, "run_code", ["mcp.run_code"], gated=["mcp.run_code"])
    assert calls == []
    assert any(e["event"] == "reply_rejected" for e in events)
    calls, events, _ = execute(protocol, "mcp.run_code", ["mcp.run_code"], gated=["mcp.run_code"])
    assert calls == []
    proposal = next(e for e in events if e["event"] == "gate_requested")
    assert proposal["tool"] == "mcp.run_code"
    assert proposal["arguments"] == {"code": "print(1)"}
