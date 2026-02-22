# tests/test_unified_client.py

import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock

from core.unified_client import UnifiedClient
from core.runtime.backends.openai_backend import OpenAIBackend


class TestUnifiedClientOpenAI:
    """Tests for UnifiedClient with injected OpenAI client."""

    def test_injected_client_skips_key_check(self):
        """When openai_client is provided, no API key is needed."""
        mock_openai = MagicMock()
        client = UnifiedClient(provider_override="openai", openai_client=mock_openai)
        assert client.provider == "openai"
        assert isinstance(client._backend, OpenAIBackend)

    def test_chat_non_streaming(self):
        mock_openai = MagicMock()
        mock_openai.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="Hello!"))]
        )
        client = UnifiedClient(provider_override="openai", openai_client=mock_openai)
        result = client.chat(model="gpt-4o-mini", messages=[{"role": "user", "content": "hi"}])
        assert result == "Hello!"
        mock_openai.chat.completions.create.assert_called_once()

    def test_chat_streaming(self):
        mock_openai = MagicMock()
        chunks = [
            SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="Hi"))]),
            SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=" there"))]),
        ]
        mock_openai.chat.completions.create.return_value = iter(chunks)
        client = UnifiedClient(provider_override="openai", openai_client=mock_openai)
        result = client.chat(model="gpt-4o-mini", messages=[{"role": "user", "content": "hi"}], stream=True)
        collected = list(result)
        assert len(collected) == 2

    def test_missing_key_raises_without_injection(self):
        with pytest.raises(RuntimeError, match="Missing OPENAI_API_KEY"):
            UnifiedClient(provider_override="openai")


class TestUnifiedClientMistral:
    """Tests for Mistral provider (no injection needed — just key check)."""

    def test_missing_mistral_key_raises(self):
        with pytest.raises(RuntimeError, match="Missing MISTRAL_API_KEY"):
            UnifiedClient(provider_override="mistral")

    def test_unsupported_provider_raises(self):
        with pytest.raises(ValueError, match="Unsupported provider"):
            UnifiedClient(provider_override="unsupported")
