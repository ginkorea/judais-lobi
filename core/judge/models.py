# core/judge/models.py — Data models for the Composite Judge and Candidate Sampling
#
# Phase 7.1: TierVerdict, TierResult, JudgeReport
# Phase 7.2: CandidateScore, CandidateReport

from enum import Enum
from typing import List

from pydantic import BaseModel


class TierVerdict(str, Enum):
    """Outcome of a single scoring tier.

    ``SKIPPED`` and ``UNKNOWN`` are both "no opinion", and they are kept
    apart because they mean different things to whoever reads the
    report: ``SKIPPED`` is *we chose not to run this* (an earlier tier
    short-circuited); ``UNKNOWN`` is *we ran it and it could not answer*
    (no backend configured, a refusal, an unparseable reply).  The
    second is a fact about the environment, and usually the thing to go
    fix.

    Neither contributes to the composite score, and — this is the part
    that matters — neither counts *against* it.  See
    ``CompositeJudge.evaluate``.
    """
    PASS = "pass"
    FAIL = "fail"
    WAIVED = "waived"
    SKIPPED = "skipped"
    UNKNOWN = "unknown"


#: Verdicts carrying no opinion. Their weight leaves the composite
#: denominator rather than being scored as a zero.
NO_OPINION = frozenset({TierVerdict.SKIPPED, TierVerdict.UNKNOWN})


class TierResult(BaseModel):
    """Result from a single evaluation tier."""
    tier_name: str
    verdict: TierVerdict
    score: float          # 0.0–1.0
    weight: float         # tier weight in composite formula
    details: str = ""
    short_circuit: bool = False  # if True, skip remaining tiers


class JudgeReport(BaseModel):
    """CRITIQUE phase output schema. Aggregated result from all tiers."""
    tier_results: List[TierResult]
    final_score: float    # weighted sum of tier scores
    verdict: str          # "pass" | "fail" | "needs_fix"
    summary: str = ""


class CandidateScore(BaseModel):
    """Score for a single candidate PatchSet."""
    candidate_index: int
    patch_set_id: str
    judge_report: JudgeReport
    worktree_diff: str = ""


class CandidateReport(BaseModel):
    """Aggregated report for all evaluated candidates. Stored in artifacts."""
    candidates: List[CandidateScore]
    winner_index: int = -1       # -1 = no winner
    total_evaluated: int = 0
