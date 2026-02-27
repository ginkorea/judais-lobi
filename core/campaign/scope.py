# core/campaign/scope.py — Effective scope intersection

from __future__ import annotations

from typing import Iterable, Optional, Set

from core.kernel.workflows import WorkflowTemplate


def compute_effective_scopes(
    workflow: WorkflowTemplate,
    step_scopes: Optional[Iterable[str]],
    phase: str,
) -> Set[str]:
    workflow_scopes = set(workflow.required_scopes)
    step_scope_set = set(step_scopes) if step_scopes is not None else set(workflow_scopes)
    phase_scopes = set(workflow.phase_capabilities.get(phase, workflow_scopes))
    return workflow_scopes & step_scope_set & phase_scopes
