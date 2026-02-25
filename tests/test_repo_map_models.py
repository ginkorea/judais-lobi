# tests/test_repo_map_models.py — Tests for repo map data models

import pytest
from pydantic import BaseModel

from core.context.models import (
    SymbolDef,
    ImportEdge,
    FileSymbols,
    RepoMapData,
    RepoMapResult,
)


# ---------------------------------------------------------------------------
# SymbolDef
# ---------------------------------------------------------------------------

class TestSymbolDef:
    def test_minimal_construction(self):
        s = SymbolDef(name="foo", kind="function")
        assert s.name == "foo"
        assert s.kind == "function"
        assert s.signature == ""
        assert s.parent == ""
        assert s.decorators == []
        assert s.line == 0

    def test_full_construction(self):
        s = SymbolDef(
            name="bar", kind="method", signature="def bar(self, x: int) -> str",
            parent="MyClass", decorators=["staticmethod"], line=42,
        )
        assert s.parent == "MyClass"
        assert s.decorators == ["staticmethod"]
        assert s.line == 42

    def test_mutable(self):
        s = SymbolDef(name="a", kind="class")
        s.name = "b"
        assert s.name == "b"


# ---------------------------------------------------------------------------
# ImportEdge
# ---------------------------------------------------------------------------

class TestImportEdge:
    def test_minimal(self):
        e = ImportEdge(module="os.path")
        assert e.module == "os.path"
        assert e.names == []
        assert e.is_relative is False

    def test_with_names(self):
        e = ImportEdge(module="core.kernel.state", names=["Phase", "SessionState"])
        assert len(e.names) == 2

    def test_relative(self):
        e = ImportEdge(module=".sibling", is_relative=True)
        assert e.is_relative is True


# ---------------------------------------------------------------------------
# FileSymbols
# ---------------------------------------------------------------------------

class TestFileSymbols:
    def test_minimal(self):
        fs = FileSymbols(rel_path="src/main.py")
        assert fs.rel_path == "src/main.py"
        assert fs.language == ""
        assert fs.symbols == []
        assert fs.imports == []

    def test_with_symbols_and_imports(self):
        syms = [SymbolDef(name="foo", kind="function")]
        imps = [ImportEdge(module="os")]
        fs = FileSymbols(rel_path="a.py", language="python", symbols=syms, imports=imps)
        assert len(fs.symbols) == 1
        assert len(fs.imports) == 1


# ---------------------------------------------------------------------------
# RepoMapData
# ---------------------------------------------------------------------------

class TestRepoMapData:
    def test_empty(self):
        data = RepoMapData(repo_root="/tmp/repo")
        assert data.total_files == 0
        assert data.total_symbols == 0
        assert data.commit_hash == ""

    def test_total_counts(self):
        fs1 = FileSymbols(
            rel_path="a.py",
            symbols=[SymbolDef(name="foo", kind="function"),
                     SymbolDef(name="bar", kind="function")],
        )
        fs2 = FileSymbols(
            rel_path="b.py",
            symbols=[SymbolDef(name="Baz", kind="class")],
        )
        data = RepoMapData(
            repo_root="/tmp/repo",
            files={"a.py": fs1, "b.py": fs2},
            commit_hash="abc123",
        )
        assert data.total_files == 2
        assert data.total_symbols == 3
        assert data.commit_hash == "abc123"


# ---------------------------------------------------------------------------
# RepoMapResult (Pydantic model)
# ---------------------------------------------------------------------------

class TestRepoMapResult:
    def test_is_pydantic_model(self):
        assert issubclass(RepoMapResult, BaseModel)

    def test_defaults(self):
        r = RepoMapResult()
        assert r.excerpt == ""
        assert r.total_files == 0
        assert r.total_symbols == 0
        assert r.excerpt_token_estimate == 0
        assert r.files_shown == 0
        assert r.files_omitted == 0
        assert r.edges_resolved == 0
        assert r.edges_unresolved == 0

    def test_full_construction(self):
        r = RepoMapResult(
            excerpt="src/main.py\n| main() -> None",
            total_files=50,
            total_symbols=200,
            excerpt_token_estimate=1024,
            files_shown=20,
            files_omitted=30,
            edges_resolved=15,
            edges_unresolved=5,
        )
        assert r.total_files == 50
        assert r.files_shown + r.files_omitted == r.total_files
        assert r.edges_resolved == 15
        assert r.edges_unresolved == 5

    def test_serialization_roundtrip(self):
        r = RepoMapResult(
            excerpt="hello", total_files=10, total_symbols=50,
            excerpt_token_estimate=256, files_shown=5, files_omitted=5,
        )
        data = r.model_dump()
        restored = RepoMapResult(**data)
        assert restored == r

    def test_json_roundtrip(self):
        r = RepoMapResult(excerpt="test", total_files=1)
        json_str = r.model_dump_json()
        restored = RepoMapResult.model_validate_json(json_str)
        assert restored == r
