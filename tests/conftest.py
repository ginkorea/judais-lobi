# tests/conftest.py — Shared fixtures for judais-lobi test suite

import os
import pytest
import numpy as np
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from core.memory.memory import UnifiedMemory
from core.kernel import BudgetConfig, SessionState
from core.contracts.schemas import PersonalityConfig, PolicyPack
from core.agent import Agent
from core.tools.bus import ToolBus
from core.tools.capability import CapabilityEngine
from core.tools.sandbox import NoneSandbox


# ---------------------------------------------------------------------------
# Fake clients
# ---------------------------------------------------------------------------

class FakeUnifiedClient:
    """Drop-in replacement for UnifiedClient. Returns canned responses."""

    def __init__(self, canned="Hello from fake client", provider="openai"):
        self.canned = canned
        self.provider = provider

    def chat(self, model, messages, stream=False):
        if stream:
            return self._stream()
        return self.canned

    def _stream(self):
        for word in self.canned.split():
            yield SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content=word + " "))]
            )


class FakeEmbeddingClient:
    """Drop-in for OpenAI embedding client. Returns deterministic vectors."""

    def __init__(self, dim=16, seed=42):
        self.dim = dim
        self.rng = np.random.RandomState(seed)
        self.embeddings = self  # self.embeddings.create() interface

    def create(self, input, model=None):
        vec = self.rng.randn(self.dim).astype("float32")
        return SimpleNamespace(data=[SimpleNamespace(embedding=vec.tolist())])


# ---------------------------------------------------------------------------
# Fake subprocess runner factory
# ---------------------------------------------------------------------------

def make_fake_subprocess_runner(rc=0, stdout="ok", stderr=""):
    """Factory returning a callable (cmd, *, shell, timeout, executable) -> (int, str, str)."""
    def runner(cmd, *, shell=False, timeout=None, executable=None):
        return rc, stdout, stderr
    return runner


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_client():
    return FakeUnifiedClient()


@pytest.fixture
def fake_embedding_client():
    return FakeEmbeddingClient()


@pytest.fixture
def memory(tmp_path, fake_embedding_client):
    """UnifiedMemory backed by a temp SQLite DB and fake embeddings."""
    db = tmp_path / "test.db"
    return UnifiedMemory(db, embedding_client=fake_embedding_client)


@pytest.fixture
def fake_tools():
    """MagicMock standing in for the Tools registry."""
    tools = MagicMock()
    tools.list_tools.return_value = ["run_shell_command", "run_python_code"]
    tools.describe_tool.return_value = {"name": "mock_tool", "description": "A mock tool"}
    tools.run.return_value = "mock result"
    return tools


@pytest.fixture(autouse=True)
def isolate_env(monkeypatch):
    """Remove API keys and provider env vars so tests never make real calls."""
    for var in ("OPENAI_API_KEY", "MISTRAL_API_KEY", "ELF_PROVIDER"):
        monkeypatch.delenv(var, raising=False)


# ---------------------------------------------------------------------------
# Kernel fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def budget():
    """Default budget config for kernel tests."""
    return BudgetConfig()


@pytest.fixture
def tight_budget():
    """Restrictive budget for testing enforcement."""
    return BudgetConfig(
        max_phase_retries=2,
        max_total_iterations=5,
        max_time_per_phase_seconds=0.01,
    )


@pytest.fixture
def session_state():
    """Fresh SessionState for kernel tests."""
    return SessionState(task_description="test task")


# ---------------------------------------------------------------------------
# Agent fixtures
# ---------------------------------------------------------------------------

STUB_PERSONALITY = PersonalityConfig(
    name="stub",
    system_message="You are a test agent.",
    examples=[("Q?", "A.")],
    env_path="/tmp/stub_env",
)


@pytest.fixture
def test_personality():
    return STUB_PERSONALITY.model_copy()


@pytest.fixture
def agent(test_personality, fake_client, memory, fake_tools):
    return Agent(
        config=test_personality, debug=False,
        client=fake_client, memory=memory, tools=fake_tools,
    )


# ---------------------------------------------------------------------------
# Phase 4: ToolBus / Capability / Sandbox fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def none_sandbox():
    """NoneSandbox instance for testing."""
    return NoneSandbox()


@pytest.fixture
def capability_engine():
    """Default deny-all CapabilityEngine for testing."""
    return CapabilityEngine()


@pytest.fixture
def permissive_capability_engine():
    """CapabilityEngine with all common scopes allowed."""
    policy = PolicyPack(allowed_scopes=[
        "shell.exec", "python.exec", "pip.install",
        "http.read", "fs.read", "audio.output",
    ])
    return CapabilityEngine(policy)


@pytest.fixture
def tool_bus(permissive_capability_engine, none_sandbox):
    """ToolBus with permissive capabilities and NoneSandbox."""
    return ToolBus(
        capability_engine=permissive_capability_engine,
        sandbox=none_sandbox,
    )
