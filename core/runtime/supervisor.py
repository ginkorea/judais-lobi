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

   One of them is not procedural.  :data:`FROZEN_FRONTIER` watches
   **epistemic** progress — the frontier, the contradictions and the
   store, as :meth:`core.runtime.cognition.ShadowCognition.progress`
   reads them — and it is ROADMAP §2.9.6's ask: *frontier unchanged, no
   predicate resolved, no contradiction reduced* is a stall the other
   four cannot see, because a run can be calling new tools and getting
   new results and establishing nothing that any goal wanted.  It is
   active **only where cognition is on**, which is a run that asked for
   it, and a run without it is reviewed exactly as it always was.
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

That arithmetic belongs to the signals that are about *what the run
did*.  A signal in :data:`NEVER_WINDS_UP` is outside it in both
directions — it is never offered :data:`STUCK`, and when the budget is
spent it produces no review at all rather than the wind-up the
arithmetic makes.

**One supervisor per turn.**  A staged (``--swarm``) turn hands the same
object to every sub-mission it builds and to its own step-level gate
review, so a plan that loops *across* its steps is a pattern this sees —
and so the review budget is the turn's, not five copies of it.

**And cognition steers with the same voice as everything else.**  The
epistemic signal raises the review this module already raises and
nothing more: no new verdict, no new record, no field on the wire, and
**no path to an ending at all** — see :data:`NEVER_WINDS_UP`, which is
that claim made true by construction rather than by argument.  The
owner's ruling of 13 September 2026 is the floor — the cognitive layer
is shadow and additive, it emits state and guidance, it never gates —
and the way that is kept true here is by giving it no machinery of its
own to gate with.

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
    "FAILED_GATE", "FROZEN_FRONTIER", "SIGNALS", "PROGRESSING", "NUDGE",
    "STUCK", "REPLAN",
    "VERDICTS", "VERDICT_LINES", "REPEATS", "REJECTIONS", "STALE_STEPS",
    "FROZEN_STEPS", "BELIEFS_PER_STEP",
    "REVIEWS", "REFUNDS_ON_PROGRESSING", "REVIEW_REFUNDS", "NEVER_WINDS_UP",
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
#: The run's **belief** has stopped moving: the same thing is owed, nothing
#: has been settled, nothing has been learned.  Cognition's, and the only
#: signal that is not about what the run *did*.
FROZEN_FRONTIER = "frozen_frontier"

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
    FROZEN_FRONTIER: (
        "the frontier — what this run's goals still require — has not moved "
        "in {n} steps: nothing on it has been resolved, no disagreement has "
        "been settled, and almost nothing new has been established{detail}"),
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

#: How many consecutive steps of frozen belief are a :data:`FROZEN_FRONTIER`.
#: **Five**, and the number is chosen against :data:`STALE_STEPS` rather
#: than in the abstract.
#:
#: One more than the stale-steps threshold, exactly as :data:`STALE_STEPS`
#: is one more than :data:`REPEATS`, and the reason is the same specificity
#: argument: where both are ready at one boundary the run should be asked
#: the concrete question — no new call, no new result — because that is the
#: more actionable sentence, and :meth:`Supervisor._signal` reads in that
#: order.  The gap keeps the two from arriving together on the ordinary
#: shape rather than guaranteeing it: :data:`NO_NEW_EVIDENCE` measures its
#: window against everything *before* it, so a run that repeats itself from
#: its very first step needs a few steps of history before it can fire at
#: all, and this signal may reach a stall of that shape first.  That is
#: not a defect — the review it raises names the frontier and quotes what
#: is owed, which is at least as answerable as "nothing new came back".
#:
#: What is left for this signal alone is the case nothing else can see:
#: **receipts arriving every step and the belief not moving**.  That run
#: reads as healthy to all four of the mechanical signals — new calls, new
#: results, no alternation — and ROADMAP §2.9.6 names it as this arc's
#: largest expected gain.
#:
#: Five steps and not three because this is an *absence*, and the absence
#: has a legitimate shape: a run reading the three receipts it needs before
#: any of them satisfies a premise moves nothing for as long as it is
#: reading.  See :data:`REFUNDS_ON_PROGRESSING`, which this signal joins for
#: the same reason.
FROZEN_STEPS = 5

#: How much the store may grow per step and still be standing still.  One:
#: a run that is learning establishes at least one thing a step, and below
#: that the store is noise around a flat line.  The window's own length is
#: the multiplier, so the rule reads "fewer new propositions than steps"
#: and has no second number in it.
#:
#: It is here because a run *can* harvest steadily while the frontier stays
#: frozen — twenty fields off a receipt that answers none of the goals —
#: and the owner's rule is that a working harness beats a strict one: an
#: absence claimed over a store that is visibly filling up is a claim the
#: run can disprove.
BELIEFS_PER_STEP = 1

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
#:
#: :data:`FROZEN_FRONTIER` is the second member and it is here for the same
#: argument plus one of its own.  It is an absence — belief that has not
#: moved — and it is **cognition's**, and the owner's ruling of 13 September
#: 2026 is the floor under this whole layer: the cognitive layer is shadow
#: and additive, it emits state and guidance, it never gates.  A signal that
#: could spend a run's review budget down to a forced wind-up would be
#: cognition deciding a mission's length, which is the one thing it may not
#: do.  Refunded, it can raise its own threshold and say what it sees, and
#: the arithmetic that ends runs stays the property of demonstrated
#: repetition.
REFUNDS_ON_PROGRESSING: frozenset = frozenset({NO_NEW_EVIDENCE,
                                               FROZEN_FRONTIER})

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

#: The signals that may **never end a run**.  One member, and it is the
#: cognitive one.
#:
#: A refund was not enough, and the review that found that out is the
#: reason this constant exists rather than an argument in a docstring.
#: :data:`REFUNDS_ON_PROGRESSING` protects a run whose reviewer keeps
#: saying ``progressing`` — and only that run.  Two other paths ended a
#: procedurally healthy mission on the strength of a frozen frontier
#: alone: a reviewer that answered ``stuck`` on the first firing, and
#: :data:`REVIEWS` spent on this signal's own nudges, after which
#: :meth:`Supervisor._review` made the wind-up verdict by arithmetic with
#: no call at all.  Both ended a cognition-**on** run that a cognition-off
#: run would have answered, which is the one thing ROADMAP §2.9.3's floor
#: rule forbids: *the cognitive layer is shadow and additive — it emits
#: state and guidance, and never gates*.
#:
#: So the exemption is structural and is read in two places, which is what
#: makes it true by construction rather than by care:
#:
#: * :meth:`Supervisor.look` does not offer :data:`STUCK` for such a
#:   signal — the word is neither in the prompt nor accepted by the parser
#:   (:meth:`Supervisor._ask` reads an unoffered word as the nearest one
#:   this review *may* return), so no reviewer can say it into being;
#: * :meth:`Supervisor._review` answers ``None`` — no review, no record,
#:   nothing said to the model — where it would otherwise make the
#:   out-of-reviews :data:`STUCK`.
#:
#: What such a signal still does is **spend** a review when it raises one,
#: because a review is a model call and an unpaid one is an unbounded one:
#: a nudge does not raise a threshold, so a signal that fired for free
#: could fire every :data:`FROZEN_STEPS` steps forever.  The residual is
#: stated rather than hidden: a run whose reviews went on frozen-frontier
#: nudges meets a later *procedural* signal with fewer left.  That ending
#: is still demonstrated repetition's, made by the arithmetic that has
#: always owned it — what cognition cannot do is be the ending itself.
NEVER_WINDS_UP: frozenset = frozenset({FROZEN_FRONTIER})

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


def describe(signal: str, n: int = 0, detail: str = "") -> str:
    """The sentence for *signal*, with its number and its quote in it.

    ``{n}`` and ``{detail}`` are filled where the row has them and left
    alone where it does not, so a row may be written with either, both or
    neither and no spelling needs a branch at the call site.

    *detail* is the one thing a row cannot state for itself: what the
    pattern was *about*.  :data:`FROZEN_FRONTIER` uses it to quote the top
    of the frontier that has not moved — the same line
    :func:`core.cognition.compile.owed_line` put in front of the model —
    because "the frontier has not moved" is a sentence a model can neither
    check nor act on, and "still owed: (alice, payment_link, ?c)" is both.
    """
    sentence = SIGNALS.get(signal, signal)
    try:
        return sentence.format(n=n, detail=detail)
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
    #: What the pattern was about, where the signal's row has somewhere to
    #: put it — :data:`FROZEN_FRONTIER` quotes the top owed line here.  Off
    #: the wire for :attr:`count`'s reason and one more: it is prose out of
    #: the kernel, and a consumer rendering it would be rendering the
    #: cognitive layer's internals as though they were contract.
    detail: str = ""

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
        return describe(self.signal, self.count, self.detail)


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
    #: What the run believed at this step's boundary — a
    #: :class:`core.runtime.cognition.Progress`, or ``None`` when cognition
    #: is off, stopped, or could not be read.  Duck-typed, like every other
    #: cognitive thing the runtime holds: this module reads four attributes
    #: off it and does not import the class.
    progress: Any = None

    @property
    def empty(self) -> bool:
        return not self.acts and not self.rejections


#: What a step's epistemic reading has to carry to be compared at all —
#: the four fields :meth:`Supervisor._frozen_frontier` reads, named once
#: because they are read twice (asked for, then compared).
#:
#: **Every attribute this module reads off a reading is optional**, and
#: that is one rule and not two: readings are duck-typed here exactly as
#: the shadow that produces them is, so a stand-in missing a field turns
#: the signal off rather than raising out of a step boundary.  The check
#: is made once, here, and the comparison below then reads the four
#: plainly; the fifth, ``owed``, is a quote rather than a comparison and
#: :meth:`Supervisor._still_owed` treats its absence as nothing to quote.
READING: Tuple[str, ...] = ("frontier", "obligations", "contradictions",
                            "propositions")


def _complete(reading: Any) -> bool:
    """Whether *reading* is a reading this module can compare.

    ``None`` — cognition off, stopped, or a frontier that could not be
    read — is the ordinary answer and is not complete.  So is an object
    that has some of :data:`READING` and not the rest: the honest reading
    of a shape this module does not recognise is *no reading*.
    """
    return reading is not None and all(hasattr(reading, name)
                                       for name in READING)


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
    repeats, rejections, stale_steps, reviews, frozen_steps:
        The five numbers above (:data:`REPEATS`, :data:`REJECTIONS`,
        :data:`STALE_STEPS`, :data:`REVIEWS`,
        :data:`FROZEN_STEPS`).  Parameters so a test can
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
        frozen_steps: int = FROZEN_STEPS,
    ):
        self._chat = chat_fn
        self._window = window
        self._usage_fn = usage_fn
        self._repeats = max(2, int(repeats))
        self._rejections = max(1, int(rejections))
        self._stale = max(2, int(stale_steps))
        self._frozen = max(2, int(frozen_steps))
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

    def look(self, objective: str, *, ledger: Any = None,
             progress: Any = None) -> Optional[Review]:
        """Close the step that just ran; review it if a signal fires.

        ``None`` — the ordinary answer, on every boundary of every run that
        is getting somewhere — means the runner does nothing at all and the
        stream is byte for byte the stream it was before this existed.

        Called at the **step boundary**, which is the one place a note can
        be delivered without landing inside a decision the model has
        already made: it is where an operator's ``inject`` is applied, and
        a nudge is the same act by somebody else.

        *progress* is the step's epistemic reading — whatever
        :meth:`core.runtime.cognition.ShadowCognition.progress` gave the
        runner, and ``None`` on every run with cognition off, which is
        every run today that did not ask for it.  It arrives **here**
        rather than through a second ``saw_…`` call because it is a fact
        about the step as a whole rather than about an act in it, and
        because this is the boundary that closes the step it belongs to: a
        reading taken at any other moment would be a different step's.
        """
        self._open.progress = progress
        self._close()
        signal, count, detail = self._signal()
        if signal is None:
            return None
        # The menu is the signal's, and the one thing it decides is whether
        # this review may end the run. See NEVER_WINDS_UP: a word that is
        # not offered is not in the prompt and is not accepted back, so the
        # exemption is a property of the shape rather than of a check
        # somewhere downstream.
        verdicts = ((PROGRESSING, NUDGE) if signal in NEVER_WINDS_UP
                    else (PROGRESSING, NUDGE, STUCK))
        return self._review(objective, signal, count, verdicts=verdicts,
                            ledger=ledger, detail=detail)

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
        step of a plan.  Always a :class:`Review` and never ``None``:
        :data:`FAILED_GATE` is not in :data:`NEVER_WINDS_UP`, which is the
        one signal class :meth:`_review` can answer nothing to, and a gate
        that reported a failure is owed an answer either way.
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

    def _signal(self) -> Tuple[Optional[str], int, str]:
        """``(signal, n, detail)`` for the first pattern that fires.

        ``(None, 0, "")`` when nothing does, which is the ordinary answer.

        Order is deliberate and it is specificity order: a run repeating one
        call trips :data:`REPEATED_CALL` and is reviewed with that sentence,
        rather than tripping the general stall a step later and being asked
        a vaguer question about the same thing.  :data:`FROZEN_FRONTIER` is
        **last** for the same reason and one more: it is the only signal
        that can fire on a run whose acts all look healthy, so anything the
        four procedural signals can see should be asked about as the
        procedural thing it is.

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
                return REPEATED_CALL, n, ""

        n = self._threshold(REJECTED_REPLIES, self._rejections)
        if len(steps) >= n:
            recent = steps[-n:]
            if all(step.rejections and not step.acts for step in recent):
                return REJECTED_REPLIES, n, ""

        n = self._threshold(OSCILLATION, OSCILLATES)
        if len(acts) >= n and n % 2 == 0:
            tail = acts[-n:]
            first, second = tail[0].call, tail[1].call
            if first != second and all(
                    act.call == (first if index % 2 == 0 else second)
                    for index, act in enumerate(tail)):
                return OSCILLATION, n, ""

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
                return NO_NEW_EVIDENCE, n, ""

        n = self._threshold(FROZEN_FRONTIER, self._frozen)
        if len(steps) >= n:
            window = [step.progress for step in steps[-n:]]
            if self._frozen_frontier(window):
                return FROZEN_FRONTIER, n, self._still_owed(window[-1])
        return None, 0, ""

    @staticmethod
    def _frozen_frontier(window: Sequence[Any]) -> bool:
        """Whether *window* is N steps of belief that did not move.

        Three conditions, and they are ROADMAP §2.9.6's three read in the
        order they can be checked cheaply:

        * **the frontier is the same** at every step in the window — the
          same obligations, in the same states, in the same order.  One
          premise satisfied renames an obligation (its id is
          content-addressed on the pattern as resolved so far), so this is
          also "no predicate resolved";
        * **no contradiction was reduced** — pairwise, step against the one
          before it, not endpoint against endpoint: a disagreement settled
          and another found is a run that did something, and comparing only
          the ends would call that standing still.  What pairwise cannot
          see is a settlement and a discovery **inside one step**: two
          readings a step apart showing the same count, one contradiction
          shorter and one longer, are indistinguishable from a step that
          did nothing, and this signal will call that frozen.  It is the
          price of reading a digest instead of the store, it is bounded by
          what the signal can do — one advisory review, which a run that
          did settle something can answer ``progressing`` — and it is
          written here rather than left for somebody to find;
        * **almost nothing new was believed** — fewer new propositions than
          there are steps of *work* in the window, which is one fewer than
          there are readings in it: N readings are taken at N boundaries
          and N-1 steps happened between them.  See
          :data:`BELIEFS_PER_STEP`.

        A step with no usable reading — cognition off, stopped, a frontier
        that could not be read, or a stand-in that does not carry
        :data:`READING` — makes the window unusable and the answer is
        ``False``: this signal is **only** ever raised on evidence, and a
        run whose shadow went quiet is a run this has nothing to say about.
        That is also the whole of the failure isolation, written as a
        condition rather than a ``try``.

        An **empty** frontier is not frozen, it is absent.  A run with no
        goals loaded — every run today that has not been given a rule pack —
        has the same empty frontier at every step forever, and a signal that
        read that as a stall would review every cognition-on mission in the
        world for standing still at nothing.
        """
        if any(not _complete(reading) for reading in window):
            return False
        first, last = window[0], window[-1]
        if not first.obligations:
            return False
        if any(reading.frontier != first.frontier for reading in window):
            return False
        if any(later.contradictions < earlier.contradictions
               for earlier, later in zip(window, window[1:])):
            return False
        return (last.propositions - first.propositions
                < BELIEFS_PER_STEP * (len(window) - 1))

    @staticmethod
    def _still_owed(reading: Any) -> str:
        """The quote the review's sentence ends with, or ``""``.

        The top of the frontier as the compiled block renders it, so the
        model reads the same words twice rather than two spellings of one
        obligation.

        ``owed`` is deliberately not in :data:`READING`: it is a quote and
        not a comparison, a reading that has none is a perfectly good
        reading, and the sentence simply ends earlier.  The attribute is
        read the same optional way every other one in this module is — see
        :data:`READING` for the single rule both places obey.
        """
        owed = str(getattr(reading, "owed", "") or "")
        return f"; still {owed}" if owed else ""

    # ── layer two: the review turn ──────────────────────────────────────

    def _review(self, objective: str, signal: str, count: int, *,
                verdicts: Sequence[str], ledger: Any = None,
                extra: str = "", detail: str = "") -> Optional[Review]:
        """Spend one review, or answer with the arithmetic when there is none.

        The budget is checked BEFORE the call and the verdict when it is
        spent is :data:`STUCK`, which is the endless-loop catch itself: a
        run whose pattern survived every review it was allowed does not get
        a fourth opinion, it gets wound up.

        ``None`` for a signal in :data:`NEVER_WINDS_UP` with the budget
        spent — the one case where nothing is said at all.  The wind-up is
        the only thing an out-of-reviews answer *is*, and a signal that may
        not end a run has nothing to make here: no call, no verdict, no
        ``review`` on the record.  The caller reads it exactly as it reads
        the ordinary boundary where no signal fired.
        """
        if self.reviews_left <= 0:
            self._move_floor()
            if signal in NEVER_WINDS_UP:
                return None
            return Review(signal=signal, verdict=STUCK, note=OUT_OF_REVIEWS,
                          reviews_left=0, count=count, detail=detail)
        self._spent += 1
        left = self.reviews_left
        refundable = (signal in REFUNDS_ON_PROGRESSING
                      and self._refunded.get(signal, 0) < REVIEW_REFUNDS)
        # On the LAST review `progressing` is not on the menu, and that is
        # the other half of the catch: a model asked "are you looping?"
        # three times and answering "no" three times has answered the
        # question. The prompt and the parser are narrowed together, so the
        # word is neither offered nor accepted.
        #
        # Except where the catch does not apply. Narrowing the menu exists
        # to force the wind-up, and a NEVER_WINDS_UP signal has none to
        # force: dropping the word there would only mean reading an honest
        # `progressing` as something else on the record.
        allowed = tuple(word for word in verdicts
                        if word != PROGRESSING or left > 0 or refundable
                        or signal in NEVER_WINDS_UP)
        verdict, note, asked = self._ask(objective, signal, count, allowed,
                                         extra, ledger, detail)
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
                      reviews_left=left, count=count, detail=detail)

    def _move_floor(self) -> None:
        """Everything reviewed once is not reviewed again."""
        self._floor = (len(self._steps), len(self._acts))

    def _ask(self, objective: str, signal: str, count: int,
             allowed: Sequence[str], extra: str,
             ledger: Any, detail: str = "") -> Tuple[str, str, bool]:
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
                objective, signal, count, extra, detail)},
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
            #
            # The nearest thing among the words this review MAY return,
            # and not `stuck` unconditionally: for a NEVER_WINDS_UP signal
            # that word is not on the menu precisely so that no reviewer
            # can end the run with it, and reading it back in here is the
            # same ending through the parser. What is left is `nudge` —
            # the model's note still reaches the run, and a nudge with no
            # note says nothing at all.
            return (STUCK if STUCK in allowed else NUDGE), note, True
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
                   extra: str = "", detail: str = "") -> str:
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
                     f"{describe(signal, count, detail)}")
        return "\n\n".join(lines)
