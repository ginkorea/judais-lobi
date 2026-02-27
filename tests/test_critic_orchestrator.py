# tests/test_critic_orchestrator.py — Tests for core.critic.orchestrator

from core.critic.config import CriticConfig, CriticProviderConfig
from core.critic.models import CriticVerdict, ExternalCriticReport
from core.critic.orchestrator import CriticOrchestrator
from core.kernel.state import SessionState


class DummyBackend:
    def __init__(self, report):
        self.report = report
        self.default_model = "dummy"

    def critique(self, payload_json, model, max_tokens, timeout):
        return self.report


class DummyKeystore:
    def get_key(self, *args, **kwargs):
        return "dummy-key"


def test_is_available_false_when_disabled():
    cfg = CriticConfig(enabled=False)
    orch = CriticOrchestrator(cfg)
    assert orch.is_available is False


def test_invoke_multi_round_approve(monkeypatch):
    cfg = CriticConfig(enabled=True, cache_enabled=False, providers=[
        CriticProviderConfig(provider="openai", model="gpt")
    ])
    report = ExternalCriticReport(verdict=CriticVerdict.APPROVE, confidence=0.6)

    def fake_backend(provider, api_key, default_model):
        return DummyBackend(report)

    monkeypatch.setattr("core.critic.orchestrator.create_backend", fake_backend)
    orch = CriticOrchestrator(cfg, keystore=DummyKeystore())

    state = SessionState(task_description="task")
    final = orch.invoke_multi_round(state, "after_plan", session_manager=None,
                                    revision_callback=lambda r, s: True)
    assert final.consensus_verdict == CriticVerdict.APPROVE
    assert len(orch.round_history) == 1


def test_invoke_multi_round_block_noise(monkeypatch):
    cfg = CriticConfig(enabled=True, cache_enabled=False, max_rounds_per_invocation=3, providers=[
        CriticProviderConfig(provider="openai", model="gpt")
    ])
    report = ExternalCriticReport(
        verdict=CriticVerdict.BLOCK,
        logic_concerns=["same"],
        confidence=0.1,
    )

    def fake_backend(provider, api_key, default_model):
        return DummyBackend(report)

    monkeypatch.setattr("core.critic.orchestrator.create_backend", fake_backend)
    orch = CriticOrchestrator(cfg, keystore=DummyKeystore())

    state = SessionState(task_description="task")
    final = orch.invoke_multi_round(state, "after_plan", session_manager=None,
                                    revision_callback=lambda r, s: True)
    assert final.consensus_verdict == CriticVerdict.BLOCK
    assert len(orch.round_history) >= 2
    assert orch.round_history[-1].is_noise is True
