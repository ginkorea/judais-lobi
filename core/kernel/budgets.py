# core/kernel/budgets.py — Hard budget configuration and enforcement
#
# Phase 7.0: Phase params accept str (was Phase enum). Since Phase is now
# str,Enum, all existing callers work without changes.

import time
from dataclasses import dataclass

from core.kernel.state import SessionState


@dataclass(frozen=True)
class BudgetConfig:
    """Hard budget parameters for a kernel session. Immutable after creation."""
    max_phase_retries: int = 3
    max_total_iterations: int = 30
    max_time_per_phase_seconds: float = 300.0
    max_tool_output_bytes_in_context: int = 32_768
    max_context_tokens_per_role: int = 16_384
    max_candidates: int = 5


class BudgetExhausted(Exception):
    """Base exception for all budget violations."""
    pass


class PhaseRetriesExhausted(BudgetExhausted):
    """Raised when a phase exceeds max_phase_retries."""

    def __init__(self, phase: str, retries: int, max_retries: int):
        self.phase = phase
        self.retries = retries
        self.max_retries = max_retries
        name = phase.name if hasattr(phase, 'name') else phase
        super().__init__(
            f"Phase {name} exhausted retries: {retries}/{max_retries}"
        )


class TotalIterationsExhausted(BudgetExhausted):
    """Raised when total iterations across all phases exceeds the cap."""

    def __init__(self, iterations: int, max_iterations: int):
        self.iterations = iterations
        self.max_iterations = max_iterations
        super().__init__(
            f"Total iterations exhausted: {iterations}/{max_iterations}"
        )


class PhaseTimeoutExhausted(BudgetExhausted):
    """Raised when a single phase exceeds its time budget."""

    def __init__(self, phase: str, elapsed: float, max_seconds: float):
        self.phase = phase
        self.elapsed = elapsed
        self.max_seconds = max_seconds
        name = phase.name if hasattr(phase, 'name') else phase
        super().__init__(
            f"Phase {name} timed out: {elapsed:.1f}s/{max_seconds:.1f}s"
        )


def check_phase_retries(state: SessionState, config: BudgetConfig) -> None:
    """Raise PhaseRetriesExhausted if current phase has exceeded retries."""
    retries = state.phase_retries.get(state.current_phase, 0)
    if retries >= config.max_phase_retries:
        raise PhaseRetriesExhausted(
            state.current_phase, retries, config.max_phase_retries
        )


def check_total_iterations(state: SessionState, config: BudgetConfig) -> None:
    """Raise TotalIterationsExhausted if session has exceeded iteration cap."""
    if state.total_iterations >= config.max_total_iterations:
        raise TotalIterationsExhausted(
            state.total_iterations, config.max_total_iterations
        )


def check_phase_time(state: SessionState, config: BudgetConfig) -> None:
    """Raise PhaseTimeoutExhausted if current phase has exceeded time budget."""
    if state.phase_start_time is None:
        return
    elapsed = time.monotonic() - state.phase_start_time
    if elapsed > config.max_time_per_phase_seconds:
        raise PhaseTimeoutExhausted(
            state.current_phase, elapsed, config.max_time_per_phase_seconds
        )


def check_all_budgets(state: SessionState, config: BudgetConfig) -> None:
    """Run all budget checks. Raises the first violation found.

    Order: total iterations (most absolute) -> phase retries -> phase time.
    """
    check_total_iterations(state, config)
    check_phase_retries(state, config)
    check_phase_time(state, config)
