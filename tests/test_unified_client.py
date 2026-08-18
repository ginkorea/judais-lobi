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

    def test_missing_key_raises_without_injection(self, monkeypatch):
        """Constructed fine; refused by name at the first chat — a client
        exists for a replay that never chats."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        client = UnifiedClient(provider_override="openai")
        with pytest.raises(RuntimeError, match="Missing OPENAI_API_KEY"):
            client.chat("m", [{"role": "user", "content": "hi"}])


class TestUnifiedClientMistral:
    """Tests for Mistral provider (no injection needed — just key check)."""

    def test_missing_mistral_key_raises(self, monkeypatch):
        monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
        client = UnifiedClient(provider_override="mistral")
        with pytest.raises(RuntimeError, match="Missing MISTRAL_API_KEY"):
            client.chat("m", [{"role": "user", "content": "hi"}])

    def test_unsupported_provider_raises(self):
        with pytest.raises(ValueError, match="Unsupported provider"):
            UnifiedClient(provider_override="unsupported")


class TestTheUsageSideChannel:
    """`chat` returns a str or an iterator; the counts arrive beside it.

    A third return shape would be a breaking change to every caller of
    `chat` for the sake of a number most of them ignore, so the client
    grew a property instead.
    """

    def _client(self, usage):
        mock_openai = MagicMock()
        mock_openai.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="Hello!"))],
            usage=usage,
        )
        return UnifiedClient(provider_override="openai", openai_client=mock_openai)

    def test_nothing_has_been_asked_yet(self):
        client = self._client(None)
        assert client.last_usage is None

    def test_it_is_the_backends(self):
        client = self._client({"prompt_tokens": 6, "completion_tokens": 2,
                               "total_tokens": 8})
        client.chat(model="gpt-4o-mini", messages=[{"role": "user", "content": "hi"}])
        assert client.last_usage is client._backend.last_usage
        assert client.last_usage.total_tokens == 8

    def test_a_provider_that_said_nothing_is_none_and_not_zero(self):
        client = self._client(None)
        client.chat(model="gpt-4o-mini", messages=[{"role": "user", "content": "hi"}])
        assert client.last_usage is None

    def test_an_injected_backend_that_never_heard_of_usage_does_not_raise(self):
        """A library caller may inject anything with `chat`. Reading the
        counts off one that has none must be `None`, not an AttributeError
        in the middle of somebody's mission."""

        class _Bare:
            capabilities = None

            def chat(self, model, messages, stream=False, **kw):
                return "hi"

        client = UnifiedClient(provider_override="openai", backend=_Bare())
        assert client.last_usage is None


class TestTheToolCallSideChannel:
    """The second channel beside the counts, read the same way.

    Native tool calls travel as plain dicts so that nothing reading them
    has to import a backend type: `{"id", "name", "arguments"}`, every
    call the provider made, in its order.
    """

    def _client(self, message):
        mock_openai = MagicMock()
        mock_openai.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=message)])
        return UnifiedClient(provider_override="openai",
                             openai_client=mock_openai)

    def test_nothing_has_been_asked_yet(self):
        client = self._client(SimpleNamespace(content="hi"))
        assert client.last_tool_calls == []

    def test_it_is_the_backends(self):
        client = self._client(SimpleNamespace(content=None, tool_calls=[
            SimpleNamespace(id="a", function=SimpleNamespace(
                name="f", arguments='{"n": 1}'))]))
        client.chat(model="gpt-4o-mini", messages=[{"role": "user",
                                                    "content": "hi"}])
        assert client.last_tool_calls is client._backend.last_tool_calls
        assert client.last_tool_calls == [
            {"id": "a", "name": "f", "arguments": {"n": 1}}]

    def test_the_native_kwargs_are_forwarded_to_the_backend(self):
        mock_openai = MagicMock()
        mock_openai.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="hi"))])
        client = UnifiedClient(provider_override="openai",
                               openai_client=mock_openai)
        client.chat(model="m", messages=[{"role": "user", "content": "hi"}],
                    tool_choice="required", parallel_tool_calls=True)
        kwargs = mock_openai.chat.completions.create.call_args.kwargs
        assert kwargs["tool_choice"] == "required"
        assert kwargs["parallel_tool_calls"] is True

    def test_an_injected_backend_that_never_heard_of_them_is_empty(self):
        """A caller loops over this. "No calls" and "a backend that cannot
        make calls" are the same instruction to that loop — whether it
        *can* is a `capabilities` question, asked somewhere else."""

        class _Bare:
            capabilities = None

            def chat(self, model, messages, stream=False, **kw):
                return "hi"

        client = UnifiedClient(provider_override="openai", backend=_Bare())
        assert client.last_tool_calls == []


class TestTheFakeCarriesBothChannels:
    """`FakeUnifiedClient` stands in for the real one in most of this
    suite, so a channel it does not have is a channel no test can script."""

    def test_it_reports_no_calls_by_default(self, fake_client):
        assert fake_client.last_tool_calls == []

    def test_scripted_calls_are_what_it_reports(self):
        from tests.conftest import FakeUnifiedClient

        calls = [{"id": "a", "name": "f", "arguments": {"n": 1}}]
        fake = FakeUnifiedClient(tool_calls=calls)
        fake.chat("m", [{"role": "user", "content": "x"}])
        assert fake.last_tool_calls == calls

    def test_it_swallows_what_a_native_request_carries(self):
        """A caller under test decides what to send; the fake must not be
        the reason a request shape cannot be tried."""
        from tests.conftest import FakeUnifiedClient

        fake = FakeUnifiedClient()
        fake.chat("m", [{"role": "user", "content": "x"}],
                  tools=[{"type": "function"}], tool_choice="required")
        assert fake.last_request["tool_choice"] == "required"


class TestUnifiedClientAnthropic:
    """The fourth provider, routed the same way as the other three."""

    def test_it_builds_the_anthropic_backend(self, monkeypatch):
        from core.runtime.backends.anthropic_backend import AnthropicBackend

        monkeypatch.setenv("ANTHROPIC_API_KEY", "key")
        client = UnifiedClient(provider_override="anthropic")
        assert client.provider == "anthropic"
        assert isinstance(client._backend, AnthropicBackend)

    def test_missing_anthropic_key_raises_by_name(self, monkeypatch):
        """Not a fallback to whichever provider does have a key."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "key")
        client = UnifiedClient(provider_override="anthropic")
        with pytest.raises(RuntimeError, match="Missing ANTHROPIC_API_KEY"):
            client.chat("m", [{"role": "user", "content": "hi"}])

    def test_the_side_channels_are_the_backends(self, monkeypatch):
        from core.runtime.backends.anthropic_backend import AnthropicBackend

        monkeypatch.setenv("ANTHROPIC_API_KEY", "key")
        stub = MagicMock()
        stub.messages.create.return_value = SimpleNamespace(
            content=[{"type": "text", "text": "hi"},
                     {"type": "tool_use", "id": "a", "name": "f",
                      "input": {"n": 1}}],
            usage={"input_tokens": 6, "output_tokens": 2})
        client = UnifiedClient(provider_override="anthropic",
                               backend=AnthropicBackend(client=stub))
        assert client.chat(model="m",
                           messages=[{"role": "user", "content": "hi"}]) == "hi"
        assert client.last_usage.total_tokens == 8
        assert client.last_tool_calls == [
            {"id": "a", "name": "f", "arguments": {"n": 1}}]
