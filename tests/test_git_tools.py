# tests/test_git_tools.py — GitTool tests

import pytest
from core.tools.git_tools import GitTool


def make_runner(rc=0, stdout="", stderr=""):
    """Factory for fake subprocess runner."""
    def runner(cmd, *, shell=False, timeout=None, executable=None):
        return rc, stdout, stderr
    return runner


@pytest.fixture
def git():
    """GitTool with fake subprocess runner that returns success."""
    return GitTool(subprocess_runner=make_runner(0, "", ""))


@pytest.fixture
def git_repo(tmp_path):
    """Create a real git repo for integration tests."""
    import subprocess
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(tmp_path), check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=str(tmp_path), check=True, capture_output=True,
    )
    return tmp_path


class TestGitReadActions:
    def test_status(self, git):
        rc, out, err = git("status")
        assert rc == 0

    def test_diff_basic(self, git):
        rc, out, err = git("diff")
        assert rc == 0

    def test_diff_staged(self, git):
        gt = GitTool(subprocess_runner=make_runner(0, "staged diff", ""))
        rc, out, err = gt("diff", staged=True)
        assert rc == 0

    def test_diff_path_spec(self, git):
        rc, out, err = git("diff", path_spec="file.py")
        assert rc == 0

    def test_log_default(self, git):
        rc, out, err = git("log")
        assert rc == 0

    def test_log_custom_n(self, git):
        rc, out, err = git("log", n=5, oneline=False)
        assert rc == 0


class TestGitWriteActions:
    def test_add_specific_paths(self, git):
        rc, out, err = git("add", paths=["file1.py", "file2.py"])
        assert rc == 0

    def test_add_all(self, git):
        rc, out, err = git("add")
        assert rc == 0

    def test_commit(self, git):
        rc, out, err = git("commit", message="test commit")
        assert rc == 0

    def test_branch_list(self, git):
        rc, out, err = git("branch")
        assert rc == 0

    def test_branch_create(self, git):
        rc, out, err = git("branch", name="feature")
        assert rc == 0

    def test_branch_delete(self, git):
        rc, out, err = git("branch", name="feature", delete=True)
        assert rc == 0

    def test_stash_push(self, git):
        rc, out, err = git("stash", sub_action="push", message="wip")
        assert rc == 0

    def test_stash_pop(self, git):
        rc, out, err = git("stash", sub_action="pop")
        assert rc == 0

    def test_stash_list(self, git):
        rc, out, err = git("stash", sub_action="list")
        assert rc == 0

    def test_stash_unknown_sub_action(self, git):
        rc, out, err = git("stash", sub_action="explode")
        assert rc == 1
        assert "unknown" in err.lower()

    def test_tag_list(self, git):
        rc, out, err = git("tag", list_tags=True)
        assert rc == 0

    def test_tag_create(self, git):
        rc, out, err = git("tag", name="v1.0")
        assert rc == 0

    def test_tag_annotated(self, git):
        rc, out, err = git("tag", name="v1.0", message="release 1.0")
        assert rc == 0

    def test_reset_mixed(self, git):
        rc, out, err = git("reset", mode="mixed", ref="HEAD~1")
        assert rc == 0

    def test_reset_invalid_mode(self, git):
        rc, out, err = git("reset", mode="nuclear")
        assert rc == 1
        assert "invalid" in err.lower()


class TestGitNetworkActions:
    def test_push_default(self, git):
        rc, out, err = git("push")
        assert rc == 0

    def test_push_specific_branch(self, git):
        rc, out, err = git("push", remote="origin", branch="main")
        assert rc == 0

    def test_pull_default(self, git):
        rc, out, err = git("pull")
        assert rc == 0

    def test_fetch_default(self, git):
        rc, out, err = git("fetch")
        assert rc == 0

    def test_fetch_custom_remote(self, git):
        rc, out, err = git("fetch", remote="upstream")
        assert rc == 0


class TestGitUnknownAction:
    def test_unknown_action(self, git):
        rc, out, err = git("explode")
        assert rc == 1
        assert "unknown" in err.lower()


class TestGitIntegration:
    """Integration tests with real git repos."""

    def test_status_clean_repo(self, git_repo):
        gt = GitTool()
        rc, out, err = gt("status", repo_path=str(git_repo))
        assert rc == 0
        assert out.strip() == ""  # clean repo

    def test_add_and_status(self, git_repo):
        (git_repo / "test.txt").write_text("hello")
        gt = GitTool()
        rc, out, err = gt("add", paths=["test.txt"], repo_path=str(git_repo))
        assert rc == 0
        rc, out, err = gt("status", repo_path=str(git_repo))
        assert rc == 0
        assert "test.txt" in out

    def test_commit_integration(self, git_repo):
        (git_repo / "f.txt").write_text("x")
        gt = GitTool()
        gt("add", paths=["f.txt"], repo_path=str(git_repo))
        rc, out, err = gt("commit", message="init", repo_path=str(git_repo))
        assert rc == 0

    def test_log_after_commit(self, git_repo):
        (git_repo / "f.txt").write_text("x")
        gt = GitTool()
        gt("add", paths=["f.txt"], repo_path=str(git_repo))
        gt("commit", message="first", repo_path=str(git_repo))
        rc, out, err = gt("log", repo_path=str(git_repo))
        assert rc == 0
        assert "first" in out

    def test_diff_shows_changes(self, git_repo):
        (git_repo / "f.txt").write_text("line1")
        gt = GitTool()
        gt("add", paths=["f.txt"], repo_path=str(git_repo))
        gt("commit", message="init", repo_path=str(git_repo))
        (git_repo / "f.txt").write_text("line1\nline2")
        rc, out, err = gt("diff", repo_path=str(git_repo))
        assert rc == 0
        assert "line2" in out
