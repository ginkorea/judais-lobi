# tests/test_mcp_client.py — the MCP client and its ToolBus bridge

"""Tested against a real MCP server over a real transport.

The stub is a ``FastMCP`` server in ``tests/mcp_stub_server.py``, spawned
as a subprocess and spoken to over stdio.  That is a genuine JSON-RPC
handshake, a genuine ``tools/list`` and a genuine ``tools/call`` — which
is the whole claim this module makes and the one a mock cannot check.

No TAIPAN server is needed: this is a client of the *protocol*.
"""

import sys
from pathlib import Path

import pytest

from core.tools.bus import ToolBus
from core.tools.capability import CapabilityEngine
from core.contracts.schemas import PolicyPack
from core.tools.descriptors import ToolDescriptor
from core.tools.mcp_client import (
    McpCallResult,
    McpClient,
    McpConnectionError,
    McpToolBridge,
    McpToolSpec,
    McpTransport,
    McpTransportMisdeclared,
    StdioTransport,
    StreamableHttpTransport,
)

mcp = pytest.importorskip("mcp", reason="the MCP client is an optional extra")

STUB = str(Path(__file__).parent / "mcp_stub_server.py")


@pytest.fixture
def client():
    transport = StdioTransport(command=sys.executable, args=[STUB])
    with McpClient(transport, timeout=30.0) as c:
        yield c


@pytest.fixture
def bus():
    return ToolBus(capability_engine=CapabilityEngine(PolicyPack(allowed_scopes=["*"])))


# ---------------------------------------------------------------------------
# Declaration is checked at class creation
# ---------------------------------------------------------------------------

class TestTransportDeclaration:
    def test_shipped_transports_are_well_declared(self):
        assert StdioTransport.scheme == "stdio"
        assert StreamableHttpTransport.scheme == "http"
        assert StdioTransport.uses_network is False
        assert StreamableHttpTransport.uses_network is True

    def test_unnamed_transport_is_refused(self):
        with pytest.raises(McpTransportMisdeclared, match="`name` is empty"):
            class Nameless(McpTransport):
                scheme = "stdio"

                async def open_streams(self, credential): ...
                def describe(self): return ""

    def test_a_name_holding_an_address_is_refused(self):
        with pytest.raises(McpTransportMisdeclared, match="contains an address"):
            class Addressed(McpTransport):
                name = "the server at 127.0.0.1"
                scheme = "http"

                async def open_streams(self, credential): ...
                def describe(self): return ""

    def test_an_unknown_scheme_is_refused(self):
        with pytest.raises(McpTransportMisdeclared, match="`scheme` is"):
            class Weird(McpTransport):
                name = "a server over carrier pigeon"
                scheme = "pigeon"

                async def open_streams(self, credential): ...
                def describe(self): return ""

    def test_overriding_the_final_session_is_refused(self):
        with pytest.raises(McpTransportMisdeclared, match="which is final"):
            class Impatient(McpTransport):
                name = "a server reached out of order"
                scheme = "stdio"

                async def open_streams(self, credential): ...
                def describe(self): return ""
                def session(self, message_handler=None): ...

    def test_every_problem_is_reported_at_once(self):
        """One message, all of it — not one mistake per import."""
        with pytest.raises(McpTransportMisdeclared) as exc:
            class AllWrong(McpTransport):
                scheme = "pigeon"

        message = str(exc.value)
        assert "`name` is empty" in message
        assert "`scheme` is" in message
        assert "does not implement `open_streams`" in message
        assert "does not implement `describe`" in message

    def test_an_intermediate_base_is_allowed(self):
        class Partial(McpTransport):
            abstract = True

        assert Partial.name == ""


class TestTransportConfigChecks:
    def test_empty_command_is_a_config_problem(self):
        assert StdioTransport(command="  ").check()

    def test_url_without_a_scheme_is_a_config_problem(self):
        problems = StreamableHttpTransport(url="spine.local/mcp").check()
        assert any("no http(s) scheme" in p for p in problems)

    def test_a_good_url_has_no_problems(self):
        assert StreamableHttpTransport(url="https://spine.local/mcp").check() == []

    def test_the_token_is_not_in_describe_or_name(self):
        t = StreamableHttpTransport(url="https://spine.local/mcp", token="s3cret")
        assert "s3cret" not in t.describe()
        assert "s3cret" not in t.name
        assert t.credential() == "s3cret"


# ---------------------------------------------------------------------------
# The protocol
# ---------------------------------------------------------------------------

class TestProtocol:
    def test_tools_list(self, client):
        names = {t.name for t in client.list_tools()}
        assert {"echo", "add", "always_fails", "governed_read"} <= names

    def test_tool_spec_carries_the_input_schema(self, client):
        spec = next(t for t in client.list_tools() if t.name == "add")
        assert spec.argument_names == ["a", "b"]
        assert spec.input_schema["type"] == "object"

    def test_tools_call(self, client):
        result = client.call_tool("echo", {"text": "ping"})
        assert isinstance(result, McpCallResult)
        assert result.is_error is False
        assert "ping" in result.text

    def test_tools_call_with_typed_arguments(self, client):
        assert "5" in client.call_tool("add", {"a": 2, "b": 3}).text

    def test_a_failing_tool_is_an_error_result_not_an_exception(self, client):
        result = client.call_tool("always_fails", {})
        assert result.is_error is True
        assert result.text

    def test_call_before_start_refuses(self):
        c = McpClient(StdioTransport(command=sys.executable, args=[STUB]))
        with pytest.raises(McpConnectionError, match="not connected"):
            c.call_tool("echo", {"text": "x"})

    def test_an_unreachable_server_refuses_at_start(self):
        transport = StdioTransport(
            command=sys.executable, args=["-c", "raise SystemExit(3)"],
        )
        with pytest.raises(McpConnectionError):
            McpClient(transport, timeout=15.0).start()

    def test_list_changed_notification_is_acted_on(self, client):
        """The server adds a tool and says so; the client re-lists itself."""
        before = client.tools_generation
        assert "late_arrival" not in {t.name for t in client.list_tools()}

        client.call_tool("add_a_tool", {})
        _wait_for(lambda: client.tools_generation > before)

        assert "late_arrival" in {t.name for t in client.list_tools()}

    def test_stop_is_idempotent(self, client):
        client.stop()
        client.stop()
        assert client.connected is False


def _wait_for(predicate, timeout=10.0, interval=0.05):
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    raise AssertionError("condition never became true")


# ---------------------------------------------------------------------------
# The bridge — the point of the module
# ---------------------------------------------------------------------------

class TestBridge:
    def test_discovered_tools_become_bus_tools(self, client, bus):
        names = McpToolBridge(client, bus).sync()
        assert "mcp.echo" in names
        assert "mcp.echo" in bus.list_tools()

    def test_descriptors_are_real_tool_descriptors(self, client, bus):
        McpToolBridge(client, bus).sync()
        assert isinstance(bus.get_descriptor("mcp.echo"), ToolDescriptor)

    def test_dispatch_reaches_the_server(self, client, bus):
        McpToolBridge(client, bus).sync()
        result = bus.dispatch("mcp.echo", text="through the bus")
        assert result.exit_code == 0
        assert "through the bus" in result.stdout

    def test_a_tool_error_is_a_non_zero_exit_not_a_raise(self, client, bus):
        McpToolBridge(client, bus).sync()
        result = bus.dispatch("mcp.always_fails")
        assert result.exit_code != 0
        assert result.stderr

    def test_names_are_namespaced_so_a_server_cannot_shadow_a_local_tool(
        self, client, bus,
    ):
        """The stub advertises 'run_shell_command'. It must not become it."""
        assert "run_shell_command" in {t.name for t in client.list_tools()}
        local = ToolDescriptor(tool_name="run_shell_command", required_scopes=[])
        bus.register(local, lambda **_kw: (0, "the local shell tool", ""))
        McpToolBridge(client, bus).sync()

        assert bus.dispatch("run_shell_command").stdout == "the local shell tool"
        assert "mcp.run_shell_command" in bus.list_tools()

    def test_capability_gating_still_applies(self, client):
        """The bridge buys the gate; that is why it is a bridge."""
        gated = ToolBus(
            capability_engine=CapabilityEngine(PolicyPack(allowed_scopes=["fs.read"])),
        )
        McpToolBridge(client, gated).sync()
        result = gated.dispatch("mcp.echo", text="denied?")
        assert result.exit_code != 0
        assert "capability_denied" in result.stderr

    def test_the_declared_scope_unlocks_it(self, client):
        allowed = ToolBus(
            capability_engine=CapabilityEngine(PolicyPack(allowed_scopes=["mcp.call"])),
        )
        McpToolBridge(client, allowed).sync()
        assert allowed.dispatch("mcp.echo", text="ok").exit_code == 0

    def test_stdio_tools_are_not_network_tools(self, client, bus):
        McpToolBridge(client, bus).sync()
        assert bus.get_descriptor("mcp.echo").requires_network is False

    def test_http_tools_would_be_network_tools(self, bus):
        """requires_network follows the transport, not the tool."""
        class _Fake(McpClient):
            def __init__(self):
                self._transport = StreamableHttpTransport(url="https://x.invalid/mcp")
                self._tools = [McpToolSpec(name="t", description="d")]

            def list_tools(self, refresh=False):
                return list(self._tools)

        McpToolBridge(_Fake(), bus).sync()
        assert bus.get_descriptor("mcp.t").requires_network is True

    def test_description_and_arguments_reach_describe_tool(self, client, bus):
        McpToolBridge(client, bus).sync()
        info = bus.describe_tool("mcp.add")
        assert "a, b" in info["description"]

    def test_resync_picks_up_a_new_tool(self, client, bus):
        bridge = McpToolBridge(client, bus)
        bridge.sync()
        assert "mcp.late_arrival" not in bus.list_tools()

        client.call_tool("add_a_tool", {})
        _wait_for(lambda: "late_arrival" in {t.name for t in client.list_tools()})
        bridge.sync()

        assert "mcp.late_arrival" in bus.list_tools()

    def test_follow_changes_resyncs_without_being_asked(self, client, bus):
        bridge = McpToolBridge(client, bus)
        bridge.sync()
        bridge.follow_changes()

        client.call_tool("add_a_tool", {})
        _wait_for(lambda: "mcp.late_arrival" in bus.list_tools())

    def test_a_custom_namespace_is_honoured(self, client, bus):
        names = McpToolBridge(client, bus, namespace="taipan").sync()
        assert "taipan.echo" in names
