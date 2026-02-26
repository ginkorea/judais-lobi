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

    def test_stub_returns_half(self):
        r = self.tier.evaluate()
        assert r.verdict == TierVerdict.PASS
        assert r.score == 0.5
        assert "stub" in r.details

    def test_ignores_all_kwargs(self):
        r = self.tier.evaluate(test_exit_code=0, lint_exit_code=0,
                               arbitrary="value")
        assert r.score == 0.5

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
