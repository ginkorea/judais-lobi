# tests/test_critic_keystore.py — Tests for core.critic.keystore

import os
import types

from core.critic.keystore import CriticKeystore


def test_env_fallback(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    ks = CriticKeystore()
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    assert ks.get_key("openai", "OPENAI_API_KEY", "openai_api_key") == "env-key"


def test_keyring_get(monkeypatch):
    fake = types.SimpleNamespace()
    fake.get_password = lambda service, key: "kr-key"
    fake.set_password = lambda service, key, value: None
    fake.delete_password = lambda service, key: None

    monkeypatch.setitem(__import__("sys").modules, "keyring", fake)
    ks = CriticKeystore()
    assert ks.get_key("openai", "OPENAI_API_KEY", "openai_api_key") == "kr-key"


def test_set_delete_without_keyring(monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "keyring", None)
    ks = CriticKeystore()
    assert ks.set_key("openai_api_key", "x") is False
    assert ks.delete_key("openai_api_key") is False
