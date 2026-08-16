# tests/test_profiles.py — Profile system + wildcard capability tests

import pytest
from core.contracts.schemas import ProfileMode, PolicyPack, PermissionGrant
from core.policy.profiles import (
    DEFAULT_PROFILE,
    PROFILE_ENV_VAR,
    PROFILE_SCOPES,
    denial_reason,
    lowest_profile_for_scope,
    policy_for_profile,
    scope_grant_hint,
    select_profile,
)
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


class TestMcpCallInSafe:
    """`mcp.call` lives in SAFE, so a `--mission` over MCP works under the
    deny-by-default profile. The plane is chosen by the operator connecting a
    server and gated per-tool by the manifest and the server itself; the scope
    would gate nothing those two do not.
    """

    def test_mcp_call_is_a_safe_scope(self):
        assert "mcp.call" in PROFILE_SCOPES[ProfileMode.SAFE]

    def test_safe_policy_grants_mcp_call(self):
        engine = CapabilityEngine(policy_for_profile(ProfileMode.SAFE))
        assert engine.check("mcp.governed_read", ["mcp.call"]).allowed is True

    def test_safe_still_refuses_shell(self):
        # The whole point: SAFE opens the MCP plane and nothing that executes.
        engine = CapabilityEngine(policy_for_profile(ProfileMode.SAFE))
        assert engine.check("run_shell_command", ["shell.exec"]).allowed is False


class TestSelectProfile:
    """flag > env > default(SAFE), resolved in one place."""

    def test_default_is_safe(self, monkeypatch):
        monkeypatch.delenv(PROFILE_ENV_VAR, raising=False)
        assert select_profile(None) is ProfileMode.SAFE
        assert DEFAULT_PROFILE is ProfileMode.SAFE

    def test_flag_opts_up(self, monkeypatch):
        monkeypatch.delenv(PROFILE_ENV_VAR, raising=False)
        assert select_profile("dev") is ProfileMode.DEV
        assert select_profile("ops") is ProfileMode.OPS

    def test_env_respected_when_no_flag(self, monkeypatch):
        monkeypatch.setenv(PROFILE_ENV_VAR, "ops")
        assert select_profile(None) is ProfileMode.OPS

    def test_flag_beats_env(self, monkeypatch):
        monkeypatch.setenv(PROFILE_ENV_VAR, "god")
        assert select_profile("dev") is ProfileMode.DEV

    def test_empty_flag_and_env_falls_to_default(self, monkeypatch):
        monkeypatch.delenv(PROFILE_ENV_VAR, raising=False)
        assert select_profile("") is ProfileMode.SAFE
        monkeypatch.setenv(PROFILE_ENV_VAR, "   ")
        assert select_profile(None) is ProfileMode.SAFE

    def test_case_insensitive(self, monkeypatch):
        monkeypatch.delenv(PROFILE_ENV_VAR, raising=False)
        assert select_profile("DEV") is ProfileMode.DEV

    def test_unknown_value_is_refused_naming_choices(self, monkeypatch):
        monkeypatch.delenv(PROFILE_ENV_VAR, raising=False)
        with pytest.raises(ValueError) as exc:
            select_profile("dveloper")
        msg = str(exc.value)
        assert "dveloper" in msg
        assert "safe" in msg and "dev" in msg and "god" in msg


class TestLowestProfileForScope:
    def test_safe_scope_resolves_to_safe(self):
        assert lowest_profile_for_scope("fs.read") is ProfileMode.SAFE
        assert lowest_profile_for_scope("mcp.call") is ProfileMode.SAFE

    def test_dev_scope_resolves_to_dev(self):
        assert lowest_profile_for_scope("shell.exec") is ProfileMode.DEV

    def test_ops_scope_resolves_to_ops(self):
        assert lowest_profile_for_scope("git.push") is ProfileMode.OPS

    def test_unplaced_scope_resolves_to_god_wildcard(self):
        # A scope named in no narrower profile is reachable only through GOD's
        # "*". This is what would have been silently true of `mcp.call` had it
        # not been placed in SAFE — unreachable even under `ops`.
        assert lowest_profile_for_scope("nuke.launch") is ProfileMode.GOD

    def test_every_descriptor_scope_is_placed_below_god(self):
        """No descriptor scope may be reachable only through the wildcard.

        A scope in no explicit profile is unreachable even under `ops`, which
        is a bug. This walks every scope any tool descriptor declares — plus
        the bridged `mcp.call` — and asserts each resolves to a profile
        narrower than GOD.
        """
        from core.tools.descriptors import ALL_DESCRIPTORS
        from core.tools.mcp_client import McpToolBridge

        scopes = set(McpToolBridge.DEFAULT_SCOPES)
        for desc in ALL_DESCRIPTORS:
            scopes.update(desc.required_scopes)
            for action_scopes in desc.action_scopes.values():
                scopes.update(action_scopes)

        unplaced = {s for s in scopes
                    if lowest_profile_for_scope(s) is ProfileMode.GOD}
        assert unplaced == set(), (
            f"scopes reachable only through GOD's wildcard: {sorted(unplaced)}"
        )


class TestScopeGrantHint:
    def test_dev_scope_names_dev(self):
        hint = scope_grant_hint("shell.exec")
        assert "--profile dev" in hint
        assert f"{PROFILE_ENV_VAR}=dev" in hint

    def test_ops_scope_names_ops(self):
        assert "--profile ops" in scope_grant_hint("git.push")

    def test_a_default_scope_has_no_hint(self):
        # Nothing to opt into — a refusal for a SAFE scope is not about profile.
        assert scope_grant_hint("fs.read") == ""
        assert scope_grant_hint("mcp.call") == ""

    def test_lowest_profile_is_named_not_god(self):
        # shell.exec is in DEV and (cumulatively) OPS and GOD; the hint names
        # the *lowest* that grants it.
        assert "dev" in scope_grant_hint("shell.exec")
        assert "ops" not in scope_grant_hint("shell.exec")


class TestDenialReason:
    def test_names_scope_and_lowest_profile(self):
        reason = denial_reason(["shell.exec"], current_profile="safe")
        assert "shell.exec" in reason
        assert "--profile dev" in reason
        assert "safe" in reason  # the profile in force is named

    def test_multiple_scopes_each_named(self):
        reason = denial_reason(["shell.exec", "git.push"])
        assert "shell.exec needs --profile dev" in reason
        assert "git.push needs --profile ops" in reason

    def test_current_profile_optional(self):
        reason = denial_reason(["shell.exec"])
        assert "shell.exec needs --profile dev" in reason
