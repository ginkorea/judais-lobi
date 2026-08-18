# core/runtime/control.py — the channel a platform steers a running mission by

"""Newline-delimited JSON commands, going the other way.

:mod:`core.runtime.mission_stream` is what a mission *says*.  This is what
a mission can be *told*, and until it existed the only lever a platform had
on a running turn was ``SIGTERM``: the reference deployment's pane offers
``POST /interrupt`` and the whole of what that could do was kill the
harness.  Three things an operator wants mid-turn are not "stop":

* **say something to the agent** — "look at the second corpus, not the
  first" — without ending the turn and starting a new one that has to
  re-establish everything;
* **abandon the current step** and let the model try again from what it
  already has, which is a much smaller ask than abandoning the run;
* **answer a gate** while the run is still standing at it, instead of
  letting the mission end at ``awaiting_approval`` and resuming it later
  with ``--approval``.

So the channel is an *input* stream, opened the same three ways ``--events``
is opened for output, read by one daemon thread, and drained by the loop at
points the loop chooses.  Everything about it is deliberately narrow:

* **the vocabulary is closed** (:data:`COMMANDS`) and validated here, once,
  so the loop never sees a command it has to guess at.  A line that is not
  JSON, an object that is not a command, a word nobody declares, an
  ``inject`` with no text, a decision signed by nobody — each is dropped
  with **one** sentence on stderr and the run carries on.  A control channel
  that could crash a mission would be a worse lever than no lever;
* **nothing here decides anything.**  ``gate_decision`` is *recorded*
  through the same :class:`~core.runtime.approvals.ApprovalStore` the
  ``--approval`` path uses, naming the platform's own decider — this module
  carries somebody's decision, it does not make one, and there is no code
  path in it that reads a state and concludes a yes;
* **``cancel`` is applied in the reader thread**, exactly as a ``SIGTERM``
  handler applies one, because a stop must not wait for the loop to reach a
  drain point.  Everything else is queued, because everything else is only
  meaningful at a place the loop is willing to be interrupted;
* **a closed channel is not an error.**  The writer going away is a fact
  about the writer.  The mission finishes the way it would have finished
  with no channel at all.

**One reader, one queue, and two ways to wait on it.**  The loop that
drains this channel is a coroutine now (:meth:`core.runtime.run.Run.arun`),
and an async loop that sat in :func:`time.sleep` waiting for a person to
answer a gate would be an async loop with nothing async about it — so
:meth:`ControlChannel.await_for` is :meth:`ControlChannel.wait_for` with
its sleep awaited, sharing every decision either of them makes.  What did
**not** move is the reader: it is still one daemon thread feeding one
:class:`queue.Queue`, because the two properties this channel is built on
are properties of that thread.  ``cancel`` is applied *in* it, so a stop
does not wait for a loop to reach a drain point — an asyncio reader would
apply it on the loop, which is the thread a model call is blocking; and
``-`` is ``sys.stdin``, a text handle with no descriptor an event loop can
be told to watch.  ``poll`` is already a non-blocking drain of that queue
and is what both loops call, unchanged.

Nothing here is required.  With no ``--control`` the loop runs exactly as it
ran before this module existed.
"""

from __future__ import annotations

import asyncio
import json
import os
import queue
import select
import stat
import sys
import threading
import time
from typing import Any, Callable, Dict, IO, List, Optional, Sequence, Tuple

from core.budgets import cancelled

__all__ = [
    "COMMANDS", "INJECT", "CANCEL", "CANCEL_STEP", "GATE_DECISION",
    "GATE_WAIT_S", "CONTROL_CAUSE", "parse_command", "ControlChannel",
]


#: A user instruction, delivered between steps.  ``{"control": "inject",
#: "text": "…"}`` — the loop appends it as a ``user`` turn immediately
#: before the next model call, and the ``step_started`` that follows carries
#: it as ``injected``.
INJECT = "inject"

#: Stop the run.  ``{"control": "cancel"}`` — identical in effect to the
#: first ``SIGTERM``: the mission's :class:`~core.budgets.Cancellation` is
#: thrown, the loop winds up at its next check, and the run ends
#: ``incomplete`` with ``reason: "cancelled"``.
CANCEL = "cancel"

#: Abandon what is left of the current step.  ``{"control":
#: "cancel_step"}`` — cooperative and bounded to *this* step: the calls the
#: model asked for and that have not been dispatched yet are skipped, the
#: model is told so, and it is asked again.  It never touches a tool
#: subprocess that is already running; see :data:`WHY_NOT_MID_FLIGHT`.
CANCEL_STEP = "cancel_step"

#: Somebody answered a gate.  ``{"control": "gate_decision",
#: "approval_id": "ap_…", "approve": true|false, "decided_by": "who",
#: "note": ""}`` — recorded through the approval store and, when it is a
#: yes, spent on the call it was about, in the same turn.
GATE_DECISION = "gate_decision"

#: The whole vocabulary.  Closed, so a word nobody declares is refused by
#: name here rather than discovered later as a command that did nothing.
COMMANDS: Tuple[str, ...] = (INJECT, CANCEL, CANCEL_STEP, GATE_DECISION)

#: How long a gated call waits for a decision on the channel before the
#: mission ends at ``awaiting_approval`` the way it always has.
#:
#: A ceiling and not a policy: the real bound is ``min(this, whatever is
#: left of the run's deadline)``, and either way **nothing times out into a
#: yes** — the durable record stays ``pending`` and ``--approval`` on a
#: later turn still works, which is the behaviour a run without a channel
#: has.  Five minutes because the thing on the other end is a person being
#: paged, and because a number an operator can override per run
#: (``MissionRunner(gate_wait_s=…)``) does not need to be a flag as well.
GATE_WAIT_S = 300.0

#: What a run cancelled through this channel records as its *cause*.
#:
#: Not on the wire — a cancelled run says ``reason: "cancelled"`` there and
#: nothing about how.  It matters to the process that owns the switch, for
#: the reason :data:`~core.runtime.mission_stream.SIGTERM_CAUSE` does and
#: with the opposite conclusion: a run stopped by a signal must exit *of*
#: that signal, and a run stopped by a command from its own platform must
#: not — the platform asked the mission to wind up, not the process to die
#: of something.
CONTROL_CAUSE = "control"

#: Why ``cancel_step`` is cooperative and stops at call boundaries.
#:
#: Killing a tool subprocess mid-flight is deliberately **out of scope**.
#: The bus owns dispatch, the sandbox owns the child, and a mission that
#: reached into either to kill a process would be a second owner of the
#: thing :meth:`~core.tools.bus.ToolBus.dispatch` exists to be.  What a
#: half-run tool did to the world is also not knowable from here: an
#: interrupted write is a state nobody recorded.  The honest lever is a
#: wall clock on the call (``deadline_s``, where the bus takes one) and a
#: cancellation that stops what has *not* started.
WHY_NOT_MID_FLIGHT = (
    "cancel_step skips calls that have not been dispatched. A tool already "
    "running is left alone: the bus owns dispatch and what a half-killed "
    "subprocess did to the world is not knowable from here."
)

#: How often :meth:`ControlChannel.wait_for` looks up from the queue.  Small
#: enough that a decision feels immediate to a person and a cancellation is
#: noticed while a gate is waiting; large enough that five minutes of
#: waiting is not five minutes of spinning.
_TICK = 0.02

#: How much of a rejected line goes into the sentence about it.  Enough to
#: recognise which line it was, bounded because it is somebody else's bytes.
_ECHO = 120


def _warn(message: str) -> None:
    """One sentence on stderr, and never raise into the run.

    stderr is where this harness already puts prose for a person — see
    ``EXIT_CONTRACT["diagnostic"]`` — and a dropped command is exactly that:
    something the operator on the other end typed wrong and will not
    otherwise find out about, because the mission cannot answer them.
    """
    try:
        sys.stderr.write(message.rstrip("\n") + "\n")
        sys.stderr.flush()
    except (OSError, ValueError):               # pragma: no cover - defensive
        pass


def _echo(text: str) -> str:
    text = text.replace("\n", " ")
    return text if len(text) <= _ECHO else text[:_ECHO] + "…"


def parse_command(payload: Any) -> Tuple[Optional[Dict[str, Any]], str, str]:
    """``(command, complaint, once)`` — exactly one of the first two is set.

    *command* is the normalized form: the word, plus exactly the fields that
    word declares and nothing else.  A caller may put anything it likes on
    the line — ``at`` timestamps are the obvious one — and it is **ignored
    rather than carried**, because a field this harness passes through
    without understanding is a field somebody will one day expect it to act
    on.

    *once* is a de-duplication key, or ``""`` for a complaint worth making
    every time.  A platform with a typo in its command word will send that
    typo on every command it sends, and a hundred identical lines on stderr
    would bury the one line about the malformed JSON.

    Pure, and separate from the channel, so the whole of what this harness
    will accept can be exercised without a thread or a pipe.
    """
    if not isinstance(payload, dict):
        return None, (f"control: dropped a line that is not a JSON object "
                      f"(got {type(payload).__name__})"), ""
    word = payload.get("control")
    if not isinstance(word, str) or not word.strip():
        return None, ("control: dropped a line with no 'control' word: "
                      f"{_echo(json.dumps(payload, default=str))}"), ""
    word = word.strip()
    if word not in COMMANDS:
        return None, (f"control: dropped an unknown command {word!r} — this "
                      f"harness accepts {', '.join(COMMANDS)}"), f"word:{word}"

    if word == INJECT:
        text = payload.get("text")
        if not isinstance(text, str) or not text.strip():
            return None, ("control: dropped an inject with no 'text' — an "
                          "instruction nobody wrote is not one"), ""
        return {"control": INJECT, "text": text}, "", ""

    if word in (CANCEL, CANCEL_STEP):
        return {"control": word}, "", ""

    approval_id = payload.get("approval_id")
    if not isinstance(approval_id, str) or not approval_id.strip():
        return None, ("control: dropped a gate_decision with no "
                      "'approval_id' — a decision has to name the request "
                      "it answers"), ""
    approve = payload.get("approve")
    if not isinstance(approve, bool):
        return None, (f"control: dropped gate_decision {approval_id} — "
                      f"'approve' must be true or false, got "
                      f"{type(approve).__name__}. There is no default: an "
                      f"omission would have to mean yes or no, and both "
                      f"readings are wrong"), ""
    decided_by = payload.get("decided_by")
    if not isinstance(decided_by, str) or not decided_by.strip():
        # The same refusal `ApprovalStore.decide` makes, made one layer
        # earlier so the run keeps waiting for a decision it can record
        # rather than spending the one it cannot.
        return None, (f"control: dropped gate_decision {approval_id} — "
                      f"'decided_by' names nobody. This framework has no "
                      f"principal system and will not invent one, but an "
                      f"approval signed by nobody is not an approval"), ""
    note = payload.get("note")
    return {"control": GATE_DECISION, "approval_id": approval_id.strip(),
            "approve": approve, "decided_by": decided_by.strip(),
            "note": note if isinstance(note, str) else ""}, "", ""


def _open_path(spec: str) -> int:
    """A path or a FIFO, opened for reading without waiting for a writer.

    Returns a **descriptor** rather than a file object, for the reason
    :meth:`ControlChannel.close` gives: a text stream being read by another
    thread cannot be closed from this one without taking a lock that thread
    is holding.

    Two problems a plain ``open(spec)`` has, and a FIFO is the form a
    platform actually uses:

    * opening a FIFO read-only **blocks until somebody opens it for
      writing**, so a mission whose platform connects a moment later would
      not start;
    * opening it read-only *before* any writer and then reading gives an
      immediate end-of-file, so the reader thread would finish before the
      first command was written.

    Opening a FIFO ``O_RDWR`` fixes both: the open does not block, and this
    process is itself a writer, so a read waits for data rather than
    reporting the pipe finished.  It is the standard trick and it is done
    only for a FIFO — a regular file is opened as a regular file, so a
    read-only fixture in somebody's test directory still works, and reaches
    its end-of-file honestly.
    """
    try:
        is_fifo = stat.S_ISFIFO(os.stat(spec).st_mode)
    except OSError:
        is_fifo = False
    if is_fifo:
        return os.open(spec, os.O_RDWR)
    return os.open(spec, os.O_RDONLY)


class ControlChannel:
    """One reader thread, one queue, and a vocabulary the loop can trust.

    Constructed from an open text stream, or — the ordinary way — through
    :meth:`open`, which resolves the same three spec forms ``--events``
    does.  The thread is a **daemon** on purpose: it may be blocked on a
    read of a pipe nobody is ever going to write to again, and a mission
    that had answered its question must not be kept alive by something
    listening for an instruction that is not coming.

    *cancel* is the run's :class:`~core.budgets.Cancellation`, thrown from
    the reader thread the moment a ``cancel`` arrives.  Without one, a
    ``cancel`` command is dropped with a sentence saying so, because a
    channel that silently accepted a stop it could not deliver is worse
    than one that refuses it.

    *warn* is the stderr writer, injected for the reason every other seam
    in this repo is: a test that proves a malformed line is reported must
    not have to read the process's stderr to find out.
    """

    def __init__(self, handle: Optional[IO[str]] = None, *,
                 fd: Optional[int] = None, cancel: Any = None,
                 spec: str = "", close: bool = True,
                 warn: Optional[Callable[[str], None]] = None):
        if (handle is None) == (fd is None):
            raise ValueError("a control channel reads a handle or a "
                             "descriptor, and exactly one of them")
        self._handle = handle
        self._fd = fd
        self._cancel = cancel
        self.spec = spec
        self._close_handle = close
        self._warn = warn or _warn
        # Set by `close`, read by the descriptor reader between its polls.
        # A thread asked to stop is how this channel lets go of a FIFO that
        # nobody is ever going to write to again — see `close`.
        self._shutting = threading.Event()
        self._queue: "queue.Queue[Dict[str, Any]]" = queue.Queue()
        # Commands drained off the queue and not yet wanted by the caller
        # that drained them: `wait_for` looks for one kind and must not
        # swallow the others, and a mid-step drain looking for
        # `cancel_step` must not eat the injection meant for the next step.
        # Order is preserved, which is the whole reason it is a list.
        self._held: List[Dict[str, Any]] = []
        self._said: set = set()
        self._closed = False
        self._reader = threading.Thread(
            target=self._read, name="mission-control", daemon=True)
        self._reader.start()

    # ── opening ─────────────────────────────────────────────────────────

    @classmethod
    def open(cls, spec: str, *, cancel: Any = None,
             warn: Optional[Callable[[str], None]] = None,
             ) -> Optional["ControlChannel"]:
        """Resolve ``--control`` into a channel, or ``None`` for no channel.

        The three forms of ``--events``, mirrored, because an operator who
        has learned one of this harness's stream specs has learned the
        other:

        ``-``        stdin.  For a person typing JSON at a running mission.
        ``fd:N``     an inherited descriptor.  What a platform uses: the
                     parent keeps the write end and the mission never has a
                     path on disk to race anybody for.
        *path*       a file or — the useful case — a **FIFO**.  Survives a
                     restart of whatever is writing to it.

        Refused at the door, like ``--events``: a spec that cannot be opened
        is a ``ValueError``/``OSError`` here rather than a channel that
        silently delivers nothing.
        """
        spec = (spec or "").strip()
        if not spec:
            return None
        if spec == "-":
            return cls(sys.stdin, cancel=cancel, spec=spec, close=False,
                       warn=warn)
        if spec.startswith("fd:"):
            number = spec[3:]
            if not number.isdigit():
                raise ValueError(f"--control {spec!r}: fd: needs a number")
            return cls(fd=int(number), cancel=cancel, spec=spec, close=True,
                       warn=warn)
        return cls(fd=_open_path(spec), cancel=cancel, spec=spec, close=True,
                   warn=warn)

    # ── the thread ──────────────────────────────────────────────────────

    def _read(self) -> None:
        """Every line, until the writer goes away or we are shut.  Never raises."""
        try:
            if self._fd is not None:
                self._read_descriptor(self._fd)
            else:
                self._read_handle(self._handle)
        except (OSError, ValueError):           # pragma: no cover - defensive
            # Closed underneath us. A fact about the writer, never about
            # the mission.
            pass

    def _read_descriptor(self, fd: int) -> None:
        """Poll, then read.  **Interruptible**, and that is the whole point.

        A blocking ``readline`` would be simpler and it is what this did
        first.  It is unusable: the ordinary case is a FIFO with no data on
        it, so the reader sits inside a read of a text stream holding that
        stream's lock — and :meth:`close`, called from the mission's
        ``finally`` on the main thread, blocks forever trying to take the
        same lock.  A mission that finished its work and then hung shutting
        down is a worse failure than any this channel exists to fix.

        So the loop looks up every :data:`_TICK`, which also means ``close``
        can ask it to stop and be obeyed within one tick, and lines are
        assembled here rather than by a buffered reader — a reader that
        reads ahead would hold a command a platform sent and is waiting for
        the mission to act on.

        Bytes and ``errors="replace"``: a line that is not UTF-8 is a bad
        line, and a bad line is dropped by the parser with a sentence, not
        by an exception that takes the reader down with it.
        """
        pending = ""
        while not self._shutting.is_set():
            try:
                ready, _w, _x = select.select([fd], [], [], _TICK)
            except (OSError, ValueError):
                return
            if not ready:
                continue
            try:
                chunk = os.read(fd, 65536)
            except (OSError, ValueError):
                return
            if not chunk:
                return                          # the writer is gone
            pending += chunk.decode("utf-8", "replace")
            while "\n" in pending:
                line, pending = pending.split("\n", 1)
                self._offer(line)

    def _read_handle(self, handle: IO[str]) -> None:
        """A stream somebody handed us — stdin, or a test's own.

        Blocking, because there is no descriptor to poll in the general
        case, and safe because nothing closes these: ``-`` is stdin and this
        process does not own it, and a caller passing its own stream owns
        the stream.
        """
        for line in iter(handle.readline, ""):
            if self._shutting.is_set():
                return
            self._offer(line)

    def _offer(self, line: str) -> None:
        text = (line or "").strip()
        if not text:
            return
        try:
            payload = json.loads(text)
        except ValueError as exc:
            self._note("", f"control: dropped a line that is not JSON "
                           f"({exc}): {_echo(text)}")
            return
        command, complaint, once = parse_command(payload)
        if command is None:
            self._note(once, complaint)
            return
        if command["control"] == CANCEL:
            # Applied HERE and not queued. A stop that waited for the loop
            # to reach a drain point would be a stop the operator watches
            # not happening while a model call is in flight — which is
            # exactly the state SIGTERM's handler exists to avoid, and this
            # is the same lever arriving by a different road.
            self._throw()
            return
        self._queue.put(command)

    def _throw(self) -> None:
        switch = self._cancel
        if switch is None:
            self._note("cancel:nothing",
                       "control: 'cancel' arrived and this run has no "
                       "cancellation to throw; it was dropped")
            return
        ask = getattr(switch, "cancel", None)
        if ask is None:
            # A bare `threading.Event`, which every `cancelled()` caller
            # already accepts. It has no room for a cause and does not
            # need one.
            switch.set()
            return
        ask(CONTROL_CAUSE)

    def _note(self, once: str, message: str) -> None:
        if once:
            if once in self._said:
                return
            self._said.add(once)
        self._warn(message)

    def warn(self, message: str) -> None:
        """Say something about a command on the same channel's stderr.

        Public because the loop drops commands too — a decision for a gate
        that has already closed, say — and a second writer to stderr with
        its own idea of the prefix would be a second owner of what a
        dropped command looks like.
        """
        self._warn(message)

    # ── what the loop asks ──────────────────────────────────────────────

    def _drain(self) -> None:
        while True:
            try:
                self._held.append(self._queue.get_nowait())
            except queue.Empty:
                return

    def poll(self, only: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
        """Every command waiting, oldest first, taken off the channel.

        *only* takes just those words and **leaves the rest where they
        were**, in order.  That is not a convenience: the loop drains
        mid-step looking for ``cancel_step``, and an injection swallowed
        there would be an operator's instruction the model was never shown
        — delivered to nobody, with nothing saying so.
        """
        self._drain()
        if only is None:
            taken, self._held = self._held, []
            return taken
        wanted = set(only)
        taken = [c for c in self._held if c.get("control") in wanted]
        self._held = [c for c in self._held if c.get("control") not in wanted]
        return taken

    def wait_for(self, predicate: Callable[[Dict[str, Any]], bool],
                 timeout_s: float) -> Optional[Dict[str, Any]]:
        """The first waiting command *predicate* accepts, or ``None``.

        ``None`` means the wait ran out, the run was cancelled underneath
        it, or the writer went away — three different facts with one
        correct response, which is that the caller does what it would have
        done with no channel at all.  A gate does not time out into a yes;
        it times out into the ``awaiting_approval`` it has always ended at.

        Commands that do not match are **kept**, not dropped: a decision
        for another gate, or an injection sent while a gate was standing,
        is still owed to the step that comes next.

        This is the wait a **synchronous** caller makes; :meth:`await_for`
        is the same wait for one inside an event loop.  The two share
        every decision — see :meth:`_seek` and :meth:`_nap` — and differ
        in one word, which is how the sleep is spent.
        """
        deadline = self._until(timeout_s)
        while True:
            command = self._seek(predicate)
            if command is not None:
                return command
            nap = self._nap(deadline)
            if nap is None:
                return None
            time.sleep(nap)

    async def await_for(self, predicate: Callable[[Dict[str, Any]], bool],
                        timeout_s: float) -> Optional[Dict[str, Any]]:
        """:meth:`wait_for`, awaited, so the loop is free while it waits.

        What :meth:`core.runtime.run.Run.arun` stands at a gate with.  The
        reader is still the one daemon thread — see :meth:`_read`, and see
        the class docstring for why ``cancel`` is applied *there* and not
        here — and this is still that thread's queue being drained; what
        changes is that five minutes of waiting for a person is five
        minutes an event loop can spend on something else, instead of five
        minutes of :func:`time.sleep` on the thread that owns it.

        Identical in every decision it makes to :meth:`wait_for`, which is
        not a comment but a construction: both call :meth:`_seek` for the
        command and :meth:`_nap` for whether to keep waiting, and neither
        holds an opinion of its own about a decision that has arrived, a
        run that was cancelled, a window that ran out or a writer that
        went away.
        """
        deadline = self._until(timeout_s)
        while True:
            command = self._seek(predicate)
            if command is not None:
                return command
            nap = self._nap(deadline)
            if nap is None:
                return None
            await asyncio.sleep(nap)

    # ── the two decisions a wait is made of, shared by both waiters ─────

    @staticmethod
    def _until(timeout_s: float) -> float:
        """The instant a wait of *timeout_s* is over."""
        return time.monotonic() + max(0.0, float(timeout_s or 0.0))

    def _seek(self, predicate: Callable[[Dict[str, Any]], bool],
              ) -> Optional[Dict[str, Any]]:
        """The first waiting command *predicate* accepts, or ``None``.

        Everything it does not accept is **kept**, in order, for the same
        reason :meth:`poll`'s *only* keeps what it was not asked for.
        """
        self._drain()
        for position, command in enumerate(self._held):
            if predicate(command):
                return self._held.pop(position)
        return None

    def _nap(self, deadline: float) -> Optional[float]:
        """How long to wait before looking again, or ``None`` — stop.

        ``None`` is the three facts :meth:`wait_for` names as one: the run
        was cancelled underneath the wait, the window ran out, or the
        writer has gone and nothing is coming.  The order is the one this
        channel has always asked them in.
        """
        if cancelled(self._cancel):
            return None
        left = deadline - time.monotonic()
        if left <= 0:
            return None
        if self.finished:
            # Nothing is coming. Waiting out the full window for a
            # writer that has closed would hold a person at a gate
            # nobody can answer.
            return None
        return min(_TICK, left)

    @property
    def waiting(self) -> int:
        """How many commands have arrived and not yet been handed over.

        Not used by the loop, which asks for what it wants rather than how
        much there is.  It is here because "did the thing I sent get here
        yet" is otherwise unanswerable without draining, and a caller — a
        console line, a test synchronising with a real thread — that had to
        drain to find out would consume the command it was asking about.
        """
        return self._queue.qsize() + len(self._held)

    @property
    def finished(self) -> bool:
        """Whether the writer has gone and nothing is left to hand over."""
        return not self._reader.is_alive() and self._queue.empty()

    @property
    def closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        """Let go of the channel.  Never raises, and never hangs.

        Called from the caller's ``finally``, beside the sink, so a mission
        that ended badly still returns the descriptor its platform handed
        it.

        **The reader is asked to stop and briefly waited for**, and only
        then is the descriptor closed.  Both halves matter.  Closing first
        would leave the reader polling a number the process may hand to the
        next thing that opens a file; not waiting at all would do the same,
        one tick later.  The wait is bounded because a bound is the whole
        difference between shutting down and hanging: a reader that has not
        noticed within a second is left to the daemon-thread disposition,
        and the descriptor is dropped rather than the mission.
        """
        self._closed = True
        self._shutting.set()
        if not self._close_handle:
            return
        self._reader.join(timeout=1.0)
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:                     # pragma: no cover - defensive
                pass
            return
        try:
            self._handle.close()
        except (OSError, ValueError):           # pragma: no cover - defensive
            pass
