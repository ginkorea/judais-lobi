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
        end of the pipe waits on a descriptor nobody will shut."""
        import core.runtime.mission_stream as stream

        MockClass, _agent = elf
        sink, handed = RecordingSink(), []
        monkeypatch.setattr(stream, "open_sink", lambda spec: sink)
        monkeypatch.setattr(stream, "close_on_sigterm", handed.append)

        run_cli(MockClass, "--skill", str(skill_file))

        assert handed == [sink]
        # The same object, not merely one of the same kind: what the
        # handler flushes has to be what the mission was writing to.
        assert sink.records and sink.closed == 1

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
