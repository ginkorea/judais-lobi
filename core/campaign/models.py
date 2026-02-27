# core/campaign/models.py — Campaign orchestration state

from __future__ import annotations

from enum import Enum
from typing import Dict, Optional

from pydantic import BaseModel

from core.contracts.campaign import CampaignPlan, MissionStep, StepPlan, CampaignLimits, ArtifactRef


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class CampaignState(BaseModel):
    campaign_id: str
    status: str = "pending"
    current_step: Optional[str] = None
    step_status: Dict[str, StepStatus] = {}


__all__ = [
    "CampaignPlan",
    "MissionStep",
    "StepPlan",
    "CampaignLimits",
    "ArtifactRef",
    "CampaignState",
    "StepStatus",
]
