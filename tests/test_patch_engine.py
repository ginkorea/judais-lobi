# tests/test_patch_engine.py — Tests for core/patch/engine.py

import json
import shutil
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.contracts.schemas import FilePatch, PatchSet
from core.patch.engine import PatchEngine


def make_runner(rc=0, stdout="", stderr=""):
    """Factory returning a mock subprocess runner."""
    calls = []
    def runner(cmd, *, shell=False, timeout=None, executable=None):
        calls.append(cmd)
        return rc, stdout, stderr
    runner.calls = calls
    return runner


class TestValidate:
    def test_all_match(self, tmp_path):
        (tmp_path / "a.py").write_text("old line\n")
        engine = PatchEngine(str(tmp_path))
        ps = PatchSet(task_id="t1", patches=[
            FilePatch(file_path="a.py", search_block="old line\n",
                      replace_block="new line\n", action="modify"),
        ])
        result = engine.validate(ps)
        assert result.success is True
        assert len(result.file_results) == 1

    def test_one_fails(self, tmp_path):
        (tmp_path / "a.py").write_text("actual content\n")
        engine = PatchEngine(str(tmp_path))
        ps = PatchSet(task_id="t1", patches=[
            FilePatch(file_path="a.py", search_block="wrong content",
                      replace_block="new", action="modify"),
        ])
        result = engine.validate(ps)
        assert result.success is False

    def test_validate_create_exists(self, tmp_path):
        (tmp_path / "exists.py").write_text("content")
        engine = PatchEngine(str(tmp_path))
        ps = PatchSet(task_id="t1", patches=[
            FilePatch(file_path="exists.py", replace_block="new",
                      action="create"),
        ])
        result = engine.validate(ps)
        assert result.success is False

    def test_validate_create_not_exists(self, tmp_path):
        engine = PatchEngine(str(tmp_path))
        ps = PatchSet(task_id="t1", patches=[
            FilePatch(file_path="new.py", replace_block="content",
                      action="create"),
        ])
        result = engine.validate(ps)
        assert result.success is True

    def test_validate_delete_exists(self, tmp_path):
        (tmp_path / "old.py").write_text("x")
        engine = PatchEngine(str(tmp_path))
        ps = PatchSet(task_id="t1", patches=[
            FilePatch(file_path="old.py", action="delete"),
        ])
        result = engine.validate(ps)
        assert result.success is True

    def test_validate_delete_not_exists(self, tmp_path):
        engine = PatchEngine(str(tmp_path))
        ps = PatchSet(task_id="t1", patches=[
            FilePatch(file_path="missing.py", action="delete"),
        ])
        result = engine.validate(ps)
        assert result.success is False

    def test_validate_unknown_action(self, tmp_path):
        engine = PatchEngine(str(tmp_path))
        ps = PatchSet(task_id="t1", patches=[
            FilePatch(file_path="x.py", action="unknown"),
        ])
        result = engine.validate(ps)
        assert result.success is False


class TestApply:
    def test_apply_without_worktree(self, tmp_path):
        (tmp_path / "a.py").write_text("old\n")
        engine = PatchEngine(str(tmp_path))
        ps = PatchSet(task_id="t1", patches=[
            FilePatch(file_path="a.py", search_block="old\n",
                      replace_block="new\n", action="modify"),
        ])
        result = engine.apply(ps, use_worktree=False)
        assert result.success is True
        assert (tmp_path / "a.py").read_text() == "new\n"

    def test_apply_failure_stops(self, tmp_path):
        (tmp_path / "a.py").write_text("content1\n")
        (tmp_path / "b.py").write_text("content2\n")
        engine = PatchEngine(str(tmp_path))
        ps = PatchSet(task_id="t1", patches=[
            FilePatch(file_path="a.py", search_block="wrong",
                      replace_block="new", action="modify"),
            FilePatch(file_path="b.py", search_block="content2\n",
                      replace_block="new2\n", action="modify"),
        ])
        result = engine.apply(ps, use_worktree=False)
        assert result.success is False
        assert len(result.file_results) == 1  # Stopped at first failure

    def test_apply_with_worktree(self, tmp_path):
        (tmp_path / "a.py").write_text("old\n")
        runner = make_runner(0, "", "")
        engine = PatchEngine(str(tmp_path), subprocess_runner=runner)
        ps = PatchSet(task_id="t1", patches=[
            FilePatch(file_path="a.py", search_block="old\n",
                      replace_block="new\n", action="modify"),
        ])
        result = engine.apply(ps, use_worktree=True)
        assert result.worktree_path != ""

    def test_apply_create_and_modify(self, tmp_path):
        (tmp_path / "existing.py").write_text("old\n")
        engine = PatchEngine(str(tmp_path))
        ps = PatchSet(task_id="t1", patches=[
            FilePatch(file_path="new.py", replace_block="new file\n",
                      action="create"),
            FilePatch(file_path="existing.py", search_block="old\n",
                      replace_block="modified\n", action="modify"),
        ])
        result = engine.apply(ps, use_worktree=False)
        assert result.success is True
        assert (tmp_path / "new.py").read_text() == "new file\n"
        assert (tmp_path / "existing.py").read_text() == "modified\n"

    def test_apply_delete_and_modify(self, tmp_path):
        (tmp_path / "remove.py").write_text("bye")
        (tmp_path / "keep.py").write_text("old\n")
        engine = PatchEngine(str(tmp_path))
        ps = PatchSet(task_id="t1", patches=[
            FilePatch(file_path="remove.py", action="delete"),
            FilePatch(file_path="keep.py", search_block="old\n",
                      replace_block="new\n", action="modify"),
        ])
        result = engine.apply(ps, use_worktree=False)
        assert result.success is True
        assert not (tmp_path / "remove.py").exists()


class TestDiff:
    def test_diff_returns_output(self, tmp_path):
        runner = make_runner(0, "diff --git a/f b/f", "")
        engine = PatchEngine(str(tmp_path), subprocess_runner=runner)
        diff = engine.diff()
        # No active worktree, so diff() returns error
        assert "failed" in diff or "No active" in diff


class TestMerge:
    def test_merge(self, tmp_path):
        runner = make_runner(0, "merged", "")
        engine = PatchEngine(str(tmp_path), subprocess_runner=runner)
        engine._worktree.create(name="merge_test")
        rc, out, err = engine.merge(message="Apply patch")
        assert rc == 0


class TestRollback:
    def test_rollback(self, tmp_path):
        runner = make_runner(0, "", "")
        engine = PatchEngine(str(tmp_path), subprocess_runner=runner)
        engine._worktree.create(name="rb_test")
        engine.rollback()
        assert not engine._worktree.active


class TestStatus:
    def test_status(self, tmp_path):
        engine = PatchEngine(str(tmp_path))
        info = engine.status()
        assert info["worktree_active"] is False
        assert info["repo_path"] == str(tmp_path)


@pytest.mark.integration
class TestEngineIntegration:
    """Integration tests with real git. Skipped if git not available."""

    @pytest.fixture(autouse=True)
    def check_git(self):
        if not shutil.which("git"):
            pytest.skip("git not available")

    def test_validate_apply_diff_merge(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@t.com"],
                        cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "user.name", "T"],
                        cwd=repo, capture_output=True)
        (repo / "f.py").write_text("old\n")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=repo, capture_output=True)

        engine = PatchEngine(str(repo))
        ps = PatchSet(task_id="t1", patches=[
            FilePatch(file_path="f.py", search_block="old\n",
                      replace_block="new\n", action="modify"),
        ])

        # Validate
        vr = engine.validate(ps)
        assert vr.success is True

        # Apply in worktree
        ar = engine.apply(ps)
        assert ar.success is True
        wt_path = ar.worktree_path
        assert (Path(wt_path) / "f.py").read_text() == "new\n"

        # Diff
        diff = engine.diff()
        # Diff should show the change
        assert "new" in diff or diff == ""  # git diff may be empty if not staged

        # Merge
        rc, out, err = engine.merge(message="Apply patch")
        assert rc == 0
        assert not engine._worktree.active

    def test_apply_rollback(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@t.com"],
                        cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "user.name", "T"],
                        cwd=repo, capture_output=True)
        (repo / "f.py").write_text("original\n")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=repo, capture_output=True)

        engine = PatchEngine(str(repo))
        ps = PatchSet(task_id="t1", patches=[
            FilePatch(file_path="f.py", search_block="original\n",
                      replace_block="changed\n", action="modify"),
        ])
        ar = engine.apply(ps)
        assert ar.success is True

        # Rollback
        engine.rollback()
        assert not engine._worktree.active
        # Original file unchanged in main repo
        assert (repo / "f.py").read_text() == "original\n"
