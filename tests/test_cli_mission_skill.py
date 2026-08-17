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
import os
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from core.contracts.schemas import PolicyPack
from core.tools.bus import ToolBus
from core.tools.capability import CapabilityEngine
from core.tools.sandbox import NoneSandbox

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
    # Stated rather than left to the mock: a bare `MagicMock` attribute is
    # truthy and arithmetic-capable, so an unset `last_usage` would be
    # accumulated as if it were a provider's report. `None` is what a
    # backend that reported nothing hands back.
    agent.client.last_usage = None
    agent.system_message = "You are Tai."
    # An explicitly unisolated bus: this fixture predates the sandbox
    # being on by default, and the tests below that reason about "a host
    # without bwrap" need the bus to SAY none rather than inherit whatever
    # `select_sandbox` finds on the machine running the suite.
    agent.tools.bus = ToolBus(
        capability_engine=CapabilityEngine(PolicyPack(allowed_scopes=["*"])),
        sandbox=NoneSandbox(),
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

    def test_both_budgets_are_said_out_loud_at_the_start(
            self, elf, skill_file, capsys, monkeypatch):
        """Beside `🪟 context:`, and for the same reason: the line an
        operator reads BEFORE an 11,000-second mission rather than after
        it. "no wall clock" is printed as such and not omitted — somebody
        who meant to pass --mission-seconds and mistyped the variable
        should see that nothing is bounding the waiting."""
        MockClass, _agent = elf
        monkeypatch.delenv("MISSION_SECONDS", raising=False)
        run_cli(MockClass, "--skill", str(skill_file))
        out = capsys.readouterr().out
        assert "budget: 8 steps, no wall clock" in out

        run_cli(MockClass, "--skill", str(skill_file), "--mission-seconds", "45")
        assert "budget: 8 steps, 45 s" in capsys.readouterr().out

    def test_gate_wait_reaches_the_runner_and_zero_is_a_value(
            self, elf, skill_file, monkeypatch):
        """`--gate-wait` is the knob an unattended caller turns down: the
        reference deployment measured a 300 s hang on a gate nobody was
        watching. Flag beats env; `0` is honoured (never wait), and silence
        on both means the runner's own default."""
        from core.runtime.control import GATE_WAIT_S
        from core.runtime import mission as mission_module

        MockClass, _agent = elf
        seen = []
        original = mission_module.MissionRunner.__init__

        def spy(self_, *a, **kw):
            seen.append(kw.get("gate_wait_s"))
            return original(self_, *a, **kw)

        monkeypatch.setattr(mission_module.MissionRunner, "__init__", spy)
        monkeypatch.delenv("MISSION_GATE_WAIT", raising=False)
        run_cli(MockClass, "--skill", str(skill_file))
        assert seen[-1] == GATE_WAIT_S
        run_cli(MockClass, "--skill", str(skill_file), "--gate-wait", "0")
        assert seen[-1] == 0.0
        monkeypatch.setenv("MISSION_GATE_WAIT", "45")
        run_cli(MockClass, "--skill", str(skill_file))
        assert seen[-1] == 45.0
        run_cli(MockClass, "--skill", str(skill_file), "--gate-wait", "7.5")
        assert seen[-1] == 7.5

    def test_the_end_of_a_run_that_ran_out_says_which_budget(
            self, elf, skill_file, capsys):
        """`Mission ended without an answer: budget_exhausted` sent an
        operator to lengthen a step cap that may not be the thing that ran
        out. The console says which, with the numbers, like the record."""
        MockClass, agent = elf
        agent.replies = [json.dumps(
            {"tool": "mcp.governed_read",
             "arguments": {"asset_id": "asset.5f21"}})] * 4
        run_cli(MockClass, "--skill", str(skill_file), "--mission-steps", "2")
        out = capsys.readouterr().out
        assert "ran out of steps: 2 of 2" in out

    def test_the_end_of_a_cancelled_run_does_not_read_like_a_failure(
            self, elf, skill_file, capsys, monkeypatch):
        """Somebody asked, and the run wound up rather than being killed
        between records — which is why there is a transcript to read at
        all. `Mission ended without an answer: incomplete` would report
        that as the harness giving up."""
        import core.runtime.mission as mission_module

        MockClass, agent = elf
        agent.replies = [json.dumps(
            {"tool": "mcp.governed_read",
             "arguments": {"asset_id": "asset.5f21"}})] * 4

        real = mission_module.MissionRunner

        class Spy(real):
            def __init__(self, *args, **kwargs):
                kwargs["cancel"].cancel()
                super().__init__(*args, **kwargs)

        monkeypatch.setattr(mission_module, "MissionRunner", Spy)
        run_cli(MockClass, "--skill", str(skill_file))
        out = capsys.readouterr().out
        assert "Mission cancelled after 0 step(s)" in out
        assert "wound up on request" in out

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


class TestSwarmFlag:
    """`--swarm` wires the staged runner through the SAME spawn path.

    Exercised against the real stub server, like everything above: the
    manifest still gates the closed set, the grounding validator is still
    built, and the swarm's router — scripted DIRECT here — hands the turn
    to the ordinary loop, so the whole run should be indistinguishable
    from a plain mission apart from one extra (plain, tool-free) triage
    call at the front.
    """

    def test_swarm_direct_route_completes_like_a_plain_mission(
            self, elf, skill_file, capsys):
        MockClass, agent = elf
        agent.replies = [
            '{"route": "direct"}',
            json.dumps({"tool": "mcp.governed_read",
                        "arguments": {"asset_id": "asset.5f21"}}),
            json.dumps({"answer": "The asset is asset.5f21."}),
        ]
        run_cli(MockClass, "--skill", str(skill_file), "--swarm")
        out = capsys.readouterr().out
        assert "asset.5f21" in out
        assert "grounded" in out

    def test_the_triage_call_declares_no_tool_schemas(self, elf, skill_file):
        MockClass, agent = elf
        agent.replies = [
            '{"route": "direct"}',
            json.dumps({"tool": "mcp.governed_read",
                        "arguments": {"asset_id": "asset.5f21"}}),
            json.dumps({"answer": "The asset is asset.5f21."}),
        ]
        run_cli(MockClass, "--skill", str(skill_file), "--swarm")
        first = agent.client.chat.call_args_list[0].kwargs
        assert "tools" not in first
        # ... and the executor's calls keep the declared function
        # namespace and its decode-level guarantees.
        second = agent.client.chat.call_args_list[1].kwargs
        assert second.get("tools")

    def test_without_the_flag_no_triage_call_happens(self, elf, skill_file):
        MockClass, agent = elf
        run_cli(MockClass, "--skill", str(skill_file))
        first_system = agent.seeds[0][0]["content"]
        assert "router" not in first_system


class TestTheGate:
    """`--gate-tool`, against the names the bus actually dispatches.

    The consumer passes the wire spelling it read off its own tool table
    — `compute_cancel_job` — and the bridge namespaces everything it
    discovers, so the offered name is `mcp.compute_cancel_job`. Matched
    with `in`, that gated nothing at all: the `🔒 gated:` line never
    printed, the catalogue carried no approval marker, and the call a
    person was meant to decide on was dispatched like any other. The
    whole feature was off, and every surface said it was on.
    """

    def test_the_wire_spelling_gates_the_namespaced_tool(
            self, elf, skill_file, capsys):
        MockClass, agent = elf
        agent.replies = [json.dumps(
            {"tool": "mcp.governed_read", "arguments": {"asset_id": "asset.5f21"}})]
        run_cli(MockClass, "--skill", str(skill_file),
                "--gate-tool", "governed_read")
        out = capsys.readouterr().out
        assert "gated: mcp.governed_read" in out
        # And the gate did what a gate is for: the mission ended holding
        # the proposed call, and nobody ran it.
        assert "Waiting on a person" in out

    def test_a_gate_naming_nothing_is_refused_at_the_door(self, elf, skill_file):
        """Loudly, like a manifest naming a tool the server does not have.
        Dropping it quietly is how the mismatch above stayed quiet: an
        operator who asked for a gate and got a mission without one has
        been told the opposite of what happened."""
        MockClass, agent = elf
        with pytest.raises(SystemExit) as exc:
            run_cli(MockClass, "--skill", str(skill_file),
                    "--gate-tool", "runs_cancel")
        assert "runs_cancel" in str(exc.value)
        assert "mcp.governed_read" in str(exc.value)     # what WAS offered
        assert agent.client.chat.call_count == 0


CODE_PLANE_SKILL = textwrap.dedent("""\
    ---
    name: recon
    skill:
      skill_id: recon
      when_to_use: Arriving at a mission cold.
      allowed_tools:
        - governed_read
        - run_shell_command
      output_format: A table.
    ---

    # Recon

    Start broad, then narrow by facet.
    """)


class TestTheCodePlaneNeverArrivesUnisolated:
    """The stub server offers `run_shell_command`, and that is the point.

    A hosted platform's MCP server can put a shell on the bus, and a
    manifest can put that shell in its closed set, and until this gate
    both of those were ordinary lines in a file nobody would look at
    twice. The refusal is at the door — before the model is asked
    anything — because a mission that has already run is a mission that
    has already run whatever it ran.
    """

    def skill(self, tmp_path, extra=""):
        path = tmp_path / "SKILL.md"
        text = CODE_PLANE_SKILL.replace(
            "  output_format:", f"{extra}  output_format:")
        assert extra in text, "the fixture did not take the declaration"
        path.write_text(text, encoding="utf-8")
        return path

    def test_naming_the_shell_without_a_declaration_stops_the_run(
            self, elf, tmp_path):
        MockClass, agent = elf
        with pytest.raises(SystemExit) as exc:
            run_cli(MockClass, "--skill", str(self.skill(tmp_path)))
        message = str(exc.value)
        assert "run_shell_command" in message
        assert "add `sandbox: bwrap`" in message
        assert agent.client.chat.call_count == 0

    def test_declaring_bwrap_on_a_host_without_it_stops_the_run(
            self, elf, tmp_path):
        """The manifest asked for isolation; the bus is a `NoneSandbox`.
        Told here, at the door, rather than left to be inferred from a
        transcript of commands that ran on the host."""
        MockClass, agent = elf
        path = self.skill(tmp_path, extra="  sandbox: bwrap\n")
        with pytest.raises(SystemExit) as exc:
            run_cli(MockClass, "--skill", str(path))
        assert "the tool bus is running 'none'" in str(exc.value)
        assert agent.client.chat.call_count == 0

    @patch("core.tools.sandbox.shutil.which", return_value="/usr/bin/bwrap")
    def test_declared_and_actually_isolated_runs(self, _which, elf, tmp_path):
        from core.tools.sandbox import BwrapSandbox

        MockClass, agent = elf
        agent.tools.bus = ToolBus(
            capability_engine=CapabilityEngine(PolicyPack(allowed_scopes=["*"])),
            sandbox=BwrapSandbox(),
        )
        run_cli(MockClass, "--skill",
                str(self.skill(tmp_path, extra="  sandbox: bwrap\n")))
        system = agent.client.chat.call_args_list[0].kwargs["messages"][0]["content"]
        assert "mcp.run_shell_command" in system
        assert "Sandbox: bwrap" in system

    def test_a_manifest_with_no_code_plane_tool_still_runs_unisolated(
            self, elf, skill_file):
        """The gate is about the code plane and nothing else. Firing on
        every manifest would make the default bus unusable and teach an
        operator to route around the refusal."""
        MockClass, agent = elf
        run_cli(MockClass, "--skill", str(skill_file))
        assert agent.client.chat.call_count >= 1


class RecordingSink:
    """What `--events` opens, near enough: an observer that can be closed."""

    def __init__(self):
        self.records, self.closed = [], 0

    def __call__(self, record):
        self.records.append(dict(record))

    def close(self):
        self.closed += 1


class TestTheMissionWiring:
    """Two lines in `_run_mission` that nothing downstream would notice.

    Both are invisible to every assertion above. A mission with no
    SIGTERM handler runs identically until somebody stops it; a staged
    mission with no `sdk_import` runs identically until a planner wants
    the `code+sdk` rung. Neither failure shows up in a transcript, which
    is why they are asserted at the wiring instead.
    """

    def test_the_opened_sink_is_the_one_the_sigterm_handler_gets(
            self, elf, skill_file, monkeypatch):
        """A consumer stops a turn with SIGTERM rather than SIGKILL *so
        that* what was already written survives. Without this call the
        default disposition kills the process outright: no `finally`
        runs, the `fd:` sink is never closed, and the reader on the far
        end of the pipe waits on a descriptor nobody will shut.

        The handler is handed the mission's cancellation as well as its
        sink, and that is the half that makes the *last* record survive
        too: a handler holding only the sink can close a stream but
        cannot ask the loop to finish first, so the record that says the
        run is over is the one a stopped turn used to lose."""
        import core.runtime.mission_stream as stream

        MockClass, _agent = elf
        sink, handed = RecordingSink(), []
        monkeypatch.setattr(stream, "open_sink", lambda spec: sink)
        monkeypatch.setattr(stream, "close_on_sigterm",
                            lambda s, c=None: handed.append((s, c)))

        run_cli(MockClass, "--skill", str(skill_file))

        assert len(handed) == 1
        # The same object, not merely one of the same kind: what the
        # handler flushes has to be what the mission was writing to.
        assert handed[0][0] is sink
        assert sink.records and sink.closed == 1
        # And a switch it can actually throw, not None.
        assert handed[0][1] is not None and not handed[0][1].is_set()

    def test_the_runner_is_given_the_endpoints_own_context_window(
            self, elf, skill_file, monkeypatch):
        """A third line nothing downstream would notice.

        Without it the mission runs identically until the conversation
        outgrows the served model, and then it either 400s or is evicted
        inside the server — and the second is the one that produces an
        answer. The window is built here because this is where the
        deployment's client, provider and model meet; the loop is handed
        one so that a library caller can hand it a different one.
        """
        import core.runtime.mission as mission_module
        from core.runtime.backends.base import BackendCapabilities

        MockClass, agent = elf
        agent.client.capabilities = BackendCapabilities(
            max_context_tokens=8192, max_output_tokens=512)

        captured = {}
        real = mission_module.MissionRunner

        class Spy(real):
            def __init__(self, *args, **kwargs):
                captured.update(kwargs)
                super().__init__(*args, **kwargs)

        monkeypatch.setattr(mission_module, "MissionRunner", Spy)
        run_cli(MockClass, "--skill", str(skill_file))

        window = captured["window"]
        assert window.profile.source == "backend"
        assert window.limit_tokens == 8192 - 512

    def test_the_runner_is_given_the_wall_clock_the_operator_asked_for(
            self, elf, skill_file, monkeypatch):
        """`--mission-seconds` is inert unless it reaches the loop, and a
        budget that silently does nothing is worse than none: an operator
        who set one believes the run is bounded."""
        import core.runtime.mission as mission_module

        MockClass, _agent = elf
        captured = {}
        real = mission_module.MissionRunner

        class Spy(real):
            def __init__(self, *args, **kwargs):
                captured.update(kwargs)
                super().__init__(*args, **kwargs)

        monkeypatch.setattr(mission_module, "MissionRunner", Spy)
        run_cli(MockClass, "--skill", str(skill_file), "--mission-seconds", "45")

        assert captured["deadline"].seconds == 45.0
        assert captured["cancel"] is not None

    def test_without_the_flag_the_clock_is_unbounded(
            self, elf, skill_file, monkeypatch):
        """Unset means unbounded, all the way down. Steps bound the work;
        a default nobody chose would kill a slow local model mid-answer."""
        import core.runtime.mission as mission_module

        MockClass, _agent = elf
        monkeypatch.delenv("MISSION_SECONDS", raising=False)
        captured = {}
        real = mission_module.MissionRunner

        class Spy(real):
            def __init__(self, *args, **kwargs):
                captured.update(kwargs)
                super().__init__(*args, **kwargs)

        monkeypatch.setattr(mission_module, "MissionRunner", Spy)
        run_cli(MockClass, "--skill", str(skill_file))

        assert captured["deadline"].seconds is None
        assert captured["deadline"].unbounded is True

    def test_the_staged_runner_is_given_the_same_clock_and_switch(
            self, elf, monkeypatch):
        """One clock for the whole turn. A swarm handed none while the
        direct path was bounded would make the budget depend on which way
        the router went."""
        import core.runtime.swarm as swarm_module

        MockClass, agent = elf
        agent.replies = ['{"route": "direct"}', '{"answer": "no tools needed"}']
        captured = {}
        real = swarm_module.SwarmRunner

        class Spy(real):
            def __init__(self, *args, **kwargs):
                captured.update(kwargs)
                super().__init__(*args, **kwargs)

        monkeypatch.setattr(swarm_module, "SwarmRunner", Spy)
        run_cli(MockClass, "--swarm", "--mission-seconds", "45")

        assert captured["deadline"].seconds == 45.0
        assert captured["cancel"] is not None

    def test_the_staged_runner_is_given_it_too(self, elf, monkeypatch):
        """A staged mission runs more steps than a direct one, not fewer."""
        import core.runtime.swarm as swarm_module
        from core.runtime.backends.base import BackendCapabilities

        MockClass, agent = elf
        agent.client.capabilities = BackendCapabilities(
            max_context_tokens=8192, max_output_tokens=512)
        agent.replies = ['{"route": "direct"}', '{"answer": "no tools needed"}']

        captured = {}
        real = swarm_module.SwarmRunner

        class Spy(real):
            def __init__(self, *args, **kwargs):
                captured.update(kwargs)
                super().__init__(*args, **kwargs)

        monkeypatch.setattr(swarm_module, "SwarmRunner", Spy)
        run_cli(MockClass, "--swarm")

        assert captured["window"].limit_tokens == 8192 - 512

    def test_the_manifests_sdk_name_reaches_the_staged_runner(
            self, elf, tmp_path, monkeypatch):
        """The manifest is the only thing here that knows what the
        platform is called to `import`. Passing `""` instead withholds
        the `code+sdk` rung from every planner, silently — the rung is
        not offered, so nothing ever asks for it and nothing complains."""
        import core.runtime.swarm as swarm_module

        MockClass, agent = elf
        path = tmp_path / "SKILL.md"
        path.write_text(
            SKILL.replace("  output_format: A table.\n",
                          "  output_format: A table.\n  sdk_import: acme\n"),
            encoding="utf-8")
        agent.replies = [
            '{"route": "direct"}',
            json.dumps({"tool": "mcp.governed_read",
                        "arguments": {"asset_id": "asset.5f21"}}),
            json.dumps({"answer": "The asset is asset.5f21."}),
        ]

        captured = {}
        real = swarm_module.SwarmRunner

        class Spy(real):
            def __init__(self, *args, **kwargs):
                captured.update(kwargs)
                super().__init__(*args, **kwargs)

        monkeypatch.setattr(swarm_module, "SwarmRunner", Spy)
        run_cli(MockClass, "--skill", str(path), "--swarm")

        assert captured["sdk_import"] == "acme"

    def test_no_manifest_declares_no_sdk_rather_than_guessing_one(
            self, elf, monkeypatch):
        import core.runtime.swarm as swarm_module

        MockClass, agent = elf
        agent.replies = ['{"route": "direct"}', '{"answer": "no tools needed"}']

        captured = {}
        real = swarm_module.SwarmRunner

        class Spy(real):
            def __init__(self, *args, **kwargs):
                captured.update(kwargs)
                super().__init__(*args, **kwargs)

        monkeypatch.setattr(swarm_module, "SwarmRunner", Spy)
        run_cli(MockClass, "--swarm")

        assert captured["sdk_import"] == ""


class TestTheSafeDefaultGovernsTheMission:
    """Deny-by-default reaches the mission path.

    The other tests here run against a wildcard bus, which is the right
    isolation for what they check. These two build the bus at the SAFE
    profile — the real default — and assert the two halves of Phase 1: an
    MCP mission still completes under it (bridged tools carry `mcp.call`,
    a SAFE scope), and a tool whose scope SAFE does not grant is refused on
    the stream with the scope named.
    """

    def _make_safe(self, agent):
        from core.contracts.schemas import ProfileMode
        engine = CapabilityEngine()
        engine.set_profile(ProfileMode.SAFE)
        agent.tools.bus = ToolBus(capability_engine=engine)

    def test_an_mcp_mission_completes_under_the_safe_default(self, elf, skill_file, capsys):
        import json
        MockClass, agent = elf
        self._make_safe(agent)
        run_cli(MockClass, "--skill", str(skill_file), "--events", "-")
        out = capsys.readouterr().out
        records = [json.loads(line) for line in out.splitlines()
                   if line.startswith('{') and '"event"' in line]
        # The point: the governed_read call (scope mcp.call) was actually
        # dispatched and NOT refused under SAFE — the answer text alone would
        # be there whether or not the tool ran, so assert on the tool_result.
        tool_results = [r for r in records
                        if r.get("event") == "tool_result"
                        and r.get("tool") == "mcp.governed_read"]
        assert tool_results, "the mcp tool was never dispatched"
        assert tool_results[0]["ok"] is True
        assert "capability_denied" not in out

    def test_the_opening_frame_names_the_profile(self, elf, skill_file, capsys):
        import json
        MockClass, agent = elf
        self._make_safe(agent)
        # --events '-' writes the NDJSON stream to stdout alongside the prose;
        # the mission_started frame carries the OPTIONAL `profile` field.
        run_cli(MockClass, "--skill", str(skill_file), "--events", "-")
        out = capsys.readouterr().out
        started = [json.loads(line) for line in out.splitlines()
                   if line.startswith('{') and '"mission_started"' in line]
        assert started
        assert started[0].get("profile") == "safe"


class TestTheAuditIsAnnounced:
    """Where the record of this mission is being kept, said before it starts.

    Both ways round, and the absence is the louder of the two: an unaudited
    run is somebody's decision (``JUDAIS_LOBI_AUDIT=off``) and should never be
    discovered afterwards by finding an empty directory. The same fact rides
    the machine channel as ``mission_started.audit_ref``, so an operator
    reading the console and a platform reading the stream are told the same
    thing.
    """

    def _audit(self, agent, path):
        from core.policy.audit import AuditLogger

        agent.tools.bus._audit = AuditLogger(path=path)

    def test_the_path_is_printed(self, elf, tmp_path, capsys):
        MockClass, agent = elf
        self._audit(agent, tmp_path / "audit.jsonl")
        run_cli(MockClass)
        assert str(tmp_path / "audit.jsonl") in capsys.readouterr().out

    def test_the_stream_carries_the_same_path(self, elf, tmp_path):
        MockClass, agent = elf
        self._audit(agent, tmp_path / "audit.jsonl")
        events = tmp_path / "events.ndjson"
        run_cli(MockClass, "--events", str(events))
        opening = json.loads(events.read_text().splitlines()[0])
        assert opening["event"] == "mission_started"
        assert opening["audit_ref"] == str(tmp_path / "audit.jsonl")

    def test_every_dispatch_reaches_the_file(self, elf, tmp_path):
        MockClass, agent = elf
        self._audit(agent, tmp_path / "audit.jsonl")
        run_cli(MockClass)
        entries = [json.loads(line) for line
                   in (tmp_path / "audit.jsonl").read_text().splitlines()]
        assert [e["tool_name"] for e in entries] == ["mcp.governed_read"]
        assert entries[0]["verdict"] == "allowed"

    def test_no_audit_is_announced_rather_than_left_to_be_noticed(
            self, elf, capsys):
        MockClass, _agent = elf
        run_cli(MockClass)
        assert "audit: DISABLED" in capsys.readouterr().out

    def test_a_disabled_audit_is_null_on_the_stream(self, elf, tmp_path):
        MockClass, _agent = elf
        events = tmp_path / "events.ndjson"
        run_cli(MockClass, "--events", str(events))
        opening = json.loads(events.read_text().splitlines()[0])
        assert opening["audit_ref"] is None

    def test_a_write_failure_is_counted_and_printed_at_the_end(
            self, elf, tmp_path, capsys):
        """Dispatch survives a full disk; the mission does not pretend it was
        recorded. The bus says the first failure on stderr with its exception
        and the CLI prints the count when the run is over — in the ``finally``,
        because a run that ended badly is exactly the run whose audit gaps
        matter."""
        class Full:
            path = tmp_path / "audit.jsonl"

            def log(self, entry):
                raise OSError(28, "No space left on device")

        MockClass, agent = elf
        agent.tools.bus._audit = Full()
        run_cli(MockClass)
        captured = capsys.readouterr()
        assert agent.tools.bus.audit_failures == 1
        assert "could NOT be written" in captured.out
        assert "No space left on device" in captured.err
        # And the mission still answered.
        assert "asset.5f21" in captured.out


class TestTheRunIsRecorded:
    """`--mission` leaves a durable transcript, and says where it is.

    The event sink is a subscriber that may not be there — no `--events`, a
    pipe that broke, a pane that closed. The run directory is what is left
    afterwards, and a consumer that wants to replay or resume needs its id
    off the opening frame rather than guessed off a timestamp.
    """

    def runs(self, tmp_path):
        from core.durable import RunStore
        return RunStore(tmp_path / "runs")

    def test_the_console_says_which_run_this_is(self, elf, capsys, tmp_path):
        MockClass, agent = elf
        agent.replies = ['{"answer": "no tools needed"}']
        run_cli(MockClass)
        listed = self.runs(tmp_path).list()
        assert len(listed) == 1
        assert listed[0].run_id in capsys.readouterr().out

    def test_the_opening_frame_names_it_and_the_log_matches_the_stream(
            self, elf, tmp_path):
        MockClass, agent = elf
        agent.replies = ['{"answer": "no tools needed"}']
        events = tmp_path / "events.ndjson"
        run_cli(MockClass, "--events", str(events))
        streamed = [json.loads(line)
                    for line in events.read_text().strip().splitlines()]
        store = self.runs(tmp_path)
        run_id = store.list()[0].run_id
        assert streamed[0]["run_id"] == run_id
        assert store.records(run_id) == streamed

    def test_the_metadata_indexes_the_run_without_a_replay(self, elf, tmp_path):
        MockClass, agent = elf
        agent.replies = ['{"answer": "no tools needed"}']
        run_cli(MockClass)
        meta = self.runs(tmp_path).list()[0].meta
        assert meta["objective"] == "what exists?"
        assert "mcp.governed_read" in meta["catalogue"]

    def test_the_run_directory_holds_no_credential(self, elf, tmp_path,
                                                   monkeypatch):
        """A run directory outlives the process it recorded. The value of
        MCP_TOKEN written into it is a token on somebody's disk next month,
        so the transport is deliberately not among the flags that are kept."""
        secret = "mcp-tok-4f19a7c2e8b6"
        monkeypatch.setenv("MCP_TOKEN", secret)
        MockClass, agent = elf
        agent.replies = [json.dumps({"answer": f"the token is {secret}"})]
        run_cli(MockClass)
        written = "".join(path.read_text(encoding="utf-8", errors="replace")
                          for path in (tmp_path / "runs").rglob("*")
                          if path.is_file())
        assert written
        assert secret not in written

    def test_a_token_passed_as_a_flag_is_not_kept_either(self, elf, tmp_path):
        secret = "mcp-tok-0b3d9155aa42"
        MockClass, agent = elf
        agent.replies = ['{"answer": "ok"}']
        run_cli(MockClass, "--mcp-token", secret)
        written = "".join(path.read_text(encoding="utf-8", errors="replace")
                          for path in (tmp_path / "runs").rglob("*")
                          if path.is_file())
        assert secret not in written

    def test_the_flags_that_are_kept_are_the_ones_that_were_given(
            self, elf, tmp_path):
        MockClass, agent = elf
        agent.replies = ['{"answer": "ok"}']
        run_cli(MockClass, "--mission-steps", "3")
        flags = self.runs(tmp_path).list()[0].meta["flags"]
        assert flags["mission_steps"] == 3
        # `--swarm` was not passed. Its default is a *false* value rather than
        # `None`, which is the case a "skip what was not given" rule gets
        # wrong: a file recording every default is one in which the setting
        # somebody chose is invisible.
        assert "swarm" not in flags
        assert "gate_tool" not in flags

    def test_off_keeps_nothing_and_says_so(self, elf, capsys, tmp_path,
                                           monkeypatch):
        """Explicitly, like a disabled audit log: keeping no transcript is a
        decision, not something to discover later from an empty directory."""
        from core.durable import RUNS_ENV

        monkeypatch.setenv(RUNS_ENV, "off")
        MockClass, agent = elf
        agent.replies = ['{"answer": "no tools needed"}']
        events = tmp_path / "events.ndjson"
        run_cli(MockClass, "--events", str(events))
        assert "NOT RECORDED" in capsys.readouterr().out
        assert not (tmp_path / "runs").exists()
        opening = json.loads(events.read_text().splitlines()[0])
        assert "run_id" not in opening


class TestTheUsageLineOnTheConsole:
    """One line, last, and only when a provider actually reported.

    stdout is prose for a person and not a machine channel — the numbers a
    platform meters on ride `mission_finished.usage`. This is the line the
    person running the command sees, and it is rendered by the ledger
    itself so the two cannot disagree about the arithmetic.
    """

    def _usage(self, prompt, completion):
        from core.runtime.backends.base import Usage

        return Usage(prompt_tokens=prompt, completion_tokens=completion,
                     total_tokens=prompt + completion)

    def test_it_says_what_the_run_spent(self, elf, skill_file, capsys):
        MockClass, agent = elf
        agent.client.last_usage = self._usage(400, 30)
        run_cli(MockClass, "--skill", str(skill_file))
        out = capsys.readouterr().out
        assert "🧮 usage: 800 prompt + 60 completion tokens over 2 calls" in out

    def test_it_is_silent_when_the_provider_reported_nothing(
            self, elf, skill_file, capsys):
        """A line here would be a run claiming to have spent nothing, and
        "nothing reported" is not "nothing spent"."""
        MockClass, agent = elf
        agent.client.last_usage = None
        run_cli(MockClass, "--skill", str(skill_file))
        assert "🧮" not in capsys.readouterr().out

    def test_a_client_that_never_heard_of_usage_still_runs(
            self, elf, skill_file, capsys):
        MockClass, agent = elf
        del agent.client.last_usage
        agent.client.mock_add_spec(["chat", "provider"])
        run_cli(MockClass, "--skill", str(skill_file))
        out = capsys.readouterr().out
        assert "asset.5f21" in out
        assert "🧮" not in out

    def test_the_cost_appears_when_the_project_priced_the_model(
            self, elf, skill_file, capsys, tmp_path, monkeypatch):
        """`.judais-lobi.yml` in the working directory is where a price may
        come from; nothing is hard-coded and nothing is guessed."""
        (tmp_path / ".judais-lobi.yml").write_text(
            'pricing:\n  local:\n    gpt-oss-20b:\n'
            '      prompt_per_1k: 1.0\n      completion_per_1k: 2.0\n')
        monkeypatch.chdir(tmp_path)
        MockClass, agent = elf
        agent.client.last_usage = self._usage(1000, 500)
        run_cli(MockClass, "--skill", str(skill_file))
        # 2000 prompt + 1000 completion across the two calls.
        assert "— 4.0 USD" in capsys.readouterr().out

    def test_an_unpriced_model_gets_tokens_and_no_money(
            self, elf, skill_file, capsys, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        MockClass, agent = elf
        agent.client.last_usage = self._usage(10, 1)
        run_cli(MockClass, "--skill", str(skill_file))
        out = capsys.readouterr().out
        assert "🧮 usage:" in out
        assert "USD" not in out


# ── approvals, from the command line an operator actually types ──────────


@pytest.fixture
def approvals_dir(tmp_path, monkeypatch):
    """Point the durable approval store somewhere this test owns.

    Env-gated rather than injected because that is the surface: a deployment
    moves the directory with `JUDAIS_LOBI_APPROVALS`, and a suite that wrote
    into the repository's own `.judais-lobi/` would be exercising a different
    path from the one an operator gets.
    """
    from core.runtime.approvals import APPROVALS_ENV, ApprovalStore

    root = tmp_path / "approvals"
    monkeypatch.setenv(APPROVALS_ENV, str(root))
    # A wide console, because rich wraps at 80 under capture and a test
    # asserting a sentence must not also be asserting where it broke — a
    # tmp_path is long enough to be folded in half mid-directory.
    monkeypatch.setenv("COLUMNS", "200")
    return ApprovalStore(root)


def decide_cli(MockClass, *extra):
    """`--approve`/`--refuse` take no message; that is half the point."""
    from core.cli import _main
    with patch("sys.argv", ["test", "--mission", *extra]):
        _main(MockClass)


class TestTheGateWritesARecordAndSaysItsName:
    def _gated(self, MockClass, agent, skill_file, *extra):
        agent.replies = [json.dumps(
            {"tool": "mcp.governed_read",
             "arguments": {"asset_id": "asset.5f21"}})]
        run_cli(MockClass, "--skill", str(skill_file),
                "--gate-tool", "governed_read", *extra)

    def test_the_console_prints_the_id_and_the_exact_next_command(
            self, elf, skill_file, approvals_dir, capsys):
        MockClass, agent = elf
        self._gated(MockClass, agent, skill_file)

        out = capsys.readouterr().out
        pending = approvals_dir.pending()
        assert len(pending) == 1
        approval_id = pending[0].approval_id
        assert approval_id in out
        assert f"--approve {approval_id} --decided-by" in out
        assert f"--approval {approval_id}" in out

    def test_the_record_holds_the_call_and_the_objective(
            self, elf, skill_file, approvals_dir):
        MockClass, agent = elf
        self._gated(MockClass, agent, skill_file)

        recorded = approvals_dir.pending()[0]
        assert recorded.tool == "mcp.governed_read"
        assert recorded.arguments == {"asset_id": "asset.5f21"}
        assert recorded.objective == "what exists?"
        assert recorded.run_id                      # reconcilable later

    def test_the_id_rides_the_stream(self, elf, skill_file, approvals_dir,
                                     tmp_path):
        MockClass, agent = elf
        events = tmp_path / "events.ndjson"
        self._gated(MockClass, agent, skill_file, "--events", str(events))

        records = [json.loads(line) for line
                   in events.read_text().splitlines()]
        gate = [r for r in records if r["event"] == "gate_requested"][0]
        assert gate["approval_id"] == approvals_dir.pending()[0].approval_id

    def test_the_store_is_announced_where_the_gate_is(
            self, elf, skill_file, approvals_dir, capsys):
        MockClass, agent = elf
        self._gated(MockClass, agent, skill_file)
        assert f"approvals: {approvals_dir.root}" in capsys.readouterr().out

    def test_a_disabled_store_is_announced_rather_than_discovered(
            self, elf, skill_file, monkeypatch, capsys):
        """A gate with no record is a gate nobody can answer, and that must
        not be found out by looking in an empty directory."""
        from core.runtime.approvals import APPROVALS_ENV

        monkeypatch.setenv(APPROVALS_ENV, "off")
        MockClass, agent = elf
        self._gated(MockClass, agent, skill_file)

        out = capsys.readouterr().out
        assert "approvals: DISABLED" in out
        assert "no id to decide against" in out

    def test_an_ungated_mission_says_nothing_about_approvals(
            self, elf, skill_file, approvals_dir, capsys):
        MockClass, _agent = elf
        run_cli(MockClass, "--skill", str(skill_file))
        assert "approvals:" not in capsys.readouterr().out


class TestDecidingIsNotAMissionRun:
    def test_approving_names_the_decider_and_prints_how_to_resume(
            self, elf, approvals_dir, capsys):
        from core.runtime.approvals import APPROVED

        MockClass, agent = elf
        approval_id = approvals_dir.request(
            tool="mcp.governed_read", arguments={"asset_id": "asset.5f21"})
        decide_cli(MockClass, "--approve", approval_id, "--decided-by", "dana",
                   "--note", "the asset is public")

        assert approvals_dir.get(approval_id).state == APPROVED
        assert approvals_dir.get(approval_id).decided_by == "dana"
        out = capsys.readouterr().out
        assert "APPROVED by dana" in out
        assert f"--approval {approval_id}" in out
        # No agent was built, no model asked, nothing connected.
        assert agent.client.chat.call_count == 0

    def test_refusing_records_the_no(self, elf, approvals_dir, capsys):
        from core.runtime.approvals import REFUSED

        MockClass, agent = elf
        approval_id = approvals_dir.request(tool="mcp.governed_read")
        decide_cli(MockClass, "--refuse", approval_id, "--decided-by", "dana")

        assert approvals_dir.get(approval_id).state == REFUSED
        assert "REFUSED by dana" in capsys.readouterr().out
        assert agent.client.chat.call_count == 0

    def test_a_decision_that_names_nobody_is_refused(self, elf, approvals_dir):
        from core.runtime.approvals import PENDING

        MockClass, _agent = elf
        approval_id = approvals_dir.request(tool="mcp.governed_read")
        with pytest.raises(SystemExit) as exc:
            decide_cli(MockClass, "--approve", approval_id)
        assert "decided_by" in str(exc.value)
        assert approvals_dir.get(approval_id).state == PENDING

    def test_a_second_decision_is_refused(self, elf, approvals_dir):
        MockClass, _agent = elf
        approval_id = approvals_dir.request(tool="mcp.governed_read")
        decide_cli(MockClass, "--refuse", approval_id, "--decided-by", "dana")
        with pytest.raises(SystemExit) as exc:
            decide_cli(MockClass, "--approve", approval_id,
                       "--decided-by", "sam")
        assert "answered once" in str(exc.value)

    def test_an_unknown_id_is_refused(self, elf, approvals_dir):
        MockClass, _agent = elf
        with pytest.raises(SystemExit) as exc:
            decide_cli(MockClass, "--approve", "ap_deadbeefdeadbeef",
                       "--decided-by", "dana")
        assert "no approval" in str(exc.value)

    def test_both_answers_at_once_is_refused(self, elf, approvals_dir):
        MockClass, _agent = elf
        approval_id = approvals_dir.request(tool="mcp.governed_read")
        with pytest.raises(SystemExit) as exc:
            decide_cli(MockClass, "--approve", approval_id,
                       "--refuse", approval_id, "--decided-by", "dana")
        assert "Pass one" in str(exc.value)

    def test_deciding_with_no_store_is_refused(self, elf, monkeypatch):
        from core.runtime.approvals import APPROVALS_ENV

        monkeypatch.setenv(APPROVALS_ENV, "none")
        MockClass, _agent = elf
        with pytest.raises(SystemExit) as exc:
            decide_cli(MockClass, "--approve", "ap_deadbeefdeadbeef",
                       "--decided-by", "dana")
        assert APPROVALS_ENV in str(exc.value)

    def test_a_message_is_still_required_of_everything_else(self, elf):
        """`message` went optional so a decision need not pretend to be one.
        Every other path still refuses without it, in this repo's words."""
        from core.cli import _main

        MockClass, _agent = elf
        with patch("sys.argv", ["test", "--mission"]):
            with pytest.raises(SystemExit) as exc:
                _main(MockClass)
        assert "a message is required" in str(exc.value)


class TestResumingWithAnApproval:
    def test_the_approved_tool_is_no_longer_gated_and_is_called(
            self, elf, skill_file, approvals_dir, tmp_path, capsys):
        from core.runtime.approvals import SPENT

        MockClass, agent = elf
        approval_id = approvals_dir.request(
            tool="mcp.governed_read", arguments={"asset_id": "asset.5f21"})
        approvals_dir.decide(approval_id, approve=True, decided_by="dana")

        events = tmp_path / "events.ndjson"
        run_cli(MockClass, "--skill", str(skill_file),
                "--gate-tool", "governed_read",
                "--approval", approval_id, "--events", str(events))

        opening = json.loads(events.read_text().splitlines()[0])
        # The widening a consumer sees: the tool is simply not in `gated`.
        assert opening["gated"] == []
        assert "mcp.governed_read" in opening["catalogue"]
        out = capsys.readouterr().out
        assert f"approval {approval_id}" in out
        assert "asset.5f21" in out                  # it answered
        assert approvals_dir.get(approval_id).state == SPENT

    def test_the_run_after_it_gates_the_tool_again(
            self, elf, skill_file, approvals_dir):
        """One tool, one run. Nothing anywhere says this operator approves
        governed reads."""
        MockClass, agent = elf
        approval_id = approvals_dir.request(tool="mcp.governed_read")
        approvals_dir.decide(approval_id, approve=True, decided_by="dana")
        run_cli(MockClass, "--skill", str(skill_file),
                "--gate-tool", "governed_read", "--approval", approval_id)

        agent.replies = [json.dumps(
            {"tool": "mcp.governed_read",
             "arguments": {"asset_id": "asset.5f21"}})]
        with pytest.raises(SystemExit) as exc:
            run_cli(MockClass, "--skill", str(skill_file),
                    "--gate-tool", "governed_read", "--approval", approval_id)
        assert "spent" in str(exc.value)

    @pytest.mark.parametrize("state,arrange", [
        ("pending", lambda s, i: None),
        ("refused", lambda s, i: s.decide(i, approve=False, decided_by="dana")),
        ("abandoned", lambda s, i: s.abandon(i)),
    ])
    def test_anything_but_approved_is_refused_at_the_door(
            self, elf, skill_file, approvals_dir, state, arrange):
        """Named, and before the model is asked. Nothing defaults into a yes,
        and an operator who pasted the wrong id finds out in a second."""
        MockClass, agent = elf
        approval_id = approvals_dir.request(tool="mcp.governed_read")
        arrange(approvals_dir, approval_id)

        with pytest.raises(SystemExit) as exc:
            run_cli(MockClass, "--skill", str(skill_file),
                    "--gate-tool", "governed_read", "--approval", approval_id)
        assert state in str(exc.value)
        assert agent.client.chat.call_count == 0

    def test_an_id_nobody_wrote_is_refused_at_the_door(
            self, elf, skill_file, approvals_dir):
        MockClass, agent = elf
        with pytest.raises(SystemExit) as exc:
            run_cli(MockClass, "--skill", str(skill_file),
                    "--approval", "ap_deadbeefdeadbeef")
        assert "no approval" in str(exc.value)
        assert agent.client.chat.call_count == 0

    def test_an_approval_for_a_tool_this_run_does_not_gate_says_so(
            self, elf, skill_file, approvals_dir, capsys):
        """It widened nothing, and it is not spent. Silence here would read as
        a resume that worked."""
        from core.runtime.approvals import APPROVED

        MockClass, _agent = elf
        approval_id = approvals_dir.request(tool="mcp.something_else")
        approvals_dir.decide(approval_id, approve=True, decided_by="dana")
        run_cli(MockClass, "--skill", str(skill_file),
                "--gate-tool", "governed_read", "--approval", approval_id)

        assert "does not gate" in capsys.readouterr().out
        assert approvals_dir.get(approval_id).state == APPROVED


def resume_argv(run_id, *extra):
    """``judais --mission --resume <id>`` — and no positional message.

    Omitting it is the point: the objective is on the record, and typing one
    that is not the recorded objective is the mistake the door refuses.
    """
    return ["test", "--mission", "--resume", run_id,
            "--mcp-stdio", f"{sys.executable} {STUB}", *extra]


def run_resume(MockClass, run_id, *extra):
    from core.cli import _main
    with patch("sys.argv", resume_argv(run_id, *extra)):
        _main(MockClass)


class TestResumingFromTheCommandLine:
    """`--resume` against the real stub server, killed at a step boundary.

    The kill is a model that raises on its second call, which is what a
    served endpoint going away looks like from in here — and the outermost
    frame of mission mode turns it into `SystemExit(1)` with a scrubbed
    traceback, so the recorded run ends `incomplete` with its log closed
    from the `finally`. That is the state a resume actually meets.
    """

    def runs(self, tmp_path):
        from core.durable import RunStore
        return RunStore(tmp_path / "runs")

    def kill_after_one_step(self, agent):
        """One tool call, then the model server goes away."""
        first = [json.dumps({"tool": "mcp.governed_read",
                             "arguments": {"asset_id": "asset.5f21"}})]

        def _chat(**kw):
            agent.seeds.append([dict(m) for m in kw["messages"]])
            if first:
                return first.pop(0)
            raise RuntimeError("the model server went away")

        agent.client.chat.side_effect = _chat

    def killed(self, MockClass, agent, tmp_path):
        self.kill_after_one_step(agent)
        with pytest.raises(SystemExit):
            run_cli(MockClass)
        listed = self.runs(tmp_path).list()
        assert len(listed) == 1
        return listed[0].run_id

    def answer_next(self, agent, text="The asset is asset.5f21."):
        agent.replies = [json.dumps({"answer": text})]

        def _chat(**kw):
            agent.seeds.append([dict(m) for m in kw["messages"]])
            return agent.replies.pop(0) if agent.replies else '{"answer": "d"}'

        agent.client.chat.side_effect = _chat

    def test_the_resumed_mission_finishes_in_the_same_run_directory(
            self, elf, tmp_path, capsys):
        MockClass, agent = elf
        run_id = self.killed(MockClass, agent, tmp_path)
        self.answer_next(agent)
        run_resume(MockClass, run_id)
        out = capsys.readouterr().out
        assert "asset.5f21" in out
        assert len(self.runs(tmp_path).list()) == 1
        assert self.runs(tmp_path).list()[0].run_id == run_id

    def test_the_log_holds_one_opening_and_the_resumed_step_says_so(
            self, elf, tmp_path):
        MockClass, agent = elf
        run_id = self.killed(MockClass, agent, tmp_path)
        self.answer_next(agent)
        run_resume(MockClass, run_id)
        records = self.runs(tmp_path).records(run_id)
        assert [r["event"] for r in records].count("mission_started") == 1
        carrying = [r for r in records
                    if r["event"] == "step_started" and "resumed" in r]
        assert len(carrying) == 1

    def test_the_resumed_model_is_shown_the_earlier_tool_result(
            self, elf, tmp_path):
        """The whole point of the replay. The first thing the resuming
        process asks the model already contains the governed read the killed
        process made — otherwise the mission starts over in everything but
        the log."""
        MockClass, agent = elf
        run_id = self.killed(MockClass, agent, tmp_path)
        agent.seeds.clear()
        self.answer_next(agent)
        run_resume(MockClass, run_id)
        first_ask = agent.seeds[0]
        assert first_ask[-1]["role"] == "user"
        assert "Result of mcp.governed_read" in first_ask[-1]["content"]

    def test_the_objective_comes_off_the_record(self, elf, tmp_path, capsys):
        MockClass, agent = elf
        run_id = self.killed(MockClass, agent, tmp_path)
        agent.seeds.clear()
        self.answer_next(agent)
        run_resume(MockClass, run_id)
        # `argv()` started the run with "what exists?" and `resume_argv`
        # passes no message at all.
        assert agent.seeds[0][1] == {"role": "user", "content": "what exists?"}

    def test_a_different_objective_is_refused_naming_both(self, elf, tmp_path):
        MockClass, agent = elf
        run_id = self.killed(MockClass, agent, tmp_path)
        from core.cli import _main
        with patch("sys.argv", ["test", "something else entirely", "--mission",
                                "--resume", run_id, "--mcp-stdio",
                                f"{sys.executable} {STUB}"]):
            with pytest.raises(SystemExit) as exc:
                _main(MockClass)
        assert "what exists?" in str(exc.value)
        assert "something else entirely" in str(exc.value)

    def test_an_unknown_run_is_refused_before_the_server_is_dialled(
            self, elf, tmp_path):
        MockClass, agent = elf
        with pytest.raises(SystemExit) as exc:
            run_resume(MockClass, "run_20260101T000000-deadbeef")
        assert "no run 'run_20260101T000000-deadbeef'" in str(exc.value)
        # Nothing was asked and nothing was connected to.
        assert agent.client.chat.call_count == 0

    def test_a_finished_run_is_refused_naming_its_outcome(self, elf, tmp_path):
        MockClass, agent = elf
        agent.replies = ['{"answer": "no tools needed"}']
        run_cli(MockClass)
        run_id = self.runs(tmp_path).list()[0].run_id
        with pytest.raises(SystemExit) as exc:
            run_resume(MockClass, run_id)
        assert "'answered'" in str(exc.value)

    def test_resume_without_mission_is_refused(self, elf, capsys):
        """A chat turn keeps its own history and is not a run. Asserted on
        the SENTENCE and not merely on the exit: this argv would exit anyway
        the moment something else refused it, and a test that could not tell
        the two apart would pass over the guard being deleted."""
        MockClass, _agent = elf
        from core.cli import _main
        with patch("sys.argv", ["test", "hello", "--resume", "run_abcd1234"]):
            with pytest.raises(SystemExit):
                _main(MockClass)
        assert "--resume continues a recorded MISSION" in capsys.readouterr().err

    def test_no_message_and_no_resume_is_refused(self, elf, capsys):
        """The positional is optional at the parser and required here,
        because argparse cannot say "required unless another flag is set".
        A server is named in this argv on purpose, so the only thing left to
        refuse is the missing message."""
        MockClass, _agent = elf
        from core.cli import _main
        with patch("sys.argv", ["test", "--mission", "--mcp-stdio",
                                f"{sys.executable} {STUB}"]):
            with pytest.raises(SystemExit) as exc:
                _main(MockClass)
        assert "a message is required" in str(exc.value)

    def test_the_run_directory_still_holds_no_credential_after_a_resume(
            self, elf, tmp_path, monkeypatch):
        """Re-read, never recovered: MCP_TOKEN comes off the environment of
        the resuming process, and the directory it resumed from has never
        held it."""
        secret = "mcp-tok-9c22ab410d7e"
        monkeypatch.setenv("MCP_TOKEN", secret)
        MockClass, agent = elf
        run_id = self.killed(MockClass, agent, tmp_path)
        self.answer_next(agent, f"the token is {secret}")
        run_resume(MockClass, run_id)
        written = "".join(path.read_text(encoding="utf-8", errors="replace")
                          for path in (tmp_path / "runs").rglob("*")
                          if path.is_file())
        assert written
        assert secret not in written

    def test_an_orphan_is_reconciled_and_announced(self, elf, tmp_path,
                                                   capsys):
        """A run with no `mission_finished`, untouched past the staleness
        rule, is closed by the next mission that comes along — so a follower
        of its stream is told it is over rather than waiting forever."""
        import datetime

        from core.runtime.resume import ORPHAN_STALE_S

        MockClass, agent = elf
        store = self.runs(tmp_path)
        orphan = store.create(meta={"objective": "one that died"}).run_id
        record = json.loads(store.meta_path(orphan).read_text())
        record["updated_at"] = (
            datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(seconds=ORPHAN_STALE_S + 10)
        ).isoformat(timespec="seconds")
        store.meta_path(orphan).write_text(json.dumps(record))

        agent.replies = ['{"answer": "no tools needed"}']
        run_cli(MockClass)
        assert "reconciled: 1 orphaned run(s)" in capsys.readouterr().out
        assert [r["event"] for r in store.records(orphan)] == \
            ["mission_finished"]
        assert store.records(orphan)[0]["outcome"] == "incomplete"

    def test_a_fresh_run_of_this_process_is_never_reconciled(self, elf,
                                                             tmp_path, capsys):
        MockClass, agent = elf
        agent.replies = ['{"answer": "no tools needed"}']
        run_cli(MockClass)
        assert "reconciled" not in capsys.readouterr().out


# ---------------------------------------------------------------------------
# `--protocol native`, against the real stub server
# ---------------------------------------------------------------------------


def native_call(name, _id=None, **arguments):
    return {"id": _id or f"c_{name}", "name": name, "arguments": arguments}


def native_answer(text, _id="ans"):
    return native_call("mission_answer", _id, text=text)


class TestTheNativeProtocolFromTheCommandLine:
    """The wiring an operator actually touches, over the real MCP stub.

    The model is a mock — there is no local vLLM in a test suite — but the
    tool plane is the real FastMCP server over stdio, so what is exercised
    is the actual sequence: declare the discovered tools as functions,
    constrain the decoder to them, read the calls off the side channel,
    dispatch each through the bridge, and answer.
    """

    def capable(self, agent, **overrides):
        """A backend that declares what the native protocol is made of.

        A ``SimpleNamespace`` and not a ``MagicMock``: every attribute of a
        mock is truthy, so a mock would declare every capability there has
        ever been and the door below would never refuse anything.
        """
        agent.client.capabilities = SimpleNamespace(
            supports_tool_calls=True, supports_tool_choice_required=True,
            **overrides)

    def script(self, agent, *turns):
        """The backend's two channels: content from `chat`, calls beside it."""
        queue = list(turns)

        def _chat(**kw):
            agent.seeds.append([dict(m) for m in kw["messages"]])
            calls = queue.pop(0) if queue else [native_answer("done")]
            agent.client.last_tool_calls = list(calls)
            return ""

        agent.client.chat.side_effect = _chat

    def body(self, agent, index=0):
        return agent.client.chat.call_args_list[index].kwargs

    # ── the request ────────────────────────────────────────────────────

    def test_the_request_declares_the_tools_and_constrains_the_decoder(
            self, elf, skill_file):
        MockClass, agent = elf
        self.capable(agent)
        self.script(agent, [native_answer("nothing to do")])
        run_cli(MockClass, "--skill", str(skill_file), "--protocol", "native")
        body = self.body(agent)
        assert body["tool_choice"] == "required"
        assert body["parallel_tool_calls"] is True
        assert [t["function"]["name"] for t in body["tools"]] == \
            ["mcp.governed_read", "mission_result", "mission_answer"]

    def test_the_answer_function_carries_its_own_schema(self, elf, skill_file):
        MockClass, agent = elf
        self.capable(agent)
        self.script(agent, [native_answer("nothing to do")])
        run_cli(MockClass, "--skill", str(skill_file), "--protocol", "native")
        answer = [t for t in self.body(agent)["tools"]
                  if t["function"]["name"] == "mission_answer"][0]
        assert answer["function"]["parameters"]["required"] == ["text"]

    def test_the_json_protocol_still_asks_for_auto(self, elf, skill_file):
        """The default is untouched, down to the two keys on the request."""
        MockClass, agent = elf
        run_cli(MockClass, "--skill", str(skill_file))
        body = self.body(agent)
        assert body["tool_choice"] == "auto"
        assert "parallel_tool_calls" not in body
        assert [t["function"]["name"] for t in body["tools"]] == \
            ["mcp.governed_read"]

    # ── the run ────────────────────────────────────────────────────────

    def test_a_native_mission_calls_the_server_and_answers(
            self, elf, skill_file, capsys):
        MockClass, agent = elf
        self.capable(agent)
        self.script(
            agent,
            [native_call("mcp.governed_read", "c0", asset_id="asset.5f21")],
            [native_answer("The asset is asset.5f21.")])
        run_cli(MockClass, "--skill", str(skill_file), "--protocol", "native")
        out = capsys.readouterr().out
        assert "The asset is asset.5f21." in out
        assert "protocol: native" in out

    def test_two_calls_in_one_turn_both_reach_the_server(
            self, elf, skill_file, capsys):
        MockClass, agent = elf
        self.capable(agent)
        self.script(
            agent,
            [native_call("mcp.governed_read", "c0", asset_id="asset.5f21"),
             native_call("mcp.governed_read", "c1", asset_id="asset.9a02")],
            [native_answer("Both read.")])
        run_cli(MockClass, "--skill", str(skill_file), "--protocol", "native")
        out = capsys.readouterr().out
        assert "asset.5f21" in out and "asset.9a02" in out
        # And the model was shown BOTH results, each quoting its own call.
        second = agent.seeds[1]
        assert [m["tool_call_id"] for m in second if m["role"] == "tool"] == \
            ["c0", "c1"]
        assert "results only, never source" in second[-1]["content"]

    def test_the_wire_shape_of_the_second_ask_is_the_openai_one(
            self, elf, skill_file):
        MockClass, agent = elf
        self.capable(agent)
        self.script(
            agent,
            [native_call("mcp.governed_read", "c0", asset_id="asset.5f21")],
            [native_answer("done")])
        run_cli(MockClass, "--skill", str(skill_file), "--protocol", "native")
        assistant = [m for m in agent.seeds[1] if m["role"] == "assistant"][0]
        assert assistant["tool_calls"][0]["id"] == "c0"
        assert assistant["tool_calls"][0]["function"]["name"] == \
            "mcp.governed_read"

    def test_the_opening_frame_and_the_log_say_native(self, elf, tmp_path,
                                                      skill_file):
        from core.durable import RunStore

        MockClass, agent = elf
        self.capable(agent)
        self.script(agent, [native_answer("done")])
        run_cli(MockClass, "--skill", str(skill_file), "--protocol", "native")
        store = RunStore(tmp_path / "runs")
        records = store.records(store.list()[0].run_id)
        assert records[0]["event"] == "mission_started"
        assert records[0]["protocol"] == "native"

    def test_the_environment_form_is_the_flags_default(self, elf, skill_file,
                                                       monkeypatch, capsys):
        MockClass, agent = elf
        monkeypatch.setenv("MISSION_PROTOCOL", "native")
        self.capable(agent)
        self.script(agent, [native_answer("done")])
        run_cli(MockClass, "--skill", str(skill_file))
        assert "protocol: native" in capsys.readouterr().out

    # ── the refusals ───────────────────────────────────────────────────

    def test_a_backend_without_the_capability_is_refused_at_the_door(
            self, elf, skill_file):
        """Naming both the capability and the way out. A run that asked for
        the constrained decoder and silently got prose would be measured as
        the protocol it was not running."""
        from core.runtime.backends.base import BackendCapabilities

        MockClass, agent = elf
        agent.client.capabilities = BackendCapabilities(
            supports_tool_calls=True)
        with pytest.raises(SystemExit) as exc:
            run_cli(MockClass, "--skill", str(skill_file),
                    "--protocol", "native")
        assert "supports_tool_choice_required" in str(exc.value)
        assert "--protocol json" in str(exc.value)

    def test_it_is_refused_before_the_model_is_asked(self, elf, skill_file):
        from core.runtime.backends.base import BackendCapabilities

        MockClass, agent = elf
        agent.client.capabilities = BackendCapabilities()
        with pytest.raises(SystemExit):
            run_cli(MockClass, "--skill", str(skill_file),
                    "--protocol", "native")
        assert agent.client.chat.call_args_list == []

    def test_a_word_that_is_neither_protocol_is_refused_naming_both(
            self, elf, skill_file):
        MockClass, _agent = elf
        with pytest.raises(SystemExit) as exc:
            run_cli(MockClass, "--skill", str(skill_file),
                    "--protocol", "functions")
        assert "json" in str(exc.value) and "native" in str(exc.value)


class TestResumingANativeRun:
    """The replay has to rebuild the shape the run was recorded in.

    A native turn is an assistant message carrying `tool_calls` answered by
    `tool` messages; rebuilding it as text and sending it back is a 400 at
    best and a model reading somebody else's transcript at worst. So the
    protocol comes off the record, and a command line that disagrees with
    the record is refused like a mismatched objective.
    """

    def runs(self, tmp_path):
        from core.durable import RunStore
        return RunStore(tmp_path / "runs")

    def capable(self, agent):
        agent.client.capabilities = SimpleNamespace(
            supports_tool_calls=True, supports_tool_choice_required=True)

    def killed(self, MockClass, agent, tmp_path):
        """One native tool call, then the model server goes away."""
        self.capable(agent)
        first = [[native_call("mcp.governed_read", "c0",
                              asset_id="asset.5f21")]]

        def _chat(**kw):
            agent.seeds.append([dict(m) for m in kw["messages"]])
            if first:
                agent.client.last_tool_calls = list(first.pop(0))
                return ""
            raise RuntimeError("the model server went away")

        agent.client.chat.side_effect = _chat
        with pytest.raises(SystemExit):
            run_cli(MockClass, "--protocol", "native")
        listed = self.runs(tmp_path).list()
        assert len(listed) == 1
        return listed[0].run_id

    def answer_next(self, agent):
        def _chat(**kw):
            agent.seeds.append([dict(m) for m in kw["messages"]])
            agent.client.last_tool_calls = [native_answer("It is asset.5f21.")]
            return ""

        agent.client.chat.side_effect = _chat

    def test_the_resumed_run_finishes_in_the_same_directory(self, elf,
                                                            tmp_path, capsys):
        MockClass, agent = elf
        run_id = self.killed(MockClass, agent, tmp_path)
        self.answer_next(agent)
        run_resume(MockClass, run_id)
        assert "It is asset.5f21." in capsys.readouterr().out
        assert [r.run_id for r in self.runs(tmp_path).list()] == [run_id]

    def test_the_protocol_comes_off_the_record_without_being_restated(
            self, elf, tmp_path, capsys):
        MockClass, agent = elf
        run_id = self.killed(MockClass, agent, tmp_path)
        self.answer_next(agent)
        run_resume(MockClass, run_id)
        out = capsys.readouterr().out
        assert "protocol: native" in out
        # And the request it made is the native one, not the default.
        assert agent.client.chat.call_args_list[-1].kwargs["tool_choice"] == \
            "required"

    def test_the_replayed_turn_is_rebuilt_as_tool_calls_and_results(
            self, elf, tmp_path):
        """The whole point. The first thing the resuming process asks
        already contains the governed read, in the shape the model made
        it — an assistant turn with `tool_calls`, answered by a `tool`
        message quoting the id."""
        MockClass, agent = elf
        run_id = self.killed(MockClass, agent, tmp_path)
        agent.seeds.clear()
        self.answer_next(agent)
        run_resume(MockClass, run_id)
        first_ask = agent.seeds[0]
        assistant = [m for m in first_ask if m["role"] == "assistant"][0]
        results = [m for m in first_ask if m["role"] == "tool"]
        assert assistant["tool_calls"][0]["function"]["name"] == \
            "mcp.governed_read"
        assert results[0]["tool_call_id"] == \
            assistant["tool_calls"][0]["id"]
        assert "Result of mcp.governed_read" in results[0]["content"]

    def test_the_minted_ids_are_said_out_loud_rather_than_passed_off(
            self, elf, tmp_path, capsys):
        """A `tool_call_id` is the provider's and never travelled on the
        stream, so the rebuilt turns quote ids this process invented."""
        MockClass, agent = elf
        run_id = self.killed(MockClass, agent, tmp_path)
        self.answer_next(agent)
        run_resume(MockClass, run_id)
        assert "not replayed:" in capsys.readouterr().out

    def test_a_protocol_that_disagrees_with_the_record_is_refused(
            self, elf, tmp_path):
        MockClass, agent = elf
        run_id = self.killed(MockClass, agent, tmp_path)
        self.answer_next(agent)
        with pytest.raises(SystemExit) as exc:
            run_resume(MockClass, run_id, "--protocol", "json")
        assert "recorded under --protocol native" in str(exc.value)

    def test_a_json_run_resumed_as_native_is_refused_too(self, elf, tmp_path):
        MockClass, agent = elf
        first = [json.dumps({"tool": "mcp.governed_read",
                             "arguments": {"asset_id": "asset.5f21"}})]

        def _chat(**kw):
            agent.seeds.append([dict(m) for m in kw["messages"]])
            if first:
                return first.pop(0)
            raise RuntimeError("the model server went away")

        agent.client.chat.side_effect = _chat
        with pytest.raises(SystemExit):
            run_cli(MockClass)
        run_id = self.runs(tmp_path).list()[0].run_id
        self.capable(agent)
        with pytest.raises(SystemExit) as exc:
            run_resume(MockClass, run_id, "--protocol", "native")
        assert "recorded under --protocol json" in str(exc.value)


class TestTheAnswerArrivesWhileItIsWritten:
    """Streaming, from the flag an operator types to the line they read.

    The wiring is the part worth exercising here rather than in
    `test_mission.py`: whether `stream=` reaches the client at all, what
    `--no-stream` and `MISSION_STREAM` do to it, and whether the fragments
    make it both onto the machine channel and onto stdout.
    """

    ANSWER = "The asset is asset.5f21."

    def streaming(self, agent):
        """A client that yields frames when it is asked to stream.

        Its `chat` still returns a string when it is not, because that is
        the shape every backend in this tree has — and because half of
        what is asserted below is that the string path is untouched.
        """
        replies = [
            json.dumps({"tool": "mcp.governed_read",
                        "arguments": {"asset_id": "asset.5f21"}}),
            json.dumps({"answer": self.ANSWER}),
        ]

        def frames(reply):
            for at in range(0, len(reply), 4):
                yield SimpleNamespace(choices=[SimpleNamespace(
                    delta=SimpleNamespace(content=reply[at:at + 4],
                                          tool_calls=None))])

        def _chat(**kw):
            agent.seeds.append([dict(m) for m in kw["messages"]])
            agent.streamed.append(kw.get("stream"))
            reply = replies.pop(0) if replies else '{"answer": "done"}'
            return frames(reply) if kw.get("stream") else reply

        agent.streamed = []
        agent.client.chat.side_effect = _chat
        # The capability is asked before the flag is consulted, and a
        # MagicMock attribute is truthy by accident rather than by
        # declaration. Said out loud so the two tests that turn streaming
        # OFF are turning off something that was on.
        agent.client.capabilities = SimpleNamespace(supports_streaming=True)
        return agent

    def records(self, path):
        return [json.loads(line) for line in
                path.read_text().splitlines() if line]

    def test_the_fragments_reach_the_stream_and_the_answer_follows(
            self, elf, tmp_path):
        MockClass, agent = elf
        self.streaming(agent)
        events = tmp_path / "events.ndjson"
        run_cli(MockClass, "--events", str(events))
        records = self.records(events)
        fragments = [r for r in records if r["event"] == "answer_delta"]
        assert fragments
        assert "".join(r["text"] for r in fragments) == self.ANSWER
        assert [r["text"] for r in records
                if r["event"] == "answer"] == [self.ANSWER]

    def test_the_fragments_belong_to_the_step_that_wrote_them(
            self, elf, tmp_path):
        """The first turn called a tool and streamed no answer; the
        second one is the answer."""
        MockClass, agent = elf
        self.streaming(agent)
        events = tmp_path / "events.ndjson"
        run_cli(MockClass, "--events", str(events))
        fragments = [r for r in self.records(events)
                     if r["event"] == "answer_delta"]
        assert {r["index"] for r in fragments} == {1}
        assert [r["part"] for r in fragments] == list(range(len(fragments)))

    def test_the_console_prints_it_as_it_arrives(self, elf, capsys):
        """Twice: once live under a `🧞 Tai:` header while the model is
        writing, and once in the transcript printed afterwards, which is
        unchanged."""
        MockClass, agent = elf
        self.streaming(agent)
        run_cli(MockClass)
        out = capsys.readouterr().out
        assert out.count(self.ANSWER) == 2
        assert "streaming:" in out

    def test_no_stream_asks_the_client_for_the_whole_reply(self, elf,
                                                           tmp_path):
        MockClass, agent = elf
        self.streaming(agent)
        events = tmp_path / "events.ndjson"
        run_cli(MockClass, "--no-stream", "--events", str(events))
        assert agent.streamed == [False, False]
        assert not [r for r in self.records(events)
                    if r["event"] == "answer_delta"]
        assert [r["text"] for r in self.records(events)
                if r["event"] == "answer"] == [self.ANSWER]

    def test_the_environment_says_it_too(self, elf, tmp_path, monkeypatch):
        MockClass, agent = elf
        self.streaming(agent)
        monkeypatch.setenv("MISSION_STREAM", "off")
        events = tmp_path / "events.ndjson"
        run_cli(MockClass, "--events", str(events))
        assert agent.streamed == [False, False]
        assert not [r for r in self.records(events)
                    if r["event"] == "answer_delta"]

    def test_a_backend_that_cannot_stream_is_not_asked_to(self, elf):
        MockClass, agent = elf
        self.streaming(agent)
        agent.client.capabilities = SimpleNamespace(supports_streaming=False)
        run_cli(MockClass)
        assert agent.streamed == [False, False]

    def test_streaming_is_on_without_anybody_saying_so(self, elf):
        MockClass, agent = elf
        self.streaming(agent)
        run_cli(MockClass)
        assert agent.streamed == [True, True]


class TestTheControlChannelFromTheCommandLine:
    """`--control fd:N`, through the real CLI and the real stub server.

    The commands are written into a real pipe before the run, which is the
    only arrangement that exercises the whole path: argparse, the open at
    the door, the daemon reader, the drain in the loop, and the close in
    the same `finally` as the sink.
    """

    def _pipe(self, *payloads):
        read_fd, write_fd = os.pipe()
        with os.fdopen(write_fd, "w", encoding="utf-8") as writer:
            for payload in payloads:
                writer.write(json.dumps(payload) + "\n")
        return read_fd

    def _channels(self, monkeypatch):
        """Every channel the CLI opens, so a test can ask what became of
        it. The real class, wrapped — the point is what `_mission` does
        with the object, not what a double would have recorded."""
        from core.runtime.control import ControlChannel

        made = []
        real = ControlChannel.open.__func__

        def opened(cls, spec, **kwargs):
            channel = real(cls, spec, **kwargs)
            if channel is not None:
                made.append(channel)
            return channel

        monkeypatch.setattr(ControlChannel, "open", classmethod(opened))
        return made

    def _settled(self, made, seconds=2.0):
        import time

        until = time.monotonic() + seconds
        while time.monotonic() < until:
            if made and made[0].waiting:
                return
            time.sleep(0.002)

    def test_an_injection_written_before_the_run_reaches_the_model(
            self, elf, skill_file, monkeypatch):
        MockClass, agent = elf
        made = self._channels(monkeypatch)
        fd = self._pipe({"control": "inject",
                         "text": "the SECOND corpus, not the first"})
        run_cli(MockClass, "--skill", str(skill_file), "--control", f"fd:{fd}")

        assert agent.seeds[0][-1] == {
            "role": "user", "content": "the SECOND corpus, not the first"}
        assert made and made[0].spec == f"fd:{fd}"

    def test_the_step_it_rode_says_so_on_the_event_stream(
            self, elf, skill_file, monkeypatch):
        import core.runtime.mission_stream as stream

        MockClass, _agent = elf
        self._channels(monkeypatch)
        sink = RecordingSink()
        monkeypatch.setattr(stream, "open_sink", lambda spec: sink)
        fd = self._pipe({"control": "inject", "text": "narrow it down"})
        run_cli(MockClass, "--skill", str(skill_file), "--control", f"fd:{fd}")

        started = [r for r in sink.records if r["event"] == "step_started"]
        assert started[0]["injected"] == ["narrow it down"]

    def test_the_channel_is_closed_in_the_same_finally_as_the_sink(
            self, elf, skill_file, monkeypatch):
        """The descriptor belongs to whoever spawned us, and a run that
        ended badly is exactly the one that must still let go of it."""
        MockClass, _agent = elf
        made = self._channels(monkeypatch)
        fd = self._pipe({"control": "inject", "text": "x"})
        run_cli(MockClass, "--skill", str(skill_file), "--control", f"fd:{fd}")
        assert made[0].closed

    def test_a_cancel_on_the_channel_winds_the_run_up(
            self, elf, skill_file, monkeypatch):
        import core.runtime.mission_stream as stream

        MockClass, _agent = elf
        self._channels(monkeypatch)
        sink = RecordingSink()
        monkeypatch.setattr(stream, "open_sink", lambda spec: sink)
        fd = self._pipe({"control": "cancel"})
        run_cli(MockClass, "--skill", str(skill_file), "--control", f"fd:{fd}")

        last = sink.records[-1]
        assert last["event"] == "mission_finished"
        assert last["reason"] == "cancelled"

    def test_a_bad_spec_is_refused_at_the_door(self, elf, skill_file):
        """Like `--events`: a spec that cannot be opened is a refusal, not
        a channel that silently delivers nothing."""
        MockClass, _agent = elf
        with pytest.raises(SystemExit) as exc:
            run_cli(MockClass, "--skill", str(skill_file),
                    "--control", "fd:nine")
        assert "--control" in str(exc.value)

    def test_no_flag_is_no_channel_and_no_runner_keyword_changes(
            self, elf, skill_file, monkeypatch):
        import core.runtime.mission as mission_module

        MockClass, _agent = elf
        made = self._channels(monkeypatch)
        captured = {}
        real = mission_module.MissionRunner

        def watched(*args, **kwargs):
            captured.update(kwargs)
            return real(*args, **kwargs)

        monkeypatch.setattr(mission_module, "MissionRunner", watched)
        run_cli(MockClass, "--skill", str(skill_file))
        assert made == []
        assert captured["control"] is None

    def test_the_environment_form_is_the_flags_default(
            self, elf, skill_file, monkeypatch):
        MockClass, agent = elf
        self._channels(monkeypatch)
        fd = self._pipe({"control": "inject", "text": "from the environment"})
        monkeypatch.setenv("MISSION_CONTROL", f"fd:{fd}")
        run_cli(MockClass, "--skill", str(skill_file))
        assert agent.seeds[0][-1]["content"] == "from the environment"
