# tests/test_agent_run_task.py — Tests for Agent.run_task() (replaces test_elf_run_task.py)

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

    def test_run_task_completes(self, fake_client, memory, fake_tools):
        agent = Agent(config=STUB_CONFIG, debug=False,
                      client=fake_client, memory=memory, tools=fake_tools)
        state = agent.run_task("add pagination")
        assert state.current_phase == Phase.COMPLETED

    def test_run_task_with_custom_budget(self, fake_client, memory, fake_tools):
        agent = Agent(config=STUB_CONFIG, debug=False,
                      client=fake_client, memory=memory, tools=fake_tools)
        budget = BudgetConfig(max_total_iterations=50)
        state = agent.run_task("add pagination", budget=budget)
        assert state.current_phase == Phase.COMPLETED

    def test_existing_chat_unaffected(self, fake_client, memory, fake_tools):
        """Adding run_task() does not break existing chat()."""
        agent = Agent(config=STUB_CONFIG, debug=False,
                      client=fake_client, memory=memory, tools=fake_tools)
        result = agent.chat("hello", stream=False)
        assert result == "Hello from fake client"
