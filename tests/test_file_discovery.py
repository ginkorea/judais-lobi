# tests/test_file_discovery.py — Tests for file discovery and language classification

import pytest
from pathlib import Path

from core.context.file_discovery import (
    classify_language,
    discover_files_git,
    discover_files_walk,
    discover_files,
    LANGUAGE_MAP,
    BINARY_EXTENSIONS,
    DEFAULT_IGNORE_PATTERNS,
)


# ---------------------------------------------------------------------------
# classify_language
# ---------------------------------------------------------------------------

class TestClassifyLanguage:
    def test_python(self):
        assert classify_language("src/main.py") == "python"

    def test_python_stub(self):
        assert classify_language("types/foo.pyi") == "python"

    def test_javascript(self):
        assert classify_language("app/index.js") == "javascript"

    def test_typescript(self):
        assert classify_language("app/index.ts") == "typescript"

    def test_tsx(self):
        assert classify_language("components/App.tsx") == "typescript"

    def test_c(self):
        assert classify_language("src/main.c") == "c"

    def test_c_header(self):
        assert classify_language("include/header.h") == "c"

    def test_cpp(self):
        assert classify_language("src/engine.cpp") == "cpp"

    def test_rust(self):
        assert classify_language("src/lib.rs") == "rust"

    def test_go(self):
        assert classify_language("cmd/main.go") == "go"

    def test_java(self):
        assert classify_language("src/Main.java") == "java"

    def test_makefile(self):
        assert classify_language("Makefile") == "makefile"

    def test_dockerfile(self):
        assert classify_language("Dockerfile") == "dockerfile"

    def test_unknown_extension(self):
        assert classify_language("data/unknown.xyz") == ""

    def test_no_extension(self):
        assert classify_language("README") == ""


# ---------------------------------------------------------------------------
# discover_files_git
# ---------------------------------------------------------------------------

class TestDiscoverFilesGit:
    def test_basic_listing(self):
        def runner(cmd, *, shell=False, timeout=None, executable=None):
            return 0, "src/main.py\nlib/util.py\nREADME.md\n", ""
        files = discover_files_git("/fake/repo", subprocess_runner=runner)
        assert files == ["README.md", "lib/util.py", "src/main.py"]

    def test_filters_binaries(self):
        def runner(cmd, *, shell=False, timeout=None, executable=None):
            return 0, "src/main.py\nassets/logo.png\nlib/helper.so\n", ""
        files = discover_files_git("/fake/repo", subprocess_runner=runner)
        assert files == ["src/main.py"]

    def test_empty_repo(self):
        def runner(cmd, *, shell=False, timeout=None, executable=None):
            return 0, "", ""
        files = discover_files_git("/fake/repo", subprocess_runner=runner)
        assert files == []

    def test_failure_raises_runtime_error(self):
        def runner(cmd, *, shell=False, timeout=None, executable=None):
            return 128, "", "fatal: not a git repository"
        with pytest.raises(RuntimeError, match="git ls-files failed"):
            discover_files_git("/fake/repo", subprocess_runner=runner)

    def test_blank_lines_filtered(self):
        def runner(cmd, *, shell=False, timeout=None, executable=None):
            return 0, "a.py\n\n\nb.py\n", ""
        files = discover_files_git("/fake/repo", subprocess_runner=runner)
        assert files == ["a.py", "b.py"]


# ---------------------------------------------------------------------------
# discover_files_walk
# ---------------------------------------------------------------------------

class TestDiscoverFilesWalk:
    def test_basic_walk(self, tmp_path):
        (tmp_path / "a.py").write_text("pass")
        (tmp_path / "b.js").write_text("//")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "c.rs").write_text("fn main(){}")
        files = discover_files_walk(str(tmp_path))
        assert "a.py" in files
        assert "b.js" in files
        assert str(Path("sub/c.rs")) in files

    def test_ignores_pycache(self, tmp_path):
        cache = tmp_path / "__pycache__"
        cache.mkdir()
        (cache / "module.cpython-312.pyc").write_text("")
        (tmp_path / "main.py").write_text("pass")
        files = discover_files_walk(str(tmp_path))
        assert files == ["main.py"]

    def test_ignores_node_modules(self, tmp_path):
        nm = tmp_path / "node_modules"
        nm.mkdir()
        (nm / "dep.js").write_text("//")
        (tmp_path / "app.js").write_text("//")
        files = discover_files_walk(str(tmp_path))
        assert files == ["app.js"]

    def test_filters_binary_extensions(self, tmp_path):
        (tmp_path / "code.py").write_text("pass")
        (tmp_path / "image.png").write_bytes(b"\x89PNG")
        files = discover_files_walk(str(tmp_path))
        assert files == ["code.py"]

    def test_empty_directory(self, tmp_path):
        files = discover_files_walk(str(tmp_path))
        assert files == []

    def test_ignores_egg_info(self, tmp_path):
        egg = tmp_path / "pkg.egg-info"
        egg.mkdir()
        (egg / "PKG-INFO").write_text("")
        (tmp_path / "setup.py").write_text("pass")
        files = discover_files_walk(str(tmp_path))
        assert files == ["setup.py"]


# ---------------------------------------------------------------------------
# discover_files (unified)
# ---------------------------------------------------------------------------

class TestDiscoverFiles:
    def test_prefers_git_when_available(self):
        def runner(cmd, *, shell=False, timeout=None, executable=None):
            return 0, "a.py\nb.py\n", ""
        files = discover_files("/fake/repo", subprocess_runner=runner)
        assert files == ["a.py", "b.py"]

    def test_falls_back_to_walk_on_git_failure(self, tmp_path):
        (tmp_path / "code.py").write_text("pass")
        def runner(cmd, *, shell=False, timeout=None, executable=None):
            return 128, "", "fatal: not a git repository"
        files = discover_files(str(tmp_path), subprocess_runner=runner)
        assert "code.py" in files


# ---------------------------------------------------------------------------
# Constants sanity checks
# ---------------------------------------------------------------------------

class TestConstants:
    def test_language_map_has_common_extensions(self):
        for ext in [".py", ".js", ".ts", ".c", ".cpp", ".rs", ".go", ".java"]:
            assert ext in LANGUAGE_MAP

    def test_binary_extensions_has_images(self):
        for ext in [".png", ".jpg", ".gif"]:
            assert ext in BINARY_EXTENSIONS

    def test_ignore_patterns_has_common_dirs(self):
        for d in ["__pycache__", ".git", "node_modules"]:
            assert d in DEFAULT_IGNORE_PATTERNS
