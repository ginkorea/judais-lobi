# tests/test_capability.py

import time
import pytest
from datetime import datetime, timezone, timedelta

from core.tools.capability import CapabilityEngine, CapabilityVerdict
from core.contracts.schemas import PermissionGrant, PolicyPack


class TestCapabilityVerdict:
    def test_allowed_verdict(self):
        v = CapabilityVerdict(allowed=True, reason="ok")
        assert v.allowed is True
        assert v.denied_scopes == []

    def test_denied_verdict(self):
        v = CapabilityVerdict(allowed=False, denied_scopes=["shell.exec"])
        assert v.allowed is False
        assert "shell.exec" in v.denied_scopes


class TestCapabilityEngineDefaults:
    def test_default_denies_all(self):
        engine = CapabilityEngine()
        result = engine.check("run_shell_command", ["shell.exec"])
        assert result.allowed is False
        assert "shell.exec" in result.denied_scopes

    def test_no_scopes_always_allowed(self):
        engine = CapabilityEngine()
        result = engine.check("any_tool", [])
        assert result.allowed is True

    def test_empty_policy(self):
        engine = CapabilityEngine(PolicyPack())
        result = engine.check("tool", ["scope.a"])
        assert result.allowed is False


class TestCapabilityEnginePolicy:
    def test_policy_allows_scope(self):
        policy = PolicyPack(allowed_scopes=["shell.exec"])
        engine = CapabilityEngine(policy)
        result = engine.check("run_shell_command", ["shell.exec"])
        assert result.allowed is True

    def test_policy_partial_coverage(self):
        policy = PolicyPack(allowed_scopes=["shell.exec"])
        engine = CapabilityEngine(policy)
        result = engine.check("tool", ["shell.exec", "net.any"])
        assert result.allowed is False
        assert "net.any" in result.denied_scopes
        assert "shell.exec" not in result.denied_scopes

    def test_policy_multiple_scopes(self):
        policy = PolicyPack(allowed_scopes=["python.exec", "pip.install"])
        engine = CapabilityEngine(policy)
        result = engine.check("install_project", ["python.exec", "pip.install"])
        assert result.allowed is True

    def test_policy_property(self):
        policy = PolicyPack(allowed_scopes=["a"])
        engine = CapabilityEngine(policy)
        assert engine.policy is policy


class TestCapabilityEngineGrants:
    def test_add_grant_allows_scope(self):
        engine = CapabilityEngine()
        grant = PermissionGrant(tool_name="run_shell_command", scope="shell.exec")
        engine.add_grant(grant)
        result = engine.check("run_shell_command", ["shell.exec"])
        assert result.allowed is True

    def test_grant_wrong_tool(self):
        engine = CapabilityEngine()
        grant = PermissionGrant(tool_name="other_tool", scope="shell.exec")
        engine.add_grant(grant)
        result = engine.check("run_shell_command", ["shell.exec"])
        assert result.allowed is False

    def test_wildcard_grant(self):
        """Grant with empty tool_name matches any tool."""
        engine = CapabilityEngine()
        grant = PermissionGrant(tool_name="", scope="shell.exec")
        engine.add_grant(grant)
        result = engine.check("run_shell_command", ["shell.exec"])
        assert result.allowed is True
        result2 = engine.check("other_tool", ["shell.exec"])
        assert result2.allowed is True

    def test_grant_plus_policy_mixed(self):
        policy = PolicyPack(allowed_scopes=["python.exec"])
        engine = CapabilityEngine(policy)
        grant = PermissionGrant(tool_name="install_project", scope="pip.install")
        engine.add_grant(grant)
        result = engine.check("install_project", ["python.exec", "pip.install"])
        assert result.allowed is True

    def test_list_active_grants(self):
        engine = CapabilityEngine()
        g1 = PermissionGrant(tool_name="a", scope="s1")
        g2 = PermissionGrant(tool_name="b", scope="s2")
        engine.add_grant(g1)
        engine.add_grant(g2)
        active = engine.list_active_grants()
        assert len(active) == 2

    def test_is_scope_granted_true(self):
        policy = PolicyPack(allowed_scopes=["shell.exec"])
        engine = CapabilityEngine(policy)
        assert engine.is_scope_granted("any", "shell.exec") is True

    def test_is_scope_granted_false(self):
        engine = CapabilityEngine()
        assert engine.is_scope_granted("any", "shell.exec") is False

    def test_is_scope_granted_via_grant(self):
        engine = CapabilityEngine()
        engine.add_grant(PermissionGrant(tool_name="t", scope="s"))
        assert engine.is_scope_granted("t", "s") is True


class TestInvocationScopedGrants:
    def test_invocation_grant_consumed_on_use(self):
        engine = CapabilityEngine()
        grant = PermissionGrant(
            tool_name="run_shell_command", scope="shell.exec",
            grant_scope="invocation",
        )
        engine.add_grant(grant)

        # First check succeeds and consumes the grant
        result = engine.check("run_shell_command", ["shell.exec"])
        assert result.allowed is True

        # Second check fails — grant consumed
        result = engine.check("run_shell_command", ["shell.exec"])
        assert result.allowed is False

    def test_session_grant_persists(self):
        engine = CapabilityEngine()
        grant = PermissionGrant(
            tool_name="run_shell_command", scope="shell.exec",
            grant_scope="session",
        )
        engine.add_grant(grant)

        result1 = engine.check("run_shell_command", ["shell.exec"])
        assert result1.allowed is True
        result2 = engine.check("run_shell_command", ["shell.exec"])
        assert result2.allowed is True


class TestTimeScopedGrants:
    def test_expired_grant_denied(self):
        engine = CapabilityEngine()
        # Grant issued 10 seconds ago, valid for 1 second
        grant = PermissionGrant(
            tool_name="t", scope="s",
            grant_issued_at=datetime.now(timezone.utc) - timedelta(seconds=10),
            grant_duration_seconds=1.0,
        )
        engine.add_grant(grant)
        result = engine.check("t", ["s"])
        assert result.allowed is False

    def test_non_expired_grant_allowed(self):
        engine = CapabilityEngine()
        grant = PermissionGrant(
            tool_name="t", scope="s",
            grant_issued_at=datetime.now(timezone.utc),
            grant_duration_seconds=3600.0,
        )
        engine.add_grant(grant)
        result = engine.check("t", ["s"])
        assert result.allowed is True

    def test_expire_stale_grants(self):
        engine = CapabilityEngine()
        stale = PermissionGrant(
            tool_name="t", scope="s",
            grant_issued_at=datetime.now(timezone.utc) - timedelta(seconds=10),
            grant_duration_seconds=1.0,
        )
        fresh = PermissionGrant(
            tool_name="t2", scope="s2",
            grant_issued_at=datetime.now(timezone.utc),
            grant_duration_seconds=3600.0,
        )
        engine.add_grant(stale)
        engine.add_grant(fresh)
        count = engine.expire_stale_grants()
        assert count == 1
        assert len(engine.list_active_grants()) == 1

    def test_no_duration_never_expires(self):
        engine = CapabilityEngine()
        grant = PermissionGrant(
            tool_name="t", scope="s",
            grant_duration_seconds=None,
        )
        engine.add_grant(grant)
        count = engine.expire_stale_grants()
        assert count == 0
        assert len(engine.list_active_grants()) == 1


class TestLoadGrants:
    def test_load_grants_replaces(self):
        engine = CapabilityEngine()
        engine.add_grant(PermissionGrant(tool_name="a", scope="x"))
        assert len(engine.list_active_grants()) == 1

        new_grants = [
            PermissionGrant(tool_name="b", scope="y"),
            PermissionGrant(tool_name="c", scope="z"),
        ]
        engine.load_grants(new_grants)
        assert len(engine.list_active_grants()) == 2

    def test_load_grants_for_replay(self):
        """Loaded grants should be usable for capability checks."""
        engine = CapabilityEngine()
        grants = [PermissionGrant(tool_name="t", scope="s")]
        engine.load_grants(grants)
        result = engine.check("t", ["s"])
        assert result.allowed is True

    def test_load_empty_clears(self):
        engine = CapabilityEngine()
        engine.add_grant(PermissionGrant(tool_name="a", scope="x"))
        engine.load_grants([])
        assert len(engine.list_active_grants()) == 0
