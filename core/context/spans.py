# core/context/spans.py — symbol-aware retrieval

"""Fetch a function, not the file it lives in.

The repo map already knows where every symbol starts and — since
``SymbolDef`` grew an ``end_line`` — where it ends.  This turns that
into the retrieval ROADMAP Phase 8 asks for: *"symbol-aware retrieval
(fetching specific function spans, not whole files)"*.

The point is context discipline.  A phase that needs to read
``Orchestrator.run`` currently has two options: paste 363 lines of
``orchestrator.py`` into the prompt, or work from the one-line signature
in the map.  Neither is the thing it wanted.

**Three refusals, and they are the design:**

* an extractor that could not determine a span reports ``end_line=0``,
  and this module *refuses* rather than reading "from the start line to
  wherever". The regex fallback genuinely cannot find the end of a
  function, and half a function delivered silently is worse than a
  clear "no span for this symbol";
* an ambiguous name is a refusal that lists the candidates. Returning
  the first ``run`` in a repository with nine of them is how a phase
  ends up reading the wrong code and being confident about it;
* a path that escapes the repository root is refused. This module is
  reached through the ``repo_map`` tool, under ``fs.read``, and the
  scope is the repository — a symbol name is not a path and must not
  become one.

Nothing here is imported by the agent loop. It is reached through
``RepoMapTool``'s ``symbol`` action, which is how everything that
touches a filesystem is reached.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from core.context.models import RepoMapData, SymbolDef

#: Hard cap on a returned span. A generated file can hold a single
#: 20,000-line function, and the point of this module is to spend less
#: context than reading the file would.
MAX_SPAN_LINES = 400


class SpanUnavailable(Exception):
    """The span was not returned, and the message says which reason."""


@dataclass(frozen=True)
class SymbolSpan:
    """One symbol's source, with the citation needed to find it again."""

    name: str
    kind: str
    rel_path: str
    start_line: int
    end_line: int
    source: str
    truncated: bool = False
    parent: str = ""

    @property
    def citation(self) -> str:
        """``path:start-end``, the form an editor and a human both take."""
        return f"{self.rel_path}:{self.start_line}-{self.end_line}"

    def render(self) -> str:
        head = f"# {self.citation}"
        if self.truncated:
            head += f"  [truncated to {MAX_SPAN_LINES} lines]"
        return f"{head}\n{self.source}"


def find_symbols(
    data: RepoMapData,
    name: str,
    *,
    file_hint: Optional[str] = None,
    parent: Optional[str] = None,
) -> List[tuple]:
    """Every ``(rel_path, SymbolDef)`` matching, in a stable order.

    ``name`` may be ``Class.method``; that is the form the repo map
    prints and therefore the form a model will echo back.
    """
    if "." in name and parent is None:
        parent, _, name = name.rpartition(".")

    matches = []
    for rel_path, file_symbols in sorted(data.files.items()):
        if file_hint and file_hint not in rel_path:
            continue
        for symbol in file_symbols.symbols:
            if symbol.name != name:
                continue
            if parent is not None and symbol.parent != parent:
                continue
            matches.append((rel_path, symbol))
    return matches


def read_span(
    repo_root: str | Path,
    rel_path: str,
    symbol: SymbolDef,
    *,
    max_lines: int = MAX_SPAN_LINES,
) -> SymbolSpan:
    """Read one symbol's lines off disk. Raises :class:`SpanUnavailable`."""
    if not symbol.has_span:
        raise SpanUnavailable(
            f"{symbol.name} in {rel_path} has no recorded end line — the "
            f"extractor for this language reports where a definition starts "
            f"and not where it ends, so the span cannot be read without "
            f"guessing at it"
        )

    root = Path(repo_root).resolve()
    target = (root / rel_path).resolve()
    if not target.is_relative_to(root):
        raise SpanUnavailable(
            f"{rel_path} resolves outside the repository root; a symbol "
            f"lookup reads the repository and nothing else"
        )
    if not target.is_file():
        raise SpanUnavailable(f"{rel_path} is not a file in this repository")

    try:
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        raise SpanUnavailable(f"{rel_path} could not be read: {exc}") from exc

    start = max(symbol.line, 1)
    end = min(symbol.end_line, len(lines))
    if start > len(lines):
        raise SpanUnavailable(
            f"{symbol.name} is recorded at {rel_path}:{start} but the file "
            f"has {len(lines)} lines — the map is stale, rebuild it"
        )

    truncated = (end - start + 1) > max_lines
    if truncated:
        end = start + max_lines - 1

    return SymbolSpan(
        name=symbol.name,
        kind=symbol.kind,
        rel_path=rel_path,
        start_line=start,
        end_line=end,
        source="\n".join(lines[start - 1:end]),
        truncated=truncated,
        parent=symbol.parent,
    )


def retrieve_symbol(
    data: RepoMapData,
    name: str,
    *,
    repo_root: Optional[str | Path] = None,
    file_hint: Optional[str] = None,
    max_lines: int = MAX_SPAN_LINES,
) -> SymbolSpan:
    """Find one symbol and read it. The whole module in one call.

    Ambiguity is a refusal listing the candidates, not a pick. A phase
    that reads the wrong ``run`` and reports on it confidently is the
    failure mode this exists to avoid, and it is invisible downstream.
    """
    matches = find_symbols(data, name, file_hint=file_hint)
    if not matches:
        where = f" in files matching {file_hint!r}" if file_hint else ""
        raise SpanUnavailable(
            f"no symbol named {name!r} is in the repository map{where}. "
            f"It may be spelled differently, or the map may predate it — "
            f"rebuild and look again."
        )
    if len(matches) > 1:
        listed = ", ".join(
            f"{path}:{sym.line}" + (f" (in {sym.parent})" if sym.parent else "")
            for path, sym in matches[:8]
        )
        raise SpanUnavailable(
            f"{name!r} is ambiguous — {len(matches)} symbols carry that name: "
            f"{listed}. Narrow it with a file hint or with Class.method."
        )

    rel_path, symbol = matches[0]
    return read_span(
        repo_root if repo_root is not None else data.repo_root,
        rel_path, symbol, max_lines=max_lines,
    )
