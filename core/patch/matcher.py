# core/patch/matcher.py — Exact matching + similarity search narrowing pipeline

import difflib
import hashlib
import re
from typing import List, Tuple

from core.patch.models import FileMatchResult, SimilarRegion


def canonicalize(text: str) -> str:
    """Normalize \\r\\n → \\n. No other transformations."""
    return text.replace("\r\n", "\n")


def find_exact_matches(content: str, search_block: str) -> List[Tuple[int, int]]:
    """Find all exact occurrences of search_block in content.

    Returns list of (start_byte, end_byte) tuples.
    """
    if not search_block:
        return []
    offsets = []
    start = 0
    while True:
        idx = content.find(search_block, start)
        if idx == -1:
            break
        offsets.append((idx, idx + len(search_block)))
        start = idx + 1
    return offsets


def compute_context_hash(content: str, offset: int, window: int = 5) -> str:
    """SHA256 of ±window lines around the byte offset."""
    lines = content.split("\n")
    # Find which line the offset falls on
    cumulative = 0
    target_line = 0
    for i, line in enumerate(lines):
        line_end = cumulative + len(line)
        if i < len(lines) - 1:
            line_end += 1  # account for \n
        if cumulative <= offset < line_end:
            target_line = i
            break
        cumulative = line_end
    else:
        target_line = len(lines) - 1

    start_line = max(0, target_line - window)
    end_line = min(len(lines), target_line + window + 1)
    context_text = "\n".join(lines[start_line:end_line])
    return hashlib.sha256(context_text.encode("utf-8")).hexdigest()


def indent_depth(line: str) -> int:
    """Count leading whitespace as spaces (tabs = 4 spaces)."""
    count = 0
    for ch in line:
        if ch == " ":
            count += 1
        elif ch == "\t":
            count += 4
        else:
            break
    return count


def find_similar_regions(
    content: str, search_block: str, max_results: int = 3
) -> List[SimilarRegion]:
    """Narrowing pipeline: indent filter → token overlap → edit distance.

    Returns top max_results SimilarRegion objects.
    """
    if not search_block.strip():
        return []

    content_lines = content.split("\n")
    search_lines = search_block.split("\n")
    search_len = len(search_lines)

    if not content_lines or search_len == 0:
        return []

    # Target indent depth from search block's first non-empty line
    target_indent = 0
    for sl in search_lines:
        if sl.strip():
            target_indent = indent_depth(sl)
            break

    # Generate sliding windows of search_len and ±1, ±2 lines
    window_sizes = set()
    for delta in range(-2, 3):
        ws = search_len + delta
        if ws >= 1:
            window_sizes.add(ws)

    # Collect candidate windows: (line_start_0indexed, line_end_0indexed, text)
    candidates = []
    for ws in sorted(window_sizes):
        for start in range(len(content_lines) - ws + 1):
            end = start + ws
            window_lines = content_lines[start:end]
            # Find first non-empty line indent
            win_indent = 0
            for wl in window_lines:
                if wl.strip():
                    win_indent = indent_depth(wl)
                    break
            # Filter: indent matches ±1 level (4 spaces)
            if abs(win_indent - target_indent) <= 4:
                candidates.append((start, end, window_lines, win_indent))

    # Hard cap at 200 candidates (stable file order)
    candidates = candidates[:200]

    if not candidates:
        return []

    # Score by token overlap
    search_tokens = set(re.findall(r"\w+", search_block))

    scored = []
    for start, end, window_lines, win_indent in candidates:
        window_text = "\n".join(window_lines)
        window_tokens = set(re.findall(r"\w+", window_text))
        if not search_tokens:
            overlap = 0.0
        else:
            overlap = len(search_tokens & window_tokens) / len(search_tokens)
        scored.append((overlap, start, end, window_lines, win_indent, window_text))

    # Top 30 by token overlap (stable tie-break by file position)
    scored.sort(key=lambda x: (-x[0], x[1]))
    top30 = scored[:30]

    # Compute SequenceMatcher ratio on top 30
    results = []
    for overlap, start, end, window_lines, win_indent, window_text in top30:
        ratio = difflib.SequenceMatcher(None, search_block, window_text).ratio()
        results.append(SimilarRegion(
            line_start=start + 1,  # 1-indexed
            line_end=end,          # 1-indexed inclusive
            content=window_text,
            similarity=ratio,
            indent_depth=win_indent,
        ))

    # Sort by similarity descending, tie-break by line position
    results.sort(key=lambda r: (-r.similarity, r.line_start))
    return results[:max_results]


def match_file(
    content: str, search_block: str, file_path: str = "", action: str = "modify"
) -> FileMatchResult:
    """Orchestrate matching: try exact, on failure run similarity."""
    content = canonicalize(content)
    search_block = canonicalize(search_block)

    offsets = find_exact_matches(content, search_block)

    if len(offsets) == 1:
        # Exactly 1 match — success
        context_hash = compute_context_hash(content, offsets[0][0])
        return FileMatchResult(
            file_path=file_path,
            action=action,
            success=True,
            match_count=1,
            match_offsets=offsets,
            context_hashes=[context_hash],
        )
    elif len(offsets) == 0:
        # Zero matches — run similarity search
        similar = find_similar_regions(content, search_block)
        return FileMatchResult(
            file_path=file_path,
            action=action,
            success=False,
            match_count=0,
            similar_regions=similar,
            error="No exact match found",
        )
    else:
        # Multiple matches — return all offsets + hashes
        context_hashes = [
            compute_context_hash(content, off[0]) for off in offsets
        ]
        return FileMatchResult(
            file_path=file_path,
            action=action,
            success=False,
            match_count=len(offsets),
            match_offsets=offsets,
            context_hashes=context_hashes,
            error=f"Ambiguous: {len(offsets)} matches found",
        )
