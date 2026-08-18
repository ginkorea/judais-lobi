# core/tools/repo_map_tool.py — ToolBus-compatible repo map tool

from typing import List, Optional, Sequence, Tuple

from core.context.repo_map import RepoMap
from core.tools.root import MissionRoot, rooted


class RepoMapTool:
    """Multi-action tool for repo map operations.

    Actions: build, excerpt, status, visualize, symbol
    Returns (exit_code, stdout, stderr) per convention.

    `symbol` is the Phase 8 retrieval action: it returns one function or
    class body with its `path:start-end` citation, instead of the whole
    file or the one-line signature the excerpt carries. It lives here
    rather than in a new tool because it answers a question about the
    repo map, reads under the same `fs.read` scope, and a second
    filesystem tool would be a second thing to gate.
    """

    def __init__(
        self,
        repo_path: str = ".",
        subprocess_runner=None,
        token_budget: int = 4096,
        root: Optional[MissionRoot] = None,
    ) -> None:
        self._repo_map = RepoMap(
            repo_path=repo_path,
            subprocess_runner=subprocess_runner,
            token_budget=token_budget,
        )
        self._repo_path = repo_path
        self._root = root

    def __call__(self, action: str, **kwargs) -> Tuple[int, str, str]:
        handler = getattr(self, f"_do_{action}", None)
        if handler is None:
            return (1, "", f"Unknown repo_map action: {action}")
        # Read-only, and rooted anyway. A map is built against one
        # repository, but `target_files` and `file_hint` are paths the
        # MODEL writes, and "it only reads" is the same argument that left
        # `fs read` able to quote `~/.ssh/id_rsa` back into a transcript.
        for path in self._paths_in(kwargs):
            outside = rooted(self._root, path, self._repo_path)
            if outside:
                return (1, "", f"repo_map {action}: {outside}")
        try:
            return handler(**kwargs)
        except Exception as exc:
            return (1, "", f"{type(exc).__name__}: {exc}")

    @staticmethod
    def _paths_in(arguments: dict) -> Sequence[str]:
        """Every path a caller named, from whichever action named it.

        Two arguments carry one across the whole tool — ``target_files``
        for ``excerpt`` and ``visualize``, ``file_hint`` for ``symbol`` —
        and listing them once here is what keeps a third action from
        arriving with a third unchecked path.
        """
        paths: List[str] = []
        target = arguments.get("target_files") or ()
        if isinstance(target, str):
            target = [target]
        paths.extend(str(entry) for entry in target if str(entry or "").strip())
        hint = arguments.get("file_hint")
        if str(hint or "").strip():
            paths.append(str(hint))
        return paths

    def _do_build(self, *, force: bool = False, **kw) -> Tuple[int, str, str]:
        """Build or reload the repo map."""
        data = self._repo_map.build(force=force)
        return (
            0,
            f"Repo map built: {data.total_files} files, {data.total_symbols} symbols",
            "",
        )

    def _do_excerpt(
        self,
        *,
        target_files: Optional[List[str]] = None,
        **kw,
    ) -> Tuple[int, str, str]:
        """Generate a token-budgeted excerpt."""
        result = self._repo_map.excerpt_for_task(target_files=target_files)
        return (0, result.excerpt, "")

    def _do_status(self, **kw) -> Tuple[int, str, str]:
        """Report current repo map status."""
        data = self._repo_map.data
        if data is None:
            return (0, "Repo map not built yet.", "")
        return (
            0,
            (
                f"Files: {data.total_files}\n"
                f"Symbols: {data.total_symbols}\n"
                f"Commit: {data.commit_hash or 'unknown'}"
            ),
            "",
        )

    def _do_symbol(
        self,
        *,
        name: str = "",
        file_hint: Optional[str] = None,
        max_lines: int = 400,
        **kw,
    ) -> Tuple[int, str, str]:
        """Return one symbol's source span, with its citation.

        A refusal here is a normal answer with a non-zero exit code and
        a reason on stderr — "that name is ambiguous, here are the nine
        candidates" is information the caller can act on, and an
        exception would only reach it as a traceback.
        """
        from core.context.spans import SpanUnavailable, retrieve_symbol

        if not (name or "").strip():
            return (1, "", "repo_map symbol: `name` is required")

        data = self._repo_map.data
        if data is None:
            data = self._repo_map.build()

        try:
            span = retrieve_symbol(
                data, name.strip(), file_hint=file_hint, max_lines=max_lines,
            )
        except SpanUnavailable as exc:
            return (1, "", str(exc))
        return (0, span.render(), "")

    def _do_visualize(
        self,
        *,
        target_files: Optional[List[str]] = None,
        format: str = "dot",
        max_nodes: int = 50,
        **kw,
    ) -> Tuple[int, str, str]:
        """Export dependency graph as DOT or Mermaid."""
        output = self._repo_map.visualize(
            target_files=target_files,
            format=format,
            max_nodes=max_nodes,
        )
        return (0, output, "")
