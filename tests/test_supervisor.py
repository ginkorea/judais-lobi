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

from core.runtime.supervisor import (
    FAILED_GATE, NO_NEW_EVIDENCE, NUDGE, OSCILLATION, PROGRESSING,
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


def step(sup, *acts, rejections=0):
    """One step's worth of observations, then the boundary that closes it.

    The boundary is where a review happens, so a test that wants three
    steps' worth of pattern calls this three times and reads the verdict
    off the last one — which is exactly the order the loop does it in.
    """
    for tool, arguments, result in acts:
        sup.saw_call(tool, arguments, result)
    for _ in range(rejections):
        sup.saw_rejection()
    return sup.look("find the actor at the top of run r-7")


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
        assert REFUNDS_ON_PROGRESSING == frozenset({NO_NEW_EVIDENCE})
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
