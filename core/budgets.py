# core/budgets.py — what a run may spend, and the switch that stops it early

"""The one definition of *steps*, *seconds*, *bytes* and *tokens*.

Two runtimes in this repo bound their work and, until this module, each
had its own vocabulary for the same four things.  The kernel's
:mod:`core.kernel.budgets` had a frozen dataclass, an exception
hierarchy and a wall clock; the mission loop had an integer called
``max_steps``, a ``for`` statement, and an outcome word — and no clock at
all.  A consumer reading ``budget_exhausted`` off a mission stream could
not tell *which* budget ran out, because only one of them existed.

Adding a wall clock to the mission was therefore an opportunity to add a
second owner of "seconds", and this module exists so that it did not:

* :class:`Budgets` is the shape.  Four optional numbers, ``None``
  meaning **unbounded** rather than zero, because a budget nobody set is
  not a budget of nothing;
* :class:`BudgetExhausted` is the one exception both runtimes raise, and
  it *names which budget* in :attr:`~BudgetExhausted.which` beside the
  limit and the spend.  ``core.kernel.budgets`` imports it rather than
  declaring a second base, so ``except BudgetExhausted`` written against
  either runtime catches the other;
* :class:`Deadline` is the wall clock, injectable and shared.  One
  ``Deadline`` per **mission**, handed to every runner a staged mission
  builds, so triage, planning and five sub-missions spend one clock
  rather than restarting it apiece;
* :class:`Cancellation` is the stop switch.  It is here rather than
  beside the stream because it is checked at exactly the points a
  deadline is, and a run that must ask two objects "may I keep going"
  will one day ask only one of them.

**Why a module and not a package.**  Same reason as
:mod:`core.bounding`, whose neighbour this is: the callers live in
:mod:`core.runtime`, :mod:`core.kernel` and :mod:`core.cli`, the mission
path deliberately does not import the kernel, and
``core.runtime.__init__`` pulls in every backend — which is not a thing
the kernel should have to load to learn what a budget is.  This module
imports nothing from this repo, so every direction is open and none of
them is a cycle.

**What is declared and not yet wired.**  ``max_bytes`` and
``max_tokens`` are part of the shape and part of the ``which``
vocabulary, and nothing in this repo spends them yet.  That is
deliberate rather than an omission: the mission counts no running byte
total (each result is bounded individually by
:data:`core.bounding.MAX_RESULT_BYTES`, and the whole of every result
stays in the store on purpose), and it counts no tokens because no
backend returns a usage figure yet.  Declaring the words now means the
lane that adds a usage ledger, and the lane that adds a durable run
store with a size on it, each fill in a field a consumer was already
told to expect — instead of inventing a fifth spelling of "you ran out".
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

__all__ = ["WHICH", "Budgets", "BudgetExhausted", "Deadline",
           "Cancellation", "cancelled"]


#: The words :attr:`BudgetExhausted.which` may take **on the event
#: stream** — the vocabulary ``mission_finished.budget.which`` is closed
#: over.  See :data:`core.runtime.contract.OPTIONAL`.
#:
#: The exception itself accepts any string, because the kernel has a
#: budget the mission does not (``retries``, which is per phase and never
#: reaches a mission stream), and a base class that refused it would push
#: the kernel back into declaring an exception of its own.
WHICH = ("steps", "seconds", "bytes", "tokens")


@dataclass(frozen=True)
class Budgets:
    """What one run may spend.  ``None`` is unbounded, and is the default.

    Unbounded by default, every field, and that is a decision rather than
    laziness.  The reference deployment bounds a turn at its own layer,
    and a framework that silently killed a mission at some number nobody
    chose would be a regression for every operator running a slow local
    model — a 20B at 59 tok/s spends minutes on one honest answer.  A
    budget is a thing an operator asks for.

    ``max_steps`` used to be the one exception in practice: the mission
    loop carried a step cap of its own with a default of 8.  It does not
    any more — see :class:`core.runtime.mission.MissionRunner`'s
    ``max_steps`` and :mod:`core.runtime.supervisor` for what catches an
    endless run instead — so every field of this dataclass now means the
    same thing when it is ``None``, which is what it always claimed.  This
    is still the *shape* the two runtimes agree on and the thing a console
    line is rendered from, and it is still not a second place to set a
    default.
    """

    #: Model round trips.  Counts refused replies and parse errors too:
    #: they are turns the endpoint served.  ``None`` — the default — is an
    #: operator who set no ceiling, and a run with no ceiling is not a run
    #: with no bound: see :mod:`core.runtime.supervisor`.
    max_steps: Optional[int] = None
    #: Wall clock for the whole run, in seconds.  Checked between steps
    #: and before each model call — see :class:`Deadline`.
    max_seconds: Optional[float] = None
    #: Declared, not yet spent anywhere.  See the module docstring.
    max_bytes: Optional[int] = None
    #: Declared, not yet spent anywhere.  See the module docstring.
    max_tokens: Optional[int] = None

    def describe(self) -> str:
        """One line for a console, naming the unbounded ones as unbounded.

        Rendered here rather than in the CLI so the sentence a person
        reads and the numbers a run is held to come from one object.  A
        line that said "8 steps" while the loop ran to 24 would be worse
        than no line.
        """
        parts = [
            f"{self.max_steps} steps" if self.max_steps is not None
            else "no step ceiling",
            f"{self.max_seconds:g} s" if self.max_seconds is not None
            else "no wall clock",
        ]
        return ", ".join(parts)


class BudgetExhausted(Exception):
    """A run spent all of one budget.  Says **which**, and by how much.

    Three attributes and no more, because three is what a consumer needs
    to render the sentence: the word for the budget, the limit it was
    held to, and what it actually spent.  ``spent`` is not always equal
    to ``limit`` — a wall clock is noticed a little after it runs out,
    and reporting the limit as the spend would hide by how much.

    :meth:`as_record` is the wire form, and the only one: the direct
    mission path and the staged one both render ``mission_finished``
    through a single function, which calls this.  The swarm once shipped
    six of a record's ten fields by hand-listing them.
    """

    def __init__(self, which: str, limit: Any, spent: Any,
                 message: str = ""):
        self.which = str(which)
        self.limit = limit
        self.spent = spent
        super().__init__(
            message or f"{self.which} budget exhausted: spent {spent} of {limit}"
        )

    def as_record(self) -> Dict[str, Any]:
        """``{"which", "limit", "spent"}`` — the ``budget`` field's shape."""
        return {"which": self.which, "limit": self.limit, "spent": self.spent}


class Deadline:
    """One run's wall clock, started once and shared by everything in it.

    *seconds* is the budget, or ``None`` for a run nobody put a clock on;
    an unbounded deadline answers :meth:`expired` with ``False`` forever
    and costs one comparison per step.

    *monotonic* is injected for the same reason ``chat_fn`` is: a test
    that proves a mission stops at its deadline must not have to spend
    the deadline to prove it.  ``time.monotonic`` and not
    ``time.time``, because a run must not end early because somebody
    stepped the system clock.

    **Started, not constructed.**  The clock begins at :meth:`start`, and
    the first start wins.  A staged mission constructs one deadline and
    hands it to the triage runner, the planner and every sub-mission; if
    construction started it, the CLI's would run from before the tool
    plane was even reached, and if each ``run()`` restarted it, five
    sub-missions of a minute each would fit inside a one-minute budget.
    An unstarted deadline has spent nothing and never expires, which is
    the honest reading of a clock nobody wound.
    """

    def __init__(self, seconds: Optional[float] = None, *,
                 monotonic: Callable[[], float] = time.monotonic):
        self._monotonic = monotonic
        self._seconds = None if seconds is None else max(0.0, float(seconds))
        self._started: Optional[float] = None

    @classmethod
    def of(cls, budgets: Budgets, *,
           monotonic: Callable[[], float] = time.monotonic) -> "Deadline":
        """The clock :attr:`Budgets.max_seconds` describes."""
        return cls(budgets.max_seconds, monotonic=monotonic)

    @property
    def seconds(self) -> Optional[float]:
        """The budget itself, or ``None`` for unbounded."""
        return self._seconds

    @property
    def unbounded(self) -> bool:
        return self._seconds is None

    @property
    def started(self) -> bool:
        return self._started is not None

    def start(self) -> "Deadline":
        """Wind the clock, once.  Returns self so it can be chained."""
        if self._started is None:
            self._started = float(self._monotonic())
        return self

    def spent(self) -> float:
        """Seconds since :meth:`start`, or ``0.0`` before it."""
        if self._started is None:
            return 0.0
        return max(0.0, float(self._monotonic()) - self._started)

    def remaining(self) -> Optional[float]:
        """Seconds left, or ``None`` when there is no budget.

        May be negative: a caller that wants a timeout ceiling wants to
        know it is already past, not to be handed a comforting zero.
        """
        if self._seconds is None:
            return None
        return self._seconds - self.spent()

    def expired(self) -> bool:
        remaining = self.remaining()
        return remaining is not None and remaining <= 0.0

    def exhausted(self) -> Optional[BudgetExhausted]:
        """The exception this clock would raise, or ``None`` if it would not.

        Returned rather than raised.  The mission loop wants to *end* on
        an exhausted budget — recorded outcome, ``mission_finished``,
        transcript intact — and a loop that has to catch an exception to
        do so is one ``except`` clause away from ending on somebody
        else's.
        """
        if not self.expired():
            return None
        return BudgetExhausted("seconds", self._seconds, round(self.spent(), 3))


class Cancellation:
    """A run's stop switch: somebody outside asked it to wind up.

    Not a budget — nothing was spent — but checked at exactly the points
    a :class:`Deadline` is, which is why it lives here.  A cancelled run
    ends ``incomplete`` and says ``reason: "cancelled"`` on
    ``mission_finished``: it is the transcript's ordinary word for
    "stopped without an answer", now carrying the one fact that word was
    missing.

    A :class:`threading.Event` underneath, so a signal handler, a UI
    thread and the loop can share it.  Any object with ``is_set()`` is
    accepted wherever this one is, because a caller that already holds an
    ``Event`` should not have to wrap it.

    *cause* is for the process that owns the switch, and it does **not**
    travel on the stream.  The CLI needs to tell "a SIGTERM asked us to
    stop" from "a library caller did", because only the first has to end
    with the process dying of that signal; a consumer reading the stream
    needs neither, and a second vocabulary on the wire would be two words
    for one fact.  First cause wins: a second cancel does not rewrite why
    the first one happened.
    """

    def __init__(self, event: Optional[threading.Event] = None):
        self._event = event if event is not None else threading.Event()
        self._cause = ""

    def cancel(self, cause: str = "") -> None:
        if not self._event.is_set():
            self._cause = str(cause or "")
        self._event.set()

    def is_set(self) -> bool:
        return bool(self._event.is_set())

    @property
    def cause(self) -> str:
        return self._cause

    def __bool__(self) -> bool:
        return self.is_set()


def cancelled(cancel: Any) -> bool:
    """Whether *cancel* is a switch that has been thrown.

    ``None`` — the default everywhere — is not cancelled, and neither is
    an object that does not know the question.  Duck-typed on
    ``is_set()`` so a bare :class:`threading.Event` works, and defensive
    because a run must not die of the shape of the thing watching it.
    """
    if cancel is None:
        return False
    check = getattr(cancel, "is_set", None)
    if check is None:
        return bool(cancel)
    try:
        return bool(check())
    except Exception:                           # pragma: no cover - defensive
        return False
