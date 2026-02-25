# core/context/visualize.py — DOT and Mermaid graph export

from typing import Dict, List, Optional, Set, Tuple

from core.context.graph import DependencyGraph


def _sanitize_id(path: str) -> str:
    """Convert a file path to a valid DOT/Mermaid node ID."""
    return path.replace("/", "_").replace(".", "_").replace("-", "_")


def _short_label(path: str) -> str:
    """Shorten a file path for display."""
    return path


def format_dot(
    graph: DependencyGraph,
    ranked_files: Optional[List[Tuple[str, float]]] = None,
    highlight_files: Optional[Set[str]] = None,
    max_nodes: int = 50,
) -> str:
    """Export the dependency graph as a Graphviz DOT string.

    Parameters
    ----------
    graph : DependencyGraph
        The graph to export.
    ranked_files : list of (path, score), optional
        If provided, only include the top max_nodes files by rank.
    highlight_files : set of str, optional
        Files to highlight with bold styling.
    max_nodes : int
        Maximum number of nodes to include.
    """
    highlight = highlight_files or set()

    # Determine which files to include
    if ranked_files:
        included = set()
        for path, _ in ranked_files[:max_nodes]:
            included.add(path)
    else:
        included = set(sorted(graph.files)[:max_nodes])

    lines = ["digraph repo_map {"]
    lines.append("    rankdir=LR;")
    lines.append('    node [shape=box, fontsize=10];')
    lines.append("")

    # Nodes
    for path in sorted(included):
        node_id = _sanitize_id(path)
        label = _short_label(path)
        if path in highlight:
            lines.append(f'    {node_id} [label="{label}", style=bold, color=blue];')
        else:
            lines.append(f'    {node_id} [label="{label}"];')

    lines.append("")

    # Edges
    for src, tgt in graph.edges:
        if src in included and tgt in included:
            lines.append(f"    {_sanitize_id(src)} -> {_sanitize_id(tgt)};")

    lines.append("}")
    return "\n".join(lines)


def format_mermaid(
    graph: DependencyGraph,
    ranked_files: Optional[List[Tuple[str, float]]] = None,
    highlight_files: Optional[Set[str]] = None,
    max_nodes: int = 50,
) -> str:
    """Export the dependency graph as a Mermaid diagram string.

    Parameters
    ----------
    graph : DependencyGraph
        The graph to export.
    ranked_files : list of (path, score), optional
        If provided, only include the top max_nodes files by rank.
    highlight_files : set of str, optional
        Files to highlight with styling.
    max_nodes : int
        Maximum number of nodes to include.
    """
    highlight = highlight_files or set()

    # Determine which files to include
    if ranked_files:
        included = set()
        for path, _ in ranked_files[:max_nodes]:
            included.add(path)
    else:
        included = set(sorted(graph.files)[:max_nodes])

    lines = ["graph TD"]

    # Node declarations with labels
    for path in sorted(included):
        node_id = _sanitize_id(path)
        label = _short_label(path)
        lines.append(f'    {node_id}["{label}"]')

    # Edges
    for src, tgt in graph.edges:
        if src in included and tgt in included:
            lines.append(f"    {_sanitize_id(src)} --> {_sanitize_id(tgt)}")

    # Styling for highlighted files
    if highlight & included:
        highlighted_ids = [_sanitize_id(f) for f in sorted(highlight & included)]
        lines.append(f"    style {','.join(highlighted_ids)} stroke:#00f,stroke-width:3px")

    return "\n".join(lines)
