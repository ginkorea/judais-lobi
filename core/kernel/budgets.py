# core/kernel/budgets.py — Hard budget configuration and enforcement
#
# Phase 7.0: Phase params accept str (was Phase enum). Since Phase is now
# str,Enum, all existing callers work without changes.
#
# 0.9.x: the base exception and the words for the budgets themselves are
# `core.budgets`'s, not this module's. A kernel session and a mission both
# run out of *steps* and of *seconds*, and until the mission grew a wall
# clock there was no second runtime to disagree with — so the moment there
# was one, the definition moved out to a module that imports nothing and
# both can import.
#
# Phase 11 (one runtime): *steps* and *seconds* are `core.runtime.run.Bounds`'
# now — the one object the mission loop and the kernel's roles are both
# bounded by. So the kernel stops declaring `TotalIterationsExhausted` and
# `PhaseTimeoutExhausted`: those were a second name for the `steps` and
# `seconds` a `BudgetExhausted` already carries in `which`, and a second name
# for a shared fact is exactly the second emitter this phase deletes. The two
# checks below now raise the shared `BudgetExhausted` directly, with the
# `which` a consumer was told to expect. What stays here is the ONE budget the
# kernel has and the mission does not: a *phase*, its retries, and the clock
# that runs per phase where a mission's runs per run — `PhaseRetriesExhausted`,
# `which="retries"`, a word `core.budgets.WHICH` deliberately does not list.

import time
from dataclasses import dataclass

from core.bounding import MAX_RESULT_BYTES
from core.budgets import BudgetExhausted
from core.kernel.state import SessionState

__all__ = [
    "BudgetConfig", "BudgetExhausted", "PhaseRetriesExhausted",
    "check_phase_retries", "check_total_iterations", "check_phase_time",
    "check_all_budgets",
]


@dataclass(frozen=True)
class BudgetConfig:
    """Hard budget parameters for a kernel session. Immutable after creation.

    The fields are the kernel's own units and stay here: a *phase* is what
    this runtime retries and what it times, and a mission has no such
    thing.  What is shared with the mission path is one directory up —
    :class:`core.budgets.Budgets` for the shape of "steps and seconds",
    :class:`core.budgets.BudgetExhausted` for the exception every check
    below raises, and :data:`core.bounding.MAX_RESULT_BYTES` for the byte
    cap this defaults to.  A caller catching ``BudgetExhausted`` around a
    kernel session catches the same class a mission would raise, and reads
    ``which``/``limit``/``spent`` off it either way.
    """
    max_phase_retries: int = 3
    max_total_iterations: int = 30
    max_time_per_phase_seconds: float = 300.0
    #: Default is ``core.bounding.MAX_RESULT_BYTES``: this is a knob a
    #: deployment may turn down, not a second opinion on the number.
    max_tool_output_bytes_in_context: int = MAX_RESULT_BYTES
    max_context_tokens_per_role: int = 16_384
    max_candidates: int = 5


class PhaseRetriesExhausted(BudgetExhausted):
    """Raised when a phase exceeds max_phase_retries.

    ``which`` is ``"retries"`` — the one budget the kernel has and the
    mission stream does not, which is why
    :data:`core.budgets.WHICH` (the closed set a ``mission_finished``
    may name) does not list it and the base class does not police the
    word.  The kernel-shaped attributes are kept beside it because
    callers read ``exc.phase``.
    """

    def __init__(self, phase: str, retries: int, max_retries: int):
        self.phase = phase
        self.retries = retries
        self.max_retries = max_retries
        name = phase.name if hasattr(phase, 'name') else phase
        super().__init__(
            "retries", max_retries, retries,
            message=f"Phase {name} exhausted retries: {retries}/{max_retries}",
        )


def check_phase_retries(state: SessionState, config: BudgetConfig) -> None:
    """Raise PhaseRetriesExhausted if current phase has exceeded retries."""
    retries = state.phase_retries.get(state.current_phase, 0)
    if retries >= config.max_phase_retries:
        raise PhaseRetriesExhausted(
            state.current_phase, retries, config.max_phase_retries
        )


def check_total_iterations(state: SessionState, config: BudgetConfig) -> None:
    """Raise the shared ``BudgetExhausted`` (``which="steps"``) at the cap.

    An iteration here and a step in a mission are the same thing under two
    names; ``steps`` is the name a consumer of a mission stream was told to
    expect, and it is `core.runtime.run.Bounds.max_steps` that owns the
    ceiling now.  The kernel raises the shared exception rather than a
    subclass of its own — see this module's header for why the subclass is
    gone — so ``except BudgetExhausted`` around a kernel session still
    catches it and reads ``which``/``limit``/``spent`` off it.
    """
    if state.total_iterations >= config.max_total_iterations:
        raise BudgetExhausted(
            "steps", config.max_total_iterations, state.total_iterations,
            message=(f"Total iterations exhausted: "
                     f"{state.total_iterations}/{config.max_total_iterations}"),
        )


def check_phase_time(state: SessionState, config: BudgetConfig) -> None:
    """Raise the shared ``BudgetExhausted`` (``which="seconds"``) past the budget.

    The clock's *scope* is the kernel's own — it runs per phase, a mission's
    per run — but the word is ``seconds`` either way, which is why the fold
    into `Bounds`' vocabulary loses nothing: ``limit`` is the phase's budget
    and ``spent`` is how far past it went, exactly as a mission's
    `~core.budgets.Deadline` reports.
    """
    if state.phase_start_time is None:
        return
    elapsed = time.monotonic() - state.phase_start_time
    if elapsed > config.max_time_per_phase_seconds:
        name = state.current_phase
        name = name.name if hasattr(name, "name") else name
        raise BudgetExhausted(
            "seconds", config.max_time_per_phase_seconds, elapsed,
            message=(f"Phase {name} timed out: "
                     f"{elapsed:.1f}s/{config.max_time_per_phase_seconds:.1f}s"),
        )


def check_all_budgets(state: SessionState, config: BudgetConfig) -> None:
    """Run all budget checks. Raises the first violation found.

    Order: total iterations (most absolute) -> phase retries -> phase time.
    """
    check_total_iterations(state, config)
    check_phase_retries(state, config)
    check_phase_time(state, config)
