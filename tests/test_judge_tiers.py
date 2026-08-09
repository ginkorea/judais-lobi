# tests/test_judge_tiers.py — Tests for core.judge.tiers

import pytest

from core.judge.models import TierVerdict
from core.judge.tiers import BaseTier, TestTier, LintTier, LLMReviewTier


# ── TestTier ─────────────────────────────────────────────────────────────────

class TestTestTier:
    def setup_method(self):
        self.tier = TestTier()

    def test_name_and_weight(self):
        assert self.tier.name == "test"
        assert self.tier.weight == 0.6

    def test_pass(self):
        r = self.tier.evaluate(test_exit_code=0, test_stdout="5 passed")
        assert r.verdict == TierVerdict.PASS
        assert r.score == 1.0
        assert r.short_circuit is False
        assert "5 passed" in r.details

    def test_fail(self):
        r = self.tier.evaluate(test_exit_code=1, test_stderr="1 failed")
        assert r.verdict == TierVerdict.FAIL
        assert r.score == 0.0
        assert r.short_circuit is True
        assert "1 failed" in r.details

    def test_fail_nonzero_exit(self):
        r = self.tier.evaluate(test_exit_code=2)
        assert r.verdict == TierVerdict.FAIL
        assert r.short_circuit is True

    def test_pass_empty_stdout(self):
        r = self.tier.evaluate(test_exit_code=0)
        assert r.verdict == TierVerdict.PASS
        assert r.details == "all tests passed"

    def test_fail_stderr_preferred_over_stdout(self):
        r = self.tier.evaluate(test_exit_code=1, test_stdout="out",
                               test_stderr="err")
        assert r.details == "err"

    def test_fail_stdout_fallback(self):
        r = self.tier.evaluate(test_exit_code=1, test_stdout="stdout err",
                               test_stderr="")
        assert r.details == "stdout err"

    def test_details_truncated(self):
        long = "x" * 500
        r = self.tier.evaluate(test_exit_code=0, test_stdout=long)
        assert len(r.details) == 200

    def test_extra_kwargs_ignored(self):
        r = self.tier.evaluate(test_exit_code=0, lint_exit_code=1)
        assert r.verdict == TierVerdict.PASS

    def test_default_exit_code_is_failure(self):
        """Default test_exit_code=1 means fail when called with no args."""
        r = self.tier.evaluate()
        assert r.verdict == TierVerdict.FAIL


# ── LintTier ─────────────────────────────────────────────────────────────────

class TestLintTier:
    def setup_method(self):
        self.tier = LintTier()

    def test_name_and_weight(self):
        assert self.tier.name == "lint"
        assert self.tier.weight == 0.25

    def test_pass(self):
        r = self.tier.evaluate(lint_exit_code=0)
        assert r.verdict == TierVerdict.PASS
        assert r.score == 1.0
        assert r.details == "lint clean"

    def test_fail(self):
        r = self.tier.evaluate(lint_exit_code=1, lint_stdout="E301 expected")
        assert r.verdict == TierVerdict.FAIL
        assert r.score == 0.0
        assert "E301" in r.details

    def test_waived(self):
        r = self.tier.evaluate(lint_exit_code=1, lint_waive=True,
                               lint_stdout="E301 expected")
        assert r.verdict == TierVerdict.WAIVED
        assert r.score == 0.5
        assert "E301" in r.details

    def test_waive_true_but_lint_passes(self):
        """If lint passes, waive flag is irrelevant."""
        r = self.tier.evaluate(lint_exit_code=0, lint_waive=True)
        assert r.verdict == TierVerdict.PASS
        assert r.score == 1.0

    def test_fail_empty_stdout(self):
        r = self.tier.evaluate(lint_exit_code=1)
        assert r.verdict == TierVerdict.FAIL
        assert r.details == "lint failed"

    def test_waived_empty_stdout(self):
        r = self.tier.evaluate(lint_exit_code=1, lint_waive=True)
        assert r.details == "lint issues waived"

    def test_no_short_circuit(self):
        r = self.tier.evaluate(lint_exit_code=1)
        assert r.short_circuit is False

    def test_extra_kwargs_ignored(self):
        r = self.tier.evaluate(lint_exit_code=0, test_exit_code=1)
        assert r.verdict == TierVerdict.PASS

    def test_default_exit_code_is_failure(self):
        r = self.tier.evaluate()
        assert r.verdict == TierVerdict.FAIL


# ── LLMReviewTier ────────────────────────────────────────────────────────────

class TestLLMReviewTier:
    def setup_method(self):
        self.tier = LLMReviewTier()

    def test_name_and_weight(self):
        assert self.tier.name == "llm_review"
        assert self.tier.weight == 0.15

    def test_no_reviewer_is_unknown_not_a_midpoint(self):
        """Was: PASS at a flat 0.5 labelled "stub". A fabricated midpoint
        is indistinguishable downstream from a real lukewarm review."""
        r = self.tier.evaluate()
        assert r.verdict == TierVerdict.UNKNOWN
        assert r.score == 0.0
        assert "no reviewer configured" in r.details

    def test_no_diff_is_unknown_too(self):
        r = LLMReviewTier(chat_fn=lambda _m: "{}").evaluate(diff="   ")
        assert r.verdict == TierVerdict.UNKNOWN
        assert "nothing to review" in r.details

    def test_no_short_circuit(self):
        r = self.tier.evaluate()
        assert r.short_circuit is False


# ── BaseTier ─────────────────────────────────────────────────────────────────

class TestBaseTier:
    def test_abstract(self):
        """BaseTier cannot be instantiated directly."""
        with pytest.raises(TypeError):
            BaseTier()

    def test_subclass_must_implement_evaluate(self):
        class Incomplete(BaseTier):
            name = "incomplete"
            weight = 0.1

        with pytest.raises(TypeError):
            Incomplete()


class TestLLMReviewTierAgainstAModel:
    """The tier that used to be a flat 0.5 labelled "stub"."""

    def _tier(self, reply):
        return LLMReviewTier(chat_fn=lambda _messages: reply)

    def test_a_clean_review_scores_high(self):
        r = self._tier('{"score": 1.0, "verdict": "pass", "concerns": []}') \
            .evaluate(diff="- a\n+ b")
        assert r.verdict == TierVerdict.PASS
        assert r.score == 1.0
        assert r.details == "no concerns raised"

    def test_concerns_reach_the_report(self):
        r = self._tier(
            '{"score": 0.2, "verdict": "fail", '
            '"concerns": ["swallows the exception", "name says the opposite"]}'
        ).evaluate(diff="x")
        assert r.verdict == TierVerdict.FAIL
        assert r.score == 0.2
        assert "swallows the exception" in r.details
        assert "name says the opposite" in r.details

    def test_it_never_short_circuits(self):
        """Style does not get to stop a run whose tests passed."""
        r = self._tier('{"score": 0.0, "verdict": "fail", "concerns": ["x"]}') \
            .evaluate(diff="x")
        assert r.short_circuit is False

    def test_a_fenced_reply_is_accepted(self):
        r = self._tier('```json\n{"score": 0.9, "verdict": "pass", '
                       '"concerns": []}\n```').evaluate(diff="x")
        assert r.score == 0.9

    def test_the_diff_is_what_gets_reviewed(self):
        seen = {}

        def chat(messages):
            seen["user"] = messages[-1]["content"]
            return '{"score": 1.0, "verdict": "pass", "concerns": []}'

        LLMReviewTier(chat_fn=chat).evaluate(diff="--- a/x\n+++ b/x")
        assert "--- a/x" in seen["user"]

    def test_a_long_diff_is_truncated_and_says_so(self):
        seen = {}

        def chat(messages):
            seen["user"] = messages[-1]["content"]
            return '{"score": 1.0, "verdict": "pass", "concerns": []}'

        LLMReviewTier(chat_fn=chat, max_diff_chars=50).evaluate(diff="z" * 5000)
        assert "truncated" in seen["user"]
        assert len(seen["user"]) < 400


class TestLLMReviewTierRefusesToGuess:
    """Every unreadable answer is UNKNOWN, never a number."""

    def _evaluate(self, reply):
        return LLMReviewTier(chat_fn=lambda _m: reply).evaluate(diff="x")

    @pytest.mark.parametrize("reply,expected", [
        ("", "returned nothing"),
        ("Looks fine to me!", "not JSON"),
        ("[1, 2]", "not an object"),
        ('{"verdict": "pass"}', "non-numeric score"),
        ('{"score": "high", "verdict": "pass"}', "non-numeric score"),
        ('{"score": true, "verdict": "pass"}', "non-numeric score"),
        ('{"score": 4.0, "verdict": "pass"}', "outside 0..1"),
        ('{"score": -1, "verdict": "pass"}', "outside 0..1"),
        ('{"score": 0.5, "verdict": "maybe"}', "unrecognised verdict"),
        ('{"score": 0.5, "verdict": "pass", "concerns": "one"}',
         "concerns were not a list"),
    ])
    def test_unreadable_replies_are_unknown(self, reply, expected):
        r = self._evaluate(reply)
        assert r.verdict == TierVerdict.UNKNOWN
        assert r.score == 0.0
        assert expected in r.details

    def test_an_unreachable_reviewer_is_unknown(self):
        def boom(_messages):
            raise ConnectionError("no route to host")

        r = LLMReviewTier(chat_fn=boom).evaluate(diff="x")
        assert r.verdict == TierVerdict.UNKNOWN
        assert "unreachable" in r.details
        assert "no route to host" in r.details

    def test_availability_is_reported(self):
        assert LLMReviewTier().available is False
        assert LLMReviewTier(chat_fn=lambda _m: "").available is True

    def test_from_agent_builds_a_working_tier(self):
        class FakeAgent:
            model = "m"

            class client:
                @staticmethod
                def chat(model, messages, stream=False):
                    return '{"score": 0.8, "verdict": "pass", "concerns": []}'

        r = LLMReviewTier.from_agent(FakeAgent()).evaluate(diff="x")
        assert r.score == 0.8


class TestAnUnknownTierCostsNothing:
    """The arithmetic reason UNKNOWN beats a fabricated 0.5."""

    def test_a_missing_reviewer_does_not_dock_the_score(self):
        from core.judge.judge import CompositeJudge

        clean = CompositeJudge().evaluate(test_exit_code=0, lint_exit_code=0)
        assert clean.final_score == pytest.approx(1.0)

    def test_a_present_reviewer_does_move_the_score(self):
        from core.judge.judge import CompositeJudge
        from core.judge.tiers import TestTier, LintTier

        judge = CompositeJudge([
            TestTier(), LintTier(),
            LLMReviewTier(chat_fn=lambda _m:
                          '{"score": 0.0, "verdict": "fail", '
                          '"concerns": ["unsafe"]}'),
        ])
        r = judge.evaluate(test_exit_code=0, lint_exit_code=0, diff="x")
        assert r.final_score == pytest.approx(0.85)

    def test_the_two_agree_when_the_reviewer_is_perfect(self):
        from core.judge.judge import CompositeJudge
        from core.judge.tiers import TestTier, LintTier

        absent = CompositeJudge().evaluate(test_exit_code=0, lint_exit_code=0)
        perfect = CompositeJudge([
            TestTier(), LintTier(),
            LLMReviewTier(chat_fn=lambda _m:
                          '{"score": 1.0, "verdict": "pass", "concerns": []}'),
        ]).evaluate(test_exit_code=0, lint_exit_code=0, diff="x")
        assert absent.final_score == pytest.approx(perfect.final_score)
