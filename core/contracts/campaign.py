# core/contracts/campaign.py — Campaign & StepPlan contracts

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional, Literal

from pydantic import BaseModel, Field


class ArtifactRef(BaseModel):
    step_id: str
    artifact_name: str


class CampaignLimits(BaseModel):
    max_steps: int = 10
    max_total_tool_calls: int = 500
    max_total_tokens: int = 2_000_000
    deadline_seconds: Optional[int] = None


class MissionStep(BaseModel):
    step_id: str
    description: str
    target_workflow: str
    capabilities_required: List[str]
    capabilities_optional: List[str] = []
    risk_flags: List[str] = []
    inputs_from: List[str] = []
    handoff_artifacts: List[ArtifactRef] = []
    exports: List[str] = []
    success_criteria: str
    budget_overrides: Dict[str, Any] = {}


class CampaignPlan(BaseModel):
    campaign_id: str
    objective: str
    assumptions: List[str]
    steps: List[MissionStep]
    limits: CampaignLimits = Field(default_factory=CampaignLimits)


class StepPlan(BaseModel):
    step_id: str
    workflow_id: str
    objective: str
    inputs: List[ArtifactRef] = []
    outputs_expected: List[ArtifactRef] = []
    capabilities_required: List[str] = []
    success_criteria: List[str]
    rollback_strategy: Literal["retry", "backtrack", "abort", "human_review"] = "backtrack"
    digest: str = ""

    def model_post_init(self, __context):
        if not self.digest:
            self.digest = self.compute_digest()

    def compute_digest(self) -> str:
        payload = {
            "step_id": self.step_id,
            "workflow_id": self.workflow_id,
            "objective": self.objective,
            "inputs": [i.model_dump() for i in self.inputs],
            "outputs_expected": [o.model_dump() for o in self.outputs_expected],
            "capabilities_required": list(self.capabilities_required),
            "success_criteria": list(self.success_criteria),
            "rollback_strategy": self.rollback_strategy,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()
