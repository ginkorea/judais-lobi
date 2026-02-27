# core/critic/pack_builder.py — Build CritiquePack from SessionState

from __future__ import annotations

from typing import Dict, List, Optional

from core.contracts.schemas import ChangePlan, PatchSet, RunReport, TaskContract
from core.judge.models import JudgeReport
from core.critic.models import CritiquePack


class CritiquePackBuilder:
    """Assembles a minimal CritiquePack from session artifacts."""

    def build(self, state, trigger_reason: str, session_manager=None) -> CritiquePack:
        task = _load_artifact(session_manager, "CONTRACT") or _load_artifact(session_manager, "INTAKE")
        plan = _load_artifact(session_manager, "PLAN")
        repo_map = _load_artifact(session_manager, "REPO_MAP")
        retrieve = _load_artifact(session_manager, "RETRIEVE")
        patch = _load_artifact(session_manager, "PATCH")
        run = _load_artifact(session_manager, "RUN")
        critique = _load_artifact(session_manager, "CRITIQUE")

        task_model = TaskContract.model_validate(task) if task else None
        plan_model = ChangePlan.model_validate(plan) if plan else None
        patch_model = PatchSet.model_validate(patch) if patch else None
        run_model = RunReport.model_validate(run) if run else None
        critique_model = JudgeReport.model_validate(critique) if critique else None

        diff_summary, files_changed, lines_added, lines_removed, snippets = _summarize_patch(patch_model)

        test_summary = ""
        tests_passed = None
        if run_model is not None:
            tests_passed = run_model.passed
            test_summary = _truncate(_join_run_output(run_model), 500)

        pack = CritiquePack(
            task_description=(task_model.description if task_model else state.task_description),
            task_constraints=(task_model.constraints if task_model else []),
            acceptance_criteria=(task_model.acceptance_criteria if task_model else []),
            plan_steps=_plan_steps(plan_model),
            plan_rationale=(plan_model.rationale if plan_model else ""),
            target_files=(plan_model.target_files if plan_model else []),
            repo_map_excerpt=_repo_excerpt(repo_map, retrieve),
            diff_summary=diff_summary,
            files_changed=files_changed,
            lines_added=lines_added,
            lines_removed=lines_removed,
            patch_snippets=snippets,
            tests_passed=tests_passed,
            test_summary=test_summary,
            local_review_verdict=(critique_model.verdict if critique_model else ""),
            local_review_summary=(critique_model.summary if critique_model else ""),
            local_review_score=(critique_model.final_score if critique_model else None),
            trigger_reason=trigger_reason,
            current_phase=state.current_phase,
            iteration_count=state.total_iterations,
        )
        return pack


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_artifact(session_manager, phase_name: str) -> Optional[dict]:
    if session_manager is None:
        return None
    try:
        return session_manager.load_latest_artifact(phase_name)
    except Exception:
        return None


def _plan_steps(plan: Optional[ChangePlan]) -> List[Dict]:
    if plan is None:
        return []
    return [step.model_dump() for step in plan.steps]


def _repo_excerpt(repo_map: Optional[dict], retrieve: Optional[dict]) -> str:
    if isinstance(repo_map, dict) and repo_map.get("excerpt"):
        return repo_map.get("excerpt", "")
    if isinstance(retrieve, dict) and retrieve.get("repo_map_excerpt"):
        return retrieve.get("repo_map_excerpt", "")
    return ""


def _summarize_patch(patch: Optional[PatchSet]):
    if patch is None:
        return "", 0, 0, 0, []
    files_changed = len(patch.patches)
    lines_added = 0
    lines_removed = 0
    snippets = []

    for file_patch in patch.patches:
        added = 0
        removed = 0
        if file_patch.action == "modify":
            added = _line_count(file_patch.replace_block)
            removed = _line_count(file_patch.search_block)
        elif file_patch.action == "create":
            added = _line_count(file_patch.replace_block)
        elif file_patch.action == "delete":
            removed = _line_count(file_patch.search_block)

        lines_added += added
        lines_removed += removed

        snippet_source = file_patch.replace_block or file_patch.search_block
        snippets.append({
            "file_path": file_patch.file_path,
            "action": file_patch.action,
            "snippet": _truncate(snippet_source, 200),
        })

    diff_summary = f"files={files_changed} +{lines_added} -{lines_removed}"
    return diff_summary, files_changed, lines_added, lines_removed, snippets


def _line_count(text: str) -> int:
    if not text:
        return 0
    return len(text.splitlines())


def _truncate(text: str, limit: int) -> str:
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def _join_run_output(run: RunReport) -> str:
    parts = []
    if run.stdout:
        parts.append(run.stdout)
    if run.stderr:
        parts.append(run.stderr)
    return "\n".join(parts).strip()
