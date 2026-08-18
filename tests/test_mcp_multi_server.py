# tests/test_mcp_multi_server.py — several MCP servers on one bus

"""Composing a platform's plane with ours, and telling them apart.

The bridge namespaced discovered tools from the day it was written, but
there was only ever one namespace because there was only ever one server:
``--mcp-stdio`` XOR ``--mcp-url``.  A deployment that has a governed plane
of its own and wants this package's built-in tools beside it — which is
exactly what ``core.tools.serve`` makes possible — needs both at once.

So the flags repeat, each server gets a namespace (``mcp``, ``mcp2``, … or
one written ``NAME=``), and :class:`~core.tools.mcp_client.McpFleet` owns
the N sessions.  What must NOT change is the single-server run: the same
names on the bus, the same line on the console, the same recorded corpus.
The tests here are half about the second server and half about the first
one being untouched.

Both real servers are spawned: this package's own
(``python -m core.tools.serve``) and ``tests/mcp_stub_server.py``.
"""

import json
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

from core.tools.mcp_client import (  # noqa: E402
    AUTO_NAMESPACE, McpFleet, McpServersMisdeclared, McpToolBridge,
    NamedTransport, StdioTransport, auto_namespace, split_namespace,
    transports_from_args, transports_from_specs,
)

STUB = str(Path(__file__).parent / "mcp_stub_server.py")
#: `--audit off` because the SDK hands a stdio child a FILTERED
#: environment: `conftest.isolate_audit`'s `JUDAIS_LOBI_AUDIT` does not
#: reach a served subprocess, and its bus would default to writing under
#: the checkout.
OURS = (f"{sys.executable} -m core.tools.serve --unsandboxed "
        f"--profile dev --audit off")
THEIRS = f"{sys.executable} {STUB}"


@pytest.fixture
def bus():
    return ToolBus(
        capability_engine=CapabilityEngine(PolicyPack(allowed_scopes=["*"])),
        sandbox=NoneSandbox(), audit=None)


# ---------------------------------------------------------------------------
# Reading the flags
# ---------------------------------------------------------------------------

class TestNamespacesFromFlags:
    def test_one_server_is_still_plain_mcp(self):
        """The whole compatibility story in one assertion: every manifest,
        every recorded corpus and every dashboard that ever wrote
        `mcp.something` keeps working, because a lone server's namespace
        did not become `mcp1`."""
        servers = transports_from_specs([OURS])
        assert [s.namespace for s in servers] == ["mcp"]
        assert AUTO_NAMESPACE == McpToolBridge.DEFAULT_NAMESPACE == "mcp"

    def test_the_second_server_is_numbered(self):
        servers = transports_from_specs([OURS, THEIRS])
        assert [s.namespace for s in servers] == ["mcp", "mcp2"]

    def test_a_name_can_be_written_on_the_flag(self):
        servers = transports_from_specs(["ours=" + OURS, "theirs=" + THEIRS])
        assert [s.namespace for s in servers] == ["ours", "theirs"]
        assert servers[0].transport.describe() == OURS

    def test_an_automatic_name_skips_one_a_flag_claimed(self):
        servers = transports_from_specs([OURS, "mcp2=" + THEIRS, THEIRS])
        assert [s.namespace for s in servers] == ["mcp", "mcp2", "mcp3"]

    def test_a_url_is_not_read_as_a_namespace(self):
        """`https://h/mcp?token=x` has an `=` in it and no namespace: the
        text before it is not an identifier, which is the whole rule."""
        assert split_namespace("https://h/mcp?token=x") == (
            None, "https://h/mcp?token=x")
        servers = transports_from_specs([], ["https://h/mcp?a=b"])
        assert servers[0].transport.url == "https://h/mcp?a=b"

    def test_stdio_comes_before_http_and_the_order_is_stated(self):
        servers = transports_from_specs([OURS], ["https://h/mcp"])
        assert [s.namespace for s in servers] == ["mcp", "mcp2"]
        assert servers[0].transport.scheme == "stdio"

    def test_two_servers_cannot_share_a_namespace(self):
        with pytest.raises(McpServersMisdeclared) as exc:
            transports_from_specs(["a=" + OURS, "a=" + THEIRS])
        assert "'a'" in str(exc.value)

    def test_the_fleet_refuses_a_shared_namespace_too(self, bus):
        """Checked where the servers are, and not only where the flags
        were parsed: a library caller builds the pairs itself."""
        pair = [NamedTransport("same", StdioTransport(command="true")),
                NamedTransport("same", StdioTransport(command="true"))]
        with pytest.raises(McpServersMisdeclared):
            McpFleet(pair, bus)

    def test_a_token_pairs_with_the_url_in_the_same_position(self):
        servers = transports_from_specs(
            [], ["https://a/mcp", "https://b/mcp"], ["tok-a", "tok-b"])
        assert servers[0].transport.credential() == "tok-a"
        assert servers[1].transport.credential() == "tok-b"

    def test_one_token_for_two_urls_is_refused_and_not_reused(self):
        """A bearer token is one server's secret. Sending it to the second
        server because the counting was convenient is a leak the other
        operator finds in their logs."""
        with pytest.raises(McpServersMisdeclared) as exc:
            transports_from_specs([], ["https://a/mcp", "https://b/mcp"],
                                  ["tok-a"])
        assert "paired by position" in str(exc.value)

    def test_an_empty_token_says_this_one_needs_none(self):
        servers = transports_from_specs(
            [], ["https://a/mcp", "https://b/mcp"], ["", "tok-b"])
        assert servers[0].transport.credential() is None
        assert servers[1].transport.credential() == "tok-b"

    def test_a_token_with_no_url_is_ignored_as_it_always_was(self, monkeypatch):
        """MCP_TOKEN is a variable a shell carries for whatever it last
        connected to; a stdio run refusing to start because of it would be
        this parser inventing a fault."""
        assert len(transports_from_specs([OURS], [], ["stray"])) == 1

    def test_the_environment_still_names_one_server(self, monkeypatch):
        monkeypatch.setenv("MCP_STDIO", THEIRS)
        monkeypatch.delenv("MCP_URL", raising=False)
        args = SimpleNamespace(mcp_stdio=None, mcp_url=None, mcp_token=None)
        assert [s.transport.describe() for s in transports_from_args(args)] == [
            THEIRS]

    def test_a_flag_replaces_the_environment_rather_than_adding_to_it(
            self, monkeypatch):
        """The reason the env is read here and not as an argparse
        `default=`: an `append` action appends TO its default, so an
        operator with MCP_STDIO set who also passed --mcp-stdio would have
        silently bridged a plane they had forgotten was in their shell."""
        monkeypatch.setenv("MCP_STDIO", THEIRS)
        args = SimpleNamespace(mcp_stdio=[OURS], mcp_url=None, mcp_token=None)
        assert [s.transport.describe() for s in transports_from_args(args)] == [
            OURS]

    def test_the_environments_token_still_credentials_a_url_from_a_flag(
            self, monkeypatch):
        """It did when there could only be one server, and an operator
        whose token stopped being sent the day the flag learned to repeat
        would debug the server's 401 rather than this function."""
        monkeypatch.setenv("MCP_TOKEN", "from-the-environment")
        args = SimpleNamespace(mcp_stdio=None, mcp_url=["https://a/mcp"],
                               mcp_token=None)
        assert transports_from_args(args)[0].transport.credential() == (
            "from-the-environment")

    def test_the_environments_token_with_two_urls_is_refused(self,
                                                             monkeypatch):
        """One variable is one server's secret. Sending it to the wrong
        one is the leak; ignoring it quietly is an unauthenticated run
        nobody asked for."""
        monkeypatch.setenv("MCP_TOKEN", "from-the-environment")
        args = SimpleNamespace(mcp_stdio=None,
                               mcp_url=["https://a/mcp", "https://b/mcp"],
                               mcp_token=None)
        with pytest.raises(McpServersMisdeclared) as exc:
            transports_from_args(args)
        assert "MCP_TOKEN" in str(exc.value)

    def test_a_token_flag_beats_the_environment(self, monkeypatch):
        monkeypatch.setenv("MCP_TOKEN", "from-the-environment")
        args = SimpleNamespace(mcp_stdio=None, mcp_url=["https://a/mcp"],
                               mcp_token=["from-the-flag"])
        assert transports_from_args(args)[0].transport.credential() == (
            "from-the-flag")

    def test_auto_namespace_counts_past_what_is_taken(self):
        assert auto_namespace([]) == "mcp"
        assert auto_namespace(["mcp"]) == "mcp2"
        assert auto_namespace(["mcp", "mcp2", "mcp3"]) == "mcp4"


# ---------------------------------------------------------------------------
# Two real servers, one bus
# ---------------------------------------------------------------------------

@pytest.fixture
def fleet(bus):
    servers = transports_from_specs([OURS, THEIRS])
    with McpFleet(servers, bus, timeout=60.0) as running:
        yield running


class TestTwoServersOnOnePlane:
    def test_both_namespaces_are_offered(self, fleet, bus):
        assert fleet.namespaces == ["mcp", "mcp2"]
        assert "mcp.fs" in bus.list_tools()
        assert "mcp2.governed_read" in bus.list_tools()

    def test_a_name_both_servers_use_stays_two_tools(self, fleet, bus):
        """Ours and the stub both publish `run_shell_command`. Without a
        namespace per server the second registration would have replaced
        the first and half the plane would be unreachable."""
        assert "mcp.run_shell_command" in bus.list_tools()
        assert "mcp2.run_shell_command" in bus.list_tools()

    def test_each_dispatch_reaches_its_own_server(self, fleet, bus, tmp_path):
        path = tmp_path / "two.txt"
        path.write_text("from ours\n", encoding="utf-8")
        ours = bus.dispatch("mcp.fs", action="read", path=str(path))
        theirs = bus.dispatch("mcp2.governed_read", asset_id="asset.5f21")
        assert ours.stdout == "from ours\n"
        assert "asset.5f21" in theirs.stdout

    def test_the_discovered_list_is_server_order(self, fleet):
        names = fleet.discovered
        assert names.index("mcp.fs") < names.index("mcp2.governed_read")

    def test_the_audit_row_names_which_server_ran_it(self, tmp_path):
        """Through the namespace, which is the bus name — one owner. An
        audit that recorded `fs` for a call to either plane could not say
        whose filesystem was read."""
        from core.policy.audit import AuditLogger

        log = tmp_path / "client-audit.jsonl"
        audited = ToolBus(
            capability_engine=CapabilityEngine(PolicyPack(allowed_scopes=["*"])),
            sandbox=NoneSandbox(), audit=AuditLogger(path=log))
        with McpFleet(transports_from_specs([OURS, THEIRS]), audited,
                      timeout=60.0):
            audited.dispatch("mcp2.echo", text="hello")
        rows = [json.loads(line) for line in
                log.read_text(encoding="utf-8").splitlines() if line]
        assert [row["tool_name"] for row in rows] == ["mcp2.echo"]

    def test_the_describe_line_names_every_plane(self, fleet):
        assert fleet.describe() == f"mcp={OURS}; mcp2={THEIRS}"

    def test_one_server_describes_itself_as_it_always_did(self, bus):
        with McpFleet(transports_from_specs([THEIRS]), bus,
                      timeout=60.0) as running:
            assert running.describe() == THEIRS

    def test_leaving_the_fleet_takes_every_tool_off_the_bus(self, bus):
        with McpFleet(transports_from_specs([OURS, THEIRS]), bus,
                      timeout=60.0):
            assert bus.list_tools()
        assert bus.list_tools() == []

    def test_a_fleet_that_cannot_bring_one_up_leaves_none_up(self, bus):
        """Half a plane is worse than none: a mission on it answers from
        whichever tools happened to connect, and the transcript looks
        ordinary."""
        from core.tools.mcp_client import McpConnectionError

        servers = transports_from_specs([THEIRS, f"{sys.executable} -c pass"])
        with pytest.raises(McpConnectionError):
            McpFleet(servers, bus, timeout=15.0).start()
        assert bus.list_tools() == []


# ---------------------------------------------------------------------------
# A skill whose closed set spans both planes
# ---------------------------------------------------------------------------

class TestASkillAcrossTwoPlanes:
    def manifest(self, tmp_path, tools):
        from core.runtime.skills import load_skill

        body = textwrap.dedent("""\
            ---
            name: composed
            skill:
              skill_id: composed
              when_to_use: Two planes at once.
              allowed_tools:
            %s
              policy:
                - Read before answering.
              output_format: One line.
            ---

            # Composed
            """) % "\n".join(f"    - {name}" for name in tools)
        path = tmp_path / "SKILL.md"
        path.write_text(body, encoding="utf-8")
        return load_skill(str(path))

    def test_one_manifest_resolves_tools_from_both_servers(self, fleet,
                                                           tmp_path):
        manifest = self.manifest(tmp_path, ["fs", "governed_read"])
        assert manifest.resolve(fleet.discovered) == ["mcp.fs",
                                                      "mcp2.governed_read"]

    def test_a_name_both_planes_offer_is_refused_rather_than_guessed(
            self, fleet, tmp_path):
        """`same_tool` matches a short name against every namespace, so a
        tool two servers both publish is ambiguous — and a coin flip about
        which plane a mission calls is not a thing to resolve quietly."""
        from core.runtime.skills import SkillToolsUnavailable

        manifest = self.manifest(tmp_path, ["run_shell_command"])
        with pytest.raises(SkillToolsUnavailable) as exc:
            manifest.resolve(fleet.discovered)
        assert "matches 2 discovered tools" in str(exc.value)
        assert "name it with its namespace" in str(exc.value)

    def test_the_namespaced_spelling_settles_it(self, fleet, tmp_path):
        manifest = self.manifest(tmp_path, ["mcp2.run_shell_command"])
        assert manifest.resolve(fleet.discovered) == ["mcp2.run_shell_command"]


# ---------------------------------------------------------------------------
# Through the command line
# ---------------------------------------------------------------------------

SKILL = textwrap.dedent("""\
    ---
    name: composed
    skill:
      skill_id: composed
      when_to_use: Two planes at once.
      allowed_tools:
        - fs
        - governed_read
      policy:
        - Read before answering.
      output_format: One line.
    ---

    # Composed

    Use ours for files and theirs for assets.
    """)


@pytest.fixture
def elf():
    agent = MagicMock()
    agent.model = "gpt-oss-20b"
    agent.text_color = "cyan"
    agent.client.provider = "local"
    agent.client.last_usage = None
    agent.system_message = "You are Tai."
    agent.tools.bus = ToolBus(
        capability_engine=CapabilityEngine(PolicyPack(allowed_scopes=["*"])),
        sandbox=NoneSandbox(), audit=None)
    agent.replies = []

    def _chat(**kw):
        return agent.replies.pop(0) if agent.replies else '{"answer": "done"}'

    agent.client.chat.side_effect = _chat
    MockClass = MagicMock(return_value=agent)
    MockClass.__name__ = "Tai"
    return MockClass, agent


class TestAMissionOverTwoServers:
    def test_it_calls_a_tool_on_each_plane(self, elf, tmp_path, capsys):
        from core.cli import _main

        skill = tmp_path / "SKILL.md"
        skill.write_text(SKILL, encoding="utf-8")
        target = tmp_path / "composed.txt"
        target.write_text("ours answered\n", encoding="utf-8")
        events = tmp_path / "events.ndjson"

        MockClass, agent = elf
        agent.replies = [
            json.dumps({"tool": "mcp.fs",
                        "arguments": {"action": "read", "path": str(target)}}),
            json.dumps({"tool": "mcp2.governed_read",
                        "arguments": {"asset_id": "asset.5f21"}}),
            json.dumps({"answer": "both planes answered"}),
        ]
        argv = ["test", "read and look up", "--mission",
                "--skill", str(skill), "--events", str(events),
                "--mcp-stdio", OURS, "--mcp-stdio", THEIRS]
        with patch("sys.argv", argv):
            _main(MockClass)

        stream = [json.loads(line) for line in
                  events.read_text(encoding="utf-8").splitlines() if line]
        results = {record["tool"]: record for record in stream
                   if record.get("event") == "tool_result"}
        assert results["mcp.fs"]["output"].strip() == "ours answered"
        assert "asset.5f21" in results["mcp2.governed_read"]["output"]

        # The console wraps the command lines at 80 columns, so what is
        # asserted is that BOTH namespaces are named on the connected line —
        # which is the thing a single-server run does not print.
        out = capsys.readouterr().out
        assert "mcp=" in out and "mcp2=" in out
        assert "both planes answered" in out
