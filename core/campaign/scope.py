# core/campaign/scope.py — Effective scope intersection

"""Least privilege by intersection, in one function.

``ROADMAP.md`` §5.1, invariant 10: *"Every tool call passes through a scope
intersection … the LLM can never escalate through any layer — it can only
narrow."*  This module is that intersection, and it is deliberately the
only place the ``&`` is written: a step's permissions are computed from the
plan rather than requested at run time, and a second computation of them
somewhere else would be a second answer to what a step may do.

Two callers, one rule.  The kernel path intersects a
:class:`~core.kernel.workflows.WorkflowTemplate`'s required scopes with the
step's and with the current phase's; the ``Run`` path
(:class:`~core.runtime.campaign.CampaignRunner`) has no phases and no
kernel template — a campaign step there is a child :class:`~core.runtime
.run.Run` under a mission pack's task template — so it intersects the
template's declared scopes with the step's.  Both go through
:func:`effective_scopes`; :func:`compute_effective_scopes` is the kernel's
door onto it, unchanged in signature and in behaviour.
"""

from __future__ import annotations

from typing import Iterable, Optional, Set

from core.kernel.workflows import WorkflowTemplate


def effective_scopes(step_scopes: Optional[Iterable[str]],
                     *layers: Optional[Iterable[str]]) -> Set[str]:
    """*step_scopes* intersected with every layer that states one.

    The step is the first argument because it is the layer that is always
    present: a plan step names what it needs, and everything else is a
    ceiling above it that may or may not exist.  A layer of ``None`` states
    nothing and narrows nothing — which is different from a layer that
    states the empty set, and the difference matters: a task template with
    no ``scopes:`` key has no opinion, and one that declares none permits
    none.

    ``step_scopes`` of ``None`` means the step named nothing, and then the
    result is the intersection of the layers alone — the kernel's reading,
    where a step that declares no capabilities inherits the workflow's.
    """
    stated = [set(layer) for layer in layers if layer is not None]
    if step_scopes is None:
        if not stated:
            return set()
        first, *rest = stated
        result = set(first)
    else:
        result = {str(scope) for scope in step_scopes}
        rest = stated
    for layer in rest:
        result &= layer
    return result


def compute_effective_scopes(
    workflow: WorkflowTemplate,
    step_scopes: Optional[Iterable[str]],
    phase: str,
) -> Set[str]:
    """The kernel's intersection: workflow ∩ step ∩ phase.

    Through :func:`effective_scopes`, so the two paths cannot disagree
    about what an intersection is.  A phase the template says nothing about
    inherits the workflow's scopes, which is what a phase with no entry in
    ``phase_capabilities`` has always meant here.
    """
    workflow_scopes = set(workflow.required_scopes)
    phase_scopes = set(workflow.phase_capabilities.get(phase, workflow_scopes))
    return effective_scopes(
        workflow_scopes if step_scopes is None else step_scopes,
        workflow_scopes, phase_scopes)
