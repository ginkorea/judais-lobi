# tests/test_mission_end_to_end.py — a skill, a real MCP server, one mission

"""The three pieces together, over the real protocol.

``tests/mcp_stub_server.py`` is a FastMCP server spawned as a subprocess
and spoken to over stdio: a real ``initialize``, a real ``tools/list``
with real JSON Schema, and a real ``tools/call`` returning a real
``structuredContent``. No TAIPAN server and no GPU — the claims under
test are about the harness.

The model is scripted, because what is being checked is what the harness
puts in front of a model and what it does with the reply, not whether a
20b model plays along.
"""

import json
import sys
import textwrap
from pathlib import Path

import pytest

from core.contracts.schemas import PolicyPack
from core.runtime.grounding import GroundingConfig, GroundingValidator
from core.runtime.mission import MissionRunner
from core.runtime.results import RESULT_TOOL
from core.runtime.skills import SkillManifest, SkillToolsUnavailable
from core.tools.bus import ToolBus
from core.tools.capability import CapabilityEngine

pytest.importorskip("mcp", reason="the MCP client is an optional extra")

from core.tools.mcp_client import McpClient, McpToolBridge, StdioTransport  # noqa: E402

STUB = str(Path(__file__).parent / "mcp_stub_server.py")

SKILL = textwrap.dedent("""\
    ---
    name: run-inspection
    description: Read a finished run and draft a synthesis with evidence.
    skill:
      skill_id: run_inspection
      version: 0.1.0
      when_to_use: A run has finished and somebody has to say what it found.
      allowed_tools:
        - governed_view
        - governed_read
        - echo?
      policy:
        - Every ranked actor cites representative record ids.
        - Never invent an identifier.
      output_format: A ranked table, then the claims this run does NOT support.
      grounding:
        identifier_pattern: '\\b(?:a|rec|run)\\.[0-9a-z]{4,}\\b'
    ---

    # Run inspection

    The view carries numbers and identifiers only, never prose.
    """)


@pytest.fixture(scope="module")
def client():
    transport = StdioTransport(command=sys.executable, args=[STUB])
    with McpClient(transport, timeout=30.0) as c:
        yield c


@pytest.fixture
def bus():
    return ToolBus(capability_engine=CapabilityEngine(PolicyPack(allowed_scopes=["*"])))


@pytest.fixture
def manifest(tmp_path):
    path = tmp_path / "SKILL.md"
    path.write_text(SKILL, encoding="utf-8")
    return SkillManifest.from_file(path)


@pytest.fixture
def discovered(client, bus):
    return McpToolBridge(client, bus).sync()


class ScriptedModel:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.seen = []

    def __call__(self, messages):
        self.seen.append([dict(m) for m in messages])
        return self.replies.pop(0) if self.replies else '{"answer": "done"}'


def tool_call(name, **arguments):
    return json.dumps({"tool": name, "arguments": arguments})


def runner_for(manifest, bus, discovered, model, **kw):
    validator = GroundingValidator.from_config(
        GroundingConfig.from_mapping(manifest.grounding)
    )
    return MissionRunner(
        model, bus, manifest.resolve(discovered),
        system_message=manifest.prompt,
        validator=validator,
        max_steps=6,
        **kw,
    )


class TestTheClosedSetAgainstARealToolsList:
    def test_it_resolves_to_namespaced_names(self, manifest, discovered):
        assert manifest.resolve(discovered) == [
            "mcp.governed_view", "mcp.governed_read", "mcp.echo",
        ]

    def test_the_server_offers_more_than_the_skill_allows(self, manifest, discovered):
        """`bridge.sync()` returns the whole bus; the skill is a subset,
        and `run_shell_command` is in the first and not the second."""
        assert "mcp.run_shell_command" in discovered
        assert "mcp.run_shell_command" not in manifest.resolve(discovered)

    def test_a_skill_naming_a_tool_this_server_lacks_refuses(self, tmp_path, discovered):
        path = tmp_path / "SKILL.md"
        path.write_text(SKILL.replace("- governed_read", "- runs_get"), encoding="utf-8")
        with pytest.raises(SkillToolsUnavailable) as exc:
            SkillManifest.from_file(path).resolve(discovered)
        assert "runs_get" in str(exc.value)
        assert "mcp.governed_view" in str(exc.value)


class TestTheCatalogueTheModelSees:
    def test_it_carries_the_servers_real_argument_types(
        self, manifest, bus, discovered,
    ):
        system = runner_for(
            manifest, bus, discovered, ScriptedModel(),
        ).seed("read run.5f21")[0]["content"]
        assert "run_id (string, required)" in system
        assert "section (string: actors|totals)" in system

    def test_the_skills_knowledge_is_in_the_same_prompt(
        self, manifest, bus, discovered,
    ):
        system = runner_for(
            manifest, bus, discovered, ScriptedModel(),
        ).seed("read run.5f21")[0]["content"]
        assert "Never invent an identifier." in system
        assert "numbers and identifiers only, never prose" in system

    def test_a_tool_outside_the_closed_set_is_not_described(
        self, manifest, bus, discovered,
    ):
        system = runner_for(
            manifest, bus, discovered, ScriptedModel(),
        ).seed("x")[0]["content"]
        assert "run_shell_command" not in system


class TestALargeGovernedResult:
    def test_the_view_is_too_big_for_a_transcript(self, bus, discovered):
        """The premise. Without it the cap is untested theatre."""
        assert len(bus.dispatch("mcp.governed_view", run_id="run.5f21").stdout) > 30_000

    def test_it_is_bounded_before_the_model_sees_it(self, manifest, bus, discovered):
        model = ScriptedModel(
            tool_call("mcp.governed_view", run_id="run.5f21"), '{"answer": "a.0000"}',
        )
        runner_for(manifest, bus, discovered, model, max_result_bytes=2_000).run("go")
        shown = model.seen[-1][-1]["content"]
        assert len(shown) < 3_000
        assert "truncated" in shown

    def test_the_structured_payload_survived_the_bridge_and_the_bus(
        self, manifest, bus, discovered,
    ):
        """`structuredContent` used to die in `as_tuple()` the moment a
        text block existed, which is always."""
        model = ScriptedModel(
            tool_call("mcp.governed_view", run_id="run.5f21"), '{"answer": "a.0000"}',
        )
        runner = runner_for(manifest, bus, discovered, model, max_result_bytes=2_000)
        runner.run("go")
        assert runner.store.get("r1").structured["result"]["totals"]["records"] == 12481

    def test_the_model_reads_one_field_instead_of_the_whole_view(
        self, manifest, bus, discovered,
    ):
        model = ScriptedModel(
            tool_call("mcp.governed_view", run_id="run.5f21"),
            tool_call(RESULT_TOOL, handle="r1", path="result.actors[0].handle"),
            '{"answer": "The leading actor is a.0000."}',
        )
        transcript = runner_for(
            manifest, bus, discovered, model, max_result_bytes=2_000,
        ).run("go")
        assert transcript.steps[1].output == "a.0000"
        assert transcript.outcome == "answered"

    def test_the_field_read_is_orders_of_magnitude_smaller(
        self, manifest, bus, discovered,
    ):
        model = ScriptedModel(
            tool_call("mcp.governed_view", run_id="run.5f21"),
            tool_call(RESULT_TOOL, handle="r1", path="result.totals"),
            '{"answer": "12481 records in run.5f21."}',
        )
        runner = runner_for(manifest, bus, discovered, model, max_result_bytes=2_000)
        runner.run("go")
        assert len(runner.store.get("r2").text) < len(runner.store.get("r1").text) / 100


class TestGroundingOverARealRun:
    def test_an_id_read_out_of_the_view_is_grounded(self, manifest, bus, discovered):
        model = ScriptedModel(
            tool_call("mcp.governed_view", run_id="run.5f21"),
            '{"answer": "Top actor a.0000, records rec.0000a."}',
        )
        transcript = runner_for(
            manifest, bus, discovered, model, max_result_bytes=2_000,
        ).run("go")
        assert transcript.outcome == "answered"
        assert transcript.grounding.grounded

    def test_an_id_from_the_truncated_middle_is_still_grounded(
        self, manifest, bus, discovered,
    ):
        """The store is the evidence, not the bounded rendering — an
        actor the model legitimately fetched by path must not be scored
        as an invention because the paste was cut."""
        model = ScriptedModel(
            tool_call("mcp.governed_view", run_id="run.5f21"),
            tool_call(RESULT_TOOL, handle="r1", path="result.actors[100].handle"),
            '{"answer": "Also present: a.0100."}',
        )
        transcript = runner_for(
            manifest, bus, discovered, model, max_result_bytes=1_000,
        ).run("go")
        assert transcript.grounding.grounded

    def test_a_plausible_invention_is_caveated(self, manifest, bus, discovered):
        """`a.9999` is exactly the shape of the 200 real handles and is
        not one of them. Nothing but this check can tell."""
        model = ScriptedModel(
            tool_call("mcp.governed_view", run_id="run.5f21"),
            '{"answer": "Top actor a.9999."}',
            '{"answer": "Top actor a.9999, definitely."}',
        )
        transcript = runner_for(
            manifest, bus, discovered, model, max_result_bytes=2_000,
        ).run("go")
        assert transcript.outcome == "answered_with_caveat"
        assert "a.9999" in transcript.answer
        assert "Ungrounded" in transcript.answer

    def test_the_store_tool_is_withdrawn_from_the_shared_bus(
        self, manifest, bus, discovered,
    ):
        runner_for(
            manifest, bus, discovered, ScriptedModel('{"answer": "done"}'),
        ).run("go")
        assert RESULT_TOOL not in bus.list_tools()


class TestAnAnswerWrittenAndNotDeliveredIsStillHandedOver:
    """The draft a repair turn took away and nothing gave back.

    There is exactly one way for a run to write a complete answer and not
    return it — a grounding repair judges it ungrounded and sends the model
    back around — and three ways for the model never to write another: the
    supervisor winds the run up and the wind-up turn does not answer, the step
    ceiling arrives, or the rest of the run goes on refused calls.

    All three used to end the same way: the consumer holding an outcome word
    over prose it had already been streamed, delta by delta. Measured on
    TAIPAN's hosted mission pane, 6 September 2026 — a complete and correct
    answer at step 1, seven `answer_delta` records carrying it, then four
    refused tool calls, and *"your agent stopped after 5 step(s) without
    reaching an answer"* on the page.

    So the draft is kept and handed over. The outcome word is deliberately
    **not** rewritten: the run did stop early, and calling it `answered` would
    be the loop overstating what happened to make a page read better.
    """

    def _abandons_then_runs_out(self, manifest, bus, discovered):
        """A run that answers ungrounded, is sent back, and never answers
        again — it spends the rest of its steps on a tool call instead."""
        model = ScriptedModel(
            tool_call("mcp.governed_view", run_id="run.5f21"),
            '{"answer": "Top actor a.9999."}',
            tool_call("mcp.echo", text="still going"),
            tool_call("mcp.echo", text="still going"),
            tool_call("mcp.echo", text="still going"),
            tool_call("mcp.echo", text="still going"),
            tool_call("mcp.echo", text="still going"),
        )
        return runner_for(manifest, bus, discovered, model,
                          max_result_bytes=2_000).run("go")

    def test_the_draft_is_delivered_rather_than_dropped(
            self, manifest, bus, discovered):
        transcript = self._abandons_then_runs_out(manifest, bus, discovered)
        assert transcript.answer == "Top actor a.9999."
        assert transcript.delivered_draft is True
        assert transcript.draft == "Top actor a.9999."

    def test_the_outcome_word_is_not_rewritten(
            self, manifest, bus, discovered):
        """The run really did run out of steps, and a consumer branching on
        the outcome keeps branching on it. `completed` stays False for the
        same reason: this is not an answer the run stands behind."""
        transcript = self._abandons_then_runs_out(manifest, bus, discovered)
        assert transcript.outcome == "budget_exhausted"
        assert transcript.completed is False

    def test_nothing_is_appended_to_the_model_s_words(
            self, manifest, bus, discovered):
        """A run that abandoned a draft has no verdict to append, so a
        sentence written in here would be a caveat with no check behind it.
        Whatever a consumer wants to say about a delivered draft it says
        beside the answer, off `delivered_draft`."""
        transcript = self._abandons_then_runs_out(manifest, bus, discovered)
        assert "Ungrounded" not in transcript.answer
        assert transcript.answer.strip() == "Top actor a.9999."

    def test_a_run_that_wrote_nothing_delivers_nothing(
            self, manifest, bus, discovered):
        """The empty case, and it must stay empty: inventing an answer for a
        run that never wrote one is the failure this is the opposite of."""
        model = ScriptedModel(
            *[tool_call("mcp.echo", text="a")] * 8,
        )
        transcript = runner_for(manifest, bus, discovered, model,
                                max_result_bytes=2_000).run("go")
        assert transcript.outcome == "budget_exhausted"
        assert not transcript.answer
        assert transcript.delivered_draft is False

    def test_a_run_that_finished_normally_carries_no_draft(
            self, manifest, bus, discovered):
        """`delivered_draft` is a fact about an unusual run. On every
        ordinary one it is False and `draft` is empty, so a consumer that
        branches on it is branching on something that means something."""
        model = ScriptedModel(
            tool_call("mcp.governed_view", run_id="run.5f21"),
            '{"answer": "Top actor a.0000, records rec.0000a."}',
        )
        transcript = runner_for(manifest, bus, discovered, model,
                                max_result_bytes=2_000).run("go")
        assert transcript.outcome == "answered"
        assert transcript.delivered_draft is False
        assert transcript.draft == ""

    def test_a_repaired_run_that_answered_again_delivers_the_repair(
            self, manifest, bus, discovered):
        """Not the draft. The second answer is the one the run reached, and
        a draft delivered over it would hand back the text the repair turn
        existed to replace."""
        model = ScriptedModel(
            tool_call("mcp.governed_view", run_id="run.5f21"),
            '{"answer": "Top actor a.9999."}',
            '{"answer": "Top actor a.0000."}',
        )
        transcript = runner_for(manifest, bus, discovered, model,
                                max_result_bytes=2_000).run("go")
        assert transcript.answer.startswith("Top actor a.0000.")
        assert transcript.delivered_draft is False
