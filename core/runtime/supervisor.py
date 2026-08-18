# core/runtime/supervisor.py — the thing that notices a run is going nowhere

"""What replaced the step budget: a watcher, not a countdown.

Until this module a mission was bounded by **counting turns**.  Eight of
them by default, and when the eighth was spent the run said
``budget_exhausted`` and stopped — whatever it was in the middle of, and
however close it was.  That number was doing two jobs and doing one of
them badly:

* it stopped an endless loop, which is a real job and has to be done by
  something;
* and it decided how much work a question was worth, which is not a
  thing a framework can know.  Some questions take four turns and some
  take forty; a mission that needed a fifth governed view spent its
  budget on the fourth and reported what it had as though that were the
  answer.  The owner's instruction, verbatim: *"sometimes tasks take more
  budget. instead we should only worry about catching an endless loop
  where it is stuck … if it just needs more thinking. Let it think."*

So the counting is gone — ``--mission-steps`` survives only as an
operator's optional ceiling, exactly like ``--mission-seconds`` — and
this module does the job that was worth doing.  Two layers, in this
order, because the cheap one has to be able to say "nothing to see here"
without spending a model call:

1. **Mechanical signals** (:data:`SIGNALS`).  Evaluated at every step
   boundary, free, and each one is a *demonstrated repetition* rather
   than a quantity: the same call returning the same bytes three times,
   three rejected replies running, four steps that produced no evidence
   the run did not already have, an A-B-A-B oscillation.  Nothing here
   counts tokens, output length or thinking time — a model that spends
   nine minutes on one honest turn trips nothing.
2. **A review turn** (:meth:`Supervisor.look`).  When a signal fires the
   *same model* is asked, in plain chat, to look at what the run has
   done and say one of three words: :data:`PROGRESSING` (a false alarm),
   :data:`NUDGE` (stuck but helpable — and here is the note to give it),
   :data:`STUCK` (wind it up).  The swarm's step-level review gets a
   fourth, :data:`REPLAN`.

**Why the model and not a rule.**  A rule that could tell "reading the
same index three times because the answer needs three fields of it" from
"reading the same index three times because it forgot it already had it"
would be an agent.  We have one of those; it is the same one, it has the
transcript, and asking it costs one cheap call at the moment something
looks wrong rather than a bound on every run that never does.

**What bounds the bound.**  A review is itself a model call, so reviews
are capped at :data:`REVIEWS` per run, and on the last one
:data:`PROGRESSING` is not offered.  A run that keeps tripping signals
and keeps being told it is fine is *precisely* the endless loop the
owner asked to catch, and it is caught by arithmetic that cannot be
talked out of it: after the last review the next signal winds the run up
with no further call.

**One supervisor per turn.**  A staged (``--swarm``) turn hands the same
object to every sub-mission it builds and to its own step-level gate
review, so a plan that loops *across* its steps is a pattern this sees —
and so the review budget is the turn's, not five copies of it.

Nothing in here ends a run by itself.  :meth:`Supervisor.look` returns a
:class:`Review` and the runner decides what to do with it; the note a
nudge carries is delivered through the mechanism an operator's
``inject`` already uses, and a wind-up is the runner asking the model for
its best answer.  A supervisor that could stop a mission would be a
second owner of "why did this run end", beside the one in
:meth:`core.runtime.mission.MissionRunner._stop`.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

__all__ = [
    "REPEATED_CALL", "REJECTED_REPLIES", "NO_NEW_EVIDENCE", "OSCILLATION",
    "FAILED_GATE", "SIGNALS", "PROGRESSING", "NUDGE", "STUCK", "REPLAN",
    "VERDICTS", "VERDICT_LINES", "REPEATS", "REJECTIONS", "STALE_STEPS",
    "REVIEWS", "REFUNDS_ON_PROGRESSING", "REVIEW_REFUNDS",
    "Review", "Supervisor", "NUDGE_NOTE", "WIND_UP", "describe",
]


# ── the signals ──────────────────────────────────────────────────────────────

#: The same tool, the same arguments, the same bytes back — again.
REPEATED_CALL = "repeated_call"
#: The model's replies have stopped being decisions this loop can act on.
REJECTED_REPLIES = "rejected_replies"
#: Steps are happening and nothing new is coming out of them.
NO_NEW_EVIDENCE = "no_new_evidence"
#: Two states, alternating: A, B, A, B.
OSCILLATION = "oscillation"
#: A staged step's gate said no.  The swarm's, and the only signal that is
#: reported to this object rather than noticed by it.
FAILED_GATE = "failed_gate"

#: One row per signal: the sentence the reviewing model is shown, with the
#: numbers filled in.  **Data and not code** for the reason
#: :data:`core.runtime.backends.policy.ERROR_POLICY` is: the next person to
#: add a signal should be adding a row here and a counter below it, not a
#: fifth ``if`` in a method that already has four, and the sentence a model
#: is asked about should be readable without reading the detector.
#:
#: Each is a statement about *repetition*, which is the whole discipline of
#: this table.  None of them is a quantity — not turns spent, not tokens,
#: not seconds — because a run that is taking a long time and a run that is
#: going nowhere are different things and only the second one is anybody's
#: business here.  The wall clock and the stop switch stay where they are:
#: they belong to the operator (:class:`core.budgets.Deadline`,
#: :class:`core.budgets.Cancellation`) and are checked by
#: :meth:`core.runtime.mission.MissionRunner._stop`.
SIGNALS: Dict[str, str] = {
    REPEATED_CALL: (
        "the same tool has been called with the same arguments and returned "
        "the same result {n} times over the last few calls — an identical "
        "result is not new information, and something is being asked again"),
    REJECTED_REPLIES: (
        "{n} model replies in a row were not decisions this loop could act "
        "on: they did not parse, or named a tool nobody offers, or carried "
        "arguments the tool's own schema refused"),
    NO_NEW_EVIDENCE: (
        "{n} steps have gone by without one new tool call and without one "
        "result the run had not already seen — the conversation is moving "
        "and the evidence is not"),
    OSCILLATION: (
        "the run is alternating between two calls, A B A B, rather than "
        "going forward from either of them"),
    FAILED_GATE: (
        "this plan step has just failed its gate — the step ran and what it "
        "produced is not what the plan asked for"),
}

#: How many identical (tool, arguments, result) acts make a
#: :data:`REPEATED_CALL`.  Three and not two: a second identical result is
#: an ordinary thing — a model re-reading a listing before quoting it — and
#: a third is a pattern.
#:
#: **Not "in a row"**, and that is a correction the live run of 17 August
#: made.  A model polling a view for something that will never appear does
#: not poll it three times running: it reads the view, reads a field out of
#: the stored result, reads the view again, tries another path, reads the
#: view a third time.  Three identical calls with two productive-looking
#: reads threaded between them is the *same* stall, and a detector that
#: wanted them consecutive watched that run go round four times and said
#: nothing.  So the window is :data:`REPEAT_WINDOW` acts wide and what is
#: counted is how many of them are the same act.
REPEATS = 3

#: How many recent acts :data:`REPEATED_CALL` is counted over, as a
#: multiple of :data:`REPEATS`.  Two: three identical calls among six is a
#: run spending half its work on one question, and widening it further
#: would start calling an ordinary re-read at the end of a long mission a
#: loop.  It is a *window* rather than the whole run for the same reason —
#: three identical reads spread over forty productive steps are three
#: careful re-reads.
REPEAT_WINDOW = 2

#: How many rejected replies in a row are :data:`REJECTED_REPLIES`.  Three,
#: for the same reason: one is a slip, and this loop hands back a
#: correction precisely so the next one is right; three says the correction
#: is not landing.
REJECTIONS = 3

#: How many steps with nothing new in them are :data:`NO_NEW_EVIDENCE`.
#: Four, which is one more than :data:`REPEATS`, so a run that is repeating
#: one call is reviewed as a repeat — the specific signal, with the specific
#: sentence — rather than as a general stall.
STALE_STEPS = 4

#: How many acts an :data:`OSCILLATION` is read over: A, B, A, B.  Four is
#: the shortest window in which alternation is distinguishable from two
#: ordinary calls, and it is even by construction — a window of five would
#: ask whether A B A B A is A-led or B-led, which is not a question about
#: the run.
OSCILLATES = 4

#: How many review turns one run may spend.  Three.
#:
#: **This is the whole of the endless-loop catch**, and it is arithmetic
#: rather than judgement on purpose.  Each review is a model call and each
#: verdict is the model's opinion of itself; a run that can keep asking for
#: another opinion is a run that can loop forever with a review turn in it.
#: So: three, the last of which is not offered :data:`PROGRESSING`, and
#: after them a signal winds the run up with no further call.
REVIEWS = 3

#: The signals for which a :data:`PROGRESSING` verdict is **refunded** —
#: the review is not counted against :data:`REVIEWS` and the last review is
#: still offered the word.
#:
#: One member, and the reason it has one is the difference between the
#: signals.  :data:`REPEATED_CALL`, :data:`REJECTED_REPLIES` and
#: :data:`OSCILLATION` are *demonstrated repetition*: the same act three
#: times, three replies the loop could not act on, A B A B.  A run that
#: keeps producing those after three reviews has answered the question, and
#: the arithmetic that ends it is the endless-loop catch working.
#:
#: :data:`NO_NEW_EVIDENCE` is not that.  It is an *absence* — nothing new
#: came out of the last few steps — and absence is the thing a healthy run
#: legitimately shows for a stretch: a long build, a retried fetch, a
#: careful re-read.  Spending the budget on it meant a run that was told
#: "this is fine" twice was forced ``stuck`` on the third, by arithmetic,
#: while the model was still saying ``progressing`` and new results were
#: still arriving.  The owner's instruction is the whole of the argument:
#: *"instead we should only worry about catching an endless loop where it
#: is stuck … if it just needs more thinking. Let it think."*
#:
#: A refund is not free.  :meth:`Supervisor._threshold` still rises on every
#: ``progressing`` — four stale steps, then eight, then twelve — so the same
#: absence costs geometrically more to report and cannot spend a run's turns
#: on reviews.  What it cannot do any more is *end* a run that is working.
REFUNDS_ON_PROGRESSING: frozenset = frozenset({NO_NEW_EVIDENCE})

#: How many refunds one signal may have.  Two, and it is a number rather
#: than "as many as it likes" because the endless-loop catch has to survive
#: this.
#:
#: There is one stall the other three signals genuinely cannot see: a
#: three-cycle, A B C A B C, with the same bytes back every time.
#: :data:`OSCILLATION` reads two states and :data:`REPEATED_CALL` counts an
#: identical act three times in a window of six, which a three-cycle never
#: reaches — so :data:`NO_NEW_EVIDENCE` is the only thing watching it, and a
#: refund with no floor would let a model that answers ``progressing``
#: forever keep a dead run alive forever.  With two refunds such a run is
#: reviewed five times, at thresholds of 4, 8, 12, 16 and 20 stale steps,
#: and then wound up.  A healthy run pays none of this: since a step with
#: either a new call or a new result is evidence, a run that is getting
#: anywhere never fires the signal at all.
REVIEW_REFUNDS = 2

#: How much of a result the reviewing model is shown per act.  Enough to
#: recognise a listing; short enough that twenty of them are a prompt and
#: not a transcript.  The whole of every result is in the mission's own
#: store either way.
EXCERPT_CHARS = 160

#: How many acts the review turn is shown, newest last.  A bound and not a
#: choice about relevance: the pattern that fired is at the end of this
#: window by construction.
WINDOW_ACTS = 20


# ── the verdicts ─────────────────────────────────────────────────────────────

#: A false alarm: the pattern is real and it is not a loop.  The run
#: carries on, and **that signal's threshold is raised for the rest of the
#: run** so the same pattern does not buy a second review — a supervisor
#: that could be told "this is fine" and ask again next step would spend
#: the whole review budget on one answered question.
PROGRESSING = "progressing"

#: Stuck, and helpable.  The verdict carries a ``note``, which the runner
#: puts in front of the model as a user turn at the next step boundary —
#: through the same mechanism an operator's ``inject`` uses, because it is
#: the same act: somebody outside the conversation saying something into it.
NUDGE = "nudge"

#: Stuck, and not helpable.  The run winds up: the model is asked for its
#: best answer with what it has, and ``mission_finished`` says
#: ``reason: "stuck"``.
#:
#: The verdict word and the word on the wire are ONE string, imported by
#: :mod:`core.runtime.mission` rather than spelled again there — the same
#: arrangement :data:`core.runtime.mission.CANCELLED` has, and for the same
#: reason: two spellings of one fact drift.
STUCK = "stuck"

#: The plan is what is stuck, not the step.  **Swarm only**, and offered
#: only at the step-level review — a direct mission has no plan to redraw,
#: and a verdict a runner cannot act on is a verdict that will be read as
#: something else.
REPLAN = "replan"

#: The closed set, so a caller can assert it knows all of them.
VERDICTS: Tuple[str, ...] = (PROGRESSING, NUDGE, STUCK, REPLAN)

#: What each verdict is *told to the model*.  Data beside the words
#: themselves so the prompt cannot offer a verdict the parser will not take,
#: which is how a review comes back unreadable and costs a turn for nothing.
VERDICT_LINES: Dict[str, str] = {
    PROGRESSING: (
        '"progressing" — this is not a loop. The repetition has a reason '
        'and the work is going somewhere. Say this and the run carries on '
        'untouched.'),
    NUDGE: (
        '"nudge" — it is stuck, and one instruction would unstick it. Put '
        'that instruction in "note", addressed to the agent in the second '
        'person, one or two sentences: what to stop doing, what to try '
        'instead, or what it already has and has not used.'),
    STUCK: (
        '"stuck" — it cannot be unstuck. The tools cannot answer this, or '
        'the thing being asked for does not exist. Say this and the run is '
        'asked for its best answer with what it has, and ends.'),
    REPLAN: (
        '"replan" — the step is fine and the PLAN is wrong: this step '
        'cannot succeed as written, whoever attempts it. Say this and the '
        'plan is redrawn around what has already succeeded. Put what is '
        'wrong with the plan in "note".'),
}

#: The system turn of a review, minus the verdict lines, which are composed
#: from :data:`VERDICT_LINES` for whichever verdicts this review may return.
REVIEW_PROMPT = """\
You are reviewing an agent that is part-way through a mission with tools. \
It is not stopped and nothing has failed; a mechanical watcher noticed a \
repeating pattern and your job is to say what the pattern means.

You are looking for ONE thing: is this agent going somewhere, or is it \
going round? Taking a long time is not going round. Reading a large \
result twice is not going round. Asking the same question, getting the \
same answer, and asking it again is going round.

Reply with exactly one JSON object and no other text, no code fence:
  {"verdict": "<one word>", "note": "<one or two sentences, or empty>"}

The words you may use:
"""

#: What a nudged run is told, with the reviewer's note in it.
#:
#: Framed as a note from outside the conversation rather than as the
#: model's own thought, for the reason
#: :data:`core.runtime.mission.PLANE_CHANGED` is said out loud: an
#: instruction that appears in a transcript with nothing saying where it
#: came from reads, from inside, as the agent having decided something it
#: did not decide.
NUDGE_NOTE = (
    "A supervisor has been watching this run and thinks it is going round "
    "in circles: {signal} Its note to you: {note}\n"
    "Nothing has been taken away from you and nothing you have already "
    "read is lost. Do something different from what you have been doing."
)

#: What a wound-up run is told.  One turn, one ask, and it is not a
#: refusal: the run is over either way, and an answer written from four
#: real tool results with its gaps named is worth more to the person who
#: asked than a transcript that stops.
WIND_UP = (
    "Stop. A supervisor has been watching this run and judges it stuck: "
    "{signal} It will not be continued past this turn.\n"
    "Give your best answer NOW, from what you have already read. State "
    "plainly what you could not establish and why, and do not claim "
    "anything a tool did not return. Answer in this reply."
)

#: The ``note`` of the verdict the **arithmetic** makes when the review
#: budget is spent, so a consumer reading ``step_started.review`` can see
#: that this one was not somebody's opinion.
OUT_OF_REVIEWS = (
    "the pattern came back after every review this run had, so it winds up "
    "without asking a fourth time"
)

_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.MULTILINE)


def describe(signal: str, n: int = 0) -> str:
    """The sentence for *signal*, with its number in it.

    ``{n}`` is filled where the row has one and left alone where it does
    not, so a row may be written with or without a count and neither
    spelling needs a branch at the call site.
    """
    sentence = SIGNALS.get(signal, signal)
    try:
        return sentence.format(n=n)
    except (KeyError, IndexError):              # pragma: no cover - defensive
        return sentence


# ── what a review is ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Review:
    """One verdict, and the record of it that rides ``step_started``."""

    #: Which of :data:`SIGNALS` fired.
    signal: str
    #: One of :data:`VERDICTS`.
    verdict: str
    #: The reviewer's instruction, on :data:`NUDGE` and :data:`REPLAN`.
    note: str = ""
    #: How many reviews this run has left after this one.  On the record
    #: because it is the only way a consumer can tell a run that is being
    #: helped from one that is about to be wound up — the difference
    #: between ``nudge`` with two left and ``nudge`` with none.
    reviews_left: int = 0
    #: The count that made the signal fire, for the sentence the model is
    #: shown.  Never on the wire: a consumer reads the signal's name and
    #: this repo's own thresholds are not a contract.
    count: int = 0

    def as_record(self) -> Dict[str, Any]:
        """``{signal, verdict, reviews_left}``, plus ``note`` when there is one.

        Absent rather than empty, like every optional thing on this stream:
        a field states a fact only when there is one to state.
        """
        record: Dict[str, Any] = {
            "signal": self.signal, "verdict": self.verdict,
            "reviews_left": self.reviews_left,
        }
        if self.note:
            record["note"] = self.note
        return record

    def sentence(self) -> str:
        """The signal's own sentence, for the turn the model is shown."""
        return describe(self.signal, self.count)


# ── what the supervisor watches ──────────────────────────────────────────────

@dataclass
class _Act:
    """One dispatched call, as this module needs to compare it."""

    tool: str
    #: Digest of ``tool`` plus its arguments.  A digest and not the text: a
    #: governed view's arguments are small but its *result* is not, and one
    #: comparison rule for both is one thing to get right.
    call: str
    #: Digest of what came back.  This is what makes a repetition a
    #: repetition: the same call returning something DIFFERENT is the run
    #: making progress, and is not a signal.
    result: str
    #: A short rendering for the review turn.  Never compared.
    shown: str


@dataclass
class _Step:
    """One model turn, as this module needs to remember it."""

    acts: List[_Act] = field(default_factory=list)
    rejections: int = 0

    @property
    def empty(self) -> bool:
        return not self.acts and not self.rejections


def _digest(text: str) -> str:
    """A short, stable fingerprint.  Not a security decision: this compares
    a 40 KB governed view with the last one cheaply, and nothing anywhere
    reverses it."""
    return hashlib.blake2s(text.encode("utf-8", "replace"),
                           digest_size=8).hexdigest()


def _short(text: str, limit: int = EXCERPT_CHARS) -> str:
    """*text* on one line, cut to *limit* with the cut marked."""
    flat = " ".join(str(text or "").split())
    if len(flat) <= limit:
        return flat
    return flat[:limit] + f"… (+{len(flat) - limit} chars)"


def _read_verdict(reply: Any) -> Tuple[str, str]:
    """``(verdict, note)`` out of a review's reply, or ``("", "")``.

    The same forgiveness :meth:`core.runtime.mission.MissionRunner._parse`
    extends and no more: a fenced object is a formatting slip and is
    unwrapped; prose around an object is read for the object; prose with no
    object in it is not guessed at.
    """
    text = _FENCE.sub("", str(reply or "")).strip()
    if not text:
        return "", ""
    decision: Any = None
    try:
        decision = json.loads(text)
    except (ValueError, TypeError):
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            return "", ""
        try:
            decision = json.loads(text[start:end + 1])
        except (ValueError, TypeError):
            return "", ""
    if not isinstance(decision, dict):
        return "", ""
    verdict = str(decision.get("verdict") or "").strip().lower()
    note = " ".join(str(decision.get("note") or "").split())
    return verdict, note


class Supervisor:
    """Watches one run for repetition, and asks the model about it.

    Parameters
    ----------
    chat_fn:
        ``messages -> str``: the **plain** chat function, with no tool
        schemas declared, which is the same one the swarm's router and
        gates use.  A review is a question to be answered, and a model
        handed a function namespace answers a question with a tool call —
        the failure ``plain_chat_fn`` exists to prevent.

        Injected rather than taken off a client, so a test proves every
        verdict without an endpoint, and so the review is billed to the
        same account the run is: it is the same model, deliberately, and
        not a cheaper one somebody has to configure.
    window:
        The run's one :class:`~core.runtime.context_window.MissionWindow`,
        or ``None``.  The review prompt is short by construction — a
        bounded window of acts, each excerpted — but it is fitted through
        the same window everything else in the run is, because "short by
        construction" is an argument that has been wrong here before.
    usage_fn:
        The backend's usage side channel, as
        :class:`~core.runtime.mission.MissionRunner` takes it.  A review is
        a model call and it goes on the ledger like every other one; a
        supervisor whose calls were free on the invoice would be
        under-reporting exactly the runs that went badly.
    repeats, rejections, stale_steps, reviews:
        The four numbers above (:data:`REPEATS`, :data:`REJECTIONS`,
        :data:`STALE_STEPS`, :data:`REVIEWS`).  Parameters so a test can
        make a pattern in three lines instead of twelve, and so a
        deployment that measures a better number can state it — not
        because any of them is a budget.
    """

    def __init__(
        self,
        chat_fn: Callable[..., Any],
        *,
        window: Any = None,
        usage_fn: Optional[Callable[[], Any]] = None,
        repeats: int = REPEATS,
        rejections: int = REJECTIONS,
        stale_steps: int = STALE_STEPS,
        reviews: int = REVIEWS,
    ):
        self._chat = chat_fn
        self._window = window
        self._usage_fn = usage_fn
        self._repeats = max(2, int(repeats))
        self._rejections = max(1, int(rejections))
        self._stale = max(2, int(stale_steps))
        self._reviews = max(0, int(reviews))
        self._spent = 0
        #: Acts and steps, oldest first, for the whole turn — every
        #: sub-mission of a staged one included, because a plan that loops
        #: across its steps is exactly the pattern one sub-mission cannot
        #: see.
        self._acts: List[_Act] = []
        self._steps: List[_Step] = []
        self._open = _Step()
        self._started = False
        #: How many times each signal has been told it was a false alarm.
        #: Its threshold is multiplied by one more than this, so a pattern
        #: somebody has explained does not keep buying reviews.
        self._raised: Dict[str, int] = {}
        #: How many reviews each signal has been given back.  See
        #: :data:`REFUNDS_ON_PROGRESSING` and :data:`REVIEW_REFUNDS`.
        self._refunded: Dict[str, int] = {}
        #: Where the last review looked to, as ``(steps, acts)``.  Everything
        #: before it has been reviewed once and is not reviewed again: the
        #: next question is about what has happened SINCE.  Without this a
        #: nudge is asked for, delivered, and re-asked at the very next
        #: boundary, because the evidence that fired the signal is still
        #: sitting in the history — the note would never get a chance to
        #: work.
        self._floor: Tuple[int, int] = (0, 0)

    # ── being told what happened ────────────────────────────────────────

    def saw_call(self, tool: str, arguments: Any, result: str) -> None:
        """One dispatched call and what came back.

        Called by the runner after the dispatch, with the WHOLE result and
        not the bounded rendering: what makes a repetition a repetition is
        whether the bytes are the same, and two different 40 KB listings
        truncated to the same first 4 KB are not the same result.
        """
        try:
            shape = json.dumps(arguments, sort_keys=True, default=str)
        except Exception:                       # pragma: no cover - defensive
            shape = str(arguments)
        text = str(result or "")
        act = _Act(tool=str(tool or ""), call=_digest(f"{tool}\x00{shape}"),
                   result=_digest(text),
                   shown=f"{tool}({_short(shape)}) -> {_short(text)}")
        self._open.acts.append(act)
        self._acts.append(act)

    def saw_rejection(self) -> None:
        """The model's reply was not a decision this loop could act on."""
        self._open.rejections += 1

    # ── the two layers ──────────────────────────────────────────────────

    @property
    def reviews_left(self) -> int:
        return max(0, self._reviews - self._spent)

    def look(self, objective: str, *, ledger: Any = None) -> Optional[Review]:
        """Close the step that just ran; review it if a signal fires.

        ``None`` — the ordinary answer, on every boundary of every run that
        is getting somewhere — means the runner does nothing at all and the
        stream is byte for byte the stream it was before this existed.

        Called at the **step boundary**, which is the one place a note can
        be delivered without landing inside a decision the model has
        already made: it is where an operator's ``inject`` is applied, and
        a nudge is the same act by somebody else.
        """
        self._close()
        signal, count = self._signal()
        if signal is None:
            return None
        return self._review(objective, signal, count,
                            verdicts=(PROGRESSING, NUDGE, STUCK),
                            ledger=ledger)

    def review_gate(self, objective: str, *, goal: str, why: str,
                    ledger: Any = None) -> Review:
        """The staged path's step-level review: a gate said no.

        The one signal that is **reported** rather than noticed, because
        only the swarm knows what a plan step promised and whether what
        came back was it.  It is offered :data:`REPLAN` on top of the three
        — the fourth verdict exists for exactly this call site — and
        :data:`PROGRESSING` is offered too: a gate is itself a judgement,
        its mechanical half can be wrong about a step that did the work
        under a different name, and a reviewer that agrees with the step is
        the run's way of saying so.

        It shares the run's review budget, and when that is spent the
        verdict is :data:`STUCK` with no call made — a settled failure the
        plan carries on past, which is what a spent budget means for one
        step of a plan.
        """
        self._close()
        return self._review(
            objective, FAILED_GATE, 0,
            verdicts=(PROGRESSING, NUDGE, REPLAN, STUCK), ledger=ledger,
            extra=f"The plan step: {goal}\nWhat the gate said: {why}")

    # ── layer one: the mechanical signals ───────────────────────────────

    def _close(self) -> None:
        """Fold the observations of the step that just ran into the history.

        A step that neither dispatched anything nor was rejected is still a
        step and is still remembered — those are the steps
        :data:`NO_NEW_EVIDENCE` is about — but nothing is remembered before
        the run's first act, so a boundary reached before anything has
        happened (the first one, always) does not count as a stale step.
        """
        if not self._started and self._open.empty:
            return
        self._started = True
        self._steps.append(self._open)
        self._open = _Step()

    def _threshold(self, signal: str, base: int) -> int:
        """*base*, raised once per :data:`PROGRESSING` verdict on *signal*."""
        return base * (1 + self._raised.get(signal, 0))

    def _signal(self) -> Tuple[Optional[str], int]:
        """``(signal, n)`` for the first pattern that fires, else ``(None, 0)``.

        Order is deliberate and it is specificity order: a run repeating one
        call trips :data:`REPEATED_CALL` and is reviewed with that sentence,
        rather than tripping the general stall a step later and being asked
        a vaguer question about the same thing.

        Everything is read from :attr:`_floor` forward — the acts and steps
        since the last review — so one pattern buys one review.
        """
        steps = self._steps[self._floor[0]:]
        acts = self._acts[self._floor[1]:]

        n = self._threshold(REPEATED_CALL, self._repeats)
        if len(acts) >= n:
            # The same ACT — tool, arguments and the bytes that came back —
            # counted over a window rather than run-length encoded. See
            # `REPEATS` for the live run that made the difference.
            window = acts[-(n * REPEAT_WINDOW):]
            seen: Dict[Tuple[str, str], int] = {}
            for act in window:
                key = (act.call, act.result)
                seen[key] = seen.get(key, 0) + 1
            if max(seen.values()) >= n:
                return REPEATED_CALL, n

        n = self._threshold(REJECTED_REPLIES, self._rejections)
        if len(steps) >= n:
            recent = steps[-n:]
            if all(step.rejections and not step.acts for step in recent):
                return REJECTED_REPLIES, n

        n = self._threshold(OSCILLATION, OSCILLATES)
        if len(acts) >= n and n % 2 == 0:
            tail = acts[-n:]
            first, second = tail[0].call, tail[1].call
            if first != second and all(
                    act.call == (first if index % 2 == 0 else second)
                    for index, act in enumerate(tail)):
                return OSCILLATION, n

        n = self._threshold(NO_NEW_EVIDENCE, self._stale)
        if len(steps) >= n:
            # "New" is measured against everything the RUN has seen, not
            # only against this window: a step that reads r1 again on the
            # fifth turn has produced nothing new even though nothing in
            # the last four steps read it.
            seen = {digest for step in self._steps[:len(self._steps) - n]
                    for act in step.acts
                    for digest in (act.call, act.result)}
            # `or`, not `and`. An act is new evidence if EITHER half of it
            # is new: a call the run has not made before, or a result it has
            # not seen before. `and` demanded both, which quietly made this
            # signal fire on two of the healthiest shapes a run has — a
            # polling loop (the same call, a new result every step: a job
            # status, a test suite after each edit) and an edit loop (a new
            # call every step, the same short "written 120 bytes" back). An
            # act whose call AND result are both familiar is a repetition,
            # and a repetition is what `REPEATED_CALL` above is for. Read
            # the other way round it is the sentence this signal has always
            # been described by, in `SIGNALS` and in PLATFORMS.md: it fires
            # on steps with no new call AND no result the run had not
            # already seen — both absent, which is what `not (a or b)` says.
            fresh = [act for step in steps[-n:] for act in step.acts
                     if act.call not in seen or act.result not in seen]
            if not fresh:
                return NO_NEW_EVIDENCE, n
        return None, 0

    # ── layer two: the review turn ──────────────────────────────────────

    def _review(self, objective: str, signal: str, count: int, *,
                verdicts: Sequence[str], ledger: Any = None,
                extra: str = "") -> Review:
        """Spend one review, or answer with the arithmetic when there is none.

        The budget is checked BEFORE the call and the verdict when it is
        spent is :data:`STUCK`, which is the endless-loop catch itself: a
        run whose pattern survived every review it was allowed does not get
        a fourth opinion, it gets wound up.
        """
        if self.reviews_left <= 0:
            self._move_floor()
            return Review(signal=signal, verdict=STUCK, note=OUT_OF_REVIEWS,
                          reviews_left=0, count=count)
        self._spent += 1
        left = self.reviews_left
        refundable = (signal in REFUNDS_ON_PROGRESSING
                      and self._refunded.get(signal, 0) < REVIEW_REFUNDS)
        # On the LAST review `progressing` is not on the menu, and that is
        # the other half of the catch: a model asked "are you looping?"
        # three times and answering "no" three times has answered the
        # question. The prompt and the parser are narrowed together, so the
        # word is neither offered nor accepted.
        allowed = tuple(word for word in verdicts
                        if word != PROGRESSING or left > 0 or refundable)
        verdict, note, asked = self._ask(objective, signal, count, allowed,
                                         extra, ledger)
        if verdict == PROGRESSING and asked:
            self._raised[signal] = self._raised.get(signal, 0) + 1
            if refundable:
                # See REFUNDS_ON_PROGRESSING: a false alarm about an
                # absence costs the threshold, not the budget.
                self._spent -= 1
                self._refunded[signal] = self._refunded.get(signal, 0) + 1
                left = self.reviews_left
        self._move_floor()
        return Review(signal=signal, verdict=verdict, note=note,
                      reviews_left=left, count=count)

    def _move_floor(self) -> None:
        """Everything reviewed once is not reviewed again."""
        self._floor = (len(self._steps), len(self._acts))

    def _ask(self, objective: str, signal: str, count: int,
             allowed: Sequence[str], extra: str,
             ledger: Any) -> Tuple[str, str, bool]:
        """``(verdict, note, asked)`` — the model's, or the safe default.

        *asked* is ``False`` when the endpoint could not be reached or the
        reply could not be read, and then the verdict is
        :data:`PROGRESSING`: a review that did not happen must not end a
        mission, and it must not raise a threshold either — nobody said the
        pattern was fine.  The review is still **spent**, so a run whose
        endpoint is failing every review still winds up after
        :data:`REVIEWS` of them rather than looping on broken calls.
        """
        messages = [
            {"role": "system", "content": self._prompt(allowed)},
            {"role": "user", "content": self._rendering(
                objective, signal, count, extra)},
        ]
        try:
            reply = self._chat(self._fit(messages))
        except Exception:                       # pragma: no cover - defensive
            return PROGRESSING, "", False
        self._meter(ledger)
        verdict, note = _read_verdict(reply)
        if verdict in allowed:
            return verdict, note, True
        if verdict in VERDICTS:
            # A word this review was not offered — `progressing` on the
            # last one, or `replan` from a direct mission that has no plan.
            # Read as the nearest thing the caller can act on rather than
            # as nothing, because a verdict dropped on the floor is a
            # review spent for nothing.
            return STUCK, note, True
        return PROGRESSING, "", False

    def _meter(self, ledger: Any) -> None:
        """Fold what the review cost into the run's ledger.  Never raises.

        A review is a model call and the run pays for it, so it goes on the
        same :class:`~core.runtime.usage.Ledger` the steps do and reaches
        the wire in ``mission_finished.usage`` like everything else.  Never
        raises, for the reason ``_spent`` in the mission loop does not: a
        usage side channel that throws must not be able to end a run.
        """
        if ledger is None or self._usage_fn is None:
            return
        try:
            ledger.add(self._usage_fn())
        except Exception:                       # pragma: no cover - defensive
            pass

    def _fit(self, messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
        if self._window is None:
            return messages
        try:
            kept, _ = self._window.fit(messages, pinned=1)
        except Exception:                       # pragma: no cover - defensive
            return messages
        return kept

    @staticmethod
    def _prompt(allowed: Sequence[str]) -> str:
        """The system turn, offering exactly the verdicts this review takes."""
        return REVIEW_PROMPT + "\n".join(
            f"- {VERDICT_LINES[word]}" for word in allowed
            if word in VERDICT_LINES)

    def _rendering(self, objective: str, signal: str, count: int,
                   extra: str = "") -> str:
        """What the run has done, compactly, and what tripped the watcher."""
        lines: List[str] = [f"The mission's objective:\n{objective}"]
        if extra:
            lines.append(extra)
        acts = self._acts[-WINDOW_ACTS:]
        if acts:
            body = "\n".join(f"- {act.shown}" for act in acts)
            lines.append(f"What it has called, oldest first:\n{body}")
        else:
            lines.append("It has not successfully called a tool at all.")
        rejected = sum(step.rejections for step in self._steps)
        if rejected:
            lines.append(f"Replies rejected by the harness so far: {rejected}")
        lines.append(f"The pattern that triggered this review: "
                     f"{describe(signal, count)}")
        return "\n\n".join(lines)
