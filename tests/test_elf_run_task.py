# tests/test_elf_run_task.py — Tests for Elf.run_task() thin adapter

import pytest
from pathlib import Path

from core.elf import Elf
from core.kernel import Phase, BudgetConfig
from tests.conftest import FakeUnifiedClient


class StubElf(Elf):
    """Minimal concrete Elf for testing run_task()."""

    @property
    def system_message(self):
        return "You are StubElf."

    @property
    def personality(self):
        return "stub"

    @property
    def examples(self):
        return [("Q?", "A.")]

    @property
    def env(self):
        return Path("/tmp/stub_env")

    @property
    def text_color(self):
        return "green"

    @property
    def rag_enhancement_style(self):
        return "Answer in stub style."


class TestElfRunTask:
    def test_run_task_returns_session_state(self, fake_client, memory, fake_tools):
        elf = StubElf(debug=False, client=fake_client, memory=memory, tools=fake_tools)
        state = elf.run_task("add pagination")
        assert state.task_description == "add pagination"

    def test_run_task_completes(self, fake_client, memory, fake_tools):
        elf = StubElf(debug=False, client=fake_client, memory=memory, tools=fake_tools)
        state = elf.run_task("add pagination")
        assert state.current_phase == Phase.COMPLETED

    def test_run_task_with_custom_budget(self, fake_client, memory, fake_tools):
        elf = StubElf(debug=False, client=fake_client, memory=memory, tools=fake_tools)
        budget = BudgetConfig(max_total_iterations=50)
        state = elf.run_task("add pagination", budget=budget)
        assert state.current_phase == Phase.COMPLETED

    def test_existing_chat_unaffected(self, fake_client, memory, fake_tools):
        """Adding run_task() does not break existing chat()."""
        elf = StubElf(debug=False, client=fake_client, memory=memory, tools=fake_tools)
        result = elf.chat("hello", stream=False)
        assert result == "Hello from fake client"
