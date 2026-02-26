# core/judge/judge.py — CompositeJudge: multi-tier scoring with short-circuit
#
# Phase 7.1: Sequences tiers, computes weighted score, returns JudgeReport.
# Pure logic — no tool calls, no subprocess. Trivially testable.

from typing import List, Optional

from core.judge.models import TierResult, TierVerdict, JudgeReport
from core.judge.tiers import BaseTier, TestTier, LintTier, LLMReviewTier


class CompositeJudge:
    """Multi-tier deterministic judge.

    Default tiers: TestTier(0.6) → LintTier(0.25) → LLMReviewTier(0.15).
    On short-circuit, remaining tiers are marked SKIPPED with score 0.0.

    Verdict logic:
      - test failed → "fail"
      - score >= 0.6 AND test passed → "pass"
      - score < 0.6 AND test passed → "needs_fix"
    """

    def __init__(self, tiers: Optional[List[BaseTier]] = None):
        self._tiers = tiers if tiers is not None else [
            TestTier(), LintTier(), LLMReviewTier(),
        ]

    @property
    def tiers(self) -> List[BaseTier]:
        return list(self._tiers)

    def evaluate(self, **kwargs) -> JudgeReport:
        """Run all tiers in sequence. Stop on short_circuit."""
        results: List[TierResult] = []
        short_circuited = False

        for tier in self._tiers:
            if short_circuited:
                results.append(TierResult(
                    tier_name=tier.name,
                    verdict=TierVerdict.SKIPPED,
                    score=0.0,
                    weight=tier.weight,
                    details="skipped due to short-circuit",
                ))
                continue
            result = tier.evaluate(**kwargs)
            results.append(result)
            if result.short_circuit:
                short_circuited = True

        final_score = sum(r.score * r.weight for r in results)
        verdict = self._compute_verdict(results, final_score)
        return JudgeReport(
            tier_results=results,
            final_score=round(final_score, 6),
            verdict=verdict,
        )

    def _compute_verdict(
        self, results: List[TierResult], score: float
    ) -> str:
        """Determine verdict from tier results and composite score."""
        test_result = next(
            (r for r in results if r.tier_name == "test"), None
        )
        test_passed = (
            test_result is not None
            and test_result.verdict == TierVerdict.PASS
        )
        if not test_passed:
            return "fail"
        if score >= 0.6:
            return "pass"
        return "needs_fix"
