# tests/test_critic_pack_builder.py — Tests for core.critic.pack_builder

from core.critic.pack_builder import CritiquePackBuilder
from core.kernel.state import SessionState
from core.sessions.manager import SessionManager
from core.contracts.schemas import TaskContract, ChangePlan, PlanStep, PatchSet, FilePatch, RunReport
from core.context.models import RepoMapResult
from core.judge.models import JudgeReport, TierResult, TierVerdict


def test_pack_builder_basic(tmp_path):
    sm = SessionManager(base_dir=tmp_path, session_id="pack-001")

    sm.write_artifact("CONTRACT", 0, TaskContract(task_id="t1", description="task"))
    sm.write_artifact("PLAN", 1, ChangePlan(task_id="t1", steps=[
        PlanStep(description="edit", target_file="a.py", action="modify")
    ], target_files=["a.py"], rationale="do thing"))
    sm.write_artifact("REPO_MAP", 2, RepoMapResult(excerpt="sig A"))
    sm.write_artifact("PATCH", 3, PatchSet(task_id="t1", patches=[
        FilePatch(file_path="a.py", search_block="x", replace_block="y", action="modify")
    ]))
    sm.write_artifact("RUN", 4, RunReport(exit_code=0, passed=True, stdout="ok"))
    judge = JudgeReport(tier_results=[
        TierResult(tier_name="test", verdict=TierVerdict.PASS, score=1.0, weight=1.0)
    ], final_score=1.0, verdict="pass", summary="good")
    sm.write_artifact("CRITIQUE", 5, judge)

    state = SessionState(task_description="task")
    pack = CritiquePackBuilder().build(state, "after_plan", sm)

    assert pack.task_description == "task"
    assert pack.plan_steps
    assert pack.repo_map_excerpt == "sig A"
    assert pack.diff_summary.startswith("files=")
    assert pack.files_changed == 1
    assert pack.lines_added == 1
    assert pack.lines_removed == 1
    assert pack.tests_passed is True
    assert pack.local_review_verdict == "pass"
