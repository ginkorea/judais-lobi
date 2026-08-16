# tests/test_patch_worktree.py — Tests for core/patch/worktree.py

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from core.patch.worktree import PatchWorktree


def make_runner(rc=0, stdout="", stderr=""):
    """Factory returning a mock subprocess runner."""
    calls = []
    def runner(cmd, *, shell=False, timeout=None, executable=None):
        calls.append(cmd)
        return rc, stdout, stderr
    runner.calls = calls
    return runner


class TestCreate:
    def test_create_worktree(self, tmp_path):
        runner = make_runner(0, "", "")
        wt = PatchWorktree(str(tmp_path), subprocess_runner=runner)
        path = wt.create(name="test1")
        assert "test1" in path
        assert wt.active is True
        assert wt.path == path
        assert wt.branch == "patch-test1"
        # Check command includes -b and HEAD
        assert any("-b" in c and "HEAD" in c for c in runner.calls)

    def test_create_with_auto_name(self, tmp_path):
        runner = make_runner(0, "", "")
        wt = PatchWorktree(str(tmp_path), subprocess_runner=runner)
        path = wt.create()
        assert wt.active is True
        assert "patch-" in wt.branch

    def test_create_when_already_active(self, tmp_path):
        runner = make_runner(0, "", "")
        wt = PatchWorktree(str(tmp_path), subprocess_runner=runner)
        wt.create(name="first")
        with pytest.raises(RuntimeError, match="already active"):
            wt.create(name="second")


class TestDiscard:
    def test_discard_worktree(self, tmp_path):
        runner = make_runner(0, "", "")
        wt = PatchWorktree(str(tmp_path), subprocess_runner=runner)
        wt.create(name="discard_me")
        rc, out, err = wt.discard()
        assert rc == 0
        assert wt.active is False
        assert wt.path is None
        # Should have called worktree remove and branch -D
        assert any("worktree remove" in c for c in runner.calls)
        assert any("branch -D" in c for c in runner.calls)

    def test_discard_when_not_active(self, tmp_path):
        runner = make_runner(0, "", "")
        wt = PatchWorktree(str(tmp_path), subprocess_runner=runner)
        rc, out, err = wt.discard()
        assert rc == 0
        assert "No active" in err


class TestMergeBack:
    def test_merge_back(self, tmp_path):
        runner = make_runner(0, "", "")
        wt = PatchWorktree(str(tmp_path), subprocess_runner=runner)
        wt.create(name="merge_me")
        rc, out, err = wt.merge_back(message="Apply patches")
        assert rc == 0
        assert wt.active is False
        # Check --no-ff in merge command
        assert any("--no-ff" in c for c in runner.calls)

    def test_merge_when_not_active(self, tmp_path):
        runner = make_runner(0, "", "")
        wt = PatchWorktree(str(tmp_path), subprocess_runner=runner)
        with pytest.raises(RuntimeError, match="No active worktree"):
            wt.merge_back()


class TestDiff:
    def test_diff(self, tmp_path):
        runner = make_runner(0, "diff output", "")
        wt = PatchWorktree(str(tmp_path), subprocess_runner=runner)
        wt.create(name="diff_me")
        rc, out, err = wt.diff()
        assert rc == 0


class TestProperties:
    def test_active_false_initially(self, tmp_path):
        runner = make_runner(0, "", "")
        wt = PatchWorktree(str(tmp_path), subprocess_runner=runner)
        assert wt.active is False
        assert wt.path is None
        assert wt.branch is None


class TestStateFile:
    def test_state_written_on_create(self, tmp_path):
        runner = make_runner(0, "", "")
        wt = PatchWorktree(str(tmp_path), subprocess_runner=runner)
        wt.create(name="state_test")
        state_file = tmp_path / ".judais-lobi" / "worktrees" / "active.json"
        assert state_file.exists()
        data = json.loads(state_file.read_text())
        assert "worktree_path" in data
        assert "branch_name" in data
        assert "timestamp" in data

    def test_state_deleted_on_discard(self, tmp_path):
        runner = make_runner(0, "", "")
        wt = PatchWorktree(str(tmp_path), subprocess_runner=runner)
        wt.create(name="cleanup_test")
        state_file = tmp_path / ".judais-lobi" / "worktrees" / "active.json"
        assert state_file.exists()
        wt.discard()
        assert not state_file.exists()

    def test_state_recovery(self, tmp_path):
        runner = make_runner(0, "", "")
        wt = PatchWorktree(str(tmp_path), subprocess_runner=runner)
        wt.create(name="recover")

        # Simulate process restart: create fresh instance
        wt2 = PatchWorktree(str(tmp_path), subprocess_runner=runner)
        assert wt2.active is True
        assert wt2.branch == "patch-recover"


class TestStateIsReplacedNeverTruncated:
    """active.json exists for the crash, so it has to survive one.

    It is read by the *next process* and by nothing else, which makes the
    truncate-then-fill it used to be exactly backwards: the one moment the
    file was half written was the one moment somebody would come looking for
    it, and a worktree whose record will not parse is a branch and a
    directory nothing will ever clean up.
    """

    def _state(self, tmp_path):
        return tmp_path / ".judais-lobi" / "worktrees" / "active.json"

    def _explode(self, monkeypatch):
        def boom(src, dst):
            raise OSError("no space left on device")

        monkeypatch.setattr(os, "replace", boom)

    def test_a_failed_state_write_leaves_the_recoverable_one(self, tmp_path,
                                                             monkeypatch):
        runner = make_runner(0, "", "")
        wt = PatchWorktree(str(tmp_path), subprocess_runner=runner)
        wt.create(name="first")
        self._explode(monkeypatch)
        wt._worktree_path = str(tmp_path / "second")
        wt._branch_name = "patch-second"
        with pytest.raises(OSError):
            wt._write_state()
        assert PatchWorktree(str(tmp_path),
                             subprocess_runner=runner).branch == "patch-first"

    def test_a_failed_state_write_leaves_no_staging_file(self, tmp_path,
                                                         monkeypatch):
        runner = make_runner(0, "", "")
        wt = PatchWorktree(str(tmp_path), subprocess_runner=runner)
        self._explode(monkeypatch)
        with pytest.raises(OSError):
            wt.create(name="orphan")
        worktrees = self._state(tmp_path).parent
        assert list(worktrees.iterdir()) == []

    def test_the_state_that_lands_is_the_whole_state(self, tmp_path):
        runner = make_runner(0, "", "")
        wt = PatchWorktree(str(tmp_path), subprocess_runner=runner)
        wt.create(name="whole")
        data = json.loads(self._state(tmp_path).read_text(encoding="utf-8"))
        assert data["branch_name"] == "patch-whole"
        assert data["timestamp"]


@pytest.mark.integration
class TestWorktreeIntegration:
    """Real git integration tests. Skipped if git is not available."""

    @pytest.fixture(autouse=True)
    def check_git(self):
        if not shutil.which("git"):
            pytest.skip("git not available")

    def test_real_worktree_lifecycle(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        # Initialize a git repo
        subprocess.run(["git", "init"], cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"],
                        cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"],
                        cwd=repo, capture_output=True)
        (repo / "file.txt").write_text("initial\n")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=repo, capture_output=True)

        wt = PatchWorktree(str(repo))
        path = wt.create(name="integ")
        assert Path(path).exists()

        # Modify a file in the worktree
        (Path(path) / "file.txt").write_text("modified\n")

        # Check diff
        rc, diff_out, err = wt.diff()
        assert rc == 0

        # Discard
        wt.discard()
        assert not wt.active
