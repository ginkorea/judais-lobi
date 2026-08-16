# tests/test_campaign_orchestrator.py — Tests for CampaignOrchestrator

import os
import shlex
import sys
from pathlib import Path

import pytest

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


def one_step_plan() -> CampaignPlan:
    return CampaignPlan(
        campaign_id="camp",
        objective="obj",
        assumptions=[],
        steps=[MissionStep(
            step_id="s1",
            description="step1",
            target_workflow="coding",
            capabilities_required=["fs.read"],
            success_criteria="done",
        )],
    )


class TestEveryFileACampaignLeavesBehindIsReplaced:
    """A campaign directory is a store, and every file in it is read back.

    The plan is read by the human who approves it, the step plan and the
    scope grant by the step that runs under them, the artifacts by the next
    step's handoff, the synthesis by whoever asks how it went. All of them
    were `path.write_text` — truncate, then fill — and a campaign is the
    longest-running thing this harness does, so it is the one most likely to
    be killed between the two.
    """

    def _explode(self, monkeypatch):
        def boom(src, dst):
            raise OSError("no space left on device")

        monkeypatch.setattr(os, "replace", boom)

    def test_every_file_a_run_writes_arrives_by_replace(self, tmp_path,
                                                        monkeypatch):
        """Not "the ones we remembered to convert": the files on the disk at
        the end, compared against the replaces that happened. A site left on
        `write_text` shows up here as a file nobody replaced."""
        replaced = []
        real = os.replace

        def watch(src, dst):
            replaced.append(Path(dst))
            return real(src, dst)

        monkeypatch.setattr(os, "replace", watch)
        orch = CampaignOrchestrator(dispatcher_factory, base_dir=tmp_path)
        orch.run(one_step_plan(), auto_approve=True)

        on_disk = sorted(p for p in tmp_path.rglob("*") if p.is_file())
        assert on_disk, "the run wrote nothing, so this proves nothing"
        assert sorted(replaced) == on_disk

    def test_a_failed_artifact_write_leaves_the_previous_one_whole(
            self, tmp_path, monkeypatch):
        from core.campaign.session import CampaignSession, StepSessionManager
        from core.contracts.schemas import TaskContract

        manager = StepSessionManager(
            CampaignSession(tmp_path, campaign_id="camp").step_dir("s1"))
        manager.write_artifact("INTAKE", 0, TaskContract(task_id="t1",
                                                         description="first"))
        self._explode(monkeypatch)
        with pytest.raises(OSError):
            manager.write_artifact("INTAKE", 0, TaskContract(
                task_id="t2", description="second"))
        assert manager.load_latest_artifact("INTAKE")["task_id"] == "t1"

    def test_a_failed_campaign_write_leaves_no_staging_file(self, tmp_path,
                                                            monkeypatch):
        from core.campaign.session import CampaignSession

        session = CampaignSession(tmp_path, campaign_id="camp")
        self._explode(monkeypatch)
        with pytest.raises(OSError):
            session.write_campaign_json("campaign.state.json", {"status": "x"})
        assert sorted(p.name for p in session.campaign_dir.iterdir()) == [
            "steps", "synthesis"]

    def test_a_checkpoint_copy_arrives_by_replace(self, tmp_path, monkeypatch):
        from core.campaign.session import CampaignSession, StepSessionManager
        from core.contracts.schemas import TaskContract

        manager = StepSessionManager(
            CampaignSession(tmp_path, campaign_id="camp").step_dir("s1"))
        artifact = manager.write_artifact("INTAKE", 0, TaskContract(
            task_id="t1", description="first"))

        replaced = []
        real = os.replace

        def watch(src, dst):
            replaced.append(Path(dst))
            return real(src, dst)

        monkeypatch.setattr(os, "replace", watch)
        checkpoint = manager.checkpoint("pre_PATCH_000")
        assert replaced == [checkpoint / "artifacts" / artifact.name]

    def test_a_rollback_restores_whole_artifacts_or_none(self, tmp_path,
                                                         monkeypatch):
        """The checkpoint copy is a store too: it is the only copy left after
        `rollback` has deleted the live artifacts."""
        from core.campaign.session import CampaignSession, StepSessionManager
        from core.contracts.schemas import TaskContract

        manager = StepSessionManager(
            CampaignSession(tmp_path, campaign_id="camp").step_dir("s1"))
        manager.write_artifact("INTAKE", 0, TaskContract(task_id="t1",
                                                         description="first"))
        manager.checkpoint("pre_PATCH_000")
        self._explode(monkeypatch)
        with pytest.raises(OSError):
            manager.rollback("pre_PATCH_000")
        assert manager.load_all_artifacts() == []

    def test_the_plan_handed_to_the_editor_is_replaced_not_truncated(
            self, tmp_path, monkeypatch):
        """`review_plan` writes the plan and then hands the path to another
        process — the one write in this repo whose reader is a human."""
        from core.campaign.hitl import review_plan

        replaced = []
        real = os.replace

        def watch(src, dst):
            replaced.append(Path(dst))
            return real(src, dst)

        monkeypatch.setattr(os, "replace", watch)
        path = tmp_path / "plan.json"
        back = review_plan(one_step_plan(), path,
                           editor=f"{shlex.quote(sys.executable)} -c pass")
        assert back.campaign_id == "camp"
        assert replaced == [path]
