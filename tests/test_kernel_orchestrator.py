# tests/test_kernel_orchestrator.py — Tests for the Orchestrator

import time
import pytest

from core.kernel.state import Phase, SessionState
from core.kernel.budgets import BudgetConfig
from core.kernel.orchestrator import Orchestrator, PhaseResult


class ConfigurableDispatcher:
    """Test stub that returns configured PhaseResult per phase."""

    def __init__(self, results=None):
        self.results = results or {}
        self.call_log = []
        self.default_result = PhaseResult(success=True)
        self._call_count = {}  # Phase -> number of times dispatched

    def dispatch(self, phase, state):
        self.call_log.append(phase)
        count = self._call_count.get(phase, 0)
        self._call_count[phase] = count + 1

        result_or_fn = self.results.get(phase, self.default_result)
        if callable(result_or_fn):
            return result_or_fn(count)
        return result_or_fn


class TestOrchestratorHappyPath:
    def test_drives_through_all_phases(self):
        """With all-success dispatcher, orchestrator visits every phase."""
        dispatcher = ConfigurableDispatcher()
        orch = Orchestrator(dispatcher=dispatcher)
        state = orch.run("test task")
        assert state.current_phase == Phase.COMPLETED

    def test_final_state_is_completed(self):
        dispatcher = ConfigurableDispatcher()
        orch = Orchestrator(dispatcher=dispatcher)
        state = orch.run("test task")
        assert state.current_phase == Phase.COMPLETED
        assert state.halt_reason is None

    def test_all_phases_dispatched(self):
        """Dispatcher receives all 10 execution phases plus FINALIZE."""
        dispatcher = ConfigurableDispatcher()
        orch = Orchestrator(dispatcher=dispatcher)
        orch.run("test task")
        expected = [
            Phase.INTAKE, Phase.CONTRACT, Phase.REPO_MAP, Phase.PLAN,
            Phase.RETRIEVE, Phase.PATCH, Phase.CRITIQUE, Phase.RUN,
            Phase.FINALIZE,
        ]
        assert dispatcher.call_log == expected

    def test_total_iterations_counted(self):
        dispatcher = ConfigurableDispatcher()
        orch = Orchestrator(dispatcher=dispatcher)
        state = orch.run("test task")
        # 9 transitions: INTAKE->CONTRACT->...->RUN->FINALIZE->COMPLETED
        assert state.total_iterations == 9


class TestOrchestratorFixLoop:
    def test_fix_loops_back_to_patch(self):
        """When RUN fails, FIX is dispatched, then loops to PATCH."""
        call_count = {"run": 0}

        def run_result(count):
            call_count["run"] += 1
            if call_count["run"] <= 1:
                return PhaseResult(success=False, error="tests failed")
            return PhaseResult(success=True)

        dispatcher = ConfigurableDispatcher(results={
            Phase.RUN: run_result,
        })
        orch = Orchestrator(dispatcher=dispatcher)
        state = orch.run("test task")
        assert state.current_phase == Phase.COMPLETED

    def test_fix_loop_eventually_succeeds(self):
        """If RUN fails twice then succeeds, state ends COMPLETED."""
        call_count = {"run": 0}

        def run_result(count):
            call_count["run"] += 1
            if call_count["run"] <= 2:
                return PhaseResult(success=False, error="tests failed")
            return PhaseResult(success=True)

        dispatcher = ConfigurableDispatcher(results={
            Phase.RUN: run_result,
        })
        orch = Orchestrator(dispatcher=dispatcher)
        state = orch.run("test task")
        assert state.current_phase == Phase.COMPLETED

    def test_fix_loop_call_order(self):
        """Call log shows correct FIX loop sequence."""
        call_count = {"run": 0}

        def run_result(count):
            call_count["run"] += 1
            if call_count["run"] <= 1:
                return PhaseResult(success=False, error="tests failed")
            return PhaseResult(success=True)

        dispatcher = ConfigurableDispatcher(results={
            Phase.RUN: run_result,
        })
        orch = Orchestrator(dispatcher=dispatcher)
        orch.run("test task")
        expected = [
            Phase.INTAKE, Phase.CONTRACT, Phase.REPO_MAP, Phase.PLAN,
            Phase.RETRIEVE, Phase.PATCH, Phase.CRITIQUE, Phase.RUN,
            Phase.FIX,
            Phase.PATCH, Phase.CRITIQUE, Phase.RUN,
            Phase.FINALIZE,
        ]
        assert dispatcher.call_log == expected


class TestOrchestratorBudgetHalt:
    def test_halts_on_total_iterations(self):
        """Perpetual FIX loop halts after max_total_iterations."""
        dispatcher = ConfigurableDispatcher(results={
            Phase.RUN: PhaseResult(success=False, error="always fails"),
        })
        budget = BudgetConfig(max_total_iterations=15, max_phase_retries=100)
        orch = Orchestrator(dispatcher=dispatcher, budget=budget)
        state = orch.run("test task")
        assert state.current_phase == Phase.HALTED
        assert "iterations" in state.halt_reason.lower()

    def test_halts_on_phase_retries(self):
        """Phase that always fails halts after max_phase_retries."""
        # CONTRACT always fails -> retries accumulate on CONTRACT
        dispatcher = ConfigurableDispatcher(results={
            Phase.CONTRACT: PhaseResult(success=False, error="invalid"),
        })
        budget = BudgetConfig(max_phase_retries=2, max_total_iterations=100)
        orch = Orchestrator(dispatcher=dispatcher, budget=budget)
        state = orch.run("test task")
        assert state.current_phase == Phase.HALTED
        assert "retries" in state.halt_reason.lower()

    def test_halt_reason_set(self):
        dispatcher = ConfigurableDispatcher(results={
            Phase.RUN: PhaseResult(success=False, error="always fails"),
        })
        budget = BudgetConfig(max_total_iterations=12, max_phase_retries=100)
        orch = Orchestrator(dispatcher=dispatcher, budget=budget)
        state = orch.run("test task")
        assert state.halt_reason is not None
        assert len(state.halt_reason) > 0

    def test_fix_loop_halts_after_budget(self):
        """FIX loop that never succeeds halts after max_total_iterations."""
        dispatcher = ConfigurableDispatcher(results={
            Phase.RUN: PhaseResult(success=False, error="tests fail"),
        })
        budget = BudgetConfig(max_total_iterations=20, max_phase_retries=100)
        orch = Orchestrator(dispatcher=dispatcher, budget=budget)
        state = orch.run("test task")
        assert state.current_phase == Phase.HALTED


class TestOrchestratorTimeoutHalt:
    def test_phase_timeout_halts(self):
        """A phase that exceeds time budget causes halt."""
        def slow_dispatch(count):
            return PhaseResult(success=True)

        dispatcher = ConfigurableDispatcher()

        budget = BudgetConfig(max_time_per_phase_seconds=0.0)
        orch = Orchestrator(dispatcher=dispatcher, budget=budget)
        state = orch.run("test task")
        # First phase (INTAKE) is dispatched, then enter_phase to CONTRACT
        # sets timer. Next check_all_budgets finds CONTRACT timed out.
        assert state.current_phase == Phase.HALTED
        assert "timed out" in state.halt_reason.lower()


class TestOrchestratorEdgeCases:
    def test_custom_budget(self):
        dispatcher = ConfigurableDispatcher()
        budget = BudgetConfig(max_total_iterations=50)
        orch = Orchestrator(dispatcher=dispatcher, budget=budget)
        state = orch.run("test task")
        assert state.current_phase == Phase.COMPLETED

    def test_default_budget(self):
        dispatcher = ConfigurableDispatcher()
        orch = Orchestrator(dispatcher=dispatcher)
        state = orch.run("test task")
        assert state.current_phase == Phase.COMPLETED

    def test_dispatcher_returns_raw_value(self):
        """If dispatcher returns non-PhaseResult, it gets wrapped as success."""

        class RawDispatcher:
            def dispatch(self, phase, state):
                return "raw value"

        orch = Orchestrator(dispatcher=RawDispatcher())
        state = orch.run("test task")
        assert state.current_phase == Phase.COMPLETED
