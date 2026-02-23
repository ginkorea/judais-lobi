# tests/test_orchestrator_sessions.py — Tests for SessionManager + Orchestrator integration

import json
import pytest
from pathlib import Path

from core.kernel.state import Phase, SessionState
from core.kernel.orchestrator import Orchestrator, PhaseResult
from core.kernel.budgets import BudgetConfig
from core.sessions.manager import SessionManager
from core.contracts.schemas import TaskContract, RunReport, FinalReport


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class StubDispatcher:
    """Succeeds on every phase (no structured output)."""
    def dispatch(self, phase: Phase, state: SessionState) -> PhaseResult:
        return PhaseResult(success=True)


class StructuredDispatcher:
    """Returns schema-appropriate structured output for phases with schemas."""

    def dispatch(self, phase: Phase, state: SessionState) -> PhaseResult:
        if phase == Phase.INTAKE:
            return PhaseResult(
                success=True,
                output=TaskContract(task_id="t1", description="test task"),
            )
        if phase == Phase.CONTRACT:
            return PhaseResult(
                success=True,
                output=TaskContract(task_id="t1", description="test task refined"),
            )
        if phase == Phase.RUN:
            return PhaseResult(
                success=True,
                output=RunReport(exit_code=0, passed=True, stdout="ok"),
            )
        if phase == Phase.FINALIZE:
            return PhaseResult(
                success=True,
                output=FinalReport(
                    task_description="test task",
                    outcome="completed",
                    total_iterations=10,
                ),
            )
        return PhaseResult(success=True)


class FailOnRunDispatcher:
    """Fails on RUN phase to test rollback."""
    def __init__(self):
        self.run_calls = 0

    def dispatch(self, phase: Phase, state: SessionState) -> PhaseResult:
        if phase == Phase.RUN:
            self.run_calls += 1
            return PhaseResult(success=False, error="tests failed", needs_fix=True)
        if phase == Phase.FIX:
            return PhaseResult(success=True)
        if phase == Phase.PATCH:
            return PhaseResult(success=True)
        return PhaseResult(success=True)


class ValidationFailDispatcher:
    """Returns invalid data for INTAKE to test validation failure."""
    def __init__(self):
        self.call_count = 0

    def dispatch(self, phase: Phase, state: SessionState) -> PhaseResult:
        if phase == Phase.INTAKE:
            self.call_count += 1
            # Return a dict missing required 'description' field
            return PhaseResult(
                success=True,
                output={"task_id": "t1"},  # missing description
            )
        return PhaseResult(success=True)


# ---------------------------------------------------------------------------
# Tests: SessionManager wiring
# ---------------------------------------------------------------------------

class TestOrchestratorWithSession:
    def test_session_id_set_on_state(self, tmp_path):
        sm = SessionManager(base_dir=tmp_path, session_id="test-001")
        orch = Orchestrator(
            dispatcher=StubDispatcher(),
            session_manager=sm,
        )
        state = orch.run("test task")
        assert state.session_id == "test-001"
        assert state.session_dir == sm.session_dir

    def test_no_session_manager_defaults_none(self):
        orch = Orchestrator(dispatcher=StubDispatcher())
        state = orch.run("test task")
        assert state.session_id is None
        assert state.session_dir is None

    def test_still_completes_with_session_manager(self, tmp_path):
        sm = SessionManager(base_dir=tmp_path)
        orch = Orchestrator(
            dispatcher=StubDispatcher(),
            session_manager=sm,
        )
        state = orch.run("test task")
        assert state.current_phase == Phase.COMPLETED


# ---------------------------------------------------------------------------
# Tests: Artifact recording
# ---------------------------------------------------------------------------

class TestArtifactRecording:
    def test_structured_output_written_to_disk(self, tmp_path):
        sm = SessionManager(base_dir=tmp_path, session_id="art-001")
        orch = Orchestrator(
            dispatcher=StructuredDispatcher(),
            session_manager=sm,
        )
        state = orch.run("test task")
        assert state.current_phase == Phase.COMPLETED

        # Check that artifacts were written
        all_artifacts = sm.load_all_artifacts()
        assert len(all_artifacts) > 0

    def test_intake_artifact_recorded(self, tmp_path):
        sm = SessionManager(base_dir=tmp_path, session_id="art-002")
        orch = Orchestrator(
            dispatcher=StructuredDispatcher(),
            session_manager=sm,
        )
        state = orch.run("test task")

        intake = sm.load_latest_artifact("INTAKE")
        assert intake is not None
        assert intake["task_id"] == "t1"

    def test_run_artifact_recorded(self, tmp_path):
        sm = SessionManager(base_dir=tmp_path, session_id="art-003")
        orch = Orchestrator(
            dispatcher=StructuredDispatcher(),
            session_manager=sm,
        )
        state = orch.run("test task")

        run = sm.load_latest_artifact("RUN")
        assert run is not None
        assert run["passed"] is True

    def test_artifact_path_in_state(self, tmp_path):
        sm = SessionManager(base_dir=tmp_path, session_id="art-004")
        orch = Orchestrator(
            dispatcher=StructuredDispatcher(),
            session_manager=sm,
        )
        state = orch.run("test task")
        assert "INTAKE" in state.artifacts


# ---------------------------------------------------------------------------
# Tests: Validate-or-retry
# ---------------------------------------------------------------------------

class TestValidateOrRetry:
    def test_validation_failure_burns_retry(self, tmp_path):
        sm = SessionManager(base_dir=tmp_path, session_id="val-001")
        dispatcher = ValidationFailDispatcher()
        budget = BudgetConfig(max_phase_retries=2, max_total_iterations=30)
        orch = Orchestrator(
            dispatcher=dispatcher,
            budget=budget,
            session_manager=sm,
        )
        state = orch.run("test task")

        # Should halt because INTAKE validation keeps failing
        assert state.current_phase == Phase.HALTED
        # Dispatcher was called multiple times (retries before exhaustion)
        assert dispatcher.call_count >= 2

    def test_no_validation_without_session_manager(self):
        """Without session_manager, validation is skipped."""
        dispatcher = ValidationFailDispatcher()
        orch = Orchestrator(dispatcher=dispatcher)
        state = orch.run("test task")
        # Completes because validation is not enforced
        assert state.current_phase == Phase.COMPLETED


# ---------------------------------------------------------------------------
# Tests: Checkpoint and rollback
# ---------------------------------------------------------------------------

class TestCheckpointRollback:
    def test_checkpoint_created_before_patch(self, tmp_path):
        sm = SessionManager(base_dir=tmp_path, session_id="cp-001")
        orch = Orchestrator(
            dispatcher=StubDispatcher(),
            session_manager=sm,
        )
        state = orch.run("test task")

        # Check that a checkpoint was created
        checkpoints = list((sm.session_dir / "checkpoints").iterdir())
        assert len(checkpoints) > 0
        assert any("pre_PATCH" in cp.name for cp in checkpoints)

    def test_rollback_on_run_failure(self, tmp_path):
        sm = SessionManager(base_dir=tmp_path, session_id="rb-001")
        dispatcher = FailOnRunDispatcher()
        budget = BudgetConfig(max_phase_retries=2, max_total_iterations=15)
        orch = Orchestrator(
            dispatcher=dispatcher,
            budget=budget,
            session_manager=sm,
        )
        state = orch.run("test task")

        # Should eventually halt (budget exhausted from PATCH→RUN→FIX→PATCH loop)
        assert state.current_phase == Phase.HALTED
        # Confirm RUN was attempted
        assert dispatcher.run_calls >= 1

    def test_last_patch_checkpoint_in_artifacts(self, tmp_path):
        sm = SessionManager(base_dir=tmp_path, session_id="cp-002")
        orch = Orchestrator(
            dispatcher=StubDispatcher(),
            session_manager=sm,
        )
        state = orch.run("test task")
        assert "_last_patch_checkpoint" in state.artifacts
