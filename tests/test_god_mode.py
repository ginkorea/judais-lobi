# tests/test_god_mode.py — GodModeSession tests

import time
import pytest

from core.contracts.schemas import ProfileMode, AuditEntry
from core.policy.audit import AuditLogger
from core.policy.god_mode import GodModeSession
from core.policy.profiles import policy_for_profile
from core.tools.capability import CapabilityEngine


@pytest.fixture
def audit(tmp_path):
    return AuditLogger(path=tmp_path / "audit.jsonl")


@pytest.fixture
def engine():
    return CapabilityEngine(policy_for_profile(ProfileMode.SAFE))


@pytest.fixture
def god(audit):
    return GodModeSession(audit)


class TestGodModeActivation:
    def test_activate_returns_grant(self, god):
        grant = god.activate(reason="deploy")
        assert grant.reason == "deploy"
        assert grant.ttl_seconds == 300.0
        assert grant.panic_revoked is False

    def test_activate_sets_god_profile(self, god, engine):
        god.activate(reason="test", capability_engine=engine)
        assert engine.current_profile == "god"
        # Should allow any scope
        verdict = engine.check("t", ["nuke.launch"])
        assert verdict.allowed is True

    def test_is_active_after_activate(self, god):
        god.activate(reason="test", ttl=10.0)
        assert god.is_active() is True

    def test_not_active_before_activate(self, god):
        assert god.is_active() is False

    def test_activate_logs_audit(self, god, audit):
        god.activate(reason="deploy fix")
        entries = audit.tail()
        assert len(entries) == 1
        assert entries[0]["event_type"] == "god_activate"
        assert "deploy fix" in entries[0]["detail"]

    def test_custom_ttl(self, god):
        grant = god.activate(reason="quick", ttl=60.0)
        assert grant.ttl_seconds == 60.0


class TestGodModePanic:
    def test_panic_sets_event(self, god):
        god.activate(reason="test")
        god.panic()
        assert god.is_panicked is True

    def test_panic_downgrades_to_safe(self, god, engine):
        god.activate(reason="test", capability_engine=engine)
        god.panic(capability_engine=engine)
        assert engine.current_profile == "safe"

    def test_panic_revokes_grants(self, god, engine):
        god.activate(reason="test", capability_engine=engine)
        # Add an extra grant
        from core.contracts.schemas import PermissionGrant
        engine.add_grant(PermissionGrant(tool_name="t", scope="x.y"))
        god.panic(capability_engine=engine)
        assert len(engine.list_active_grants()) == 0

    def test_panic_marks_grant_revoked(self, god):
        grant = god.activate(reason="test")
        god.panic()
        assert grant.panic_revoked is True

    def test_is_active_false_after_panic(self, god):
        god.activate(reason="test")
        god.panic()
        assert god.is_active() is False

    def test_panic_logs_audit(self, god, audit):
        god.activate(reason="test")
        god.panic()
        entries = audit.tail()
        assert len(entries) == 2  # activate + panic
        assert entries[1]["event_type"] == "panic"
        assert entries[1]["verdict"] == "panic_revoked"

    def test_panic_without_activate(self, god):
        # Should not raise
        god.panic()
        assert god.is_panicked is True


class TestGodModeTTLExpiry:
    def test_auto_downgrade_on_ttl(self, god, engine):
        god.activate(reason="test", ttl=0.1, capability_engine=engine)
        assert engine.current_profile == "god"
        time.sleep(0.3)
        assert engine.current_profile == "dev"

    def test_not_active_after_ttl(self, god):
        god.activate(reason="test", ttl=0.1)
        time.sleep(0.3)
        assert god.is_active() is False

    def test_ttl_logs_expire_event(self, god, engine, audit):
        god.activate(reason="test", ttl=0.1, capability_engine=engine)
        time.sleep(0.3)
        entries = audit.tail()
        event_types = [e["event_type"] for e in entries]
        assert "god_expire" in event_types

    def test_panic_prevents_auto_downgrade(self, god, engine):
        god.activate(reason="test", ttl=0.2, capability_engine=engine)
        god.panic(capability_engine=engine)
        assert engine.current_profile == "safe"
        time.sleep(0.4)
        # Should still be SAFE, not DEV (panic overrides)
        assert engine.current_profile == "safe"


class TestGodModeReactivation:
    def test_reactivate_after_expiry(self, god, engine):
        god.activate(reason="first", ttl=0.1, capability_engine=engine)
        time.sleep(0.2)
        assert god.is_active() is False
        god.activate(reason="second", ttl=10.0, capability_engine=engine)
        assert god.is_active() is True
        assert engine.current_profile == "god"

    def test_reactivate_cancels_old_timer(self, god, engine):
        god.activate(reason="first", ttl=0.3, capability_engine=engine)
        god.activate(reason="second", ttl=10.0, capability_engine=engine)
        time.sleep(0.5)
        # Old timer (0.3s) should have been cancelled
        assert engine.current_profile == "god"
