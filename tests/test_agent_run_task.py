# tests/test_agent_run_task.py — Tests for Agent.run_task() (replaces test_elf_run_task.py)

from types import SimpleNamespace

import pytest
from pathlib import Path

from core.agent import Agent
from core.contracts.schemas import PersonalityConfig
from core.kernel import Phase, BudgetConfig
from tests.conftest import FakeUnifiedClient


STUB_CONFIG = PersonalityConfig(
    name="stub",
    system_message="You are StubAgent.",
    examples=[("Q?", "A.")],
    env_path="/tmp/stub_env",
)


class TestAgentRunTask:
    def test_run_task_returns_session_state(self, fake_client, memory, fake_tools):
        agent = Agent(config=STUB_CONFIG, debug=False,
                      client=fake_client, memory=memory, tools=fake_tools)
        state = agent.run_task("add pagination")
        assert state.task_description == "add pagination"

    def test_a_client_that_only_chats_halts_instead_of_claiming_success(
        self, fake_client, memory, fake_tools,
    ):
        """This asserted COMPLETED, and it was the stub talking.

        `fake_client` answers every prompt with "Hello from fake client".
        Under `StubDispatcher` that walked INTAKE -> ... -> COMPLETED and
        reported a finished task, because the dispatcher returned
        success without looking at the reply. INTAKE now has to produce a
        TaskContract, prose is not one, and the session halts naming the
        phase. A halt here is the correct answer and the old pass was not.
        """
        agent = Agent(config=STUB_CONFIG, debug=False,
                      client=fake_client, memory=memory, tools=fake_tools)
        state = agent.run_task("add pagination")
        assert state.current_phase == Phase.HALTED
        assert "INTAKE" in state.halt_reason

    def test_run_task_with_custom_budget(self, fake_client, memory, fake_tools):
        """The budget still reaches the orchestrator; see the halt reason."""
        agent = Agent(config=STUB_CONFIG, debug=False,
                      client=fake_client, memory=memory, tools=fake_tools)
        budget = BudgetConfig(max_total_iterations=50, max_phase_retries=1)
        state = agent.run_task("add pagination", budget=budget)
        assert state.current_phase == Phase.HALTED
        assert "1/1" in state.halt_reason  # one retry, as configured

    def test_the_dispatcher_is_no_longer_a_stub(self, fake_client, memory,
                                                fake_tools):
        from core.kernel.roles import LLMRoleDispatcher

        agent = Agent(config=STUB_CONFIG, debug=False,
                      client=fake_client, memory=memory, tools=fake_tools)
        assert isinstance(agent._make_task_dispatcher(), LLMRoleDispatcher)

    def test_the_dispatcher_and_orchestrator_share_one_workflow(
        self, fake_client, memory, fake_tools,
    ):
        """They used to default independently, which a role-mapped
        dispatcher cannot survive."""
        from core.kernel.workflows import get_generic_workflow

        agent = Agent(config=STUB_CONFIG, debug=False,
                      client=fake_client, memory=memory, tools=fake_tools)
        workflow = get_generic_workflow()
        state = agent.run_task("do a thing", workflow=workflow,
                               budget=BudgetConfig(max_phase_retries=1))
        # The generic workflow has phases the coding roles do not serve, so
        # this halts — but on "no role is registered", not on a mismatch
        # nobody could explain.
        assert state.current_phase == Phase.HALTED

    def test_the_kernel_path_gets_the_window_the_mission_path_gets(
        self, memory, fake_tools,
    ):
        """B2's wiring half: a library caller is bounded without asking.

        The dispatcher's window is built from the agent's own provider,
        model and client — the three inputs `core/cli.py` builds the
        mission's window from — so the coding kernel and the mission loop
        cannot hold two opinions about how big the endpoint's window is.
        And it is read lazily: constructing the dispatcher must not be the
        thing that waits on a `GET /models`.
        """
        class CountingClient(FakeUnifiedClient):
            def __init__(self):
                super().__init__()
                self.reads = 0

            @property
            def capabilities(self):
                self.reads += 1
                return SimpleNamespace(max_context_tokens=8_192,
                                       max_output_tokens=1_024)

        client = CountingClient()
        agent = Agent(config=STUB_CONFIG, debug=False,
                      client=client, memory=memory, tools=fake_tools)

        window = agent._make_task_dispatcher().context.prompt_window
        assert client.reads == 0
        assert window.limit_tokens == 8_192 - 1_024
        assert window.profile.source == "backend"
        assert client.reads == 1

    def test_a_budget_cannot_raise_the_limit_the_endpoint_will_refuse(
        self, fake_client, memory, fake_tools,
    ):
        """The effective limit is the smaller of the two, from this side
        of the wiring as well."""
        agent = Agent(config=STUB_CONFIG, debug=False,
                      client=fake_client, memory=memory, tools=fake_tools)
        window = agent._make_task_dispatcher(
            budget=BudgetConfig(max_context_tokens_per_role=10_000_000),
        ).context.prompt_window

        assert window.profile.source != "per_role_budget"
        assert window.limit_tokens == window.profile.max_input_tokens
        assert 0 < window.limit_tokens < 10_000_000

    def test_existing_chat_unaffected(self, fake_client, memory, fake_tools):
        """Adding run_task() does not break existing chat()."""
        agent = Agent(config=STUB_CONFIG, debug=False,
                      client=fake_client, memory=memory, tools=fake_tools)
        result = agent.chat("hello", stream=False)
        assert result == "Hello from fake client"
