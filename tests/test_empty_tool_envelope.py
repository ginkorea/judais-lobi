"""The live catalogue failure: an empty envelope is not a tool argument."""
from copy import deepcopy

import pytest

from core.contracts.schemas import PolicyPack
from core.runtime.mission import MissionRunner
from core.runtime.run import NO_SUPERVISOR
from core.runtime.schema_check import empty_envelope
from core.tools.bus import ToolBus
from core.tools.capability import CapabilityEngine
from core.tools.descriptors import ToolDescriptor
from tests.test_mission import NativeModel, ScriptedModel, answer_call, native_call, native_runner, tool_call

EMPTY = {"type": "object", "properties": {}, "additionalProperties": False}


def run_case(protocol, schema=EMPTY, arguments=None, *, gated=False):
    arguments = {"arguments": {}} if arguments is None else arguments
    calls, events = [], []
    bus = ToolBus(capability_engine=CapabilityEngine(PolicyPack(allowed_scopes=["*"])))
    bus.register(ToolDescriptor(tool_name="catalog.facets", input_schema=schema),
                 lambda **kw: calls.append(kw) or {"types": ["dataset"]})
    options = dict(max_steps=2, supervisor=NO_SUPERVISOR, gate_wait_s=0.01,
                   gated=["catalog.facets"] if gated else [])
    if protocol == "native":
        supplied = native_call("catalog.facets", **arguments)
        original = deepcopy(supplied)
        model = NativeModel(supplied, answer_call("done"))
        result = native_runner(bus, model, tools=("catalog.facets",), events=events,
                               **options).run("What is in the catalogue?")
        assert supplied == original
    else:
        model = ScriptedModel(tool_call("catalog.facets", **arguments), '{"answer":"done"}')
        result = MissionRunner(model, bus, ["catalog.facets"], observer=events.append,
                               store_tool="", **options).run("What is in the catalogue?")
    return calls, events, result


@pytest.mark.parametrize("protocol", ["json", "native"])
def test_empty_protocol_envelope_dispatches_exactly_once(protocol):
    calls, events, result = run_case(protocol)
    assert calls == [{}]
    assert not any(e["event"] == "reply_rejected" for e in events)
    called = [e for e in events if e["event"] == "tool_call"]
    assert len(called) == 1 and called[0]["arguments"] == {}
    assert result.answer == "done"


@pytest.mark.parametrize("protocol", ["json", "native"])
def test_nonempty_unknown_arguments_are_never_discarded(protocol):
    calls, events, _ = run_case(protocol, arguments={"arguments": {"asset_id": "x"}})
    assert not calls
    assert any(e["event"] == "reply_rejected" for e in events)


@pytest.mark.parametrize("protocol", ["json", "native"])
def test_real_arguments_property_is_not_unwrapped(protocol):
    schema = {"type": "object", "properties": {"arguments": {"type": "object"}},
              "required": ["arguments"], "additionalProperties": False}
    calls, _, _ = run_case(protocol, schema=schema)
    assert calls == [{"arguments": {}}]


@pytest.mark.parametrize("protocol", ["json", "native"])
def test_gate_sees_original_proposal_and_no_dispatch(protocol):
    calls, events, _ = run_case(protocol, gated=True)
    assert not calls
    proposal = next(e for e in events if e["event"] == "gate_requested")
    assert proposal["arguments"] == {"arguments": {}}


@pytest.mark.parametrize("protocol", ["json", "native"])
def test_unknown_schema_is_not_rewritten(protocol):
    calls, _, _ = run_case(protocol, schema={})
    assert calls == [{"arguments": {}}]


@pytest.mark.parametrize("schema", [
    None, {}, True,
    {**EMPTY, "additionalProperties": True},
    {**EMPTY, "required": ["asset_id"]},
    {**EMPTY, "allOf": [{"minProperties": 1}]},
    {**EMPTY, "$ref": "#/$defs/other"},
    {**EMPTY, "properties": {"arguments": {"type": "object"}}},
])
def test_repair_requires_the_exact_unambiguous_empty_schema(schema):
    arguments = {"arguments": {}}
    assert empty_envelope(schema, arguments) is arguments


@pytest.mark.parametrize("arguments", [
    {}, {"arguments": None}, {"arguments": []}, {"arguments": "{}"},
    {"arguments": {}, "extra": True}, {"arguments": {"arguments": {}}},
])
def test_repair_never_discards_values_or_recursively_unwraps(arguments):
    assert empty_envelope(EMPTY, arguments) is arguments


def test_schema_and_model_arguments_remain_unchanged():
    schema = deepcopy(EMPTY)
    arguments = {"arguments": {}}
    assert empty_envelope(schema, arguments) == {}
    assert schema == EMPTY and arguments == {"arguments": {}}
