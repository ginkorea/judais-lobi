# tests/test_critic_backends.py — Tests for core.critic.backends

from core.critic.backends import (
    create_backend,
    _parse_critic_response,
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
