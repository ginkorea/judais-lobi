# core/judge/__init__.py — Composite Judge & Candidate Sampling (Phase 7.1-7.2)
#
# Lightweight imports (models, tiers, judge) are eager.
# CandidateManager is lazy to avoid the circular import through
# core.contracts.schemas → core.judge.models → core.patch.engine.
#
# There is no GPUProfile here, and as of 0.9.0 there is no longer one
# anywhere. There were two: this package's always said "cpu_only" and had no
# caller at all, and core.runtime.gpu probed the client's devices to cap the
# context window. The first was deleted as an unused liar; the second went
# with the cap it fed, because how many candidates may run at once and how
# long a context is accepted are both properties of the serving layer, not of
# the device list on the machine that happens to be holding the CLI.

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
