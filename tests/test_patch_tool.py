# tests/test_patch_tool.py — Tests for core/tools/patch_tool.py

import json
from pathlib import Path

import pytest

from core.contracts.schemas import FilePatch, PatchSet
from core.tools.patch_tool import PatchTool
from core.tools.descriptors import PATCH_DESCRIPTOR, ALL_DESCRIPTORS


def make_runner(rc=0, stdout="", stderr=""):
    calls = []
    def runner(cmd, *, shell=False, timeout=None, executable=None):
        calls.append(cmd)
        return rc, stdout, stderr
    runner.calls = calls
    return runner


def make_patch_set_json(**overrides):
    data = {"task_id": "t1", "patches": []}
    data.update(overrides)
    return json.dumps(data)


class TestPatchToolActions:
    def test_all_actions_return_tuple(self, tmp_path):
        tool = PatchTool(repo_path=str(tmp_path))
        for action in ("validate", "apply", "diff", "merge", "rollback", "status"):
            if action in ("validate", "apply"):
                result = tool(action, patch_set_json=make_patch_set_json())
            else:
                result = tool(action)
            assert isinstance(result, tuple)
            assert len(result) == 3
            rc, out, err = result
            assert isinstance(rc, int)
            assert isinstance(out, str)
            assert isinstance(err, str)

    def test_unknown_action(self, tmp_path):
        tool = PatchTool(repo_path=str(tmp_path))
        rc, out, err = tool("nonexistent")
        assert rc == 1
        assert "Unknown patch action" in err

    def test_validate_action(self, tmp_path):
        (tmp_path / "a.py").write_text("old\n")
        tool = PatchTool(repo_path=str(tmp_path))
        ps_json = json.dumps({
            "task_id": "t1",
            "patches": [{
                "file_path": "a.py",
                "search_block": "old\n",
                "replace_block": "new\n",
                "action": "modify",
            }],
        })
        rc, out, err = tool("validate", patch_set_json=ps_json)
        assert rc == 0
        data = json.loads(out)
        assert data["success"] is True

    def test_apply_action(self, tmp_path):
        (tmp_path / "a.py").write_text("old\n")
        tool = PatchTool(repo_path=str(tmp_path))
        ps_json = json.dumps({
            "task_id": "t1",
            "patches": [{
                "file_path": "a.py",
                "search_block": "old\n",
                "replace_block": "new\n",
                "action": "modify",
            }],
        })
        rc, out, err = tool("apply", patch_set_json=ps_json, use_worktree=False)
        assert rc == 0
        data = json.loads(out)
        assert data["success"] is True
        assert (tmp_path / "a.py").read_text() == "new\n"

    def test_diff_action_no_worktree(self, tmp_path):
        tool = PatchTool(repo_path=str(tmp_path))
        rc, out, err = tool("diff")
        assert rc == 1  # No active worktree

    def test_rollback_action(self, tmp_path):
        tool = PatchTool(repo_path=str(tmp_path))
        rc, out, err = tool("rollback")
        assert rc == 0
        data = json.loads(out)
        assert data["rolled_back"] is True

    def test_status_action(self, tmp_path):
        tool = PatchTool(repo_path=str(tmp_path))
        rc, out, err = tool("status")
        assert rc == 0
        data = json.loads(out)
        assert "worktree_active" in data

    def test_merge_action_no_worktree(self, tmp_path):
        runner = make_runner(0, "", "")
        tool = PatchTool(repo_path=str(tmp_path), subprocess_runner=runner)
        rc, out, err = tool("merge")
        assert rc == 1  # No active worktree → RuntimeError caught


class TestPatchDescriptor:
    def test_descriptor_in_all(self):
        names = [d.tool_name for d in ALL_DESCRIPTORS]
        assert "patch" in names

    def test_descriptor_scopes(self):
        assert "fs.read" in PATCH_DESCRIPTOR.required_scopes
        assert "fs.write" in PATCH_DESCRIPTOR.required_scopes
        assert "git.read" in PATCH_DESCRIPTOR.required_scopes
        assert "git.write" in PATCH_DESCRIPTOR.required_scopes

    def test_action_scopes(self):
        assert PATCH_DESCRIPTOR.action_scopes["validate"] == ["fs.read"]
        assert "fs.write" in PATCH_DESCRIPTOR.action_scopes["apply"]
        assert "git.read" in PATCH_DESCRIPTOR.action_scopes["diff"]
        assert PATCH_DESCRIPTOR.action_scopes["rollback"] == ["git.write"]
        assert PATCH_DESCRIPTOR.action_scopes["merge"] == ["git.write"]

    def test_all_six_actions(self):
        expected = {"validate", "apply", "diff", "rollback", "merge", "status"}
        assert set(PATCH_DESCRIPTOR.action_scopes.keys()) == expected
