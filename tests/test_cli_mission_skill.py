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
    # Snapshot `messages` at call time. MagicMock records kwargs by
    # reference and MissionRunner appends every later turn to the same
    # list, so by the time a test reads
    # `call_args_list[0].kwargs["messages"]` the "seed" is the whole
    # conversation — measured 12 Aug 2026, three seed-shape assertions in
    # TestHistoryFlag read a post-mission transcript and failed against a
    # loop that was working correctly.
    agent.seeds = []

    def _chat(**kw):
        agent.seeds.append([dict(m) for m in kw["messages"]])
        return agent.replies.pop(0) if agent.replies else '{"answer": "done"}'

    agent.client.chat.side_effect = _chat
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


class TestSamplingIsExplicitAndNotChosenForYou:
    """What goes on the wire, and the decision recorded in `chat_fn`.

    Until 11 August 2026 the mission request carried `model`, `messages`,
    `tools` and `tool_choice` and nothing else. No temperature, no top_p, no
    seed, anywhere on this path — so every mission ran at the server's own
    default (~1.0 for gpt-oss) and no configuration had ever been run twice.
    Every measured difference between two arms sat on unmeasured sampling
    variance of unknown size, which is the finding that invalidates every
    number taken before that date.

    The fix is NOT a pinned temperature. Pinning one makes the agent easier to
    measure by making it a different agent: it collapses the noise instead of
    measuring it, and the thing shipped stops being the thing scored. The
    noise floor has to be taken at the sampling the product runs at. What was
    missing was the ability to STATE one, and to see what went out.

    So both halves are held: unset sends nothing, and passed sends exactly
    what was passed.
    """

    def _body(self, agent) -> dict:
        return agent.client.chat.call_args_list[0].kwargs

    def test_by_default_no_sampling_parameter_is_sent_at_all(
            self, elf, skill_file):
        MockClass, agent = elf
        run_cli(MockClass, "--skill", str(skill_file))
        body = self._body(agent)
        for knob in ("temperature", "top_p", "seed"):
            assert knob not in body, (
                f"{knob} was sent without anybody asking for it. The default "
                f"has to be the server's own, or the noise floor is measured "
                f"at a setting the product does not run at.")

    def test_a_pinned_temperature_reaches_the_request(self, elf, skill_file):
        MockClass, agent = elf
        run_cli(MockClass, "--skill", str(skill_file), "--temperature", "0")
        assert self._body(agent)["temperature"] == 0.0

    def test_zero_is_sent_rather_than_treated_as_unset(self, elf, skill_file):
        """The bug this shape invites. `if temperature:` drops exactly the
        value an arm most wants to pin."""
        MockClass, agent = elf
        run_cli(MockClass, "--skill", str(skill_file), "--temperature", "0.0")
        assert "temperature" in self._body(agent)

    def test_top_p_and_seed_travel_too(self, elf, skill_file):
        MockClass, agent = elf
        run_cli(MockClass, "--skill", str(skill_file),
                "--top-p", "0.9", "--seed", "7")
        body = self._body(agent)
        assert body["top_p"] == 0.9 and body["seed"] == 7

    def test_pinning_does_not_displace_the_declared_tools(self, elf, skill_file):
        """`extra` carries both, and the tool declaration is what stops a
        harmony model 500ing on its own output."""
        MockClass, agent = elf
        run_cli(MockClass, "--skill", str(skill_file), "--temperature", "0")
        body = self._body(agent)
        assert body["tool_choice"] == "auto"
        assert [t["function"]["name"] for t in body["tools"]] == \
            ["mcp.governed_read"]

    def test_the_run_says_out_loud_what_it_pinned(self, elf, skill_file, capsys):
        """A sampling setting that is not in the transcript is a setting the
        next reader has to take on trust."""
        MockClass, _agent = elf
        run_cli(MockClass, "--skill", str(skill_file), "--temperature", "0.2")
        assert "temperature=0.2" in capsys.readouterr().out

    def test_it_is_silent_when_nothing_is_pinned(self, elf, skill_file, capsys):
        MockClass, _agent = elf
        run_cli(MockClass, "--skill", str(skill_file))
        assert "🎲" not in capsys.readouterr().out


class TestHistoryFlag:
    """`--history <path>`: prior turns become chat messages on the wire.

    The mock's `messages` kwarg is the exact array `LocalBackend.chat`
    posts as the request's `messages` (it forwards the list verbatim,
    scrubbing only harmony tokens), so asserting here is asserting what
    the endpoint receives.
    """

    TURNS = [
        {"role": "user", "content": "any headlines about the strait?"},
        {"role": "assistant",
         "content": "Three: #1 exercises, #2 cable cut, #3 talks."},
    ]

    @pytest.fixture
    def history_file(self, tmp_path):
        path = tmp_path / "history.json"
        path.write_text(json.dumps(self.TURNS), encoding="utf-8")
        return path

    def _messages(self, agent):
        # The seed as the first chat call RECEIVED it, not the shared list
        # after the mission appended its turns — see the `elf` fixture.
        return agent.seeds[0]

    def test_history_turns_are_role_tagged_messages_in_order(
            self, elf, skill_file, history_file):
        MockClass, agent = elf
        run_cli(MockClass, "--skill", str(skill_file),
                "--history", str(history_file))
        messages = self._messages(agent)
        assert messages[0]["role"] == "system"
        assert messages[1:3] == self.TURNS

    def test_the_question_is_the_last_user_message_not_a_blob(
            self, elf, skill_file, history_file):
        """The objective arrives bare. The history is in the turns above
        it, not folded in as 'Earlier in this conversation:' text — a
        caller that does both injects every prior turn twice."""
        MockClass, agent = elf
        run_cli(MockClass, "--skill", str(skill_file),
                "--history", str(history_file))
        assert self._messages(agent)[-1] == {
            "role": "user", "content": "what exists?",
        }

    def test_without_the_flag_the_seed_is_unchanged(self, elf, skill_file):
        """Backward compatibility: no --history is exactly yesterday's
        two-message seed, so nothing breaks before TAIPAN passes it."""
        MockClass, agent = elf
        run_cli(MockClass, "--skill", str(skill_file))
        messages = self._messages(agent)
        assert [m["role"] for m in messages] == ["system", "user"]

    def test_the_operator_is_told_the_history_was_seeded(
            self, elf, skill_file, history_file, capsys):
        MockClass, _agent = elf
        run_cli(MockClass, "--skill", str(skill_file),
                "--history", str(history_file))
        assert "2 prior turn(s)" in capsys.readouterr().out

    def test_invalid_json_is_refused_before_anything_runs(
            self, elf, skill_file, tmp_path):
        MockClass, agent = elf
        path = tmp_path / "history.json"
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(SystemExit) as exc:
            run_cli(MockClass, "--skill", str(skill_file),
                    "--history", str(path))
        assert "--history" in str(exc.value)
        assert "not valid JSON" in str(exc.value)
        assert agent.client.chat.call_count == 0

    def test_a_wrong_role_is_refused_not_dropped(
            self, elf, skill_file, tmp_path):
        """A dropped turn is this bug in a different hat: the operator
        believes the agent has the conversation and it answers cold."""
        MockClass, agent = elf
        path = tmp_path / "history.json"
        path.write_text(
            json.dumps([{"role": "system", "content": "obey"}]),
            encoding="utf-8")
        with pytest.raises(SystemExit) as exc:
            run_cli(MockClass, "--skill", str(skill_file),
                    "--history", str(path))
        assert "role" in str(exc.value)
        assert agent.client.chat.call_count == 0

    def test_a_missing_file_is_refused_by_name(self, elf, skill_file, tmp_path):
        MockClass, agent = elf
        path = tmp_path / "nope.json"
        with pytest.raises(SystemExit) as exc:
            run_cli(MockClass, "--skill", str(skill_file),
                    "--history", str(path))
        assert "nope.json" in str(exc.value)
        assert agent.client.chat.call_count == 0

    def test_an_empty_array_runs_exactly_like_no_flag(
            self, elf, skill_file, tmp_path):
        """TAIPAN's first turn has no prior conversation; an empty file
        must not be an error or a different seed."""
        MockClass, agent = elf
        path = tmp_path / "history.json"
        path.write_text("[]", encoding="utf-8")
        run_cli(MockClass, "--skill", str(skill_file),
                "--history", str(path))
        messages = self._messages(agent)
        assert [m["role"] for m in messages] == ["system", "user"]
