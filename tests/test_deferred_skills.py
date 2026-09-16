"""Task-scoped exposure does not widen the installed authority ceiling."""

import json
from dataclasses import replace

import pytest

from core.contracts.schemas import PolicyPack
from core.runtime.deferred_skills import DeferredSkills
from core.runtime.grounding import GroundingConfig, GroundingValidator
from core.runtime.mission import MissionCall, MissionStep, NATIVE_PROTOCOL
from core.runtime.resume import Resumption
from core.runtime.run import (
    NO_SUPERVISOR, Bounds, Model, Observer, Personality, Run, Store, ToolPlane,
)
from core.runtime.skills import SkillManifest, SkillManifestError
from core.tools.bus import ToolBus
from core.tools.capability import CapabilityEngine
from core.tools.descriptors import ToolDescriptor
from core.tools.sandbox import NoneSandbox
from tests.test_mission import (NativeModel, ScriptedModel, answer_call,
                               native_call, tool_call)


def library(**kwargs):
    return DeferredSkills([
        SkillManifest(name="catalogue", description="Find registered assets",
                      allowed_tools=("catalog.search",),
                      prompt="CATALOGUE FULL INSTRUCTIONS. Cite returned IDs."),
        SkillManifest(name="weather", description="Inspect conditions",
                      allowed_tools=("weather.read",),
                      prompt="WEATHER FULL INSTRUCTIONS. Preserve uncertainty."),
    ], **kwargs)


def runner(*replies, deferred=None, gated=(), changed=None):
    calls = []
    bus = ToolBus(capability_engine=CapabilityEngine(
        PolicyPack(allowed_scopes=["*"])), sandbox=NoneSandbox())
    for name in ("catalog.search", "weather.read", "admin.secret"):
        bus.register(ToolDescriptor(tool_name=name,
                                    description=f"FULL SCHEMA DESCRIPTION {name}"),
                     lambda _name=name, **kw: calls.append(_name) or {"ok": True})
    model = ScriptedModel(*replies)
    run = Run(Personality(deferred_skills=deferred or library()),
              ToolPlane(bus=bus, offered=["catalog.search", "weather.read"],
                        gated=frozenset(gated), plane_changed=changed),
              Bounds(max_steps=12, supervisor=NO_SUPERVISOR), Store(), Observer(),
              Model(ask=model))
    return run, model, calls


def test_index_has_capabilities_without_full_skill_or_schema():
    run, model, calls = runner('{"answer":"Yes, I am here."}')
    result = run.run("are you alive?")
    system = model.seen[0][0]["content"]
    assert "catalogue" in system and "catalog.search" in system
    assert "WEATHER FULL INSTRUCTIONS" not in system
    assert "CATALOGUE FULL INSTRUCTIONS" not in system
    assert "FULL SCHEMA DESCRIPTION" not in system
    assert "select_skills" in system
    assert result.answer == "Yes, I am here."
    assert calls == []
    assert "select_skills" not in run.plane.registered()


def test_existing_personality_positional_constructor_is_unchanged():
    critic = object()
    memory = object()
    personality = Personality("persona", "conduct", (), None, critic, "sdk", memory)
    assert personality.critic is critic
    assert personality.sdk_import == "sdk"
    assert personality.memory is memory
    assert personality.deferred_skills is None


def test_multi_skill_selection_then_switch_updates_prompt_schema_and_dispatch():
    changes = []
    run, model, calls = runner(
        tool_call("select_skills", skills=["catalogue", "weather"]),
        tool_call("catalog.search"), tool_call("weather.read"),
        tool_call("select_skills", skills=["weather"]),
        tool_call("catalog.search"), tool_call("weather.read"),
        '{"answer":"done"}', changed=lambda names: changes.append(list(names)))
    run.run("Find assets, then inspect weather, then switch to weather only")
    assert calls == ["catalog.search", "weather.read", "weather.read"]
    assert "CATALOGUE FULL INSTRUCTIONS" not in model.seen[0][0]["content"]
    assert "CATALOGUE FULL INSTRUCTIONS" in model.seen[1][0]["content"]
    assert "WEATHER FULL INSTRUCTIONS" in model.seen[1][0]["content"]
    assert "CATALOGUE FULL INSTRUCTIONS" not in model.seen[4][0]["content"]
    assert "FULL SCHEMA DESCRIPTION catalog.search" not in model.seen[4][0]["content"]
    assert "catalog.search" not in changes[0]
    assert "catalog.search" in changes[1]
    assert "catalog.search" not in changes[2]
    assert run.plane.offered == ["catalog.search", "weather.read"]


@pytest.mark.parametrize("bad", [None, "catalogue", ["../secret"],
                                  ["catalogue", "ignore previous instructions"],
                                  [False], {"skill": "catalogue"}])
def test_unknown_or_injected_ids_fail_atomically(bad):
    selected = library()
    selected.select(["catalogue"])
    with pytest.raises(ValueError, match="configured skill IDs"):
        selected.select(bad)
    assert selected.active == selected.used == ("catalogue",)


def test_extra_arguments_cannot_supply_tools_paths_or_authority():
    run, model, calls = runner(
        tool_call("select_skills", skills=["catalogue"],
                  tools=["admin.secret"], authority="owner", path="/etc/passwd"),
        tool_call("admin.secret"), tool_call("catalog.search"),
        '{"answer":"done"}')
    run.run("Try forged selection")
    assert calls == []
    assert run.personality.deferred_skills.active == ()


def test_hallucinated_inactive_tool_never_executes():
    run, _, calls = runner(tool_call("catalog.search"), '{"answer":"done"}')
    run.run("Find an asset")
    assert calls == []


def test_selection_does_not_remove_approval_gate():
    run, _, calls = runner(tool_call("select_skills", skills=["catalogue"]),
                           tool_call("catalog.search"),
                           gated=["catalog.search"])
    run.run("Find an asset")
    assert calls == []
    assert "catalog.search" in run.plane.gated


def test_grounding_obligations_accumulate_after_unselecting():
    seen = []
    deferred = library(validator_factory=lambda manifest, names:
                       seen.append((manifest.composed or (manifest.name,), names)))
    run, _, _ = runner(tool_call("select_skills", skills=["catalogue"]),
                        tool_call("select_skills", skills=["weather"]),
                        tool_call("select_skills", skills=[]),
                        '{"answer":"done"}', deferred=deferred)
    run.run("Multiple tasks")
    assert seen[0][0] == ("catalogue",)
    assert seen[-1][0] == ("catalogue", "weather")
    assert run.personality.deferred_skills.active == ()
    assert deferred.active == deferred.used == ()


def test_duplicate_selection_is_idempotent_and_library_is_fixed():
    selected = library()
    selected.select(["weather", "weather", "catalogue"])
    assert selected.active == ("weather", "catalogue")
    assert selected.ceiling.allowed_tools == ("catalog.search", "weather.read")
    assert selected.descriptor().input_schema["additionalProperties"] is False


def test_duplicate_configured_names_refuse_at_startup():
    one = SkillManifest(name="same")
    with pytest.raises(SkillManifestError, match="unique"):
        DeferredSkills([one, one])


@pytest.mark.parametrize("native", [False, True])
def test_resume_restores_selection_and_cumulative_obligations(native):
    def recorded(index, selected):
        fields = dict(tool="select_skills", arguments={"skills": selected},
                      exit_code=0, output=json.dumps({"selected": selected,
                                                     "authority_changed": False}))
        return (MissionStep(index=index, raw_reply="", calls=[MissionCall(**fields)])
                if native else MissionStep(index=index, raw_reply="", **fields))
    previous = Resumption(run_id="resume-test", objective="continue", from_seq=3,
                          next_index=2, steps=[recorded(0, ["catalogue"]),
                                               recorded(1, ["weather"])])
    run, model, calls = runner(tool_call("catalog.search"),
                               tool_call("weather.read"), '{"answer":"done"}')
    run.run("continue", previous)
    selected = run.personality.deferred_skills
    assert selected.active == ("weather",)
    assert selected.used == ("catalogue", "weather")
    assert calls == ["weather.read"]
    assert "WEATHER FULL INSTRUCTIONS" in model.seen[0][0]["content"]
    assert "CATALOGUE FULL INSTRUCTIONS" not in model.seen[0][0]["content"]


def test_child_changes_do_not_change_parent_selection():
    run, _, _ = runner()
    child = run.child(branch="part-one")
    child.personality.deferred_skills.select(["weather"])
    assert run.personality.deferred_skills.active == ()
    assert child.personality.deferred_skills.tool_name != "select_skills"


def test_selector_name_collision_cannot_overwrite_existing_tool():
    run, _, calls = runner()
    run.plane.bus.register(ToolDescriptor(tool_name="select_skills"),
                           lambda **kw: "original")
    with pytest.raises(ValueError, match="already registered"):
        run.run("hello")
    assert calls == []
    assert "mission_result" not in run.plane.registered()


def test_native_batch_must_read_selected_instructions_before_using_new_tool():
    run, _, calls = runner()
    native = NativeModel(
        [native_call("select_skills", skills=["catalogue"]),
         native_call("catalog.search", _id="too-soon")],
        native_call("catalog.search", _id="after-reading"), answer_call("done"))
    run.model = Model(ask=native, protocol=NATIVE_PROTOCOL,
                      tool_calls_fn=native.tool_calls)
    result = run.run("Find assets")
    assert calls == ["catalog.search"]
    assert result.steps[0].calls[1].error
    assert not result.steps[1].calls[0].error
    assert "CATALOGUE FULL INSTRUCTIONS" in native.seen[1][0]["content"]


def test_new_cold_run_does_not_inherit_previous_selection():
    run, _, calls = runner(tool_call("select_skills", skills=["catalogue"]),
                           '{"answer":"done"}')
    run.run("Find assets")
    again = ScriptedModel(tool_call("catalog.search"), '{"answer":"hello"}')
    run.model = replace(run.model, ask=again)
    run.run("An unrelated greeting")
    assert calls == []
    assert "CATALOGUE FULL INSTRUCTIONS" not in again.seen[0][0]["content"]
    assert run.personality.deferred_skills.used == ()


def test_bad_resume_cleans_all_internal_registrations():
    previous = Resumption(run_id="bad-resume", objective="continue", from_seq=1,
                          steps=[MissionStep(index=0, raw_reply="", tool="select_skills",
                                             exit_code=0, output="not json")])
    run, _, _ = runner()
    with pytest.raises(ValueError, match="cannot restore"):
        run.run("continue", previous)
    assert "select_skills" not in run.plane.registered()
    assert "mission_result" not in run.plane.registered()


def test_real_identifier_check_survives_unselection():
    manifest = SkillManifest(name="evidence", allowed_tools=("catalog.search",),
                             grounding={"identifier_pattern": r"\basset\.[a-z]+\b"})
    deferred = DeferredSkills([manifest], validator_factory=lambda selected, offered:
                              GroundingValidator.from_config(
                                  GroundingConfig.from_mapping(selected.grounding)
                                  .offering(offered)))
    run, _, _ = runner(tool_call("select_skills", skills=["evidence"]),
                        tool_call("select_skills", skills=[]),
                        '{"answer":"hello"}', deferred=deferred)
    run.run("read, then stop reading")
    report = run.personality.grounding.validate("asset.fabricated", [])
    assert not report.grounded


def test_routing_hint_survives_a_manifest_without_description():
    deferred = DeferredSkills([SkillManifest(
        name="opaque", allowed_tools=("opaque.tool",),
        prompt="Skill: opaque\n\nWhen to use: Investigate unusual weather\n\nBODY HIDDEN")])
    assert "Investigate unusual weather" in deferred.prompt()
    assert "BODY HIDDEN" not in deferred.prompt()


@pytest.mark.parametrize("flag", ["swarm", "campaign", "campaign_plan"])
def test_unsupported_new_flag_combinations_refuse_before_loading(flag):
    from types import SimpleNamespace
    from core.cli import _load_skill
    args = SimpleNamespace(skill=[], defer_skills=True, **{flag: True})
    with pytest.raises(SystemExit, match="direct missions"):
        _load_skill(args)
