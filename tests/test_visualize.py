# tests/test_visualize.py — Tests for DOT and Mermaid graph export

import pytest

from core.context.models import FileSymbols, ImportEdge, RepoMapData, SymbolDef
from core.context.graph import DependencyGraph
from core.context.visualize import format_dot, format_mermaid


def _make_graph(files_dict):
    """Helper: build DependencyGraph from {rel_path: [import_modules]}."""
    files = {}
    for rel_path, imports in files_dict.items():
        imp_edges = [ImportEdge(module=m) for m in imports]
        files[rel_path] = FileSymbols(
            rel_path=rel_path,
            symbols=[SymbolDef(name="x", kind="function")],
            imports=imp_edges,
        )
    data = RepoMapData(repo_root="/tmp", files=files)
    return DependencyGraph(data)


# ---------------------------------------------------------------------------
# DOT format
# ---------------------------------------------------------------------------

class TestFormatDot:
    def test_basic_structure(self):
        g = _make_graph({"a.py": ["b"], "b.py": []})
        dot = format_dot(g)
        assert "digraph repo_map {" in dot
        assert "}" in dot

    def test_contains_nodes(self):
        g = _make_graph({"a.py": [], "b.py": []})
        dot = format_dot(g)
        assert "a_py" in dot
        assert "b_py" in dot

    def test_contains_edges(self):
        g = _make_graph({"a.py": ["b"], "b.py": []})
        dot = format_dot(g)
        assert "a_py -> b_py" in dot

    def test_highlight_files(self):
        g = _make_graph({"a.py": [], "b.py": []})
        dot = format_dot(g, highlight_files={"a.py"})
        assert "style=bold" in dot
        assert "color=blue" in dot

    def test_max_nodes_caps_output(self):
        files = {f"file{i}.py": [] for i in range(20)}
        g = _make_graph(files)
        dot = format_dot(g, max_nodes=5)
        # Should have at most 5 node definitions
        node_count = dot.count('[label=')
        assert node_count <= 5

    def test_empty_graph(self):
        data = RepoMapData(repo_root="/tmp", files={})
        g = DependencyGraph(data)
        dot = format_dot(g)
        assert "digraph repo_map {" in dot

    def test_ranked_files_limits_output(self):
        g = _make_graph({"a.py": [], "b.py": [], "c.py": []})
        ranked = [("a.py", 1.0), ("b.py", 0.5)]
        dot = format_dot(g, ranked_files=ranked, max_nodes=50)
        assert "a_py" in dot
        assert "b_py" in dot
        assert "c_py" not in dot


# ---------------------------------------------------------------------------
# Mermaid format
# ---------------------------------------------------------------------------

class TestFormatMermaid:
    def test_basic_structure(self):
        g = _make_graph({"a.py": ["b"], "b.py": []})
        md = format_mermaid(g)
        assert md.startswith("graph TD")

    def test_contains_nodes(self):
        g = _make_graph({"a.py": [], "b.py": []})
        md = format_mermaid(g)
        assert "a_py" in md
        assert "b_py" in md

    def test_contains_edges(self):
        g = _make_graph({"a.py": ["b"], "b.py": []})
        md = format_mermaid(g)
        assert "a_py --> b_py" in md

    def test_highlight_styling(self):
        g = _make_graph({"a.py": [], "b.py": []})
        md = format_mermaid(g, highlight_files={"a.py"})
        assert "style" in md
        assert "stroke:#00f" in md

    def test_max_nodes_caps_output(self):
        files = {f"file{i}.py": [] for i in range(20)}
        g = _make_graph(files)
        md = format_mermaid(g, max_nodes=5)
        # Count node declarations (lines with [...])
        node_lines = [l for l in md.split("\n") if "[" in l and "]" in l]
        assert len(node_lines) <= 5

    def test_empty_graph(self):
        data = RepoMapData(repo_root="/tmp", files={})
        g = DependencyGraph(data)
        md = format_mermaid(g)
        assert "graph TD" in md

    def test_no_highlight_styling_when_empty(self):
        g = _make_graph({"a.py": []})
        md = format_mermaid(g)
        assert "style" not in md

    def test_ranked_files_limits_output(self):
        g = _make_graph({"a.py": [], "b.py": [], "c.py": []})
        ranked = [("a.py", 1.0)]
        md = format_mermaid(g, ranked_files=ranked, max_nodes=50)
        assert "a_py" in md
        assert "c_py" not in md
