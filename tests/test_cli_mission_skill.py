# tests/test_cli_mission_skill.py — `--mission --skill` from the command line

"""The wiring, exercised where an operator actually touches it.

The mission path is spawned against the real FastMCP stub over stdio, so
what is being checked is the actual sequence — load the manifest, bridge
the server, intersect the closed set, join persona and skill prompt,
build the validator — and not a rehearsal of it.

The refusals are the important half. An operator who names a skill and
gets a run *without* one gets a plausible answer from an agent holding
the whole bus and none of the operational knowledge they meant to give
it, and nothing in the output says so.
"""

import json
import sys
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.contracts.schemas import PolicyPack
from core.tools.bus import ToolBus
from core.tools.capability import CapabilityEngine

pytest.importorskip("mcp", reason="the MCP client is an optional extra")

STUB = str(Path(__file__).parent / "mcp_stub_server.py")

SKILL = textwrap.dedent("""\
    ---
    name: recon
    skill:
      skill_id: recon
      when_to_use: Arriving at a mission cold.
      allowed_tools:
        - governed_read
      policy:
        - Never invent an asset id.
      output_format: A table.
      grounding:
        identifier_pattern: '\\basset\\.[0-9a-z]{4,}\\b'
    ---

    # Recon

    Start broad, then narrow by facet.
    """)


@pytest.fixture
def skill_file(tmp_path):
    path = tmp_path / "SKILL.md"
    path.write_text(SKILL, encoding="utf-8")
    return path


@pytest.fixture
def elf():
    """An agent with a real ToolBus and a scripted backend."""
    agent = MagicMock()
    agent.model = "gpt-oss-20b"
    agent.text_color = "cyan"
    agent.client.provider = "local"
    agent.system_message = "You are Tai."
    agent.tools.bus = ToolBus(
        capability_engine=CapabilityEngine(PolicyPack(allowed_scopes=["*"])),
    )
    agent.replies = [
        json.dumps({"tool": "mcp.governed_read", "arguments": {"asset_id": "asset.5f21"}}),
        json.dumps({"answer": "The asset is asset.5f21."}),
    ]
    agent.client.chat.side_effect = lambda **_kw: (
        agent.replies.pop(0) if agent.replies else '{"answer": "done"}'
    )
    MockClass = MagicMock(return_value=agent)
    MockClass.__name__ = "Tai"
    return MockClass, agent


def argv(*extra):
    return [
        "test", "what exists?", "--mission",
        "--mcp-stdio", f"{sys.executable} {STUB}", *extra,
    ]


def run_cli(MockClass, *extra):
    from core.cli import _main
    with patch("sys.argv", argv(*extra)):
        _main(MockClass)


class TestTheHappyPath:
    def test_the_skills_prompt_and_persona_both_reach_the_model(self, elf, skill_file):
        MockClass, agent = elf
        run_cli(MockClass, "--skill", str(skill_file))
        system = agent.client.chat.call_args_list[0].kwargs["messages"][0]["content"]
        assert system.startswith("You are Tai.")
        assert "Never invent an asset id." in system
        assert "Start broad, then narrow by facet." in system

    def test_the_closed_set_is_what_is_offered(self, elf, skill_file):
        MockClass, agent = elf
        run_cli(MockClass, "--skill", str(skill_file))
        system = agent.client.chat.call_args_list[0].kwargs["messages"][0]["content"]
        assert "mcp.governed_read" in system
        assert "mcp.run_shell_command" not in system

    def test_the_argument_schema_reaches_the_model(self, elf, skill_file):
        MockClass, agent = elf
        run_cli(MockClass, "--skill", str(skill_file))
        system = agent.client.chat.call_args_list[0].kwargs["messages"][0]["content"]
        assert "asset_id (string, required)" in system

    def test_the_mission_completes(self, elf, skill_file, capsys):
        MockClass, _agent = elf
        run_cli(MockClass, "--skill", str(skill_file))
        assert "asset.5f21" in capsys.readouterr().out

    def test_grounding_is_reported(self, elf, skill_file, capsys):
        MockClass, _agent = elf
        run_cli(MockClass, "--skill", str(skill_file))
        assert "grounded" in capsys.readouterr().out

    def test_the_bus_is_left_without_the_store_tool(self, elf, skill_file):
        MockClass, agent = elf
        run_cli(MockClass, "--skill", str(skill_file))
        assert "mission_result" not in agent.tools.bus.list_tools()


class TestTheRefusals:
    def test_a_skill_naming_an_undiscovered_tool_stops_the_run(self, elf, tmp_path):
        MockClass, agent = elf
        path = tmp_path / "SKILL.md"
        path.write_text(SKILL.replace("governed_read", "runs_get"), encoding="utf-8")
        with pytest.raises(SystemExit) as exc:
            run_cli(MockClass, "--skill", str(path))
        assert "runs_get" in str(exc.value)
        assert agent.client.chat.call_count == 0

    def test_an_unreadable_manifest_stops_the_run(self, elf, tmp_path):
        MockClass, agent = elf
        path = tmp_path / "SKILL.md"
        path.write_text("no frontmatter here\n", encoding="utf-8")
        with pytest.raises(SystemExit) as exc:
            run_cli(MockClass, "--skill", str(path))
        assert "frontmatter" in str(exc.value)
        assert agent.client.chat.call_count == 0

    def test_a_broken_grounding_grammar_stops_the_run(self, elf, tmp_path):
        """Before the mission, not eleven thousand seconds into it."""
        MockClass, agent = elf
        path = tmp_path / "SKILL.md"
        path.write_text(
            SKILL.replace("'\\basset\\.[0-9a-z]{4,}\\b'", "'[unclosed'"),
            encoding="utf-8",
        )
        with pytest.raises(SystemExit) as exc:
            run_cli(MockClass, "--skill", str(path))
        assert "regex" in str(exc.value)
        assert agent.client.chat.call_count == 0


class TestWithoutASkill:
    def test_the_mission_still_runs(self, elf):
        MockClass, agent = elf
        agent.replies = ['{"answer": "no tools needed"}']
        run_cli(MockClass)
        assert agent.client.chat.call_count == 1

    def test_it_says_the_agent_was_handed_everything(self, elf, capsys):
        """The fallback is a fallback, and the operator is told which
        posture they are in."""
        MockClass, agent = elf
        agent.replies = ['{"answer": "no tools needed"}']
        run_cli(MockClass)
        assert "No --skill" in capsys.readouterr().out

    def test_nothing_claims_the_answer_was_checked(self, elf, capsys):
        MockClass, agent = elf
        agent.replies = ['{"answer": "asset.deadbeef"}']
        run_cli(MockClass)
        out = capsys.readouterr().out
        assert "grounded" not in out.lower()
