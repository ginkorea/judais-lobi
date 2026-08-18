# core/campaign/validator.py — Campaign and StepPlan validation

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from core.contracts.campaign import CampaignPlan, MissionStep, StepPlan
from core.kernel.workflows import select_workflow


class CampaignValidationError(ValueError):
    pass


def validate_campaign_plan(
    plan: CampaignPlan,
    known_workflows: Optional[Iterable[str]] = None,
) -> List[str]:
    """Every fault in *plan*, by name, in one pass.

    The one owner of what makes a campaign plan legal: unique and safe step
    ids, a real dependency for every ``inputs_from``, an exporter for every
    handoff reference, a relative and non-escaping path for every artifact
    name, a length inside ``limits.max_steps``, and no cycle.
    :class:`~core.runtime.campaign.CampaignRunner` is what reads it, at
    construction and again after a person edits a plan at HUMAN_REVIEW, and
    it has no second opinion about any of that.

    *known_workflows* is the one thing a caller legitimately supplies: what
    a step's ``target_workflow`` may name.  ``None`` — the default, and every
    caller before the ``Run`` path existed — means the kernel's installed
    :class:`~core.kernel.workflows.WorkflowTemplate`\\ s, checked through
    :func:`~core.kernel.workflows.select_workflow`.  A caller that hands in
    a collection means *these names and no others*: on the ``Run`` path a
    step names a **task template** out of a mission pack, which the kernel
    has never heard of.  The vocabulary is the caller's; the rules are this
    function's.
    """
    errors: List[str] = []
    vocabulary = (None if known_workflows is None
                  else {str(name) for name in known_workflows})

    if len(plan.steps) > plan.limits.max_steps:
        errors.append("max_steps_exceeded")

    if not _is_safe_id(plan.campaign_id):
        errors.append("unsafe_campaign_id")

    step_ids = [s.step_id for s in plan.steps]
    if len(step_ids) != len(set(step_ids)):
        errors.append("duplicate_step_ids")

    steps_by_id = {s.step_id: s for s in plan.steps}

    for step in plan.steps:
        if not _is_safe_id(step.step_id):
            errors.append(f"unsafe_step_id:{step.step_id}")
        if not step.success_criteria:
            errors.append(f"step_missing_success_criteria:{step.step_id}")
        # workflow existence — against the caller's vocabulary when it named
        # one, and against the kernel's installed templates otherwise.
        if vocabulary is not None:
            if step.target_workflow not in vocabulary:
                errors.append(f"unknown_workflow:{step.step_id}")
        else:
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


def toposort(plan: CampaignPlan) -> List[str]:
    """The plan's step ids in an order every dependency comes first in.

    Kahn's algorithm, and ties are broken by the plan's own order, so a
    plan whose steps are already in a valid order runs in exactly the order
    its author wrote — which is what somebody approving it read.

    Here, beside :func:`_has_cycle`, because the two are one fact about one
    graph: this returns an order and that returns whether one exists, and a
    second walk of the ``inputs_from`` edges living next to whichever runner
    happened to need it is how a campaign comes to dispatch in an order its
    validator never checked.  A plan with a cycle — refused by
    :func:`validate_campaign_plan` before anything gets this far — returns
    the steps it could order and drops the rest; there is nothing honest to
    do with a cycle here, and the refusal has already happened.
    """
    steps = {step.step_id: step for step in plan.steps}
    indegree: Dict[str, int] = {sid: 0 for sid in steps}
    for step in plan.steps:
        for dep in step.inputs_from:
            if dep in steps:
                indegree[step.step_id] += 1

    ready = [step.step_id for step in plan.steps
             if indegree[step.step_id] == 0]
    order: List[str] = []
    while ready:
        node = ready.pop(0)
        order.append(node)
        for step in plan.steps:
            if node in step.inputs_from and step.step_id in indegree:
                indegree[step.step_id] -= 1
                if indegree[step.step_id] == 0:
                    ready.append(step.step_id)
    return order


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


def _is_safe_id(value: str) -> bool:
    if not value:
        return False
    if len(value) > 64:
        return False
    return re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]*$", value) is not None
