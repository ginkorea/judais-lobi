# tests/test_campaign_validator.py — Tests for campaign validators

from pathlib import Path

from core.contracts.campaign import CampaignPlan, MissionStep, ArtifactRef, StepPlan
from core.campaign.validator import validate_campaign_plan, validate_step_plan


def test_campaign_validator_ok():
    steps = [
        MissionStep(
            step_id="s1",
            description="step1",
            target_workflow="coding",
            capabilities_required=["fs.read"],
            success_criteria="done",
            exports=["out.txt"],
        ),
        MissionStep(
            step_id="s2",
            description="step2",
            target_workflow="coding",
            capabilities_required=["fs.read"],
            success_criteria="done",
            inputs_from=["s1"],
            handoff_artifacts=[ArtifactRef(step_id="s1", artifact_name="out.txt")],
        ),
    ]
    plan = CampaignPlan(
        campaign_id="c1",
        objective="obj",
        assumptions=[],
        steps=steps,
    )
    errors = validate_campaign_plan(plan)
    assert errors == []


def test_campaign_validator_cycle():
    steps = [
        MissionStep(
            step_id="a",
            description="a",
            target_workflow="coding",
            capabilities_required=["fs.read"],
            success_criteria="done",
            inputs_from=["b"],
        ),
        MissionStep(
            step_id="b",
            description="b",
            target_workflow="coding",
            capabilities_required=["fs.read"],
            success_criteria="done",
            inputs_from=["a"],
        ),
    ]
    plan = CampaignPlan(
        campaign_id="c1",
        objective="obj",
        assumptions=[],
        steps=steps,
    )
    errors = validate_campaign_plan(plan)
    assert "campaign_dag_cycle" in errors


def test_step_plan_validation():
    step_plan = StepPlan(
        step_id="s1",
        workflow_id="coding",
        objective="obj",
        inputs=[ArtifactRef(step_id="s0", artifact_name="in.txt")],
        outputs_expected=[ArtifactRef(step_id="s1", artifact_name="out.txt")],
        capabilities_required=["fs.read"],
        success_criteria=["ok"],
    )
    errors = validate_step_plan(step_plan, Path("/tmp/step"))
    assert errors == []
