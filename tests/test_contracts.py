# tests/test_contracts.py — Tests for Pydantic contract models

import pytest
from datetime import datetime
from pydantic import ValidationError

from core.contracts.schemas import (
    PersonalityConfig,
    TaskContract,
    PlanStep,
    ChangePlan,
    RetrievedChunk,
    MemoryPin,
    ContextPack,
    FilePatch,
    PatchSet,
    RunReport,
    PermissionRequest,
    PermissionGrant,
    PolicyPack,
    FinalReport,
    PHASE_SCHEMAS,
)


# ---------------------------------------------------------------------------
# PersonalityConfig
# ---------------------------------------------------------------------------

class TestPersonalityConfig:
    def test_minimal_construction(self):
        pc = PersonalityConfig(
            name="test", system_message="You are test.",
            examples=[("Q?", "A.")],
        )
        assert pc.name == "test"
        assert pc.text_color == "cyan"  # default
        assert pc.env_path == "~/.elf_env"  # default

    def test_full_construction(self):
        pc = PersonalityConfig(
            name="lobi", system_message="You are Lobi.",
            examples=[("Q?", "A."), ("Q2?", "A2.")],
            text_color="green", env_path="~/.lobi_env",
            rag_enhancement_style="playful",
            default_model="gpt-5-mini", default_provider="openai",
        )
        assert pc.default_model == "gpt-5-mini"
        assert pc.default_provider == "openai"
        assert len(pc.examples) == 2

    def test_frozen_immutability(self):
        pc = PersonalityConfig(
            name="test", system_message="msg", examples=[],
        )
        with pytest.raises(ValidationError):
            pc.name = "changed"

    def test_model_copy(self):
        pc = PersonalityConfig(
            name="test", system_message="msg", examples=[("Q", "A")],
        )
        copy = pc.model_copy()
        assert copy == pc
        assert copy is not pc

    def test_missing_required_field(self):
        with pytest.raises(ValidationError):
            PersonalityConfig(name="test")  # missing system_message, examples

    def test_serialization_roundtrip(self):
        pc = PersonalityConfig(
            name="test", system_message="msg", examples=[("Q", "A")],
        )
        data = pc.model_dump()
        restored = PersonalityConfig(**data)
        assert restored == pc


# ---------------------------------------------------------------------------
# TaskContract
# ---------------------------------------------------------------------------

class TestTaskContract:
    def test_construction_with_defaults(self):
        tc = TaskContract(task_id="t1", description="Add pagination")
        assert tc.task_id == "t1"
        assert tc.constraints == []
        assert tc.acceptance_criteria == []
        assert tc.allowed_tools == []
        assert isinstance(tc.created_at, datetime)

    def test_full_construction(self):
        tc = TaskContract(
            task_id="t2", description="Fix bug",
            constraints=["no side effects"],
            acceptance_criteria=["tests pass"],
            allowed_tools=["run_shell_command"],
        )
        assert len(tc.constraints) == 1
        assert "tests pass" in tc.acceptance_criteria

    def test_missing_required(self):
        with pytest.raises(ValidationError):
            TaskContract(task_id="t1")  # missing description


# ---------------------------------------------------------------------------
# PlanStep & ChangePlan
# ---------------------------------------------------------------------------

class TestChangePlan:
    def test_plan_step(self):
        step = PlanStep(description="Create file", action="create", target_file="foo.py")
        assert step.action == "create"

    def test_change_plan(self):
        steps = [PlanStep(description="Create file", action="create")]
        plan = ChangePlan(task_id="t1", steps=steps, rationale="needed")
        assert len(plan.steps) == 1
        assert plan.rationale == "needed"

    def test_empty_steps_allowed(self):
        plan = ChangePlan(task_id="t1", steps=[])
        assert plan.steps == []


# ---------------------------------------------------------------------------
# Memory & Retrieval
# ---------------------------------------------------------------------------

class TestRetrievedChunk:
    def test_construction(self):
        chunk = RetrievedChunk(source="memory.db", content="The sky is blue")
        assert chunk.relevance_score == 0.0

    def test_with_score(self):
        chunk = RetrievedChunk(source="rag", content="data", relevance_score=0.95)
        assert chunk.relevance_score == 0.95


class TestMemoryPin:
    def test_construction(self):
        pin = MemoryPin(
            embedding_backend="openai", model_name="text-embedding-3-large",
            query="what color", chunk_ids=[1, 2], similarity_scores=[0.9, 0.8],
        )
        assert len(pin.chunk_ids) == 2
        assert isinstance(pin.timestamp, datetime)


class TestContextPack:
    def test_empty(self):
        cp = ContextPack(task_id="t1")
        assert cp.retrieved_chunks == []
        assert cp.memory_pins == []

    def test_with_chunks(self):
        chunks = [RetrievedChunk(source="rag", content="data")]
        cp = ContextPack(task_id="t1", retrieved_chunks=chunks)
        assert len(cp.retrieved_chunks) == 1


# ---------------------------------------------------------------------------
# Patch contracts
# ---------------------------------------------------------------------------

class TestPatchContracts:
    def test_file_patch_defaults(self):
        fp = FilePatch(file_path="foo.py")
        assert fp.action == "modify"
        assert fp.search_block == ""

    def test_patch_set(self):
        patches = [FilePatch(file_path="a.py", search_block="old", replace_block="new")]
        ps = PatchSet(task_id="t1", patches=patches)
        assert len(ps.patches) == 1


# ---------------------------------------------------------------------------
# RunReport
# ---------------------------------------------------------------------------

class TestRunReport:
    def test_defaults(self):
        rr = RunReport()
        assert rr.exit_code == 0
        assert rr.passed is False

    def test_successful_run(self):
        rr = RunReport(exit_code=0, passed=True, stdout="ok", duration_seconds=1.5)
        assert rr.passed is True


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------

class TestPermissions:
    def test_permission_request(self):
        pr = PermissionRequest(tool_name="run_shell_command", scope="*", reason="needed")
        assert isinstance(pr.requested_at, datetime)

    def test_permission_grant(self):
        pg = PermissionGrant(tool_name="run_shell_command", scope="*")
        assert pg.granted_by == "user"
        assert pg.grant_scope == "session"
        assert pg.grant_duration_seconds is None

    def test_permission_grant_with_duration(self):
        pg = PermissionGrant(
            tool_name="run_shell_command", scope="*",
            grant_duration_seconds=3600.0, grant_scope="task",
        )
        assert pg.grant_duration_seconds == 3600.0


# ---------------------------------------------------------------------------
# PolicyPack
# ---------------------------------------------------------------------------

class TestPolicyPack:
    def test_defaults(self):
        pp = PolicyPack()
        assert pp.sandbox_backend == "bwrap"
        assert pp.allowed_tools == []

    def test_full(self):
        pp = PolicyPack(
            allowed_tools=["run_shell_command"],
            sandbox_backend="docker",
            budget_overrides={"max_phase_retries": 5},
        )
        assert pp.sandbox_backend == "docker"


# ---------------------------------------------------------------------------
# FinalReport
# ---------------------------------------------------------------------------

class TestFinalReport:
    def test_completed(self):
        fr = FinalReport(
            task_description="add pagination", outcome="completed",
            total_iterations=10, duration_seconds=45.0,
        )
        assert fr.outcome == "completed"
        assert fr.halt_reason is None

    def test_halted(self):
        fr = FinalReport(
            task_description="fix bug", outcome="halted",
            halt_reason="budget exhausted",
        )
        assert fr.halt_reason == "budget exhausted"


# ---------------------------------------------------------------------------
# PHASE_SCHEMAS mapping
# ---------------------------------------------------------------------------

class TestPhaseSchemas:
    def test_contains_expected_phases(self):
        expected = {"INTAKE", "CONTRACT", "REPO_MAP", "PLAN", "RETRIEVE", "PATCH", "RUN", "FINALIZE"}
        assert set(PHASE_SCHEMAS.keys()) == expected

    def test_intake_maps_to_task_contract(self):
        assert PHASE_SCHEMAS["INTAKE"] is TaskContract

    def test_plan_maps_to_change_plan(self):
        assert PHASE_SCHEMAS["PLAN"] is ChangePlan

    def test_run_maps_to_run_report(self):
        assert PHASE_SCHEMAS["RUN"] is RunReport

    def test_finalize_maps_to_final_report(self):
        assert PHASE_SCHEMAS["FINALIZE"] is FinalReport

    def test_all_values_are_pydantic_models(self):
        from pydantic import BaseModel
        for phase, schema in PHASE_SCHEMAS.items():
            assert issubclass(schema, BaseModel), f"{phase} does not map to a BaseModel"
