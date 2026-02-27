# core/kernel/orchestrator.py — Main orchestration loop
#
# Phase 7.0: Orchestrator accepts a WorkflowTemplate and delegates all phase
# logic to it. No hardcoded phase names, transitions, or branching rules.

import logging
from dataclasses import dataclass
from typing import Any, Optional, Protocol

from core.kernel.state import Phase, SessionState, InvalidTransition
from core.kernel.budgets import BudgetConfig, BudgetExhausted, check_all_budgets

logger = logging.getLogger(__name__)


@dataclass
class PhaseResult:
    """Outcome of executing a single phase."""
    success: bool
    output: Any = None
    error: Optional[str] = None
    needs_fix: bool = False


class RoleDispatcher(Protocol):
    """Protocol for phase-specific role execution.

    Implementations are injected into the Orchestrator.
    Phase arg is a string (workflow-defined phase name).
    """

    def dispatch(self, phase: str, state: SessionState) -> PhaseResult: ...


class Orchestrator:
    """Drives the kernel state machine through all phases.

    Phase 7.0: All phase logic comes from the injected WorkflowTemplate.
    The orchestrator is workflow-agnostic — it reads phase_order, branch_rules,
    and terminal_phases from the template.
    """

    def __init__(
        self,
        dispatcher: RoleDispatcher,
        budget: Optional[BudgetConfig] = None,
        session_manager=None,
        tool_bus=None,
        workflow=None,
        critic=None,
    ):
        self._dispatcher = dispatcher
        self._budget = budget or BudgetConfig()
        self._session_manager = session_manager
        self._tool_bus = tool_bus
        self._artifact_sequence = 0
        self._critic = critic

        # Lazy import to avoid circular dependency
        if workflow is None:
            from core.kernel.workflows import get_coding_workflow
            workflow = get_coding_workflow()
        self._workflow = workflow

    def run(self, task: str) -> SessionState:
        """Execute a complete task through the state machine.

        Returns the final SessionState (COMPLETED or HALTED).
        """
        state = SessionState(
            task_description=task,
            current_phase=self._workflow.phases[0],
            _transitions=self._workflow.transitions,
        )

        if self._session_manager is not None:
            state.session_id = self._session_manager.session_id
            state.session_dir = self._session_manager.session_dir

        while not self._is_terminal(state.current_phase):
            try:
                check_all_budgets(state, self._budget)

                # Checkpoint before PATCH for rollback on RUN failure
                if (state.current_phase == Phase.PATCH
                        and self._session_manager is not None):
                    label = f"pre_PATCH_{state.total_iterations:03d}"
                    self._session_manager.checkpoint(label)
                    state.artifacts["_last_patch_checkpoint"] = label

                result = self._execute_phase(state)

                # Validate and record artifact if session_manager present
                if result.success and self._session_manager is not None:
                    validation_result = self._validate_and_record(state, result)
                    if validation_result is not None:
                        result = validation_result

                # On RUN failure, attempt rollback to pre-PATCH checkpoint
                if (state.current_phase == Phase.RUN
                        and not result.success
                        and self._session_manager is not None):
                    checkpoint_label = state.artifacts.get("_last_patch_checkpoint")
                    if checkpoint_label:
                        try:
                            self._session_manager.rollback(checkpoint_label)
                            logger.info("Rolled back to checkpoint: %s", checkpoint_label)
                        except FileNotFoundError:
                            logger.warning("Checkpoint %s not found for rollback", checkpoint_label)

                self._maybe_invoke_critic(state, result)

                next_phase = self._select_next_phase(state, result)
                if next_phase is not None:
                    state.enter_phase(next_phase)
            except BudgetExhausted as exc:
                logger.warning("Budget exhausted: %s", exc)
                state.halt(str(exc))
            except InvalidTransition as exc:
                logger.error("Invalid transition: %s", exc)
                state.halt(str(exc))

        return state

    def _execute_phase(self, state: SessionState) -> PhaseResult:
        """Dispatch current phase to the role handler."""
        phase_name = state.current_phase
        if hasattr(phase_name, 'name'):
            phase_name = phase_name.name
        logger.info("Executing phase: %s", phase_name)
        result = self._dispatcher.dispatch(state.current_phase, state)
        if not isinstance(result, PhaseResult):
            result = PhaseResult(success=True, output=result)
        if not result.success:
            retry_count = state.record_phase_retry(state.current_phase)
            logger.info(
                "Phase %s failed (retry %d/%d): %s",
                phase_name,
                retry_count,
                self._budget.max_phase_retries,
                result.error,
            )
        return result

    def _validate_and_record(self, state: SessionState, result: PhaseResult) -> Optional[PhaseResult]:
        """Validate phase output against schema, write artifact if valid.

        Returns None if validation succeeds (or no schema).
        Returns a failed PhaseResult if validation fails (burns a retry).
        """
        from core.contracts.validation import get_schema_for_phase, validate_phase_output

        schema = get_schema_for_phase(
            state.current_phase,
            phase_schemas=self._workflow.phase_schemas,
        )
        if schema is None:
            return None

        if result.output is None:
            return None

        phase_name = state.current_phase
        if hasattr(phase_name, 'name'):
            phase_name = phase_name.name

        try:
            validated = validate_phase_output(
                state.current_phase, result.output,
                phase_schemas=self._workflow.phase_schemas,
            )
            path = self._session_manager.write_artifact(
                phase_name,
                self._artifact_sequence,
                validated,
            )
            self._artifact_sequence += 1
            state.artifacts[phase_name] = str(path)
            return None
        except Exception as exc:
            logger.warning(
                "Validation failed for phase %s: %s",
                phase_name, exc,
            )
            retry_count = state.record_phase_retry(state.current_phase)
            return PhaseResult(
                success=False,
                error=f"Validation failed: {exc}",
            )

    def _select_next_phase(
        self, state: SessionState, result: PhaseResult,
    ) -> Optional[str]:
        """Determine the next phase based on current state and phase result.

        Uses workflow.branch_rules for phases with special branching.
        For linear phases: retry on failure, advance through phase_order on success.
        Returns None if the current phase should be retried.
        """
        current = state.current_phase

        # Check branch rules first (RUN, FIX, FINALIZE in coding workflow)
        if current in self._workflow.branch_rules:
            rule = self._workflow.branch_rules[current]
            return rule(result)

        # For phases without branch rules: retry on failure, advance on success
        if not result.success:
            return None

        phase_order = self._workflow.phase_order
        if current in phase_order:
            idx = list(phase_order).index(current)
            if idx + 1 < len(phase_order):
                return phase_order[idx + 1]

        raise InvalidTransition(current, "HALTED")

    def _is_terminal(self, phase: str) -> bool:
        return phase in self._workflow.terminal_phases

    def _maybe_invoke_critic(self, state: SessionState, result: PhaseResult) -> None:
        if self._critic is None:
            return
        try:
            if not self._critic.is_available:
                return
        except Exception:
            return

        next_phase = self._predict_next_phase(state, result)
        if next_phase is None:
            return

        try:
            from core.critic.models import CriticTriggerContext
            from core.critic.triggers import (
                should_invoke_critic,
                detect_security_surface,
                detect_dependency_changes,
            )
            from core.contracts.schemas import RunReport
            from core.judge.models import JudgeReport
        except Exception:
            return

        target_files, files_changed, lines_changed = self._extract_patch_stats()
        touches_security = detect_security_surface(target_files)
        has_deps = detect_dependency_changes(target_files)

        local_disagree = False
        if self._session_manager is not None:
            run_artifact = self._session_manager.load_latest_artifact("RUN")
            critique_artifact = self._session_manager.load_latest_artifact("CRITIQUE")
            if run_artifact and critique_artifact:
                try:
                    run_report = RunReport.model_validate(run_artifact)
                    judge_report = JudgeReport.model_validate(critique_artifact)
                    if run_report.passed and judge_report.verdict in ("fail", "needs_fix"):
                        local_disagree = True
                except Exception:
                    pass

        try:
            max_calls = self._critic.config.max_calls_per_session
            calls = self._critic.calls_this_session
        except Exception:
            max_calls = 10
            calls = 0

        context = CriticTriggerContext(
            current_phase=state.current_phase,
            next_phase=next_phase,
            total_iterations=state.total_iterations,
            consecutive_fix_loops=state.phase_retries.get("RUN", 0),
            files_changed_count=files_changed,
            lines_changed_count=lines_changed,
            touches_security_surface=touches_security,
            has_dependency_changes=has_deps,
            local_reviewer_disagrees=local_disagree,
            critic_calls_this_session=calls,
            max_calls_per_session=max_calls,
        )

        try:
            should_call, reason = should_invoke_critic(context, self._critic.config)
        except Exception:
            return

        if not should_call:
            return

        report = self._critic.invoke_multi_round(
            state,
            reason,
            session_manager=self._session_manager,
            revision_callback=lambda _report, _state: False,
        )
        key = f"_critic_{state.total_iterations:03d}"
        try:
            state.artifacts[key] = report.model_dump()
        except Exception:
            state.artifacts[key] = report

        if report.consensus_verdict == "block":
            logger.warning("External critic issued BLOCK verdict (round %d)", report.round_number)

    def _predict_next_phase(self, state: SessionState,
                            result: PhaseResult) -> Optional[str]:
        try:
            return self._select_next_phase(state, result)
        except Exception:
            return None

    def _extract_patch_stats(self):
        if self._session_manager is None:
            return [], 0, 0
        patch_artifact = self._session_manager.load_latest_artifact("PATCH")
        if not patch_artifact:
            plan_artifact = self._session_manager.load_latest_artifact("PLAN")
            if isinstance(plan_artifact, dict):
                targets = plan_artifact.get("target_files", []) or []
                return list(targets), len(targets), 0
            return [], 0, 0
        try:
            from core.contracts.schemas import PatchSet
            patch_set = PatchSet.model_validate(patch_artifact)
        except Exception:
            return [], 0, 0

        target_files = [p.file_path for p in patch_set.patches]
        files_changed = len(patch_set.patches)
        lines_changed = 0
        for p in patch_set.patches:
            removed = len(p.search_block.splitlines()) if p.search_block else 0
            added = len(p.replace_block.splitlines()) if p.replace_block else 0
            lines_changed += added + removed
        return target_files, files_changed, lines_changed
