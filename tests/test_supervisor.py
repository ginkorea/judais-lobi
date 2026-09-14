# tests/test_supervisor.py — the watcher that replaced the step budget

"""Two layers, tested as two layers.

The mechanical half must fire on a repetition and, much more importantly,
must NOT fire on work: every signal here has a twin test in which the same
shape of activity is progress and nothing happens.  A watcher that cried
wolf would spend a run's review budget on the first mission that read a
listing twice, and the third review would then wind up a run that was
fine — which is a worse failure than the endless loop this exists to
catch, because it is silent and it looks like an answer.

The review half is tested against a scripted model for the reason every
other model in this suite is scripted: a verdict is a decision the run
acts on, and a decision that can only be exercised by paying an endpoint
is a decision nobody exercises.
"""

import json

import pytest

from core.runtime.cognition import Progress
from core.runtime.supervisor import (
    BELIEFS_PER_STEP, FAILED_GATE, FROZEN_FRONTIER, FROZEN_STEPS,
    NEVER_WINDS_UP, NO_NEW_EVIDENCE, NUDGE, OSCILLATION, PROGRESSING,
    REFUNDS_ON_PROGRESSING, REJECTED_REPLIES, REPEATED_CALL, REPLAN,
    REVIEW_REFUNDS, REVIEWS, SIGNALS, STALE_STEPS, STUCK,
    VERDICTS, Review, Supervisor,
)


class ScriptedReviewer:
    """Replays canned verdicts and records what it was shown."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.seen = []

    def __call__(self, messages):
        self.seen.append([dict(m) for m in messages])
        return self.replies.pop(0) if self.replies else verdict(PROGRESSING)

    @property
    def calls(self):
        return len(self.seen)


def verdict(word, note=""):
    return json.dumps({"verdict": word, "note": note})


def watching(*replies, **kw):
    """A supervisor over a scripted reviewer: ``(supervisor, reviewer)``."""
    reviewer = ScriptedReviewer(*replies)
    return Supervisor(reviewer, **kw), reviewer


def step(sup, *acts, rejections=0, progress=None):
    """One step's worth of observations, then the boundary that closes it.

    The boundary is where a review happens, so a test that wants three
    steps' worth of pattern calls this three times and reads the verdict
    off the last one — which is exactly the order the loop does it in.

    *progress* is the step's epistemic reading, as the runner hands it over
    — ``None`` on every run with cognition off, which is every test in this
    file but one section.
    """
    for tool, arguments, result in acts:
        sup.saw_call(tool, arguments, result)
    for _ in range(rejections):
        sup.saw_rejection()
    return sup.look("find the actor at the top of run r-7", progress=progress)


READ = ("governed_read", {"asset_id": "a.1"}, "asset a.1: results only")


# ── the table is data ────────────────────────────────────────────────────────


class TestTheSignalsAreATable:
    def test_every_signal_has_a_sentence(self):
        """The sentence is what the reviewing model is shown, so a signal
        with no row is a review that asks about nothing."""
        for name, sentence in SIGNALS.items():
            assert sentence and isinstance(sentence, str), name

    def test_the_verdicts_are_a_closed_set(self):
        assert VERDICTS == (PROGRESSING, NUDGE, STUCK, REPLAN)

    def test_a_review_record_omits_an_empty_note(self):
        """Absent rather than empty, like every optional thing on this
        stream: a field states a fact only when there is one to state."""
        assert Review(signal=REPEATED_CALL, verdict=PROGRESSING,
                      reviews_left=2).as_record() == {
            "signal": "repeated_call", "verdict": "progressing",
            "reviews_left": 2}
        assert Review(signal=REPEATED_CALL, verdict=NUDGE, note="try r-9",
                      reviews_left=1).as_record()["note"] == "try r-9"


# ── layer one: the mechanical signals ────────────────────────────────────────


class TestTheSameCallReturningTheSameThing:
    def test_three_identical_acts_with_work_between_them_are_a_signal(self):
        """Not "in a row", and that is what the live run of 17 August
        taught: a model polling a view for something that will never appear
        reads the view, reads a field out of the stored result, reads the
        view again, tries another path, reads the view a third time. Three
        identical calls with productive-looking reads threaded between them
        is the same stall, and a detector that wanted them consecutive
        watched exactly that run go round and said nothing."""
        sup, reviewer = watching(verdict(NUDGE, "it is not coming"))
        other = ("mission_result", {"handle": "r1", "path": "x"}, "no such")
        assert step(sup, READ) is None
        assert step(sup, other) is None
        assert step(sup, READ) is None
        assert step(sup, ("mission_result", {"handle": "r1", "path": "y"},
                          "nope")) is None
        review = step(sup, READ)
        assert review is not None and review.signal == REPEATED_CALL
        assert reviewer.calls == 1

    def test_three_identical_acts_are_a_signal(self):
        sup, reviewer = watching(verdict(NUDGE, "read something else"))
        assert step(sup, READ) is None
        assert step(sup, READ) is None
        review = step(sup, READ)
        assert review is not None
        assert review.signal == REPEATED_CALL
        assert reviewer.calls == 1

    def test_two_are_not(self):
        """A model re-reading a listing before it quotes it is an ordinary
        thing, and a watcher that reviewed it would spend a run's budget on
        the first careful mission it met."""
        sup, reviewer = watching()
        assert step(sup, READ) is None
        assert step(sup, READ) is None
        assert reviewer.calls == 0

    def test_three_spread_across_a_long_working_run_are_not(self):
        """The window is what keeps a re-read a re-read. Three identical
        reads with five other things between them are three careful reads,
        and the run that is actually stalled trips `no_new_evidence`
        instead — a different question with a different sentence."""
        sup, reviewer = watching()
        for index in range(9):
            act = (READ if index % 4 == 0 else
                   ("governed_view", {"run": f"r-{index}"}, f"view {index}"))
            assert step(sup, act) is None
        assert reviewer.calls == 0

    def test_a_different_result_is_progress(self):
        """The whole discipline of the table: the same call returning
        something NEW is a paging loop doing its job."""
        sup, reviewer = watching()
        for page in range(4):
            assert step(sup, ("page", {"n": 1}, f"page {page}")) is None
        assert reviewer.calls == 0

    def test_a_different_argument_is_progress(self):
        sup, reviewer = watching()
        for asset in ("a.1", "a.2", "a.3", "a.4"):
            assert step(sup, ("governed_read", {"asset_id": asset},
                              "results only")) is None
        assert reviewer.calls == 0

    def test_three_in_one_step_are_a_signal_too(self):
        """A native turn dispatches several calls in one model turn, and
        three identical ones inside a turn are the same repetition as three
        across three turns."""
        sup, _reviewer = watching(verdict(STUCK))
        review = step(sup, READ, READ, READ)
        assert review is not None and review.signal == REPEATED_CALL


class TestRepliesThatAreNotDecisions:
    def test_three_rejections_running_are_a_signal(self):
        sup, _reviewer = watching(verdict(NUDGE, "reply with one object"))
        assert step(sup, rejections=1) is None
        assert step(sup, rejections=1) is None
        review = step(sup, rejections=1)
        assert review is not None and review.signal == REJECTED_REPLIES

    def test_a_step_that_did_something_breaks_the_run(self):
        """"In a row" is the whole claim: this loop hands back a correction
        precisely so the next reply is right, and a run that recovers has
        not stopped being a run that recovered."""
        sup, reviewer = watching()
        assert step(sup, rejections=1) is None
        assert step(sup, READ) is None
        assert step(sup, rejections=1) is None
        assert step(sup, rejections=1) is None
        assert reviewer.calls == 0


class TestStepsThatProduceNothingNew:
    #: Three known reads, cycled. Three because two would alternate, and
    #: alternating is a signal of its own — the specificity order in
    #: `_signal` means a run going A B A B is asked the A-B-A-B question
    #: rather than the vaguer one.
    KNOWN = [("governed_read", {"asset_id": f"a.{n}"}, f"result {n}")
             for n in range(3)]

    def test_four_steps_of_nothing_new_are_a_signal(self):
        sup, _reviewer = watching(verdict(NUDGE, "you already have this"))
        for act in self.KNOWN:
            assert step(sup, act) is None
        # Four steps that read only what the run already has. Nothing is
        # identical three times running and nothing alternates, so this is
        # neither `repeated_call` nor `oscillation`.
        review = None
        for index in range(4):
            review = step(sup, self.KNOWN[index % 3])
        assert review is not None and review.signal == NO_NEW_EVIDENCE

    def test_one_new_result_in_the_window_is_progress(self):
        """A run that keeps finding things it has not seen is a run that is
        working, however long it goes on for."""
        sup, reviewer = watching()
        for index in range(8):
            assert step(sup, ("governed_read", {"asset_id": f"a.{index}"},
                              f"result {index}")) is None
        assert reviewer.calls == 0


class TestEitherHalfOfAnActIsEvidence:
    """New call **or** new result. Not both, and the difference is two of
    the healthiest shapes a run has.

    The detector once demanded that an act be new in *both* halves before
    it counted as evidence, which quietly made ``no_new_evidence`` fire on a
    polling loop (the same call, a new result every step — a job status, a
    test suite after each edit) and on an edit loop (a new call every step,
    the same "written 120 bytes" back). Both are runs that are getting
    somewhere; a run whose call AND result are both familiar is repeating
    itself, and that is what ``repeated_call`` is for.
    """

    def test_a_polling_loop_with_a_new_result_each_step_is_progress(self):
        """The same call, a new result every time — thirty steps of it."""
        sup, reviewer = watching()
        for index in range(30):
            assert step(sup, ("job.status", {"id": 7},
                              f"running {index}%")) is None
        assert reviewer.calls == 0

    def test_an_edit_loop_with_a_new_call_each_step_is_progress(self):
        """A new call every time, the same short acknowledgement back."""
        sup, reviewer = watching()
        for index in range(30):
            assert step(sup, ("fs", {"action": "write", "path": "x.py",
                                     "content": f"v{index}"},
                              "Written 12 bytes to x.py")) is None
        assert reviewer.calls == 0

    def test_a_run_repeating_both_halves_still_fires(self):
        """The signal is not gone: an act the run has made before AND whose
        result it has seen before is not evidence, and four steps of that
        is still a stall."""
        known = [("governed_read", {"asset_id": f"a.{n}"}, f"result {n}")
                 for n in range(3)]
        sup, _reviewer = watching(verdict(NUDGE, "you already have this"))
        for act in known:
            assert step(sup, act) is None
        review = None
        for index in range(4):
            review = step(sup, known[index % 3])
        assert review is not None and review.signal == NO_NEW_EVIDENCE


class TestAnAbsenceOfEvidenceDoesNotSpendTheBudget:
    """``progressing`` on ``no_new_evidence`` is refunded, twice.

    The other signals are *demonstrated repetition* — the same act three
    times, three replies the loop could not act on, A B A B — and a run
    still producing those after three reviews has answered the question.
    An absence of new evidence is not that: a long build or a careful
    re-read shows it honestly, and a run told "this is fine" twice and then
    forced ``stuck`` on the third by arithmetic is the step budget coming
    back under another name.
    """

    def _stalling(self, *replies, steps=200):
        """A three-cycle with the same bytes back: the one true stall that
        `repeated_call` (3 identical acts in 6) and `oscillation` (two
        states) both miss."""
        sup, reviewer = watching(*replies)
        seen = []
        for index in range(steps):
            review = step(sup, ("ABC"[index % 3], {}, "same"))
            if review is not None:
                seen.append(review)
                if review.verdict == STUCK:
                    break
        return sup, reviewer, seen

    def test_two_progressing_verdicts_cost_no_reviews(self):
        _sup, _reviewer, seen = self._stalling(
            verdict(PROGRESSING), verdict(PROGRESSING), verdict(NUDGE, "a"),
            verdict(NUDGE, "b"), verdict(NUDGE, "c"))
        assert [r.verdict for r in seen[:2]] == [PROGRESSING, PROGRESSING]
        assert [r.reviews_left for r in seen[:2]] == [REVIEWS, REVIEWS]

    def test_the_last_review_may_still_say_progressing_while_refunds_last(
            self):
        """The narrowing that ends a healthy run by arithmetic is the thing
        being fixed, so the word is offered as long as saying it is free."""
        _sup, reviewer, _seen = self._stalling(
            verdict(PROGRESSING), verdict(PROGRESSING), verdict(NUDGE, "a"),
            verdict(NUDGE, "b"), verdict(NUDGE, "c"))
        assert '"progressing"' in reviewer.seen[0][0]["content"]
        assert '"progressing"' in reviewer.seen[1][0]["content"]

    def test_the_threshold_still_rises_so_a_refund_is_not_free(self):
        """Four stale steps, then eight, then twelve: the same absence costs
        geometrically more to report."""
        _sup, reviewer, seen = self._stalling(
            *[verdict(PROGRESSING)] * 10)
        assert [r.count for r in seen[:3]] == [STALE_STEPS, STALE_STEPS * 2,
                                               STALE_STEPS * 3]

    def test_a_run_that_really_is_going_in_circles_is_still_wound_up(self):
        """The endless-loop catch survives the refund. A model that answers
        `progressing` forever gets `REVIEWS + REVIEW_REFUNDS` reviews and
        then the arithmetic."""
        _sup, reviewer, seen = self._stalling(*[verdict(PROGRESSING)] * 20)
        assert seen[-1].verdict == STUCK
        assert reviewer.calls == REVIEWS + REVIEW_REFUNDS

    def test_the_other_signals_keep_the_arithmetic(self):
        """`repeated_call` is demonstrated repetition and a `progressing`
        verdict on it spends a review, exactly as it always did."""
        sup, reviewer = watching(verdict(PROGRESSING))
        seen = []
        for _ in range(12):
            review = step(sup, READ)
            if review is not None:
                seen.append(review)
                break
        assert seen[0].signal == REPEATED_CALL
        assert seen[0].reviews_left == REVIEWS - 1

    def test_the_refunded_signals_are_a_stated_set(self):
        """Two absences, and both for the same reason. `frozen_frontier`
        is cognition's, and the owner's ruling of 13 September 2026 is the
        floor under it: the cognitive layer is shadow and additive, so a
        signal it feeds must not be able to spend a run's review budget
        down to a forced wind-up."""
        assert REFUNDS_ON_PROGRESSING == frozenset({NO_NEW_EVIDENCE,
                                                    FROZEN_FRONTIER})
        assert REVIEW_REFUNDS == 2


class TestGoingRoundInTwos:
    def test_a_b_a_b_is_an_oscillation(self):
        sup, _reviewer = watching(verdict(NUDGE, "pick one"))
        a = ("governed_view", {"run": "r-7"}, "view seven")
        b = ("governed_view", {"run": "r-9"}, "view nine")
        assert step(sup, a) is None
        assert step(sup, b) is None
        assert step(sup, a) is None
        review = step(sup, b)
        assert review is not None and review.signal == OSCILLATION

    def test_a_a_b_b_is_not(self):
        """Two calls made twice is a run doing two things, and doing each
        of them twice is not alternating between them."""
        sup, reviewer = watching()
        a = ("governed_view", {"run": "r-7"}, "view seven")
        b = ("governed_view", {"run": "r-9"}, "view nine")
        assert step(sup, a) is None
        assert step(sup, a) is None
        assert step(sup, b) is None
        assert reviewer.calls == 0


# ── the signal that is not about what the run did ────────────────────────────


OWED = "owed: (alice, payment_link, ?c) — for goal g1, open"


def believing(frontier="f1", obligations=2, contradictions=0,
              propositions=0, owed=OWED):
    """One step's epistemic reading, in the shape the shadow hands over.

    The production class, not a stand-in: the supervisor duck-types it, and
    a test that invented its own four fields would go on passing the day
    the shadow renamed one.
    """
    return Progress(frontier=frontier, obligations=obligations,
                    contradictions=contradictions, propositions=propositions,
                    owed=owed)


def working(sup, count, readings=None, start=0, **kw):
    """*count* steps of honest-looking work, each with its own reading.

    A new call and a new result every step, so none of the four procedural
    signals has anything to say: this is the run that looks healthy to all
    of them, which is the whole case `frozen_frontier` exists for.  *start*
    is where the act numbering picks up, for a test that calls this twice
    and needs the second stretch to be new work rather than a re-read.
    """
    seen = []
    for index in range(start, start + count):
        reading = (readings[index - start] if readings is not None
                   else believing(**kw))
        seen.append(step(sup, ("read", {"n": index}, f"row {index}"),
                         progress=reading))
    return seen


class TestTheRunsBeliefHasStoppedMoving:
    """ROADMAP §2.9.6's signal: the frontier, not the transcript.

    Every run in this class is *busy* — a new call and a new result every
    step — so `repeated_call`, `oscillation`, `rejected_replies` and
    `no_new_evidence` all see a healthy mission. What they cannot see is
    that nothing the run is learning answers anything the goals asked for,
    and §2.9.6 calls that this arc's largest expected gain.
    """

    def test_five_frozen_steps_are_a_signal(self):
        sup, reviewer = watching(verdict(NUDGE, "try the holder directly"))
        seen = working(sup, FROZEN_STEPS)
        assert [review for review in seen[:-1]] == [None] * (FROZEN_STEPS - 1)
        assert seen[-1] is not None
        assert seen[-1].signal == FROZEN_FRONTIER
        assert reviewer.calls == 1

    def test_four_are_not(self):
        sup, reviewer = watching()
        assert working(sup, FROZEN_STEPS - 1) == [None] * (FROZEN_STEPS - 1)
        assert reviewer.calls == 0

    def test_a_moving_frontier_is_never_a_signal(self):
        """The condition, stated as its negative: a run whose obligations
        are changing is a run whose goals are being worked, however long it
        takes."""
        sup, reviewer = watching()
        assert working(sup, 20, readings=[believing(frontier=f"f{index}")
                                          for index in range(20)]) \
            == [None] * 20
        assert reviewer.calls == 0

    def test_a_contradiction_settled_is_progress(self):
        """Frozen frontier, and one disagreement fewer than the step
        before: the run resolved something, which is exactly what §2.9.6's
        third clause is about."""
        sup, reviewer = watching()
        readings = [believing(contradictions=count)
                    for count in (3, 3, 2, 2, 2)]
        assert working(sup, len(readings), readings=readings) \
            == [None] * len(readings)
        assert reviewer.calls == 0

    def test_and_the_comparison_is_pairwise_and_not_end_to_end(self):
        """The window that separates the two spellings: two disagreements,
        one settled, one found again. Its ends agree — an endpoint
        comparison sees a run standing still — and step against step there
        is a reduction in it, which is a run that settled something. The
        second reading is the true one, and this window is the only kind
        that can tell."""
        sup, reviewer = watching()
        readings = [believing(contradictions=count)
                    for count in (2, 1, 2, 2, 2)]
        assert working(sup, len(readings), readings=readings) \
            == [None] * len(readings)
        assert reviewer.calls == 0

    def test_a_contradiction_found_is_not_progress(self):
        """The check is "none was reduced", not "the number moved". A run
        that keeps discovering disagreements and settling none of them has
        a frontier that is still exactly where it was."""
        sup, _reviewer = watching(verdict(NUDGE, "settle one of them"))
        readings = [believing(contradictions=count)
                    for count in range(FROZEN_STEPS)]
        assert working(sup, FROZEN_STEPS,
                       readings=readings)[-1].signal == FROZEN_FRONTIER

    def test_a_store_that_is_filling_up_is_progress(self):
        """One new proposition a step is a run that is establishing things,
        and an absence claimed over that is a claim the run disproves."""
        sup, reviewer = watching()
        readings = [believing(propositions=index * BELIEFS_PER_STEP)
                    for index in range(FROZEN_STEPS)]
        assert working(sup, FROZEN_STEPS, readings=readings) \
            == [None] * FROZEN_STEPS
        assert reviewer.calls == 0

    def test_but_a_trickle_is_noise(self):
        """Two new propositions across four steps of work is a store that
        is standing still with a rounding error on it."""
        sup, _reviewer = watching(verdict(NUDGE, "read the holder"))
        readings = [believing(propositions=count)
                    for count in (10, 10, 11, 11, 12)]
        assert working(sup, FROZEN_STEPS,
                       readings=readings)[-1].signal == FROZEN_FRONTIER

    def test_an_empty_frontier_is_absent_and_not_frozen(self):
        """Every run that has not been given a rule pack has the same empty
        frontier at every step forever. A signal that read that as a stall
        would review every cognition-on mission in the world for standing
        still at nothing."""
        sup, reviewer = watching()
        assert working(sup, 20, obligations=0, owed="") == [None] * 20
        assert reviewer.calls == 0

    def test_the_review_quotes_what_has_not_moved(self):
        """"The frontier has not moved" is a sentence a model can neither
        check nor act on. The top owed line — the same words the compiled
        block showed it — is both."""
        sup, reviewer = watching(verdict(NUDGE, "ask for the holder"))
        review = working(sup, FROZEN_STEPS)[-1]
        assert OWED in review.sentence()
        assert f"has not moved in {FROZEN_STEPS} steps" in review.sentence()
        assert OWED in reviewer.seen[0][-1]["content"]

    def test_it_asks_once_and_not_once_a_step(self):
        """The floor moves after a review, exactly as it does for every
        other signal: a note that is re-asked at the very next boundary
        never gets a chance to work."""
        sup, reviewer = watching(verdict(NUDGE, "ask for the holder"))
        assert working(sup, FROZEN_STEPS)[-1] is not None
        assert working(sup, FROZEN_STEPS - 1, start=FROZEN_STEPS) \
            == [None] * (FROZEN_STEPS - 1)
        assert reviewer.calls == 1

    def test_the_frontier_moving_resets_the_count(self):
        """Recovery. Four frozen steps, one that moves, and the count
        starts again — the window is consecutive by construction."""
        sup, reviewer = watching()
        working(sup, FROZEN_STEPS - 1)
        assert step(sup, ("read", {"n": 99}, "row 99"),
                    progress=believing(frontier="moved")) is None
        assert working(sup, FROZEN_STEPS - 2, start=FROZEN_STEPS,
                       frontier="moved") == [None] * (FROZEN_STEPS - 2)
        assert reviewer.calls == 0


class TestCognitionOffChangesNothing:
    """The floor under the whole feature: a run that did not ask for
    cognition is supervised byte for byte as it always was."""

    def test_no_reading_is_no_signal_however_long_the_run(self):
        sup, reviewer = watching()
        for index in range(40):
            assert step(sup, ("read", {"n": index}, f"row {index}")) is None
        assert reviewer.calls == 0

    def test_the_other_signals_are_untouched_without_readings(self):
        sup, _reviewer = watching(verdict(NUDGE, "read something else"))
        assert step(sup, READ) is None
        assert step(sup, READ) is None
        assert step(sup, READ).signal == REPEATED_CALL

    def test_a_reading_that_goes_missing_disables_the_signal(self):
        """Failure isolation, written as a condition rather than a `try`:
        the shadow answers `None` when its frontier cannot be read, the
        window stops being usable, and the supervisor keeps its other
        four."""
        sup, reviewer = watching()
        readings = [believing()] * (FROZEN_STEPS * 2)
        readings[FROZEN_STEPS - 1] = None
        assert working(sup, FROZEN_STEPS, readings=readings) \
            == [None] * FROZEN_STEPS
        assert reviewer.calls == 0

    def test_a_reading_this_module_does_not_recognise_is_no_reading(self):
        """Every attribute read off a reading here is optional, and it is
        one rule rather than two: a stand-in carrying three of the four
        fields is a shape this module cannot compare, and the honest
        answer to a shape it cannot compare is no signal — not an
        `AttributeError` out of a step boundary."""

        class _Partial:
            frontier = "f1"
            obligations = 2
            contradictions = 0
            # and no `propositions`, which is the one being compared to
            # `BELIEFS_PER_STEP`.

        sup, reviewer = watching()
        assert working(sup, FROZEN_STEPS,
                       readings=[_Partial()] * FROZEN_STEPS) \
            == [None] * FROZEN_STEPS
        assert reviewer.calls == 0

    def test_and_the_signal_comes_back_when_the_readings_do(self):
        """Disabled for the window and not for the run: a shadow that
        recovers is watched again, because nothing here latches."""
        sup, _reviewer = watching(verdict(NUDGE, "ask for the holder"))
        readings = [None] + [believing()] * FROZEN_STEPS
        assert working(sup, len(readings),
                       readings=readings)[-1].signal == FROZEN_FRONTIER


class TestCognitionSteersAndNeverGates:
    """The owner's ruling of 13 September 2026, checked at the seam.

    The cognitive layer emits state and guidance; it never gates. What
    keeps that true here is that the signal was given no machinery of its
    own: it raises the review this module already raises, and there is no
    path from it to an ending that a repeated call did not already have.
    """

    def test_it_rides_the_record_every_other_signal_rides(self):
        sup, _reviewer = watching(verdict(NUDGE, "ask for the holder"))
        record = working(sup, FROZEN_STEPS)[-1].as_record()
        assert set(record) == {"signal", "verdict", "reviews_left", "note"}
        assert record["signal"] == FROZEN_FRONTIER

    def test_it_invents_no_verdict(self):
        assert FROZEN_FRONTIER in SIGNALS
        assert VERDICTS == (PROGRESSING, NUDGE, STUCK, REPLAN)

    def test_the_quoted_line_is_not_on_the_wire(self):
        """`detail` is prose out of the kernel. A consumer rendering it
        would be rendering the cognitive layer's internals as contract."""
        sup, _reviewer = watching(verdict(NUDGE, "ask for the holder"))
        review = working(sup, FROZEN_STEPS)[-1]
        assert review.detail
        assert review.detail not in json.dumps(review.as_record())

    def test_a_progressing_verdict_costs_it_nothing(self):
        """Refunded, like the other absence. A cognitive signal that could
        spend a run's review budget down to a forced wind-up would be
        cognition deciding a mission's length."""
        sup, _reviewer = watching(verdict(PROGRESSING))
        review = working(sup, FROZEN_STEPS)[-1]
        assert review.verdict == PROGRESSING
        assert review.reviews_left == REVIEWS

    def test_and_the_threshold_rises_so_the_refund_is_not_free(self):
        sup, reviewer = watching(*[verdict(PROGRESSING)] * 4)
        seen = [review for review in working(sup, FROZEN_STEPS * 4)
                if review is not None]
        assert [review.count for review in seen[:2]] == [FROZEN_STEPS,
                                                         FROZEN_STEPS * 2]

    def test_the_exempt_signals_are_a_stated_set(self):
        """One member, and it is the cognitive one. A refund was not
        enough: it protects a run whose reviewer keeps saying
        `progressing`, and two other paths ended a procedurally healthy
        mission on this signal alone.

        It is an exemption and not a softening — the arithmetic that ends
        runs still belongs to demonstrated repetition, which
        `TestTheEndlessLoopIsCaughtByArithmetic` is the owner of."""
        assert NEVER_WINDS_UP == frozenset({FROZEN_FRONTIER})

    def test_the_reviewing_model_is_not_offered_the_ending_word(self):
        """Not offered and not accepted, which is the same narrowing the
        last review already does for `progressing`: a word that is not in
        the prompt cannot come back as a verdict by accident."""
        sup, reviewer = watching(verdict(NUDGE, "ask for the holder"))
        working(sup, FROZEN_STEPS)
        prompt = reviewer.seen[0][0]["content"]
        assert '"progressing"' in prompt and '"nudge"' in prompt
        assert '"stuck"' not in prompt

    def test_and_a_reviewer_that_says_it_anyway_is_read_as_a_nudge(self):
        """A verdict dropped on the floor is a review spent for nothing,
        so an unoffered word is read as the nearest one this review MAY
        return — and the note, which is the actionable half, still reaches
        the run."""
        sup, _reviewer = watching(verdict(STUCK, "nothing is moving"))
        review = working(sup, FROZEN_STEPS)[-1]
        assert review.verdict == NUDGE
        assert review.note == "nothing is moving"

    def test_and_the_spent_budget_says_nothing_at_all(self):
        """The out-of-reviews answer *is* the wind-up — `stuck` by
        arithmetic, with no call made. A signal that may not end a run has
        none to make, so the boundary is the ordinary one: no review, no
        record, nothing said to the model."""
        sup, reviewer = watching(*[verdict(NUDGE, "try the holder")] * 8)
        spent = [working(sup, FROZEN_STEPS, start=FROZEN_STEPS * turn)[-1]
                 for turn in range(REVIEWS)]
        assert [review.verdict for review in spent] == [NUDGE] * REVIEWS
        assert sup.reviews_left == 0
        assert working(sup, FROZEN_STEPS,
                       start=FROZEN_STEPS * REVIEWS)[-1] is None
        assert reviewer.calls == REVIEWS

    def test_and_a_run_told_it_is_fine_to_the_last_review_records_that(self):
        """Taking `progressing` off the last menu exists to force the
        wind-up, and there is none here to force. So the word stays on the
        menu: dropping it would mean an honest `progressing` came back as
        an unoffered word, was read as the nearest one this review may
        return, and rode `step_started` as a nudge nobody wrote.

        Five firings, because every `progressing` raises the threshold —
        5, 10, 15, 20 and 25 steps of work — and the last two spend the
        budget the refund stops covering.
        """
        sup, reviewer = watching(*[verdict(PROGRESSING)] * 8)
        seen, done = [], 0
        for turn in range(5):
            window = FROZEN_STEPS * (turn + 1)
            seen.append(working(sup, window, start=done)[-1])
            done += window
        assert [review.verdict for review in seen] == [PROGRESSING] * 5
        assert reviewer.calls == 5
        assert sup.reviews_left == 0

    def test_a_run_that_is_repeating_itself_is_asked_the_concrete_question(
            self):
        """Specificity order, at the one boundary where it decides
        anything: both thresholds ready, and the run is asked about the
        evidence — that sentence names a call and a result, which is
        something a model can act on. The two are put on the same number
        here because that is the only way to make them arrive together;
        with the shipped numbers they usually do not."""
        known = [("governed_read", {"asset_id": f"a.{n}"}, f"result {n}")
                 for n in range(3)]
        sup, _reviewer = watching(verdict(NUDGE, "you already have this"),
                                  frozen_steps=STALE_STEPS)
        review = None
        for index in range(3 + STALE_STEPS):
            # The frontier moves while the run is reading things for the
            # first time and freezes once it starts re-reading them, so the
            # two thresholds come ready on the same boundary.
            review = step(sup, known[index % 3],
                          progress=believing(frontier=f"f{min(index, 3)}"))
        assert review is not None and review.signal == NO_NEW_EVIDENCE


# ── layer two: the review turn ───────────────────────────────────────────────


class TestWhatTheReviewerIsShown:
    def _reviewed(self, *replies):
        sup, reviewer = watching(*replies)
        for _ in range(3):
            review = step(sup, READ)
        return review, reviewer

    def test_it_is_shown_the_objective_and_what_ran(self):
        _review, reviewer = self._reviewed(verdict(STUCK))
        shown = reviewer.seen[0][-1]["content"]
        assert "find the actor at the top of run r-7" in shown
        assert "governed_read" in shown
        assert "results only" in shown

    def test_it_is_told_which_pattern_fired(self):
        _review, reviewer = self._reviewed(verdict(STUCK))
        assert "3 times over the last few calls" in \
            reviewer.seen[0][-1]["content"]

    def test_it_is_offered_exactly_three_words(self):
        _review, reviewer = self._reviewed(verdict(STUCK))
        system = reviewer.seen[0][0]["content"]
        assert '"progressing"' in system
        assert '"nudge"' in system
        assert '"stuck"' in system
        assert '"replan"' not in system

    def test_a_gate_review_is_offered_the_fourth(self):
        """`replan` exists for one call site and is offered at one call
        site: a direct mission has no plan to redraw."""
        sup, reviewer = watching(verdict(REPLAN, "the plan is wrong"))
        review = sup.review_gate("obj", goal="read the view",
                                 why="no successful tool call")
        assert review.verdict == REPLAN
        system = reviewer.seen[0][0]["content"]
        assert '"replan"' in system
        assert review.signal == FAILED_GATE
        assert "read the view" in reviewer.seen[0][-1]["content"]
        assert "no successful tool call" in reviewer.seen[0][-1]["content"]


class TestTheVerdictsAreActedOn:
    def test_progressing_raises_the_threshold_for_that_signal(self):
        """A pattern somebody has explained does not keep buying reviews.
        Three more identical calls after a `progressing` are not a second
        review — it takes six.

        `stale_steps` is put out of the way so this measures the threshold
        and not the OTHER signal a repeating run trips: four steps with
        nothing new in them is a different question, asked with a different
        sentence, and it is allowed to be asked.
        """
        sup, reviewer = watching(verdict(PROGRESSING), stale_steps=99)
        for _ in range(3):
            review = step(sup, READ)
        assert review.verdict == PROGRESSING
        for _ in range(5):
            assert step(sup, READ) is None
        assert reviewer.calls == 1
        assert step(sup, READ) is not None
        assert reviewer.calls == 2

    def test_a_nudge_is_not_re_asked_about_the_evidence_it_saw(self):
        """The floor. Without it the note is delivered and the very next
        boundary asks about the same three calls again, so a nudge never
        gets a chance to work."""
        sup, reviewer = watching(verdict(NUDGE, "read r-9 instead"),
                                 stale_steps=99)
        for _ in range(3):
            review = step(sup, READ)
        assert review.verdict == NUDGE
        assert step(sup, READ) is None
        assert step(sup, READ) is None
        assert reviewer.calls == 1
        # Three NEW identical calls, and it is asked again.
        assert step(sup, READ) is not None
        assert reviewer.calls == 2

    def test_an_unreadable_verdict_is_read_as_progressing_and_spent(self):
        """A review that could not be read must not end a mission — and
        must not raise a threshold either, because nobody said the pattern
        was fine. It is still SPENT, so a model answering in prose forever
        still winds the run up after three of them."""
        sup, reviewer = watching("I think it's fine, honestly")
        for _ in range(3):
            review = step(sup, READ)
        assert review.verdict == PROGRESSING
        assert review.reviews_left == REVIEWS - 1
        assert sup._raised == {}

    def test_an_endpoint_that_throws_does_not_end_the_run(self):
        def broken(_messages):
            raise RuntimeError("the endpoint is down")

        sup = Supervisor(broken)
        for _ in range(3):
            review = step(sup, READ)
        assert review.verdict == PROGRESSING
        assert sup.reviews_left == REVIEWS - 1


class TestTheEndlessLoopIsCaughtByArithmetic:
    def _looping(self, *replies):
        sup, reviewer = watching(*replies)
        seen = []
        for _ in range(40):
            review = step(sup, READ)
            if review is not None:
                seen.append(review)
            if seen and seen[-1].verdict == STUCK:
                break
        return sup, reviewer, seen

    def test_the_last_review_is_not_offered_progressing(self):
        sup, reviewer, seen = self._looping(
            verdict(NUDGE, "one"), verdict(NUDGE, "two"),
            verdict(NUDGE, "three"))
        assert [r.verdict for r in seen[:3]] == [NUDGE, NUDGE, NUDGE]
        assert '"progressing"' in reviewer.seen[0][0]["content"]
        assert '"progressing"' in reviewer.seen[1][0]["content"]
        assert '"progressing"' not in reviewer.seen[2][0]["content"]

    def test_progressing_on_the_last_review_is_read_as_stuck(self):
        """The word is neither offered nor accepted. A model asked "are you
        looping?" three times and answering "no" three times has answered
        the question."""
        sup, _reviewer, seen = self._looping(
            verdict(NUDGE, "one"), verdict(NUDGE, "two"),
            verdict(PROGRESSING))
        assert seen[2].verdict == STUCK

    def test_after_the_last_review_a_signal_winds_up_with_no_call(self):
        sup, reviewer, seen = self._looping(
            verdict(NUDGE, "one"), verdict(NUDGE, "two"),
            verdict(NUDGE, "three"))
        assert reviewer.calls == REVIEWS
        assert seen[-1].verdict == STUCK
        assert seen[-1].reviews_left == 0
        assert "without asking a fourth time" in seen[-1].note

    def test_a_run_of_nudges_cannot_go_on_forever(self):
        _sup, reviewer, seen = self._looping(
            *[verdict(NUDGE, f"note {n}") for n in range(10)])
        assert reviewer.calls == REVIEWS
        assert seen[-1].verdict == STUCK


class TestAReviewIsAModelCallLikeAnyOther:
    def test_what_it_cost_goes_on_the_ledger(self):
        """A review is a model call and the run pays for it, so it reaches
        `mission_finished.usage` like every other call. A supervisor whose
        calls were free on the invoice would be under-reporting exactly the
        runs that went badly."""
        from core.runtime.backends.base import Usage
        from core.runtime.usage import Ledger

        ledger = Ledger()
        sup = Supervisor(ScriptedReviewer(verdict(STUCK)),
                         usage_fn=lambda: Usage(prompt_tokens=30,
                                                completion_tokens=5,
                                                total_tokens=35))
        for _ in range(2):
            sup.saw_call(*READ)
            sup.look("obj", ledger=ledger)
        sup.saw_call(*READ)
        assert sup.look("obj", ledger=ledger) is not None
        assert ledger.as_record()["total_tokens"] == 35
        assert ledger.as_record()["calls"] == 1

    def test_it_is_fitted_through_the_run_s_own_window(self):
        class _Window:
            def __init__(self):
                self.asked = 0

            def fit(self, messages, pinned=0, note=None):
                self.asked += 1
                return list(messages), None

        window = _Window()
        sup = Supervisor(ScriptedReviewer(verdict(STUCK)), window=window)
        for _ in range(3):
            sup.saw_call(*READ)
            review = sup.look("obj")
        assert review is not None
        assert window.asked == 1
