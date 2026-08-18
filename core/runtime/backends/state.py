# core/runtime/backends/state.py — what a backend can say about the model itself

"""The side channel for *why you are waiting*, in seven words.

A run's stream says what the agent decided and what it cost.  It has never
said anything about the thing on the other end of the socket, and two weeks
of a deployment watching a local endpoint taught the same lesson twice: a
pane that shows nothing for ninety seconds is showing three different
situations — a server loading weights, a server that has the request and is
behind a queue, and a server that is not there at all — and an operator
cannot act on any of them without being told which.  ``ROADMAP.md`` §5.9
records it as *"queued is not loading, and a browser must be able to say
which"*.

So a backend reports, and the words are these:

``cold``
    The server is up and the model this backend asks for is not among the
    ones it lists.  Nothing is wrong; nothing is loaded either.
``asking``
    The request has been sent.  The steady state, and the one word that
    **never reaches the wire** — see :data:`WAITING`.
``queued``
    The server took the request and is not answering yet, and ``/models``
    says the model is loaded.  Somebody else is in front of you.
``loading``
    The **server said so** — a 503, with whatever it put in the body and
    whatever ``Retry-After`` it asked for.  This word is never a guess:
    a silence is ``queued`` or ``cold``, and only the server's own answer
    is ``loading``.
``loaded``
    A reply, or a first token, arrived — with the model id the server
    reported.
``failed``
    The class of error :data:`core.runtime.backends.policy.ERROR_POLICY`
    names, arrived at through that table rather than through a second
    opinion here.
``absent``
    Nothing answered on the socket — a refused, reset or unresolved
    connect, whether on the completion or on the ``GET /models`` a stalled
    call goes back to ask.

**Nothing here imports anything.**  Standard library only, like
:mod:`core.runtime.contract` and for the same reason: this is the bottom of
the backend stack, the policy module beside it reads the vocabulary, and a
state module that could reach up into the runtime would stop being a
vocabulary and start being an opinion about what the runtime is doing.

**A report is dropped unless somebody installed a sink.**  :func:`watching`
is how a run installs one — see
:meth:`core.runtime.run.Model.watching`, which is the only caller in this
repository and which turns reports into ``model_state`` records.  A
backend called from a chat session, a capability probe at start-up, a
library caller with no observer: all of them report into nothing, at the
cost of one :class:`~contextvars.ContextVar` read.  That is deliberate.  A
backend must not have to know whether it is inside a mission, and a side
channel that required wiring would be a side channel that half the paths
forgot.

The sink is carried in a :class:`~contextvars.ContextVar` rather than
passed down, because the call it describes goes to a worker thread
(:func:`asyncio.to_thread` copies the context) and sometimes to a timer
thread (:func:`first_byte_within` copies it by hand).  A parameter would
have had to be threaded through ``chat`` and every private method under
it, in four backends, for a fact none of them return.
"""

from __future__ import annotations

import contextvars
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Iterator, Optional

__all__ = [
    "COLD", "ASKING", "QUEUED", "LOADING", "LOADED", "FAILED", "ABSENT",
    "STATES", "WAITING", "FIRST_BYTE_QUEUED_S",
    "Report", "report", "watching", "first_byte_within",
    "retry_after_seconds",
]


# ── the seven words ──────────────────────────────────────────────────────────

#: The server is up and does not list the model this backend asks for.
COLD = "cold"
#: The request has been sent.  Never on the wire; see :data:`WAITING`.
ASKING = "asking"
#: Accepted, not answering, and ``/models`` says the model is loaded.
QUEUED = "queued"
#: The server said it is loading — a 503 and its body.
LOADING = "loading"
#: A reply, or a first token, arrived.
LOADED = "loaded"
#: The error class :data:`~core.runtime.backends.policy.ERROR_POLICY` names.
FAILED = "failed"
#: Nothing answered on the socket.
ABSENT = "absent"

#: The closed vocabulary, as data, so a test can read it and a consumer can
#: assert it knows all of them.  The order is the order a bad afternoon
#: tends to produce them in.
STATES: tuple[str, ...] = (
    COLD, ASKING, QUEUED, LOADING, LOADED, FAILED, ABSENT,
)

#: The states that mean **a person is waiting and does not know why**.
#:
#: This is the set the ``model_state`` record exists for, and the reason
#: the record is not simply "every state change".  ``asking`` and
#: ``loaded`` are the two halves of a healthy call, and a healthy call
#: already has records — ``step_started`` before it and ``answer`` or
#: ``tool_call`` after it — so emitting them would put two records on
#: every stream ever recorded to say what those records already say.  See
#: :meth:`core.runtime.run.Model.watching`, which owns that rule, and
#: ``CONTRACT.md`` on ``model_state``, which states it to consumers.
WAITING: frozenset = frozenset({COLD, QUEUED, LOADING, FAILED, ABSENT})

#: How long the first byte of an accepted request may take before the wait
#: is reported as a state rather than left as a silence.
#:
#: Twenty seconds is a judgement about **a person**, not about a model: a
#: local endpoint at 59 tok/s spends tens of seconds on one answer and is
#: perfectly healthy while it does, so a threshold short enough to catch
#: every slow call would report a state on every call.  What it is meant
#: to catch is the wait that has stopped looking like work — and at that
#: point ``/models`` is asked, which is what makes ``queued`` and ``cold``
#: different words rather than two guesses.
#:
#: A constructor argument on the backend, not an environment variable: it
#: is a property of the endpoint a deployment is pointed at, and the
#: contract's :data:`~core.runtime.contract.ENV_VARS` is a surface a
#: consumer is promised rather than a place to put a tuning knob.
FIRST_BYTE_QUEUED_S = 20.0


@dataclass(frozen=True)
class Report:
    """One thing a backend noticed about the model, on its way to a record.

    Frozen, and plain data: it crosses a thread boundary, and the sink
    that receives it may be de-duplicating a run's worth of them.

    *provider* and *model* are the backend's own names for what it is
    talking to — the words that reach the record's required fields.
    *detail* is what the **server** said, if it said anything, and is
    scrubbed by the observer like every other free-text field on the
    stream.  *retry_after_s* is the server's own ``Retry-After``, in
    seconds, and ``None`` when it did not ask for one.
    """

    state: str
    provider: str = ""
    model: str = ""
    detail: str = ""
    retry_after_s: Optional[float] = None


# ── who is listening ─────────────────────────────────────────────────────────

_SINK: contextvars.ContextVar[Optional[Callable[[Report], None]]] = \
    contextvars.ContextVar("judais_model_state_sink", default=None)


def report(state: str, *, provider: str = "", model: str = "",
           detail: str = "", retry_after_s: Optional[float] = None) -> None:
    """Say something about the model.  Dropped when nobody is listening.

    Cheap enough to call unconditionally — one context lookup when there
    is no sink — which is the property that lets a backend report from
    the four or five places it actually learns something, rather than
    from the one place somebody remembered to wire.

    A word outside :data:`STATES` raises, and it raises **here** rather
    than at the far end of a pipe: the vocabulary is closed, a consumer
    asserts it, and a typo that reached the wire would be an event a
    browser has no branch for.  A sink that throws is swallowed for the
    same reason an observer that throws is: a mission must not fail
    because somebody was watching it.
    """
    if state not in STATES:
        raise ValueError(
            f"{state!r} is not one of the model states: {', '.join(STATES)}")
    sink = _SINK.get()
    if sink is None:
        return
    try:
        sink(Report(state=state, provider=provider, model=model,
                    detail=detail, retry_after_s=retry_after_s))
    except Exception:                       # pragma: no cover - defensive
        pass


@contextmanager
def watching(sink: Callable[[Report], None]) -> Iterator[None]:
    """Route every report made in this context to *sink*.

    Restored on the way out, including out of an exception, so a call
    that raised does not leave a mission's sink installed for whatever
    the process does next.

    Nested rather than replaced: the inner sink wins for the length of
    the inner block and the outer one is back afterwards, which is what
    :class:`~contextvars.ContextVar` tokens give for free and what a
    module-level global would have made a lie.
    """
    token = _SINK.set(sink)
    try:
        yield
    finally:
        _SINK.reset(token)


# ── the wait that stopped looking like work ──────────────────────────────────

class FirstByte:
    """A one-shot alarm for a request that has been accepted and is silent.

    Held by :func:`first_byte_within`.  :meth:`arrived` is idempotent and
    is called both by the backend, when the first byte turns up, and by
    the context manager's ``finally``, so an abandoned generator or a
    raised call cannot leave a timer thread behind.
    """

    def __init__(self, timer: Optional[threading.Timer] = None):
        self._timer = timer

    def arrived(self) -> None:
        """The wait is over — disarm.  Safe to call twice, or never."""
        timer, self._timer = self._timer, None
        if timer is not None:
            timer.cancel()

    @property
    def armed(self) -> bool:
        """Whether the alarm is still pending.  Read by tests."""
        return self._timer is not None


@contextmanager
def first_byte_within(after_s: float,
                      on_late: Callable[[], None]) -> Iterator[FirstByte]:
    """Run *on_late* once if nothing has arrived within *after_s* seconds.

    The observable signal behind ``queued``: a request the server
    **accepted** and has not begun answering.  It is a timer and not a
    read timeout on purpose — a slow endpoint must keep its long
    ``CHAT_TIMEOUT``, because the point is to *say something* about a
    wait, never to shorten one.

    *on_late* runs on a timer thread, in a **copy of the calling
    context**, so a :func:`report` inside it reaches the sink the caller
    installed.  Timer threads inherit no context of their own, and that
    is the whole reason this helper exists rather than a bare
    :class:`threading.Timer` at each call site.

    Nothing is armed when no sink is installed, or when *after_s* is not
    positive: a chat session, a probe and a library caller with no
    observer must not each spawn a thread to notice something nobody
    asked to be told.
    """
    if _SINK.get() is None or not after_s or after_s <= 0:
        yield FirstByte()
        return
    context = contextvars.copy_context()

    def fire() -> None:
        try:
            context.run(on_late)
        except Exception:                   # pragma: no cover - defensive
            pass

    timer = threading.Timer(after_s, fire)
    timer.daemon = True
    timer.start()
    watch = FirstByte(timer)
    try:
        yield watch
    finally:
        watch.arrived()


# ── what the server asked for ────────────────────────────────────────────────

def retry_after_seconds(headers: Any) -> Optional[float]:
    """``Retry-After`` as seconds, or ``None`` when there is nothing to read.

    Both forms the RFC allows: a delay in seconds, which is what every
    server this repo has met sends, and an HTTP date, which is read
    against the date the server stamped the response with rather than
    against this host's clock — the two are routinely minutes apart and
    the number is meant to be a wait, not a timestamp difference.

    Never raises and never negative: a header this cannot make sense of
    is a header that said nothing, and a wait in the past is over.
    """
    get = getattr(headers, "get", None)
    if not callable(get):
        return None
    try:
        raw = get("Retry-After") or get("retry-after")
    except Exception:                       # pragma: no cover - defensive
        return None
    if raw is None:
        return None
    try:
        return max(0.0, float(str(raw).strip()))
    except (TypeError, ValueError):
        pass
    try:
        when = parsedate_to_datetime(str(raw))
        stamped = get("Date") or get("date")
        now = (parsedate_to_datetime(str(stamped)) if stamped
               else datetime.now(timezone.utc))
        return max(0.0, (when - now).total_seconds())
    except (TypeError, ValueError):
        return None
