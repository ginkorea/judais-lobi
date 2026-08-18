# core/server/sse.py — the run store, as server-sent events

"""SSE framing and the three rules a long-lived stream is killed by.

:mod:`core.durable` already holds everything a follower needs: a numbered,
append-only log per run and a :meth:`~core.durable.RunStore.follow` that
replays from a cursor and then blocks for what comes next.  This module is
that iterator turned into ``text/event-stream``, and nothing else.  It knows
about SSE and about the shape of a store envelope; it does not know about
HTTP, about an ASGI framework, or about who is listening.  That is on
purpose: everything the operational rules below are *about* is testable here
with a list and a fake clock, and the framework half in
:mod:`core.server` is then thin enough to read.

**Nothing new goes on the wire.**  A record served here is the record the
mission wrote, re-serialized: the same events, the same fields, already
scrubbed by :mod:`core.redact` at the emitter and never scrubbed — or
widened — again.  ``seq`` is the store's and travels in the SSE ``id:`` line,
which is where a cursor belongs, rather than inside the record where it
would make this module a second author of a document the contract owns.

**The three rules.**  Each is a constant with the failure it prevents
written on it, because each was learned from a stream that broke in
production and none of them is guessable from the happy path:

* :data:`MAX_STREAMS` — the cap that has to sit *below* the connection
  ceiling of whatever is in front of this process;
* :data:`HEARTBEAT_S` — the comment line that has to arrive *inside* the
  idle timeout of whatever is in front of this process;
* and the one that is a shape rather than a number: **no refusal after the
  first byte.**  Every check that can say no — unknown run, cap reached,
  unreadable cursor — happens before the response starts.  Once bytes are
  moving the status code is 200 forever, so a failure mid-follow becomes a
  final :data:`TRANSPORT_ERROR` frame and a clean close, never a 500 that a
  client which has already parsed a 200 cannot see.
"""

from __future__ import annotations

import json
import threading
import time
from typing import (
    Any, Callable, Dict, Iterable, Iterator, List, Mapping, Optional,
)

from core.runtime import agui, contract

__all__ = [
    "SSE_MEDIA_TYPE", "SSE_HEADERS", "HEARTBEAT", "TRANSPORT_ERROR",
    "MAX_STREAMS", "HEARTBEAT_S", "RETRY_AFTER_S", "PAGE_DEFAULT", "PAGE_MAX",
    "BadCursor", "AtCapacity", "StreamSlots",
    "frame", "comment", "parse_cursor", "page_size",
    "Records", "Agui", "stream",
]


# ── the media type ───────────────────────────────────────────────────────────

SSE_MEDIA_TYPE = "text/event-stream"

#: The headers an event stream needs to survive the things between here and
#: a browser.  ``no-cache`` and ``no-transform`` stop a cache from holding
#: the response until it is complete — which for a stream that ends when the
#: mission does means holding it for the whole mission — and
#: ``X-Accel-Buffering: no`` is nginx's own opt-out of the same behaviour,
#: named here because nginx is what a deployment usually has and because a
#: proxy buffering an event stream looks exactly like a harness that has
#: stopped emitting.
SSE_HEADERS: Mapping[str, str] = {
    "Cache-Control": "no-cache, no-transform",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}

#: An SSE *comment*: two bytes of colon and a word, ignored by every client
#: and by the specification, and therefore the only thing that can be sent
#: down a stream without inventing a record type nobody agreed to.
HEARTBEAT = ": heartbeat\n\n"

#: The event name for the one frame this module authors itself.
#:
#: It is deliberately **not** in :data:`core.runtime.contract.EVENTS`, and a
#: test pins that: a consumer switching on the event name can tell a mission
#: record from a transport failure without being told which is which, and
#: this module cannot quietly grow into a second emitter of the vocabulary
#: the contract owns.
TRANSPORT_ERROR = "error"


# ── the operational rules ────────────────────────────────────────────────────

#: How many event streams this process will hold open at once.
#:
#: **Set this below the connection ceiling of everything in front of it** —
#: the reverse proxy's worker connections, uvicorn's ``--limit-concurrency``,
#: the file-descriptor ulimit.  The failure it prevents is the one that has
#: no error message: an event stream is a connection held for the length of a
#: mission, so N followers of long runs occupy N slots for minutes, and the
#: request that exhausts the ceiling is refused *by the proxy*, at which
#: point every client sees a generic 502 and this process's logs say nothing
#: at all.  Refused here instead, the (N+1)th follower gets a 503 with a
#: :data:`RETRY_AFTER_S`, before a single byte of body — see :data:`
#: TRANSPORT_ERROR` for why "before" is the load-bearing word.
#:
#: 64 is a starting number and not a discovery.  It is the one to raise
#: *after* raising the ceiling it is supposed to sit under, never before.
MAX_STREAMS = 64

#: How long a silent stream may stay silent before a comment line is sent.
#:
#: **Inside the socket write timeout of everything in front of it** — nginx's
#: ``proxy_read_timeout`` defaults to 60 s, and a load balancer's idle
#: timeout is commonly 60 s too.  The failure it prevents: a mission that is
#: *thinking* — one model call on a cold local backend, one long tool — emits
#: nothing for minutes, the proxy sees an idle socket, and cuts it.  The
#: client then sees a stream that stopped, which
#: ``EXIT_CONTRACT["finished"]`` says is indistinguishable from an agent
#: still working, and reconnects, and is cut again.
#:
#: 15 s is a quarter of the commonest 60 s timeout, so three heartbeats have
#: to be lost before anything gives up.
HEARTBEAT_S = 15.0

#: The ``Retry-After`` on a refusal at :data:`MAX_STREAMS`, in seconds.
#:
#: A refusal without one asks every rejected follower to invent its own
#: backoff, and the answer they invent together is a retry storm against the
#: process that just said it was full.
RETRY_AFTER_S = 5

#: How many runs ``GET /runs`` answers with when nobody says.
PAGE_DEFAULT = 50

#: The most it will answer with however loudly it is asked.
#:
#: A store is a directory that grows for as long as a deployment runs, and
#: an unbounded listing is a request that reads every ``meta.json`` on the
#: disk and builds one JSON document out of it — cheap on the day it is
#: written and a timeout a year later.  Clamped rather than refused: a
#: ``limit=100000`` is somebody asking for everything, and everything is
#: this many.
PAGE_MAX = 500


class BadCursor(ValueError):
    """A ``since`` (or a ``Last-Event-ID``) that is not a sequence number.

    Raised where it can still become a 400 — see the module docstring: the
    cursor is parsed before the response starts, because a stream that has
    begun cannot take it back.
    """


class AtCapacity(RuntimeError):
    """:data:`MAX_STREAMS` streams are already open."""


# ── framing ──────────────────────────────────────────────────────────────────

def _payload(data: Any) -> str:
    """One JSON line, serialized exactly as :meth:`RunStore.append` writes it.

    The same three arguments, so that what a follower is handed round-trips
    to what is on the disk rather than to something near it: ``ensure_ascii``
    off keeps the store's UTF-8, ``allow_nan`` off keeps a ``NaN`` — which is
    not JSON and which no client parses — from reaching a socket, and
    ``default=str`` is the store's own answer to a value JSON cannot hold.

    JSON never emits a literal newline inside a string, so one record is
    always one ``data:`` line and this function is why that is true rather
    than a hope.
    """
    return json.dumps(data, ensure_ascii=False, allow_nan=False, default=str)


def frame(event: str, data: Any, *, ident: Optional[int] = None) -> str:
    """One SSE frame: an event name, an optional id, one line of JSON.

    *ident* is the store's ``seq`` and it is what a client sends back as
    ``Last-Event-ID`` after a reconnect, so it is written **only** on a frame
    after which resuming is correct.  For a raw record that is every frame;
    for the AG-UI translation, where one record becomes several frames, it is
    the last of them — see :class:`Agui`.
    """
    head = f"event: {event}\n"
    if ident is not None:
        head += f"id: {int(ident)}\n"
    return f"{head}data: {_payload(data)}\n\n"


def comment(text: str) -> str:
    """An SSE comment line.  Ignored by clients, seen by proxies."""
    return f": {text}\n\n"


def parse_cursor(since: Optional[str], last_event_id: Optional[str] = None
                 ) -> int:
    """The sequence number to replay from, or :class:`BadCursor`.

    ``since`` wins over ``Last-Event-ID`` because one is what the caller
    asked for on this request and the other is what its previous connection
    happened to reach; a client that has both is reconnecting *and* has an
    opinion, and the opinion is newer.

    Both are read the same way and refused the same way.  A cursor that is
    not a whole number is not defaulted to zero: replaying a whole mission to
    a client that asked to resume near the end is the failure that looks like
    the harness repeating itself.
    """
    for raw in (since, last_event_id):
        if raw is None or str(raw).strip() == "":
            continue
        text = str(raw).strip()
        try:
            value = int(text)
        except ValueError:
            raise BadCursor(
                f"since must be a sequence number, got {text!r}") from None
        if value < 0:
            raise BadCursor(f"since must not be negative, got {value}")
        return value
    return 0


def page_size(limit: Optional[str]) -> int:
    """A listing's page size: the default, or the caller's, clamped.

    Clamped and not refused — see :data:`PAGE_MAX`.  Unreadable is the
    default rather than a 400, because a listing is the one request whose
    caller is often a person with a browser.
    """
    if limit is None or str(limit).strip() == "":
        return PAGE_DEFAULT
    try:
        asked = int(str(limit).strip())
    except ValueError:
        return PAGE_DEFAULT
    return max(1, min(PAGE_MAX, asked))


# ── the cap ──────────────────────────────────────────────────────────────────

class StreamSlots:
    """A counted set of open streams, and the refusal when it is full.

    A counter and a lock rather than a semaphore, for two reasons that are
    the same reason: :meth:`healthz` has to be able to *say* how many are
    open, and a follower is refused rather than queued.  A semaphore's
    ``acquire(blocking=False)`` gives the second and not the first, and a
    waiting queue in front of an event stream is a client holding a socket
    open to be told later that it cannot have one.

    :meth:`release` is idempotent per claim: the transport releases a slot
    from the one place that always runs (see :class:`core.server.
    _EventStream`), and a generator finalizer may get there too.  Counting
    one disconnect twice would leak capacity downwards until the process
    refused everybody.
    """

    def __init__(self, limit: int = MAX_STREAMS) -> None:
        self.limit = max(1, int(limit))
        self._lock = threading.Lock()
        self._open = 0

    @property
    def active(self) -> int:
        with self._lock:
            return self._open

    def claim(self) -> Callable[[], None]:
        """Take a slot and return the one function that gives it back.

        Raises :class:`AtCapacity` when there is none — **before** the caller
        has written anything, which is the whole point of claiming here
        rather than inside the body generator.
        """
        with self._lock:
            if self._open >= self.limit:
                raise AtCapacity(
                    f"{self._open} of {self.limit} event streams are already "
                    f"open")
            self._open += 1
        done = threading.Event()

        def release() -> None:
            if done.is_set():
                return
            done.set()
            with self._lock:
                self._open = max(0, self._open - 1)

        return release


# ── the two renderings ───────────────────────────────────────────────────────

class Records:
    """The store's records, one SSE frame each, named by their own event.

    The default rendering, and the one with nothing in it: a consumer of
    ``--events`` NDJSON and a consumer of this endpoint switch on the same
    ten names and read the same fields.  That is the property worth having —
    a platform that already reads the subprocess stream can point at HTTP
    without touching its reader.
    """

    def __init__(self) -> None:
        #: Set when the terminal record has been rendered.  The stream ends
        #: on it: ``mission_finished`` comes out of a ``finally`` and is the
        #: contract's own end-of-stream, so a follower that kept waiting
        #: after it would be holding a slot for a run that is over.
        self.finished = False
        #: The highest ``seq`` rendered — what a client's next
        #: ``Last-Event-ID`` will be.
        self.cursor = 0

    def feed(self, envelope: Mapping[str, Any]) -> Iterator[str]:
        record = dict(envelope.get("record") or {})
        seq = int(envelope.get("seq") or 0)
        self.cursor = max(self.cursor, seq)
        event = str(record.get("event") or "")
        if event == contract.MISSION_FINISHED:
            self.finished = True
        yield frame(event, record, ident=seq)

    def close(self) -> Iterator[str]:
        """Nothing.  The records are the whole rendering."""
        return iter(())


class Agui:
    """The same records, through :class:`core.runtime.agui.Translator`.

    **One translator and not a second.**  This class holds an instance and
    feeds it; every decision about what a record becomes is that module's,
    so the frames a browser gets over HTTP are frame-for-frame the frames it
    gets from :func:`core.runtime.agui.translate` over the same records —
    which is an assertion in ``tests/test_server.py`` and not a claim here.

    The ``id:`` line goes on the **last** frame a record produced, and on no
    other.  One record can become four frames, and a client cut off after
    the second of them must resume at the record before, not in the middle
    of one: ``Last-Event-ID`` means "I have all of this seq", and stamping it
    on the first frame would make it mean "I have some of it".
    """

    def __init__(self, *, thread_id: str = "", run_id: str = "") -> None:
        self._translator = agui.Translator(thread_id=thread_id, run_id=run_id)
        self.finished = False
        self.cursor = 0

    def feed(self, envelope: Mapping[str, Any]) -> Iterator[str]:
        record = dict(envelope.get("record") or {})
        seq = int(envelope.get("seq") or 0)
        self.cursor = max(self.cursor, seq)
        if str(record.get("event") or "") == contract.MISSION_FINISHED:
            self.finished = True
        frames = list(self._translator.feed(record))
        for index, item in enumerate(frames):
            last = index == len(frames) - 1
            yield frame(str(item.get("type") or ""), item,
                        ident=seq if last else None)

    def close(self) -> Iterator[str]:
        """Whatever ends the AG-UI stream — including the failure frame.

        Empty after ``mission_finished``, which closed everything already.
        For a stream that stopped without one it is a ``RUN_ERROR``, because
        that is what :meth:`Translator.close` says a mission that stopped
        without its terminal record is, and a pane spinning forever is the
        state this whole seam exists to prevent.
        """
        for item in self._translator.close():
            yield frame(str(item.get("type") or ""), item)


# ── the loop ─────────────────────────────────────────────────────────────────

def stream(envelopes: Iterable[Optional[Mapping[str, Any]]],
           renderer: Any, *,
           heartbeat_s: float = HEARTBEAT_S,
           clock: Callable[[], float] = time.monotonic,
           on_idle: Optional[Callable[[], None]] = None) -> Iterator[str]:
    """Store envelopes in, ``text/event-stream`` out.  Never raises.

    *envelopes* is :meth:`core.durable.RunStore.follow` — a replay from the
    cursor, then a block for what comes next, yielding ``None`` every time
    the wait times out.  Those ``None``\\ s are the whole reason a heartbeat
    is possible without a second thread and a clock of its own.

    Three things happen here and each is one of the rules:

    * a ``None`` older than *heartbeat_s* since the last byte becomes a
      :data:`HEARTBEAT` — measured from the last byte and not from the last
      heartbeat, so a run that is talking never sends one;
    * the terminal record ends the loop, so a finished run's follower gets
      its close rather than a slot held forever;
    * **anything that goes wrong becomes a frame.**  A store read that fails
      mid-follow — the directory removed underneath us, a disk that has gone
      away — is caught here and rendered as a :data:`TRANSPORT_ERROR` frame
      followed by the end of the stream.  It cannot become a status code
      because the status code was 200 several minutes ago.  This function
      therefore does not raise, and the one thing it must never do is let an
      exception out into a transport that would answer it with a 500 a
      client has already stopped being able to see.

    *on_idle* is called on each timed-out wait, before the heartbeat is
    considered.  It is how a follower notices a run that ended without
    saying so — see :func:`core.server.reconcile_hook`.  Its failures are
    swallowed for the reason above: a housekeeping call must not end
    somebody's stream.
    """
    last_byte = clock()
    try:
        for envelope in envelopes:
            if envelope is None:
                if on_idle is not None:
                    try:
                        on_idle()
                    except Exception:           # noqa: BLE001 - housekeeping
                        pass
                if clock() - last_byte >= heartbeat_s:
                    last_byte = clock()
                    yield HEARTBEAT
                continue
            for chunk in renderer.feed(envelope):
                last_byte = clock()
                yield chunk
            if renderer.finished:
                break
        for chunk in renderer.close():
            yield chunk
    except GeneratorExit:                       # the client went away
        raise
    except Exception as exc:                    # noqa: BLE001 - see docstring
        yield frame(TRANSPORT_ERROR,
                    {"error": type(exc).__name__, "detail": str(exc)})


def run_summary(run: Any) -> Dict[str, Any]:
    """One run's metadata as a listing entry.

    :meth:`core.durable.Run.to_json` and nothing added: the store owns what a
    run record is, and a summary that composed its own would drift from it
    the first time a field was added there.
    """
    return dict(run.to_json())


def listing(runs: List[Any], *, limit: int, offset: int = 0) -> Dict[str, Any]:
    """A bounded page of :func:`run_summary`, newest first.

    Newest first is :meth:`core.durable.RunStore.list`'s order and is not
    re-sorted here; ``total`` is what the store holds, so a caller can tell a
    full page from the end of the list without asking twice.
    """
    offset = max(0, offset)
    page = runs[offset:offset + limit]
    return {"runs": [run_summary(run) for run in page],
            "total": len(runs), "limit": limit, "offset": offset}
