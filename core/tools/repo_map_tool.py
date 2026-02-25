# core/tools/repo_map_tool.py — ToolBus-compatible repo map tool

from typing import List, Optional, Tuple

from core.context.repo_map import RepoMap


class RepoMapTool:
    """Multi-action tool for repo map operations.

    Actions: build, excerpt, status, visualize
    Returns (exit_code, stdout, stderr) per convention.
    """

    def __init__(
        self,
        repo_path: str = ".",
        subprocess_runner=None,
        token_budget: int = 4096,
    ) -> None:
        self._repo_map = RepoMap(
            repo_path=repo_path,
            subprocess_runner=subprocess_runner,
            token_budget=token_budget,
        )

    def __call__(self, action: str, **kwargs) -> Tuple[int, str, str]:
        handler = getattr(self, f"_do_{action}", None)
        if handler is None:
            return (1, "", f"Unknown repo_map action: {action}")
        try:
            return handler(**kwargs)
        except Exception as exc:
            return (1, "", f"{type(exc).__name__}: {exc}")

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
