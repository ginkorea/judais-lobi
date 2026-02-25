# tests/test_repo_map_cache.py — Tests for git-commit-keyed cache

import pytest

from core.context.models import FileSymbols, ImportEdge, RepoMapData, SymbolDef
from core.context.cache import (
    get_commit_hash,
    get_dirty_files,
    RepoMapCache,
)


# ---------------------------------------------------------------------------
# get_commit_hash
# ---------------------------------------------------------------------------

class TestGetCommitHash:
    def test_returns_hash(self):
        def runner(cmd, *, shell=False, timeout=None, executable=None):
            return 0, "abc123def456", ""
        assert get_commit_hash("/tmp/repo", subprocess_runner=runner) == "abc123def456"

    def test_returns_none_on_failure(self):
        def runner(cmd, *, shell=False, timeout=None, executable=None):
            return 128, "", "fatal: not a git repository"
        assert get_commit_hash("/tmp/repo", subprocess_runner=runner) is None


# ---------------------------------------------------------------------------
# get_dirty_files
# ---------------------------------------------------------------------------

class TestGetDirtyFiles:
    def test_modified_files(self):
        def runner(cmd, *, shell=False, timeout=None, executable=None):
            return 0, " M src/main.py\n?? new_file.py\n", ""
        files = get_dirty_files("/tmp/repo", subprocess_runner=runner)
        assert "src/main.py" in files
        assert "new_file.py" in files

    def test_clean_repo(self):
        def runner(cmd, *, shell=False, timeout=None, executable=None):
            return 0, "", ""
        assert get_dirty_files("/tmp/repo", subprocess_runner=runner) == []

    def test_failure_returns_empty(self):
        def runner(cmd, *, shell=False, timeout=None, executable=None):
            return 128, "", "error"
        assert get_dirty_files("/tmp/repo", subprocess_runner=runner) == []


# ---------------------------------------------------------------------------
# RepoMapCache save/load
# ---------------------------------------------------------------------------

class TestRepoMapCache:
    def _sample_data(self) -> RepoMapData:
        return RepoMapData(
            repo_root="/tmp/repo",
            commit_hash="abc123",
            files={
                "main.py": FileSymbols(
                    rel_path="main.py",
                    language="python",
                    symbols=[
                        SymbolDef(name="main", kind="function",
                                  signature="def main() -> None", line=1),
                        SymbolDef(name="Config", kind="class",
                                  decorators=["dataclass"], line=5),
                    ],
                    imports=[
                        ImportEdge(module="os.path", names=["join"]),
                        ImportEdge(module=".helper", is_relative=True),
                    ],
                ),
            },
        )

    def test_save_and_load_roundtrip(self, tmp_path):
        cache = RepoMapCache(str(tmp_path))
        data = self._sample_data()
        cache.save("abc123", data)
        loaded = cache.load("abc123")
        assert loaded is not None
        assert loaded.repo_root == data.repo_root
        assert loaded.commit_hash == data.commit_hash
        assert loaded.total_files == data.total_files
        assert loaded.total_symbols == data.total_symbols
        # Check symbol details
        fs = loaded.files["main.py"]
        assert fs.symbols[0].name == "main"
        assert fs.symbols[0].signature == "def main() -> None"
        assert fs.symbols[1].decorators == ["dataclass"]
        # Check import details
        assert fs.imports[0].module == "os.path"
        assert fs.imports[0].names == ["join"]
        assert fs.imports[1].is_relative is True

    def test_load_missing_returns_none(self, tmp_path):
        cache = RepoMapCache(str(tmp_path))
        assert cache.load("nonexistent") is None

    def test_save_creates_directories(self, tmp_path):
        cache = RepoMapCache(str(tmp_path))
        data = self._sample_data()
        path = cache.save("abc123", data)
        assert path.exists()

    def test_overwrite_existing(self, tmp_path):
        cache = RepoMapCache(str(tmp_path))
        data1 = self._sample_data()
        cache.save("abc123", data1)
        # Overwrite with different data
        data2 = RepoMapData(repo_root="/tmp/repo", commit_hash="abc123", files={})
        cache.save("abc123", data2)
        loaded = cache.load("abc123")
        assert loaded.total_files == 0
