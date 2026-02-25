# core/context/formatter.py — Compact tree-style formatting with token budget

import re
from typing import List, Optional, Tuple

from core.context.models import FileSymbols, RepoMapData, SymbolDef


def estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token."""
    return len(text) // 4


def _normalize_whitespace(text: str) -> str:
    """Collapse runs of spaces/tabs within a line to single spaces.

    Preserves leading indentation structure (| and |   prefixes)
    but normalizes whitespace inside signatures for deterministic output.
    """
    lines = text.split("\n")
    result = []
    for line in lines:
        # Preserve the tree prefix (| or |   ) then normalize the rest
        if line.startswith("|   "):
            prefix = "|   "
            body = line[4:]
        elif line.startswith("| "):
            prefix = "| "
            body = line[2:]
        else:
            # File path header or footer — normalize fully
            result.append(" ".join(line.split()))
            continue
        body = " ".join(body.split())
        result.append(prefix + body)
    return "\n".join(result)


def format_symbol(sym: SymbolDef) -> str:
    """Format a single symbol for display."""
    if sym.signature:
        # Normalize internal whitespace for deterministic output
        return " ".join(sym.signature.split())
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
    char_budget: Optional[int] = None,
    header: str = "",
) -> Tuple[str, int, int]:
    """Format a repo map excerpt within a token budget.

    Args:
        map_data: The full repo map data.
        ranked_files: List of (rel_path, score) in priority order.
        token_budget: Maximum estimated tokens for the excerpt body.
        char_budget: Optional hard character limit. When set, output is
            also capped at this many characters (regardless of token estimate).
        header: Optional metadata header prepended to the excerpt.
            Header chars/tokens count toward the budgets.

    Returns (excerpt_text, files_shown, files_omitted).
    """
    parts: List[str] = []
    tokens_used = 0
    chars_used = 0
    files_shown = 0

    # Account for header in budgets
    if header:
        parts.append(header)
        tokens_used += estimate_tokens(header)
        chars_used += len(header) + 1  # +1 for joining newline

    for rel_path, _score in ranked_files:
        fs = map_data.files.get(rel_path)
        if fs is None:
            continue
        entry = format_file_entry(fs)
        entry_tokens = estimate_tokens(entry)
        entry_chars = len(entry) + 1  # +1 for joining newline

        # Check token budget (reserve ~20 tokens for footer)
        if tokens_used + entry_tokens > token_budget - 20 and files_shown > 0:
            break

        # Check char budget
        if char_budget is not None:
            if chars_used + entry_chars > char_budget - 80 and files_shown > 0:
                break

        parts.append(entry)
        tokens_used += entry_tokens
        chars_used += entry_chars
        files_shown += 1

    files_omitted = len(ranked_files) - files_shown
    if files_omitted > 0:
        parts.append(f"... and {files_omitted} more files")

    excerpt = "\n".join(parts)
    return excerpt, files_shown, files_omitted
