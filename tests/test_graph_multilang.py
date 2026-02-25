# tests/test_graph_multilang.py — Tests for multi-language graph resolution

import pytest

from core.context.models import FileSymbols, ImportEdge, RepoMapData, SymbolDef
from core.context.graph import DependencyGraph


def _make_data(files_dict):
    """Helper: build RepoMapData from {rel_path: (language, [import_modules])}.

    Unlike the Python-only helper, this takes language info per file.
    """
    files = {}
    for rel_path, (language, imports) in files_dict.items():
        imp_edges = [ImportEdge(module=m) for m in imports]
        files[rel_path] = FileSymbols(
            rel_path=rel_path,
            language=language,
            symbols=[SymbolDef(name="x", kind="function")],
            imports=imp_edges,
        )
    return RepoMapData(repo_root="/tmp", files=files)


# ---------------------------------------------------------------------------
# C include resolution
# ---------------------------------------------------------------------------

class TestCIncludeResolution:
    def test_direct_header_match(self):
        data = _make_data({
            "main.c": ("c", ["util.h"]),
            "util.h": ("c", []),
        })
        g = DependencyGraph(data)
        assert ("main.c", "util.h") in g.edges

    def test_include_dir_prefix(self):
        data = _make_data({
            "main.c": ("c", ["mylib.h"]),
            "include/mylib.h": ("c", []),
        })
        g = DependencyGraph(data)
        assert ("main.c", "include/mylib.h") in g.edges

    def test_system_include_ignored(self):
        data = _make_data({
            "main.c": ("c", ["stdio.h"]),
        })
        g = DependencyGraph(data)
        assert g.edges == []


# ---------------------------------------------------------------------------
# Rust use resolution
# ---------------------------------------------------------------------------

class TestRustUseResolution:
    def test_crate_module(self):
        data = _make_data({
            "src/main.rs": ("rust", ["crate::config"]),
            "src/config.rs": ("rust", []),
        })
        g = DependencyGraph(data)
        assert ("src/main.rs", "src/config.rs") in g.edges

    def test_crate_module_mod_rs(self):
        data = _make_data({
            "src/main.rs": ("rust", ["crate::utils"]),
            "src/utils/mod.rs": ("rust", []),
        })
        g = DependencyGraph(data)
        assert ("src/main.rs", "src/utils/mod.rs") in g.edges

    def test_external_crate_ignored(self):
        data = _make_data({
            "src/main.rs": ("rust", ["serde::Deserialize"]),
        })
        g = DependencyGraph(data)
        assert g.edges == []


# ---------------------------------------------------------------------------
# Go import resolution
# ---------------------------------------------------------------------------

class TestGoImportResolution:
    def test_package_import(self):
        data = _make_data({
            "cmd/main.go": ("go", ["myapp/pkg/config"]),
            "pkg/config/config.go": ("go", []),
        })
        g = DependencyGraph(data)
        assert ("cmd/main.go", "pkg/config/config.go") in g.edges

    def test_stdlib_ignored(self):
        data = _make_data({
            "main.go": ("go", ["fmt"]),
        })
        g = DependencyGraph(data)
        assert g.edges == []


# ---------------------------------------------------------------------------
# JS/TS import resolution
# ---------------------------------------------------------------------------

class TestJSImportResolution:
    def test_relative_import_with_extension_guess(self):
        data = _make_data({
            "src/app.js": ("javascript", ["./utils"]),
            "src/utils.js": ("javascript", []),
        })
        g = DependencyGraph(data)
        assert ("src/app.js", "src/utils.js") in g.edges

    def test_relative_import_ts(self):
        data = _make_data({
            "src/app.ts": ("typescript", ["./config"]),
            "src/config.ts": ("typescript", []),
        })
        g = DependencyGraph(data)
        assert ("src/app.ts", "src/config.ts") in g.edges

    def test_index_resolution(self):
        data = _make_data({
            "src/app.js": ("javascript", ["./components"]),
            "src/components/index.js": ("javascript", []),
        })
        g = DependencyGraph(data)
        assert ("src/app.js", "src/components/index.js") in g.edges

    def test_node_modules_ignored(self):
        data = _make_data({
            "src/app.js": ("javascript", ["react"]),
        })
        g = DependencyGraph(data)
        assert g.edges == []


# ---------------------------------------------------------------------------
# Mixed-language repo
# ---------------------------------------------------------------------------

class TestMixedLanguageRepo:
    def test_mixed_repo_graph(self):
        data = _make_data({
            "main.py": ("python", ["config"]),
            "config.py": ("python", []),
            "src/main.c": ("c", ["util.h"]),
            "util.h": ("c", []),
            "src/app.js": ("javascript", ["./helpers"]),
            "src/helpers.js": ("javascript", []),
        })
        g = DependencyGraph(data)
        # Python edge
        assert ("main.py", "config.py") in g.edges
        # C edge
        assert ("src/main.c", "util.h") in g.edges
        # JS edge
        assert ("src/app.js", "src/helpers.js") in g.edges
        # No cross-language edges
        assert len(g.edges) == 3
