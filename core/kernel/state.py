# core/kernel/state.py — Phase enum, transition rules, and session state

import time
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any, Dict, Optional


class Phase(Enum):
    """Phases of the kernel state machine."""
    INTAKE = auto()
    CONTRACT = auto()
    REPO_MAP = auto()
    PLAN = auto()
    RETRIEVE = auto()
    PATCH = auto()
    CRITIQUE = auto()
    RUN = auto()
    FIX = auto()
    FINALIZE = auto()
    HALTED = auto()
    COMPLETED = auto()


# Allowed transitions: current phase -> set of valid next phases
TRANSITIONS: Dict[Phase, frozenset] = {
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

    def __init__(self, from_phase: Phase, to_phase: Phase):
        self.from_phase = from_phase
        self.to_phase = to_phase
        super().__init__(f"Invalid transition: {from_phase.name} -> {to_phase.name}")


def validate_transition(from_phase: Phase, to_phase: Phase) -> None:
    """Raise InvalidTransition if from_phase -> to_phase is not allowed."""
    allowed = TRANSITIONS.get(from_phase, frozenset())
    if to_phase not in allowed:
        raise InvalidTransition(from_phase, to_phase)


@dataclass
class SessionState:
    """Mutable state for a single kernel session (one --task invocation)."""

    task_description: str
    current_phase: Phase = Phase.INTAKE
    total_iterations: int = 0
    phase_retries: Dict[Phase, int] = field(default_factory=dict)
    phase_start_time: Optional[float] = None
    session_start_time: float = field(default_factory=time.monotonic)
    halt_reason: Optional[str] = None
    artifacts: Dict[str, Any] = field(default_factory=dict)
    session_id: Optional[str] = None
    session_dir: Optional[Path] = None

    def enter_phase(self, phase: Phase) -> None:
        """Transition to a new phase. Validates, increments iterations, resets timer."""
        validate_transition(self.current_phase, phase)
        self.current_phase = phase
        self.phase_start_time = time.monotonic()
        self.total_iterations += 1

    def record_phase_retry(self, phase: Phase) -> int:
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
        validate_transition(self.current_phase, Phase.COMPLETED)
        self.current_phase = Phase.COMPLETED
