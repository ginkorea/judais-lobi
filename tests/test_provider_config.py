# tests/test_provider_config.py — Tests for provider resolution and defaults

import os
import pytest

from core.runtime.provider_config import (
    API_KEY_ENV,
    DEFAULT_MODELS,
    PROVIDERS,
    resolve_provider,
)


class TestDefaultModels:
    def test_openai_default(self):
        assert DEFAULT_MODELS["openai"] == "gpt-4o-mini"

    def test_mistral_default(self):
        assert DEFAULT_MODELS["mistral"] == "codestral-latest"

    def test_local_default(self):
        """Only the last resort: LOCAL_MODEL and GET /models come first."""
        assert DEFAULT_MODELS["local"] == "local-model"

    def test_anthropic_default(self):
        """The current Opus, undated: the owner chose Opus 5 as the
        framework's Anthropic default, and a dated snapshot pinned here
        goes stale."""
        assert DEFAULT_MODELS["anthropic"] == "claude-opus-5"

    def test_keys(self):
        assert set(DEFAULT_MODELS.keys()) == {
            "openai", "anthropic", "mistral", "local"}

    def test_every_provider_is_reachable_from_the_cli(self):
        """The --provider choices are generated from this dict, so a
        backend cannot be reachable from one and not the other."""
        assert set(PROVIDERS) == set(DEFAULT_MODELS)


class TestResolveProvider:
    def test_explicit_provider(self):
        assert resolve_provider(requested="mistral", has_injected_client=True) == "mistral"

    def test_explicit_openai(self):
        assert resolve_provider(requested="openai", has_injected_client=True) == "openai"

    def test_env_var(self, monkeypatch):
        monkeypatch.setenv("ELF_PROVIDER", "mistral")
        assert resolve_provider(has_injected_client=True) == "mistral"

    def test_default_is_openai(self):
        assert resolve_provider(has_injected_client=True) == "openai"

    def test_injected_client_skips_fallback(self):
        """With an injected client, no key checking / fallback happens."""
        result = resolve_provider(requested="openai", has_injected_client=True)
        assert result == "openai"

    def test_fallback_openai_to_mistral(self, monkeypatch):
        """No OpenAI key -> falls back to mistral."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setenv("MISTRAL_API_KEY", "key")
        result = resolve_provider(requested="openai", has_injected_client=False)
        assert result == "mistral"

    def test_fallback_mistral_to_openai(self, monkeypatch):
        """No Mistral key -> falls back to openai."""
        monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "key")
        result = resolve_provider(requested="mistral", has_injected_client=False)
        assert result == "openai"

    def test_case_insensitive(self):
        assert resolve_provider(requested="OpenAI", has_injected_client=True) == "openai"

    def test_strips_whitespace(self):
        assert resolve_provider(requested="  mistral  ", has_injected_client=True) == "mistral"


class TestAnthropicIsNeverFallenBackFrom:
    """Naming a provider on purpose is an instruction, not a preference.

    `openai` and `mistral` swap when a key is missing because `openai` is
    the default nobody chose. Asking for Anthropic and being answered by
    OpenAI would be a different model, a different bill and a different
    set of capability flags — so the run stops by name instead, in
    `AnthropicBackend.__init__`.
    """

    def test_it_has_a_key_env(self):
        assert API_KEY_ENV["anthropic"] == "ANTHROPIC_API_KEY"

    def test_no_key_does_not_silently_become_openai(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "key")
        assert resolve_provider(requested="anthropic",
                                has_injected_client=False) == "anthropic"

    def test_a_missing_openai_key_does_not_become_anthropic_either(self, monkeypatch):
        """The swap is still the pair it has always been."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setenv("MISTRAL_API_KEY", "key")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "key")
        assert resolve_provider(requested="openai",
                                has_injected_client=False) == "mistral"
