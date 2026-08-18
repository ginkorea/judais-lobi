# core/server/__init__.py — the run store, over HTTP, for a platform that would rather subscribe

"""An optional HTTP face on :class:`core.durable.RunStore`.

The seam this framework has always had is a subprocess and a pipe: a
platform spawns ``judais --mission … --events fd:3`` and reads NDJSON off
the descriptor.  It is the right seam when the platform owns the process,
and it is the wrong one when it does not — a browser cannot spawn anything,
a second pane cannot read a descriptor the first pane owns, and a run that
finished an hour ago has no process left to read from at all.  All three of
those are already answered on disk: the store is a numbered, append-only log
per run, and :meth:`~core.durable.RunStore.follow` replays from a cursor and
then blocks for what comes next.

So this package is a *client of the store*, and deliberately nothing more.
It has no opinion about missions, it never starts one, and **nothing it
serves is new**: the records are the records the mission wrote, already
scrubbed by :mod:`core.redact` at the emitter, and the AG-UI variant is
:mod:`core.runtime.agui` applied to those same records rather than a second
translation of them.  A platform can therefore point at HTTP without
changing what its reader understands.

**It is an extra.**  ``pip install 'judais-lobi[server]'`` brings starlette
and uvicorn; without them this module still imports — :func:`require_server`
is the same shape of refusal :func:`core.tools.mcp_client.require_mcp` makes,
and ``python -m core.server`` prints the install line and exits non-zero
rather than a traceback about a missing wheel.

**It is read-only, and that is a decision.**  See
:data:`WHY_NO_CONTROL_ENDPOINT`.

The framing, the cap and the heartbeat — everything that is about a socket
rather than about HTTP — are in :mod:`core.server.sse`, with the failure each
one prevents written on it.  What is here is the routing, and the one rule
that only the routing can keep: **every refusal happens before the first
byte.**
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Optional

from core.durable import NoSuchRun, RunStore, open_run_store, POLL_S, RUNS_ENV
from core.runtime import contract
from core.server.sse import (
    HEARTBEAT_S, MAX_STREAMS, RETRY_AFTER_S, SSE_HEADERS, SSE_MEDIA_TYPE,
    Agui, AtCapacity, BadCursor, Records, StreamSlots, listing, page_size,
    parse_cursor, stream,
)

__all__ = [
    "SERVER_REQUIREMENT", "WHY_NO_CONTROL_ENDPOINT", "ServerUnavailable",
    "require_server", "require_uvicorn", "resolve_store", "create_app",
    "reconcile_hook", "DEFAULT_HOST", "DEFAULT_PORT",
]


#: What the extra installs, named in the refusal so an operator reading it
#: does not have to find this file.  Repeated in ``setup.py`` rather than
#: imported from it, because ``tests/test_packaging.py`` reads
#: ``extras_require`` with :func:`ast.literal_eval` and a shared name would
#: not survive that — the same reason the ``anthropic`` floor is written
#: twice there, and the same test keeps the two honest.
SERVER_REQUIREMENT = "starlette>=0.37, uvicorn>=0.30"

#: Where this server listens when nobody says.
#:
#: Loopback, not ``0.0.0.0``.  There is no authentication in this package
#: and a run's transcript is the whole of what an agent did on somebody's
#: machine; a default that published that to the network would be a decision
#: this framework made on a deployment's behalf.  Putting it behind a proxy
#: that terminates TLS and knows who is asking is the deployment's job, and
#: ``--host`` is how it says so.
DEFAULT_HOST = "127.0.0.1"

#: An unremarkable high port, so the default does not collide with the
#: things that are usually already listening.
DEFAULT_PORT = 8787

#: Why there is no ``POST /runs/{id}/control``, written down so the next
#: reader does not have to re-derive it.
#:
#: ``--control`` (see :mod:`core.runtime.control`) is genuinely a channel
#: *into* a running mission, and an HTTP endpoint in front of it is an
#: obvious thing to want.  It is not shippable, for three reasons and the
#: first one alone is enough:
#:
#: * **the run does not record how it was reached.**  ``meta["flags"]`` is
#:   built by ``_run_meta_flags`` from the flags that were given, and the
#:   control spec is not one of them — deliberately, since it may carry a
#:   path on the spawning host.  So this server cannot tell whether a run
#:   even has a channel, let alone where it is;
#: * **the commonest form has no path at all.**  ``fd:N`` is what a platform
#:   uses precisely so that the mission never has a name on disk anybody can
#:   race it for; there is nothing for a second process to open;
#: * **a second writer to the other two forms is unsafe in different ways.**
#:   For a regular file, ``ControlChannel._read_descriptor`` returns the
#:   moment ``os.read`` gives nothing — "the writer is gone" — so a line
#:   appended after the mission started is read by a thread that has already
#:   exited, and the command is silently lost.  For a FIFO a short line is
#:   atomic and would in fact be delivered, but this server has no way to
#:   know which of the three it is looking at, and a control endpoint that
#:   works for one spec and silently drops commands for another is worse
#:   than no endpoint: the failure is invisible at both ends.
#:
#: The honest seam for steering a run stays the one that owns the process
#: that started it.
WHY_NO_CONTROL_ENDPOINT = (
    "This server is read-only. A run does not record its --control spec, the "
    "commonest spec (fd:N) has no path a second process could open, and a "
    "second writer to a regular-file spec is read by a thread that has "
    "already reached end-of-file — the command would be dropped in silence. "
    "Steer a run from whatever started it."
)


class ServerUnavailable(RuntimeError):
    """The ``[server]`` extra is not installed."""


def require_server():
    """Import the ASGI stack or refuse with the install line.

    :func:`core.tools.mcp_client.require_mcp`'s shape, for the same reason:
    an optional stack is soft-imported at the one place that needs it, and
    the refusal names the extra that fixes it rather than reporting a
    ``ModuleNotFoundError`` about a wheel nobody asked for by name.
    """
    try:
        from starlette.applications import Starlette
        from starlette.responses import JSONResponse, StreamingResponse
        from starlette.routing import Route
    except ImportError as exc:                  # pragma: no cover - the extra
        raise ServerUnavailable(
            f"The event-stream server needs an ASGI stack, which is an "
            f"optional extra: pip install 'judais-lobi[server]'  "
            f"(pin: {SERVER_REQUIREMENT}). Underlying error: {exc}"
        ) from exc
    return Starlette, Route, JSONResponse, StreamingResponse


def require_uvicorn():
    """The other half of the extra: the thing that owns the socket.

    Separate from :func:`require_server` because they are wanted at
    different moments — :func:`create_app` needs an ASGI framework and an
    embedder running this app inside its own server needs nothing else,
    while ``python -m core.server`` needs something to listen with.  Same
    sentence, so an operator meets one refusal however they arrive at it.
    """
    try:
        import uvicorn
    except ImportError as exc:                  # pragma: no cover - the extra
        raise ServerUnavailable(
            f"The event-stream server needs an ASGI server to listen with, "
            f"which is an optional extra: pip install 'judais-lobi[server]'  "
            f"(pin: {SERVER_REQUIREMENT}). Underlying error: {exc}"
        ) from exc
    return uvicorn


def resolve_store(spec: Optional[str] = None) -> RunStore:
    """The store to serve, through the resolver the CLI already uses.

    *spec* is a ``--runs`` value and takes the place of the environment for
    this process; ``None`` reads :data:`core.durable.RUNS_ENV`.  One owner of
    "where the runs are": a server that resolved the directory itself would
    be the second place a deployment has to move when it moves them.

    The disable words are honoured and then refused, which is the only
    sensible reading of them here — ``JUDAIS_LOBI_RUNS=none`` says this
    deployment keeps no transcripts, and a server whose entire purpose is to
    serve transcripts must say so at the door rather than answer every
    request with an empty list.
    """
    store = open_run_store(spec)
    if store is None:
        raise ServerUnavailable(
            f"{RUNS_ENV} is set to a disable word, so there are no runs to "
            f"serve. Point it (or --runs) at a directory.")
    return store


def reconcile_hook(store: RunStore, *, stale_s: Optional[float] = None,
                   clock: Callable[[], float] = time.monotonic,
                   ) -> Callable[[], None]:
    """Housekeeping for a stream that has gone quiet, rate-limited.

    A run whose process died leaves a log with no ``mission_finished`` in it,
    and a follower of that log waits forever — the spinner-that-never-stops
    ``EXIT_CONTRACT["finished"]`` exists to prevent.
    :func:`core.runtime.resume.reconcile_orphans` is the one owner of the
    decision and of the write; this only decides *when to ask it*, at most
    once per staleness window per stream, so that sixty followers do not scan
    the store sixty times a minute.

    **Off by default.**  ``reconcile_orphans`` closes any run whose metadata
    has not moved for :data:`~core.runtime.resume.ORPHAN_STALE_S`, and a run
    that is merely slow — one call to a cold local model — looks exactly like
    that from outside.  Writing a terminal record into a live run's log from
    a process that is only *watching* it is the one failure that would be
    caused by this server rather than merely observed by it.  An operator
    whose store accumulates orphans asks for it with ``--reconcile``.
    """
    from core.runtime.resume import ORPHAN_STALE_S, reconcile_orphans

    window = ORPHAN_STALE_S if stale_s is None else float(stale_s)
    state = {"next": clock() + window}

    def hook() -> None:
        if clock() < state["next"]:
            return
        state["next"] = clock() + window
        reconcile_orphans(store)

    return hook


# ── the response that always gives its slot back ─────────────────────────────

_EVENT_STREAM = None


def _event_stream_class():
    """A ``StreamingResponse`` whose slot is released by the transport.

    Built lazily so that importing this package without the extra does not
    touch starlette, and cached so that the class is one class.

    The release is here and not in the body generator's ``finally`` on
    purpose.  When a client disappears mid-stream, starlette's send raises
    and the exception unwinds *this* frame — deterministically, on every
    path — while the generator underneath is merely dropped, and its
    ``finally`` runs whenever the interpreter gets round to collecting it.
    A cap whose accounting depends on garbage collection is a cap that
    drifts down until the process refuses everybody.  Setting the follow's
    ``stop`` event here matters for the same reason: it is what lets the
    store's blocking wait return so the thread behind the generator ends.
    """
    global _EVENT_STREAM
    if _EVENT_STREAM is not None:
        return _EVENT_STREAM
    _, _, _, StreamingResponse = require_server()

    class _EventStream(StreamingResponse):
        def __init__(self, content, *, release, stop, **kwargs):
            super().__init__(content, **kwargs)
            self._release = release
            self._stop = stop

        async def __call__(self, scope, receive, send):
            try:
                await super().__call__(scope, receive, send)
            finally:
                self._stop.set()
                self._release()

    _EVENT_STREAM = _EventStream
    return _EVENT_STREAM


# ── the app ──────────────────────────────────────────────────────────────────

def create_app(store: RunStore, *,
               max_streams: int = MAX_STREAMS,
               heartbeat_s: float = HEARTBEAT_S,
               poll_s: float = POLL_S,
               reconcile: bool = False,
               slots: Optional[StreamSlots] = None):
    """The ASGI application.  Five endpoints, all of them reads.

    ``GET /healthz``                     liveness, and how full the cap is.
    ``GET /runs``                        a bounded page of run metadata,
                                         newest first.
    ``GET /runs/{run_id}``               one run's metadata.
    ``GET /runs/{run_id}/events``        the records, as SSE.
    ``GET /runs/{run_id}/agui``          the same, translated.

    Both stream endpoints take ``?since=<seq>`` and honour ``Last-Event-ID``,
    replay everything after it, then follow until the run's terminal record.

    Every argument that is a rule is injectable rather than read from a
    module global, because a test of the cap that has to open sixty-four
    sockets is a test nobody runs.  The defaults are :mod:`core.server.sse`'s
    and are documented there.

    *slots* is the shared :class:`~core.server.sse.StreamSlots`; supplying
    one is how a caller (or ``/healthz``) sees the same counter the streams
    do.
    """
    Starlette, Route, JSONResponse, _ = require_server()
    slots = slots or StreamSlots(max_streams)
    EventStream = _event_stream_class()

    def _ended_at(run_id: str, last_seq: int) -> int:
        """The ``seq`` of this run's terminal record, or 0 if it has none.

        Read as the *last* envelope only, because that is where
        ``mission_finished`` is: it comes out of a ``finally``, and a
        reconciliation that writes one for a run that died appends it at the
        end too.  One tail read at connect time, so that a follower which
        has already seen the ending is not made to wait for a second one —
        without which a client reconnecting at the end of a finished run
        would sit on an open socket forever, which is precisely the spinner
        ``EXIT_CONTRACT["finished"]`` exists to prevent.
        """
        if last_seq <= 0:
            return 0
        try:
            tail = store.since(run_id, last_seq - 1)
        except (NoSuchRun, ValueError, OSError):
            return 0
        if not tail:
            return 0
        record = tail[-1].get("record") or {}
        if record.get("event") != contract.MISSION_FINISHED:
            return 0
        return int(tail[-1].get("seq") or 0)

    def _meta_or_404(run_id: str):
        """The store's one answer for both "not there" and "not a name we
        would ever mint" — see :class:`core.durable.NoSuchRun`, which refuses
        to let a caller tell a traversal attempt from a typo."""
        try:
            return store.meta(run_id)
        except (NoSuchRun, ValueError, OSError):
            return None

    async def healthz(request):
        return JSONResponse({
            "ok": True,
            "schema_version": contract.SCHEMA_VERSION,
            "streams": slots.active,
            "max_streams": slots.limit,
        })

    async def runs(request):
        limit = page_size(request.query_params.get("limit"))
        try:
            offset = int(request.query_params.get("offset") or 0)
        except ValueError:
            offset = 0
        return JSONResponse(listing(store.list(), limit=limit, offset=offset))

    async def run_meta(request):
        run = _meta_or_404(request.path_params["run_id"])
        if run is None:
            return JSONResponse({"error": "no such run"}, status_code=404)
        return JSONResponse(run.to_json())

    def _events(request, make_renderer):
        """The whole of "no refusal after the first byte", in order.

        Cursor, then run, then slot — the cheapest refusal first and the one
        that takes a resource last, so a bad request never occupies a slot on
        its way to being told it is bad.  Only after all three does anything
        become a response body, and from that moment the status is 200 and
        every remaining failure is a frame; see :func:`core.server.sse.
        stream`.
        """
        run_id = request.path_params["run_id"]
        try:
            cursor = parse_cursor(request.query_params.get("since"),
                                  request.headers.get("last-event-id"))
        except BadCursor as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

        run = _meta_or_404(run_id)
        if run is None:
            return JSONResponse({"error": "no such run"}, status_code=404)

        # A cursor past the end of the log is CLAMPED to the end, and this
        # is the one place the server does not simply pass the store's
        # semantics through. `RunStore.follow` yields what is `seq >
        # cursor`, so a client claiming seq 99 of a run that has written 3
        # records would be handed nothing at all — not now and not for the
        # next 96 records either. That is the blank-pane failure
        # `core.durable`'s module docstring is written about, arriving from
        # the other side: a reader whose cursor is ahead of the log drops
        # everything it is then sent. A client cannot have seen a record
        # that does not exist, so the honest reading of an impossible
        # cursor is "the end", and from the end it follows.
        cursor = min(cursor, int(run.last_seq))

        try:
            release = slots.claim()
        except AtCapacity as exc:
            return JSONResponse(
                {"error": str(exc)}, status_code=503,
                headers={"Retry-After": str(RETRY_AFTER_S)})

        stop = threading.Event()
        ended = _ended_at(run_id, int(run.last_seq))
        if ended and cursor >= ended:
            # The run is over and this client has all of it: an empty body
            # that closes at once, rather than a follow of a log nothing
            # will ever append to again. Not even through `stream`, because
            # the AG-UI renderer's `close` would report a stream that
            # carried nothing as a failure — which is the right answer for a
            # run that stopped and the wrong one for a client that has
            # already been told how this one ended.
            body = iter(())
        else:
            body = stream(
                store.follow(run_id, cursor, stop=stop, poll_s=poll_s),
                make_renderer(run_id),
                heartbeat_s=heartbeat_s,
                on_idle=reconcile_hook(store) if reconcile else None,
            )
        return EventStream(body, release=release, stop=stop,
                           media_type=SSE_MEDIA_TYPE, headers=dict(SSE_HEADERS))

    async def events(request):
        return _events(request, lambda run_id: Records())

    async def agui(request):
        return _events(request, lambda run_id: Agui(run_id=run_id))

    app = Starlette(routes=[
        Route("/healthz", healthz),
        Route("/runs", runs),
        Route("/runs/{run_id}", run_meta),
        Route("/runs/{run_id}/events", events),
        Route("/runs/{run_id}/agui", agui),
    ])
    app.state.slots = slots
    app.state.store = store
    return app
