# tests/test_critic_triggers.py — Tests for core.critic.triggers

from core.critic.config import CriticConfig
from core.critic.models import CriticTriggerContext
from core.critic.triggers import should_invoke_critic, detect_security_surface, detect_dependency_changes


def test_after_plan_trigger():
    cfg = CriticConfig(enabled=True)
    ctx = CriticTriggerContext(current_phase="PLAN", next_phase="RETRIEVE",
                               total_iterations=1)
    ok, reason = should_invoke_critic(ctx, cfg)
    assert ok is True
    assert reason == "after_plan"


def test_after_run_trigger():
    cfg = CriticConfig(enabled=True)
    ctx = CriticTriggerContext(current_phase="RUN", next_phase="FINALIZE",
                               total_iterations=3)
    ok, reason = should_invoke_critic(ctx, cfg)
    assert ok is True
    assert reason == "after_run_pass"


def test_fix_loop_trigger():
    cfg = CriticConfig(enabled=True, trigger_after_plan=False, trigger_after_run_pass=False)
    ctx = CriticTriggerContext(current_phase="RUN", next_phase="FIX",
                               total_iterations=5, consecutive_fix_loops=4)
    ok, reason = should_invoke_critic(ctx, cfg)
    assert ok is True
    assert reason == "fix_loop"


def test_security_surface_detection():
    assert detect_security_surface(["auth/token.py"]) is True
    assert detect_security_surface(["docs/readme.md"]) is False


def test_dependency_detection():
    assert detect_dependency_changes(["requirements.txt"]) is True
    assert detect_dependency_changes(["backend/pyproject.toml"]) is True
    assert detect_dependency_changes(["src/app.py"]) is False
