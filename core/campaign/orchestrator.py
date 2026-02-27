# core/campaign/orchestrator.py — Tier 0 Campaign Orchestrator

from __future__ import annotations

import time
from typing import Callable, Dict, List, Optional

from core.campaign.handoff import materialize_handoff
from core.campaign.hitl import review_plan
from core.campaign.models import CampaignState, StepStatus
from core.campaign.session import CampaignSession, StepSessionManager
from core.campaign.validator import validate_campaign_plan, validate_step_plan
from core.contracts.campaign import CampaignPlan, StepPlan, ArtifactRef
from core.kernel import Orchestrator
from core.kernel.workflows import select_workflow


class CampaignOrchestrator:
    """Orchestrates multi-step CampaignPlan execution."""

    def __init__(
        self,
        dispatcher_factory: Callable,
        base_dir,
        tool_bus=None,
        budget=None,
    ):
        self._dispatcher_factory = dispatcher_factory
        self._base_dir = base_dir
        self._tool_bus = tool_bus
        self._budget = budget

    def run(
        self,
        plan: CampaignPlan,
        auto_approve: bool = False,
        editor: Optional[str] = None,
    ) -> CampaignState:
        errors = validate_campaign_plan(plan)
        if errors:
            raise ValueError(f"Invalid campaign plan: {errors}")

        session = CampaignSession(self._base_dir, campaign_id=plan.campaign_id)
        session.write_campaign_file("campaign.json", plan)

        if not auto_approve:
            plan = review_plan(plan, session.campaign_dir / "campaign.plan.json", editor=editor)
            errors = validate_campaign_plan(plan)
            if errors:
                raise ValueError(f"Invalid campaign plan after review: {errors}")
            session.write_campaign_file("campaign.json", plan)

        state = CampaignState(campaign_id=plan.campaign_id, status="running")
        for step in plan.steps:
            state.step_status[step.step_id] = StepStatus.PENDING

        steps_by_id = {s.step_id: s for s in plan.steps}
        ordered = _toposort(plan)
        started_at = time.monotonic()
        deadline = plan.limits.deadline_seconds

        for step_id in ordered:
            if deadline is not None and (time.monotonic() - started_at) > deadline:
                state.status = "halted"
                break

            step = steps_by_id[step_id]
            state.current_step = step_id
            state.step_status[step_id] = StepStatus.RUNNING

            step_dir = session.step_dir(step_id)
            materialize_handoff(session.campaign_dir, step_dir, step.handoff_artifacts)

            workflow = select_workflow(cli_flag=step.target_workflow)
            step_plan = _build_step_plan(step, workflow.name)
            errors = validate_step_plan(step_plan, step_dir)
            if errors:
                state.step_status[step_id] = StepStatus.FAILED
                raise ValueError(f"Invalid step plan: {errors}")

            (step_dir / "step_plan.json").write_text(step_plan.model_dump_json(indent=2))

            scope_grant = _scope_grant_payload(step_plan, workflow.required_scopes)
            (step_dir / "scope_grant.json").write_text(scope_grant)

            step_session = StepSessionManager(step_dir=step_dir)
            orchestrator = Orchestrator(
                dispatcher=self._dispatcher_factory(step),
                budget=self._budget,
                session_manager=step_session,
                tool_bus=self._tool_bus,
                workflow=workflow,
                step_scopes=step_plan.capabilities_required,
            )
            result = orchestrator.run(step.description)
            if result.current_phase == "HALTED":
                state.step_status[step_id] = StepStatus.FAILED
                state.status = "halted"
                break

            state.step_status[step_id] = StepStatus.COMPLETED

        if state.status != "halted":
            state.status = "completed"

        session.write_campaign_file("campaign.state.json", state)
        _write_synthesis(session, state, plan)
        return state


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _toposort(plan: CampaignPlan) -> List[str]:
    steps = {s.step_id: s for s in plan.steps}
    indeg: Dict[str, int] = {sid: 0 for sid in steps}
    for s in plan.steps:
        for dep in s.inputs_from:
            indeg[s.step_id] += 1

    ready = [sid for sid, d in indeg.items() if d == 0]
    order: List[str] = []

    while ready:
        node = ready.pop(0)
        order.append(node)
        for s in plan.steps:
            if node in s.inputs_from:
                indeg[s.step_id] -= 1
                if indeg[s.step_id] == 0:
                    ready.append(s.step_id)

    return order


def _build_step_plan(step, workflow_id: str) -> StepPlan:
    inputs = list(step.handoff_artifacts)
    outputs = [
        ArtifactRef(step_id=step.step_id, artifact_name=name)
        for name in step.exports
    ]
    return StepPlan(
        step_id=step.step_id,
        workflow_id=workflow_id,
        objective=step.description,
        inputs=inputs,
        outputs_expected=outputs,
        capabilities_required=list(step.capabilities_required),
        success_criteria=[step.success_criteria],
    )


def _scope_grant_payload(step_plan: StepPlan, workflow_scopes: List[str]) -> str:
    requested = set(step_plan.capabilities_required)
    allowed = set(workflow_scopes)
    granted = sorted(requested & allowed)
    denied = sorted(requested - allowed)
    payload = {
        "step_id": step_plan.step_id,
        "requested_scopes": sorted(requested),
        "granted_scopes": granted,
        "denied_scopes": denied,
    }
    import json
    return json.dumps(payload, indent=2)


def _write_synthesis(session: CampaignSession, state: CampaignState, plan: CampaignPlan) -> None:
    import json
    payload = {
        "campaign_id": state.campaign_id,
        "status": state.status,
        "steps": {k: v.value for k, v in state.step_status.items()},
        "objective": plan.objective,
    }
    path = session.synthesis_dir / "summary.json"
    path.write_text(json.dumps(payload, indent=2))
