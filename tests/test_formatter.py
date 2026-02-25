# tests/test_formatter.py — Tests for compact formatting with token budget

import pytest

from core.context.models import FileSymbols, RepoMapData, SymbolDef
from core.context.formatter import (
    estimate_tokens,
    format_file_entry,
    format_excerpt,
    format_symbol,
    _normalize_whitespace,
)


# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------

class TestEstimateTokens:
    def test_empty_string(self):
        assert estimate_tokens("") == 0

    def test_short_string(self):
        assert estimate_tokens("hello") == 1

    def test_known_length(self):
        # 100 chars = 25 tokens
        assert estimate_tokens("a" * 100) == 25


# ---------------------------------------------------------------------------
# Symbol formatting
# ---------------------------------------------------------------------------

class TestFormatSymbol:
    def test_function_with_signature(self):
        sym = SymbolDef(name="foo", kind="function", signature="def foo(x: int) -> str")
        assert format_symbol(sym) == "def foo(x: int) -> str"

    def test_class_without_signature(self):
        sym = SymbolDef(name="Foo", kind="class")
        assert format_symbol(sym) == "class Foo"

    def test_constant(self):
        sym = SymbolDef(name="MAX_SIZE", kind="constant")
        assert format_symbol(sym) == "MAX_SIZE"


# ---------------------------------------------------------------------------
# File entry formatting
# ---------------------------------------------------------------------------

class TestFormatFileEntry:
    def test_file_with_symbols(self):
        fs = FileSymbols(
            rel_path="src/main.py",
            language="python",
            symbols=[
                SymbolDef(name="main", kind="function", signature="def main() -> None"),
                SymbolDef(name="Config", kind="class", signature="class Config"),
                SymbolDef(name="load", kind="method", signature="def load(self)", parent="Config"),
            ],
        )
        result = format_file_entry(fs)
        assert "src/main.py" in result
        assert "| def main() -> None" in result
        assert "| class Config" in result
        assert "|   def load(self)" in result

    def test_empty_file(self):
        fs = FileSymbols(rel_path="empty.py")
        result = format_file_entry(fs)
        assert result == "empty.py"

    def test_methods_indented_under_class(self):
        fs = FileSymbols(
            rel_path="a.py",
            symbols=[
                SymbolDef(name="Foo", kind="class"),
                SymbolDef(name="bar", kind="method", parent="Foo"),
                SymbolDef(name="baz", kind="method", parent="Foo"),
            ],
        )
        result = format_file_entry(fs)
        lines = result.split("\n")
        # Class line
        assert lines[1] == "| class Foo"
        # Method lines indented
        assert lines[2].startswith("|   ")
        assert lines[3].startswith("|   ")


# ---------------------------------------------------------------------------
# Excerpt formatting
# ---------------------------------------------------------------------------

class TestFormatExcerpt:
    def _make_data(self, n_files: int) -> RepoMapData:
        files = {}
        for i in range(n_files):
            rel = f"file_{i:03d}.py"
            files[rel] = FileSymbols(
                rel_path=rel,
                language="python",
                symbols=[
                    SymbolDef(name=f"func_{i}", kind="function",
                              signature=f"def func_{i}() -> None"),
                ],
            )
        return RepoMapData(repo_root="/tmp", files=files)

    def test_all_files_fit(self):
        data = self._make_data(3)
        ranked = [(f"file_{i:03d}.py", 1.0 - i * 0.1) for i in range(3)]
        excerpt, shown, omitted = format_excerpt(data, ranked, token_budget=4096)
        assert shown == 3
        assert omitted == 0
        assert "file_000.py" in excerpt
        assert "... and" not in excerpt

    def test_budget_enforced(self):
        data = self._make_data(100)
        ranked = [(f"file_{i:03d}.py", 1.0) for i in range(100)]
        # Very small budget
        excerpt, shown, omitted = format_excerpt(data, ranked, token_budget=50)
        assert shown < 100
        assert omitted > 0
        assert "... and" in excerpt

    def test_truncation_footer(self):
        data = self._make_data(10)
        ranked = [(f"file_{i:03d}.py", 1.0) for i in range(10)]
        excerpt, shown, omitted = format_excerpt(data, ranked, token_budget=50)
        assert f"... and {omitted} more files" in excerpt

    def test_empty_map(self):
        data = RepoMapData(repo_root="/tmp", files={})
        excerpt, shown, omitted = format_excerpt(data, [], token_budget=4096)
        assert shown == 0
        assert omitted == 0
        assert excerpt == ""

    def test_missing_file_in_ranked_skipped(self):
        data = self._make_data(1)
        ranked = [("nonexistent.py", 1.0), ("file_000.py", 0.5)]
        excerpt, shown, omitted = format_excerpt(data, ranked, token_budget=4096)
        assert shown == 1
        assert "file_000.py" in excerpt

    def test_at_least_one_file_shown(self):
        """Even with tiny budget, at least one file should be shown."""
        data = self._make_data(5)
        ranked = [(f"file_{i:03d}.py", 1.0) for i in range(5)]
        excerpt, shown, omitted = format_excerpt(data, ranked, token_budget=1)
        assert shown >= 1

    def test_char_budget_enforced(self):
        data = self._make_data(100)
        ranked = [(f"file_{i:03d}.py", 1.0) for i in range(100)]
        excerpt, shown, omitted = format_excerpt(
            data, ranked, token_budget=999999, char_budget=200,
        )
        assert shown < 100
        assert len(excerpt) <= 300  # some slack for footer

    def test_header_prepended(self):
        data = self._make_data(3)
        ranked = [(f"file_{i:03d}.py", 1.0) for i in range(3)]
        excerpt, shown, omitted = format_excerpt(
            data, ranked, token_budget=4096, header="# Test header",
        )
        assert excerpt.startswith("# Test header")

    def test_header_counts_toward_budget(self):
        """A massive header should eat into the token budget."""
        data = self._make_data(50)
        ranked = [(f"file_{i:03d}.py", 1.0) for i in range(50)]
        big_header = "# " + "x" * 4000  # ~1000 tokens
        excerpt, shown, omitted = format_excerpt(
            data, ranked, token_budget=1050, header=big_header,
        )
        # With most budget consumed by header, few files should fit
        assert shown < 50


# ---------------------------------------------------------------------------
# Whitespace normalization
# ---------------------------------------------------------------------------

class TestNormalizeWhitespace:
    def test_collapses_internal_spaces(self):
        result = _normalize_whitespace("| def  foo(  x:  int )  ->  str")
        assert result == "| def foo( x: int ) -> str"

    def test_preserves_tree_prefix(self):
        result = _normalize_whitespace("|   def  bar(self)")
        assert result.startswith("|   ")
        assert "  " not in result[4:]

    def test_file_header_normalized(self):
        result = _normalize_whitespace("  src/main.py  ")
        assert result == "src/main.py"

    def test_multiline(self):
        text = "file.py\n| def  foo()\n|   def  bar()"
        result = _normalize_whitespace(text)
        lines = result.split("\n")
        assert lines[0] == "file.py"
        assert "  " not in lines[1][2:]  # after "| "
        assert "  " not in lines[2][4:]  # after "|   "


# ---------------------------------------------------------------------------
# Deterministic symbol formatting
# ---------------------------------------------------------------------------

class TestDeterministicFormatting:
    def test_signature_whitespace_normalized(self):
        sym = SymbolDef(
            name="foo", kind="function",
            signature="def  foo(  x:  int ,  y:  str )  ->  None",
        )
        result = format_symbol(sym)
        assert result == "def foo( x: int , y: str ) -> None"
