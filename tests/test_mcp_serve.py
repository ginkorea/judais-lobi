# tests/test_mcp_serve.py — the built-in tools, served over MCP

"""One owner, two transports — asserted by running both.

``core.tools.serve`` publishes the tools that are already on a
:class:`~core.tools.bus.ToolBus` and dispatches every call back through it.
The claim that makes it worth having is **parity**: a client that reaches
``fs`` over the protocol gets the same answer, under the same profile, with
the same refusal sentence and the same audit row, as a caller that dispatched
it in-process.  Every test below is that claim in one respect, and the ones
that matter compare the two answers rather than asserting a remembered shape.

The server is spawned as a real subprocess and spoken to with this
package's own MCP client, so what is exercised is the protocol and not a
rehearsal of it.
"""

import dataclasses
import json
import sys
import textwrap
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.contracts.schemas import PolicyPack
from core.tools.bus import ToolBus
from core.tools.capability import CapabilityEngine
from core.tools.sandbox import NoneSandbox, select_sandbox

pytest.importorskip("mcp", reason="the MCP server is an optional extra")

from core.tools.mcp_client import McpClient, McpToolBridge, StdioTransport  # noqa: E402
from core.tools.serve import (  # noqa: E402
    build_tools, describe_served, input_schema_for, result_payload,
    result_text, schema_from_signature, served_names,
)

# `StreamableHttpTransport` deliberately uses `streamablehttp_client`; see
# the comment there for why the "replacement" is not one. Same filter as
# `tests/test_mcp_client.py`, for the same deprecation.
pytestmark = pytest.mark.filterwarnings(
    "ignore:Use `streamable_http_client` instead.:DeprecationWarning"
)

#: The command an operator writes, and the one every test spawns.
SERVE = [sys.executable, "-m", "core.tools.serve"]

#: The same command as a `--mcp-stdio` string, for the mission tests.
#: `--audit off` because the SDK gives a stdio child a filtered
#: environment: the served bus would not see `conftest.isolate_audit`'s
#: `JUDAIS_LOBI_AUDIT` and would write under the checkout instead.
SERVED_DEV = " ".join([*SERVE, "--unsandboxed", "--profile", "dev",
                       "--audit", "off"])


def local_bus(profile="safe"):
    """The bus a local run would have had, with no audit and no sandbox.

    The other half of every parity assertion.  ``audit="off"`` because the
    comparison is about the *answer*; that the serving side writes rows is
    its own test.
    """
    return build_tools(profile, sandbox_request="none", audit="off").bus


@contextmanager
def served(*extra, bus=None):
    """A spawned ``python -m core.tools.serve``, bridged onto a client bus.

    Yields ``(client, bus)``.  The client bus grants everything, so what a
    test measures is the SERVER's profile and never the caller's.

    ``--audit off`` first, and a test's own ``--audit`` after it wins:
    the SDK's stdio client hands a child a filtered environment, so the
    ``JUDAIS_LOBI_AUDIT`` that ``conftest.isolate_audit`` sets does NOT
    reach this subprocess and a served bus would default to writing under
    the checkout.  The one test that reads audit rows passes a path.
    """
    client_bus = bus if bus is not None else ToolBus(
        capability_engine=CapabilityEngine(PolicyPack(allowed_scopes=["*"])),
        sandbox=NoneSandbox(), audit=None)
    transport = StdioTransport(
        command=SERVE[0], args=[*SERVE[1:], "--audit", "off", *extra])
    with McpClient(transport, timeout=60.0) as client:
        McpToolBridge(client, client_bus).sync()
        yield client, client_bus


@pytest.fixture
def target(tmp_path):
    path = tmp_path / "served.txt"
    path.write_text("the served bus read this\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# What is published
# ---------------------------------------------------------------------------

class TestWhatIsServed:
    def test_every_tool_on_the_bus_is_published(self):
        """Not a list in this file: the served set IS the bus's registry,
        so a tool added to `core.tools.Tools` tomorrow is served without a
        line being written here."""
        with served("--unsandboxed") as (client, _bus):
            assert ({spec.name for spec in client.list_tools()}
                    == set(local_bus().list_tools()))

    def test_the_description_is_the_descriptors_own(self):
        with served("--unsandboxed") as (client, _bus):
            served_fs = [s for s in client.list_tools() if s.name == "fs"][0]
        assert (served_fs.description
                == local_bus().describe_tool("fs")["description"])

    def test_a_multi_action_tools_schema_carries_its_actions(self):
        """From ``action_scopes`` — the mapping the bus checks scopes
        against — so the enum a client is given cannot offer an action the
        bus would refuse to resolve."""
        bus = local_bus()
        with served("--unsandboxed") as (client, _bus):
            schema = [s for s in client.list_tools() if s.name == "fs"][0]
        assert (schema.input_schema["properties"]["action"]["enum"]
                == bus.describe_tool("fs")["actions"])
        assert "action" in schema.input_schema["required"]

    def test_a_single_action_tools_arguments_come_off_its_own_callable(self):
        """`run_shell_command` has no `input_schema` on its descriptor and
        never has: its arguments are declared by its `__call__`. A schema
        with no properties would tell a client nothing and send a model
        guessing.

        The *type* is published only where the callable declares one —
        `run_python_code(code: str, …)` does and `run_shell_command`'s
        `command` does not — because a guessed type is a schema telling a
        model to fix an argument that was already right."""
        with served("--unsandboxed") as (client, _bus):
            published = {spec.name: spec.input_schema
                         for spec in client.list_tools()}
        assert published["run_shell_command"]["required"] == ["command"]
        assert published["run_shell_command"]["properties"]["command"] == {}
        assert published["run_python_code"]["properties"]["code"]["type"] == (
            "string")

    def test_only_serves_the_subset_it_names(self):
        with served("--unsandboxed", "--only", "fs,repo_map") as (client, _b):
            assert sorted(s.name for s in client.list_tools()) == ["fs",
                                                                   "repo_map"]

    def test_a_tool_held_back_by_only_is_refused_by_name(self):
        """And not answered `unknown_tool`: it exists, this server is not
        offering it, and a caller told the wrong one of those goes looking
        for a tool that is right there."""
        with served("--unsandboxed", "--only", "fs") as (client, _bus):
            answer = client.call_tool("run_shell_command", {"command": "id"})
        assert answer.is_error is True
        assert "not_served" in answer.text
        assert "run_shell_command" in answer.text

    def test_only_refuses_a_name_the_bus_has_not_got(self):
        with pytest.raises(SystemExit) as exc:
            served_names(local_bus(), ["fs", "teleport"])
        assert "teleport" in str(exc.value)
        assert "fs" in str(exc.value)

    def test_a_mistyped_profile_is_a_refusal_and_not_a_traceback(self):
        """The four words are already in `select_profile`'s sentence; an
        operator reading a stack trace to find them is this program
        answering a question it was asked politely."""
        from core.tools.serve import main

        with pytest.raises(SystemExit) as exc:
            main(["--profile", "dveloper", "--list"])
        assert "dveloper" in str(exc.value)
        from core.policy.profiles import ProfileMode
        # The list is the enumeration's, in ladder order — not a literal
        # that goes stale the day a level is added (`research`, Phase 15).
        assert ", ".join(m.value for m in ProfileMode) in str(exc.value)

    def test_list_prints_what_would_be_served_with_its_scopes(self, tmp_path):
        rendered = describe_served(local_bus(), ["fs", "run_python_code"])
        assert "fs" in rendered
        assert "fs.read" in rendered
        assert "python.exec" in rendered


# ---------------------------------------------------------------------------
# Parity: the same answer, through the protocol
# ---------------------------------------------------------------------------

class TestParity:
    def test_the_payload_is_the_same_object(self, target):
        """THE claim. `structuredContent` is the bus's own ToolResult, so
        an MCP caller holds the fields an in-process caller holds — exit
        code, stderr beside a non-empty stdout, granted scopes — and not a
        string it has to parse them back out of."""
        arguments = {"action": "read", "path": str(target)}
        here = local_bus().dispatch("fs", **arguments)
        with served("--unsandboxed") as (client, bus):
            there = bus.dispatch("mcp.fs", **arguments)
        assert json.loads(there.evidence) == dataclasses.asdict(here)

    def test_the_text_a_caller_reads_is_the_local_stdout(self, target):
        arguments = {"action": "read", "path": str(target)}
        here = local_bus().dispatch("fs", **arguments)
        with served("--unsandboxed") as (client, bus):
            there = bus.dispatch("mcp.fs", **arguments)
        assert there.stdout == here.stdout == "the served bus read this\n"

    def test_a_denial_is_the_serving_sides_and_says_the_same_sentence(self):
        """SAFE denies `python.exec` here exactly as it denies it there,
        and the sentence names the scope and the profile both times. The
        gate is the SERVER's: the client bus in `served` grants `*`."""
        here = local_bus().dispatch("run_python_code", code="print(1)")
        with served("--unsandboxed") as (client, bus):
            there = bus.dispatch("mcp.run_python_code", code="print(1)")
        assert there.exit_code != 0
        assert json.loads(there.evidence) == dataclasses.asdict(here)
        refusal = json.loads(here.stderr)
        assert refusal["missing_scopes"] == ["python.exec"]
        assert "profile 'safe'" in refusal["message"]
        assert refusal["message"] in there.evidence

    def test_the_profile_flag_opens_what_safe_refuses(self, tmp_path):
        """The one gate on a client that reaches this plane, and it is the
        server's flag and not the caller's."""
        with served("--unsandboxed", "--profile", "dev") as (client, bus):
            answer = bus.dispatch("mcp.fs", action="write",
                                  path=str(tmp_path / "written.txt"),
                                  content="from the far end")
        assert answer.exit_code == 0
        assert (tmp_path / "written.txt").read_text() == "from the far end"

    def test_the_serving_side_wrote_the_audit_rows(self, tmp_path, target):
        """Written where the dispatch happened, which is the only side
        that knows what ran. The client's bus in this test audits nothing."""
        log = tmp_path / "served-audit.jsonl"
        with served("--unsandboxed", "--audit", str(log)) as (client, bus):
            bus.dispatch("mcp.fs", action="read", path=str(target))
            bus.dispatch("mcp.run_python_code", code="print(1)")
        rows = [json.loads(line)
                for line in log.read_text(encoding="utf-8").splitlines() if line]
        by_tool = {(row["tool_name"], row["verdict"]) for row in rows}
        assert ("fs", "allowed") in by_tool
        assert ("run_python_code", "denied") in by_tool

    def test_the_served_bus_is_isolated_like_any_other(self):
        """`select_sandbox` is the one owner of that choice and the server
        does not get a second opinion: bwrap where bubblewrap exists, and
        `--unsandboxed` is the only way to opt out — on the record, in the
        line the server prints."""
        chosen = build_tools("safe", audit="off").bus.sandbox_name
        assert chosen == ("bwrap" if select_sandbox()[0].__class__.__name__
                          == "BwrapSandbox" else "none")
        assert build_tools(
            "safe", sandbox_request="none", audit="off").bus.sandbox_name == "none"


# ---------------------------------------------------------------------------
# The other transport, over a real socket
# ---------------------------------------------------------------------------

HTTP_TOKEN = "served-token-8f21ab"


@pytest.fixture(scope="module")
def http_served():
    """The same server over streamable HTTP, with a bearer token.

    Module-scoped for the reason ``tests/test_mcp_client.py``'s stub is:
    this spawns a uvicorn process, and paying that once is the difference
    between a fast file and a slow one.
    """
    import socket
    import subprocess
    import time
    import urllib.error
    import urllib.request

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    proc = subprocess.Popen(
        [*SERVE, "--http", f"127.0.0.1:{port}", "--token", HTTP_TOKEN,
         "--unsandboxed", "--audit", "off"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}/mcp"
    deadline = time.time() + 30
    while time.time() < deadline:
        if proc.poll() is not None:  # pragma: no cover - a broken spawn
            raise AssertionError(f"the server exited with {proc.returncode}")
        try:
            urllib.request.urlopen(url, timeout=1)
        except urllib.error.HTTPError:
            break              # any HTTP status means the socket answers
        except Exception:
            time.sleep(0.1)
    else:  # pragma: no cover - a host that cannot bind
        proc.kill()
        raise AssertionError("the HTTP server never came up")

    try:
        yield url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover
            proc.kill()


class TestOverHttp:
    def test_the_same_tools_are_served_over_the_socket(self, http_served):
        from core.tools.mcp_client import StreamableHttpTransport

        with McpClient(StreamableHttpTransport(url=http_served,
                                               token=HTTP_TOKEN),
                       timeout=30.0) as client:
            assert ({spec.name for spec in client.list_tools()}
                    == set(local_bus().list_tools()))

    def test_a_call_over_http_goes_through_the_same_bus(self, http_served,
                                                        tmp_path):
        from core.tools.mcp_client import StreamableHttpTransport

        path = tmp_path / "over-http.txt"
        path.write_text("read over a socket\n", encoding="utf-8")
        with McpClient(StreamableHttpTransport(url=http_served,
                                               token=HTTP_TOKEN),
                       timeout=30.0) as client:
            answer = client.call_tool("fs", {"action": "read",
                                             "path": str(path)})
        assert answer.text == "read over a socket\n"
        assert answer.structured["granted_scopes"] == ["fs.read"]

    def test_without_the_token_nothing_is_reached(self, http_served):
        """Refused by the gate in front of the session manager, so an
        unauthenticated caller never gets a session kept for it."""
        from core.tools.mcp_client import (
            McpConnectionError, StreamableHttpTransport,
        )

        with pytest.raises(McpConnectionError):
            McpClient(StreamableHttpTransport(url=http_served),
                      timeout=10.0).start()


# ---------------------------------------------------------------------------
# The renderers, on their own
# ---------------------------------------------------------------------------

class TestTheRenderers:
    def test_a_result_payload_keeps_every_field_of_the_tool_result(self):
        from core.tools.bus import ToolResult

        result = ToolResult(exit_code=3, stdout="out", stderr="err",
                            tool_name="fs", granted_scopes=["fs.read"],
                            evidence="{}")
        assert result_payload(result) == dataclasses.asdict(result)

    def test_the_text_of_a_failure_is_its_stderr(self):
        from core.tools.bus import ToolResult

        assert result_text(ToolResult(exit_code=1, stdout="", stderr="boom",
                                      tool_name="fs")) == "boom"
        assert result_text(ToolResult(exit_code=0, stdout="fine", stderr="",
                                      tool_name="fs")) == "fine"

    def test_a_signature_with_kwargs_stays_open_ended(self):
        def tool(action: str, path: str, timeout: int = 5, **kwargs):
            return None

        schema = schema_from_signature(tool)
        assert schema["properties"]["timeout"]["type"] == "integer"
        assert schema["required"] == ["action", "path"]
        assert schema["additionalProperties"] is True

    def test_a_bare_port_is_refused_rather_than_bound_everywhere(self):
        """Binding a tool plane to every interface is a decision, and not
        one a missing half of an argument gets to make."""
        from core.tools.serve import parse_host_port

        assert parse_host_port("127.0.0.1:8765") == ("127.0.0.1", 8765)
        with pytest.raises(SystemExit) as exc:
            parse_host_port("8765")
        assert "HOST:PORT" in str(exc.value)

    def test_a_bridged_tools_schema_is_passed_through_untouched(self):
        """A schema that arrived from somebody else's server is theirs.
        Reshaping it on the way through would make this server the author
        of a contract it is only relaying."""
        bus = local_bus()
        from core.tools.descriptors import ToolDescriptor

        theirs = {"type": "object", "properties": {"q": {"type": "string"}},
                  "required": ["q"]}
        bus.register(ToolDescriptor(tool_name="mcp.search",
                                    input_schema=dict(theirs)),
                     lambda **kw: (0, "", ""))
        assert input_schema_for(bus, "mcp.search") == theirs


# ---------------------------------------------------------------------------
# The same mission, in-process and over the protocol
# ---------------------------------------------------------------------------

SKILL = textwrap.dedent("""\
    ---
    name: readback
    skill:
      skill_id: readback
      when_to_use: Reading one file and saying what is in it.
      allowed_tools:
        - fs
      policy:
        - Read before answering.
      output_format: One line.
    ---

    # Readback

    Read the file, then answer.
    """)


@pytest.fixture
def skill_file(tmp_path):
    path = tmp_path / "SKILL.md"
    path.write_text(SKILL, encoding="utf-8")
    return path


@pytest.fixture
def elf():
    """An agent whose replies are scripted per run, as the CLI tests do.

    Its bus is the **real** built-in registry, built by the same
    :func:`~core.tools.serve.build_tools` the server builds one with —
    which is the whole point of these three tests: the in-process run has
    to be dispatching the same tools the served run reaches over the
    protocol, or the comparison is between two different planes.
    """
    agent = MagicMock()
    agent.model = "gpt-oss-20b"
    agent.text_color = "cyan"
    agent.client.provider = "local"
    agent.client.last_usage = None
    agent.system_message = "You are Tai."
    agent.tools.bus = build_tools("dev", sandbox_request="none",
                                  audit="off").bus
    agent.replies = []

    def _chat(**kw):
        return agent.replies.pop(0) if agent.replies else '{"answer": "done"}'

    agent.client.chat.side_effect = _chat
    MockClass = MagicMock(return_value=agent)
    MockClass.__name__ = "Tai"
    return MockClass, agent


def run_mission(MockClass, agent, tool, target, events, *extra):
    """One mission that reads *target* with *tool*, recorded to *events*."""
    from core.cli import _main

    agent.replies = [
        json.dumps({"tool": tool,
                    "arguments": {"action": "read", "path": str(target)}}),
        json.dumps({"answer": "the file was read"}),
    ]
    argv = ["test", "read it", "--mission", "--events", str(events), *extra]
    with patch("sys.argv", argv):
        _main(MockClass)
    return [json.loads(line)
            for line in Path(events).read_text(encoding="utf-8").splitlines()
            if line]


def records(stream, kind):
    return [record for record in stream if record.get("event") == kind]


class TestTheSameMissionBothWays:
    """The parity proof at the altitude an operator sees it: one skill, one
    objective, one scripted model — run once on the built-in tools and once
    over ``--mcp-stdio 'python -m core.tools.serve'``."""

    def test_the_tool_result_is_the_same_and_only_the_name_is_namespaced(
            self, elf, skill_file, tmp_path, target):
        MockClass, agent = elf
        here = run_mission(MockClass, agent, "fs", target,
                           tmp_path / "local.ndjson", "--skill", str(skill_file))
        there = run_mission(
            MockClass, agent, "mcp.fs", target, tmp_path / "mcp.ndjson",
            "--skill", str(skill_file),
            "--mcp-stdio", SERVED_DEV)

        local_result = records(here, "tool_result")[0]
        mcp_result = records(there, "tool_result")[0]
        assert local_result["tool"] == "fs"
        assert mcp_result["tool"] == "mcp.fs"
        assert mcp_result["tool"].split(".", 1)[1] == local_result["tool"]
        assert mcp_result["arguments"] == local_result["arguments"]
        assert mcp_result["output"] == local_result["output"]
        assert mcp_result["ok"] == local_result["ok"] is True

    def test_both_missions_answer(self, elf, skill_file, tmp_path, target,
                                  capsys):
        MockClass, agent = elf
        run_mission(MockClass, agent, "fs", target, tmp_path / "a.ndjson",
                    "--skill", str(skill_file))
        assert "the file was read" in capsys.readouterr().out
        run_mission(
            MockClass, agent, "mcp.fs", target, tmp_path / "b.ndjson",
            "--skill", str(skill_file),
            "--mcp-stdio", SERVED_DEV)
        assert "the file was read" in capsys.readouterr().out

    def test_the_connected_line_for_one_server_names_no_namespace(
            self, elf, skill_file, tmp_path, target, capsys):
        """Byte-identical to the single-server line this CLI has always
        printed: a namespace is shown when there is more than one plane to
        tell apart, and not before."""
        MockClass, agent = elf
        run_mission(MockClass, agent, "mcp.fs", target, tmp_path / "c.ndjson",
                    "--skill", str(skill_file), "--mcp-stdio", SERVED_DEV)
        out = capsys.readouterr().out
        # The console wraps at 80 columns and the command line is longer
        # than that, so the assertion is about the NAMESPACE and not the
        # path: with one server there is nothing to tell apart and the line
        # carries no `name=` prefix, exactly as it did before the flags
        # repeated. `tests/test_mcp_multi_server.py` asserts the other half.
        assert "connected to" in out
        assert "mcp=" not in out
