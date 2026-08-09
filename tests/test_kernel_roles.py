# tests/test_kernel_roles.py — the roles that replaced StubDispatcher

"""What a phase does, and what it does when it cannot.

The thing under test is mostly a *refusal*: ``StubDispatcher`` returned
``PhaseResult(success=True)`` for every phase, so ``run_task()`` walked
to COMPLETED having done nothing.  Most of what follows checks that the
same run now halts, loudly, at the phase that could not produce its
artifact — and that a run whose model answers properly still completes.
"""

import json

import pytest

from core.contracts.schemas import ChangePlan, PolicyPack, TaskContract
from core.judge.models import JudgeReport
from core.kernel.budgets import BudgetConfig
from core.kernel.orchestrator import Orchestrator, PhaseResult
from core.kernel.roles import (
    IntakeRole,
    LLMPhaseRole,
    LLMRoleDispatcher,
    PhaseRole,
    RepoMapRole,
    RoleContext,
    RoleMisdeclared,
    RoleRefused,
    RunRole,
    ToolPhaseRole,
    default_roles,
)
from core.kernel.state import Phase, SessionState
from core.kernel.workflows import get_coding_workflow
from core.tools.bus import ToolBus
from core.tools.capability import CapabilityEngine
from core.tools.descriptors import ToolDescriptor


# ---------------------------------------------------------------------------
# Doubles
# ---------------------------------------------------------------------------

class ScriptedModel:
    """Answers each phase with whatever the script says for it."""

    def __init__(self, by_phase=None, default="I am not JSON."):
        self.by_phase = dict(by_phase or {})
        self.default = default
        self.asked = []

    def __call__(self, messages):
        system = messages[0]["content"]
        self.asked.append(system)
        for phase, reply in self.by_phase.items():
            if f"Phase {phase}." in system:
                return reply
        return self.default


GOOD_SCRIPT = {
    "INTAKE": json.dumps({
        "task_id": "t1", "description": "add pagination",
        "acceptance_criteria": ["tests pass"],
    }),
    "CONTRACT": json.dumps({"task_id": "t1", "description": "add pagination"}),
    "PLAN": json.dumps({
        "task_id": "t1",
        "steps": [{"description": "edit views", "target_file": "v.py",
                   "action": "modify"}],
    }),
    "RETRIEVE": json.dumps({"task_id": "t1", "repo_map_excerpt": "v.py"}),
    "PATCH": json.dumps({
        "task_id": "t1",
        "patches": [{"file_path": "v.py", "search_block": "a",
                     "replace_block": "b", "action": "modify"}],
    }),
}


def make_bus(*, test_rc=0, lint_rc=0, allowed=("*",)):
    bus = ToolBus(capability_engine=CapabilityEngine(
        PolicyPack(allowed_scopes=list(allowed))))
    bus.register(
        ToolDescriptor(tool_name="repo_map", required_scopes=["fs.read"],
                       action_scopes={"excerpt": ["fs.read"]},
                       description="Repository map."),
        lambda action=None, **kw: (
            0, json.dumps({"excerpt": "core/ …", "total_files": 3}), ""),
    )
    bus.register(
        ToolDescriptor(tool_name="verify", required_scopes=["verify.run"],
                       action_scopes={"test": ["verify.run"],
                                      "lint": ["verify.run"]},
                       description="Verification."),
        lambda action=None, **kw: (
            (test_rc, "3 passed" if test_rc == 0 else "1 failed", "")
            if action == "test" else (lint_rc, "clean", "")),
    )
    return bus


def make_ctx(model=None, bus=None, **kw):
    return RoleContext(
        chat=model or ScriptedModel(),
        tool_bus=bus,
        workflow=get_coding_workflow(),
        budget=kw.pop("budget", BudgetConfig()),
        **kw,
    )


# ---------------------------------------------------------------------------
# Declaration is checked at class creation
# ---------------------------------------------------------------------------

class TestRoleDeclaration:
    def test_every_shipped_role_declares_a_phase_and_an_instruction(self):
        for role in default_roles():
            assert role.phase
            assert role.instruction

    def test_shipped_roles_cover_the_coding_workflow(self):
        served = {r.phase for r in default_roles()}
        workflow = get_coding_workflow()
        assert served == set(workflow.phases) - workflow.terminal_phases

    def test_a_role_without_a_phase_is_refused(self):
        with pytest.raises(RoleMisdeclared, match="`phase` is empty"):
            class Anonymous(PhaseRole):
                instruction = "do a thing"

                def produce(self, state, ctx): return None

    def test_a_role_without_an_instruction_is_refused(self):
        with pytest.raises(RoleMisdeclared, match="`instruction` is empty"):
            class Mute(PhaseRole):
                phase = "PLAN"

                def produce(self, state, ctx): return None

    def test_overriding_run_is_refused(self):
        """The whole bug, prevented structurally."""
        with pytest.raises(RoleMisdeclared, match="which is final"):
            class Liar(PhaseRole):
                phase = "PLAN"
                instruction = "plan"

                def produce(self, state, ctx): return None
                def run(self, state, ctx): return PhaseResult(success=True)

    def test_every_problem_is_reported_at_once(self):
        with pytest.raises(RoleMisdeclared) as exc:
            class AllWrong(PhaseRole):
                pass

        message = str(exc.value)
        assert "`phase` is empty" in message
        assert "`instruction` is empty" in message
        assert "does not implement `produce`" in message

    def test_intermediate_bases_are_allowed(self):
        assert LLMPhaseRole.abstract is True
        assert ToolPhaseRole.abstract is True


# ---------------------------------------------------------------------------
# The template decides success — the role never does
# ---------------------------------------------------------------------------

class TestTheTemplate:
    def test_valid_output_succeeds(self):
        role = IntakeRole()
        model = ScriptedModel({"INTAKE": GOOD_SCRIPT["INTAKE"]})
        result = role.run(SessionState(task_description="x"), make_ctx(model))
        assert result.success
        assert isinstance(result.output, TaskContract)

    def test_prose_where_a_schema_was_required_fails_the_phase(self):
        """The stub's exact scenario: a reply that is not the artifact."""
        result = IntakeRole().run(SessionState(task_description="x"), make_ctx())
        assert result.success is False
        assert "not valid JSON" in result.error or "returned something else" in result.error

    def test_json_of_the_wrong_shape_fails_the_phase(self):
        model = ScriptedModel({"PLAN": json.dumps({"steps": "not a list"})})
        from core.kernel.roles import PlanRole

        result = PlanRole().run(SessionState(task_description="x"), make_ctx(model))
        assert result.success is False
        assert "ChangePlan" in result.error

    def test_an_empty_reply_fails_the_phase(self):
        model = ScriptedModel({"INTAKE": ""})
        result = IntakeRole().run(SessionState(task_description="x"), make_ctx(model))
        assert result.success is False
        assert "returned nothing" in result.error

    def test_a_fenced_reply_is_accepted(self):
        model = ScriptedModel({"INTAKE": f"```json\n{GOOD_SCRIPT['INTAKE']}\n```"})
        result = IntakeRole().run(SessionState(task_description="x"), make_ctx(model))
        assert result.success

    def test_a_raising_role_becomes_a_failed_phase_not_a_traceback(self):
        class Exploding(PhaseRole):
            phase = "PLAN"
            instruction = "plan"

            def produce(self, state, ctx):
                raise ValueError("kaboom")

        result = Exploding().run(SessionState(task_description="x"), make_ctx())
        assert result.success is False
        assert "kaboom" in result.error

    def test_a_refusal_names_the_reason(self):
        class Refusing(PhaseRole):
            phase = "PLAN"
            instruction = "plan"

            def produce(self, state, ctx):
                raise RoleRefused("the repository is not a git checkout")

        result = Refusing().run(SessionState(task_description="x"), make_ctx())
        assert result.success is False
        assert "not a git checkout" in result.error

    def test_a_schemaless_phase_passes_text_through(self):
        class Freeform(PhaseRole):
            phase = "NOTES"
            instruction = "take notes"

            def produce(self, state, ctx):
                return "some notes"

        result = Freeform().run(SessionState(task_description="x"), make_ctx())
        assert result.success
        assert result.output == "some notes"


# ---------------------------------------------------------------------------
# Facts come from tools, not from the model
# ---------------------------------------------------------------------------

class TestToolRoles:
    def test_the_repo_map_comes_from_the_tool(self):
        bus = make_bus()
        result = RepoMapRole().run(SessionState(task_description="x"),
                                   make_ctx(bus=bus))
        assert result.success
        assert result.output.total_files == 3

    def test_the_test_result_is_the_tools_exit_code(self):
        for rc, passed in ((0, True), (1, False)):
            result = RunRole().run(SessionState(task_description="x"),
                                   make_ctx(bus=make_bus(test_rc=rc)))
            assert result.output.exit_code == rc
            assert result.output.passed is passed

    def test_no_bus_is_a_refusal_and_not_a_crash(self):
        result = RepoMapRole().run(SessionState(task_description="x"), make_ctx())
        assert result.success is False
        assert "no ToolBus" in result.error

    def test_a_capability_denial_fails_the_phase(self):
        """The phase scopes are the orchestrator's; a role just obeys."""
        bus = make_bus(allowed=("fs.read",))  # no verify.run
        result = RunRole().run(SessionState(task_description="x"),
                               make_ctx(bus=bus))
        assert result.output.passed is False
        assert "capability_denied" in result.output.stderr

    def test_a_tool_failure_refuses_rather_than_inventing_a_map(self):
        bus = make_bus()
        bus.register(
            ToolDescriptor(tool_name="repo_map", action_scopes={"excerpt": []}),
            lambda action=None, **kw: (1, "", "not a git repository"),
        )
        result = RepoMapRole().run(SessionState(task_description="x"),
                                   make_ctx(bus=bus))
        assert result.success is False
        assert "not a git repository" in result.error


# ---------------------------------------------------------------------------
# The dispatcher
# ---------------------------------------------------------------------------

class TestDispatcher:
    def test_an_unmapped_phase_is_refused_not_succeeded(self):
        """StubDispatcher's defining behaviour, now impossible."""
        d = LLMRoleDispatcher(chat_fn=ScriptedModel(), roles=[IntakeRole()])
        result = d.dispatch("PATCH", SessionState(task_description="x"))
        assert result.success is False
        assert "no role is registered" in result.error

    def test_it_routes_by_phase(self):
        model = ScriptedModel(GOOD_SCRIPT)
        d = LLMRoleDispatcher(chat_fn=model, tool_bus=make_bus())
        result = d.dispatch("PLAN", SessionState(task_description="x"))
        assert result.success
        assert isinstance(result.output, ChangePlan)

    def test_the_run_report_is_left_for_critique(self):
        d = LLMRoleDispatcher(chat_fn=ScriptedModel(), tool_bus=make_bus())
        state = SessionState(task_description="x")
        d.dispatch("RUN", state)
        assert state.artifacts["_run_report"].passed is True

    def test_a_failing_run_is_a_failed_phase(self):
        d = LLMRoleDispatcher(chat_fn=ScriptedModel(), tool_bus=make_bus(test_rc=1))
        result = d.dispatch("RUN", SessionState(task_description="x"))
        assert result.success is False

    def test_critique_scores_with_the_judge(self):
        d = LLMRoleDispatcher(chat_fn=ScriptedModel(), tool_bus=make_bus())
        state = SessionState(task_description="x")
        d.dispatch("RUN", state)
        result = d.dispatch("CRITIQUE", state)
        assert isinstance(result.output, JudgeReport)
        assert result.output.verdict == "pass"


# ---------------------------------------------------------------------------
# Budgets reach the roles
# ---------------------------------------------------------------------------

class TestBudgets:
    def test_the_per_role_context_cap_truncates_a_huge_prompt(self):
        seen = {}

        def capture(messages):
            seen["len"] = max(len(m["content"]) for m in messages)
            return GOOD_SCRIPT["INTAKE"]

        ctx = make_ctx(capture, budget=BudgetConfig(max_context_tokens_per_role=10))
        ctx.remember("x" * 100_000)
        IntakeRole().run(SessionState(task_description="y"), ctx)
        assert seen["len"] <= 10 * 4 + 80

    def test_tool_output_is_capped_in_the_trace(self):
        ctx = make_ctx(budget=BudgetConfig(max_tool_output_bytes_in_context=50))
        ctx.remember("y" * 10_000)
        assert len(ctx.trace[0]) < 200
        assert "truncated" in ctx.trace[0]


# ---------------------------------------------------------------------------
# End to end, through the real orchestrator
# ---------------------------------------------------------------------------

class TestThroughTheOrchestrator:
    def _run(self, model, bus, budget=None):
        workflow = get_coding_workflow()
        return Orchestrator(
            dispatcher=LLMRoleDispatcher(chat_fn=model, tool_bus=bus,
                                         workflow=workflow),
            workflow=workflow,
            tool_bus=bus,
            budget=budget or BudgetConfig(),
        ).run("add pagination")

    def test_a_model_that_answers_properly_completes(self):
        state = self._run(ScriptedModel(GOOD_SCRIPT), make_bus())
        assert state.current_phase == Phase.COMPLETED

    def test_a_model_that_only_chats_halts_at_the_first_phase(self):
        """Was COMPLETED, silently, having produced nothing."""
        state = self._run(ScriptedModel(), make_bus())
        assert state.current_phase == Phase.HALTED
        assert "INTAKE" in state.halt_reason

    def test_failing_tests_route_to_FIX_not_to_success(self):
        model = ScriptedModel({**GOOD_SCRIPT, "FIX": GOOD_SCRIPT["PATCH"]})
        state = self._run(model, make_bus(test_rc=1),
                          budget=BudgetConfig(max_total_iterations=12))
        assert state.current_phase == Phase.HALTED
        assert "iterations" in state.halt_reason.lower()

    def test_every_phase_of_a_completed_run_was_actually_asked(self):
        model = ScriptedModel(GOOD_SCRIPT)
        self._run(model, make_bus())
        asked = " ".join(model.asked)
        for phase in ("INTAKE", "CONTRACT", "PLAN", "RETRIEVE", "PATCH"):
            assert f"Phase {phase}." in asked
