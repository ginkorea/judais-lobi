# tests/test_critic_backends.py — Tests for core.critic.backends

import inspect

from core.critic.backends import (
    create_backend,
    _parse_critic_response,
    AnthropicCritic,
    OpenAICritic,
)
from core.critic.models import CriticVerdict


def test_create_backend_unknown():
    assert create_backend("unknown", "k", "m") is None


def test_create_backend_openai():
    backend = create_backend("openai", "k", "m")
    assert isinstance(backend, OpenAICritic)


def test_parse_json_response():
    raw = '{"verdict":"approve","confidence":0.7,"top_risks":[]}'
    report = _parse_critic_response(raw, "openai", "gpt", 0.1)
    assert report.verdict == CriticVerdict.APPROVE
    assert report.confidence == 0.7


def test_parse_code_block():
    raw = """Here is JSON:\n```json\n{\"verdict\":\"caution\",\"confidence\":0.3}\n```\n"""
    report = _parse_critic_response(raw, "openai", "gpt", 0.1)
    assert report.verdict == CriticVerdict.CAUTION


def test_parse_invalid_response():
    report = _parse_critic_response("not json", "openai", "gpt", 0.1)
    assert report.verdict == CriticVerdict.UNAVAILABLE


def test_create_backend_anthropic():
    assert isinstance(create_backend("anthropic", "k", "m"), AnthropicCritic)


def test_the_anthropic_critic_speaks_the_sdk_and_not_a_second_http_client():
    """One client per provider.

    The critic tier reached Anthropic through the official SDK before
    `AnthropicBackend` existed, and it still does — which is why adding
    that backend changed nothing here. `core.runtime.backends.policy`
    states the rule: an SDK where the provider ships one, and the shared
    HTTP policy only for the two backends that speak HTTP by hand.
    """
    source = inspect.getsource(AnthropicCritic)
    assert "from anthropic import Anthropic" in source
    assert "client.messages.create" in source
    assert "requests." not in source and "httpx" not in source
