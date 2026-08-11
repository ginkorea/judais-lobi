# tests/test_mission.py — the loop where the model chooses the tool

import json

import pytest

from core.contracts.schemas import PolicyPack
from core.runtime.grounding import GroundingConfig, GroundingValidator
from core.runtime.mission import MissionRunner, MissionTranscript
from core.runtime.results import RESULT_TOOL
from core.runtime.skills import SkillManifest
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


# ---------------------------------------------------------------------------
# Argument schemas in the catalogue
# ---------------------------------------------------------------------------

SEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "q": {"type": "string"},
        "type": {"type": "string", "enum": ["dataset", "model", "service"]},
        "limit": {"type": "integer"},
        "owner": {"anyOf": [{"type": "string"}, {"type": "null"}]},
    },
    "required": ["q"],
}


@pytest.fixture
def typed_bus():
    b = ToolBus(capability_engine=CapabilityEngine(PolicyPack(allowed_scopes=["*"])))
    b.register(
        ToolDescriptor(
            tool_name="catalog.search",
            description="Search the catalogue by facet.",
            input_schema=SEARCH_SCHEMA,
        ),
        lambda **kw: (0, f"hits for {kw.get('q')}", ""),
    )
    return b


class TestTheCatalogueCarriesTypes:
    def test_types_and_required_reach_the_prompt(self, typed_bus):
        system = MissionRunner(
            ScriptedModel(), typed_bus, ["catalog.search"],
        ).seed("x")[0]["content"]
        assert "q (string, required)" in system
        assert "limit (integer)" in system

    def test_an_enum_is_spelled_out(self, typed_bus):
        """Naming the facet values is the difference between a first
        call that works and three refused ones discovering that `type`
        is not free text."""
        system = MissionRunner(
            ScriptedModel(), typed_bus, ["catalog.search"],
        ).seed("x")[0]["content"]
        assert "type (string: dataset|model|service)" in system

    def test_an_optional_argument_still_shows_its_type(self, typed_bus):
        system = MissionRunner(
            ScriptedModel(), typed_bus, ["catalog.search"],
        ).seed("x")[0]["content"]
        assert "owner (string)" in system

    def test_a_tool_without_a_schema_renders_as_before(self, bus):
        system = MissionRunner(
            ScriptedModel(), bus, ["catalog.search"],
        ).seed("x")[0]["content"]
        assert "- catalog.search: Search the catalogue." in system
        assert "arguments:" not in system


# ---------------------------------------------------------------------------
# Bounded results, and the store that keeps the rest
# ---------------------------------------------------------------------------

@pytest.fixture
def big_bus():
    b = ToolBus(capability_engine=CapabilityEngine(PolicyPack(allowed_scopes=["*"])))
    b.register(
        ToolDescriptor(tool_name="runs.get", description="Read a run view."),
        lambda **_kw: (
            0,
            "HEAD" + ("x" * 5_000) + "TAIL",
            "",
            json.dumps({"run_id": "run.5f21", "totals": {"records": 12481}}),
        ),
    )
    return b


class TestBoundedToolOutput:
    def test_a_large_result_does_not_enter_the_transcript_whole(self, big_bus):
        model = ScriptedModel(tool_call("runs.get"), '{"answer": "ok"}')
        MissionRunner(
            model, big_bus, ["runs.get"], max_result_bytes=500,
        ).run("go")
        shown = model.seen[-1][-1]["content"]
        assert len(shown) < 1_500

    def test_the_cut_is_marked_and_not_silent(self, big_bus):
        """A silently truncated result is worse than an oversized one:
        nothing tells the model a figure was cut off, so the persona rule
        against restating from memory has nothing to bite on."""
        model = ScriptedModel(tool_call("runs.get"), '{"answer": "ok"}')
        MissionRunner(
            model, big_bus, ["runs.get"], max_result_bytes=500,
        ).run("go")
        shown = model.seen[-1][-1]["content"]
        assert "truncated" in shown
        assert "must not be guessed at" in shown

    def test_head_and_tail_both_survive(self, big_bus):
        model = ScriptedModel(tool_call("runs.get"), '{"answer": "ok"}')
        MissionRunner(
            model, big_bus, ["runs.get"], max_result_bytes=500,
        ).run("go")
        shown = model.seen[-1][-1]["content"]
        assert "HEAD" in shown and "TAIL" in shown

    def test_the_marker_names_the_handle_to_read_the_rest_from(self, big_bus):
        model = ScriptedModel(tool_call("runs.get"), '{"answer": "ok"}')
        MissionRunner(
            model, big_bus, ["runs.get"], max_result_bytes=500,
        ).run("go")
        assert 'mission_result(handle="r1"' in model.seen[-1][-1]["content"]

    def test_the_step_records_that_it_was_truncated(self, big_bus):
        transcript = MissionRunner(
            ScriptedModel(tool_call("runs.get"), '{"answer": "ok"}'),
            big_bus, ["runs.get"], max_result_bytes=500,
        ).run("go")
        assert transcript.steps[0].truncated is True
        assert transcript.steps[0].handle == "r1"

    def test_the_transcript_keeps_the_untruncated_output(self, big_bus):
        transcript = MissionRunner(
            ScriptedModel(tool_call("runs.get"), '{"answer": "ok"}'),
            big_bus, ["runs.get"], max_result_bytes=500,
        ).run("go")
        assert len(transcript.steps[0].output) > 5_000

    def test_a_small_result_is_untouched(self, bus):
        model = ScriptedModel(tool_call("catalog.search", q="taiwan"),
                              '{"answer": "ok"}')
        transcript = MissionRunner(model, bus, ["catalog.search"]).run("go")
        assert transcript.steps[0].truncated is False
        assert "truncated" not in model.seen[-1][-1]["content"]


class TestTheResultStore:
    def test_the_full_result_is_reachable_by_handle(self, big_bus):
        runner = MissionRunner(
            ScriptedModel(tool_call("runs.get"), '{"answer": "ok"}'),
            big_bus, ["runs.get"], max_result_bytes=500,
        )
        runner.run("go")
        assert len(runner.store.get("r1").text) > 5_000

    def test_the_structured_payload_survives_the_bus(self, big_bus):
        """`as_tuple()` drops it whenever there is text; the bridge and
        the bus carry it in the fourth element so the store keeps it."""
        runner = MissionRunner(
            ScriptedModel(tool_call("runs.get"), '{"answer": "ok"}'),
            big_bus, ["runs.get"],
        )
        runner.run("go")
        assert runner.store.get("r1").structured["totals"]["records"] == 12481

    def test_the_model_can_fetch_one_field(self, big_bus):
        model = ScriptedModel(
            tool_call("runs.get"),
            tool_call(RESULT_TOOL, handle="r1", path="totals.records"),
            '{"answer": "12481"}',
        )
        transcript = MissionRunner(
            model, big_bus, ["runs.get"], max_result_bytes=500,
        ).run("go")
        assert transcript.steps[1].output == "12481"

    def test_the_store_tool_is_in_the_catalogue(self, bus):
        runner = MissionRunner(ScriptedModel(), bus, ["catalog.search"])
        assert RESULT_TOOL in runner.offered

    def test_the_model_is_told_about_it_during_the_run(self, bus):
        """It is registered inside `run()`, so a catalogue rendered
        before then would silently omit the one tool the truncation
        marker tells the model to call."""
        model = ScriptedModel('{"answer": "ok"}')
        MissionRunner(model, bus, ["catalog.search"]).run("go")
        system = model.seen[0][0]["content"]
        assert f"- {RESULT_TOOL}:" in system
        assert "handle (string)" in system

    def test_it_is_withdrawn_when_the_mission_ends(self, bus):
        MissionRunner(
            ScriptedModel('{"answer": "ok"}'), bus, ["catalog.search"],
        ).run("go")
        assert RESULT_TOOL not in bus.list_tools()

    def test_it_is_withdrawn_even_when_the_loop_raises(self, bus):
        def explode(_messages):
            raise RuntimeError("backend fell over")

        with pytest.raises(RuntimeError):
            MissionRunner(explode, bus, ["catalog.search"]).run("go")
        assert RESULT_TOOL not in bus.list_tools()

    def test_a_second_run_does_not_see_the_first_ones_results(self, bus):
        runner = MissionRunner(
            ScriptedModel(tool_call("catalog.search", q="a"), '{"answer": "ok"}',
                          tool_call("catalog.search", q="b"), '{"answer": "ok"}'),
            bus, ["catalog.search"],
        )
        runner.run("first")
        runner.run("second")
        assert len(runner.store) == 1
        assert runner.store.get("r1").arguments == {"q": "b"}

    def test_a_mission_can_run_without_one(self, bus):
        runner = MissionRunner(
            ScriptedModel('{"answer": "ok"}'), bus, ["catalog.search"],
            store_tool="",
        )
        assert runner.offered == ["catalog.search"]
        assert runner.run("go").completed


# ---------------------------------------------------------------------------
# Grounding: an answer is checked against this run's own tool output
# ---------------------------------------------------------------------------

ID_PATTERN = r"\b(?:asset|labels|run)\.[0-9a-f]{4,}\b"


@pytest.fixture
def asset_bus():
    b = ToolBus(capability_engine=CapabilityEngine(PolicyPack(allowed_scopes=["*"])))
    b.register(
        ToolDescriptor(tool_name="catalog.search", description="Search."),
        lambda **_kw: (0, "asset.5f21c9 — Taiwan narrative corpus", ""),
    )
    return b


@pytest.fixture
def strict():
    return GroundingValidator.from_config(
        GroundingConfig(identifier_pattern=ID_PATTERN)
    )


class TestGroundingTheAnswer:
    def test_a_cited_answer_is_answered(self, asset_bus, strict):
        transcript = MissionRunner(
            ScriptedModel(tool_call("catalog.search"),
                          '{"answer": "The corpus is asset.5f21c9."}'),
            asset_bus, ["catalog.search"], validator=strict,
        ).run("go")
        assert transcript.outcome == "answered"
        assert transcript.grounding.grounded

    def test_an_invented_identifier_gets_a_repair_turn(self, asset_bus, strict):
        model = ScriptedModel(
            tool_call("catalog.search"),
            '{"answer": "The label set is labels.7a19c4e2."}',
            '{"answer": "The corpus is asset.5f21c9; no label set was found."}',
        )
        transcript = MissionRunner(
            model, asset_bus, ["catalog.search"], validator=strict,
        ).run("go")
        assert transcript.outcome == "answered"
        assert "labels.7a19c4e2" not in transcript.answer

    def test_the_repair_turn_names_the_token(self, asset_bus, strict):
        model = ScriptedModel(
            tool_call("catalog.search"),
            '{"answer": "labels.7a19c4e2 is the set."}',
            '{"answer": "asset.5f21c9 only."}',
        )
        MissionRunner(
            model, asset_bus, ["catalog.search"], validator=strict,
        ).run("go")
        turns = [m["content"] for m in model.seen[-1] if m["role"] == "user"]
        assert any("labels.7a19c4e2" in t for t in turns)

    def test_a_second_failure_is_caveated_not_suppressed(self, asset_bus, strict):
        """THE test. The answer survives — deleting it hides a finding —
        and says of itself what no tool established."""
        model = ScriptedModel(
            tool_call("catalog.search"),
            '{"answer": "labels.7a19c4e2 is the set."}',
            '{"answer": "It is definitely labels.7a19c4e2."}',
        )
        transcript = MissionRunner(
            model, asset_bus, ["catalog.search"], validator=strict,
        ).run("go")
        assert transcript.outcome == "answered_with_caveat"
        assert transcript.completed
        assert "Ungrounded" in transcript.answer
        assert "labels.7a19c4e2" in transcript.answer

    def test_only_one_repair_turn_is_spent(self, asset_bus, strict):
        model = ScriptedModel(
            tool_call("catalog.search"),
            '{"answer": "labels.aaaaaa"}',
            '{"answer": "labels.bbbbbb"}',
            '{"answer": "labels.cccccc"}',
        )
        MissionRunner(
            model, asset_bus, ["catalog.search"], validator=strict,
        ).run("go")
        assert len(model.replies) == 1  # the third answer was never asked for

    def test_zero_repairs_goes_straight_to_the_caveat(self, asset_bus):
        validator = GroundingValidator.from_config(
            GroundingConfig(identifier_pattern=ID_PATTERN, max_repairs=0)
        )
        transcript = MissionRunner(
            ScriptedModel(tool_call("catalog.search"),
                          '{"answer": "labels.7a19c4e2"}'),
            asset_bus, ["catalog.search"], validator=validator,
        ).run("go")
        assert transcript.outcome == "answered_with_caveat"

    def test_an_id_from_a_refused_call_is_not_grounded(self, strict):
        """A tool that refused established nothing, whatever its error
        message happened to contain."""
        refusing = ToolBus(
            capability_engine=CapabilityEngine(PolicyPack(allowed_scopes=["*"])),
        )
        refusing.register(
            ToolDescriptor(tool_name="catalog.search", description="Search."),
            lambda **_kw: (1, "", "not found: asset.5f21c9"),
        )
        transcript = MissionRunner(
            ScriptedModel(tool_call("catalog.search"),
                          '{"answer": "asset.5f21c9"}',
                          '{"answer": "asset.5f21c9"}'),
            refusing, ["catalog.search"], validator=strict,
        ).run("go")
        assert transcript.outcome == "answered_with_caveat"

    def test_no_validator_leaves_the_loop_exactly_as_it_was(self, asset_bus):
        transcript = MissionRunner(
            ScriptedModel(tool_call("catalog.search"),
                          '{"answer": "labels.7a19c4e2"}'),
            asset_bus, ["catalog.search"],
        ).run("go")
        assert transcript.outcome == "answered"
        assert transcript.grounding is None

    def test_a_validator_that_could_not_run_does_not_claim_a_pass(self, asset_bus):
        """No grammar means no opinion. It must never read as grounded."""
        from core.runtime.grounding import IdentifierGroundingCheck

        blind = GroundingValidator([IdentifierGroundingCheck(GroundingConfig())])
        transcript = MissionRunner(
            ScriptedModel(tool_call("catalog.search"),
                          '{"answer": "labels.7a19c4e2"}'),
            asset_bus, ["catalog.search"], validator=blind,
        ).run("go")
        assert transcript.outcome == "answered"
        assert transcript.grounding.ran is False
        assert transcript.grounding.grounded is False


# ---------------------------------------------------------------------------
# A skill manifest drives the whole thing
# ---------------------------------------------------------------------------

SKILL = """\
---
name: recon
skill:
  skill_id: recon
  allowed_tools:
    - search
    - get
  policy:
    - Never invent an asset id.
  output_format: A table, then a paragraph.
  grounding:
    identifier_pattern: '\\b(?:asset|labels)\\.[0-9a-f]{4,}\\b'
---

# Recon

Start broad, then narrow by facet.
"""


class TestDrivenByAManifest:
    @pytest.fixture
    def manifest(self, tmp_path):
        path = tmp_path / "SKILL.md"
        path.write_text(SKILL, encoding="utf-8")
        return SkillManifest.from_file(path)

    @pytest.fixture
    def server_bus(self):
        b = ToolBus(capability_engine=CapabilityEngine(PolicyPack(allowed_scopes=["*"])))
        for name in ("mcp.search", "mcp.get", "mcp.delete_everything"):
            b.register(
                ToolDescriptor(tool_name=name, description=f"The {name} tool."),
                lambda **_kw: (0, "asset.5f21c9", ""),
            )
        return b

    def test_the_closed_set_narrows_what_is_offered(self, manifest, server_bus):
        names = manifest.resolve(server_bus.list_tools())
        runner = MissionRunner(ScriptedModel(), server_bus, names)
        system = runner.seed("x")[0]["content"]
        assert "mcp.search" in system
        assert "mcp.delete_everything" not in system

    def test_a_tool_outside_the_set_is_refused_even_though_the_bus_has_it(
        self, manifest, server_bus,
    ):
        names = manifest.resolve(server_bus.list_tools())
        transcript = MissionRunner(
            ScriptedModel(tool_call("mcp.delete_everything"), '{"answer": "no"}'),
            server_bus, names,
        ).run("go")
        assert "no tool named 'mcp.delete_everything'" in transcript.steps[0].error

    def test_the_skills_operational_knowledge_reaches_the_model(
        self, manifest, server_bus,
    ):
        names = manifest.resolve(server_bus.list_tools())
        runner = MissionRunner(
            ScriptedModel(), server_bus, names,
            system_message="You are Tai.\n\n" + manifest.prompt,
        )
        system = runner.seed("x")[0]["content"]
        assert system.startswith("You are Tai.")
        assert "Never invent an asset id." in system
        assert "Start broad, then narrow by facet." in system
        assert "A table, then a paragraph." in system

    def test_the_manifests_grammar_is_what_enforces_grounding(
        self, manifest, server_bus,
    ):
        """The pattern is content, from the file. The checking is the
        harness's. Neither works without the other."""
        validator = GroundingValidator.from_config(
            GroundingConfig.from_mapping(manifest.grounding)
        )
        transcript = MissionRunner(
            ScriptedModel(tool_call("mcp.search"),
                          '{"answer": "labels.deadbeef"}',
                          '{"answer": "labels.deadbeef"}'),
            server_bus, manifest.resolve(server_bus.list_tools()),
            validator=validator,
        ).run("go")
        assert transcript.outcome == "answered_with_caveat"


class TestAnUnchangedResultIsNotPastedTwice:
    """The Qwen3-30B context death, as a harness behaviour.

    Recorded 10 August 2026: three `runs_get` calls on the same `run_id` at
    turns 1, 2 and 4, three copies of one 33,000-character view in a history
    nothing trims, and a context overflow at turn 5 that was not about
    context. `mission_result` was offered in the truncation marker of every
    one of those turns and never called.

    The call is still made — this platform is submit-and-poll and a repeated
    `compute_job_status` is a mission working correctly. What is collapsed is
    the paste, and only when the bytes are identical.
    """

    @pytest.fixture
    def polling_bus(self):
        """A tool whose answer changes, and one whose answer does not."""
        b = ToolBus(capability_engine=CapabilityEngine(
            PolicyPack(allowed_scopes=["*"])))
        b.register(
            ToolDescriptor(tool_name="runs.get", description="One run, whole."),
            lambda **kw: (0, "X" * 5_000, ""),
        )
        polls = {"n": 0}

        def status(**kw):
            polls["n"] += 1
            return 0, f"status poll {polls['n']}", ""

        b.register(
            ToolDescriptor(tool_name="compute.status", description="Job state."),
            status,
        )
        return b

    def shown(self, model):
        """Every tool-result message the model was handed."""
        return [m["content"] for m in model.seen[-1]
                if m["role"] == "user" and m["content"].startswith("Result of")]

    def test_the_second_identical_fetch_is_one_line(self, polling_bus):
        model = ScriptedModel(
            tool_call("runs.get", run_id="a1"),
            tool_call("runs.get", run_id="a1"),
            '{"answer": "done"}',
        )
        MissionRunner(model, polling_bus, ["runs.get"], max_steps=5).run("go")
        first, second = self.shown(model)[:2]
        assert len(first) > 4_000
        assert len(second) < 400, (
            f"the unchanged re-fetch was pasted again in full: {len(second)} "
            f"chars")

    def test_it_names_the_handle_and_the_call_that_reads_it(self, polling_bus):
        model = ScriptedModel(
            tool_call("runs.get", run_id="a1"),
            tool_call("runs.get", run_id="a1"),
            '{"answer": "done"}',
        )
        MissionRunner(model, polling_bus, ["runs.get"], max_steps=5).run("go")
        second = self.shown(model)[1]
        assert "r1" in second
        assert f'{RESULT_TOOL}(handle="r1"' in second, (
            "a notice that does not spell out the call is a notice the model "
            "has to guess its way past")

    def test_the_call_is_still_dispatched_and_still_recorded(self, polling_bus):
        """Not a refusal. The audit log and the evidence must not lose it."""
        model = ScriptedModel(
            tool_call("runs.get", run_id="a1"),
            tool_call("runs.get", run_id="a1"),
            '{"answer": "done"}',
        )
        runner = MissionRunner(model, polling_bus, ["runs.get"], max_steps=5)
        transcript = runner.run("go")
        calls = [s for s in transcript.steps if s.tool == "runs.get"]
        assert len(calls) == 2
        assert [s.exit_code for s in calls] == [0, 0]
        assert len(runner.store) == 2, "the repeat was not recorded"

    def test_a_poll_that_changed_is_shown_in_full(self, polling_bus):
        """The behaviour a blanket repeat-refusal would have broken."""
        model = ScriptedModel(
            tool_call("compute.status", job="j1"),
            tool_call("compute.status", job="j1"),
            '{"answer": "done"}',
        )
        MissionRunner(model, polling_bus, ["compute.status"],
                      max_steps=5).run("go")
        first, second = self.shown(model)[:2]
        assert "status poll 1" in first
        assert "status poll 2" in second, (
            "a poll whose answer changed was collapsed as a duplicate")
        assert "identical" not in second

    def test_a_different_argument_is_not_a_duplicate(self, polling_bus):
        model = ScriptedModel(
            tool_call("runs.get", run_id="a1"),
            tool_call("runs.get", run_id="a2"),
            '{"answer": "done"}',
        )
        MissionRunner(model, polling_bus, ["runs.get"], max_steps=5).run("go")
        second = self.shown(model)[1]
        assert "identical" not in second, (
            "runs.get(a2) returned the same bytes as runs.get(a1) only "
            "because this stub ignores its arguments; the check must compare "
            "the call as well")


class TestTheRefusalNamesTheNearMiss:
    """Three spellings of one tool in one prompt, and the turns they cost.

    Measured 10 August 2026. `mcp.catalog_search_assets` is the dispatch
    name; the catalogue prose says `catalog.search_assets`; the skill prose
    says bare `catalog_search_assets`. A mission emitted the bare form, burnt
    a turn on `reply_rejected`, then burnt a second on a repair that guessed
    wrong — because the refusal listed the whole catalogue and never said
    which entry the model had nearly typed.

    The set is derived from the bus at runtime, so a tool TAIPAN adds is
    matchable here without a judais-lobi release.
    """

    @pytest.fixture
    def namespaced_bus(self):
        b = ToolBus(capability_engine=CapabilityEngine(
            PolicyPack(allowed_scopes=["*"])))
        for name in ("mcp.catalog_search_assets", "mcp.catalog_get_asset",
                     "mcp.runs_list"):
            b.register(ToolDescriptor(tool_name=name, description="A tool."),
                       lambda **kw: (0, "ok", ""))
        return b

    def refusal_for(self, bus, spelling):
        model = ScriptedModel(tool_call(spelling), '{"answer": "done"}')
        offered = ["mcp.catalog_search_assets", "mcp.catalog_get_asset",
                   "mcp.runs_list"]
        transcript = MissionRunner(model, bus, offered, max_steps=4).run("go")
        return transcript.steps[0].error

    @pytest.mark.parametrize("spelling", [
        "catalog_search_assets",            # the skill prose spelling
        "catalog.search_assets",            # the catalogue prose spelling
        "CATALOG_SEARCH_ASSETS",            # case
    ])
    def test_every_recorded_spelling_gets_the_dispatch_name(
            self, namespaced_bus, spelling):
        refusal = self.refusal_for(namespaced_bus, spelling)
        assert "mcp.catalog_search_assets" in refusal
        assert "almost certainly mean" in refusal, (
            f"{spelling!r} was refused with a bare catalogue dump; that is "
            f"the refusal that cost two turns on 10 August")

    def test_the_catalogue_still_follows_it(self, namespaced_bus):
        """A model that meant a different tool must still see the set."""
        refusal = self.refusal_for(namespaced_bus, "catalog_search_assets")
        assert "mcp.runs_list" in refusal

    def test_a_genuinely_unknown_tool_gets_no_suggestion(self, namespaced_bus):
        """A confident wrong suggestion is worse than none."""
        refusal = self.refusal_for(namespaced_bus, "run_inspection")
        assert "almost certainly mean" not in refusal
        assert "Choose one of" in refusal

    def test_an_ambiguous_name_proposes_neither(self):
        """Two tools normalising the same way is a coin flip the model
        cannot see it is taking."""
        b = ToolBus(capability_engine=CapabilityEngine(
            PolicyPack(allowed_scopes=["*"])))
        for name in ("mcp.runs_list", "local.runs_list"):
            b.register(ToolDescriptor(tool_name=name, description="A tool."),
                       lambda **kw: (0, "ok", ""))
        model = ScriptedModel(tool_call("runs_list"), '{"answer": "done"}')
        transcript = MissionRunner(
            model, b, ["mcp.runs_list", "local.runs_list"],
            max_steps=4).run("go")
        assert "almost certainly mean" not in transcript.steps[0].error
