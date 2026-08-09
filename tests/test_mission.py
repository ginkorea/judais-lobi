# tests/test_mission.py — the loop where the model chooses the tool

import json

import pytest

from core.contracts.schemas import PolicyPack
from core.runtime.mission import MissionRunner, MissionTranscript
from core.tools.bus import ToolBus
from core.tools.capability import CapabilityEngine
from core.tools.descriptors import ToolDescriptor


class ScriptedModel:
    """Replays canned replies and records what it was shown."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.seen = []

    def __call__(self, messages):
        self.seen.append([dict(m) for m in messages])
        return self.replies.pop(0) if self.replies else '{"answer": "done"}'


@pytest.fixture
def bus():
    b = ToolBus(capability_engine=CapabilityEngine(PolicyPack(allowed_scopes=["*"])))
    b.register(
        ToolDescriptor(tool_name="catalog.search", description="Search the catalogue."),
        lambda **kw: (0, f"hits for {kw.get('q')}", ""),
    )
    b.register(
        ToolDescriptor(tool_name="catalog.get", description="Fetch one asset."),
        lambda **kw: (0, f"asset {kw.get('asset_id')}", ""),
    )
    return b


def tool_call(name, **arguments):
    return json.dumps({"tool": name, "arguments": arguments})


class TestSeeding:
    def test_the_catalogue_is_in_the_system_message(self, bus):
        runner = MissionRunner(ScriptedModel(), bus, ["catalog.search", "catalog.get"])
        system = runner.seed("find things")[0]["content"]
        assert "catalog.search: Search the catalogue." in system
        assert "catalog.get: Fetch one asset." in system

    def test_the_objective_is_the_user_turn(self, bus):
        runner = MissionRunner(ScriptedModel(), bus, ["catalog.search"])
        assert runner.seed("find things")[1] == {
            "role": "user", "content": "find things",
        }

    def test_only_the_mission_tools_are_offered(self, bus):
        """A mission gets its tools, not everything the bus happens to hold."""
        runner = MissionRunner(ScriptedModel(), bus, ["catalog.search"])
        system = runner.seed("x")[0]["content"]
        assert "catalog.search" in system
        assert "catalog.get" not in system

    def test_the_personality_leads_the_prompt(self, bus):
        runner = MissionRunner(
            ScriptedModel(), bus, ["catalog.search"], system_message="You are Tai.",
        )
        assert runner.seed("x")[0]["content"].startswith("You are Tai.")

    def test_no_tools_says_so(self):
        empty = ToolBus(capability_engine=CapabilityEngine(PolicyPack(allowed_scopes=["*"])))
        runner = MissionRunner(ScriptedModel(), empty, [])
        assert "(no tools available)" in runner.seed("x")[0]["content"]


class TestTheLoop:
    def test_the_model_chooses_and_the_tool_runs(self, bus):
        model = ScriptedModel(
            tool_call("catalog.search", q="taiwan"),
            '{"answer": "found 3 assets"}',
        )
        transcript = MissionRunner(model, bus, ["catalog.search"]).run("go")

        assert transcript.completed
        assert transcript.answer == "found 3 assets"
        assert transcript.steps[0].tool == "catalog.search"
        assert transcript.steps[0].output == "hits for taiwan"

    def test_the_result_is_fed_back_to_the_model(self, bus):
        model = ScriptedModel(
            tool_call("catalog.search", q="taiwan"), '{"answer": "ok"}',
        )
        MissionRunner(model, bus, ["catalog.search"]).run("go")

        assert "hits for taiwan" in model.seen[-1][-1]["content"]

    def test_several_tools_in_sequence(self, bus):
        model = ScriptedModel(
            tool_call("catalog.search", q="x"),
            tool_call("catalog.get", asset_id="a-1"),
            '{"answer": "a-1"}',
        )
        transcript = MissionRunner(model, bus, ["catalog.search", "catalog.get"]).run("go")

        assert [s.tool for s in transcript.steps] == [
            "catalog.search", "catalog.get", None,
        ]

    def test_an_immediate_answer_needs_no_tool(self, bus):
        transcript = MissionRunner(
            ScriptedModel('{"answer": "nothing to look up"}'), bus, ["catalog.search"],
        ).run("go")
        assert transcript.completed
        assert all(s.tool is None for s in transcript.steps)


class TestRefusals:
    def test_an_invented_tool_is_refused_with_the_real_catalogue(self, bus):
        model = ScriptedModel(tool_call("delete_everything"), '{"answer": "fine"}')
        transcript = MissionRunner(model, bus, ["catalog.search"]).run("go")

        assert "no tool named 'delete_everything'" in transcript.steps[0].error
        assert "catalog.search" in model.seen[-1][-1]["content"]
        assert transcript.completed

    def test_an_invented_tool_never_reaches_the_bus(self, bus):
        calls = []
        bus.dispatch = lambda *a, **k: calls.append(a) or pytest.fail("dispatched")
        MissionRunner(
            ScriptedModel(tool_call("nope"), '{"answer": "x"}'), bus, ["catalog.search"],
        ).run("go")
        assert calls == []

    def test_unparseable_json_is_handed_back(self, bus):
        model = ScriptedModel("I think I will search now!", '{"answer": "ok"}')
        transcript = MissionRunner(model, bus, ["catalog.search"]).run("go")

        assert "not valid JSON" in transcript.steps[0].error
        assert transcript.completed

    def test_a_fenced_reply_is_accepted(self, bus):
        """A code fence is a formatting slip, not a different decision."""
        model = ScriptedModel(
            '```json\n{"tool": "catalog.search", "arguments": {"q": "z"}}\n```',
            '{"answer": "ok"}',
        )
        transcript = MissionRunner(model, bus, ["catalog.search"]).run("go")
        assert transcript.steps[0].output == "hits for z"

    def test_an_object_with_neither_key_is_refused(self, bus):
        model = ScriptedModel('{"thoughts": "hmm"}', '{"answer": "ok"}')
        transcript = MissionRunner(model, bus, ["catalog.search"]).run("go")
        assert '"tool" key or an "answer" key' in transcript.steps[0].error

    def test_non_object_arguments_are_refused(self, bus):
        model = ScriptedModel(
            '{"tool": "catalog.search", "arguments": "taiwan"}', '{"answer": "ok"}',
        )
        transcript = MissionRunner(model, bus, ["catalog.search"]).run("go")
        assert "must be a JSON object" in transcript.steps[0].error

    def test_an_empty_reply_is_refused(self, bus):
        transcript = MissionRunner(
            ScriptedModel("", '{"answer": "ok"}'), bus, ["catalog.search"],
        ).run("go")
        assert "Empty reply" in transcript.steps[0].error

    def test_a_capability_denial_reaches_the_model_as_a_refusal(self):
        gated = ToolBus(
            capability_engine=CapabilityEngine(PolicyPack(allowed_scopes=["fs.read"])),
        )
        gated.register(
            ToolDescriptor(tool_name="privileged", required_scopes=["admin"],
                           description="Needs a scope this mission lacks."),
            lambda **_kw: (0, "should not run", ""),
        )
        model = ScriptedModel(tool_call("privileged"), '{"answer": "denied"}')
        transcript = MissionRunner(model, gated, ["privileged"]).run("go")

        assert transcript.steps[0].refused
        assert "capability_denied" in transcript.steps[0].error
        assert "refused" in model.seen[-1][-1]["content"]


class TestBudget:
    def test_the_step_cap_is_hard(self, bus):
        model = ScriptedModel(*[tool_call("catalog.search", q="x")] * 20)
        transcript = MissionRunner(model, bus, ["catalog.search"], max_steps=3).run("go")

        assert transcript.outcome == "budget_exhausted"
        assert transcript.completed is False
        assert len(transcript.steps) == 3

    def test_exhaustion_is_recorded_not_silent(self, bus):
        transcript = MissionRunner(
            ScriptedModel(*[tool_call("catalog.search", q="x")] * 5),
            bus, ["catalog.search"], max_steps=2,
        ).run("go")
        assert isinstance(transcript, MissionTranscript)
        assert transcript.answer is None
        assert transcript.outcome == "budget_exhausted"
