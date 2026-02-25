# tests/test_dependency_graph.py — Tests for dependency graph and relevance ranking

import pytest

from core.context.models import FileSymbols, ImportEdge, RepoMapData, SymbolDef
from core.context.graph import DependencyGraph


def _make_data(files_dict):
    """Helper: build RepoMapData from {rel_path: [import_modules]}."""
    files = {}
    for rel_path, imports in files_dict.items():
        imp_edges = [ImportEdge(module=m) for m in imports]
        files[rel_path] = FileSymbols(
            rel_path=rel_path,
            language="python",
            symbols=[SymbolDef(name="x", kind="function")],
            imports=imp_edges,
        )
    return RepoMapData(repo_root="/tmp", files=files)


# ---------------------------------------------------------------------------
# Graph building
# ---------------------------------------------------------------------------

class TestGraphBuilding:
    def test_empty_data(self):
        data = RepoMapData(repo_root="/tmp", files={})
        g = DependencyGraph(data)
        assert g.files == frozenset()
        assert g.edges == []

    def test_simple_edge(self):
        data = _make_data({
            "a.py": ["b"],
            "b.py": [],
        })
        g = DependencyGraph(data)
        assert ("a.py", "b.py") in g.edges

    def test_unresolvable_imports_ignored(self):
        data = _make_data({
            "a.py": ["os", "sys", "unknown_third_party"],
        })
        g = DependencyGraph(data)
        assert g.edges == []

    def test_self_import_ignored(self):
        """A file importing itself should not create a self-edge."""
        data = _make_data({
            "a.py": ["a"],
        })
        g = DependencyGraph(data)
        assert g.edges == []


# ---------------------------------------------------------------------------
# Dependencies and dependents
# ---------------------------------------------------------------------------

class TestDepsAndRdeps:
    def test_dependencies_of(self):
        data = _make_data({
            "a.py": ["b", "c"],
            "b.py": [],
            "c.py": [],
        })
        g = DependencyGraph(data)
        assert g.dependencies_of("a.py") == {"b.py", "c.py"}

    def test_dependents_of(self):
        data = _make_data({
            "a.py": ["c"],
            "b.py": ["c"],
            "c.py": [],
        })
        g = DependencyGraph(data)
        assert g.dependents_of("c.py") == {"a.py", "b.py"}

    def test_no_dependencies(self):
        data = _make_data({"a.py": []})
        g = DependencyGraph(data)
        assert g.dependencies_of("a.py") == set()

    def test_no_dependents(self):
        data = _make_data({"a.py": []})
        g = DependencyGraph(data)
        assert g.dependents_of("a.py") == set()


# ---------------------------------------------------------------------------
# Dependency closure
# ---------------------------------------------------------------------------

class TestDependencyClosure:
    def test_depth_0_returns_seeds(self):
        data = _make_data({
            "a.py": ["b"],
            "b.py": ["c"],
            "c.py": [],
        })
        g = DependencyGraph(data)
        closure = g.dependency_closure(["a.py"], max_depth=0)
        assert closure == {"a.py"}

    def test_depth_1(self):
        data = _make_data({
            "a.py": ["b"],
            "b.py": ["c"],
            "c.py": [],
        })
        g = DependencyGraph(data)
        closure = g.dependency_closure(["a.py"], max_depth=1)
        assert "a.py" in closure
        assert "b.py" in closure
        assert "c.py" not in closure

    def test_depth_2(self):
        data = _make_data({
            "a.py": ["b"],
            "b.py": ["c"],
            "c.py": [],
        })
        g = DependencyGraph(data)
        closure = g.dependency_closure(["a.py"], max_depth=2)
        assert closure == {"a.py", "b.py", "c.py"}

    def test_circular_imports(self):
        data = _make_data({
            "a.py": ["b"],
            "b.py": ["a"],
        })
        g = DependencyGraph(data)
        closure = g.dependency_closure(["a.py"], max_depth=5)
        assert closure == {"a.py", "b.py"}

    def test_unknown_file_ignored(self):
        data = _make_data({"a.py": []})
        g = DependencyGraph(data)
        closure = g.dependency_closure(["nonexistent.py"], max_depth=2)
        assert closure == set()


# ---------------------------------------------------------------------------
# Relevance ranking
# ---------------------------------------------------------------------------

class TestRelevanceRanking:
    def test_target_gets_highest_score(self):
        data = _make_data({
            "target.py": [],
            "other.py": [],
        })
        g = DependencyGraph(data)
        ranked = g.rank_by_relevance(["target.py"])
        scores = dict(ranked)
        assert scores["target.py"] == 1.0
        assert scores["other.py"] == 0.1

    def test_direct_dependency_gets_0_8(self):
        data = _make_data({
            "target.py": ["dep"],
            "dep.py": [],
            "other.py": [],
        })
        g = DependencyGraph(data)
        scores = dict(g.rank_by_relevance(["target.py"]))
        assert scores["dep.py"] == 0.8

    def test_direct_dependent_gets_0_6(self):
        data = _make_data({
            "target.py": [],
            "user.py": ["target"],
            "other.py": [],
        })
        g = DependencyGraph(data)
        scores = dict(g.rank_by_relevance(["target.py"]))
        assert scores["user.py"] == 0.6

    def test_two_hop_gets_0_4(self):
        data = _make_data({
            "target.py": ["hop1"],
            "hop1.py": ["hop2"],
            "hop2.py": [],
            "other.py": [],
        })
        g = DependencyGraph(data)
        scores = dict(g.rank_by_relevance(["target.py"]))
        assert scores["hop2.py"] == 0.4

    def test_ranked_order(self):
        data = _make_data({
            "target.py": ["dep"],
            "dep.py": [],
            "user.py": ["target"],
            "other.py": [],
        })
        g = DependencyGraph(data)
        ranked = g.rank_by_relevance(["target.py"])
        names = [f for f, _ in ranked]
        # target should be first
        assert names[0] == "target.py"


# ---------------------------------------------------------------------------
# Centrality ranking
# ---------------------------------------------------------------------------

class TestCentralityRanking:
    def test_hub_file_ranks_highest(self):
        data = _make_data({
            "hub.py": ["a", "b", "c"],
            "a.py": [],
            "b.py": [],
            "c.py": [],
            "lonely.py": [],
        })
        g = DependencyGraph(data)
        ranked = g.rank_by_centrality()
        scores = dict(ranked)
        # hub has out-degree 3, each of a/b/c has in-degree 1
        assert scores["hub.py"] > scores["lonely.py"]
        assert scores["hub.py"] == 1.0
        assert scores["lonely.py"] == 0.0

    def test_empty_graph(self):
        data = RepoMapData(repo_root="/tmp", files={})
        g = DependencyGraph(data)
        assert g.rank_by_centrality() == []

    def test_all_isolated(self):
        data = _make_data({
            "a.py": [],
            "b.py": [],
        })
        g = DependencyGraph(data)
        ranked = g.rank_by_centrality()
        scores = dict(ranked)
        # All scores 0
        assert scores["a.py"] == 0.0
        assert scores["b.py"] == 0.0


# ---------------------------------------------------------------------------
# Package __init__ resolution
# ---------------------------------------------------------------------------

class TestPackageResolution:
    def test_resolves_to_init(self):
        data = _make_data({
            "a.py": ["pkg"],
            "pkg/__init__.py": [],
        })
        g = DependencyGraph(data)
        assert ("a.py", "pkg/__init__.py") in g.edges
