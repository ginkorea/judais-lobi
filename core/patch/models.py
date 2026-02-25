# core/patch/models.py — Internal result models for the patch engine

from dataclasses import dataclass, field
from typing import List, Tuple


@dataclass
class SimilarRegion:
    """A region of a file that is similar to a SEARCH block."""
    line_start: int          # 1-indexed
    line_end: int            # 1-indexed, inclusive
    content: str             # the actual text of the region
    similarity: float        # 0.0–1.0 (SequenceMatcher ratio)
    indent_depth: int        # spaces of first non-empty line


@dataclass
class FileMatchResult:
    """Result of matching/applying a single FilePatch."""
    file_path: str
    action: str              # "modify", "create", "delete"
    success: bool
    match_count: int = 0
    match_offsets: List[Tuple[int, int]] = field(default_factory=list)
    context_hashes: List[str] = field(default_factory=list)
    similar_regions: List[SimilarRegion] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "file_path": self.file_path,
            "action": self.action,
            "success": self.success,
            "match_count": self.match_count,
            "match_offsets": self.match_offsets,
            "context_hashes": self.context_hashes,
            "similar_regions": [
                {
                    "line_start": r.line_start,
                    "line_end": r.line_end,
                    "content": r.content,
                    "similarity": r.similarity,
                    "indent_depth": r.indent_depth,
                }
                for r in self.similar_regions
            ],
            "error": self.error,
        }


@dataclass
class PatchResult:
    """Aggregate result of applying a PatchSet."""
    success: bool
    file_results: List[FileMatchResult] = field(default_factory=list)
    worktree_path: str = ""
    diff: str = ""
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "file_results": [r.to_dict() for r in self.file_results],
            "worktree_path": self.worktree_path,
            "diff": self.diff,
            "error": self.error,
        }
