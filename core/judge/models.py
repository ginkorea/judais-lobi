# core/judge/models.py — Data models for the Composite Judge and Candidate Sampling
#
# Phase 7.1: TierVerdict, TierResult, JudgeReport
# Phase 7.2: CandidateScore, CandidateReport

from enum import Enum
from typing import List

from pydantic import BaseModel


class TierVerdict(str, Enum):
    """Outcome of a single scoring tier."""
    PASS = "pass"
    FAIL = "fail"
    WAIVED = "waived"
    SKIPPED = "skipped"


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
