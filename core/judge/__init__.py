# core/judge/__init__.py — Composite Judge & Candidate Sampling (Phase 7.1-7.2)
#
# Lightweight imports (models, tiers, judge) are eager.
# CandidateManager is lazy to avoid the circular import through
# core.contracts.schemas → core.judge.models → core.patch.engine.
#
# There is no GPUProfile here any more. There were two of them: this package's
# always said "cpu_only" and had no caller at all, while core.runtime.gpu
# detects honestly and feeds ContextWindowManager. Two types with one name is
# a coin flip at every import site, so the unused liar was deleted. Ask
# core.runtime.detect_gpu_profile(). See tests/test_one_gpu_profile.py.

from core.judge.models import (
    TierVerdict,
    TierResult,
    JudgeReport,
    CandidateScore,
    CandidateReport,
)
from core.judge.tiers import BaseTier, TestTier, LintTier, LLMReviewTier
from core.judge.judge import CompositeJudge


def __getattr__(name):
    """Lazy imports for heavy modules that would cause circular imports."""
    if name == "CandidateManager":
        from core.judge.candidates import CandidateManager
        return CandidateManager
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # Models
    "TierVerdict",
    "TierResult",
    "JudgeReport",
    "CandidateScore",
    "CandidateReport",
    # Tiers
    "BaseTier",
    "TestTier",
    "LintTier",
    "LLMReviewTier",
    # Judge
    "CompositeJudge",
    # Candidates (lazy)
    "CandidateManager",
]
