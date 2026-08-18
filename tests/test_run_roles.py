# tests/test_run_roles.py — Phase 11 lane E: chat and the roles through `Run`
#
# Three seams meet here and one thing is asserted of each: that it did not
# move a byte on the wire.
#
#  * `Agent.chat` is a `Run` with no tools now; the messages it sends must be
#    byte-identical to what it sent before (a served endpoint's prefix cache
#    is keyed on them), and the "before" is pinned as a fixture literal
#    captured off master, so this test fails if the assembly drifts even
#    where the code that produced it is gone.
#  * `RoleContext.ask` composes a `core.runtime.run.Model`; what a role sends
#    is what the window produced, exactly as when `ask` called the chat
#    function directly.
#  * `set_scope_constraints` is `ToolPlane.narrow` now — the same denials for
#    the same scopes, a new plane, the original untouched.
#
# And two deletions are pinned: `Agent.run_task` is gone, and the kernel's
# two budget subclasses folded into the shared `BudgetExhausted`.

import pytest
from types import SimpleNamespace

from core.agent import Agent
from core.contracts.schemas import PersonalityConfig, PolicyPack
from core.kernel.roles import (
    RoleContext, _truncate_messages, role_compaction_note,
)
from core.kernel.workflows import get_coding_workflow
from core.kernel.budgets import (
    BudgetConfig, BudgetExhausted, check_total_iterations, check_phase_time,
)
from core.kernel.state import Phase, SessionState
from core.runtime.run import ToolPlane
from core.tools.capability import CapabilityEngine


STUB_CONFIG = PersonalityConfig(
    name="stub",
    system_message="You are StubAgent, a test agent.",
    examples=[("How?", "Like this.")],
    text_color="green",
    env_path="/tmp/stub_env",
    rag_enhancement_style="Answer in stub style.",
)


# The exact messages `Agent.chat` put on the wire on master (0.13.x), captured
# before lane E touched the code. The whole point: a refactor's assertions
# pass against the old code too, so the guard has to be the recorded bytes.
CHAT_MESSAGES_MASTER = [
    {
        "role": "system",
        "content": (
            "You are StubAgent, a test agent.\n\n"
            "You have the following tools (do not call them directly):\n"
            "- run_shell_command: A mock tool\n"
            "- run_python_code: A mock tool\n\n"
            "Tool results appear in history as assistant messages; treat "
            "them as your own work.\n\n"
            "Here are examples:\n\n"
            "User: How?\nAssistant: Like this."
        ),
    },
    {"role": "user", "content": "hello"},
]

CHAT_MESSAGES_MASTER_INVOKED = [
    {
        "role": "system",
        "content": (
            CHAT_MESSAGES_MASTER[0]["content"]
            + "\n\n[Tool Context] run_shell_command results are available "
            "above.\n"
        ),
    },
    {"role": "user", "content": "hello"},
]


def _agent(fake_client, memory, fake_tools):
    return Agent(config=STUB_CONFIG, model="test-model", provider="openai",
                 debug=False, client=fake_client, memory=memory,
                 tools=fake_tools)


class TestChatThroughRunSendsTheSameBytes:
    def test_a_plain_chat_turn_is_byte_identical_to_master(
        self, fake_client, memory, fake_tools,
    ):
        agent = _agent(fake_client, memory, fake_tools)
        agent.chat("hello", stream=False)
        assert fake_client.last_request["messages"] == CHAT_MESSAGES_MASTER

    def test_an_invoked_tools_turn_keeps_its_trailing_newline(
        self, fake_client, memory, fake_tools,
    ):
        """The `[Tool Context]` annotation ends with a newline. Routing chat
        through `Run.seed`/`stacked` would strip it — the reason chat keeps
        its own `build_chat_context` assembly. This pins the byte."""
        agent = _agent(fake_client, memory, fake_tools)
        agent.chat("hello", stream=False, invoked_tools=["run_shell_command"])
        sent = fake_client.last_request["messages"]
        assert sent == CHAT_MESSAGES_MASTER_INVOKED
        assert sent[0]["content"].endswith("available above.\n")

    def test_the_streaming_surface_is_unchanged(
        self, fake_client, memory, fake_tools,
    ):
        """`stream=True` still returns the backend's chunk iterator, whose
        chunks carry `.choices[0].delta.content` — the shape `core/cli.py`
        iterates. The model call is still the direct one; lane C moves it
        into `Run.arun`."""
        agent = _agent(fake_client, memory, fake_tools)
        chunks = list(agent.chat("hello", stream=True))
        assert chunks
        text = "".join(c.choices[0].delta.content for c in chunks)
        assert text.strip() == "Hello from fake client"
        assert fake_client.last_request["stream"] is True


class TestRolesAskThroughModel:
    def _ctx_with_trace(self, chat, *, per_role):
        ctx = RoleContext(chat=chat, workflow=get_coding_workflow(),
                          budget=BudgetConfig(max_context_tokens_per_role=per_role))
        for i in range(6):
            ctx.remember(f"[STEP{i}] " + "z" * 400,
                         speaker="assistant" if i % 2 == 0 else "user")
        return ctx

    def _messages(self, ctx):
        return [
            {"role": "system", "content": "role prompt"},
            {"role": "user", "content": "Task: do it"},
            *ctx.transcript(),
        ]

    def test_a_windowed_role_turn_sends_what_the_window_produced(self):
        """The composition routes `ask` through `Model.ask` (the role's chat)
        and `Model.window` (the effective `RoleWindow`). What is sent must be
        exactly the window's own output — truncate, then fit, then that — the
        way it was when `ask` called `chat` directly. A tiny per-role budget
        forces the compaction so the equality has teeth."""
        sent = []

        def chat(messages):
            sent.append(messages)
            return "ok"

        ctx = self._ctx_with_trace(chat, per_role=10)
        messages = self._messages(ctx)
        window = ctx.prompt_window
        limit = window.limit_tokens
        expected_prompt = (_truncate_messages(messages, limit * 4)
                           if limit > 0 else list(messages))
        expected_fitted, _ = window.fit(
            expected_prompt, pinned=2, note=role_compaction_note)

        reply = ctx.ask(messages, pinned=2)

        assert reply == "ok"
        assert sent[0] == expected_fitted
        # The composed Model is the mission loop's own object, and its window
        # is the role's effective window by identity.
        assert ctx.model.window is ctx.prompt_window

    def test_a_role_turn_that_fits_is_sent_unchanged(self):
        sent = []

        def chat(messages):
            sent.append(messages)
            return "ok"

        ctx = self._ctx_with_trace(chat, per_role=100_000)
        messages = self._messages(ctx)
        ctx.ask(messages, pinned=2)
        assert sent[0] == messages

    def test_the_role_folds_its_usage_through_the_models_ledger(self):
        """The seam, not a second accountant: with no usage source the fold
        is a no-op, and the ledger a role carries is the Model's one."""
        ctx = self._ctx_with_trace(lambda m: "ok", per_role=100_000)
        ctx.ask(self._messages(ctx), pinned=2)
        assert ctx.model.ledger is not None
        assert ctx.model.spend(ctx.model.ledger) == {}


class TestToolPlaneNarrow:
    def _bus_with_engine(self):
        # A wildcard policy so ONLY the scope constraint decides a denial —
        # which is what `set_scope_constraints` narrows.
        engine = CapabilityEngine(PolicyPack(allowed_scopes=["*"]))
        bus = SimpleNamespace(capability_engine=engine)
        return bus, engine

    def test_narrow_constrains_the_engine_exactly_as_set_scope_constraints(self):
        bus, engine = self._bus_with_engine()
        plane = ToolPlane(bus=bus, offered=("fs_read", "shell"))

        plane.narrow(["fs.read"])

        # Same state the old call produced, checked as the same denials:
        assert engine.check("shell", ["shell.exec"]).allowed is False
        assert engine.check("fs_read", ["fs.read"]).allowed is True

        # And literally the same, compared against a second engine narrowed
        # the old way.
        bus2, engine2 = self._bus_with_engine()
        engine2.set_scope_constraints(["fs.read"])
        for tool, scopes in [("shell", ["shell.exec"]),
                             ("fs_read", ["fs.read"]),
                             ("x", ["net.http"])]:
            assert (engine.check(tool, scopes).allowed
                    == engine2.check(tool, scopes).allowed)

    def test_narrow_returns_a_new_plane_and_leaves_the_original(self):
        bus, engine = self._bus_with_engine()
        plane = ToolPlane(bus=bus, offered=("fs_read", "shell"))
        narrowed = plane.narrow(["fs.read"])
        assert narrowed is not plane
        assert list(plane.offered) == ["fs_read", "shell"]
        assert narrowed.bus is plane.bus

    def test_narrow_is_a_no_op_on_a_bus_with_no_engine(self):
        """A bus that owes no capability engine — a fake with only dispatch
        and describe_tool — is narrowed without a failure, the honest reading
        of 'restrict what is already unrestricted'."""
        plane = ToolPlane(bus=SimpleNamespace(dispatch=None, describe_tool=None))
        assert plane.narrow(["fs.read"]) is not plane


class TestTheBudgetSubclassesFoldedIntoBounds:
    def test_check_total_iterations_raises_the_shared_steps_verdict(self):
        state = SessionState(task_description="t")
        state.total_iterations = 30
        with pytest.raises(BudgetExhausted) as exc:
            check_total_iterations(state, BudgetConfig(max_total_iterations=30))
        assert exc.value.which == "steps"

    def test_check_phase_time_raises_the_shared_seconds_verdict(self):
        import time
        state = SessionState(task_description="t")
        state.enter_phase(Phase.CONTRACT)
        state.phase_start_time = time.monotonic() - 400.0
        with pytest.raises(BudgetExhausted) as exc:
            check_phase_time(state, BudgetConfig(max_time_per_phase_seconds=300.0))
        assert exc.value.which == "seconds"

    def test_the_kernel_except_budgetexhausted_still_catches_them(self):
        state = SessionState(task_description="t")
        state.total_iterations = 5
        caught = False
        try:
            check_total_iterations(state, BudgetConfig(max_total_iterations=5))
        except BudgetExhausted:
            caught = True
        assert caught

    def test_the_two_kernel_subclasses_are_gone(self):
        import core.kernel.budgets as kb
        assert not hasattr(kb, "TotalIterationsExhausted")
        assert not hasattr(kb, "PhaseTimeoutExhausted")


class TestRunTaskIsGone:
    def test_agent_has_no_run_task(self):
        assert not hasattr(Agent, "run_task")

    def test_no_source_in_core_or_main_calls_run_task(self):
        """Importer scan: the method is deleted and nothing reaches for it.
        `_make_task_dispatcher` (kept for `run_campaign`) is the surviving
        seam and may still be named."""
        import pathlib
        root = pathlib.Path(__file__).resolve().parent.parent
        offenders = []
        for path in [*(root / "core").rglob("*.py"), root / "main.py"]:
            if not path.exists():
                continue
            for lineno, line in enumerate(path.read_text().splitlines(), 1):
                if ".run_task(" in line or "def run_task(" in line:
                    offenders.append(f"{path.name}:{lineno}")
        assert offenders == [], offenders
