# tests/test_agent_run_task.py — Tests for the Agent's coding-kernel seam
#
# `Agent.run_task` was deleted in Phase 11 (lane E): it had no caller in
# `core/` or `main.py`, and a library caller that wants the single-task path
# builds the six lines PLATFORMS.md documents ("Running the coding kernel as
# a library"). The four tests that drove `run_task` end to end went with it;
# what a mutation of Phase 11 would still have to survive — that the kernel
# path is reachable and shares the mission's window — is `_make_task_
# dispatcher`, and those tests stay.

from types import SimpleNamespace

import pytest
from pathlib import Path

from core.agent import Agent
from core.contracts.schemas import PersonalityConfig
from core.kernel import BudgetConfig
from tests.conftest import FakeUnifiedClient


STUB_CONFIG = PersonalityConfig(
    name="stub",
    system_message="You are StubAgent.",
    examples=[("Q?", "A.")],
    env_path="/tmp/stub_env",
)


class TestAgentRunTask:
    def test_run_task_is_gone(self, fake_client, memory, fake_tools):
        """The single-task entry point has no caller and is deleted; the
        campaign path and `_make_task_dispatcher` are the reachable forms."""
        agent = Agent(config=STUB_CONFIG, debug=False,
                      client=fake_client, memory=memory, tools=fake_tools)
        assert not hasattr(agent, "run_task")

    def test_the_dispatcher_is_no_longer_a_stub(self, fake_client, memory,
                                                fake_tools):
        from core.kernel.roles import LLMRoleDispatcher

        agent = Agent(config=STUB_CONFIG, debug=False,
                      client=fake_client, memory=memory, tools=fake_tools)
        assert isinstance(agent._make_task_dispatcher(), LLMRoleDispatcher)

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
