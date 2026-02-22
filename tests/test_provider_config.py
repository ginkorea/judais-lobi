# tests/test_provider_config.py — Tests for provider resolution and defaults

import os
import pytest

from core.runtime.provider_config import DEFAULT_MODELS, resolve_provider


class TestDefaultModels:
    def test_openai_default(self):
        assert DEFAULT_MODELS["openai"] == "gpt-4o-mini"

    def test_mistral_default(self):
        assert DEFAULT_MODELS["mistral"] == "codestral-latest"

    def test_keys(self):
        assert set(DEFAULT_MODELS.keys()) == {"openai", "mistral"}


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
