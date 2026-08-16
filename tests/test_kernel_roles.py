# tests/test_kernel_roles.py — the roles that replaced StubDispatcher

"""What a phase does, and what it does when it cannot.

The thing under test is mostly a *refusal*: ``StubDispatcher`` returned
``PhaseResult(success=True)`` for every phase, so ``run_task()`` walked
to COMPLETED having done nothing.  Most of what follows checks that the
same run now halts, loudly, at the phase that could not produce its
artifact — and that a run whose model answers properly still completes.
"""

import json
from types import SimpleNamespace

import pytest

from core.contracts.schemas import ChangePlan, PolicyPack, TaskContract
from core.judge.models import JudgeReport
from core.kernel.budgets import BudgetConfig
from core.kernel.orchestrator import Orchestrator, PhaseResult
from core.kernel.roles import (
    AuthoredToolPhaseRole,
    CritiqueRole,
    FixRole,
    IntakeRole,
    LLMPhaseRole,
    LLMRoleDispatcher,
    PatchRole,
    PhaseRole,
    PlanRole,
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
from core.runtime.context_window import Compaction, MissionWindow
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


def make_bus(*, test_rc=0, lint_rc=0, patch_rc=0, allowed=("*",)):
    """A bus with the three tools the coding roles dispatch.

    ``patch`` is here because PATCH now *applies* what the model wrote.
    While it was absent these tests still reported a completed run: the
    phase produced a schema-valid ``PatchSet``, nobody dispatched it, and
    the pipeline walked to COMPLETED having changed nothing. The double
    records what it was handed so a test can assert the patch set
    actually reached a tool, and returns the engine's own result shape —
    including the ``diff``, which is what CRITIQUE reviews.
    """
    bus = ToolBus(capability_engine=CapabilityEngine(
        PolicyPack(allowed_scopes=list(allowed))))
    applied = []

    def patch_tool(action=None, *, patch_set_json="", **kw):
        if action != "apply":
            return (0, json.dumps({"success": True}), "")
        applied.append({"patch_set": json.loads(patch_set_json or "{}"),
                        "kwargs": dict(kw)})
        if patch_rc != 0:
            return (patch_rc, json.dumps({
                "success": False,
                "file_results": [{"file_path": "v.py", "success": False,
                                  "error": "search block not found"}],
            }), "")
        return (0, json.dumps({
            "success": True,
            "file_results": [{"file_path": "v.py", "success": True}],
            "diff": "--- a/v.py\n+++ b/v.py\n@@\n-a\n+b\n",
        }), "")

    bus.register(
        ToolDescriptor(tool_name="patch",
                       required_scopes=["fs.read", "fs.write", "git.write"],
                       action_scopes={"apply": ["fs.read", "fs.write",
                                                "git.write"]},
                       description="Patch engine."),
        patch_tool,
    )
    bus.applied = applied
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
        assert AuthoredToolPhaseRole.abstract is True


class TestAuthoredToolRoleDeclaration:
    """The third kind checks its own extra requirement, in the same message.

    A role of this kind that dispatches nothing is the original defect
    wearing the new base class's name, so `settles_with` is checked where
    `phase` and `instruction` are — and the checks compose across levels
    rather than raising twice.
    """

    def test_a_role_that_settles_with_nothing_is_refused(self):
        with pytest.raises(RoleMisdeclared, match="`settles_with` names no tool"):
            class Unsettled(AuthoredToolPhaseRole):
                phase = "PATCH"
                instruction = "write patches"

                def settle(self, state, ctx, authored): return authored

    def test_a_role_that_never_settles_is_refused(self):
        with pytest.raises(RoleMisdeclared, match="does not implement `settle`"):
            class NeverSettles(AuthoredToolPhaseRole):
                phase = "PATCH"
                instruction = "write patches"
                settles_with = ("patch", "apply")

    def test_overriding_produce_is_refused(self):
        """`produce` is final here for the reason `run` is final above.

        A subclass that overrode it could return the model's proposal
        and skip the settlement, which is the whole bug.
        """
        with pytest.raises(RoleMisdeclared, match="overrides `produce`"):
            class SkipsTheTool(AuthoredToolPhaseRole):
                phase = "PATCH"
                instruction = "write patches"
                settles_with = ("patch", "apply")

                def settle(self, state, ctx, authored): return authored
                def produce(self, state, ctx): return {"task_id": "t"}

    def test_every_problem_across_both_levels_arrives_at_once(self):
        """The base's checks and this kind's, in one message.

        Two `__init_subclass__` hooks, each raising, would report the
        first level's problems and hide the second's until they were
        fixed — a round trip per mistake.
        """
        with pytest.raises(RoleMisdeclared) as exc:
            class AllWrong(AuthoredToolPhaseRole):
                pass

        message = str(exc.value)
        assert "`phase` is empty" in message
        assert "`instruction` is empty" in message
        assert "does not implement `settle`" in message
        assert "`settles_with` names no tool" in message

    def test_the_shipped_authored_roles_name_their_tool(self):
        from core.kernel.roles import RetrieveRole
        assert PatchRole.settles_with == ("patch", "apply")
        assert RetrieveRole.settles_with == ("repo_map", "symbol")

    def test_the_checks_run_on_the_roles_that_ship(self):
        """`abstract` used to be inherited, which exempted all of them.

        `LLMPhaseRole.abstract` is True and `IntakeRole` inherits it, so
        `__init_subclass__` returned on its first line for every role in
        `default_roles()`. The validation was declared and ran on
        nothing — visible only by asking a shipped role to fail it.
        """
        assert "abstract" not in IntakeRole.__dict__
        with pytest.raises(RoleMisdeclared, match="`instruction` is empty"):
            class MuteChild(IntakeRole):
                phase = "PLAN"
                instruction = ""


# ---------------------------------------------------------------------------
# PATCH: the model authors, the tool disposes
# ---------------------------------------------------------------------------

class TestPatchIsApplied:
    """`PatchSet` used to be produced and dispatched to nothing."""

    def _run(self, bus, patches=None, phase="PATCH"):
        body = {"task_id": "t1", "patches": patches if patches is not None else [
            {"file_path": "v.py", "search_block": "a", "replace_block": "b",
             "action": "modify"},
        ]}
        role = PatchRole() if phase == "PATCH" else FixRole()
        state = SessionState(task_description="x")
        model = ScriptedModel({phase: json.dumps(body)})
        return role.run(state, make_ctx(model, bus=bus)), state

    def test_the_patch_set_reaches_the_patch_tool(self):
        bus = make_bus()
        result, _state = self._run(bus)
        assert result.success
        assert len(bus.applied) == 1
        assert bus.applied[0]["patch_set"]["patches"][0]["file_path"] == "v.py"

    def test_it_applies_to_the_tree_the_tests_run_in(self):
        """`use_worktree=False`, and not by accident.

        A worktree puts the change somewhere RUN never looks, which is
        the same bug one level down: real files, real diff, tests green
        against the untouched tree.
        """
        bus = make_bus()
        self._run(bus)
        assert bus.applied[0]["kwargs"]["use_worktree"] is False

    def test_the_diff_is_left_where_critique_reads_it(self):
        bus = make_bus()
        _result, state = self._run(bus)
        assert "+b" in state.artifacts["_diff"]

    def test_a_patch_that_does_not_apply_fails_the_phase(self):
        result, state = self._run(make_bus(patch_rc=1))
        assert result.success is False
        assert "did not apply" in result.error
        # The per-file reason, named — not the engine's JSON handed on
        # whole. FIX is told to read the failure, and "which search block
        # missed, in which file" is the part it has to read; a serialised
        # result contains that string too, which is why this asserts the
        # rendering and not merely the substring.
        assert "v.py: search block not found" in result.error
        assert "file_results" not in result.error
        assert "_diff" not in state.artifacts

    def test_an_empty_patch_set_is_refused(self):
        result, _state = self._run(make_bus(), patches=[])
        assert result.success is False
        assert "no patches" in result.error

    def test_no_bus_is_a_refusal_and_not_a_silent_success(self):
        model = ScriptedModel({"PATCH": GOOD_SCRIPT["PATCH"]})
        result = PatchRole().run(SessionState(task_description="x"),
                                 make_ctx(model))
        assert result.success is False
        assert "no ToolBus" in result.error

    def test_a_capability_denial_fails_the_phase(self):
        """PATCH is the only phase granted fs.write; without it, no change."""
        bus = make_bus(allowed=("fs.read",))
        result, state = self._run(bus)
        assert result.success is False
        assert "_diff" not in state.artifacts

    def test_fix_diagnoses_and_does_not_apply(self):
        """FIX subclassed PatchRole, and the workflow sends FIX to PATCH.

        Applying in both would apply the same change twice: the first
        replaces the text the second searches for, so the second fails
        against a file that is already right and the run halts on a
        patch that worked. One phase writes, and it is the one the
        orchestrator's checkpoint brackets.
        """
        bus = make_bus()
        model = ScriptedModel({"FIX": "the assertion in v.py:12 wants b"})
        state = SessionState(task_description="x")
        ctx = make_ctx(model, bus=bus)

        result = FixRole().run(state, ctx)

        assert result.success
        assert bus.applied == []
        assert "_diff" not in state.artifacts
        # The diagnosis is how the next PATCH turn knows what went wrong.
        assert "v.py:12" in ctx.recent()


class TestCritiqueHasAReviewer:
    def test_the_default_judge_can_reach_the_model(self):
        """`CompositeJudge()` gives LLMReviewTier no chat_fn at all.

        A judge whose review tier can never speak reports itself as
        three tiers and votes with two — and the rescaling that makes an
        absent reviewer cost nothing is exactly what hides it.
        """
        state = SessionState(task_description="x")
        state.artifacts["_diff"] = "--- a/v.py\n+++ b/v.py\n@@\n-a\n+b\n"
        review = json.dumps({"score": 0.8, "verdict": "pass",
                             "concerns": ["naming"]})
        model = ScriptedModel(default=review)

        result = CritiqueRole().run(state, make_ctx(model, bus=make_bus()))
        tier = next(t for t in result.output.tier_results
                    if t.tier_name == "llm_review")
        assert tier.verdict.value != "unknown"
        assert tier.score == 0.8

    def test_an_injected_judge_still_wins(self):
        class Fixed:
            def evaluate(self, **kw):
                from core.judge.models import JudgeReport
                return JudgeReport(tier_results=[], final_score=1.0,
                                   verdict="pass")

        result = CritiqueRole(judge=Fixed()).run(
            SessionState(task_description="x"),
            make_ctx(ScriptedModel(), bus=make_bus()))
        assert result.output.tier_results == []


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

    def test_the_end_of_a_capped_trace_line_survives(self):
        """The cap used to keep the head and drop everything after it.

        A trace line is a tool result rendered for a later phase to read,
        and a tool result puts its totals at the end — a head-only cut
        kept the invocation and threw away the counts CRITIQUE and FIX
        are looking for. Both ends now, through the one shared cut.
        """
        ctx = make_ctx(budget=BudgetConfig(max_tool_output_bytes_in_context=50))
        ctx.remember("HEAD" + "y" * 10_000 + "TAIL: 3 failed")
        assert ctx.trace[0].startswith("HEAD")
        assert ctx.trace[0].endswith("TAIL: 3 failed")

    def test_a_capped_trace_line_says_how_much_went(self):
        ctx = make_ctx(budget=BudgetConfig(max_tool_output_bytes_in_context=50))
        ctx.remember("y" * 10_000)
        assert "30 head + 20 tail bytes of 10000" in ctx.trace[0]

    def test_a_trace_line_inside_the_cap_is_untouched(self):
        ctx = make_ctx(budget=BudgetConfig(max_tool_output_bytes_in_context=50))
        ctx.remember("short line")
        assert ctx.trace[0] == "short line"


# ---------------------------------------------------------------------------
# The window: a role's prompt is bounded against the model's real one
# ---------------------------------------------------------------------------

class Endpoint:
    """A client that states its window, and counts who asked.

    The count is the point of the double.  `MissionWindow` reads
    `capabilities` lazily and remembers the answer because on a local
    backend reading it is a `GET /models` against a server that may still
    be loading weights; a kernel that resolved the profile again per phase
    would pay for that ten times a session and could disagree with the
    mission loop about how big the window is.
    """

    def __init__(self, max_context_tokens=4_000, max_output_tokens=1_000):
        self.reads = 0
        self._caps = SimpleNamespace(
            max_context_tokens=max_context_tokens,
            max_output_tokens=max_output_tokens,
        )

    @property
    def capabilities(self):
        self.reads += 1
        return self._caps


def make_window(input_tokens, *, reserve=1_000, client=None):
    """A window whose *input* budget — the reserve already taken out — is
    exactly ``input_tokens``, built the way the CLI builds the mission's."""
    return MissionWindow(
        provider="openai", model="m",
        client=client or Endpoint(input_tokens + reserve, reserve),
    )


def capturing(reply=GOOD_SCRIPT["PLAN"]):
    """A chat function that keeps every message list it was handed."""

    def chat(messages):
        chat.sent.append(messages)
        return reply

    chat.sent = []
    return chat


def capturing_script(script=None):
    """The same, over `ScriptedModel`, for tests that need two phases."""
    model = ScriptedModel(script if script is not None else GOOD_SCRIPT)

    def chat(messages):
        chat.sent.append(messages)
        return model(messages)

    chat.sent = []
    return chat


def with_trace(ctx, lines=6, size=400):
    """Six trace lines, alternating model reply and tool result.

    Newest is a tool result, because that is what a role's transcript ends
    with in every phase that dispatches — and it is the message the window
    is forbidden to drop.
    """
    for i in range(lines):
        ctx.remember(f"[STEP{i}] " + "z" * size,
                     speaker="assistant" if i % 2 == 0 else "user")
    return ctx


class TestTheEffectiveLimit:
    """`min(per-role budget, resolved profile input budget)`, and no more.

    Two numbers, and neither may raise the other: the budget is a choice
    about spend, the profile is a fact about the endpoint.
    """

    def test_the_per_role_budget_wins_when_it_is_smaller(self):
        ctx = make_ctx(window=make_window(3_000),
                       budget=BudgetConfig(max_context_tokens_per_role=1_000))
        assert ctx.prompt_window.limit_tokens == 1_000

    def test_the_model_profile_wins_when_it_is_smaller(self):
        """A generous budget cannot buy room the server will refuse."""
        ctx = make_ctx(window=make_window(3_000),
                       budget=BudgetConfig(max_context_tokens_per_role=100_000))
        assert ctx.prompt_window.limit_tokens == 3_000

    def test_the_endpoint_is_read_once_however_many_phases_ask(self):
        endpoint = Endpoint(4_000, 1_000)
        ctx = make_ctx(window=make_window(0, client=endpoint))
        assert ctx.prompt_window.limit_tokens == 3_000
        assert ctx.prompt_window.limit_tokens == 3_000
        assert endpoint.reads == 1

    def test_no_window_is_the_per_role_budget_and_nothing_is_probed(self):
        """The library default, and what every fake client gets.

        No window means no model profile — not a fabricated one and not a
        probe of an endpoint nobody offered.
        """
        ctx = make_ctx(budget=BudgetConfig(max_context_tokens_per_role=777))
        assert ctx.prompt_window.limit_tokens == 777
        assert ctx.prompt_window.profile.source == "per_role_budget"


class TestThePromptIsFittedToTheWindow:
    """ROADMAP Phase 8, milestone B2: an agentic phase's prompt goes
    through the window owner.

    The trace used to be folded into the task's own message, so the whole
    prompt was two messages: when it did not fit there was nothing to drop,
    only something to cut by a character count that called itself "not an
    accounting system".  It is now the same policy the mission loop uses —
    pin the role prompt and the task, drop the oldest round trips whole,
    leave a note where they were — over the same estimate.
    """

    def _sent(self, input_tokens, task="add pagination"):
        chat = capturing()
        ctx = with_trace(make_ctx(chat, window=make_window(input_tokens)))
        PlanRole().run(SessionState(task_description=task), ctx)
        return chat.sent[0], ctx

    def test_a_trace_that_would_overflow_is_sent_under_the_cap(self):
        sent, ctx = self._sent(600)
        assert ctx.prompt_window.estimate(sent) <= ctx.prompt_window.limit_tokens

    def test_the_role_prompt_and_the_task_survive(self):
        """Pinned, and not by luck: a phase that has forgotten which phase
        it is or what was asked is a worse failure than a long prompt."""
        sent, _ctx = self._sent(600)
        assert "Phase PLAN." in sent[0]["content"]
        assert "steps" in sent[0]["content"]          # the JSON contract
        assert any("Task: add pagination" in m["content"] for m in sent)

    def test_the_newest_result_survives_and_the_oldest_goes(self):
        sent, _ctx = self._sent(600)
        assert any("[STEP5]" in m["content"] for m in sent)
        assert not any("[STEP0]" in m["content"] for m in sent)

    def test_the_tail_still_begins_with_the_model_own_turn(self):
        """Whole round trips, so no result is left without its call."""
        sent, _ctx = self._sent(600)
        kept = [m for m in sent if "[STEP" in m["content"]]
        assert kept[0]["role"] == "assistant"

    def test_the_model_is_told_that_something_went(self):
        """A silently shortened prompt makes a phase re-run a tool it
        already ran, out of a budget of thirty."""
        sent, _ctx = self._sent(600)
        assert any("[context]" in m["content"] for m in sent)
        assert any("Do not repeat a step" in m["content"] for m in sent)

    def test_the_compaction_is_counted_where_the_phase_can_report_it(self):
        _sent, ctx = self._sent(600)
        assert len(ctx.compactions) == 1
        compaction = ctx.compactions[0]
        assert compaction.dropped_messages == 4
        assert compaction.dropped_turns == 2
        assert compaction.limit_tokens == 600
        assert compaction.tokens_after < compaction.tokens_before

    def test_draining_leaves_the_next_phase_counting_only_its_own(self):
        """Per phase, never a running total.  A reader adding the records
        up must not count the first phase's compaction once for every
        phase that came after it."""
        ctx = with_trace(make_ctx(capturing(), window=make_window(600)))
        PlanRole().run(SessionState(task_description="add pagination"), ctx)
        assert len(ctx.drain_compactions()) == 1
        assert ctx.drain_compactions() == []

    def test_a_prompt_that_fits_is_left_alone(self):
        sent, ctx = self._sent(800)
        assert ctx.compactions == []
        assert any("[STEP0]" in m["content"] for m in sent)
        assert not any("[context]" in m["content"] for m in sent)

    def test_an_earlier_phase_reply_arrives_as_the_model_own_turn(self):
        """`remember` records who spoke, and a model reply is not a tool
        result.  The window drops round trips by reading exactly these
        roles, so a reply filed as tool output makes the next drop take
        half a round trip — a result whose call is gone.
        """
        chat = capturing_script()
        dispatcher = LLMRoleDispatcher(chat_fn=chat, tool_bus=make_bus())
        state = SessionState(task_description="add pagination")
        dispatcher.dispatch("INTAKE", state)
        dispatcher.dispatch("PLAN", state)

        carried = [m for m in chat.sent[1] if "[INTAKE]" in m["content"]]
        assert carried
        assert all(m["role"] == "assistant" for m in carried)

    def test_a_tool_result_arrives_as_the_turn_the_role_was_given(self):
        chat = capturing_script()
        dispatcher = LLMRoleDispatcher(chat_fn=chat, tool_bus=make_bus())
        state = SessionState(task_description="add pagination")
        dispatcher.dispatch("REPO_MAP", state)
        dispatcher.dispatch("PLAN", state)

        carried = [m for m in chat.sent[0] if "[REPO_MAP]" in m["content"]]
        assert carried
        assert all(m["role"] == "user" for m in carried)

    def test_the_transcript_reaches_the_model_as_its_own_turns(self):
        sent, _ctx = self._sent(800)
        assert [m["role"] for m in sent] == [
            "system", "user",
            "assistant", "user", "assistant", "user", "assistant", "user",
        ]


class TestNoWindowLeavesTheOldBehaviour:
    """`window=None` is what a caller with a stubbed client has always had.

    The per-role budget is then the only limit and nothing is probed to
    find another one.
    """

    def test_the_whole_transcript_goes_and_nothing_is_recorded(self):
        chat = capturing()
        ctx = with_trace(make_ctx(chat))
        PlanRole().run(SessionState(task_description="add pagination"), ctx)
        sent = chat.sent[0]
        assert len(sent) == 8                       # role prompt, task, six
        assert any("[STEP0]" in m["content"] for m in sent)
        assert ctx.compactions == []

    def test_the_character_cap_follows_the_limit_that_actually_applies(self):
        """It used to be the per-role budget times four whatever the
        endpoint said.  A message no window is allowed to drop — the task
        itself — is now cut at the smaller of the two.
        """
        chat = capturing()
        ctx = make_ctx(chat, window=make_window(50),
                       budget=BudgetConfig(max_context_tokens_per_role=100_000))
        PlanRole().run(SessionState(task_description="q" * 10_000), ctx)
        task = chat.sent[0][1]["content"]
        assert len(task) <= 50 * 4 + 80
        assert "truncated" in task


class TestTheCompactionIsRecorded:
    """A compaction the session did not write down is the silent
    truncation the window was built to replace."""

    def _run(self, tmp_path, input_tokens=120):
        from core.sessions.manager import SessionManager

        workflow = get_coding_workflow()
        bus = make_bus()
        manager = SessionManager(tmp_path)
        Orchestrator(
            dispatcher=LLMRoleDispatcher(
                chat_fn=ScriptedModel(GOOD_SCRIPT), tool_bus=bus,
                workflow=workflow, window=make_window(input_tokens)),
            workflow=workflow, tool_bus=bus, session_manager=manager,
        ).run("add pagination")
        return manager

    def test_a_run_that_compacts_leaves_a_record_per_compaction(self, tmp_path):
        records = self._run(tmp_path).load_context_warnings()
        assert records
        assert all(r["dropped_messages"] >= 1 for r in records)

    def test_the_record_is_the_mission_shape_plus_where_it_happened(self, tmp_path):
        """One shape, owned by `Compaction`.  A watcher that has learned to
        read the mission stream's `compacted` field reads this too — and if
        that dataclass grows a field, this record grows it as well rather
        than becoming a second, staler answer."""
        records = self._run(tmp_path).load_context_warnings()
        expected = set(Compaction(0, 0, 0, 0, 0, 0, "x").as_record()) | {"phase"}
        assert set(records[0]) == expected
        assert records[0]["limit_tokens"] == 120
        assert records[0]["profile"] == "backend"
        assert records[0]["phase"] in {role.phase for role in default_roles()}

    def test_a_phase_that_compacted_and_then_failed_still_leaves_it(
        self, tmp_path,
    ):
        """The most interesting compaction there is.

        Recorded before the phase's artifact is validated, because a record
        kept only on success is missing exactly when someone goes looking
        for why the phase went wrong.
        """
        from core.sessions.manager import SessionManager

        workflow = get_coding_workflow()
        bus = make_bus()
        manager = SessionManager(tmp_path)
        state = Orchestrator(
            dispatcher=LLMRoleDispatcher(
                chat_fn=ScriptedModel({**GOOD_SCRIPT, "PLAN": "no JSON here"}),
                tool_bus=bus, workflow=workflow, window=make_window(120)),
            workflow=workflow, tool_bus=bus, session_manager=manager,
            budget=BudgetConfig(max_phase_retries=1),
        ).run("add pagination")

        assert state.current_phase == Phase.HALTED
        assert "PLAN" in state.halt_reason
        assert "PLAN" in {r["phase"] for r in manager.load_context_warnings()}

    def test_a_run_that_fits_records_nothing(self, tmp_path):
        assert self._run(tmp_path, input_tokens=100_000).load_context_warnings() == []

    def test_the_record_outlives_the_rollback_that_undoes_the_artifacts(
        self, tmp_path,
    ):
        """Beside the artifacts, not among them.  The orchestrator restores
        the artifacts directory when RUN fails, and a rollback must not
        un-say that a prompt had to be shortened on the way there."""
        from core.sessions.manager import SessionManager

        manager = SessionManager(tmp_path)
        manager.checkpoint("pre_PATCH_000")
        path = manager.write_context_warning({"phase": "PATCH"})
        manager.rollback("pre_PATCH_000")

        assert path.exists()
        assert path.name == "context_warn_000.json"
        assert manager.load_context_warnings() == [{"phase": "PATCH"}]


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
