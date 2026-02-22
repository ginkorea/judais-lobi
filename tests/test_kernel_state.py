# tests/test_kernel_state.py — Tests for Phase enum, transitions, and SessionState

import time
import pytest

from core.kernel.state import (
    Phase,
    TRANSITIONS,
    InvalidTransition,
    validate_transition,
    SessionState,
)


class TestPhaseEnum:
    def test_all_phases_defined(self):
        """All 12 phases exist (10 execution + HALTED + COMPLETED)."""
        names = {p.name for p in Phase}
        expected = {
            "INTAKE", "CONTRACT", "REPO_MAP", "PLAN", "RETRIEVE",
            "PATCH", "CRITIQUE", "RUN", "FIX", "FINALIZE",
            "HALTED", "COMPLETED",
        }
        assert names == expected

    def test_phase_values_unique(self):
        """Every Phase member has a unique value."""
        values = [p.value for p in Phase]
        assert len(values) == len(set(values))


class TestTransitions:
    def test_intake_to_contract(self):
        validate_transition(Phase.INTAKE, Phase.CONTRACT)

    def test_linear_progression(self):
        """Each phase in the linear chain transitions to the next."""
        chain = [
            Phase.INTAKE, Phase.CONTRACT, Phase.REPO_MAP, Phase.PLAN,
            Phase.RETRIEVE, Phase.PATCH, Phase.CRITIQUE, Phase.RUN,
        ]
        for i in range(len(chain) - 1):
            validate_transition(chain[i], chain[i + 1])

    def test_run_to_fix(self):
        validate_transition(Phase.RUN, Phase.FIX)

    def test_run_to_finalize(self):
        validate_transition(Phase.RUN, Phase.FINALIZE)

    def test_fix_to_patch(self):
        validate_transition(Phase.FIX, Phase.PATCH)

    def test_finalize_to_completed(self):
        validate_transition(Phase.FINALIZE, Phase.COMPLETED)

    def test_halted_is_terminal(self):
        assert TRANSITIONS[Phase.HALTED] == frozenset()

    def test_completed_is_terminal(self):
        assert TRANSITIONS[Phase.COMPLETED] == frozenset()

    def test_invalid_transition_raises(self):
        with pytest.raises(InvalidTransition):
            validate_transition(Phase.INTAKE, Phase.RUN)

    def test_backward_transition_raises(self):
        with pytest.raises(InvalidTransition):
            validate_transition(Phase.CONTRACT, Phase.INTAKE)

    def test_every_non_terminal_can_halt(self):
        """Every phase except HALTED/COMPLETED allows transition to HALTED."""
        terminals = {Phase.HALTED, Phase.COMPLETED}
        for phase in Phase:
            if phase in terminals:
                continue
            assert Phase.HALTED in TRANSITIONS[phase], (
                f"{phase.name} cannot transition to HALTED"
            )


class TestSessionState:
    def test_initial_state(self):
        state = SessionState(task_description="do something")
        assert state.current_phase == Phase.INTAKE
        assert state.total_iterations == 0
        assert state.phase_retries == {}
        assert state.halt_reason is None
        assert state.task_description == "do something"

    def test_enter_phase_increments_iterations(self):
        state = SessionState(task_description="test")
        state.enter_phase(Phase.CONTRACT)
        assert state.total_iterations == 1
        state.enter_phase(Phase.REPO_MAP)
        assert state.total_iterations == 2

    def test_enter_phase_sets_timer(self):
        state = SessionState(task_description="test")
        assert state.phase_start_time is None
        state.enter_phase(Phase.CONTRACT)
        assert state.phase_start_time is not None
        assert state.phase_start_time <= time.monotonic()

    def test_enter_invalid_phase_raises(self):
        state = SessionState(task_description="test")
        with pytest.raises(InvalidTransition):
            state.enter_phase(Phase.RUN)

    def test_record_phase_retry(self):
        state = SessionState(task_description="test")
        state.enter_phase(Phase.CONTRACT)
        count = state.record_phase_retry(Phase.CONTRACT)
        assert count == 1
        count = state.record_phase_retry(Phase.CONTRACT)
        assert count == 2

    def test_halt_sets_reason(self):
        state = SessionState(task_description="test")
        state.halt("budget exceeded")
        assert state.current_phase == Phase.HALTED
        assert state.halt_reason == "budget exceeded"

    def test_complete_from_finalize(self):
        state = SessionState(task_description="test")
        # Walk to FINALIZE
        state.enter_phase(Phase.CONTRACT)
        state.enter_phase(Phase.REPO_MAP)
        state.enter_phase(Phase.PLAN)
        state.enter_phase(Phase.RETRIEVE)
        state.enter_phase(Phase.PATCH)
        state.enter_phase(Phase.CRITIQUE)
        state.enter_phase(Phase.RUN)
        state.enter_phase(Phase.FINALIZE)
        state.complete()
        assert state.current_phase == Phase.COMPLETED

    def test_complete_from_wrong_phase_raises(self):
        state = SessionState(task_description="test")
        with pytest.raises(InvalidTransition):
            state.complete()
