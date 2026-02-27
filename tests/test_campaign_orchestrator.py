# tests/test_campaign_orchestrator.py — Tests for CampaignOrchestrator

from core.campaign.orchestrator import CampaignOrchestrator
from core.contracts.campaign import CampaignPlan, MissionStep, ArtifactRef
from core.kernel.orchestrator import PhaseResult


class StubDispatcher:
    def dispatch(self, phase, state):
        return PhaseResult(success=True)


def dispatcher_factory(step):
    return StubDispatcher()


def test_campaign_orchestrator_runs(tmp_path):
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
        campaign_id="camp",
        objective="obj",
        assumptions=[],
        steps=steps,
    )

    orch = CampaignOrchestrator(dispatcher_factory, base_dir=tmp_path)
    state = orch.run(plan, auto_approve=True)
    assert state.status == "completed"
    assert (tmp_path / "sessions" / "camp" / "steps" / "s1").exists()
