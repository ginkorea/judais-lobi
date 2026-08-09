# tests/test_symbol_retrieval.py — Phase 8 symbol-aware retrieval

"""Fetching a function span instead of a file.

The ROADMAP's Phase 8 asks for "symbol-aware retrieval (fetching
specific function spans, not whole files)". Most of what follows is
about the three ways it declines: no recorded span, an ambiguous name,
and a path that leaves the repository.
"""

import textwrap

import pytest

from core.context.models import FileSymbols, RepoMapData, SymbolDef
from core.context.spans import (
    MAX_SPAN_LINES,
    SpanUnavailable,
    SymbolSpan,
    find_symbols,
    read_span,
    retrieve_symbol,
)
from core.context.symbols.python_extractor import PythonExtractor

SOURCE = textwrap.dedent('''\
    """A module."""
    import os

    CONSTANT = 1


    def alone(a, b):
        """Docstring."""
        return a + b


    class Holder:
        def method(self):
            return 1

        def other(self):
            return 2
    ''')


@pytest.fixture
def repo(tmp_path):
    """Writes pkg/mod.py; `repo(*rels)` maps them. `twin` is opt-in so the
    single-match tests are not accidentally ambiguous."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "mod.py").write_text(SOURCE, encoding="utf-8")

    def build(*rel_paths):
        extractor = PythonExtractor()
        files = {}
        for rel in (rel_paths or ("pkg/mod.py",)):
            path = tmp_path / rel
            files[rel] = extractor.extract(
                path.read_text(encoding="utf-8"), rel,
            )
        return RepoMapData(repo_root=str(tmp_path), files=files)

    def add_twin():
        (tmp_path / "pkg" / "twin.py").write_text(SOURCE, encoding="utf-8")
        return build("pkg/mod.py", "pkg/twin.py")

    build.root = tmp_path
    build.with_twin = add_twin
    return build


# ---------------------------------------------------------------------------
# The extractor now records where a definition ends
# ---------------------------------------------------------------------------

class TestEndLine:
    def test_a_function_records_its_last_line(self, repo):
        data = repo("pkg/mod.py")
        fn = next(s for s in data.files["pkg/mod.py"].symbols if s.name == "alone")
        assert fn.line == 7
        assert fn.end_line == 9
        assert fn.has_span is True

    def test_a_class_spans_its_methods(self, repo):
        data = repo("pkg/mod.py")
        cls = next(s for s in data.files["pkg/mod.py"].symbols if s.name == "Holder")
        assert cls.end_line > cls.line + 3

    def test_a_constant_records_one_line(self, repo):
        data = repo("pkg/mod.py")
        const = next(s for s in data.files["pkg/mod.py"].symbols
                     if s.name == "CONSTANT")
        assert const.line == const.end_line

    def test_an_extractor_that_cannot_tell_says_zero(self):
        """The regex fallback genuinely cannot find an end."""
        assert SymbolDef(name="x", kind="function", line=3).end_line == 0
        assert SymbolDef(name="x", kind="function", line=3).has_span is False


# ---------------------------------------------------------------------------
# Finding
# ---------------------------------------------------------------------------

class TestFinding:
    def test_it_finds_by_bare_name(self, repo):
        assert len(find_symbols(repo("pkg/mod.py"), "alone")) == 1

    def test_it_finds_a_method_by_dotted_name(self, repo):
        found = find_symbols(repo("pkg/mod.py"), "Holder.method")
        assert len(found) == 1
        assert found[0][1].parent == "Holder"

    def test_a_file_hint_narrows(self, repo):
        data = repo.with_twin()
        assert len(find_symbols(data, "alone")) == 2
        assert len(find_symbols(data, "alone", file_hint="twin")) == 1

    def test_a_missing_name_finds_nothing(self, repo):
        assert find_symbols(repo("pkg/mod.py"), "nope") == []

    def test_the_order_is_stable(self, repo):
        data = repo.with_twin()
        assert [p for p, _ in find_symbols(data, "alone")] == [
            "pkg/mod.py", "pkg/twin.py",
        ]


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

class TestReading:
    def test_it_returns_the_function_and_not_the_file(self, repo):
        span = retrieve_symbol(repo("pkg/mod.py"), "alone")
        assert span.source.startswith("def alone(a, b):")
        assert "class Holder" not in span.source
        assert "import os" not in span.source

    def test_the_citation_is_path_and_lines(self, repo):
        span = retrieve_symbol(repo("pkg/mod.py"), "alone")
        assert span.citation == "pkg/mod.py:7-9"
        assert span.render().startswith("# pkg/mod.py:7-9")

    def test_a_method_comes_back_alone(self, repo):
        span = retrieve_symbol(repo("pkg/mod.py"), "Holder.method")
        assert "def method" in span.source
        assert "def other" not in span.source

    def test_the_result_carries_its_kind_and_parent(self, repo):
        span = retrieve_symbol(repo("pkg/mod.py"), "Holder.method")
        assert isinstance(span, SymbolSpan)
        assert span.kind == "method"
        assert span.parent == "Holder"

    def test_a_long_span_is_truncated_and_says_so(self, repo):
        span = retrieve_symbol(repo("pkg/mod.py"), "Holder", max_lines=2)
        assert span.truncated is True
        assert len(span.source.splitlines()) == 2
        assert "truncated" in span.render()

    def test_the_default_cap_is_declared(self):
        assert MAX_SPAN_LINES == 400


# ---------------------------------------------------------------------------
# The three refusals
# ---------------------------------------------------------------------------

class TestRefusals:
    def test_no_recorded_span_refuses_rather_than_guessing(self, repo, tmp_path):
        """Half a function delivered silently is the failure to avoid."""
        data = RepoMapData(
            repo_root=str(tmp_path),
            files={"pkg/mod.py": FileSymbols(
                rel_path="pkg/mod.py",
                symbols=[SymbolDef(name="alone", kind="function", line=7)],
            )},
        )
        repo("pkg/mod.py")  # ensure the file exists on disk
        with pytest.raises(SpanUnavailable, match="no recorded end line"):
            retrieve_symbol(data, "alone")

    def test_an_ambiguous_name_lists_the_candidates(self, repo):
        data = repo.with_twin()
        with pytest.raises(SpanUnavailable) as exc:
            retrieve_symbol(data, "alone")
        message = str(exc.value)
        assert "ambiguous" in message
        assert "pkg/mod.py:7" in message
        assert "pkg/twin.py:7" in message

    def test_a_file_hint_resolves_the_ambiguity(self, repo):
        data = repo.with_twin()
        assert retrieve_symbol(data, "alone", file_hint="twin").rel_path \
            == "pkg/twin.py"

    def test_a_path_escaping_the_root_is_refused(self, repo, tmp_path):
        data = repo("pkg/mod.py")
        symbol = SymbolDef(name="x", kind="function", line=1, end_line=2)
        with pytest.raises(SpanUnavailable, match="outside the repository"):
            read_span(tmp_path / "pkg", "../../etc/passwd", symbol)

    def test_a_missing_name_says_so_and_suggests_a_rebuild(self, repo):
        with pytest.raises(SpanUnavailable, match="rebuild"):
            retrieve_symbol(repo("pkg/mod.py"), "never_defined")

    def test_a_stale_map_pointing_past_the_end_refuses(self, repo, tmp_path):
        repo("pkg/mod.py")
        data = RepoMapData(
            repo_root=str(tmp_path),
            files={"pkg/mod.py": FileSymbols(
                rel_path="pkg/mod.py",
                symbols=[SymbolDef(name="ghost", kind="function",
                                   line=9000, end_line=9010)],
            )},
        )
        with pytest.raises(SpanUnavailable, match="stale"):
            retrieve_symbol(data, "ghost")

    def test_a_vanished_file_refuses(self, repo, tmp_path):
        data = repo("pkg/mod.py")
        (tmp_path / "pkg" / "mod.py").unlink()
        with pytest.raises(SpanUnavailable, match="not a file"):
            retrieve_symbol(data, "alone")


# ---------------------------------------------------------------------------
# Reachable only through the bus
# ---------------------------------------------------------------------------

class TestThroughTheToolBus:
    """Nothing reads a path except through a gated tool."""

    def _bus(self, repo_path, scopes=("*",)):
        from core.contracts.schemas import PolicyPack
        from core.tools.bus import ToolBus
        from core.tools.capability import CapabilityEngine
        from core.tools.descriptors import REPO_MAP_DESCRIPTOR
        from core.tools.repo_map_tool import RepoMapTool

        bus = ToolBus(capability_engine=CapabilityEngine(
            PolicyPack(allowed_scopes=list(scopes))))
        bus.register(REPO_MAP_DESCRIPTOR, RepoMapTool(repo_path=str(repo_path)))
        return bus

    def test_the_symbol_action_is_declared_with_its_scope(self):
        from core.tools.descriptors import REPO_MAP_DESCRIPTOR

        assert REPO_MAP_DESCRIPTOR.action_scopes["symbol"] == ["fs.read"]

    def test_dispatch_returns_the_span(self, repo):
        bus = self._bus(repo.root)
        repo("pkg/mod.py")
        result = bus.dispatch("repo_map", action="symbol", name="alone")
        assert result.exit_code == 0
        assert "def alone(a, b):" in result.stdout
        assert "pkg/mod.py:" in result.stdout

    def test_a_refusal_is_a_non_zero_exit_and_not_a_traceback(self, repo):
        bus = self._bus(repo.root)
        repo("pkg/mod.py")
        result = bus.dispatch("repo_map", action="symbol", name="never_defined")
        assert result.exit_code != 0
        assert "no symbol named" in result.stderr

    def test_a_missing_name_argument_is_refused(self, repo):
        bus = self._bus(repo.root)
        result = bus.dispatch("repo_map", action="symbol")
        assert result.exit_code != 0
        assert "`name` is required" in result.stderr

    def test_without_fs_read_it_is_denied(self, repo):
        bus = self._bus(repo.root, scopes=("git.read",))
        result = bus.dispatch("repo_map", action="symbol", name="alone")
        assert result.exit_code != 0
        assert "capability_denied" in result.stderr


# ---------------------------------------------------------------------------
# The RETRIEVE phase uses it
# ---------------------------------------------------------------------------

class TestRetrievePhaseFetchesSpans:
    """Context discipline: the phase asks for symbols and gets spans."""

    def _ctx(self, reply, repo_root):
        from core.contracts.schemas import PolicyPack
        from core.kernel.roles import RoleContext
        from core.kernel.workflows import get_coding_workflow
        from core.tools.bus import ToolBus
        from core.tools.capability import CapabilityEngine
        from core.tools.descriptors import REPO_MAP_DESCRIPTOR
        from core.tools.repo_map_tool import RepoMapTool

        bus = ToolBus(capability_engine=CapabilityEngine(
            PolicyPack(allowed_scopes=["*"])))
        bus.register(REPO_MAP_DESCRIPTOR, RepoMapTool(repo_path=str(repo_root)))
        return RoleContext(chat=lambda _m: reply, tool_bus=bus,
                           workflow=get_coding_workflow())

    def _run(self, reply, repo):
        import json as _json
        from core.kernel.roles import RetrieveRole
        from core.kernel.state import SessionState

        repo("pkg/mod.py")
        return RetrieveRole().run(SessionState(task_description="x"),
                                  self._ctx(reply, repo.root))

    def test_named_symbols_arrive_as_source_with_citations(self, repo):
        import json as _json

        result = self._run(_json.dumps(
            {"task_id": "t", "symbols": ["alone", "Holder.method"]}), repo)
        assert result.success
        excerpt = result.output.repo_map_excerpt
        assert "def alone(a, b):" in excerpt
        assert "def method(self):" in excerpt
        assert "pkg/mod.py:7-9" in excerpt

    def test_a_whole_file_is_not_pulled_in(self, repo):
        import json as _json

        result = self._run(_json.dumps({"task_id": "t", "symbols": ["alone"]}),
                           repo)
        assert "class Holder" not in result.output.repo_map_excerpt

    def test_an_unresolvable_symbol_is_recorded_not_dropped(self, repo):
        import json as _json

        result = self._run(_json.dumps(
            {"task_id": "t", "symbols": ["nowhere"]}), repo)
        excerpt = result.output.repo_map_excerpt
        assert "nowhere: not retrieved" in excerpt
        assert "no symbol named" in excerpt

    def test_asking_for_nothing_fetches_nothing(self, repo):
        import json as _json

        result = self._run(_json.dumps({"task_id": "t", "symbols": []}), repo)
        assert result.success
        assert result.output.repo_map_excerpt == ""

    def test_the_request_is_capped(self, repo):
        import json as _json
        from core.kernel.roles import RetrieveRole

        many = ["alone"] * 50
        result = self._run(_json.dumps({"task_id": "t", "symbols": many}), repo)
        blocks = result.output.repo_map_excerpt.count("def alone(a, b):")
        assert blocks == RetrieveRole.MAX_SYMBOLS

    def test_the_model_is_told_the_symbols_key_exists(self):
        from core.kernel.roles import RetrieveRole, RoleContext
        from core.kernel.state import SessionState
        from core.kernel.workflows import get_coding_workflow

        ctx = RoleContext(chat=lambda _m: "{}", workflow=get_coding_workflow())
        messages = RetrieveRole().compose(
            SessionState(task_description="x"), ctx,
            ctx.schema_for("RETRIEVE"),
        )
        assert "symbols" in messages[0]["content"]
