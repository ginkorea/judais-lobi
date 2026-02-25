# core/context/repo_map.py — Top-level RepoMap orchestrator

from pathlib import Path
from typing import Callable, List, Optional, Set

from core.context.models import FileSymbols, RepoMapData, RepoMapResult
from core.context.file_discovery import classify_language, discover_files
from core.context.symbols import get_extractor
from core.context.graph import DependencyGraph
from core.context.formatter import format_excerpt, estimate_tokens
from core.context.visualize import format_dot, format_mermaid
from core.context.cache import RepoMapCache, get_commit_hash, get_dirty_files


class RepoMap:
    """Orchestrates file discovery, symbol extraction, graph building,
    caching, and excerpt generation.

    Dual-use:
    - REPO_MAP phase: overview mode (centrality-ranked, no target_files)
    - RETRIEVE phase: focused mode (relevance-ranked by target_files)
    """

    def __init__(
        self,
        repo_path: str,
        subprocess_runner: Optional[Callable] = None,
        token_budget: int = 4096,
    ) -> None:
        self._repo_path = str(Path(repo_path).resolve())
        self._subprocess_runner = subprocess_runner
        self._token_budget = token_budget
        self._data: Optional[RepoMapData] = None
        self._graph: Optional[DependencyGraph] = None
        self._cache = RepoMapCache(self._repo_path)

    @property
    def data(self) -> Optional[RepoMapData]:
        return self._data

    @property
    def graph(self) -> Optional[DependencyGraph]:
        return self._graph

    def build(self, force: bool = False) -> RepoMapData:
        """Build or load the full repo map.

        On clean commit: full cache hit.
        On dirty state: load cache + re-extract dirty files.
        force=True: skip cache entirely.
        """
        if self._data is not None and not force:
            return self._data

        commit = get_commit_hash(self._repo_path, self._subprocess_runner)

        # Try cache
        if not force and commit:
            cached = self._cache.load(commit)
            if cached is not None:
                dirty = get_dirty_files(self._repo_path, self._subprocess_runner)
                if dirty:
                    # Re-extract only dirty files
                    self._overlay_dirty(cached, dirty)
                self._data = cached
                self._graph = DependencyGraph(self._data)
                return self._data

        # Full build
        files = discover_files(self._repo_path, self._subprocess_runner)
        file_symbols = {}
        for rel_path in files:
            language = classify_language(rel_path)
            extractor = get_extractor(language)
            try:
                full_path = Path(self._repo_path) / rel_path
                source = full_path.read_text(encoding="utf-8", errors="replace")
            except (OSError, UnicodeDecodeError):
                continue
            fs = extractor.extract(source, rel_path)
            fs.language = language
            file_symbols[rel_path] = fs

        self._data = RepoMapData(
            repo_root=self._repo_path,
            files=file_symbols,
            commit_hash=commit or "",
        )
        self._graph = DependencyGraph(self._data)

        # Save to cache
        if commit:
            self._cache.save(commit, self._data)

        return self._data

    def excerpt_for_task(
        self,
        target_files: Optional[List[str]] = None,
        char_budget: Optional[int] = None,
    ) -> RepoMapResult:
        """Generate a token-budgeted excerpt.

        target_files=None → overview mode (centrality ranking)
        target_files provided → focused mode (relevance ranking)
        char_budget: optional hard character limit (in addition to token budget).
        """
        if self._data is None:
            self.build()

        assert self._data is not None
        assert self._graph is not None

        if target_files:
            ranked = self._graph.rank_by_relevance(target_files)
            mode = "relevance"
        else:
            ranked = self._graph.rank_by_centrality()
            mode = "centrality"

        # Build metadata header
        languages = set()
        for fs in self._data.files.values():
            if fs.language:
                languages.add(fs.language)
        lang_str = ", ".join(sorted(languages)[:8])
        if len(languages) > 8:
            lang_str += f", +{len(languages) - 8} more"
        header = (
            f"# Repo map: {self._data.total_files} files, "
            f"{self._data.total_symbols} symbols\n"
            f"# Languages: {lang_str}\n"
            f"# Ranking: {mode} | Budget: {self._token_budget} tokens"
        )

        excerpt, files_shown, files_omitted = format_excerpt(
            self._data, ranked, self._token_budget,
            char_budget=char_budget, header=header,
        )

        return RepoMapResult(
            excerpt=excerpt,
            total_files=self._data.total_files,
            total_symbols=self._data.total_symbols,
            excerpt_token_estimate=estimate_tokens(excerpt),
            files_shown=files_shown,
            files_omitted=files_omitted,
            edges_resolved=self._graph.edges_resolved,
            edges_unresolved=self._graph.edges_unresolved,
        )

    def visualize(
        self,
        target_files: Optional[List[str]] = None,
        format: str = "dot",
        max_nodes: int = 50,
    ) -> str:
        """Export the dependency graph as DOT or Mermaid.

        target_files: highlight these files in the output.
        """
        if self._data is None:
            self.build()

        assert self._graph is not None

        # Compute ranked files for filtering
        if target_files:
            ranked = self._graph.rank_by_relevance(target_files)
            highlight: Optional[Set[str]] = set(target_files)
        else:
            ranked = self._graph.rank_by_centrality()
            highlight = None

        if format == "mermaid":
            return format_mermaid(
                self._graph, ranked_files=ranked,
                highlight_files=highlight, max_nodes=max_nodes,
            )
        else:
            return format_dot(
                self._graph, ranked_files=ranked,
                highlight_files=highlight, max_nodes=max_nodes,
            )

    def _overlay_dirty(self, data: RepoMapData, dirty: List[str]) -> None:
        """Re-extract only dirty files on top of cached data."""
        for rel_path in dirty:
            language = classify_language(rel_path)
            extractor = get_extractor(language)
            try:
                full_path = Path(self._repo_path) / rel_path
                if not full_path.exists():
                    # File was deleted
                    data.files.pop(rel_path, None)
                    continue
                source = full_path.read_text(encoding="utf-8", errors="replace")
            except (OSError, UnicodeDecodeError):
                continue
            fs = extractor.extract(source, rel_path)
            fs.language = language
            data.files[rel_path] = fs
