# core/kernel/state.py — Phase enum, transition rules, and session state
#
# Phase 7.0: Phase is now a str,Enum — members compare equal to their name
# strings. This allows WorkflowTemplate phases to be plain strings while
# remaining backward-compatible with existing code that uses Phase.INTAKE etc.

import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, FrozenSet, Optional


class Phase(str, Enum):
    """Phases of the coding workflow state machine.

    str,Enum: each member IS its name string. Phase.INTAKE == "INTAKE" is True.
    This allows workflow templates to use plain strings for phase names while
    existing code continues to use Phase enum members interchangeably.

    Note: custom workflows define their own phase names as plain strings.
    This enum exists for backward compatibility and as a convenience for the
    built-in coding workflow.
    """
    INTAKE = "INTAKE"
    CONTRACT = "CONTRACT"
    REPO_MAP = "REPO_MAP"
    PLAN = "PLAN"
    RETRIEVE = "RETRIEVE"
    PATCH = "PATCH"
    CRITIQUE = "CRITIQUE"
    RUN = "RUN"
    FIX = "FIX"
    FINALIZE = "FINALIZE"
    HALTED = "HALTED"
    COMPLETED = "COMPLETED"


# Allowed transitions: current phase -> set of valid next phases
# Uses Phase members (which are strings) as keys and values.
TRANSITIONS: Dict[str, FrozenSet[str]] = {
    Phase.INTAKE:    frozenset({Phase.CONTRACT, Phase.HALTED}),
    Phase.CONTRACT:  frozenset({Phase.REPO_MAP, Phase.HALTED}),
    Phase.REPO_MAP:  frozenset({Phase.PLAN, Phase.HALTED}),
    Phase.PLAN:      frozenset({Phase.RETRIEVE, Phase.HALTED}),
    Phase.RETRIEVE:  frozenset({Phase.PATCH, Phase.HALTED}),
    Phase.PATCH:     frozenset({Phase.CRITIQUE, Phase.HALTED}),
    Phase.CRITIQUE:  frozenset({Phase.RUN, Phase.HALTED}),
    Phase.RUN:       frozenset({Phase.FIX, Phase.FINALIZE, Phase.HALTED}),
    Phase.FIX:       frozenset({Phase.PATCH, Phase.HALTED}),
    Phase.FINALIZE:  frozenset({Phase.COMPLETED, Phase.HALTED}),
    Phase.HALTED:    frozenset(),
    Phase.COMPLETED: frozenset(),
}


class InvalidTransition(Exception):
    """Raised when a phase transition violates state machine rules."""

    def __init__(self, from_phase: str, to_phase: str):
        self.from_phase = from_phase
        self.to_phase = to_phase
        fname = from_phase.name if hasattr(from_phase, 'name') else from_phase
        tname = to_phase.name if hasattr(to_phase, 'name') else to_phase
        super().__init__(f"Invalid transition: {fname} -> {tname}")


def validate_transition(
    from_phase: str,
    to_phase: str,
    transitions: Optional[Dict[str, FrozenSet[str]]] = None,
) -> None:
    """Raise InvalidTransition if from_phase -> to_phase is not allowed.

    Uses the provided transitions dict, or falls back to the default
    TRANSITIONS (coding workflow) if none given.
    """
    t = transitions if transitions is not None else TRANSITIONS
    allowed = t.get(from_phase, frozenset())
    if to_phase not in allowed:
        raise InvalidTransition(from_phase, to_phase)


@dataclass
class SessionState:
    """Mutable state for a single kernel session (one --task invocation).

    Phase 7.0: current_phase is str (not Phase enum). Phases are workflow-
    defined strings. The Phase enum still works as values since it's str,Enum.
    """

    task_description: str
    current_phase: str = Phase.INTAKE
    total_iterations: int = 0
    phase_retries: Dict[str, int] = field(default_factory=dict)
    phase_start_time: Optional[float] = None
    session_start_time: float = field(default_factory=time.monotonic)
    halt_reason: Optional[str] = None
    artifacts: Dict[str, Any] = field(default_factory=dict)
    session_id: Optional[str] = None
    session_dir: Optional[Path] = None
    # Transitions dict for this session (set by orchestrator from workflow)
    _transitions: Optional[Dict[str, FrozenSet[str]]] = field(
        default=None, repr=False, compare=False,
    )

    def enter_phase(self, phase: str) -> None:
        """Transition to a new phase. Validates, increments iterations, resets timer."""
        validate_transition(self.current_phase, phase, self._transitions)
        self.current_phase = phase
        self.phase_start_time = time.monotonic()
        self.total_iterations += 1

    def record_phase_retry(self, phase: str) -> int:
        """Increment retry count for a phase. Returns new count."""
        current = self.phase_retries.get(phase, 0)
        self.phase_retries[phase] = current + 1
        return current + 1

    def halt(self, reason: str) -> None:
        """Move to HALTED terminal state."""
        self.current_phase = Phase.HALTED
        self.halt_reason = reason

    def complete(self) -> None:
        """Move to COMPLETED terminal state."""
        validate_transition(self.current_phase, Phase.COMPLETED, self._transitions)
        self.current_phase = Phase.COMPLETED
