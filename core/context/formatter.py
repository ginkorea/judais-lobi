# core/context/formatter.py — Compact tree-style formatting with token budget

from typing import List, Tuple

from core.context.models import FileSymbols, RepoMapData, SymbolDef


def estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token."""
    return len(text) // 4


def format_symbol(sym: SymbolDef) -> str:
    """Format a single symbol for display."""
    if sym.signature:
        return sym.signature
    prefix = ""
    if sym.kind == "class":
        prefix = "class "
    elif sym.kind == "constant":
        prefix = ""
    return f"{prefix}{sym.name}"


def format_file_entry(fs: FileSymbols) -> str:
    """Format a single file's symbols in compact tree style.

    Output:
        core/kernel/state.py
        | Phase(Enum): INTAKE, CONTRACT, ...
        | SessionState
        |   enter_phase(next_phase: Phase) -> None
    """
    lines = [fs.rel_path]
    # Group: top-level symbols (no parent) and their children (methods with parent)
    parents = {}  # class_name -> list of method symbols
    top_level = []

    for sym in fs.symbols:
        if sym.parent:
            parents.setdefault(sym.parent, []).append(sym)
        else:
            top_level.append(sym)

    for sym in top_level:
        lines.append(f"| {format_symbol(sym)}")
        # If it's a class, show its methods indented
        if sym.kind == "class" and sym.name in parents:
            for method in parents[sym.name]:
                lines.append(f"|   {format_symbol(method)}")

    return "\n".join(lines)


def format_excerpt(
    map_data: RepoMapData,
    ranked_files: List[Tuple[str, float]],
    token_budget: int = 4096,
) -> Tuple[str, int, int]:
    """Format a repo map excerpt within a token budget.

    Returns (excerpt_text, files_shown, files_omitted).
    """
    parts: List[str] = []
    tokens_used = 0
    files_shown = 0

    for rel_path, _score in ranked_files:
        fs = map_data.files.get(rel_path)
        if fs is None:
            continue
        entry = format_file_entry(fs)
        entry_tokens = estimate_tokens(entry)

        # Check if adding this entry would exceed budget
        # Reserve ~20 tokens for the footer
        if tokens_used + entry_tokens > token_budget - 20 and files_shown > 0:
            break

        parts.append(entry)
        tokens_used += entry_tokens
        files_shown += 1

    files_omitted = len(ranked_files) - files_shown
    if files_omitted > 0:
        parts.append(f"... and {files_omitted} more files")

    excerpt = "\n".join(parts)
    return excerpt, files_shown, files_omitted
