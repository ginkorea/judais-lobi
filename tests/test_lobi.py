# tests/test_lobi.py — Tests for Lobi personality

import pytest
from tests.conftest import FakeUnifiedClient


class TestLobi:
    def test_personality(self, fake_client, memory, fake_tools):
        from lobi.lobi import Lobi
        lobi = Lobi(debug=False, client=fake_client, memory=memory, tools=fake_tools)
        assert lobi.personality == "lobi"

    def test_default_model(self, fake_client, memory, fake_tools):
        from lobi.lobi import Lobi
        lobi = Lobi(debug=False, client=fake_client, memory=memory, tools=fake_tools)
        assert lobi.model == "gpt-5-mini"

    def test_default_provider(self, fake_client, memory, fake_tools):
        from lobi.lobi import Lobi
        lobi = Lobi(debug=False, client=fake_client, memory=memory, tools=fake_tools)
        assert lobi.provider == "openai"

    def test_text_color(self, fake_client, memory, fake_tools):
        from lobi.lobi import Lobi
        lobi = Lobi(debug=False, client=fake_client, memory=memory, tools=fake_tools)
        assert lobi.text_color == "cyan"

    def test_system_message_contains_lobi(self, fake_client, memory, fake_tools):
        from lobi.lobi import Lobi
        lobi = Lobi(debug=False, client=fake_client, memory=memory, tools=fake_tools)
        assert "Lobi" in lobi.system_message

    def test_di_forwarding(self, fake_client, memory, fake_tools):
        """Verify **kwargs forwards client/memory/tools to Elf.__init__."""
        from lobi.lobi import Lobi
        lobi = Lobi(debug=False, client=fake_client, memory=memory, tools=fake_tools)
        assert lobi.client is fake_client
        assert lobi.memory is memory
        assert lobi.tools is fake_tools

    def test_examples_not_empty(self, fake_client, memory, fake_tools):
        from lobi.lobi import Lobi
        lobi = Lobi(debug=False, client=fake_client, memory=memory, tools=fake_tools)
        assert len(lobi.examples) > 0

    def test_chat_works(self, fake_client, memory, fake_tools):
        from lobi.lobi import Lobi
        lobi = Lobi(debug=False, client=fake_client, memory=memory, tools=fake_tools)
        result = lobi.chat("hello", stream=False)
        assert result == "Hello from fake client"
