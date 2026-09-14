# tests/test_mcp_client.py — the MCP client and its ToolBus bridge

"""Tested against a real MCP server over a real transport.

The stub is a ``FastMCP`` server in ``tests/mcp_stub_server.py``, spawned
as a subprocess and spoken to over stdio.  That is a genuine JSON-RPC
handshake, a genuine ``tools/list`` and a genuine ``tools/call`` — which
is the whole claim this module makes and the one a mock cannot check.

No TAIPAN server is needed: this is a client of the *protocol*.
"""

import contextlib
import json
import sys
from pathlib import Path

import pytest

from core.tools.bus import ToolBus
from core.tools.capability import CapabilityEngine
from core.contracts.schemas import PolicyPack
from core.tools.descriptors import ToolDescriptor
from core.tools.mcp_client import (
    DEFAULT_TIMEOUT_S,
    HTTP_REFUSAL_BODY_CAP,
    TIMEOUT_ENV,
    TIMEOUT_FLAG,
    McpCallResult,
    McpClient,
    McpConnectionError,
    McpToolBridge,
    McpToolSpec,
    McpTransport,
    McpTransportMisdeclared,
    StdioTransport,
    StreamableHttpTransport,
    parse_http_refusal,
)

mcp = pytest.importorskip("mcp", reason="the MCP client is an optional extra")

# StreamableHttpTransport deliberately uses `streamablehttp_client`; see the
# comment there for why the "replacement" is not one.
pytestmark = pytest.mark.filterwarnings(
    "ignore:Use `streamable_http_client` instead.:DeprecationWarning"
)

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

    def test_a_server_that_starts_and_says_nothing_names_its_timeout(self):
        """Spawn-then-silence, which is the failure a deployment sees most.

        The transport came up — the subprocess is RUNNING — and the
        `initialize` handshake never came back, so the caller watches a
        process live for exactly the timeout and die. The message used to
        carry the number and not the name of the number, which leaves a
        reader with a constant they cannot trace to a knob. So it names the
        bound, the flag, the variable and the default.
        """
        transport = StdioTransport(
            command=sys.executable, args=["-c", "import time; time.sleep(5)"])
        with pytest.raises(McpConnectionError) as caught:
            McpClient(transport, timeout=1.0).start()
        said = str(caught.value)
        assert "initialize" in said            # what was waited FOR
        assert "within 1s" in said             # the value it waited
        assert TIMEOUT_FLAG in said            # the knob that sets it
        assert TIMEOUT_ENV in said
        assert f"default {DEFAULT_TIMEOUT_S:g}s" in said

    def test_the_default_bound_has_one_owner(self):
        """Three constructors here and one in the CLI all wrote `30.0`. A
        message naming a default that a caller's own default disagreed with
        would be worse than no message."""
        from core.tools.mcp_client import McpFleet, StreamableHttpTransport

        assert McpClient(StdioTransport(command="x"))._timeout == \
            DEFAULT_TIMEOUT_S
        assert StreamableHttpTransport(url="http://x/mcp").timeout == \
            DEFAULT_TIMEOUT_S
        assert McpFleet((), object())._timeout == DEFAULT_TIMEOUT_S

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

    def test_a_stdio_tools_sandbox_keeps_the_network_shut(self, client, bus):
        McpToolBridge(client, bus).sync()
        profile = bus.get_descriptor("mcp.echo").sandbox_profile
        assert profile.allow_network is False

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

    def test_an_http_tools_sandbox_lets_it_reach_the_server(self, bus):
        """The bus gate and the sandbox have to agree. A bridged tool
        allowed through the network check and then run inside an unshared
        namespace comes back ``mcp_unreachable`` — a refusal naming the
        server for a fault that was entirely ours."""
        class _Fake(McpClient):
            def __init__(self):
                self._transport = StreamableHttpTransport(url="https://x.invalid/mcp")
                self._tools = [McpToolSpec(name="t", description="d")]

            def list_tools(self, refresh=False):
                return list(self._tools)

        McpToolBridge(_Fake(), bus).sync()
        assert bus.get_descriptor("mcp.t").sandbox_profile.allow_network is True

    def test_the_description_is_the_servers_own(self, client, bus):
        """It used to be "Add two integers. Arguments: a, b." — the names
        pasted into prose, which was the lossy half of a job the schema
        now does properly."""
        McpToolBridge(client, bus).sync()
        assert bus.describe_tool("mcp.add")["description"] == "Add two integers."

    def test_the_whole_input_schema_reaches_the_descriptor(self, client, bus):
        McpToolBridge(client, bus).sync()
        schema = bus.get_descriptor("mcp.add").input_schema
        assert schema["properties"]["a"]["type"] == "integer"
        assert sorted(schema["required"]) == ["a", "b"]

    def test_describe_tool_carries_types_and_required(self, client, bus):
        McpToolBridge(client, bus).sync()
        info = bus.describe_tool("mcp.add")
        assert info["arguments"] == "a (integer, required), b (integer, required)"
        assert info["input_schema"]["properties"]["b"]["type"] == "integer"

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
        names = McpToolBridge(client, bus, namespace="acme").sync()
        assert "acme.echo" in names


# ---------------------------------------------------------------------------
# The other transport, over a real socket
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def http_server():
    """The same stub, served over streamable HTTP on an ephemeral port.

    Module-scoped: this spawns a uvicorn process, and paying that once
    is the difference between a fast file and a slow one. The tests
    below only read from it, apart from the notification test, which
    adds a tool the others do not assert the absence of.
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
        [sys.executable, STUB, "http", str(port)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}/mcp"
    deadline = time.time() + 30
    while time.time() < deadline:
        if proc.poll() is not None:
            raise AssertionError(f"stub server exited with {proc.returncode}")
        try:
            urllib.request.urlopen(url, timeout=1)
        except urllib.error.HTTPError:
            break          # any HTTP status means the socket is answering
        except Exception:
            time.sleep(0.1)
    else:
        proc.kill()
        raise AssertionError("stub HTTP server never came up")

    try:
        yield url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover
            proc.kill()


@pytest.fixture
def http_client(http_server):
    transport = StreamableHttpTransport(url=http_server, token="test-token")
    with McpClient(transport, timeout=30.0) as c:
        yield c


class TestStreamableHttpTransport:
    """The stdio path carried all the end-to-end coverage; this closes it."""

    def test_it_initializes_over_http(self, http_client):
        assert http_client.connected is True

    def test_tools_list_over_http(self, http_client):
        names = {t.name for t in http_client.list_tools()}
        assert {"echo", "add", "always_fails"} <= names

    def test_tools_call_over_http(self, http_client):
        assert "ping" in http_client.call_tool("echo", {"text": "ping"}).text

    def test_a_failing_tool_over_http_is_an_error_result(self, http_client):
        assert http_client.call_tool("always_fails", {}).is_error is True

    def test_a_bearer_token_is_accepted(self, http_server):
        """The stub does not check it; what is under test is that adding
        an Authorization header does not break the handshake."""
        transport = StreamableHttpTransport(url=http_server, token="s3cret")
        with McpClient(transport, timeout=30.0) as client:
            assert client.list_tools()

    def test_no_token_also_connects(self, http_server):
        with McpClient(StreamableHttpTransport(url=http_server),
                       timeout=30.0) as client:
            assert client.list_tools()

    def test_a_wrong_port_refuses_at_start_rather_than_hanging(self):
        transport = StreamableHttpTransport(
            url="http://127.0.0.1:1/mcp", timeout=2.0,
        )
        with pytest.raises(McpConnectionError):
            McpClient(transport, timeout=15.0).start()

    def test_bridged_http_tools_are_network_tools(self, http_client, bus):
        McpToolBridge(http_client, bus).sync()
        assert bus.get_descriptor("mcp.echo").requires_network is True

    def test_dispatch_over_http_through_the_bus(self, http_client, bus):
        McpToolBridge(http_client, bus).sync()
        result = bus.dispatch("mcp.echo", text="over http")
        assert result.exit_code == 0
        assert "over http" in result.stdout


# ---------------------------------------------------------------------------
# Withdrawal — a server that takes a tool back
# ---------------------------------------------------------------------------

class TestWithdrawal:
    def test_sync_unregisters_what_the_server_dropped(self, client, bus):
        bridge = McpToolBridge(client, bus)
        bridge.sync()
        assert "mcp.echo" in bus.list_tools()

        # Pretend the server withdrew everything but `add`.
        client._tools = [t for t in client.list_tools() if t.name == "add"]
        bridge.sync()

        assert bus.list_tools() == ["mcp.add"]

    def test_a_withdrawn_tool_stops_being_described(self, client, bus):
        bridge = McpToolBridge(client, bus)
        bridge.sync()
        client._tools = []
        bridge.sync()
        assert "error" in bus.describe_tool("mcp.echo")

    def test_withdrawal_never_touches_a_local_tool(self, client, bus):
        """A server must not be able to unregister `fs` by omitting it."""
        bus.register(ToolDescriptor(tool_name="fs"), lambda **_kw: (0, "local", ""))
        bridge = McpToolBridge(client, bus)
        bridge.sync()
        client._tools = []
        bridge.sync()
        assert "fs" in bus.list_tools()

    def test_withdrawal_never_touches_another_bridge(self, client, bus):
        first = McpToolBridge(client, bus, namespace="a")
        second = McpToolBridge(client, bus, namespace="b")
        first.sync()
        second.sync()
        client._tools = []
        first.sync()
        assert "b.echo" in bus.list_tools()
        assert "a.echo" not in bus.list_tools()

    def test_withdraw_removes_everything_this_bridge_added(self, client, bus):
        bus.register(ToolDescriptor(tool_name="fs"), lambda **_kw: (0, "", ""))
        bridge = McpToolBridge(client, bus)
        bridge.sync()
        removed = bridge.withdraw()

        assert "mcp.echo" in removed
        assert bus.list_tools() == ["fs"]
        assert bridge.registered == []

    def test_withdraw_twice_is_harmless(self, client, bus):
        bridge = McpToolBridge(client, bus)
        bridge.sync()
        bridge.withdraw()
        assert bridge.withdraw() == []


# ---------------------------------------------------------------------------
# An admission refusal, with the body the server sent with it
# ---------------------------------------------------------------------------

def _refuser(status=503, body=b"", content_type="application/json",
             declared_length=None, hold_open=False):
    """A request handler class that answers every POST with one refusal.

    *declared_length* and *hold_open* together make the body a server never
    finishes sending: the ``Content-Length`` promises more than arrives and
    the handler then holds the connection open until the test releases it.
    """
    import threading
    from http.server import BaseHTTPRequestHandler

    class _Handler(BaseHTTPRequestHandler):
        released = threading.Event()

        def log_message(self, *args):  # the test's output is the test's
            pass

        def do_POST(self):
            length = int(self.headers.get("content-length") or 0)
            self.rfile.read(length)
            self.send_response(status)
            self.send_header("content-type", content_type)
            self.send_header(
                "content-length",
                str(len(body) if declared_length is None else declared_length))
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()
            if hold_open:
                self.released.wait(30)

        # The same refusal on a GET, for the requests httpx does not stream.
        do_GET = do_POST

    return _Handler


@contextlib.contextmanager
def _serving(handler_cls):
    """*handler_cls* on an ephemeral port, as a URL, for the block."""
    import threading
    from http.server import ThreadingHTTPServer

    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/mcp"
    finally:
        handler_cls.released.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)


def _refused_by(handler_cls, timeout=20.0):
    """Start a client against *handler_cls* and return the refusal's words."""
    with _serving(handler_cls) as url:
        transport = StreamableHttpTransport(url=url, timeout=10.0)
        with pytest.raises(McpConnectionError) as caught:
            McpClient(transport, timeout=timeout).start()
        return str(caught.value)


class TestReadingARefusalBody:
    """The parser alone: tolerant, and never a crash on a stranger's bytes."""

    def test_the_shape_a_platform_writes(self):
        refusal = parse_http_refusal(503, json.dumps({
            "code": "session_capacity",
            "detail": "all 8 sessions are in use",
            "limit": 8,
            "remedy": "retry after 30s",
        }).encode())
        said = refusal.sentence()
        assert "HTTP 503" in said
        assert "code `session_capacity`" in said
        assert "detail: all 8 sessions are in use" in said
        assert "limit: 8" in said
        assert "remedy: retry after 30s" in said

    def test_a_body_with_no_code_still_carries_its_detail(self):
        said = parse_http_refusal(429, b'{"detail": "slow down"}').sentence()
        assert "HTTP 429" in said and "detail: slow down" in said

    def test_json_with_none_of_the_keys_degrades_to_its_text(self):
        said = parse_http_refusal(503, b'{"upstream": "queue-3"}').sentence()
        assert "HTTP 503" in said and "queue-3" in said

    def test_json_that_is_not_an_object_degrades_to_its_text(self):
        said = parse_http_refusal(500, b'["boom"]').sentence()
        assert "HTTP 500" in said and "boom" in said

    def test_prose_degrades_to_its_text(self):
        said = parse_http_refusal(502, b"<html>Bad Gateway</html>").sentence()
        assert "HTTP 502" in said and "Bad Gateway" in said

    def test_an_empty_body_is_the_status_alone(self):
        said = parse_http_refusal(503, b"").sentence()
        assert said == "HTTP 503; the body was empty"

    def test_bytes_that_are_not_text_are_counted_not_quoted(self):
        said = parse_http_refusal(503, b"\xff\xfe\x00\x01" * 16).sentence()
        assert "HTTP 503" in said
        assert "64 bytes that are not text" in said
        assert said.isprintable()

    def test_a_truncated_body_says_so(self):
        said = parse_http_refusal(503, b"x" * 64, truncated=True).sentence()
        assert f"truncated at {HTTP_REFUSAL_BODY_CAP} bytes" in said

    def test_a_value_that_is_not_a_scalar_is_rendered_not_dropped(self):
        said = parse_http_refusal(
            503, b'{"code": "busy", "limit": {"sessions": 8}}').sentence()
        assert "code `busy`" in said and "sessions" in said

    def test_a_json_boolean_is_quoted_as_json_wrote_it(self):
        """`True` is Python quoted at somebody who wrote JSON."""
        said = parse_http_refusal(
            503, b'{"code": "busy", "limit": true, "remedy": false}').sentence()
        assert "limit: true" in said and "remedy: false" in said
        assert "True" not in said and "False" not in said

    def test_control_characters_never_reach_the_message(self):
        said = parse_http_refusal(
            503, b'{"code": "busy", "detail": "one\\ntwo\\u0007"}').sentence()
        assert said.isprintable()
        assert "one two" in said


class TestAnAdmissionRefusalReachesTheAgent:
    """A server that refuses at the HTTP level said *why*, in the body.

    The SDK posts with a streamed request and raises on the status line, so
    the body is dropped unread and what arrives here is the task group's
    ``ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)`` —
    which does not carry the code, the limit, the remedy, or even the status.
    An agent told only that a server "could not be reached" will retry one
    that asked it to wait.
    """

    def test_a_503_reaches_the_agent_with_its_code_and_remedy(self):
        said = _refused_by(_refuser(body=json.dumps({
            "code": "session_capacity",
            "detail": "all 8 broker sessions are in use",
            "limit": 8,
            "remedy": "retry after 30s",
        }).encode()))
        assert "HTTP 503" in said
        assert "session_capacity" in said
        assert "all 8 broker sessions are in use" in said
        assert "limit: 8" in said
        assert "retry after 30s" in said

    def test_the_existing_context_is_still_there(self):
        """Never worse than now: the transport and the target still name
        themselves, and the underlying exception is still reported."""
        handler = _refuser(body=b'{"code": "server_busy"}')
        with _serving(handler) as url:
            transport = StreamableHttpTransport(url=url, timeout=10.0)
            with pytest.raises(McpConnectionError) as caught:
                McpClient(transport, timeout=20.0).start()
            said = str(caught.value)
            assert "could not reach" in said
            assert transport.name in said
            assert url in said
            assert "server_busy" in said

    def test_any_status_that_refuses_is_read_the_same_way(self):
        said = _refused_by(_refuser(
            status=401, body=b'{"code": "no_seat", "remedy": "lease one"}'))
        assert "HTTP 401" in said
        assert "no_seat" in said and "lease one" in said

    def test_a_json_body_without_a_code_degrades_to_what_it_had(self):
        said = _refused_by(_refuser(body=b'{"queue_depth": 41}'))
        assert "HTTP 503" in said and "queue_depth" in said

    def test_a_non_json_body_degrades_to_its_text(self):
        said = _refused_by(_refuser(
            body=b"Service Unavailable", content_type="text/plain"))
        assert "HTTP 503" in said and "Service Unavailable" in said

    def test_an_empty_body_leaves_the_status(self):
        said = _refused_by(_refuser(body=b""))
        assert "HTTP 503" in said and "the body was empty" in said

    def test_a_binary_body_is_neither_quoted_nor_a_crash(self):
        said = _refused_by(_refuser(
            body=b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 4,
            content_type="application/octet-stream"))
        assert "HTTP 503" in said
        assert "bytes that are not text" in said
        assert said.isprintable()

    def test_a_huge_body_is_truncated_at_the_cap(self):
        said = _refused_by(_refuser(
            body=b"z" * 200_000, content_type="text/plain"))
        assert "HTTP 503" in said
        assert f"truncated at {HTTP_REFUSAL_BODY_CAP} bytes" in said
        assert said.count("z") <= HTTP_REFUSAL_BODY_CAP

    def test_a_body_that_never_ends_is_still_a_refusal_and_not_a_wait(self):
        """The cap is on the READ, which is the half that matters.

        This server promises five megabytes, sends eight kilobytes and then
        holds the connection open. Reading to the end would block until the
        SSE read timeout — five minutes, far past the handshake bound — and
        the caller would be told its handshake timed out rather than that
        the server refused it.
        """
        import time

        handler = _refuser(body=b"z" * 8192, declared_length=5_000_000,
                           hold_open=True, content_type="text/plain")
        started = time.time()
        said = _refused_by(handler, timeout=30.0)
        assert "HTTP 503" in said
        assert f"truncated at {HTTP_REFUSAL_BODY_CAP} bytes" in said
        assert time.time() - started < 20.0

    def test_a_refusal_is_not_carried_into_the_next_attempt(self):
        """One connection attempt, one refusal. A body read against a server
        that refused must not be quoted into a later failure to reach one
        that never answered at all."""
        transport = StreamableHttpTransport(url="", timeout=5.0)
        with _serving(_refuser(body=b'{"code": "server_busy"}')) as url:
            transport.url = url
            with pytest.raises(McpConnectionError):
                McpClient(transport, timeout=20.0).start()
            assert "server_busy" in transport.refusal()

        transport.url = "http://127.0.0.1:1/mcp"
        with pytest.raises(McpConnectionError) as caught:
            McpClient(transport, timeout=15.0).start()
        assert "server_busy" not in str(caught.value)

    def test_a_connection_that_was_refused_says_what_it_always_said(self):
        transport = StreamableHttpTransport(url="http://127.0.0.1:1/mcp",
                                            timeout=2.0)
        with pytest.raises(McpConnectionError) as caught:
            McpClient(transport, timeout=15.0).start()
        said = str(caught.value)
        assert "could not reach" in said
        assert "The server answered" not in said

    def test_a_stdio_server_has_nothing_to_say_about_http(self):
        transport = StdioTransport(
            command=sys.executable, args=["-c", "raise SystemExit(3)"])
        assert transport.refusal() == ""
        with pytest.raises(McpConnectionError) as caught:
            McpClient(transport, timeout=15.0).start()
        assert "The server answered" not in str(caught.value)

    def test_a_server_that_answers_records_no_refusal(self, http_server):
        """2xx is untouched: the hook reads nothing, and the SSE stream the
        whole protocol rides on is still the SDK's to read."""
        transport = StreamableHttpTransport(url=http_server)
        with McpClient(transport, timeout=30.0) as client:
            assert client.call_tool("echo", {"text": "ping"}).text
        assert transport.refusal() == ""


class TestTheHookStaysOnOurSideOfTheSdk:
    """No vendoring, no import-time patch: the SDK's own factory parameter."""

    def test_the_factory_returns_the_sdks_client_with_our_hook_on_it(self):
        transport = StreamableHttpTransport(url="https://spine.local/mcp")
        client = transport._http_client_factory()(
            headers={"x-test": "1"}, timeout=None, auth=None)
        assert transport._capture_refusal in client.event_hooks["response"]
        assert client.headers["x-test"] == "1"
        assert client.follow_redirects is True

    def test_an_auth_flow_that_reads_the_body_keeps_it(self):
        """A better message is not worth a broken token refresh: httpx hands
        the whole response to an auth flow that declares it needs one, and a
        hook that had consumed part of the stream would turn its 401 retry
        into a `StreamConsumed`."""
        import httpx

        class _Oauth(httpx.Auth):
            requires_response_body = True

        transport = StreamableHttpTransport(url="https://spine.local/mcp")
        client = transport._http_client_factory()(
            headers=None, timeout=None, auth=_Oauth())
        assert transport._capture_refusal not in client.event_hooks["response"]

    def test_a_client_is_still_built_if_the_sdk_helper_moves(self, monkeypatch):
        """A refusal that reads better must not be able to break a
        connection that worked."""
        monkeypatch.setitem(sys.modules, "mcp.shared._httpx_utils", None)
        transport = StreamableHttpTransport(url="https://spine.local/mcp")
        client = transport._http_client_factory()(
            headers=None, timeout=None, auth=None)
        assert transport._capture_refusal in client.event_hooks["response"]

    def test_the_hook_ignores_a_success(self):
        import asyncio

        class _Ok:
            status_code = 200

            def aiter_bytes(self):  # never called
                raise AssertionError("a 200 body is the SDK's to read")

        transport = StreamableHttpTransport(url="https://spine.local/mcp")
        asyncio.run(transport._capture_refusal(_Ok()))
        assert transport.refusal() == ""

    def test_the_hook_never_raises_on_a_body_it_cannot_read(self):
        import asyncio

        class _Broken:
            status_code = 503
            request = None

            def aiter_bytes(self):
                raise OSError("the connection went away mid-read")

        transport = StreamableHttpTransport(url="https://spine.local/mcp")
        asyncio.run(transport._capture_refusal(_Broken()))
        assert transport.refusal() == "HTTP 503; the body was empty"

    def test_the_hook_never_raises_on_a_response_it_does_not_recognise(self):
        import asyncio

        transport = StreamableHttpTransport(url="https://spine.local/mcp")
        asyncio.run(transport._capture_refusal(object()))
        assert transport.refusal() == ""

    def test_a_response_read_after_the_hook_still_has_its_body(self):
        """The invariant, demonstrated on the shape that would break: a
        request httpx does **not** stream is read by httpx itself right
        after this hook, and a stream consumed and not put back would meet
        that read as `StreamConsumed`. The bytes go back where `aread()`
        keeps them, so the next reader finds a body."""
        import asyncio

        transport = StreamableHttpTransport(url="https://spine.local/mcp")
        with _serving(_refuser(status=401,
                               body=b'{"code": "no_seat"}')) as url:
            async def _unstreamed_get():
                client = transport._http_client_factory()(
                    headers=None, timeout=None, auth=None)
                async with client:
                    response = await client.get(url)
                    return response.status_code, response.text

            status, text = asyncio.run(_unstreamed_get())

        assert status == 401
        assert "no_seat" in text            # httpx read it, after we did
        assert "no_seat" in transport.refusal()

    def test_a_helper_whose_signature_moved_still_connects(self, monkeypatch):
        """The fallback's whole promise. A renamed helper and one whose
        keywords changed are the same event to a caller, so the call is
        inside the try with the import — otherwise a better error message
        would break every connection this package makes."""
        import types

        stub = types.ModuleType("mcp.shared._httpx_utils")

        def create_mcp_http_client(http_client=None):   # the keywords moved
            raise AssertionError("our keywords cannot reach this")

        stub.create_mcp_http_client = create_mcp_http_client
        monkeypatch.setitem(sys.modules, "mcp.shared._httpx_utils", stub)

        transport = StreamableHttpTransport(url="https://spine.local/mcp")
        client = transport._http_client_factory()(
            headers={"x-test": "1"}, timeout=None, auth=None)
        assert transport._capture_refusal in client.event_hooks["response"]
        assert client.headers["x-test"] == "1"

        # and the connection it is for still happens, over a real socket
        said = _refused_by(_refuser(body=b'{"code": "session_capacity"}'))
        assert "session_capacity" in said

    def test_session_termination_is_left_to_the_sdk(self):
        """The DELETE is the one request the SDK does not stream; consuming
        its body here would take it away from the library's own read."""
        import asyncio

        class _Request:
            method = "DELETE"

        class _Gone:
            status_code = 405
            request = _Request()

            def aiter_bytes(self):
                raise AssertionError("the DELETE body is the SDK's to read")

        transport = StreamableHttpTransport(url="https://spine.local/mcp")
        asyncio.run(transport._capture_refusal(_Gone()))
        assert transport.refusal() == ""


class TestATooldescriptionIsTheSameOnEveryPython:
    """Python 3.13 dedents docstrings at compile time; a FastMCP tool's
    description IS a docstring; the description is in the model's request
    and in the system turn's catalogue. So the bridge renders it the 3.13
    way on every interpreter — the same bytes on 3.10 and 3.14 — or the
    recorded corpus, the cache key and the conformance kit's replay all
    depend on which Python recorded them (CI on 3.10 found it)."""

    def test_the_pre_313_shape_becomes_the_313_shape(self):
        from core.tools.mcp_client import docstring_dedent
        old = ("A large, typed result.\n\n    Three things a mission needs\n"
               "    never produces.\n    ")
        new = "A large, typed result.\n\nThree things a mission needs\nnever produces.\n"
        assert docstring_dedent(old) == new

    def test_it_is_idempotent_on_what_313_already_stripped(self):
        from core.tools.mcp_client import docstring_dedent
        text = "A large, typed result.\n\nThree things a mission needs\nnever produces.\n"
        assert docstring_dedent(text) == text

    def test_a_hand_written_description_passes_through(self):
        from core.tools.mcp_client import docstring_dedent
        for text in ("one line", "", "two\nlines with no indent", "  led\n  even"):
            assert docstring_dedent(text) == (text if text != "  led\n  even" else "  led\neven")
