# core/runtime/mission_stream.py — what a mission tells a harness while it runs

"""A newline-delimited JSON account of a mission, as it happens.

``MissionRunner.run`` returns a :class:`~core.runtime.mission.MissionTranscript`
when the whole mission is over.  That is the right shape for a terminal, which
prints the steps afterwards anyway, and the wrong shape for anything that has
to *show* a mission to somebody while it is running: a mission on a 59 tok/s
local model is minutes long, and a caller holding only ``run()`` has nothing to
render for all of them.

So the loop takes an **observer** — one callable, one dict per thing that
happened — and this module is the observer that writes those dicts as NDJSON to
a stream.  It is deliberately the whole of the streaming contract:

* **the names are the interface**, and they are declared in
  :mod:`core.runtime.contract` and re-exported here.  A caller switches on
  ``event`` and nothing else.  They live one module over because a stream is
  one way to carry these records and not what they are — an observer that is a
  queue or a websocket speaks the same vocabulary without going near NDJSON —
  and because a consumer pinning a release of this repo needs the whole seam,
  names and required fields and outcome words together, in one importable
  place;
* **these are this harness's own facts, not somebody's rendering of them.**
  ``tool_call`` says the model named a tool and ``tool_result`` says what came
  back through :meth:`ToolBus.dispatch`.  What a *consumer* decides about that —
  whether the result may be quoted, cited, or shown beside a number — is the
  consumer's judgement to make from ``tool``, and this module deliberately
  supplies no field that invites it to be made from the prose instead;
* **one line, one event, flushed.**  A reader that is a pipe away gets each
  event as it happens; a reader that arrives late reads a file.  A line that
  cannot be serialized is dropped with a marker rather than raising into the
  loop — a mission must not fail because somebody was watching it.

Nothing here is required.  With no observer the loop runs exactly as it ran
before this module existed, and ``judais --mission`` without ``--events`` writes
no NDJSON at all.
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable, Dict, IO, Optional

__all__ = [
    "MISSION_STARTED", "STEP_STARTED", "REPLY_REJECTED", "TOOL_CALL",
    "TOOL_RESULT", "GATE_REQUESTED", "ANSWER_DELTA", "ANSWER", "GROUNDING",
    "MISSION_FINISHED", "MODEL_STATE",
    "EVENTS", "NdjsonSink", "open_sink", "close_on_sigterm",
    "exit_as_signalled", "SIGTERM_CAUSE",
]

# The vocabulary is `core.runtime.contract`'s to own — see its module docstring
# for the compatibility rule and for what each record is required to carry.
# Re-exported under the names they have always had here so that every existing
# importer, in this repo and in whatever pinned a release of it, is untouched.
from core.runtime.contract import (           # noqa: E402  (re-export)
    ANSWER, ANSWER_DELTA, EVENTS, GATE_REQUESTED, GROUNDING, MISSION_FINISHED,
    MISSION_STARTED, MODEL_STATE, REPLY_REJECTED, STEP_STARTED, TOOL_CALL,
    TOOL_RESULT,
)


class NdjsonSink:
    """Write one JSON object per line, flushed, and never raise into the loop.

    ``ensure_ascii=False``: a tool result from a Chinese corpus goes out as
    itself, so a consumer scanning the bytes for a leak is scanning the text
    rather than a pile of escapes.

    ``allow_nan=False``: ``NaN`` and ``Infinity`` are not JSON.  A strict
    reader on the far end would fail on the whole line, and a lenient one
    would render ``NaN`` as a fact.  Neither is what a non-finite number
    deserves, so it becomes a loud marker here instead.
    """

    def __init__(self, stream: IO[str], close: bool = False):
        self._stream = stream
        self._close = close

    def __call__(self, record: Dict[str, Any]) -> None:
        try:
            line = json.dumps(record, ensure_ascii=False, allow_nan=False,
                              default=str)
        except (TypeError, ValueError):
            line = json.dumps({"event": record.get("event", "?"),
                               "unserializable": True})
        try:
            self._stream.write(line + "\n")
            self._stream.flush()
        except (OSError, ValueError):
            # The watcher went away.  That is a fact about the watcher and
            # must never become a fact about the mission.
            pass

    def flush(self) -> None:
        """Push whatever is buffered, and never raise.

        Every line is flushed as it is written, so this is a no-op on the
        ordinary path.  It exists for the path that is not ordinary: a signal
        handler has microseconds and no business assuming which stream it got.
        """
        try:
            self._stream.flush()
        except (OSError, ValueError):
            pass

    def close(self) -> None:
        if self._close:
            try:
                self._stream.close()
            except OSError:
                pass


def open_sink(spec: str) -> Optional[NdjsonSink]:
    """Resolve ``--events`` into a sink, or ``None`` when nothing was asked for.

    Three forms, and the middle one is the one a harness uses:

    ``-``        stdout.  For a person with ``jq``.
    ``fd:N``     an inherited file descriptor.  A parent process that passed a
                 pipe gets each event the moment it happens, with no file to
                 tail and nothing interleaved with the console rendering — the
                 console writes to stdout and this does not.
    *path*       a file, opened for append.  Survives the run, and a reader
                 that arrives late still gets the whole thing.
    """
    spec = (spec or "").strip()
    if not spec:
        return None
    if spec == "-":
        import sys
        return NdjsonSink(sys.stdout)
    if spec.startswith("fd:"):
        number = spec[3:]
        if not number.isdigit():
            raise ValueError(f"--events {spec!r}: fd: needs a number")
        return NdjsonSink(os.fdopen(int(number), "w", encoding="utf-8"),
                          close=True)
    handle = open(spec, "a", encoding="utf-8")
    return NdjsonSink(handle, close=True)


#: The word :func:`close_on_sigterm` records on a cancellation it threw, so
#: the process that owns the switch can tell "a signal asked us to stop" from
#: "a library caller did".  It does **not** travel on the stream — a cancelled
#: run says ``reason: "cancelled"`` there and nothing about how.
SIGTERM_CAUSE = "sigterm"


def close_on_sigterm(sink: Optional[NdjsonSink], cancel: Any = None) -> None:
    """Wind up cleanly when this process is asked to stop.

    A consumer that stops a turn sends ``SIGTERM`` and expects the events
    already written to be on the transcript — TAIPAN's ``MissionAgent.stop``
    says so in as many words, and picks ``SIGTERM`` over ``SIGKILL`` precisely
    "so the harness gets to close its stream".  Nothing made that true.  The
    default disposition kills the process outright: no ``finally`` runs, the
    ``fd:`` sink is never closed, and a reader on the far end of the pipe is
    left waiting on a descriptor nobody is going to shut.

    **Without a cancellation** this flushes, closes, restores the default
    disposition and re-raises the signal at itself.  The last part matters —
    swallowing it would turn a killed mission into a clean exit, and a consumer
    reading the exit status would be told the turn finished.  It did not; it
    was stopped, and the status says so.

    **With one**, the first signal is *cooperative*: the switch is thrown and
    the handler returns, so the mission notices at its next check, ends its
    transcript, and writes its own ``mission_finished`` — and only then does
    the caller's ``finally`` close the sink.  Closing on the signal itself
    saved the events already written and lost the one record that says the run
    is over, which is the record a pane needs to stop spinning.  Ordering,
    then: cancel → the loop ends → the mission finishes → the sink closes.
    The caller re-raises the signal afterwards (see
    :func:`exit_as_signalled`), so the exit status is still the signal's.

    A **second** ``SIGTERM`` is not cooperative.  Somebody asked twice, which
    means the first ask is not being honoured fast enough — a model call in
    flight, a tool mid-subprocess — and the honest answer is the old
    behaviour: flush what there is, close, and die of the signal.

    Best effort by construction.  A platform without ``SIGTERM``, or a call
    from a thread that is not the main one, is a no-op rather than a mission
    that failed to start because somebody was watching it.
    """
    if sink is None:
        return
    import signal

    term = getattr(signal, "SIGTERM", None)
    if term is None:                            # pragma: no cover - not POSIX
        return

    def _wind_up(signum, frame):                # pragma: no cover - signalled
        if cancel is not None and not cancel.is_set():
            cancel.cancel(SIGTERM_CAUSE)
            return
        sink.flush()
        sink.close()
        signal.signal(signum, signal.SIG_DFL)
        os.kill(os.getpid(), signum)

    try:
        signal.signal(term, _wind_up)
    except (ValueError, OSError):
        # Not the main thread, or a platform that will not have it. The
        # mission is what matters and it runs either way.
        pass


def exit_as_signalled(cancel: Any) -> None:
    """Die of the ``SIGTERM`` we were cooperatively asked to die of.

    Called after the sink is closed, by the caller that passed *cancel* to
    :func:`close_on_sigterm`.  A run that wound up because somebody signalled
    it has now done everything a clean exit would do — the transcript is
    written, ``mission_finished`` is on the stream, the descriptor is shut —
    and the one thing left is the exit status, which must still be the
    signal's.  A turn that was stopped and reports success is a turn a
    consumer will believe finished.

    A no-op for every other kind of cancellation: a library caller that threw
    the switch wants its process back, not a corpse.
    """
    if cancel is None or getattr(cancel, "cause", "") != SIGTERM_CAUSE:
        return
    import signal

    term = getattr(signal, "SIGTERM", None)
    if term is None:                            # pragma: no cover - not POSIX
        return
    signal.signal(term, signal.SIG_DFL)
    os.kill(os.getpid(), term)


#: The type the loop asks for.  Named so that a caller supplying its own
#: observer — a test, a queue, a websocket — sees that NDJSON is one
#: implementation of the contract and not the contract.
Observer = Callable[[Dict[str, Any]], None]
