# tests/test_profiles.py — Profile system + wildcard capability tests

import pytest
from core.contracts.schemas import ProfileMode, PolicyPack, PermissionGrant
from core.policy.profiles import PROFILE_SCOPES, policy_for_profile
from core.tools.capability import CapabilityEngine


class TestProfileScopes:
    def test_safe_scopes(self):
        scopes = PROFILE_SCOPES[ProfileMode.SAFE]
        assert "fs.read" in scopes
        assert "git.read" in scopes
        assert "verify.run" in scopes

    def test_dev_scopes(self):
        scopes = PROFILE_SCOPES[ProfileMode.DEV]
        assert "fs.write" in scopes
        assert "git.write" in scopes
        assert "python.exec" in scopes
        assert "shell.exec" in scopes

    def test_ops_scopes(self):
        scopes = PROFILE_SCOPES[ProfileMode.OPS]
        assert "git.push" in scopes
        assert "git.fetch" in scopes
        assert "pip.install" in scopes
        assert "http.read" in scopes
        assert "fs.delete" in scopes

    def test_god_is_wildcard(self):
        assert "*" in PROFILE_SCOPES[ProfileMode.GOD]


class TestPolicyForProfile:
    def test_safe_only_read_scopes(self):
        policy = policy_for_profile(ProfileMode.SAFE)
        assert "fs.read" in policy.allowed_scopes
        assert "git.read" in policy.allowed_scopes
        assert "verify.run" in policy.allowed_scopes
        # Should NOT include write scopes
        assert "fs.write" not in policy.allowed_scopes
        assert "git.write" not in policy.allowed_scopes

    def test_dev_includes_safe(self):
        policy = policy_for_profile(ProfileMode.DEV)
        # Safe scopes included
        assert "fs.read" in policy.allowed_scopes
        assert "git.read" in policy.allowed_scopes
        # Dev scopes included
        assert "fs.write" in policy.allowed_scopes
        assert "python.exec" in policy.allowed_scopes
        # OPS scopes NOT included
        assert "git.push" not in policy.allowed_scopes

    def test_ops_includes_dev_and_safe(self):
        policy = policy_for_profile(ProfileMode.OPS)
        # All lower level scopes
        assert "fs.read" in policy.allowed_scopes
        assert "fs.write" in policy.allowed_scopes
        assert "git.push" in policy.allowed_scopes
        assert "pip.install" in policy.allowed_scopes

    def test_god_includes_wildcard(self):
        policy = policy_for_profile(ProfileMode.GOD)
        assert "*" in policy.allowed_scopes

    def test_scopes_are_deduplicated(self):
        policy = policy_for_profile(ProfileMode.OPS)
        assert len(policy.allowed_scopes) == len(set(policy.allowed_scopes))


class TestWildcardCapability:
    def test_wildcard_allows_any_scope(self):
        policy = PolicyPack(allowed_scopes=["*"])
        engine = CapabilityEngine(policy)
        verdict = engine.check("any_tool", ["some.random.scope"])
        assert verdict.allowed is True

    def test_wildcard_allows_multiple_scopes(self):
        policy = PolicyPack(allowed_scopes=["*"])
        engine = CapabilityEngine(policy)
        verdict = engine.check("t", ["a.b", "c.d", "e.f"])
        assert verdict.allowed is True

    def test_no_wildcard_denies_missing_scope(self):
        policy = PolicyPack(allowed_scopes=["fs.read"])
        engine = CapabilityEngine(policy)
        verdict = engine.check("t", ["fs.write"])
        assert verdict.allowed is False

    def test_god_profile_allows_everything(self):
        engine = CapabilityEngine(policy_for_profile(ProfileMode.GOD))
        verdict = engine.check("any_tool", ["git.push", "fs.delete", "nuke.launch"])
        assert verdict.allowed is True


class TestSetProfile:
    def test_set_profile_changes_policy(self):
        engine = CapabilityEngine()
        # Default deny-all
        verdict = engine.check("t", ["fs.read"])
        assert verdict.allowed is False
        # Set to SAFE
        engine.set_profile(ProfileMode.SAFE)
        verdict = engine.check("t", ["fs.read"])
        assert verdict.allowed is True

    def test_set_profile_tracks_current(self):
        engine = CapabilityEngine()
        engine.set_profile(ProfileMode.DEV)
        assert engine.current_profile == "dev"

    def test_upgrade_profile(self):
        engine = CapabilityEngine()
        engine.set_profile(ProfileMode.SAFE)
        verdict = engine.check("t", ["git.write"])
        assert verdict.allowed is False
        engine.set_profile(ProfileMode.DEV)
        verdict = engine.check("t", ["git.write"])
        assert verdict.allowed is True

    def test_downgrade_profile(self):
        engine = CapabilityEngine()
        engine.set_profile(ProfileMode.OPS)
        verdict = engine.check("t", ["git.push"])
        assert verdict.allowed is True
        engine.set_profile(ProfileMode.SAFE)
        verdict = engine.check("t", ["git.push"])
        assert verdict.allowed is False


class TestRevokeAllGrants:
    def test_revoke_clears_grants(self):
        engine = CapabilityEngine()
        engine.add_grant(PermissionGrant(tool_name="t", scope="x.y"))
        assert len(engine.list_active_grants()) == 1
        count = engine.revoke_all_grants()
        assert count == 1
        assert len(engine.list_active_grants()) == 0

    def test_revoke_empty(self):
        engine = CapabilityEngine()
        count = engine.revoke_all_grants()
        assert count == 0

    def test_revoked_grant_no_longer_works(self):
        engine = CapabilityEngine()
        engine.add_grant(PermissionGrant(tool_name="t", scope="x.y"))
        verdict = engine.check("t", ["x.y"])
        assert verdict.allowed is True
        engine.revoke_all_grants()
        verdict = engine.check("t", ["x.y"])
        assert verdict.allowed is False
