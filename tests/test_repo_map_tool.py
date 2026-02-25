# tests/test_repo_map_tool.py — Tests for RepoMapTool

import pytest
from pathlib import Path

from core.tools.repo_map_tool import RepoMapTool
from core.tools.descriptors import REPO_MAP_DESCRIPTOR


def _make_repo(tmp_path):
    (tmp_path / "main.py").write_text("def main():\n    pass\n")
    (tmp_path / "util.py").write_text("def helper():\n    pass\n")
    return tmp_path


def _fake_runner(cmd, *, shell=False, timeout=None, executable=None):
    return 128, "", "not a git repo"


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------

class TestActions:
    def test_build_action(self, tmp_path):
        _make_repo(tmp_path)
        tool = RepoMapTool(str(tmp_path), subprocess_runner=_fake_runner)
        rc, stdout, stderr = tool("build")
        assert rc == 0
        assert "2 files" in stdout

    def test_excerpt_action(self, tmp_path):
        _make_repo(tmp_path)
        tool = RepoMapTool(str(tmp_path), subprocess_runner=_fake_runner)
        rc, stdout, stderr = tool("excerpt")
        assert rc == 0
        assert "main.py" in stdout or "util.py" in stdout

    def test_status_action_before_build(self, tmp_path):
        tool = RepoMapTool(str(tmp_path), subprocess_runner=_fake_runner)
        rc, stdout, stderr = tool("status")
        assert rc == 0
        assert "not built" in stdout.lower()

    def test_status_action_after_build(self, tmp_path):
        _make_repo(tmp_path)
        tool = RepoMapTool(str(tmp_path), subprocess_runner=_fake_runner)
        tool("build")
        rc, stdout, stderr = tool("status")
        assert rc == 0
        assert "Files: 2" in stdout

    def test_visualize_action_dot(self, tmp_path):
        _make_repo(tmp_path)
        tool = RepoMapTool(str(tmp_path), subprocess_runner=_fake_runner)
        rc, stdout, stderr = tool("visualize", format="dot")
        assert rc == 0
        assert "digraph" in stdout

    def test_visualize_action_mermaid(self, tmp_path):
        _make_repo(tmp_path)
        tool = RepoMapTool(str(tmp_path), subprocess_runner=_fake_runner)
        rc, stdout, stderr = tool("visualize", format="mermaid")
        assert rc == 0
        assert "graph TD" in stdout

    def test_unknown_action(self, tmp_path):
        tool = RepoMapTool(str(tmp_path), subprocess_runner=_fake_runner)
        rc, stdout, stderr = tool("nonexistent")
        assert rc == 1
        assert "Unknown" in stderr


# ---------------------------------------------------------------------------
# Descriptor
# ---------------------------------------------------------------------------

class TestDescriptor:
    def test_descriptor_name(self):
        assert REPO_MAP_DESCRIPTOR.tool_name == "repo_map"

    def test_descriptor_scopes(self):
        assert "fs.read" in REPO_MAP_DESCRIPTOR.required_scopes
        assert "git.read" in REPO_MAP_DESCRIPTOR.required_scopes

    def test_descriptor_actions(self):
        assert set(REPO_MAP_DESCRIPTOR.action_scopes.keys()) == {
            "build", "excerpt", "status", "visualize"
        }

    def test_descriptor_has_description(self):
        assert REPO_MAP_DESCRIPTOR.description != ""
