# tests/test_judge_composite.py — Tests for core.judge.judge.CompositeJudge

import pytest

from core.judge.models import TierResult, TierVerdict, JudgeReport
from core.judge.tiers import BaseTier, TestTier, LintTier, LLMReviewTier
from core.judge.judge import CompositeJudge


class TestCompositeJudgeDefaults:
    """Default tier configuration: Test(0.6) + Lint(0.25) + LLMReview(0.15)."""

    def setup_method(self):
        self.judge = CompositeJudge()

    def test_default_tiers(self):
        tiers = self.judge.tiers
        assert len(tiers) == 3
        assert isinstance(tiers[0], TestTier)
        assert isinstance(tiers[1], LintTier)
        assert isinstance(tiers[2], LLMReviewTier)

    def test_all_pass(self):
        """Test pass + lint pass + LLM stub(0.5) → score ~0.925, pass."""
        r = self.judge.evaluate(test_exit_code=0, lint_exit_code=0)
        assert r.verdict == "pass"
        # 1.0*0.6 + 1.0*0.25 + 0.5*0.15 = 0.925
        assert r.final_score == pytest.approx(0.925, abs=1e-4)
        assert len(r.tier_results) == 3

    def test_test_fail_short_circuits(self):
        """Test fail → short-circuit, lint and LLM skipped."""
        r = self.judge.evaluate(test_exit_code=1, lint_exit_code=0)
        assert r.verdict == "fail"
        assert r.final_score == 0.0
        assert r.tier_results[0].verdict == TierVerdict.FAIL
        assert r.tier_results[1].verdict == TierVerdict.SKIPPED
        assert r.tier_results[2].verdict == TierVerdict.SKIPPED

    def test_test_pass_lint_fail(self):
        """Test pass + lint fail → score = 0.6 + 0.0 + 0.075 = 0.675."""
        r = self.judge.evaluate(test_exit_code=0, lint_exit_code=1)
        assert r.final_score == pytest.approx(0.675, abs=1e-4)
        assert r.verdict == "pass"  # >= 0.6

    def test_test_pass_lint_waived(self):
        """Test pass + lint waived(0.5) → score = 0.6 + 0.125 + 0.075 = 0.8."""
        r = self.judge.evaluate(test_exit_code=0, lint_exit_code=1,
                                lint_waive=True)
        assert r.final_score == pytest.approx(0.8, abs=1e-4)
        assert r.verdict == "pass"

    def test_result_is_judge_report(self):
        r = self.judge.evaluate(test_exit_code=0, lint_exit_code=0)
        assert isinstance(r, JudgeReport)

    def test_tier_results_have_correct_weights(self):
        r = self.judge.evaluate(test_exit_code=0, lint_exit_code=0)
        assert r.tier_results[0].weight == 0.6
        assert r.tier_results[1].weight == 0.25
        assert r.tier_results[2].weight == 0.15

    def test_score_rounded(self):
        """Score is rounded to 6 decimal places."""
        r = self.judge.evaluate(test_exit_code=0, lint_exit_code=0)
        assert r.final_score == round(r.final_score, 6)


class TestCompositeJudgeCustomTiers:
    """Custom tier configurations."""

    def test_empty_tiers(self):
        judge = CompositeJudge(tiers=[])
        r = judge.evaluate(test_exit_code=0)
        assert r.final_score == 0.0
        # No test tier → test_passed is False → "fail"
        assert r.verdict == "fail"
        assert len(r.tier_results) == 0

    def test_single_test_tier(self):
        judge = CompositeJudge(tiers=[TestTier()])
        r = judge.evaluate(test_exit_code=0)
        assert r.final_score == pytest.approx(0.6)
        assert r.verdict == "pass"

    def test_single_test_tier_fail(self):
        judge = CompositeJudge(tiers=[TestTier()])
        r = judge.evaluate(test_exit_code=1)
        assert r.final_score == 0.0
        assert r.verdict == "fail"

    def test_test_then_lint_only(self):
        judge = CompositeJudge(tiers=[TestTier(), LintTier()])
        r = judge.evaluate(test_exit_code=0, lint_exit_code=0)
        assert r.final_score == pytest.approx(0.85)
        assert r.verdict == "pass"

    def test_custom_tier(self):
        """Verify custom tiers integrate correctly."""

        class AlwaysPassTier(BaseTier):
            name = "custom"
            weight = 0.5

            def evaluate(self, **kw):
                return TierResult(tier_name=self.name, verdict=TierVerdict.PASS,
                                  score=1.0, weight=self.weight)

        judge = CompositeJudge(tiers=[TestTier(), AlwaysPassTier()])
        r = judge.evaluate(test_exit_code=0)
        # 1.0*0.6 + 1.0*0.5 = 1.1
        assert r.final_score == pytest.approx(1.1)
        assert r.verdict == "pass"

    def test_tiers_property_is_copy(self):
        judge = CompositeJudge()
        tiers = judge.tiers
        tiers.clear()
        assert len(judge.tiers) == 3  # Original unchanged


class TestCompositeJudgeVerdicts:
    """Edge cases for verdict computation."""

    def test_exactly_at_threshold(self):
        """Score exactly 0.6 → pass (>= 0.6)."""
        judge = CompositeJudge(tiers=[TestTier()])
        r = judge.evaluate(test_exit_code=0)
        # 1.0 * 0.6 = 0.6 exactly
        assert r.final_score == pytest.approx(0.6)
        assert r.verdict == "pass"

    def test_below_threshold_needs_fix(self):
        """Test passes but score < 0.6 → needs_fix."""

        class LowScoreTier(BaseTier):
            name = "test"
            weight = 0.5

            def evaluate(self, **kw):
                return TierResult(tier_name=self.name, verdict=TierVerdict.PASS,
                                  score=1.0, weight=self.weight)

        judge = CompositeJudge(tiers=[LowScoreTier()])
        r = judge.evaluate()
        # 1.0 * 0.5 = 0.5 < 0.6
        assert r.verdict == "needs_fix"

    def test_no_test_tier_means_fail(self):
        """If no tier named 'test', verdict is always 'fail'."""
        judge = CompositeJudge(tiers=[LintTier()])
        r = judge.evaluate(lint_exit_code=0)
        assert r.verdict == "fail"

    def test_multiple_short_circuits(self):
        """Only the first short-circuit matters; rest are skipped."""

        class AnotherShortCircuit(BaseTier):
            name = "blocker"
            weight = 0.1

            def evaluate(self, **kw):
                return TierResult(tier_name=self.name, verdict=TierVerdict.FAIL,
                                  score=0.0, weight=self.weight,
                                  short_circuit=True)

        judge = CompositeJudge(tiers=[
            TestTier(), AnotherShortCircuit(), LintTier(),
        ])
        # Test passes, then AnotherShortCircuit fires, LintTier skipped
        r = judge.evaluate(test_exit_code=0, lint_exit_code=0)
        assert r.tier_results[0].verdict == TierVerdict.PASS
        assert r.tier_results[1].verdict == TierVerdict.FAIL
        assert r.tier_results[2].verdict == TierVerdict.SKIPPED


class TestCompositeJudgeSerialization:
    """JudgeReport from evaluate() is serializable."""

    def test_roundtrip(self):
        judge = CompositeJudge()
        r = judge.evaluate(test_exit_code=0, lint_exit_code=0)
        d = r.model_dump()
        r2 = JudgeReport.model_validate(d)
        assert r2.final_score == r.final_score
        assert r2.verdict == r.verdict
        assert len(r2.tier_results) == 3

    def test_failed_report_roundtrip(self):
        judge = CompositeJudge()
        r = judge.evaluate(test_exit_code=1)
        d = r.model_dump()
        r2 = JudgeReport.model_validate(d)
        assert r2.verdict == "fail"
        assert r2.tier_results[1].verdict == TierVerdict.SKIPPED
