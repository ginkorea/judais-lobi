# tests/test_campaign_orchestrator.py — Tests for CampaignOrchestrator

from core.campaign.orchestrator import CampaignOrchestrator
from core.contracts.campaign import CampaignPlan, MissionStep, ArtifactRef
from core.kernel.orchestrator import PhaseResult


class StubDispatcher:
    def dispatch(self, phase, state):
        return PhaseResult(success=True)


def dispatcher_factory(step):
    return StubDispatcher()


def test_a_step_records_a_compaction_beside_its_artifacts(tmp_path):
    """`StepSessionManager` is `SessionManager`'s subset for one step, and
    a step whose prompts had to be shortened has to be able to say so.

    Written after the checkpoint and read after the rollback, because that
    is the sequence a failed RUN produces: the record lives beside the
    artifacts the rollback replaces, not among them.
    """
    from core.campaign.session import CampaignSession, StepSessionManager

    session = CampaignSession(tmp_path, campaign_id="camp")
    manager = StepSessionManager(session.step_dir("s1"))
    manager.checkpoint("pre_PATCH_000")
    path = manager.write_context_warning({"phase": "PATCH", "dropped_turns": 2})
    manager.rollback("pre_PATCH_000")

    assert path.exists()
    assert path.name == "context_warn_000.json"
    assert manager.load_context_warnings() == [
        {"phase": "PATCH", "dropped_turns": 2}]


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
