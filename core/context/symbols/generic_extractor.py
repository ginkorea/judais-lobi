# core/context/symbols/generic_extractor.py — Regex-based fallback extractor

import re
from typing import List, Tuple

from core.context.models import FileSymbols, SymbolDef


# Patterns: (regex, kind) — first group captures the symbol name
_PATTERNS: List[Tuple[re.Pattern, str]] = [
    # JavaScript/TypeScript: class X
    (re.compile(r"^\s*(?:export\s+)?(?:abstract\s+)?class\s+(\w+)", re.MULTILINE), "class"),
    # JavaScript/TypeScript: function X(
    (re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(", re.MULTILINE), "function"),
    # Go: func X(
    (re.compile(r"^func\s+(\w+)\s*\(", re.MULTILINE), "function"),
    # Go: func (r *Receiver) X(
    (re.compile(r"^func\s+\([^)]+\)\s+(\w+)\s*\(", re.MULTILINE), "method"),
    # Rust: pub fn X(
    (re.compile(r"^\s*(?:pub\s+)?(?:async\s+)?fn\s+(\w+)", re.MULTILINE), "function"),
    # Rust: struct X / trait X / impl X / enum X
    (re.compile(r"^\s*(?:pub\s+)?(?:struct|trait|enum)\s+(\w+)", re.MULTILINE), "class"),
    # C/C++: return_type function_name(
    (re.compile(r"^(?:[\w:*&<>]+\s+)+(\w+)\s*\([^;]*$", re.MULTILINE), "function"),
    # Java: public class X
    (re.compile(r"^\s*(?:public|private|protected)?\s*(?:static\s+)?(?:final\s+)?class\s+(\w+)", re.MULTILINE), "class"),
    # Java: method declarations
    (re.compile(r"^\s*(?:public|private|protected)\s+(?:static\s+)?[\w<>\[\]]+\s+(\w+)\s*\(", re.MULTILINE), "method"),
]


class GenericExtractor:
    """Regex-based symbol extractor for non-Python languages.

    Provides basic function/class detection. No import extraction.
    """

    def extract(self, source: str, rel_path: str) -> FileSymbols:
        """Extract symbols using regex patterns."""
        seen: set = set()
        symbols: List[SymbolDef] = []

        for pattern, kind in _PATTERNS:
            for match in pattern.finditer(source):
                name = match.group(1)
                # Deduplicate by (name, kind)
                key = (name, kind)
                if key in seen:
                    continue
                seen.add(key)
                # Compute line number
                line = source[:match.start()].count("\n") + 1
                symbols.append(SymbolDef(
                    name=name,
                    kind=kind,
                    line=line,
                ))

        # Sort by line number
        symbols.sort(key=lambda s: s.line)
        return FileSymbols(rel_path=rel_path, symbols=symbols)
