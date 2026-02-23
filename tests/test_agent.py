# tests/test_agent.py — Tests for the Agent class (replaces test_elf.py)

import pytest
from pathlib import Path
from unittest.mock import MagicMock

from core.agent import Agent
from core.contracts.schemas import PersonalityConfig
from tests.conftest import FakeUnifiedClient


STUB_CONFIG = PersonalityConfig(
    name="stub",
    system_message="You are StubAgent, a test agent.",
    examples=[("How?", "Like this.")],
    text_color="green",
    env_path="/tmp/stub_env",
    rag_enhancement_style="Answer in stub style.",
)


class TestAgentConstruction:
    def test_di_injection(self, fake_client, memory, fake_tools):
        agent = Agent(
            config=STUB_CONFIG,
            model="test-model", provider="openai", debug=False,
            client=fake_client, memory=memory, tools=fake_tools,
        )
        assert agent.client is fake_client
        assert agent.memory is memory
        assert agent.tools is fake_tools
        assert agent.model == "test-model"
        assert agent.provider == "openai"

    def test_default_model_resolution(self, fake_client, memory, fake_tools):
        agent = Agent(
            config=STUB_CONFIG,
            provider="openai", debug=False,
            client=fake_client, memory=memory, tools=fake_tools,
        )
        # No default_model on STUB_CONFIG, so falls through to DEFAULT_MODELS["openai"]
        assert agent.model == "gpt-4o-mini"

    def test_config_default_model(self, fake_client, memory, fake_tools):
        config = PersonalityConfig(
            name="test", system_message="msg", examples=[("Q", "A")],
            default_model="custom-model", default_provider="openai",
        )
        agent = Agent(
            config=config, debug=False,
            client=fake_client, memory=memory, tools=fake_tools,
        )
        assert agent.model == "custom-model"

    def test_no_fallback_warning_with_injected_client(self, fake_client, memory, fake_tools):
        agent = Agent(
            config=STUB_CONFIG,
            provider="openai", debug=False,
            client=fake_client, memory=memory, tools=fake_tools,
        )
        assert agent.provider == "openai"

    def test_personality_property(self, fake_client, memory, fake_tools):
        agent = Agent(config=STUB_CONFIG, debug=False,
                      client=fake_client, memory=memory, tools=fake_tools)
        assert agent.personality == "stub"

    def test_system_message_property(self, fake_client, memory, fake_tools):
        agent = Agent(config=STUB_CONFIG, debug=False,
                      client=fake_client, memory=memory, tools=fake_tools)
        assert "StubAgent" in agent.system_message

    def test_text_color_property(self, fake_client, memory, fake_tools):
        agent = Agent(config=STUB_CONFIG, debug=False,
                      client=fake_client, memory=memory, tools=fake_tools)
        assert agent.text_color == "green"

    def test_env_property(self, fake_client, memory, fake_tools):
        agent = Agent(config=STUB_CONFIG, debug=False,
                      client=fake_client, memory=memory, tools=fake_tools)
        assert agent.env == Path("/tmp/stub_env")

    def test_examples_property(self, fake_client, memory, fake_tools):
        agent = Agent(config=STUB_CONFIG, debug=False,
                      client=fake_client, memory=memory, tools=fake_tools)
        assert agent.examples == [("How?", "Like this.")]

    def test_rag_enhancement_style(self, fake_client, memory, fake_tools):
        agent = Agent(config=STUB_CONFIG, debug=False,
                      client=fake_client, memory=memory, tools=fake_tools)
        assert agent.rag_enhancement_style == "Answer in stub style."


class TestAgentHistory:
    def test_initial_history_system_message(self, fake_client, memory, fake_tools):
        agent = Agent(config=STUB_CONFIG, debug=False,
                      client=fake_client, memory=memory, tools=fake_tools)
        assert len(agent.history) >= 1
        assert agent.history[0]["role"] == "system"
        assert "StubAgent" in agent.history[0]["content"]

    def test_save_and_load_history(self, fake_client, memory, fake_tools):
        agent = Agent(config=STUB_CONFIG, debug=False,
                      client=fake_client, memory=memory, tools=fake_tools)
        agent.history.append({"role": "user", "content": "test message"})
        agent.history.append({"role": "assistant", "content": "test reply"})
        agent.save_history()

        agent2 = Agent(config=STUB_CONFIG, debug=False,
                       client=fake_client, memory=memory, tools=fake_tools)
        assert len(agent2.history) >= 2

    def test_reset_history(self, fake_client, memory, fake_tools):
        agent = Agent(config=STUB_CONFIG, debug=False,
                      client=fake_client, memory=memory, tools=fake_tools)
        agent.history.append({"role": "user", "content": "data"})
        agent.reset_history()
        assert len(agent.history) == 1
        assert agent.history[0]["role"] == "system"


class TestAgentChat:
    def test_chat_non_streaming(self, fake_client, memory, fake_tools):
        agent = Agent(config=STUB_CONFIG, debug=False,
                      client=fake_client, memory=memory, tools=fake_tools)
        result = agent.chat("hello", stream=False)
        assert result == "Hello from fake client"
        assert any(h["content"] == "hello" for h in agent.history)

    def test_chat_streaming(self, fake_client, memory, fake_tools):
        agent = Agent(config=STUB_CONFIG, debug=False,
                      client=fake_client, memory=memory, tools=fake_tools)
        result = agent.chat("hello", stream=True)
        chunks = list(result)
        assert len(chunks) > 0

    def test_chat_with_invoked_tools(self, fake_client, memory, fake_tools):
        agent = Agent(config=STUB_CONFIG, debug=False,
                      client=fake_client, memory=memory, tools=fake_tools)
        result = agent.chat("hello", invoked_tools=["run_shell_command"])
        assert result == "Hello from fake client"


class TestAgentMemory:
    def test_enrich_with_memory_no_results(self, fake_client, memory, fake_tools):
        agent = Agent(config=STUB_CONFIG, debug=False,
                      client=fake_client, memory=memory, tools=fake_tools)
        initial_len = len(agent.history)
        agent.enrich_with_memory("test query")
        assert len(agent.history) == initial_len

    def test_enrich_with_memory_with_results(self, fake_client, memory, fake_tools):
        memory.add_long("user", "The sky is blue")
        agent = Agent(config=STUB_CONFIG, debug=False,
                      client=fake_client, memory=memory, tools=fake_tools)
        initial_len = len(agent.history)
        agent.enrich_with_memory("what color is the sky?")
        assert len(agent.history) > initial_len
        assert "long-term memory" in agent.history[-1]["content"]

    def test_purge_memory(self, fake_client, memory, fake_tools):
        memory.add_long("user", "remember this")
        agent = Agent(config=STUB_CONFIG, debug=False,
                      client=fake_client, memory=memory, tools=fake_tools)
        agent.purge_memory()
        assert memory.long_index is None


class TestAgentCodeGeneration:
    def test_generate_shell_command(self, memory, fake_tools):
        client = FakeUnifiedClient(canned="```bash\nls -la\n```")
        agent = Agent(config=STUB_CONFIG, debug=False,
                      client=client, memory=memory, tools=fake_tools)
        cmd = agent.generate_shell_command("list files")
        assert "ls" in cmd

    def test_generate_python_code(self, memory, fake_tools):
        client = FakeUnifiedClient(canned="```python\nprint('hello')\n```")
        agent = Agent(config=STUB_CONFIG, debug=False,
                      client=client, memory=memory, tools=fake_tools)
        code = agent.generate_python_code("print hello")
        assert "print" in code


class TestAgentCLIMethods:
    def test_recall_adventures_empty(self, fake_client, memory, fake_tools):
        agent = Agent(config=STUB_CONFIG, debug=False,
                      client=fake_client, memory=memory, tools=fake_tools)
        rows = agent.recall_adventures(n=10)
        assert rows == []

    def test_recall_adventures_with_data(self, fake_client, memory, fake_tools):
        memory.add_adventure("test prompt", "echo hi", "hi", "shell", True)
        agent = Agent(config=STUB_CONFIG, debug=False,
                      client=fake_client, memory=memory, tools=fake_tools)
        rows = agent.recall_adventures(n=10)
        assert len(rows) == 1
        assert rows[0]["prompt"] == "test prompt"

    def test_recall_adventures_mode_filter(self, fake_client, memory, fake_tools):
        memory.add_adventure("shell prompt", "echo", "ok", "shell", True)
        memory.add_adventure("python prompt", "print(1)", "1", "python", True)
        agent = Agent(config=STUB_CONFIG, debug=False,
                      client=fake_client, memory=memory, tools=fake_tools)
        rows = agent.recall_adventures(n=10, mode="shell")
        assert len(rows) == 1
        assert rows[0]["mode"] == "shell"

    def test_format_recall(self, fake_client, memory, fake_tools):
        agent = Agent(config=STUB_CONFIG, debug=False,
                      client=fake_client, memory=memory, tools=fake_tools)
        rows = [
            {"prompt": "list files", "mode": "shell", "success": True},
            {"prompt": "fail task", "mode": "python", "success": False},
        ]
        output = agent.format_recall(rows)
        assert "✅" in output
        assert "❌" in output
        assert "shell" in output

    def test_format_recall_empty(self, fake_client, memory, fake_tools):
        agent = Agent(config=STUB_CONFIG, debug=False,
                      client=fake_client, memory=memory, tools=fake_tools)
        assert agent.format_recall([]) == ""
