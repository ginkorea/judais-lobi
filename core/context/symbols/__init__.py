# core/context/symbols/__init__.py — Symbol extractor exports and factory

from .base import SymbolExtractor
from .python_extractor import PythonExtractor
from .generic_extractor import GenericExtractor


def get_extractor(language: str) -> SymbolExtractor:
    """Get the best available extractor for a language.

    - Python: always uses ast-based PythonExtractor
    - Other languages: tries tree-sitter, falls back to GenericExtractor
    """
    if language == "python":
        return PythonExtractor()
    try:
        from .treesitter_extractor import TreeSitterExtractor
        return TreeSitterExtractor(language)
    except (ImportError, ValueError):
        return GenericExtractor()


__all__ = [
    "SymbolExtractor",
    "PythonExtractor",
    "GenericExtractor",
    "get_extractor",
]
