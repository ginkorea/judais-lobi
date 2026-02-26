# core/judge/tiers.py — Scoring tiers for the Composite Judge
#
# Phase 7.1: TestTier (hard pass/fail), LintTier (soft-block), LLMReviewTier (stub)
#
# Each tier is pure logic: receives verification results as kwargs, returns TierResult.
# No subprocess calls, no ToolBus dependency — the caller runs tools and passes results.

from abc import ABC, abstractmethod

from core.judge.models import TierResult, TierVerdict


class BaseTier(ABC):
    """Base class for scoring tiers."""
    name: str = ""
    weight: float = 0.0

    @abstractmethod
    def evaluate(self, **kwargs) -> TierResult:
        """Evaluate this tier. kwargs contain verification results."""
        ...


class TestTier(BaseTier):
    """Hard pass/fail based on test suite exit code.

    Weight: 0.6. Short-circuits on failure (remaining tiers skipped).
    """
    name = "test"
    weight = 0.6

    def evaluate(self, *, test_exit_code: int = 1,
                 test_stdout: str = "", test_stderr: str = "",
                 **kw) -> TierResult:
        if test_exit_code == 0:
            return TierResult(
                tier_name=self.name,
                verdict=TierVerdict.PASS,
                score=1.0,
                weight=self.weight,
                details=test_stdout[:200] if test_stdout else "all tests passed",
            )
        return TierResult(
            tier_name=self.name,
            verdict=TierVerdict.FAIL,
            score=0.0,
            weight=self.weight,
            details=(test_stderr or test_stdout)[:200],
            short_circuit=True,
        )


class LintTier(BaseTier):
    """Soft-block based on linter exit code.

    Weight: 0.25. Does not short-circuit.
    Supports lint waive: score 0.5 instead of 0.0 when waived.
    """
    name = "lint"
    weight = 0.25

    def evaluate(self, *, lint_exit_code: int = 1,
                 lint_stdout: str = "", lint_waive: bool = False,
                 **kw) -> TierResult:
        if lint_exit_code == 0:
            return TierResult(
                tier_name=self.name,
                verdict=TierVerdict.PASS,
                score=1.0,
                weight=self.weight,
                details="lint clean",
            )
        if lint_waive:
            return TierResult(
                tier_name=self.name,
                verdict=TierVerdict.WAIVED,
                score=0.5,
                weight=self.weight,
                details=lint_stdout[:200] if lint_stdout else "lint issues waived",
            )
        return TierResult(
            tier_name=self.name,
            verdict=TierVerdict.FAIL,
            score=0.0,
            weight=self.weight,
            details=lint_stdout[:200] if lint_stdout else "lint failed",
        )


class LLMReviewTier(BaseTier):
    """Tiebreaker via LLM review. Stub: always returns 0.5.

    Weight: 0.15. Real LLM call deferred to a future phase.
    """
    name = "llm_review"
    weight = 0.15

    def evaluate(self, **kw) -> TierResult:
        return TierResult(
            tier_name=self.name,
            verdict=TierVerdict.PASS,
            score=0.5,
            weight=self.weight,
            details="stub: no LLM review performed",
        )
