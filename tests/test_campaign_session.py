# tests/test_campaign_session.py — a campaign's directories, written whole

"""The store a campaign leaves on disk, and that every write to it is atomic.

Named for ``CampaignOrchestrator`` until Phase 15, lane Q, and renamed with
it: that class walked a plan's DAG through the coding kernel's task
dispatcher while :mod:`core.runtime.swarm` walked one through
:class:`~core.runtime.run.Run`, and the second loop had the run store, the
approvals, the supervisor, the wire and the resume that the first did not.
A campaign is :class:`~core.runtime.campaign.CampaignRunner` now, and
``tests/test_campaign_run.py`` is what tests *running* one.

What is left here is what a campaign still owns and what those tests do not
reach: :class:`~core.campaign.session.CampaignSession`'s layout,
:class:`~core.campaign.session.StepSessionManager`'s artifacts and
checkpoints, :func:`~core.campaign.handoff.materialize_handoff` in
isolation, and :func:`~core.campaign.hitl.review_plan`.  The two
orchestrator tests went with the class — one ran it end to end, which
``tests/test_campaign_run.py`` now does against a real plane and a real
stream, and one proved every file it wrote arrived by ``os.replace``, which
is asserted below against the writers themselves rather than through a
runner that no longer calls them.
"""

import os
import shlex
import sys
from pathlib import Path

import pytest

from core.contracts.campaign import CampaignPlan, MissionStep, ArtifactRef


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


def test_a_campaign_session_lays_out_a_directory_per_step(tmp_path):
    """The layout every other reader of a campaign assumes: one directory
    per step, and inside it the two the handoff moves files between."""
    from core.campaign.session import CampaignSession

    session = CampaignSession(tmp_path, campaign_id="camp")
    step_dir = session.step_dir("s1")
    assert step_dir == tmp_path / "sessions" / "camp" / "steps" / "s1"
    for name in ("artifacts", "handoff_in", "handoff_out"):
        assert (step_dir / name).is_dir()


def test_a_step_id_that_would_escape_the_campaign_is_refused(tmp_path):
    """A step id names a directory, so it is checked where the directory is
    made and not only where the plan is validated."""
    from core.campaign.session import CampaignSession

    session = CampaignSession(tmp_path, campaign_id="camp")
    with pytest.raises(ValueError, match="unsafe_step_id"):
        session.step_dir("../elsewhere")


def test_a_handoff_moves_one_declared_artifact_between_two_steps(tmp_path):
    """The copy itself, in isolation from anything that runs a plan:
    ``handoff_out`` of the producer to ``handoff_in`` of the consumer, by
    name, and nothing else along for the ride."""
    from core.campaign.handoff import materialize_handoff
    from core.campaign.session import CampaignSession

    session = CampaignSession(tmp_path, campaign_id="camp")
    (session.step_dir("s1") / "handoff_out" / "out.txt").write_text("figures")
    (session.step_dir("s1") / "handoff_out" / "extra.txt").write_text("no")
    copied = materialize_handoff(
        session.campaign_dir, session.step_dir("s2"),
        [ArtifactRef(step_id="s1", artifact_name="out.txt")])

    assert [path.name for path in copied] == ["out.txt"]
    assert (session.step_dir("s2") / "handoff_in" / "out.txt").read_text() \
        == "figures"
    assert not (session.step_dir("s2") / "handoff_in" / "extra.txt").exists()


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

    def test_every_file_the_campaign_writers_write_arrives_by_replace(
            self, tmp_path, monkeypatch):
        """Not "the ones we remembered to convert": the files on the disk at
        the end, compared against the replaces that happened. A site left on
        `write_text` shows up here as a file nobody replaced.

        Against the writers themselves rather than through a runner. It used
        to drive ``CampaignOrchestrator``, which wrote every one of these;
        the runner that replaced it writes its own progress through the run
        store — ``tests/test_durable.py`` holds that one — and leaves these
        three to the campaign's own directory.
        """
        from core.campaign.session import CampaignSession, StepSessionManager
        from core.contracts.schemas import TaskContract

        replaced = []
        real = os.replace

        def watch(src, dst):
            replaced.append(Path(dst))
            return real(src, dst)

        monkeypatch.setattr(os, "replace", watch)
        session = CampaignSession(tmp_path, campaign_id="camp")
        session.write_campaign_file("campaign.json", one_step_plan())
        session.write_campaign_json("campaign.state.json", {"status": "ok"})
        StepSessionManager(session.step_dir("s1")).write_artifact(
            "INTAKE", 0, TaskContract(task_id="t1", description="first"))

        on_disk = sorted(p for p in tmp_path.rglob("*") if p.is_file())
        assert on_disk, "nothing was written, so this proves nothing"
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
