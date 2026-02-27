# tests/test_critic_integration.py — Orchestrator + critic integration

from core.critic.config import CriticConfig
from core.critic.models import AggregatedCriticReport, CriticVerdict
from core.kernel.orchestrator import Orchestrator, PhaseResult
from core.kernel.state import Phase


class StubDispatcher:
    def dispatch(self, phase, state):
        return PhaseResult(success=True)


class StubCritic:
    def __init__(self, config):
        self.config = config
        self.calls = []
        self.calls_this_session = 0
        self.is_available = True

    def invoke_multi_round(self, state, reason, session_manager=None, revision_callback=None):
        self.calls.append(reason)
        self.calls_this_session += 1
        return AggregatedCriticReport(consensus_verdict=CriticVerdict.APPROVE,
                                      round_number=1)


def test_orchestrator_no_critic():
    orch = Orchestrator(dispatcher=StubDispatcher(), critic=None)
    state = orch.run("task")
    assert state.current_phase == Phase.COMPLETED


def test_orchestrator_disabled_critic():
    cfg = CriticConfig(enabled=False)
    critic = StubCritic(cfg)
    orch = Orchestrator(dispatcher=StubDispatcher(), critic=critic)
    state = orch.run("task")
    assert state.current_phase == Phase.COMPLETED
    assert critic.calls == []


def test_orchestrator_invokes_after_plan():
    cfg = CriticConfig(enabled=True, trigger_after_run_pass=False)
    critic = StubCritic(cfg)
    orch = Orchestrator(dispatcher=StubDispatcher(), critic=critic)
    state = orch.run("task")
    assert state.current_phase == Phase.COMPLETED
    assert "after_plan" in critic.calls
