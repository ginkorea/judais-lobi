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

* **the names below are the interface.**  A caller switches on ``event`` and
  nothing else.  They are stated here, once, so that a harness on the other end
  of a pipe is reading a published vocabulary rather than the field names of
  whichever dataclass happened to be convenient;
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
    "TOOL_RESULT", "GATE_REQUESTED", "ANSWER", "GROUNDING", "MISSION_FINISHED",
    "EVENTS", "NdjsonSink", "open_sink",
]


#: The mission has begun.  ``objective``, ``catalogue`` (the tool names the
#: model was offered, in order), ``gated`` (offered but needing a person),
#: ``max_steps``, ``history`` (how many prior conversation turns were seeded
#: ahead of the objective — a count, so a watcher can tell a continued
#: conversation from a cold start without the turns travelling twice).
MISSION_STARTED = "mission_started"

#: A step of the plan/act loop is about to ask the model.  ``index``.
STEP_STARTED = "step_started"

#: The model's reply was not a decision this loop could act on — unparseable,
#: not an object, no ``tool`` and no ``answer``, or a tool nobody offers.
#: ``index``, ``problem`` (the sentence handed back to the model), ``tool`` when
#: one was named.  A recorded step, never a crash, and never a guess at intent.
REPLY_REJECTED = "reply_rejected"

#: The model named a tool and the loop is about to dispatch it.  ``index``,
#: ``tool``, ``arguments``.  **Emitted before the call**, which is what lets a
#: watcher show what is about to happen rather than only what happened.
TOOL_CALL = "tool_call"

#: The bus answered.  ``index``, ``tool``, ``arguments``, ``ok``, ``exit_code``,
#: ``output`` (stdout, whole — bounding is what the *model* is shown, not what a
#: watcher is), ``error`` (stderr), ``handle`` (the mission store's handle for
#: the full result), ``truncated``.
TOOL_RESULT = "tool_result"

#: The model named a tool this deployment offers **and gates**: the call was not
#: made, and it will not be made unless somebody says so.  ``index``, ``tool``,
#: ``arguments``, ``reason``.  The mission ends here — see
#: :data:`~core.runtime.mission.AWAITING_APPROVAL`.
#:
#: The arguments travel verbatim, because what a person approves has to be the
#: bytes that would run.
GATE_REQUESTED = "gate_requested"

#: The model finished.  ``text``.  One event, after any grounding repair turns,
#: carrying exactly what :attr:`MissionTranscript.answer` will carry.
ANSWER = "answer"

#: What the grounding validator said, when one was configured.  ``ran``,
#: ``grounded``, ``verified``, ``repairs``, ``caveat``, ``unsupported``,
#: ``silent``, ``uncited``, ``checks`` (``[{check, configured, grounded,
#: verdict, considered, minimum, unsupported, detail}]``).  Absent entirely
#: when no grammar was supplied — an absent report and a clean one are
#: different facts.
#:
#: So are ``grounded`` and ``verified``.  The first says nothing unsupported
#: was found; the second says something was found to check at all.  A
#: consumer reading only ``grounded`` cannot tell an answer that cited three
#: things correctly from one that cited nothing — which is what six of the
#: first ten measured missions did.
GROUNDING = "grounding"

#: Terminal.  ``outcome`` — the transcript's own word — and ``steps``.
MISSION_FINISHED = "mission_finished"

#: The closed vocabulary, so a consumer can assert it knows all of them.
EVENTS: tuple[str, ...] = (
    MISSION_STARTED, STEP_STARTED, REPLY_REJECTED, TOOL_CALL, TOOL_RESULT,
    GATE_REQUESTED, ANSWER, GROUNDING, MISSION_FINISHED,
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


#: The type the loop asks for.  Named so that a caller supplying its own
#: observer — a test, a queue, a websocket — sees that NDJSON is one
#: implementation of the contract and not the contract.
Observer = Callable[[Dict[str, Any]], None]
