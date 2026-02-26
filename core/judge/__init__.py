# core/judge/__init__.py — Composite Judge & Candidate Sampling (Phase 7.1-7.2)
#
# Lightweight imports (models, tiers, judge) are eager.
# Heavy imports (candidates, gpu_profile) are lazy to avoid circular import
# with core.contracts.schemas → core.judge.models → core.patch.engine chain.

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
    if name == "GPUProfile":
        from core.judge.gpu_profile import GPUProfile
        return GPUProfile
    if name == "detect_profile":
        from core.judge.gpu_profile import detect_profile
        return detect_profile
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
    # GPU Profile (lazy)
    "GPUProfile",
    "detect_profile",
]
