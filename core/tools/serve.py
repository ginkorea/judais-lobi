# core/tools/serve.py — the built-in tools, served over MCP

"""Publish this package's own tools as an MCP server.  One owner, two transports.

``core.tools.mcp_client`` is the client half: it takes somebody else's
server and registers what it advertises into our
:class:`~core.tools.bus.ToolBus`.  This is the mirror of it.  It takes the
tools that are *already* on that bus — ``fs``, ``git``, ``repo_map``,
``patch``, ``verify``, ``run_shell_command``, ``run_python_code``, the
research tools — and publishes them over the Model Context Protocol, so any
MCP client (another agent, a desktop app, a platform's plane) can call them.

**Through the same bus, not beside it.**  Every call this server accepts is
dispatched with :meth:`ToolBus.dispatch`, which means the profile's
capability check, the sandbox and the audit log all apply *on the serving
side* — a client that reaches ``run_python_code`` here gets bwrap because
this process put it there, and a scope the profile does not grant comes back
as the very sentence the CLI prints.  The alternative — a second registry
that re-implements the tools for the protocol — would be a second opinion
about what is allowed, and the day the two disagree is the day the governed
path is the one nobody took.

That is also why there are no descriptors in this file.  The tool set is
whatever the bus holds, the scopes are the descriptor's, the answer is the
bus's :class:`~core.tools.bus.ToolResult` rendered as MCP content.  This
module owns exactly one fact of its own: how a bus result becomes a
``CallToolResult``.

    python -m core.tools.serve                       # stdio, profile SAFE
    python -m core.tools.serve --profile dev         # stdio, code plane on
    python -m core.tools.serve --http 127.0.0.1:8765 # streamable HTTP
    python -m core.tools.serve --list                # what would be served

No new dependency and therefore **no new extra**: the server half lives in
the same ``mcp`` SDK the client half needs (FastMCP's own transports —
stdio, and starlette+uvicorn for streamable HTTP — are its dependencies), so
``pip install 'judais-lobi[mcp]'`` (or ``[mission]``) is all a host needs.

The protocol is spoken through the SDK's low-level ``Server`` rather than
``FastMCP``.  FastMCP derives a tool's schema from a Python function's type
hints, and the schemas here are not ours to derive twice: a bus tool's
arguments are declared by its descriptor (``input_schema``) or by its own
callable, and the server's job is to publish them, not to restate them in a
signature it invented.
"""

from __future__ import annotations

import argparse
import dataclasses
import inspect
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from core.policy.audit import default_audit_logger
from core.policy.profiles import PROFILE_ENV_VAR, select_profile

#: What this server calls itself in the MCP handshake.  A client that
#: bridges several planes shows this name beside the namespace it gave us.
SERVER_NAME = "judais-lobi-tools"

#: The environment form of ``--token``, and the reason it exists: a bearer
#: token in ``argv`` is visible in ``ps`` to every other user on the host.
#: The same trade-off ``--mcp-token`` documents on the client side.
TOKEN_ENV = "MCP_SERVE_TOKEN"

#: Annotation names this maps to JSON Schema types.  Names and not classes
#: because the tool modules use ``from __future__ import annotations``, so an
#: annotation arrives here as the string a reader typed.  Anything not in
#: this table is published without a ``type`` — a schema that says nothing
#: about an argument is honest, and one that guesses wrong sends a model to
#: fix an argument that was already right.
_JSON_TYPES: Dict[str, str] = {
    "str": "string",
    "int": "integer",
    "float": "number",
    "bool": "boolean",
    "dict": "object",
    "list": "array",
}


def server_version() -> Optional[str]:
    """The installed distribution's version, or ``None`` in a checkout.

    Derived rather than written down: ``VERSION`` lives in ``setup.py`` and
    a second copy of it here would be right until the first release nobody
    remembered to edit twice.
    """
    try:
        from importlib.metadata import version

        return version("judais-lobi")
    except Exception:  # pragma: no cover - a source checkout, or no metadata
        return None


# ---------------------------------------------------------------------------
# The bus this server serves
# ---------------------------------------------------------------------------

def build_tools(
    profile: Optional[str] = None,
    *,
    sandbox_request: Optional[str] = None,
    audit: Optional[str] = None,
    elfenv: Optional[str] = None,
):
    """The default tool registry, built the way every other caller builds it.

    :class:`core.tools.Tools` is the one builder — the CLI's agent
    constructs it with exactly these arguments — so the served bus is the
    bus a local run would have had, down to which sandbox was selected and
    where the audit file went.  A second builder here would be the drift
    this whole module exists to prevent.

    *profile* is the ``--profile`` word or ``None``; resolution (flag, then
    ``JUDAIS_LOBI_PROFILE``, then SAFE) belongs to
    :func:`~core.policy.profiles.select_profile` and is not repeated.
    *audit* is the ``--audit`` path, ``"off"``, or ``None`` for the
    ``JUDAIS_LOBI_AUDIT`` default — one resolution, in
    :func:`~core.policy.audit.default_audit_logger`.

    *elfenv* is the Python environment ``run_python_code`` runs in, and it
    defaults to **the one this server is running in** (``sys.prefix``).  The
    CLI's agent points it at the personality's env, which it creates on
    first use; a server that built a fresh virtualenv on startup would pay
    for it on every spawn, including the ones that never get a call for the
    code plane.  Point ``--elfenv`` at a dedicated environment when served
    code should not see the server's own imports.
    """
    from core.tools import Tools

    return Tools(
        elfenv=Path(elfenv) if elfenv else Path(sys.prefix),
        profile=select_profile(profile),
        sandbox_request=sandbox_request,
        audit=default_audit_logger(audit),
    )


def served_names(bus: Any, only: Sequence[str] = ()) -> List[str]:
    """Which tools this server publishes: everything, or ``--only``'s subset.

    A name in *only* that is not on the bus is a refusal naming it and
    listing what is there.  Silently serving four of the five tools an
    operator asked for is how a client discovers the missing one by asking
    a question it cannot answer.
    """
    available = list(bus.list_tools())
    wanted = [name.strip() for name in only if name.strip()]
    if not wanted:
        return available
    missing = [name for name in wanted if name not in available]
    if missing:
        raise SystemExit(
            f"--only names {len(missing)} tool(s) this bus does not have: "
            f"{', '.join(missing)}. On the bus: {', '.join(available)}"
        )
    return [name for name in available if name in wanted]


def schema_from_signature(executor: Callable) -> Dict[str, Any]:
    """A tool's arguments as JSON Schema, read off the callable itself.

    The fallback for a tool whose descriptor carries no ``input_schema`` —
    which is every compiled-in tool, because their arguments have always
    been declared by their own ``__call__`` and nowhere else.  Reading the
    signature is therefore not a second declaration; it is the only one
    there is, published instead of retyped.

    ``**kwargs`` becomes ``additionalProperties: true`` rather than being
    dropped: the multi-action tools take their per-action arguments that
    way, and a schema that forbade them would forbid ``fs write``'s
    ``content``.
    """
    try:
        signature = inspect.signature(executor)
    except (TypeError, ValueError):  # pragma: no cover - exotic callables
        return {"type": "object", "properties": {}, "additionalProperties": True}

    properties: Dict[str, Any] = {}
    required: List[str] = []
    open_ended = False
    for name, parameter in signature.parameters.items():
        if name == "self":
            continue
        if parameter.kind in (parameter.VAR_KEYWORD, parameter.VAR_POSITIONAL):
            open_ended = True
            continue
        annotation = parameter.annotation
        declared = getattr(annotation, "__name__", None) or str(annotation)
        entry: Dict[str, Any] = {}
        if declared in _JSON_TYPES:
            entry["type"] = _JSON_TYPES[declared]
        properties[name] = entry
        if parameter.default is inspect.Parameter.empty:
            required.append(name)

    schema: Dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    if open_ended:
        schema["additionalProperties"] = True
    return schema


def input_schema_for(bus: Any, name: str) -> Dict[str, Any]:
    """The schema this server publishes for one bus tool.

    Three sources, in the order they are authoritative:

    * the descriptor's own ``input_schema`` when it has one — a bridged
      tool's schema is its server's, verbatim, and must not be reshaped by
      passing through us;
    * otherwise the executor's signature (:func:`schema_from_signature`);
    * plus, for a multi-action tool, an ``action`` enum built from
      ``descriptor.action_scopes``.  That mapping is the one owner of which
      actions exist — it is what the bus checks scopes against — so an enum
      derived from it cannot drift from the set the bus will accept.
    """
    info = bus.describe_tool(name)
    if info.get("input_schema"):
        return dict(info["input_schema"])

    executor = bus.get_executor(name)
    schema = schema_from_signature(executor) if executor is not None else {
        "type": "object", "properties": {}, "additionalProperties": True}

    actions = info.get("actions") or []
    if actions:
        properties = dict(schema.get("properties") or {})
        entry = dict(properties.get("action") or {})
        entry["type"] = "string"
        entry["enum"] = list(actions)
        properties["action"] = entry
        schema["properties"] = properties
        required = list(schema.get("required") or [])
        if "action" not in required:
            required.insert(0, "action")
        schema["required"] = required
    return schema


def result_payload(result: Any) -> Dict[str, Any]:
    """One :class:`~core.tools.bus.ToolResult`, whole, as a JSON object.

    Whole and not summarised, because MCP's content blocks can carry a
    string and this cannot: the exit code, the stderr *beside* a non-empty
    stdout, the granted scopes, and the typed ``evidence`` a governed view
    is made of.  A client that flattens the answer to its text — which is
    what our own bridge does — still gets the text; a client that wants the
    parts finds them in ``structuredContent``, and they are the same object
    an in-process caller holds.  That equality is the parity this server
    claims, and ``tests/test_mcp_serve.py`` asserts it call for call.
    """
    return dataclasses.asdict(result)


def result_text(result: Any) -> str:
    """What a reader of the tool result sees: stdout, or the failure.

    The same choice ``Tools.run`` makes for a legacy caller, so the text a
    bridged tool hands back to a model is the text the local tool would
    have handed it.
    """
    if result.exit_code == 0:
        return result.stdout
    return result.stderr or result.stdout


# ---------------------------------------------------------------------------
# The protocol
# ---------------------------------------------------------------------------

def build_server(bus: Any, names: Sequence[str]):
    """A low-level MCP ``Server`` publishing *names* off *bus*.

    ``validate_input=False`` on the call handler is deliberate.  The SDK can
    check arguments against the advertised schema and refuse before the
    handler runs — and a call refused there reaches no bus, so it is in no
    audit log and gets an answer this framework did not write.  Everything
    goes to :meth:`ToolBus.dispatch`, which records what was attempted and
    answers in the harness's own words; a malformed call is a tool error
    like any other, which is exactly what an in-process caller gets.
    """
    from mcp import types
    from mcp.server.lowlevel import Server

    import anyio.to_thread

    server = Server(SERVER_NAME, version=server_version())
    published = list(names)

    @server.list_tools()
    async def _list_tools() -> List[Any]:
        return [
            types.Tool(
                name=name,
                description=bus.describe_tool(name).get("description") or "",
                inputSchema=input_schema_for(bus, name),
            )
            for name in published
        ]

    @server.call_tool(validate_input=False)
    async def _call_tool(name: str, arguments: Dict[str, Any]):
        if name not in published:
            # Refused here rather than dispatched, because "not served" is
            # this server's fact and not the bus's: the tool may well be
            # registered and simply held back by ``--only``, and answering
            # `unknown_tool` would send the caller looking for a tool that
            # exists.
            return types.CallToolResult(
                content=[types.TextContent(
                    type="text",
                    text=json.dumps({
                        "error": "not_served",
                        "tool": name,
                        "message": (f"{name} is not served by this server; "
                                    f"it publishes: {', '.join(published)}"),
                    }, sort_keys=True))],
                isError=True,
            )
        # Off the event loop: a bus dispatch runs a subprocess (and a
        # sandboxed one at that), and a server that awaited it on its own
        # loop would stop answering everything else — including the
        # cancellation the client sends when it gives up waiting.
        result = await anyio.to_thread.run_sync(
            lambda: bus.dispatch(name, **dict(arguments or {})))
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=result_text(result))],
            structuredContent=result_payload(result),
            isError=result.exit_code != 0,
        )

    return server


def run_stdio(server: Any) -> None:
    """Speak MCP on this process's stdin/stdout.

    Nothing may print to stdout while this runs — it is the wire.  Every
    line this module says goes to stderr for that reason, and the bus's own
    audit-failure warning already does.
    """
    import anyio
    from mcp.server.stdio import stdio_server

    async def _main() -> None:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream, write_stream,
                server.create_initialization_options(),
            )

    anyio.run(_main)


class BearerGate:
    """ASGI wrapper refusing any request without the expected bearer token.

    The mirror of ``--mcp-token`` on the client side, and the reason it is a
    wrapper rather than a check inside the handler: a request that is not
    authorized must not reach the session manager at all, because the
    session manager's job is to *keep state* for whoever asked.

    It answers 401 with a JSON body and no detail about what was wrong with
    the credential — "which half of my token is wrong" is not a question a
    server should help an unauthenticated caller answer.
    """

    def __init__(self, app: Callable, token: str):
        self._app = app
        self._token = token

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") == "http" and not self._authorized(scope):
            body = json.dumps({"error": "unauthorized"}).encode("utf-8")
            await send({
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                    (b"www-authenticate", b"Bearer"),
                ],
            })
            await send({"type": "http.response.body", "body": body})
            return
        await self._app(scope, receive, send)

    def _authorized(self, scope) -> bool:
        for key, value in scope.get("headers") or []:
            if key.lower() != b"authorization":
                continue
            offered = value.decode("latin-1").strip()
            prefix = "bearer "
            if offered.lower().startswith(prefix):
                offered = offered[len(prefix):].strip()
            # Constant-time: the comparison of a secret is one of the few
            # places in this repository where how long a check takes is
            # itself an answer.
            import hmac

            return hmac.compare_digest(offered, self._token)
        return False


def http_app(server: Any, token: str = ""):
    """A Starlette app serving *server* at ``/mcp`` over streamable HTTP.

    Returned rather than run, so a test can drive it without a socket and a
    host can mount it inside its own application.
    """
    import contextlib

    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
    from starlette.applications import Starlette
    from starlette.routing import Mount

    manager = StreamableHTTPSessionManager(app=server)

    async def _handle(scope, receive, send) -> None:
        await manager.handle_request(scope, receive, send)

    @contextlib.asynccontextmanager
    async def _lifespan(_app):
        async with manager.run():
            yield

    endpoint: Any = _handle
    if token:
        endpoint = BearerGate(_handle, token)
    return Starlette(routes=[Mount("/mcp", app=endpoint)], lifespan=_lifespan)


def run_http(server: Any, host: str, port: int, token: str = "") -> None:
    """Serve over streamable HTTP at ``http://host:port/mcp``."""
    import uvicorn

    uvicorn.run(http_app(server, token), host=host, port=port,
                log_level="error")


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------

def parse_host_port(value: str) -> Tuple[str, int]:
    """``"127.0.0.1:8765"`` → ``("127.0.0.1", 8765)``.

    A bare port is refused rather than defaulted to ``0.0.0.0``: binding a
    tool plane to every interface is a decision, and it is not one a missing
    half of an argument should make.
    """
    host, sep, port = str(value or "").rpartition(":")
    if not sep or not host.strip() or not port.strip().isdigit():
        raise SystemExit(
            f"--http wants HOST:PORT (for example 127.0.0.1:8765); got "
            f"{value!r}. The host is not optional — binding a tool plane to "
            f"every interface is a decision, not a default"
        )
    return host.strip(), int(port)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m core.tools.serve",
        description=(
            "Serve this package's built-in tools over MCP, dispatched "
            "through the same ToolBus a local run uses — so the profile, "
            "the sandbox and the audit log apply on the serving side."),
    )
    parser.add_argument(
        "--profile", type=str, default=None,
        help=(f"Capability profile for everything this server runs: safe, "
              f"dev, ops, god. Default SAFE (env: {PROFILE_ENV_VAR}). This is "
              f"the ONE gate on a client that reaches this plane"))
    parser.add_argument(
        "--unsandboxed", action="store_true",
        help=("Run tools with no isolation. Off by default: with bubblewrap "
              "present the served bus sandboxes exactly as the CLI does, and "
              "a client's `run_python_code` is isolated by THIS process"))
    parser.add_argument(
        "--audit", type=str, default=None, metavar="PATH",
        help=("Where the audit log goes ('off' for none). Default: the "
              "JUDAIS_LOBI_AUDIT resolution. The rows are written HERE, by "
              "the serving bus, which is the only side that knows what ran"))
    parser.add_argument(
        "--elfenv", type=str, default=None, metavar="PATH",
        help=("The Python environment `run_python_code` runs in. Default: "
              "the environment this server is running in"))
    parser.add_argument(
        "--only", type=str, default="", metavar="a,b,c",
        help="Serve only these tools, comma-separated")
    parser.add_argument(
        "--http", type=str, default="", metavar="HOST:PORT",
        help="Serve over streamable HTTP at HOST:PORT/mcp instead of stdio")
    parser.add_argument(
        "--token", type=str, default=os.getenv(TOKEN_ENV, ""),
        help=(f"Bearer token every --http request must carry (env: "
              f"{TOKEN_ENV}). Prefer the env var; an argument is visible in "
              f"ps. Ignored for stdio, which is a pipe to a child of the "
              f"client and has no other reader"))
    parser.add_argument(
        "--list", action="store_true",
        help="Print what would be served, with scopes, and exit")
    return parser


def describe_served(bus: Any, names: Sequence[str]) -> str:
    """The ``--list`` rendering: what is served, and what it needs.

    The scopes are on it because they are the question an operator actually
    has — "will this server let a client do that under this profile" — and
    the answer is the descriptor's, printed rather than re-derived.
    """
    lines: List[str] = []
    for name in names:
        info = bus.describe_tool(name)
        scopes = ", ".join(info.get("required_scopes") or []) or "(none)"
        arguments = ", ".join(
            (input_schema_for(bus, name).get("properties") or {}).keys())
        network = " [network]" if info.get("requires_network") else ""
        lines.append(f"{name}{network}\n    scopes: {scopes}"
                     + (f"\n    arguments: {arguments}" if arguments else ""))
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)

    # A refusal and not a traceback: `--profile dveloper` is a typo, the
    # sentence `select_profile` raises already lists the four words, and an
    # operator reading a stack trace to find it is the harness answering a
    # question it was asked politely.
    try:
        tools = build_tools(
            args.profile,
            sandbox_request="none" if args.unsandboxed else None,
            audit=args.audit,
            elfenv=args.elfenv,
        )
    except ValueError as exc:
        raise SystemExit(f"--profile: {exc}")
    bus = tools.bus
    names = served_names(bus, (args.only or "").split(","))

    if args.list:
        print(describe_served(bus, names))
        return 0

    # Everything the operator is told goes to stderr, always — on stdio the
    # other stream is the protocol, and a server that greeted its client on
    # stdout would be a server that never completed a handshake.
    profile = bus.capability_engine.current_profile
    print(f"judais-lobi tools over MCP: {len(names)} tool(s), profile "
          f"{profile}, sandbox {bus.sandbox_name}, audit "
          f"{bus.audit_ref or 'DISABLED'}", file=sys.stderr)

    if args.http:
        host, port = parse_host_port(args.http)
        if not args.token:
            print("⚠️  --http with no --token: every reachable client may "
                  "call this plane under the profile above", file=sys.stderr)
        run_http(build_server(bus, names), host, port, args.token)
    else:
        run_stdio(build_server(bus, names))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised as a subprocess
    raise SystemExit(main())
