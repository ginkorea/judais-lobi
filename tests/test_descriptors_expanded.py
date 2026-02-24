# tests/test_descriptors_expanded.py — Phase 4a consolidated descriptor tests

import pytest

from core.tools.descriptors import (
    ToolDescriptor,
    FS_DESCRIPTOR,
    GIT_DESCRIPTOR,
    VERIFY_DESCRIPTOR,
    HIGH_RISK_ACTIONS,
    SKIP_SANDBOX_ACTIONS,
    NETWORK_ACTIONS,
    ALL_DESCRIPTORS,
)


class TestToolDescriptorNewFields:
    def test_high_risk_default_false(self):
        d = ToolDescriptor(tool_name="t")
        assert d.high_risk is False

    def test_skip_sandbox_default_false(self):
        d = ToolDescriptor(tool_name="t")
        assert d.skip_sandbox is False

    def test_action_scopes_default_empty(self):
        d = ToolDescriptor(tool_name="t")
        assert d.action_scopes == {}

    def test_action_scopes_custom(self):
        d = ToolDescriptor(
            tool_name="multi",
            action_scopes={"read": ["a.read"], "write": ["a.write"]},
        )
        assert d.action_scopes["read"] == ["a.read"]
        assert d.action_scopes["write"] == ["a.write"]

    def test_frozen_action_scopes(self):
        d = ToolDescriptor(tool_name="t", action_scopes={"a": ["x"]})
        with pytest.raises(AttributeError):
            d.action_scopes = {}


class TestFsDescriptor:
    def test_tool_name(self):
        assert FS_DESCRIPTOR.tool_name == "fs"

    def test_required_scopes_union(self):
        assert "fs.read" in FS_DESCRIPTOR.required_scopes
        assert "fs.write" in FS_DESCRIPTOR.required_scopes
        assert "fs.delete" in FS_DESCRIPTOR.required_scopes

    def test_action_scopes_read(self):
        assert FS_DESCRIPTOR.action_scopes["read"] == ["fs.read"]
        assert FS_DESCRIPTOR.action_scopes["list"] == ["fs.read"]
        assert FS_DESCRIPTOR.action_scopes["stat"] == ["fs.read"]

    def test_action_scopes_write(self):
        assert FS_DESCRIPTOR.action_scopes["write"] == ["fs.write"]

    def test_action_scopes_delete(self):
        assert FS_DESCRIPTOR.action_scopes["delete"] == ["fs.delete"]

    def test_all_actions_present(self):
        expected = {"read", "write", "delete", "list", "stat"}
        assert set(FS_DESCRIPTOR.action_scopes.keys()) == expected


class TestGitDescriptor:
    def test_tool_name(self):
        assert GIT_DESCRIPTOR.tool_name == "git"

    def test_required_scopes_union(self):
        scopes = set(GIT_DESCRIPTOR.required_scopes)
        assert {"git.read", "git.write", "git.push", "git.fetch"} == scopes

    def test_read_actions(self):
        for action in ("status", "diff", "log"):
            assert GIT_DESCRIPTOR.action_scopes[action] == ["git.read"]

    def test_write_actions(self):
        for action in ("add", "commit", "branch", "stash", "tag", "reset"):
            assert GIT_DESCRIPTOR.action_scopes[action] == ["git.write"]

    def test_push_action(self):
        assert GIT_DESCRIPTOR.action_scopes["push"] == ["git.push"]

    def test_fetch_actions(self):
        for action in ("pull", "fetch"):
            assert GIT_DESCRIPTOR.action_scopes[action] == ["git.fetch"]

    def test_all_twelve_actions(self):
        expected = {
            "status", "diff", "log", "add", "commit", "branch",
            "push", "pull", "fetch", "stash", "tag", "reset",
        }
        assert set(GIT_DESCRIPTOR.action_scopes.keys()) == expected


class TestVerifyDescriptor:
    def test_tool_name(self):
        assert VERIFY_DESCRIPTOR.tool_name == "verify"

    def test_single_scope(self):
        assert VERIFY_DESCRIPTOR.required_scopes == ["verify.run"]

    def test_all_actions_use_same_scope(self):
        for action in ("lint", "test", "typecheck", "format"):
            assert VERIFY_DESCRIPTOR.action_scopes[action] == ["verify.run"]


class TestActionMetadataSets:
    def test_high_risk_git_push(self):
        assert ("git", "push") in HIGH_RISK_ACTIONS

    def test_high_risk_git_reset(self):
        assert ("git", "reset") in HIGH_RISK_ACTIONS

    def test_high_risk_fs_delete(self):
        assert ("fs", "delete") in HIGH_RISK_ACTIONS

    def test_skip_sandbox_network_tools(self):
        for action in ("push", "pull", "fetch"):
            assert ("git", action) in SKIP_SANDBOX_ACTIONS
            assert ("git", action) in NETWORK_ACTIONS

    def test_safe_actions_not_high_risk(self):
        assert ("git", "status") not in HIGH_RISK_ACTIONS
        assert ("git", "log") not in HIGH_RISK_ACTIONS
        assert ("fs", "read") not in HIGH_RISK_ACTIONS

    def test_all_descriptors_includes_consolidated(self):
        names = [d.tool_name for d in ALL_DESCRIPTORS]
        assert "fs" in names
        assert "git" in names
        assert "verify" in names
        assert len(ALL_DESCRIPTORS) == 10
