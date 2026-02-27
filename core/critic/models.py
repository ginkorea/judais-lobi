# core/critic/models.py — Pydantic models for the External Critic

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class CriticVerdict(str, Enum):
    APPROVE = "approve"
    CAUTION = "caution"
    BLOCK = "block"
    REFUSED = "refused"
    UNAVAILABLE = "unavailable"


class CriticRisk(BaseModel):
    severity: str = "medium"  # low/medium/high/critical
    category: str = ""        # logic/security/performance/design
    description: str = ""
    affected_files: List[str] = []
    confidence: float = 0.5


class ExternalCriticReport(BaseModel):
    provider: str = ""
    model: str = ""
    verdict: CriticVerdict = CriticVerdict.UNAVAILABLE
    top_risks: List[CriticRisk] = []
    missing_tests: List[str] = []
    logic_concerns: List[str] = []
    suggested_plan_adjustments: List[str] = []
    suggested_patch_adjustments: List[str] = []
    questions_for_builder: List[str] = []
    confidence: float = 0.0
    raw_response: str = ""
    response_time_seconds: float = 0.0
    payload_hash: str = ""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AggregatedCriticReport(BaseModel):
    provider_reports: List[ExternalCriticReport] = []
    consensus_verdict: CriticVerdict = CriticVerdict.UNAVAILABLE
    all_risks: List[CriticRisk] = []
    all_missing_tests: List[str] = []
    all_logic_concerns: List[str] = []
    all_suggested_adjustments: List[str] = []
    mean_confidence: float = 0.0
    round_number: int = 0
    payload_hash: str = ""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CriticRoundSummary(BaseModel):
    round_number: int
    verdict: CriticVerdict
    unique_concerns_count: int
    new_concerns_count: int
    mean_confidence: float
    is_noise: bool = False


class CritiquePack(BaseModel):
    # Task info
    task_description: str = ""
    task_constraints: List[str] = []
    acceptance_criteria: List[str] = []
    # Plan
    plan_steps: List[Dict[str, Any]] = []
    plan_rationale: str = ""
    target_files: List[str] = []
    # RepoMap (signatures only)
    repo_map_excerpt: str = ""
    # Patch (diff stats + snippets)
    diff_summary: str = ""
    files_changed: int = 0
    lines_added: int = 0
    lines_removed: int = 0
    patch_snippets: List[Dict[str, str]] = []
    # Run
    tests_passed: Optional[bool] = None
    test_summary: str = ""
    # Local review
    local_review_verdict: str = ""
    local_review_summary: str = ""
    local_review_score: Optional[float] = None
    # Metadata
    trigger_reason: str = ""
    current_phase: str = ""
    iteration_count: int = 0


class CriticTriggerContext(BaseModel):
    current_phase: str
    next_phase: str
    total_iterations: int
    consecutive_fix_loops: int = 0
    files_changed_count: int = 0
    lines_changed_count: int = 0
    touches_security_surface: bool = False
    has_dependency_changes: bool = False
    local_reviewer_disagrees: bool = False
    critic_calls_this_session: int = 0
    max_calls_per_session: int = 10
