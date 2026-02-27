# tests/test_campaign_contracts.py — Tests for campaign contracts

from core.contracts.campaign import CampaignPlan, MissionStep, CampaignLimits, ArtifactRef, StepPlan


def test_campaign_plan_roundtrip():
    step = MissionStep(
        step_id="s1",
        description="do thing",
        target_workflow="coding",
        capabilities_required=["fs.read"],
        success_criteria="done",
    )
    plan = CampaignPlan(
        campaign_id="c1",
        objective="obj",
        assumptions=["a"],
        steps=[step],
    )
    data = plan.model_dump()
    plan2 = CampaignPlan.model_validate(data)
    assert plan2.campaign_id == "c1"
    assert plan2.steps[0].step_id == "s1"


def test_step_plan_digest():
    ref = ArtifactRef(step_id="s0", artifact_name="out.txt")
    step = StepPlan(
        step_id="s1",
        workflow_id="coding",
        objective="obj",
        inputs=[ref],
        outputs_expected=[ArtifactRef(step_id="s1", artifact_name="out2.txt")],
        capabilities_required=["fs.read"],
        success_criteria=["ok"],
    )
    assert step.digest
