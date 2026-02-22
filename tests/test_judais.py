# tests/test_judais.py — Tests for JudAIs personality

import pytest
from tests.conftest import FakeUnifiedClient


class TestJudAIs:
    def test_personality(self, fake_client, memory, fake_tools):
        from judais.judais import JudAIs
        j = JudAIs(debug=False, client=fake_client, memory=memory, tools=fake_tools)
        assert j.personality == "judAIs"

    def test_default_model(self, fake_client, memory, fake_tools):
        from judais.judais import JudAIs
        j = JudAIs(debug=False, client=fake_client, memory=memory, tools=fake_tools)
        assert j.model == "codestral-latest"

    def test_default_provider(self, fake_client, memory, fake_tools):
        from judais.judais import JudAIs
        j = JudAIs(debug=False, client=fake_client, memory=memory, tools=fake_tools)
        assert j.provider == "mistral"

    def test_text_color(self, fake_client, memory, fake_tools):
        from judais.judais import JudAIs
        j = JudAIs(debug=False, client=fake_client, memory=memory, tools=fake_tools)
        assert j.text_color == "red"

    def test_system_message_contains_judais(self, fake_client, memory, fake_tools):
        from judais.judais import JudAIs
        j = JudAIs(debug=False, client=fake_client, memory=memory, tools=fake_tools)
        assert "JudAIs" in j.system_message

    def test_di_forwarding(self, fake_client, memory, fake_tools):
        """Verify **kwargs forwards client/memory/tools to Elf.__init__."""
        from judais.judais import JudAIs
        j = JudAIs(debug=False, client=fake_client, memory=memory, tools=fake_tools)
        assert j.client is fake_client
        assert j.memory is memory
        assert j.tools is fake_tools

    def test_examples_not_empty(self, fake_client, memory, fake_tools):
        from judais.judais import JudAIs
        j = JudAIs(debug=False, client=fake_client, memory=memory, tools=fake_tools)
        assert len(j.examples) > 0

    def test_chat_works(self, fake_client, memory, fake_tools):
        from judais.judais import JudAIs
        j = JudAIs(debug=False, client=fake_client, memory=memory, tools=fake_tools)
        result = j.chat("hello", stream=False)
        assert result == "Hello from fake client"

    def test_provider_override(self, fake_client, memory, fake_tools):
        """JudAIs can accept provider override."""
        from judais.judais import JudAIs
        j = JudAIs(provider="openai", debug=False, client=fake_client, memory=memory, tools=fake_tools)
        assert j.provider == "openai"
