# core/campaign/validator.py — Campaign and StepPlan validation

from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from core.contracts.campaign import CampaignPlan, MissionStep, StepPlan
from core.kernel.workflows import select_workflow


class CampaignValidationError(ValueError):
    pass


def validate_campaign_plan(plan: CampaignPlan) -> List[str]:
    errors: List[str] = []

    if len(plan.steps) > plan.limits.max_steps:
        errors.append("max_steps_exceeded")

    step_ids = [s.step_id for s in plan.steps]
    if len(step_ids) != len(set(step_ids)):
        errors.append("duplicate_step_ids")

    steps_by_id = {s.step_id: s for s in plan.steps}

    for step in plan.steps:
        if not step.success_criteria:
            errors.append(f"step_missing_success_criteria:{step.step_id}")
        # workflow existence
        try:
            select_workflow(cli_flag=step.target_workflow)
        except Exception:
            errors.append(f"unknown_workflow:{step.step_id}")
        # inputs_from existence
        for dep in step.inputs_from:
            if dep not in steps_by_id:
                errors.append(f"missing_dependency:{step.step_id}:{dep}")
        # handoff artifact references
        for ref in step.handoff_artifacts:
            if ref.step_id not in steps_by_id:
                errors.append(f"missing_handoff_step:{step.step_id}:{ref.step_id}")
            else:
                exports = steps_by_id[ref.step_id].exports
                if exports and ref.artifact_name not in exports:
                    errors.append(
                        f"handoff_artifact_not_exported:{step.step_id}:{ref.step_id}:{ref.artifact_name}"
                    )
            if _is_unsafe_path(ref.artifact_name):
                errors.append(f"unsafe_handoff_path:{step.step_id}:{ref.artifact_name}")

    if _has_cycle(plan.steps):
        errors.append("campaign_dag_cycle")

    return errors


def validate_step_plan(step_plan: StepPlan, step_dir: Path) -> List[str]:
    errors: List[str] = []
    try:
        workflow = select_workflow(cli_flag=step_plan.workflow_id)
    except Exception:
        errors.append("unknown_workflow")
        return errors

    if step_plan.workflow_id != workflow.name:
        errors.append("workflow_id_mismatch")

    workflow_scopes = set(workflow.required_scopes)
    for scope in step_plan.capabilities_required:
        if scope not in workflow_scopes:
            errors.append(f"capability_not_in_workflow:{scope}")

    for ref in step_plan.outputs_expected:
        if ref.step_id != step_plan.step_id:
            errors.append(f"output_step_id_mismatch:{ref.step_id}")
        if _is_unsafe_path(ref.artifact_name):
            errors.append(f"unsafe_output_path:{ref.artifact_name}")

    for ref in step_plan.inputs:
        if _is_unsafe_path(ref.artifact_name):
            errors.append(f"unsafe_input_path:{ref.artifact_name}")

    # Enforce outputs under handoff_out/ (by convention, no absolute or ..)
    handoff_out = Path(step_dir) / "handoff_out"
    if handoff_out.exists():
        # Not enforcing filesystem presence, just path safety
        pass

    return errors


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _has_cycle(steps: Iterable[MissionStep]) -> bool:
    graph: Dict[str, List[str]] = {}
    for step in steps:
        graph[step.step_id] = list(step.inputs_from)

    visiting = set()
    visited = set()

    def visit(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        for dep in graph.get(node, []):
            if visit(dep):
                return True
        visiting.remove(node)
        visited.add(node)
        return False

    for node in graph:
        if visit(node):
            return True
    return False


def _is_unsafe_path(path: str) -> bool:
    if not path:
        return True
    p = Path(path)
    if p.is_absolute():
        return True
    if ".." in p.parts:
        return True
    return False
