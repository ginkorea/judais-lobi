# core/tools/mcp_client.py — a real MCP client, bridged into the ToolBus

"""Speak the Model Context Protocol, and hand what it finds to the ToolBus.

The README has called this package's tool layer "MCP-style" for a while.
It was not: :class:`core.tools.bus.ToolBus` is a local registry with
capability gating, and nothing here ever spoke JSON-RPC.  This module is
the client half of the real protocol — ``initialize``, ``tools/list``,
``tools/call``, ``notifications/tools/list_changed`` — over the official
SDK (``pip install judais-lobi[mcp]``).

**The shape is a bridge, not a second tool system.**  Each tool a server
advertises is registered into the existing ``ToolBus`` as a
:class:`~core.tools.descriptors.ToolDescriptor` whose executor dispatches
``tools/call``.  The kernel loop, the capability engine, the audit log
and the sandbox profiles keep working unchanged, and a remote governed
tool simply appears as one more tool.  The alternative — an HTTP client
inside the agent loop — would put a second, ungated path to a remote
service beside the gated one, which is exactly the caveat this bridge
exists to respect: **an agent reaches a store, a path or a compute plane
through tools or not at all.**

Names are namespaced (``mcp.search`` and not ``search``) so a server
discovered at runtime cannot shadow ``fs``, ``git`` or
``run_shell_command`` by choosing their names.

Threading: the SDK is async and every caller here is sync.  One
:class:`McpClient` owns one background thread running one event loop
holding one initialized session for its whole lifetime.  Sessions are
long-lived on purpose — ``initialize`` is a round trip and, for a stdio
server, a process spawn.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import threading
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from core.tools.descriptors import ToolDescriptor

_IPV4 = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
_SCHEMES = frozenset({"stdio", "http"})

#: What we call ourselves in ``initialize``, when nothing says otherwise.
DEFAULT_CLIENT_NAME = "judais-lobi"
CLIENT_VERSION = "1"

#: The environment variable a harness sets to say which agent is running.
CLIENT_NAME_ENV = "MCP_CLIENT_NAME"


def client_name() -> str:
    """Who this client says it is in the MCP ``initialize`` handshake.

    **A server that governs by principal still has to be able to say which
    agent acted, and it can only know what we tell it.** The handshake was sent
    with no ``clientInfo`` at all, so the SDK's own default went out and TAIPAN
    — which builds its audit actor as ``<person> via agent:<clientInfo.name>``
    — recorded every one of Tai's calls as ``analyst via agent:mcp``.

    That is not cosmetic. It made Tai indistinguishable in the governance
    record from any other bare MCP caller, and TAIPAN's bake-off harness, which
    scores an agent by filtering the shared audit trail on the actor, therefore
    measured Tai as having called **no tools at all** across a whole suite it
    had in fact worked through correctly. An agent that cannot be told apart in
    the audit cannot be graded, credited, or held to anything.

    Read from the environment rather than fixed, because this module is shared
    by three personas and the one that is running is the harness's knowledge,
    not this file's.
    """
    return (os.environ.get(CLIENT_NAME_ENV) or DEFAULT_CLIENT_NAME).strip()

#: The pin.  Kept here as well as in setup.py because this is the module a
#: reader lands on when an import fails, and "install the extra" is only
#: useful advice if it says which one.
MCP_REQUIREMENT = "mcp>=1.25,<2"


class McpUnavailable(RuntimeError):
    """The ``mcp`` SDK is not installed.

    Raised at *connect* time and never at import time: this module is
    imported by the CLI on every run, and an optional extra that breaks
    ``judais --help`` is not optional.
    """


class McpTransportMisdeclared(TypeError):
    """A transport subclass is unusable, with every reason in one message."""


class McpConnectionError(RuntimeError):
    """A server could not be reached, initialized, or answered in time."""


def require_mcp():
    """Import the SDK or refuse with the install line."""
    try:
        import mcp  # noqa: F401
        from mcp import ClientSession, types
    except ImportError as exc:  # pragma: no cover - exercised by the extra
        raise McpUnavailable(
            f"The MCP client needs the official SDK, which is an optional "
            f"extra: pip install 'judais-lobi[mcp]'  (pin: {MCP_REQUIREMENT}). "
            f"Underlying error: {exc}"
        ) from exc
    return ClientSession, types


# ---------------------------------------------------------------------------
# Transports
# ---------------------------------------------------------------------------

class McpTransport(ABC):
    """One way of reaching an MCP server.

    A subclass supplies :meth:`open_streams` and :meth:`describe`.
    :meth:`session` is the template and is **final**, because every step
    of it is a statement about order and two of them are the easy ones
    to drop in a copy:

    * *credential before connect* — a transport that cannot authenticate
      must not open the stream anyway.  A server may answer an
      unauthenticated call differently (a public tool list, a redirect to
      a login page) and the caller then debugs the answer instead of the
      missing token;
    * *initialize before yield* — the protocol has no meaning before the
      handshake, and a caller handed a live-looking session that has not
      initialized gets a protocol error attributed to its own first call.

    What a subclass declares is checked at **class creation**, and every
    problem is collected into one message: finding out about the second
    mistake only after fixing the first is how a five-minute fix becomes
    an afternoon.
    """

    #: What this transport reaches, in words a person reads.  It goes into
    #: every refusal, so it names a *target* and never an address —
    #: "the mission spine's MCP server", not "127.0.0.1:8091".  An address
    #: in a repeated string is the one that gets pasted into a ticket.
    name: str = ""
    #: ``stdio`` or ``http``.  Checked against a closed set.
    scheme: str = ""
    #: Whether reaching this server leaves the host.  Feeds
    #: ``ToolDescriptor.requires_network``, so the ToolBus applies its
    #: network gate to bridged tools for the right transports and not for
    #: a co-located subprocess.
    uses_network: bool = False

    _REQUIRED: Tuple[str, ...] = ("open_streams", "describe")
    _FINAL: Tuple[str, ...] = ("session",)

    def __init_subclass__(cls, **kw: Any) -> None:
        super().__init_subclass__(**kw)
        if getattr(cls, "abstract", False):  # an intermediate base is fine
            return
        problems: List[str] = []
        if not cls.name:
            problems.append(
                "`name` is empty; every refusal this transport raises has to "
                "say what could not be reached, and an unnamed one sends the "
                "reader to check whichever server they thought of first"
            )
        elif "://" in cls.name or _IPV4.search(cls.name):
            problems.append(
                f"`name` is {cls.name!r}, which contains an address. It is the "
                f"one part of a refusal that is always repeated, so it names a "
                f"target and never an endpoint"
            )
        if cls.scheme not in _SCHEMES:
            problems.append(
                f"`scheme` is {cls.scheme!r}; it must be one of "
                f"{sorted(_SCHEMES)}. The bridge reads it to decide whether a "
                f"bridged tool is a network tool, and an unrecognised value "
                f"would silently mean 'not'"
            )
        for attr in cls._REQUIRED:
            if getattr(cls, attr, None) is getattr(McpTransport, attr, None):
                problems.append(
                    f"does not implement `{attr}`; the base's stub refuses "
                    f"rather than inventing an answer"
                )
        for attr in cls._FINAL:
            if attr in cls.__dict__:
                problems.append(
                    f"overrides `{attr}`, which is final. It is a statement "
                    f"about ORDER — credential before connect, initialize "
                    f"before yield — and a re-implementation is how a session "
                    f"gets handed out before its handshake. Override "
                    f"`open_streams` or `credential` instead"
                )
        if problems:
            raise McpTransportMisdeclared(
                f"{cls.__name__} is not a usable McpTransport:\n  - "
                + "\n  - ".join(problems)
            )

    # ── the template. FINAL. ────────────────────────────────────────────

    @asynccontextmanager
    async def session(self, message_handler: Optional[Callable] = None):
        """Yield an initialized ``ClientSession``.  See the class docstring."""
        ClientSession, _types = require_mcp()

        problems = self.check()
        if problems:
            raise McpConnectionError(
                f"{self.name} is not configured to be reachable:\n  - "
                + "\n  - ".join(problems)
            )

        credential = self.credential()  # resolved BEFORE anything opens

        async with self.open_streams(credential) as streams:
            read_stream, write_stream = streams[0], streams[1]
            async with ClientSession(
                read_stream, write_stream, message_handler=message_handler,
                client_info=_types.Implementation(
                    name=client_name(), version=CLIENT_VERSION),
            ) as sess:
                await sess.initialize()
                yield sess

    # ── what a subclass supplies ────────────────────────────────────────

    @abstractmethod
    @asynccontextmanager
    async def open_streams(self, credential: Optional[str]) -> AsyncIterator[Sequence[Any]]:
        """Open the byte streams.  Yields ``(read, write, *rest)``."""
        raise NotImplementedError

    @abstractmethod
    def describe(self) -> str:
        """One line naming what this reaches, without a secret in it."""
        raise NotImplementedError

    def credential(self) -> Optional[str]:
        """Resolve the credential, or ``None`` where none is used."""
        return None

    def check(self) -> List[str]:
        """Instance-level configuration problems, all of them."""
        return []

    def __repr__(self) -> str:  # pragma: no cover - diagnostic
        return f"<{type(self).__name__} {self.describe()}>"


class StdioTransport(McpTransport):
    """Spawn a server as a child process and speak MCP over its stdio.

    The default for a co-located server: no port, no token, and the
    server's lifetime is the client's.
    """

    name = "an MCP server run as a local subprocess"
    scheme = "stdio"
    uses_network = False

    def __init__(
        self,
        command: str,
        args: Optional[Sequence[str]] = None,
        env: Optional[Mapping[str, str]] = None,
        cwd: Optional[str] = None,
    ):
        self.command = command
        self.args = list(args or [])
        self.env = dict(env) if env is not None else None
        self.cwd = cwd

    def check(self) -> List[str]:
        problems: List[str] = []
        if not (self.command or "").strip():
            problems.append("`command` is empty; there is no process to start")
        return problems

    @asynccontextmanager
    async def open_streams(self, credential: Optional[str]) -> AsyncIterator[Sequence[Any]]:
        from mcp import StdioServerParameters
        from mcp.client.stdio import stdio_client

        params = StdioServerParameters(
            command=self.command, args=self.args, env=self.env, cwd=self.cwd,
        )
        async with stdio_client(params) as streams:
            yield streams

    def describe(self) -> str:
        return " ".join([self.command, *self.args]).strip()


class StreamableHttpTransport(McpTransport):
    """Reach a server over streamable-HTTP with a bearer token.

    The token is resolved by :meth:`credential` before the stream opens,
    and is never put in :attr:`name` or :meth:`describe` — those two
    strings end up in refusals and logs.
    """

    name = "an MCP server reached over streamable HTTP"
    scheme = "http"
    uses_network = True

    def __init__(
        self,
        url: str,
        token: Optional[str] = None,
        headers: Optional[Mapping[str, str]] = None,
        timeout: float = 30.0,
    ):
        self.url = url
        self._token = token
        self.headers = dict(headers or {})
        self.timeout = timeout

    def credential(self) -> Optional[str]:
        return self._token

    def check(self) -> List[str]:
        problems: List[str] = []
        url = (self.url or "").strip()
        if not url:
            problems.append("`url` is empty; there is nothing to connect to")
        elif not url.startswith(("http://", "https://")):
            problems.append(
                f"`url` is {url!r}, which has no http(s) scheme; "
                f"streamable HTTP is the only thing this transport speaks"
            )
        return problems

    @asynccontextmanager
    async def open_streams(self, credential: Optional[str]) -> AsyncIterator[Sequence[Any]]:
        from mcp.client.streamable_http import streamablehttp_client

        # This name is deprecated in favour of `streamable_http_client`, and
        # it is used anyway, deliberately. The replacement is NOT a rename:
        # it dropped `headers` and `timeout` for a prepared
        # `http_client: httpx.AsyncClient`, and it does not exist at the
        # bottom of the pin (mcp 1.25). Supporting both would mean a second
        # code path only one of which this suite can exercise, and an
        # untested branch guarding a signature nobody here has run is worse
        # than a warning. Revisit when the floor moves.
        headers = dict(self.headers)
        if credential:
            headers["Authorization"] = f"Bearer {credential}"
        async with streamablehttp_client(
            self.url, headers=headers or None, timeout=self.timeout,
        ) as streams:
            yield streams

    def describe(self) -> str:
        return self.url


# ---------------------------------------------------------------------------
# What a server told us
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class McpToolSpec:
    """One entry of ``tools/list``."""

    name: str
    description: str = ""
    input_schema: Dict[str, Any] = field(default_factory=dict)

    @property
    def argument_names(self) -> List[str]:
        props = (self.input_schema or {}).get("properties") or {}
        return sorted(props)

    @property
    def required_arguments(self) -> List[str]:
        return list((self.input_schema or {}).get("required") or [])


@dataclass(frozen=True)
class McpCallResult:
    """One answer to ``tools/call``, flattened to what the ToolBus carries."""

    tool: str
    text: str = ""
    is_error: bool = False
    structured: Optional[Any] = None

    def as_tuple(self) -> Tuple[int, str, str]:
        """``(exit_code, stdout, stderr)`` — the shape ToolBus unpacks.

        A tool-level error is a non-zero exit and not an exception: the
        model asked for something the server declined, which is an
        answer the loop should see and act on, not a crash.

        This drops :attr:`structured` whenever there is text, which is
        the ordinary case — see :meth:`as_bus_tuple`, which does not.
        """
        if self.is_error:
            return (1, "", self.text)
        return (0, self.text, "")

    @property
    def evidence(self) -> str:
        """The structured payload as JSON, or ``""``.

        ``structuredContent`` is the *typed* answer — the numbers and
        identifiers a governed view is made of — and the text block
        beside it is usually a rendering of it for a human. Keeping only
        the rendering is how a caller ends up parsing figures back out of
        a table it was handed, which is the failure mode a typed view
        exists to remove.
        """
        if self.structured is None:
            return ""
        return json.dumps(self.structured, ensure_ascii=False, default=str)

    def as_bus_tuple(self) -> Tuple[int, str, str, str]:
        """``(exit_code, stdout, stderr, evidence)``.

        The four-element form ``ToolBus.dispatch`` unpacks into
        ``ToolResult.evidence``. Kept separate from :meth:`as_tuple`
        rather than replacing it: three-tuples are the executor contract
        every other tool in this package speaks, and widening the one
        method both of them go through would change that contract for
        tools that have nothing structured to carry.
        """
        return (*self.as_tuple(), self.evidence)


# ---------------------------------------------------------------------------
# The client
# ---------------------------------------------------------------------------

class McpClient:
    """A synchronous handle on one long-lived MCP session.

    Use it as a context manager.  ``start`` spawns the thread and blocks
    until the session is initialized and ``tools/list`` has answered, so
    a caller that gets a client back has a *working* client — a
    connection error surfaces where it was caused.
    """

    def __init__(
        self,
        transport: McpTransport,
        *,
        timeout: float = 30.0,
        on_tools_changed: Optional[Callable[[List[McpToolSpec]], None]] = None,
    ):
        self._transport = transport
        self._timeout = timeout
        self._on_tools_changed = on_tools_changed

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._session: Any = None
        self._stop: Optional[asyncio.Event] = None
        self._ready = threading.Event()
        self._error: Optional[BaseException] = None
        self._tools: List[McpToolSpec] = []
        self._lock = threading.Lock()
        #: Bumped every time a ``notifications/tools/list_changed`` has been
        #: acted on.  A test can wait on it; a bridge can compare it.
        self.tools_generation = 0

    # ── lifecycle ───────────────────────────────────────────────────────

    @property
    def transport(self) -> McpTransport:
        return self._transport

    @property
    def connected(self) -> bool:
        return self._session is not None

    def start(self) -> "McpClient":
        if self._thread is not None:
            return self
        require_mcp()  # refuse here, not from inside a worker thread
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run, name="mcp-client", daemon=True,
        )
        self._thread.start()
        if not self._ready.wait(self._timeout):
            self.stop()
            raise McpConnectionError(
                f"{self._transport.name} did not initialize within "
                f"{self._timeout:g}s ({self._transport.describe()})"
            )
        if self._error is not None:
            err = self._error
            self.stop()
            raise McpConnectionError(
                f"could not reach {self._transport.name} "
                f"({self._transport.describe()}): {type(err).__name__}: {err}"
            ) from err
        return self

    def stop(self) -> None:
        loop, thread = self._loop, self._thread
        if loop is not None and self._stop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(self._stop.set)
        if thread is not None:
            thread.join(timeout=self._timeout)
        self._thread = None
        self._loop = None
        self._session = None

    def __enter__(self) -> "McpClient":
        return self.start()

    def __exit__(self, *exc_info) -> None:
        self.stop()

    # ── the worker ──────────────────────────────────────────────────────

    def _run(self) -> None:
        assert self._loop is not None
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._main())
        finally:
            try:
                self._loop.close()
            except Exception:  # pragma: no cover - shutdown noise
                pass

    async def _main(self) -> None:
        self._stop = asyncio.Event()
        try:
            async with self._transport.session(
                message_handler=self._on_message,
            ) as sess:
                self._session = sess
                self._tools = await self._fetch_tools(sess)
                self._ready.set()
                await self._stop.wait()
        except BaseException as exc:  # noqa: BLE001 — reported to start()
            self._error = exc
            self._ready.set()
        finally:
            self._session = None

    async def _fetch_tools(self, sess: Any) -> List[McpToolSpec]:
        result = await sess.list_tools()
        specs = []
        for tool in result.tools:
            schema = getattr(tool, "inputSchema", None) or {}
            specs.append(
                McpToolSpec(
                    name=tool.name,
                    description=tool.description or "",
                    input_schema=dict(schema),
                )
            )
        return specs

    async def _on_message(self, message: Any) -> None:
        """Handle ``notifications/tools/list_changed``.

        The refresh is scheduled as a task rather than awaited here: this
        runs on the session's receive loop, and issuing a request from
        inside it would wait for a response the same loop has to read.
        """
        _ClientSession, types = require_mcp()
        root = getattr(message, "root", message)
        if isinstance(root, types.ToolListChangedNotification):
            asyncio.get_running_loop().create_task(self._refresh_tools())

    async def _refresh_tools(self) -> None:
        sess = self._session
        if sess is None:
            return
        try:
            tools = await self._fetch_tools(sess)
        except Exception:  # pragma: no cover - a dead session stops us anyway
            return
        self._tools = tools
        with self._lock:
            self.tools_generation += 1
        if self._on_tools_changed is not None:
            try:
                self._on_tools_changed(list(tools))
            except Exception:  # pragma: no cover
                pass  # a listener must never kill the session

    def _submit(self, coro):
        loop = self._loop
        if loop is None or self._session is None:
            raise McpConnectionError(
                f"not connected to {self._transport.name}; call start() first"
            )
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result(self._timeout)

    # ── protocol ────────────────────────────────────────────────────────

    def list_tools(self, refresh: bool = False) -> List[McpToolSpec]:
        """The server's ``tools/list``, from cache unless asked otherwise."""
        if refresh:
            if self._session is None:
                raise McpConnectionError(
                    f"not connected to {self._transport.name}; call start() first"
                )
            self._tools = self._submit(self._fetch_tools(self._session))
        return list(self._tools)

    def call_tool(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> McpCallResult:
        """``tools/call``, flattened to text plus an error flag."""
        session = self._session
        if session is None:
            raise McpConnectionError(
                f"not connected to {self._transport.name}; call start() first"
            )
        raw = self._submit(session.call_tool(name, arguments or {}))
        return self._flatten(name, raw)

    @staticmethod
    def _flatten(name: str, raw: Any) -> McpCallResult:
        parts: List[str] = []
        for block in getattr(raw, "content", None) or []:
            text = getattr(block, "text", None)
            if text:
                parts.append(text)
                continue
            # A non-text block (image, resource link) is reported as its
            # type rather than dropped: a silently empty result reads as a
            # tool that did nothing.
            parts.append(f"[{getattr(block, 'type', 'content')}]")
        structured = getattr(raw, "structuredContent", None)
        if not parts and structured is not None:
            parts.append(json.dumps(structured, ensure_ascii=False, default=str))
        return McpCallResult(
            tool=name,
            text="\n".join(parts),
            is_error=bool(getattr(raw, "isError", False)),
            structured=structured,
        )


# ---------------------------------------------------------------------------
# The bridge
# ---------------------------------------------------------------------------

class McpToolBridge:
    """Register a server's tools into an existing :class:`ToolBus`.

    This is the whole point of the module.  Nothing downstream learns
    that a tool came from a server: the kernel loop dispatches it by
    name, the capability engine gates it on
    :attr:`scopes`, and the audit log records it like any other.
    """

    #: Prefix on every bridged name.  Not decoration: a server chooses the
    #: names it advertises, and without a namespace one that calls itself
    #: ``run_shell_command`` would replace the local tool of that name in
    #: the bus's registry.
    DEFAULT_NAMESPACE = "mcp"

    #: The scope a bridged tool needs.  One scope for all of them, because
    #: the decision a policy actually wants to express is "may this agent
    #: call out to this server at all"; the server does the per-tool
    #: authorization, and duplicating it here would be a second opinion
    #: that drifts.
    DEFAULT_SCOPES: Tuple[str, ...] = ("mcp.call",)

    def __init__(
        self,
        client: McpClient,
        bus: Any,
        *,
        namespace: str = DEFAULT_NAMESPACE,
        scopes: Sequence[str] = DEFAULT_SCOPES,
    ):
        self._client = client
        self._bus = bus
        self._namespace = namespace.strip(".") or self.DEFAULT_NAMESPACE
        self._scopes = list(scopes)
        self._registered: List[str] = []

    @property
    def registered(self) -> List[str]:
        """Bus names this bridge has registered, in ``tools/list`` order."""
        return list(self._registered)

    def local_name(self, remote: str) -> str:
        return f"{self._namespace}.{remote}"

    def sync(self, refresh: bool = False) -> List[str]:
        """Reconcile the bus against ``tools/list``.

        Registers what the server now advertises and **unregisters what
        it withdrew**, so the bus never offers the model a tool whose
        only possible answer is an error from the far end.

        Only names this bridge put there are removed. Another bridge's
        namespace, and every compiled-in tool, are untouched — a server
        cannot cause the removal of `fs` by any list it sends.
        """
        specs = self._client.list_tools(refresh=refresh)
        names = []
        for spec in specs:
            name = self.local_name(spec.name)
            self._bus.register(self._descriptor(spec, name), self._executor(spec))
            names.append(name)

        for gone in [n for n in self._registered if n not in names]:
            self._bus.unregister(gone)

        self._registered = names
        return list(names)

    def follow_changes(self) -> None:
        """Re-sync whenever the server says its tool list changed.

        Installed as the client's ``on_tools_changed`` listener.
        """
        self._client._on_tools_changed = lambda _specs: self.sync()

    def withdraw(self) -> List[str]:
        """Unregister everything this bridge added; return what went.

        For a session ending or a server going away. Without it every
        bridged descriptor outlives the client and dispatches into a
        closed transport.
        """
        removed = [n for n in self._registered if self._bus.unregister(n)]
        self._registered = []
        return removed

    def _descriptor(self, spec: McpToolSpec, name: str) -> ToolDescriptor:
        # The schema is carried whole and NOT flattened into the
        # description. It used to be reduced to "Arguments: a, b, c." —
        # which threw away every type, every `required` and every enum,
        # the three things that decide whether a model's first call to a
        # faceted search is a valid one. Renderers summarise it
        # (`summarize_input_schema`); the descriptor keeps it.
        return ToolDescriptor(
            tool_name=name,
            required_scopes=list(self._scopes),
            requires_network=self._client.transport.uses_network,
            network_scopes=list(self._scopes),
            description=spec.description or f"MCP tool {spec.name}.",
            input_schema=dict(spec.input_schema or {}),
        )

    def _executor(self, spec: McpToolSpec) -> Callable[..., Tuple[int, str, str, str]]:
        client = self._client

        def _call(**arguments: Any) -> Tuple[int, str, str, str]:
            try:
                return client.call_tool(spec.name, arguments).as_bus_tuple()
            except McpConnectionError as exc:
                return (1, "", f"mcp_unreachable: {exc}", "")

        _call.__name__ = f"mcp_{spec.name}"
        _call.__doc__ = spec.description or f"Dispatches tools/call for {spec.name}."
        return _call
