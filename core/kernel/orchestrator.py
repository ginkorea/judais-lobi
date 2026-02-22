# core/kernel/orchestrator.py — Main orchestration loop

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
    Phase 7 provides real implementations; Phase 2 tests use stubs.
    """

    def dispatch(self, phase: Phase, state: SessionState) -> PhaseResult: ...


# Linear phase order (excludes FIX, HALTED, COMPLETED — those are branching targets)
_PHASE_ORDER = [
    Phase.INTAKE, Phase.CONTRACT, Phase.REPO_MAP, Phase.PLAN,
    Phase.RETRIEVE, Phase.PATCH, Phase.CRITIQUE, Phase.RUN,
]


class Orchestrator:
    """Drives the kernel state machine through all phases.

    Reads current state, selects next phase, dispatches to roles,
    and enforces hard budgets. The orchestrator never touches the
    filesystem directly — all I/O goes through the injected dispatcher.
    """

    def __init__(
        self,
        dispatcher: RoleDispatcher,
        budget: Optional[BudgetConfig] = None,
    ):
        self._dispatcher = dispatcher
        self._budget = budget or BudgetConfig()

    def run(self, task: str) -> SessionState:
        """Execute a complete task through the state machine.

        Returns the final SessionState (COMPLETED or HALTED).
        """
        state = SessionState(task_description=task)

        while not self._is_terminal(state.current_phase):
            try:
                check_all_budgets(state, self._budget)
                result = self._execute_phase(state)
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
        logger.info("Executing phase: %s", state.current_phase.name)
        result = self._dispatcher.dispatch(state.current_phase, state)
        if not isinstance(result, PhaseResult):
            result = PhaseResult(success=True, output=result)
        if not result.success:
            retry_count = state.record_phase_retry(state.current_phase)
            logger.info(
                "Phase %s failed (retry %d/%d): %s",
                state.current_phase.name,
                retry_count,
                self._budget.max_phase_retries,
                result.error,
            )
        return result

    def _select_next_phase(
        self, state: SessionState, result: PhaseResult,
    ) -> Optional[Phase]:
        """Determine the next phase based on current state and phase result.

        Returns None if the current phase should be retried (failure in a
        non-RUN linear phase). The main loop skips enter_phase in that case,
        and the next iteration's budget check catches exhausted retries.
        """
        current = state.current_phase

        # RUN branches: success → FINALIZE, failure → FIX
        if current == Phase.RUN:
            return Phase.FINALIZE if result.success else Phase.FIX

        # FIX always loops back to PATCH
        if current == Phase.FIX:
            return Phase.PATCH

        # FINALIZE → COMPLETED
        if current == Phase.FINALIZE:
            return Phase.COMPLETED

        # For all other phases: retry on failure, advance on success
        if not result.success:
            return None

        if current in _PHASE_ORDER:
            idx = _PHASE_ORDER.index(current)
            if idx + 1 < len(_PHASE_ORDER):
                return _PHASE_ORDER[idx + 1]

        raise InvalidTransition(current, Phase.HALTED)

    @staticmethod
    def _is_terminal(phase: Phase) -> bool:
        return phase in (Phase.HALTED, Phase.COMPLETED)
