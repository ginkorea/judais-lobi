# core/context/symbols/base.py — SymbolExtractor protocol

from typing import Protocol, runtime_checkable

from core.context.models import FileSymbols


@runtime_checkable
class SymbolExtractor(Protocol):
    """Protocol for source code symbol extractors.

    Each extractor takes raw source text and a relative file path,
    returning a FileSymbols with extracted symbols and imports.
    """

    def extract(self, source: str, rel_path: str) -> FileSymbols:
        ...
