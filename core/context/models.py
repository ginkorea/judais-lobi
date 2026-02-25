# core/context/models.py — Data models for repo map extraction

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Pure dataclasses for internal extraction pipeline
# ---------------------------------------------------------------------------

@dataclass
class SymbolDef:
    """A single extracted symbol (function, class, constant)."""
    name: str
    kind: str  # "function", "class", "method", "constant"
    signature: str = ""
    parent: str = ""  # enclosing class name for methods
    decorators: List[str] = field(default_factory=list)
    line: int = 0


@dataclass
class ImportEdge:
    """A single import statement resolved to a module path."""
    module: str  # e.g. "core.kernel.state" or "os.path"
    names: List[str] = field(default_factory=list)  # e.g. ["Phase", "SessionState"]
    is_relative: bool = False


@dataclass
class FileSymbols:
    """Extraction results for a single file."""
    rel_path: str
    language: str = ""
    symbols: List[SymbolDef] = field(default_factory=list)
    imports: List[ImportEdge] = field(default_factory=list)


@dataclass
class RepoMapData:
    """Full repo map: all files with their symbols and imports.

    This is the cacheable artifact produced by a full extraction pass.
    """
    repo_root: str
    files: Dict[str, FileSymbols] = field(default_factory=dict)  # rel_path -> FileSymbols
    commit_hash: str = ""

    @property
    def total_files(self) -> int:
        return len(self.files)

    @property
    def total_symbols(self) -> int:
        return sum(len(fs.symbols) for fs in self.files.values())


# ---------------------------------------------------------------------------
# Pydantic model for phase artifact storage
# ---------------------------------------------------------------------------

class RepoMapResult(BaseModel):
    """Result artifact for the REPO_MAP phase and RETRIEVE context."""
    excerpt: str = ""
    total_files: int = 0
    total_symbols: int = 0
    excerpt_token_estimate: int = 0
    files_shown: int = 0
    files_omitted: int = 0
    edges_resolved: int = 0
    edges_unresolved: int = 0
