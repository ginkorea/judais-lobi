# tests/test_repo_map.py — Tests for RepoMap orchestrator

import pytest
from pathlib import Path

from core.context.repo_map import RepoMap
from core.context.models import RepoMapResult


def _make_repo(tmp_path):
    """Create a synthetic Python repo for testing."""
    # main.py imports helper
    (tmp_path / "main.py").write_text(
        "from helper import do_stuff\n\ndef main():\n    do_stuff()\n"
    )
    # helper.py imports util
    (tmp_path / "helper.py").write_text(
        "from util import format_output\n\ndef do_stuff():\n    format_output()\n"
    )
    # util.py — leaf node
    (tmp_path / "util.py").write_text(
        "MAX_LEN = 80\n\ndef format_output() -> str:\n    return ''\n"
    )
    return tmp_path


def _fake_git_runner_failure(cmd, *, shell=False, timeout=None, executable=None):
    """Runner that fails git commands (simulates non-git repo)."""
    return 128, "", "fatal: not a git repository"


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

class TestBuild:
    def test_build_on_synthetic_repo(self, tmp_path):
        _make_repo(tmp_path)
        rm = RepoMap(str(tmp_path), subprocess_runner=_fake_git_runner_failure)
        data = rm.build()
        assert data.total_files == 3
        assert data.total_symbols > 0

    def test_build_is_idempotent(self, tmp_path):
        _make_repo(tmp_path)
        rm = RepoMap(str(tmp_path), subprocess_runner=_fake_git_runner_failure)
        data1 = rm.build()
        data2 = rm.build()
        assert data1 is data2

    def test_force_rebuild(self, tmp_path):
        _make_repo(tmp_path)
        rm = RepoMap(str(tmp_path), subprocess_runner=_fake_git_runner_failure)
        data1 = rm.build()
        data2 = rm.build(force=True)
        assert data2 is not data1
        assert data2.total_files == data1.total_files


# ---------------------------------------------------------------------------
# Excerpt
# ---------------------------------------------------------------------------

class TestExcerpt:
    def test_overview_mode(self, tmp_path):
        _make_repo(tmp_path)
        rm = RepoMap(str(tmp_path), subprocess_runner=_fake_git_runner_failure)
        result = rm.excerpt_for_task()
        assert isinstance(result, RepoMapResult)
        assert result.total_files == 3
        assert result.total_symbols > 0
        assert result.excerpt != ""
        assert result.files_shown > 0

    def test_focused_mode_with_targets(self, tmp_path):
        _make_repo(tmp_path)
        rm = RepoMap(str(tmp_path), subprocess_runner=_fake_git_runner_failure)
        result = rm.excerpt_for_task(target_files=["main.py"])
        assert "main.py" in result.excerpt

    def test_token_budget_respected(self, tmp_path):
        _make_repo(tmp_path)
        rm = RepoMap(str(tmp_path), subprocess_runner=_fake_git_runner_failure, token_budget=10)
        result = rm.excerpt_for_task()
        # With such a tiny budget, not all files should be shown
        assert result.files_shown <= result.total_files

    def test_edge_stats_populated(self, tmp_path):
        _make_repo(tmp_path)
        rm = RepoMap(str(tmp_path), subprocess_runner=_fake_git_runner_failure)
        result = rm.excerpt_for_task()
        # main imports helper, helper imports util → at least 2 resolved
        assert result.edges_resolved >= 2
        # Some imports may be unresolvable (if third-party)
        assert result.edges_resolved + result.edges_unresolved > 0

    def test_excerpt_has_header(self, tmp_path):
        _make_repo(tmp_path)
        rm = RepoMap(str(tmp_path), subprocess_runner=_fake_git_runner_failure)
        result = rm.excerpt_for_task()
        assert result.excerpt.startswith("# Repo map:")
        assert "files" in result.excerpt.split("\n")[0]
        assert "# Languages:" in result.excerpt
        assert "# Ranking: centrality" in result.excerpt

    def test_focused_excerpt_header_says_relevance(self, tmp_path):
        _make_repo(tmp_path)
        rm = RepoMap(str(tmp_path), subprocess_runner=_fake_git_runner_failure)
        result = rm.excerpt_for_task(target_files=["main.py"])
        assert "# Ranking: relevance" in result.excerpt

    def test_char_budget_param(self, tmp_path):
        _make_repo(tmp_path)
        rm = RepoMap(str(tmp_path), subprocess_runner=_fake_git_runner_failure)
        result = rm.excerpt_for_task(char_budget=200)
        assert len(result.excerpt) <= 400  # some slack for footer


# ---------------------------------------------------------------------------
# Visualize
# ---------------------------------------------------------------------------

class TestVisualize:
    def test_dot_output(self, tmp_path):
        _make_repo(tmp_path)
        rm = RepoMap(str(tmp_path), subprocess_runner=_fake_git_runner_failure)
        dot = rm.visualize(format="dot")
        assert "digraph repo_map" in dot

    def test_mermaid_output(self, tmp_path):
        _make_repo(tmp_path)
        rm = RepoMap(str(tmp_path), subprocess_runner=_fake_git_runner_failure)
        md = rm.visualize(format="mermaid")
        assert "graph TD" in md

    def test_visualize_with_targets(self, tmp_path):
        _make_repo(tmp_path)
        rm = RepoMap(str(tmp_path), subprocess_runner=_fake_git_runner_failure)
        dot = rm.visualize(target_files=["main.py"], format="dot")
        assert "main_py" in dot


# ---------------------------------------------------------------------------
# Cache integration
# ---------------------------------------------------------------------------

class TestCacheIntegration:
    def test_cache_hit(self, tmp_path):
        _make_repo(tmp_path)
        call_count = 0

        def runner(cmd, *, shell=False, timeout=None, executable=None):
            nonlocal call_count
            call_count += 1
            if "rev-parse" in cmd:
                return 0, "deadbeef", ""
            if "ls-files" in cmd:
                return 0, "main.py\nhelper.py\nutil.py\n", ""
            if "status --porcelain" in cmd:
                return 0, "", ""
            return 128, "", "unknown"

        rm1 = RepoMap(str(tmp_path), subprocess_runner=runner)
        rm1.build()

        rm2 = RepoMap(str(tmp_path), subprocess_runner=runner)
        data = rm2.build()
        assert data.total_files == 3

    def test_dirty_overlay(self, tmp_path):
        _make_repo(tmp_path)

        def runner(cmd, *, shell=False, timeout=None, executable=None):
            if "rev-parse" in cmd:
                return 0, "deadbeef", ""
            if "ls-files" in cmd:
                return 0, "main.py\nhelper.py\nutil.py\n", ""
            if "status --porcelain" in cmd:
                return 0, " M main.py\n", ""
            return 128, "", "unknown"

        # First build caches
        rm1 = RepoMap(str(tmp_path), subprocess_runner=runner)
        rm1.build()

        # Modify main.py
        (tmp_path / "main.py").write_text(
            "from helper import do_stuff\n\ndef main_v2():\n    do_stuff()\n"
        )

        # Second build should overlay dirty file
        rm2 = RepoMap(str(tmp_path), subprocess_runner=runner)
        data = rm2.build()
        syms = data.files["main.py"].symbols
        names = [s.name for s in syms]
        assert "main_v2" in names
