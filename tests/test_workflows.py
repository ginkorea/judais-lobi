# tests/test_workflows.py — Phase 7.0: WorkflowTemplate, workflows, and selector

import pytest

from core.kernel.state import Phase, SessionState, TRANSITIONS, InvalidTransition, validate_transition
from core.kernel.budgets import BudgetConfig
from core.kernel.orchestrator import Orchestrator, PhaseResult
from core.kernel.workflows import (
    WorkflowTemplate,
    get_coding_workflow,
    get_generic_workflow,
    select_workflow,
)
from core.contracts.schemas import (
    TaskContract,
    ChangePlan,
    ContextPack,
    PatchSet,
    RunReport,
    FinalReport,
    PHASE_SCHEMAS,
)
from core.context.models import RepoMapResult


# ---------------------------------------------------------------------------
# Phase str,Enum backward compatibility
# ---------------------------------------------------------------------------

class TestPhaseStrEnum:
    """Phase is now str,Enum. Members compare equal to their name strings."""

    def test_phase_equals_string(self):
        assert Phase.INTAKE == "INTAKE"
        assert Phase.CONTRACT == "CONTRACT"
        assert Phase.COMPLETED == "COMPLETED"

    def test_phase_is_instance_of_str(self):
        assert isinstance(Phase.INTAKE, str)

    def test_phase_name_equals_value(self):
        for p in Phase:
            assert p.name == p.value

    def test_phase_in_string_set(self):
        s = {"INTAKE", "CONTRACT"}
        assert Phase.INTAKE in s
        assert Phase.CONTRACT in s

    def test_string_in_phase_frozenset(self):
        fs = frozenset({Phase.INTAKE, Phase.CONTRACT})
        assert "INTAKE" in fs
        assert "CONTRACT" in fs

    def test_phase_as_dict_key_string_lookup(self):
        d = {Phase.INTAKE: "value"}
        assert d["INTAKE"] == "value"
        assert d[Phase.INTAKE] == "value"

    def test_string_as_dict_key_phase_lookup(self):
        d = {"INTAKE": "value"}
        assert d[Phase.INTAKE] == "value"

    def test_phase_hash_equals_string_hash(self):
        assert hash(Phase.INTAKE) == hash("INTAKE")

    def test_all_12_phases_exist(self):
        names = {p.name for p in Phase}
        expected = {
            "INTAKE", "CONTRACT", "REPO_MAP", "PLAN", "RETRIEVE",
            "PATCH", "CRITIQUE", "RUN", "FIX", "FINALIZE",
            "HALTED", "COMPLETED",
        }
        assert names == expected

    def test_phase_values_unique(self):
        values = [p.value for p in Phase]
        assert len(values) == len(set(values))


# ---------------------------------------------------------------------------
# WorkflowTemplate structure
# ---------------------------------------------------------------------------

class TestWorkflowTemplate:
    def test_construction(self):
        wf = WorkflowTemplate(
            name="test",
            phases=("A", "B", "C"),
            transitions={"A": frozenset({"B"}), "B": frozenset({"C"}), "C": frozenset()},
            phase_schemas={},
            phase_order=("A", "B"),
            branch_rules={"B": lambda r: "C"},
            terminal_phases=frozenset({"C"}),
            phase_capabilities={"A": frozenset({"fs.read"})},
        )
        assert wf.name == "test"
        assert wf.phases == ("A", "B", "C")

    def test_equality_by_name(self):
        wf1 = WorkflowTemplate(
            name="same", phases=("A",), transitions={}, phase_schemas={},
            phase_order=(), branch_rules={}, terminal_phases=frozenset(),
            phase_capabilities={},
        )
        wf2 = WorkflowTemplate(
            name="same", phases=("B",), transitions={}, phase_schemas={},
            phase_order=(), branch_rules={}, terminal_phases=frozenset(),
            phase_capabilities={},
        )
        assert wf1 == wf2

    def test_inequality_by_name(self):
        wf1 = WorkflowTemplate(
            name="a", phases=(), transitions={}, phase_schemas={},
            phase_order=(), branch_rules={}, terminal_phases=frozenset(),
            phase_capabilities={},
        )
        wf2 = WorkflowTemplate(
            name="b", phases=(), transitions={}, phase_schemas={},
            phase_order=(), branch_rules={}, terminal_phases=frozenset(),
            phase_capabilities={},
        )
        assert wf1 != wf2

    def test_hash_by_name(self):
        wf = WorkflowTemplate(
            name="test", phases=(), transitions={}, phase_schemas={},
            phase_order=(), branch_rules={}, terminal_phases=frozenset(),
            phase_capabilities={},
        )
        assert hash(wf) == hash("test")

    def test_default_fields(self):
        wf = WorkflowTemplate(
            name="minimal", phases=(), transitions={}, phase_schemas={},
            phase_order=(), branch_rules={}, terminal_phases=frozenset(),
            phase_capabilities={},
        )
        assert wf.default_budget_overrides == {}
        assert wf.required_scopes == []
        assert wf.description == ""


# ---------------------------------------------------------------------------
# CODING_WORKFLOW
# ---------------------------------------------------------------------------

class TestCodingWorkflow:
    @pytest.fixture
    def coding(self):
        return get_coding_workflow()

    def test_name(self, coding):
        assert coding.name == "coding"

    def test_12_phases(self, coding):
        assert len(coding.phases) == 12

    def test_phases_match_enum(self, coding):
        enum_names = {p.name for p in Phase}
        assert set(coding.phases) == enum_names

    def test_transitions_match_global(self, coding):
        """CODING_WORKFLOW transitions produce identical behavior to TRANSITIONS."""
        for phase in coding.phases:
            wf_allowed = coding.transitions.get(phase, frozenset())
            global_allowed = TRANSITIONS.get(phase, frozenset())
            assert wf_allowed == global_allowed, f"Mismatch at {phase}"

    def test_phase_order_8_linear(self, coding):
        assert coding.phase_order == (
            "INTAKE", "CONTRACT", "REPO_MAP", "PLAN",
            "RETRIEVE", "PATCH", "CRITIQUE", "RUN",
        )

    def test_branch_rules_run_success(self, coding):
        result = PhaseResult(success=True)
        assert coding.branch_rules["RUN"](result) == "FINALIZE"

    def test_branch_rules_run_failure(self, coding):
        result = PhaseResult(success=False)
        assert coding.branch_rules["RUN"](result) == "FIX"

    def test_branch_rules_fix(self, coding):
        result = PhaseResult(success=True)
        assert coding.branch_rules["FIX"](result) == "PATCH"

    def test_branch_rules_finalize(self, coding):
        result = PhaseResult(success=True)
        assert coding.branch_rules["FINALIZE"](result) == "COMPLETED"

    def test_terminal_phases(self, coding):
        assert coding.terminal_phases == frozenset({"HALTED", "COMPLETED"})

    def test_phase_schemas_match_global(self, coding):
        for phase_name, schema in PHASE_SCHEMAS.items():
            assert coding.phase_schemas.get(phase_name) is schema

    def test_required_scopes(self, coding):
        assert "fs.read" in coding.required_scopes
        assert "fs.write" in coding.required_scopes
        assert "git.read" in coding.required_scopes
        assert "verify.run" in coding.required_scopes

    def test_description_not_empty(self, coding):
        assert len(coding.description) > 0


# ---------------------------------------------------------------------------
# CODING_WORKFLOW phase_capabilities
# ---------------------------------------------------------------------------

class TestCodingWorkflowCapabilities:
    @pytest.fixture
    def caps(self):
        return get_coding_workflow().phase_capabilities

    def test_intake_read_only(self, caps):
        assert caps["INTAKE"] == frozenset({"fs.read"})

    def test_plan_read_only(self, caps):
        assert caps["PLAN"] == frozenset({"fs.read", "git.read"})

    def test_patch_can_write(self, caps):
        assert "fs.write" in caps["PATCH"]
        assert "git.write" in caps["PATCH"]

    def test_run_can_verify(self, caps):
        assert "verify.run" in caps["RUN"]

    def test_critique_read_only(self, caps):
        assert caps["CRITIQUE"] == frozenset({"fs.read", "git.read"})

    def test_finalize_read_only(self, caps):
        assert caps["FINALIZE"] == frozenset({"fs.read", "git.read"})

    def test_no_write_in_plan(self, caps):
        assert "fs.write" not in caps["PLAN"]
        assert "git.write" not in caps["PLAN"]

    def test_all_execution_phases_have_capabilities(self, caps):
        """Every non-terminal phase has defined capabilities."""
        for phase in ("INTAKE", "CONTRACT", "REPO_MAP", "PLAN", "RETRIEVE",
                      "PATCH", "CRITIQUE", "RUN", "FIX", "FINALIZE"):
            assert phase in caps, f"Missing capabilities for {phase}"

    def test_all_capabilities_are_frozensets(self, caps):
        for phase, cap_set in caps.items():
            assert isinstance(cap_set, frozenset), f"{phase} is not frozenset"


# ---------------------------------------------------------------------------
# GENERIC_WORKFLOW
# ---------------------------------------------------------------------------

class TestGenericWorkflow:
    @pytest.fixture
    def generic(self):
        return get_generic_workflow()

    def test_name(self, generic):
        assert generic.name == "generic"

    def test_7_phases(self, generic):
        assert len(generic.phases) == 7

    def test_phase_names(self, generic):
        assert set(generic.phases) == {
            "INTAKE", "PLAN", "EXECUTE", "EVALUATE",
            "FINALIZE", "HALTED", "COMPLETED",
        }

    def test_terminal_phases(self, generic):
        assert generic.terminal_phases == frozenset({"HALTED", "COMPLETED"})

    def test_phase_order(self, generic):
        assert generic.phase_order == ("INTAKE", "PLAN", "EXECUTE", "EVALUATE")

    def test_branch_rules_evaluate_success(self, generic):
        result = PhaseResult(success=True)
        assert generic.branch_rules["EVALUATE"](result) == "FINALIZE"

    def test_branch_rules_evaluate_failure(self, generic):
        result = PhaseResult(success=False)
        assert generic.branch_rules["EVALUATE"](result) == "PLAN"

    def test_branch_rules_finalize(self, generic):
        result = PhaseResult(success=True)
        assert generic.branch_rules["FINALIZE"](result) == "COMPLETED"

    def test_transitions_intake_to_plan(self, generic):
        assert "PLAN" in generic.transitions["INTAKE"]

    def test_transitions_evaluate_branches(self, generic):
        allowed = generic.transitions["EVALUATE"]
        assert "PLAN" in allowed
        assert "EXECUTE" in allowed
        assert "FINALIZE" in allowed

    def test_all_non_terminal_can_halt(self, generic):
        for phase in generic.phases:
            if phase in generic.terminal_phases:
                continue
            assert "HALTED" in generic.transitions[phase], f"{phase} can't halt"

    def test_execute_has_write_capabilities(self, generic):
        assert "fs.write" in generic.phase_capabilities["EXECUTE"]

    def test_plan_read_only(self, generic):
        assert generic.phase_capabilities["PLAN"] == frozenset({"fs.read"})

    def test_schemas_intake(self, generic):
        assert generic.phase_schemas["INTAKE"] is TaskContract

    def test_schemas_plan(self, generic):
        assert generic.phase_schemas["PLAN"] is ChangePlan

    def test_schemas_finalize(self, generic):
        assert generic.phase_schemas["FINALIZE"] is FinalReport


# ---------------------------------------------------------------------------
# select_workflow
# ---------------------------------------------------------------------------

class TestSelectWorkflow:
    def test_default_returns_coding(self):
        wf = select_workflow()
        assert wf.name == "coding"

    def test_cli_flag_coding(self):
        wf = select_workflow(cli_flag="coding")
        assert wf.name == "coding"

    def test_cli_flag_generic(self):
        wf = select_workflow(cli_flag="generic")
        assert wf.name == "generic"

    def test_policy_workflow(self):
        wf = select_workflow(policy_workflow="generic")
        assert wf.name == "generic"

    def test_cli_flag_overrides_policy(self):
        wf = select_workflow(cli_flag="coding", policy_workflow="generic")
        assert wf.name == "coding"

    def test_unknown_workflow_raises(self):
        with pytest.raises(ValueError, match="Unknown workflow"):
            select_workflow(cli_flag="nonexistent")


# ---------------------------------------------------------------------------
# SessionState with workflow transitions
# ---------------------------------------------------------------------------

class TestSessionStateWithWorkflow:
    def test_default_transitions(self):
        """SessionState without explicit transitions uses global TRANSITIONS."""
        state = SessionState(task_description="test")
        state.enter_phase(Phase.CONTRACT)  # Should work with default transitions
        assert state.current_phase == Phase.CONTRACT

    def test_custom_transitions(self):
        """SessionState with custom transitions validates against them."""
        custom = {
            "A": frozenset({"B"}),
            "B": frozenset(),
        }
        state = SessionState(task_description="test", current_phase="A", _transitions=custom)
        state.enter_phase("B")
        assert state.current_phase == "B"

    def test_custom_transitions_rejects_invalid(self):
        custom = {
            "A": frozenset({"B"}),
            "B": frozenset(),
        }
        state = SessionState(task_description="test", current_phase="A", _transitions=custom)
        with pytest.raises(InvalidTransition):
            state.enter_phase("C")  # C not in transitions from A

    def test_generic_workflow_transitions(self):
        """SessionState with generic workflow transitions follows generic path."""
        generic = get_generic_workflow()
        state = SessionState(
            task_description="test",
            current_phase="INTAKE",
            _transitions=generic.transitions,
        )
        state.enter_phase("PLAN")
        assert state.current_phase == "PLAN"
        state.enter_phase("EXECUTE")
        assert state.current_phase == "EXECUTE"

    def test_string_phases_work(self):
        """Pure string phases work without Phase enum."""
        state = SessionState(task_description="test", current_phase="INTAKE")
        state.enter_phase("CONTRACT")
        assert state.current_phase == "CONTRACT"

    def test_phase_retries_with_strings(self):
        state = SessionState(task_description="test")
        state.enter_phase("CONTRACT")
        count = state.record_phase_retry("CONTRACT")
        assert count == 1
        # Lookup with Phase enum also works
        assert state.phase_retries.get(Phase.CONTRACT, 0) == 1


# ---------------------------------------------------------------------------
# Orchestrator with CODING_WORKFLOW (default)
# ---------------------------------------------------------------------------

class ConfigurableDispatcher:
    """Test stub: configured PhaseResult per phase."""

    def __init__(self, results=None):
        self.results = results or {}
        self.call_log = []
        self.default_result = PhaseResult(success=True)
        self._call_count = {}

    def dispatch(self, phase, state):
        self.call_log.append(phase)
        count = self._call_count.get(phase, 0)
        self._call_count[phase] = count + 1
        result_or_fn = self.results.get(phase, self.default_result)
        if callable(result_or_fn):
            return result_or_fn(count)
        return result_or_fn


class TestOrchestratorWithCodingWorkflow:
    def test_happy_path_completes(self):
        dispatcher = ConfigurableDispatcher()
        orch = Orchestrator(dispatcher=dispatcher)
        state = orch.run("test task")
        assert state.current_phase == Phase.COMPLETED

    def test_all_phases_dispatched(self):
        dispatcher = ConfigurableDispatcher()
        orch = Orchestrator(dispatcher=dispatcher)
        orch.run("test task")
        expected = [
            "INTAKE", "CONTRACT", "REPO_MAP", "PLAN",
            "RETRIEVE", "PATCH", "CRITIQUE", "RUN",
            "FINALIZE",
        ]
        assert dispatcher.call_log == expected

    def test_fix_loop(self):
        call_count = {"run": 0}

        def run_result(count):
            call_count["run"] += 1
            if call_count["run"] <= 1:
                return PhaseResult(success=False, error="tests failed")
            return PhaseResult(success=True)

        dispatcher = ConfigurableDispatcher(results={"RUN": run_result})
        orch = Orchestrator(dispatcher=dispatcher)
        state = orch.run("test task")
        assert state.current_phase == Phase.COMPLETED

    def test_fix_loop_call_order(self):
        call_count = {"run": 0}

        def run_result(count):
            call_count["run"] += 1
            if call_count["run"] <= 1:
                return PhaseResult(success=False, error="tests failed")
            return PhaseResult(success=True)

        dispatcher = ConfigurableDispatcher(results={"RUN": run_result})
        orch = Orchestrator(dispatcher=dispatcher)
        orch.run("test task")
        expected = [
            "INTAKE", "CONTRACT", "REPO_MAP", "PLAN",
            "RETRIEVE", "PATCH", "CRITIQUE", "RUN",
            "FIX",
            "PATCH", "CRITIQUE", "RUN",
            "FINALIZE",
        ]
        assert dispatcher.call_log == expected


# ---------------------------------------------------------------------------
# Orchestrator with GENERIC_WORKFLOW
# ---------------------------------------------------------------------------

class TestOrchestratorWithGenericWorkflow:
    def test_happy_path_completes(self):
        dispatcher = ConfigurableDispatcher()
        generic = get_generic_workflow()
        orch = Orchestrator(dispatcher=dispatcher, workflow=generic)
        state = orch.run("test task")
        assert state.current_phase == "COMPLETED"

    def test_phases_dispatched(self):
        dispatcher = ConfigurableDispatcher()
        generic = get_generic_workflow()
        orch = Orchestrator(dispatcher=dispatcher, workflow=generic)
        orch.run("test task")
        expected = ["INTAKE", "PLAN", "EXECUTE", "EVALUATE", "FINALIZE"]
        assert dispatcher.call_log == expected

    def test_evaluate_failure_loops_to_plan(self):
        call_count = {"eval": 0}

        def eval_result(count):
            call_count["eval"] += 1
            if call_count["eval"] <= 1:
                return PhaseResult(success=False, error="not good enough")
            return PhaseResult(success=True)

        dispatcher = ConfigurableDispatcher(results={"EVALUATE": eval_result})
        generic = get_generic_workflow()
        orch = Orchestrator(dispatcher=dispatcher, workflow=generic)
        state = orch.run("test task")
        assert state.current_phase == "COMPLETED"
        expected = [
            "INTAKE", "PLAN", "EXECUTE", "EVALUATE",
            "PLAN", "EXECUTE", "EVALUATE",
            "FINALIZE",
        ]
        assert dispatcher.call_log == expected

    def test_starts_at_intake(self):
        dispatcher = ConfigurableDispatcher()
        generic = get_generic_workflow()
        orch = Orchestrator(dispatcher=dispatcher, workflow=generic)
        state = orch.run("test task")
        assert dispatcher.call_log[0] == "INTAKE"

    def test_budget_halt(self):
        dispatcher = ConfigurableDispatcher(results={
            "EVALUATE": PhaseResult(success=False, error="always fails"),
        })
        generic = get_generic_workflow()
        budget = BudgetConfig(max_total_iterations=10, max_phase_retries=100)
        orch = Orchestrator(
            dispatcher=dispatcher, budget=budget, workflow=generic,
        )
        state = orch.run("test task")
        assert state.current_phase == "HALTED"
        assert "iterations" in state.halt_reason.lower()

    def test_phase_retry_on_linear_failure(self):
        """PLAN failure retries (no branch rule for PLAN)."""
        call_count = {"plan": 0}

        def plan_result(count):
            call_count["plan"] += 1
            if call_count["plan"] <= 1:
                return PhaseResult(success=False, error="bad plan")
            return PhaseResult(success=True)

        dispatcher = ConfigurableDispatcher(results={"PLAN": plan_result})
        generic = get_generic_workflow()
        orch = Orchestrator(dispatcher=dispatcher, workflow=generic)
        state = orch.run("test task")
        assert state.current_phase == "COMPLETED"
        # PLAN dispatched twice (fail + succeed)
        assert dispatcher.call_log.count("PLAN") == 2


# ---------------------------------------------------------------------------
# Custom workflow template
# ---------------------------------------------------------------------------

class TestCustomWorkflow:
    def test_three_phase_workflow(self):
        """A minimal custom workflow: START -> WORK -> DONE."""
        wf = WorkflowTemplate(
            name="minimal",
            phases=("START", "WORK", "DONE", "HALTED"),
            transitions={
                "START": frozenset({"WORK", "HALTED"}),
                "WORK":  frozenset({"DONE", "HALTED"}),
                "DONE":  frozenset(),
                "HALTED": frozenset(),
            },
            phase_schemas={},
            phase_order=("START", "WORK"),
            branch_rules={
                "WORK": lambda r: "DONE" if r.success else "START",
            },
            terminal_phases=frozenset({"DONE", "HALTED"}),
            phase_capabilities={
                "START": frozenset({"fs.read"}),
                "WORK":  frozenset({"fs.read", "fs.write"}),
            },
        )
        dispatcher = ConfigurableDispatcher()
        orch = Orchestrator(dispatcher=dispatcher, workflow=wf)
        state = orch.run("custom task")
        assert state.current_phase == "DONE"
        assert dispatcher.call_log == ["START", "WORK"]

    def test_custom_loop(self):
        """Custom workflow with WORK->REVIEW->WORK loop."""
        wf = WorkflowTemplate(
            name="looping",
            phases=("START", "WORK", "REVIEW", "DONE", "HALTED"),
            transitions={
                "START":  frozenset({"WORK", "HALTED"}),
                "WORK":   frozenset({"REVIEW", "HALTED"}),
                "REVIEW": frozenset({"WORK", "DONE", "HALTED"}),
                "DONE":   frozenset(),
                "HALTED": frozenset(),
            },
            phase_schemas={},
            phase_order=("START", "WORK"),
            branch_rules={
                "WORK": lambda r: "REVIEW",
                "REVIEW": lambda r: "DONE" if r.success else "WORK",
            },
            terminal_phases=frozenset({"DONE", "HALTED"}),
            phase_capabilities={},
        )
        call_count = {"review": 0}

        def review_result(count):
            call_count["review"] += 1
            if call_count["review"] <= 1:
                return PhaseResult(success=False, error="needs rework")
            return PhaseResult(success=True)

        dispatcher = ConfigurableDispatcher(results={"REVIEW": review_result})
        orch = Orchestrator(dispatcher=dispatcher, workflow=wf)
        state = orch.run("task")
        assert state.current_phase == "DONE"
        assert dispatcher.call_log == ["START", "WORK", "REVIEW", "WORK", "REVIEW"]


# ---------------------------------------------------------------------------
# validate_transition with custom transitions
# ---------------------------------------------------------------------------

class TestValidateTransitionCustom:
    def test_custom_transitions(self):
        custom = {"X": frozenset({"Y"}), "Y": frozenset()}
        validate_transition("X", "Y", custom)

    def test_custom_transitions_reject(self):
        custom = {"X": frozenset({"Y"}), "Y": frozenset()}
        with pytest.raises(InvalidTransition):
            validate_transition("X", "Z", custom)

    def test_default_transitions(self):
        """Without custom transitions, uses global TRANSITIONS."""
        validate_transition(Phase.INTAKE, Phase.CONTRACT)

    def test_string_with_default(self):
        """String args work with default TRANSITIONS (Phase is str,Enum)."""
        validate_transition("INTAKE", "CONTRACT")


# ---------------------------------------------------------------------------
# InvalidTransition with string phases
# ---------------------------------------------------------------------------

class TestInvalidTransitionStrings:
    def test_string_phases(self):
        exc = InvalidTransition("ALPHA", "BETA")
        assert "ALPHA" in str(exc)
        assert "BETA" in str(exc)
        assert exc.from_phase == "ALPHA"
        assert exc.to_phase == "BETA"

    def test_phase_enum_phases(self):
        exc = InvalidTransition(Phase.INTAKE, Phase.RUN)
        assert "INTAKE" in str(exc)
        assert "RUN" in str(exc)


# ---------------------------------------------------------------------------
# Workflow singleton behavior
# ---------------------------------------------------------------------------

class TestWorkflowSingletons:
    def test_coding_same_object(self):
        a = get_coding_workflow()
        b = get_coding_workflow()
        assert a is b

    def test_generic_same_object(self):
        a = get_generic_workflow()
        b = get_generic_workflow()
        assert a is b

    def test_coding_not_generic(self):
        assert get_coding_workflow() != get_generic_workflow()
