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
    """Drop-in replacement for UnifiedClient. Returns canned responses.

    ``usage`` is the side channel the real client has: whatever is passed
    is what ``last_usage`` reports after every call, and the default
    ``None`` is a provider that reported nothing — which is what a fake
    should be unless a test says otherwise, because "nothing reported" is
    the state a ledger has to keep distinct from "nothing spent".

    ``tool_calls`` is the other side channel, and works the same way: a
    scripted list of ``{"id", "name", "arguments"}`` dicts that
    ``last_tool_calls`` reports, defaulting to none. Scripted rather than
    derived from ``canned`` on purpose — a real backend's tool calls do
    not appear in the text it returns, and a fake whose two channels
    agreed by construction could not catch a caller that read the wrong
    one.
    """

    def __init__(self, canned="Hello from fake client", provider="openai",
                 usage=None, tool_calls=None):
        self.canned = canned
        self.provider = provider
        self.last_usage = usage
        self.last_tool_calls = list(tool_calls or [])
        self.last_request = None

    def chat(self, model, messages, stream=False, **kwargs):
        # `**kwargs` swallows what a real request carries — `tools`,
        # `tool_choice`, `response_format`, sampling — because a caller
        # under test decides what to send and a fake must not be the
        # reason a request shape cannot be tried.
        self.last_request = {"model": model, "messages": messages,
                             "stream": stream, **kwargs}
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
    """Factory returning a callable (cmd, *, shell, timeout, executable, stdin) -> (int, str, str).

    ``stdin`` is accepted because ``run_python`` now hands its program to
    the interpreter on standard input, and ``run_subprocess`` forwards a
    non-``None`` stdin to whatever runner is installed; a fake that could
    not take the keyword would raise the moment it stood in for the real
    sandbox under that tool.
    """
    def runner(cmd, *, shell=False, timeout=None, executable=None, stdin=None):
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
    for var in (
        "OPENAI_API_KEY",
        "MISTRAL_API_KEY",
        "ANTHROPIC_API_KEY",
        "GOOGLE_API_KEY",
        "ELF_PROVIDER",
        # Deny-by-default: an ambient profile opt-up would silently change
        # what the default-profile tests measure. Removed so "the default"
        # means SAFE everywhere, and a test that wants another profile sets
        # it explicitly.
        "JUDAIS_LOBI_PROFILE",
    ):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture(autouse=True)
def isolate_audit(monkeypatch, tmp_path):
    """Point the default audit log at this test's tmp dir.

    Auditing is on by default from 0.8.x — every ``Tools()`` gets an
    ``AuditLogger`` writing to ``.judais-lobi/audit/<run-id>.jsonl`` under
    the *working directory*, which during a test run is the repository.
    Without this, the first suite that builds a default registry starts
    scattering audit files through the checkout.

    Autouse and env-based rather than a fixture each test opts into: the
    litter comes from tests that never mention auditing at all, so an
    opt-in guard would be absent from exactly the tests that need it. A
    test that wants the real default path sets ``JUDAIS_LOBI_AUDIT``
    itself with ``monkeypatch``, and one that wants no logger at all
    passes ``Tools(audit=None)``.
    """
    from core.policy.audit import AUDIT_ENV
    monkeypatch.setenv(AUDIT_ENV, str(tmp_path / "audit" / "default.jsonl"))


@pytest.fixture(autouse=True)
def isolate_runs(monkeypatch, tmp_path):
    """Point the durable run store at this test's tmp dir.

    Autouse for exactly the reason :func:`isolate_audit` is: the litter
    comes from tests that never mention a run store at all — anything
    that goes through ``judais --mission`` now opens one under
    ``.judais-lobi/runs/`` in the working directory, which during a test
    run is the repository. A test that wants no store at all sets
    ``JUDAIS_LOBI_RUNS=none``; a test that wants to read what was written
    reads ``tmp_path / "runs"``.
    """
    from core.durable import RUNS_ENV
    monkeypatch.setenv(RUNS_ENV, str(tmp_path / "runs"))




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


# ---------------------------------------------------------------------------
# Phase 4b: Profile / Audit fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def audit_logger(tmp_path):
    """AuditLogger writing to a temp directory."""
    from core.policy.audit import AuditLogger
    return AuditLogger(path=tmp_path / "test_audit.jsonl")


# ---------------------------------------------------------------------------
# Critic fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def critic_config():
    from core.critic.config import CriticConfig
    return CriticConfig(enabled=True)


@pytest.fixture
def disabled_critic_config():
    from core.critic.config import CriticConfig
    return CriticConfig(enabled=False)


@pytest.fixture
def critic_keystore():
    from core.critic.keystore import CriticKeystore
    return CriticKeystore()
