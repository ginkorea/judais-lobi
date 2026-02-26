# tests/test_validation.py — Tests for contract validation

import pytest
from pydantic import ValidationError

from core.kernel.state import Phase
from core.context.models import RepoMapResult
from core.contracts.schemas import (
    TaskContract,
    ChangePlan,
    PlanStep,
    ContextPack,
    PatchSet,
    RunReport,
    FinalReport,
)
from core.contracts.validation import get_schema_for_phase, validate_phase_output


# ---------------------------------------------------------------------------
# get_schema_for_phase
# ---------------------------------------------------------------------------

class TestGetSchemaForPhase:
    def test_intake_returns_task_contract(self):
        assert get_schema_for_phase(Phase.INTAKE) is TaskContract

    def test_plan_returns_change_plan(self):
        assert get_schema_for_phase(Phase.PLAN) is ChangePlan

    def test_run_returns_run_report(self):
        assert get_schema_for_phase(Phase.RUN) is RunReport

    def test_finalize_returns_final_report(self):
        assert get_schema_for_phase(Phase.FINALIZE) is FinalReport

    def test_repo_map_returns_repo_map_result(self):
        """REPO_MAP now has a structured schema."""
        assert get_schema_for_phase(Phase.REPO_MAP) is RepoMapResult

    def test_critique_returns_judge_report(self):
        from core.judge.models import JudgeReport
        assert get_schema_for_phase(Phase.CRITIQUE) is JudgeReport

    def test_fix_returns_none(self):
        assert get_schema_for_phase(Phase.FIX) is None

    def test_halted_returns_none(self):
        assert get_schema_for_phase(Phase.HALTED) is None

    def test_completed_returns_none(self):
        assert get_schema_for_phase(Phase.COMPLETED) is None


# ---------------------------------------------------------------------------
# validate_phase_output — happy path
# ---------------------------------------------------------------------------

class TestValidatePhaseOutputHappy:
    def test_validate_dict(self):
        data = {"task_id": "t1", "description": "Add pagination"}
        result = validate_phase_output(Phase.INTAKE, data)
        assert isinstance(result, TaskContract)
        assert result.task_id == "t1"

    def test_validate_existing_model(self):
        tc = TaskContract(task_id="t1", description="Fix bug")
        result = validate_phase_output(Phase.INTAKE, tc)
        assert result is tc

    def test_validate_plan_from_dict(self):
        data = {
            "task_id": "t1",
            "steps": [{"description": "create file", "action": "create"}],
        }
        result = validate_phase_output(Phase.PLAN, data)
        assert isinstance(result, ChangePlan)
        assert len(result.steps) == 1

    def test_validate_run_report(self):
        data = {"exit_code": 0, "passed": True, "stdout": "ok"}
        result = validate_phase_output(Phase.RUN, data)
        assert isinstance(result, RunReport)
        assert result.passed is True

    def test_validate_final_report(self):
        data = {
            "task_description": "add pagination",
            "outcome": "completed",
            "total_iterations": 10,
        }
        result = validate_phase_output(Phase.FINALIZE, data)
        assert isinstance(result, FinalReport)

    def test_validate_context_pack(self):
        data = {"task_id": "t1", "repo_map_excerpt": "src/"}
        result = validate_phase_output(Phase.RETRIEVE, data)
        assert isinstance(result, ContextPack)

    def test_validate_patch_set(self):
        data = {"task_id": "t1", "patches": [{"file_path": "a.py"}]}
        result = validate_phase_output(Phase.PATCH, data)
        assert isinstance(result, PatchSet)


# ---------------------------------------------------------------------------
# validate_phase_output — error cases
# ---------------------------------------------------------------------------

class TestValidatePhaseOutputErrors:
    def test_no_schema_for_phase(self):
        with pytest.raises(ValueError, match="No schema defined"):
            validate_phase_output(Phase.FIX, {})

    def test_invalid_dict_data(self):
        """Missing required fields should raise ValidationError."""
        with pytest.raises(ValidationError):
            validate_phase_output(Phase.INTAKE, {"task_id": "t1"})  # missing description

    def test_wrong_type_raises(self):
        """Non-dict, non-model data should raise."""
        with pytest.raises((ValidationError, TypeError)):
            validate_phase_output(Phase.INTAKE, "not a dict")

    def test_invalid_field_type(self):
        with pytest.raises(ValidationError):
            validate_phase_output(Phase.RUN, {"exit_code": "not_an_int"})
