# tests/test_elf.py — Tests for the Elf base class via a concrete StubElf subclass

import pytest
from pathlib import Path
from unittest.mock import MagicMock

from core.elf import Elf
from tests.conftest import FakeUnifiedClient


class StubElf(Elf):
    """Minimal concrete Elf subclass for testing."""

    @property
    def system_message(self):
        return "You are StubElf, a test elf."

    @property
    def personality(self):
        return "stub"

    @property
    def examples(self):
        return [("How?", "Like this.")]

    @property
    def env(self):
        return Path("/tmp/stub_env")

    @property
    def text_color(self):
        return "green"

    @property
    def rag_enhancement_style(self):
        return "Answer in stub style."


class TestElfConstruction:
    def test_di_injection(self, fake_client, memory, fake_tools):
        """Elf constructed with injected dependencies uses them directly."""
        elf = StubElf(
            model="test-model", provider="openai", debug=False,
            client=fake_client, memory=memory, tools=fake_tools,
        )
        assert elf.client is fake_client
        assert elf.memory is memory
        assert elf.tools is fake_tools
        assert elf.model == "test-model"
        assert elf.provider == "openai"

    def test_default_model_resolution(self, fake_client, memory, fake_tools):
        """When model=None, defaults are used based on provider."""
        elf = StubElf(
            provider="openai", debug=False,
            client=fake_client, memory=memory, tools=fake_tools,
        )
        assert elf.model == "gpt-4o-mini"  # DEFAULT_MODELS["openai"]

    def test_no_fallback_warning_with_injected_client(self, fake_client, memory, fake_tools, capsys):
        """Injected client should suppress the key-missing fallback logic."""
        elf = StubElf(
            provider="openai", debug=False,
            client=fake_client, memory=memory, tools=fake_tools,
        )
        # No fallback should happen — provider stays as requested
        assert elf.provider == "openai"


class TestElfHistory:
    def test_initial_history_system_message(self, fake_client, memory, fake_tools):
        elf = StubElf(
            debug=False, client=fake_client, memory=memory, tools=fake_tools,
        )
        assert len(elf.history) >= 1
        assert elf.history[0]["role"] == "system"
        assert "StubElf" in elf.history[0]["content"]

    def test_save_and_load_history(self, fake_client, memory, fake_tools):
        elf = StubElf(
            debug=False, client=fake_client, memory=memory, tools=fake_tools,
        )
        elf.history.append({"role": "user", "content": "test message"})
        elf.history.append({"role": "assistant", "content": "test reply"})
        elf.save_history()

        # Create a new elf with same memory — should load history
        elf2 = StubElf(
            debug=False, client=fake_client, memory=memory, tools=fake_tools,
        )
        assert len(elf2.history) >= 2  # at least system + saved entries

    def test_reset_history(self, fake_client, memory, fake_tools):
        elf = StubElf(
            debug=False, client=fake_client, memory=memory, tools=fake_tools,
        )
        elf.history.append({"role": "user", "content": "data"})
        elf.reset_history()
        assert len(elf.history) == 1
        assert elf.history[0]["role"] == "system"


class TestElfChat:
    def test_chat_non_streaming(self, fake_client, memory, fake_tools):
        elf = StubElf(
            debug=False, client=fake_client, memory=memory, tools=fake_tools,
        )
        result = elf.chat("hello", stream=False)
        assert result == "Hello from fake client"
        # User message should be added to history
        assert any(h["content"] == "hello" for h in elf.history)

    def test_chat_streaming(self, fake_client, memory, fake_tools):
        elf = StubElf(
            debug=False, client=fake_client, memory=memory, tools=fake_tools,
        )
        result = elf.chat("hello", stream=True)
        chunks = list(result)
        assert len(chunks) > 0

    def test_chat_with_invoked_tools(self, fake_client, memory, fake_tools):
        elf = StubElf(
            debug=False, client=fake_client, memory=memory, tools=fake_tools,
        )
        result = elf.chat("hello", invoked_tools=["run_shell_command"])
        assert result == "Hello from fake client"


class TestElfMemory:
    def test_enrich_with_memory_no_results(self, fake_client, memory, fake_tools):
        elf = StubElf(
            debug=False, client=fake_client, memory=memory, tools=fake_tools,
        )
        initial_len = len(elf.history)
        elf.enrich_with_memory("test query")
        # No long-term memories → no new history entry
        assert len(elf.history) == initial_len

    def test_enrich_with_memory_with_results(self, fake_client, memory, fake_tools):
        memory.add_long("user", "The sky is blue")
        elf = StubElf(
            debug=False, client=fake_client, memory=memory, tools=fake_tools,
        )
        initial_len = len(elf.history)
        elf.enrich_with_memory("what color is the sky?")
        assert len(elf.history) > initial_len
        assert "long-term memory" in elf.history[-1]["content"]

    def test_purge_memory(self, fake_client, memory, fake_tools):
        memory.add_long("user", "remember this")
        elf = StubElf(
            debug=False, client=fake_client, memory=memory, tools=fake_tools,
        )
        elf.purge_memory()
        assert memory.long_index is None


class TestElfCodeGeneration:
    def test_generate_shell_command(self, memory, fake_tools):
        client = FakeUnifiedClient(canned="```bash\nls -la\n```")
        elf = StubElf(
            debug=False, client=client, memory=memory, tools=fake_tools,
        )
        cmd = elf.generate_shell_command("list files")
        assert "ls" in cmd

    def test_generate_python_code(self, memory, fake_tools):
        client = FakeUnifiedClient(canned="```python\nprint('hello')\n```")
        elf = StubElf(
            debug=False, client=client, memory=memory, tools=fake_tools,
        )
        code = elf.generate_python_code("print hello")
        assert "print" in code
