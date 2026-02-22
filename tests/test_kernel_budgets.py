# tests/test_kernel_budgets.py — Tests for budget config and enforcement

import time
import pytest
from dataclasses import FrozenInstanceError

from core.kernel.state import Phase, SessionState
from core.kernel.budgets import (
    BudgetConfig,
    BudgetExhausted,
    PhaseRetriesExhausted,
    TotalIterationsExhausted,
    PhaseTimeoutExhausted,
    check_phase_retries,
    check_total_iterations,
    check_phase_time,
    check_all_budgets,
)


class TestBudgetConfig:
    def test_defaults(self):
        config = BudgetConfig()
        assert config.max_phase_retries == 3
        assert config.max_total_iterations == 30
        assert config.max_time_per_phase_seconds == 300.0
        assert config.max_tool_output_bytes_in_context == 32_768
        assert config.max_context_tokens_per_role == 16_384

    def test_frozen(self):
        config = BudgetConfig()
        with pytest.raises(FrozenInstanceError):
            config.max_phase_retries = 10

    def test_custom_values(self):
        config = BudgetConfig(
            max_phase_retries=5,
            max_total_iterations=100,
            max_time_per_phase_seconds=60.0,
        )
        assert config.max_phase_retries == 5
        assert config.max_total_iterations == 100
        assert config.max_time_per_phase_seconds == 60.0


class TestCheckPhaseRetries:
    def test_under_limit_no_raise(self):
        state = SessionState(task_description="test")
        state.enter_phase(Phase.CONTRACT)
        config = BudgetConfig(max_phase_retries=3)
        check_phase_retries(state, config)  # Should not raise

    def test_at_limit_raises(self):
        state = SessionState(task_description="test")
        state.enter_phase(Phase.CONTRACT)
        state.phase_retries[Phase.CONTRACT] = 3
        config = BudgetConfig(max_phase_retries=3)
        with pytest.raises(PhaseRetriesExhausted):
            check_phase_retries(state, config)

    def test_over_limit_raises(self):
        state = SessionState(task_description="test")
        state.enter_phase(Phase.CONTRACT)
        state.phase_retries[Phase.CONTRACT] = 5
        config = BudgetConfig(max_phase_retries=3)
        with pytest.raises(PhaseRetriesExhausted):
            check_phase_retries(state, config)

    def test_exception_attributes(self):
        state = SessionState(task_description="test")
        state.enter_phase(Phase.CONTRACT)
        state.phase_retries[Phase.CONTRACT] = 3
        config = BudgetConfig(max_phase_retries=3)
        with pytest.raises(PhaseRetriesExhausted) as exc_info:
            check_phase_retries(state, config)
        assert exc_info.value.phase == Phase.CONTRACT
        assert exc_info.value.retries == 3
        assert exc_info.value.max_retries == 3


class TestCheckTotalIterations:
    def test_under_limit_no_raise(self):
        state = SessionState(task_description="test")
        state.total_iterations = 10
        config = BudgetConfig(max_total_iterations=30)
        check_total_iterations(state, config)  # Should not raise

    def test_at_limit_raises(self):
        state = SessionState(task_description="test")
        state.total_iterations = 30
        config = BudgetConfig(max_total_iterations=30)
        with pytest.raises(TotalIterationsExhausted):
            check_total_iterations(state, config)

    def test_exception_attributes(self):
        state = SessionState(task_description="test")
        state.total_iterations = 30
        config = BudgetConfig(max_total_iterations=30)
        with pytest.raises(TotalIterationsExhausted) as exc_info:
            check_total_iterations(state, config)
        assert exc_info.value.iterations == 30
        assert exc_info.value.max_iterations == 30


class TestCheckPhaseTime:
    def test_within_limit_no_raise(self):
        state = SessionState(task_description="test")
        state.phase_start_time = time.monotonic()  # Just started
        config = BudgetConfig(max_time_per_phase_seconds=300.0)
        check_phase_time(state, config)  # Should not raise

    def test_over_limit_raises(self):
        state = SessionState(task_description="test")
        # Simulate phase started 400 seconds ago
        state.phase_start_time = time.monotonic() - 400.0
        config = BudgetConfig(max_time_per_phase_seconds=300.0)
        with pytest.raises(PhaseTimeoutExhausted):
            check_phase_time(state, config)

    def test_no_start_time_no_raise(self):
        state = SessionState(task_description="test")
        state.phase_start_time = None
        config = BudgetConfig(max_time_per_phase_seconds=1.0)
        check_phase_time(state, config)  # Should not raise


class TestCheckAllBudgets:
    def test_all_under_limit(self):
        state = SessionState(task_description="test")
        config = BudgetConfig()
        check_all_budgets(state, config)  # Should not raise

    def test_iterations_checked_first(self):
        """When both iterations and retries are exceeded, TotalIterationsExhausted fires."""
        state = SessionState(task_description="test")
        state.enter_phase(Phase.CONTRACT)
        state.total_iterations = 30
        state.phase_retries[Phase.CONTRACT] = 5
        config = BudgetConfig(max_total_iterations=30, max_phase_retries=3)
        with pytest.raises(TotalIterationsExhausted):
            check_all_budgets(state, config)


class TestExceptionHierarchy:
    def test_all_subclass_budget_exhausted(self):
        assert issubclass(PhaseRetriesExhausted, BudgetExhausted)
        assert issubclass(TotalIterationsExhausted, BudgetExhausted)
        assert issubclass(PhaseTimeoutExhausted, BudgetExhausted)

    def test_catch_base_catches_all(self):
        """except BudgetExhausted catches all specific exception types."""
        exceptions = [
            PhaseRetriesExhausted(Phase.INTAKE, 3, 3),
            TotalIterationsExhausted(30, 30),
            PhaseTimeoutExhausted(Phase.INTAKE, 400.0, 300.0),
        ]
        for exc in exceptions:
            try:
                raise exc
            except BudgetExhausted:
                pass  # Expected
