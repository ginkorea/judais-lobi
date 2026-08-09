# tests/test_backends.py — Tests for backend implementations

import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock

from core.runtime.backends.base import BackendCapabilities
from core.runtime.backends.openai_backend import OpenAIBackend
from core.runtime.backends.mistral_backend import MistralBackend
from core.runtime.backends.local_backend import LocalBackend


class TestOpenAIBackend:
    def test_injected_client(self):
        mock = MagicMock()
        backend = OpenAIBackend(openai_client=mock)
        assert backend.client is mock

    def test_non_streaming(self):
        mock = MagicMock()
        mock.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="hi"))]
        )
        backend = OpenAIBackend(openai_client=mock)
        result = backend.chat("gpt-4o-mini", [{"role": "user", "content": "hello"}])
        assert result == "hi"
        mock.chat.completions.create.assert_called_once_with(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "hello"}],
        )

    def test_streaming(self):
        mock = MagicMock()
        chunks = [
            SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="a"))]),
            SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="b"))]),
        ]
        mock.chat.completions.create.return_value = iter(chunks)
        backend = OpenAIBackend(openai_client=mock)
        result = list(backend.chat("gpt-4o-mini", [{"role": "user", "content": "hi"}], stream=True))
        assert len(result) == 2
        mock.chat.completions.create.assert_called_once_with(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "hi"}],
            stream=True,
        )

    def test_missing_key_raises(self):
        with pytest.raises(RuntimeError, match="Missing OPENAI_API_KEY"):
            OpenAIBackend()

    def test_capabilities(self):
        mock = MagicMock()
        backend = OpenAIBackend(openai_client=mock)
        caps = backend.capabilities
        assert caps.supports_streaming is True
        assert caps.supports_json_mode is True
        assert caps.supports_tool_calls is True


class TestMistralBackend:
    def test_missing_key_raises(self):
        with pytest.raises(RuntimeError, match="Missing MISTRAL_API_KEY"):
            MistralBackend()

    def test_capabilities(self, monkeypatch):
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
        backend = MistralBackend()
        caps = backend.capabilities
        assert caps.supports_streaming is True
        assert caps.supports_json_mode is True
        assert caps.supports_tool_calls is False


class TestLocalBackend:
    """The Phase-8 stub is gone; see tests/test_local_backend.py.

    Those four tests asserted the *absence* of a local backend — a
    ``NotImplementedError``, three ``False`` capabilities, and a default
    endpoint with no ``/v1``.  They are replaced rather than deleted so
    the change is visible here, next to the other two backends, and what
    stays is only what still belongs in this file: that the class is a
    ``Backend`` and that constructing one contacts nothing.
    """

    def test_is_a_backend(self):
        from core.runtime.backends.base import Backend

        assert isinstance(LocalBackend(endpoint="http://127.0.0.1:1/v1"), Backend)

    def test_chat_no_longer_raises_not_implemented(self):
        backend = LocalBackend(endpoint="http://127.0.0.1:1/v1")
        with pytest.raises(Exception) as exc:
            backend.chat("local-model", [{"role": "user", "content": "hi"}])
        assert not isinstance(exc.value, NotImplementedError)

    def test_construction_contacts_nothing(self):
        """No probe at construction: a CLI must start with the server cold."""
        LocalBackend(endpoint="http://127.0.0.1:1/v1")
