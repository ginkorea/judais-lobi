# core/judge/judge.py — CompositeJudge: multi-tier scoring with short-circuit
#
# Phase 7.1: Sequences tiers, computes weighted score, returns JudgeReport.
# Pure logic — no tool calls, no subprocess. Trivially testable.

from typing import List, Optional

from core.judge.models import NO_OPINION, TierResult, TierVerdict, JudgeReport
from core.judge.tiers import BaseTier, TestTier, LintTier, LLMReviewTier


class CompositeJudge:
    """Multi-tier deterministic judge.

    Default tiers: TestTier(0.6) → LintTier(0.25) → LLMReviewTier(0.15).
    On short-circuit, remaining tiers are marked SKIPPED.

    **A tier with no opinion does not vote, and is not voted against.**
    SKIPPED and UNKNOWN results have their weight taken out of the
    denominator and the remainder rescaled to the full available weight,
    so a run whose reviewer was unreachable scores exactly what its two
    real tiers say it does.

    The alternative — score the silent tier 0.0 and keep its weight — is
    what the old flat ``0.5`` stub existed to paper over: without a
    fabricated midpoint, an absent reviewer would have quietly docked
    every change 15% and pushed borderline work to ``needs_fix`` for a
    reason no line of the report gave. Rescaling removes the need for
    the lie rather than preserving it.

    Weights are *not* required to sum to 1.0 — a caller may pass its own
    tiers — so the rescale preserves the total available weight instead
    of normalising to one. With nothing missing it is a no-op, and the
    arithmetic is exactly what it always was.

    Verdict logic (unchanged):
      - test did not pass → "fail"
      - score >= 0.6 AND test passed → "pass"
      - score < 0.6 AND test passed → "needs_fix"

    A test tier returning UNKNOWN is therefore "fail": a gate that could
    not run its tests must not answer "pass", and the tier result records
    UNKNOWN so the reason is on the report rather than inferred from a
    number.
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

        final_score = self._composite(results)
        verdict = self._compute_verdict(results, final_score)
        return JudgeReport(
            tier_results=results,
            final_score=round(final_score, 6),
            verdict=verdict,
        )

    @staticmethod
    def _composite(results: List[TierResult]) -> float:
        """Weighted score over the tiers that actually had an opinion.

        Returns 0.0 when nothing did — which the verdict then reads as
        "fail", because a judge that learned nothing must not pass a
        change.
        """
        total_weight = sum(r.weight for r in results)
        answered = [r for r in results if r.verdict not in NO_OPINION]
        answered_weight = sum(r.weight for r in answered)
        if answered_weight <= 0:
            return 0.0
        raw = sum(r.score * r.weight for r in answered)
        return raw * (total_weight / answered_weight)

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
