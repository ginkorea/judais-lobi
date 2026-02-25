# core/patch/engine.py — Top-level PatchEngine orchestrator

from pathlib import Path
from typing import Optional, Tuple

from core.contracts.schemas import PatchSet
from core.patch.applicator import apply_patch
from core.patch.matcher import canonicalize, match_file
from core.patch.models import FileMatchResult, PatchResult
from core.patch.worktree import PatchWorktree


class PatchEngine:
    """Orchestrates patch validation, application, and worktree lifecycle.

    Stateful: tracks the active worktree. State survives process restart
    via PatchWorktree's active.json file.
    """

    def __init__(self, repo_path: str, subprocess_runner=None):
        self._repo_path = repo_path
        self._subprocess_runner = subprocess_runner
        self._worktree = PatchWorktree(repo_path, subprocess_runner)

    def validate(self, patch_set: PatchSet) -> PatchResult:
        """Dry-run: match all patches without writing.

        For modify patches, reads file and checks for exact match.
        For create patches, checks file doesn't exist.
        For delete patches, checks file exists.
        """
        file_results = []
        all_success = True

        for patch in patch_set.patches:
            if patch.action == "modify":
                file_path = Path(self._repo_path) / patch.file_path
                if not file_path.exists():
                    result = FileMatchResult(
                        file_path=patch.file_path,
                        action="modify",
                        success=False,
                        error=f"File does not exist: {patch.file_path}",
                    )
                else:
                    content = file_path.read_text(
                        encoding="utf-8", errors="replace"
                    )
                    content = canonicalize(content)
                    result = match_file(
                        content, patch.search_block,
                        file_path=patch.file_path, action="modify",
                    )
            elif patch.action == "create":
                file_path = Path(self._repo_path) / patch.file_path
                if file_path.exists():
                    result = FileMatchResult(
                        file_path=patch.file_path,
                        action="create",
                        success=False,
                        error=f"File already exists: {patch.file_path}",
                    )
                else:
                    result = FileMatchResult(
                        file_path=patch.file_path,
                        action="create",
                        success=True,
                    )
            elif patch.action == "delete":
                file_path = Path(self._repo_path) / patch.file_path
                if not file_path.exists():
                    result = FileMatchResult(
                        file_path=patch.file_path,
                        action="delete",
                        success=False,
                        error=f"File does not exist: {patch.file_path}",
                    )
                else:
                    result = FileMatchResult(
                        file_path=patch.file_path,
                        action="delete",
                        success=True,
                    )
            else:
                result = FileMatchResult(
                    file_path=patch.file_path,
                    action=patch.action,
                    success=False,
                    error=f"Unknown action: {patch.action}",
                )

            if not result.success:
                all_success = False
            file_results.append(result)

        return PatchResult(success=all_success, file_results=file_results)

    def apply(
        self, patch_set: PatchSet, use_worktree: bool = True
    ) -> PatchResult:
        """Apply all patches. Optionally in a git worktree.

        On any file failure: stop, leave worktree intact for diagnostics.
        """
        worktree_path = ""

        if use_worktree:
            worktree_path = self._worktree.create()
            apply_root = worktree_path
        else:
            apply_root = self._repo_path

        file_results = []
        all_success = True

        for patch in patch_set.patches:
            result = apply_patch(apply_root, patch)
            file_results.append(result)
            if not result.success:
                all_success = False
                break  # Stop at first failure

        return PatchResult(
            success=all_success,
            file_results=file_results,
            worktree_path=worktree_path,
        )

    def diff(self) -> str:
        """Return real git diff from the active worktree."""
        rc, out, err = self._worktree.diff()
        if rc != 0:
            return f"diff failed: {err}"
        return out

    def merge(self, message: str = "") -> Tuple[int, str, str]:
        """Merge the active worktree branch back."""
        return self._worktree.merge_back(message=message)

    def rollback(self) -> None:
        """Discard the active worktree."""
        self._worktree.discard()

    def status(self) -> dict:
        """Report engine state."""
        return {
            "worktree_active": self._worktree.active,
            "worktree_path": self._worktree.path or "",
            "worktree_branch": self._worktree.branch or "",
            "repo_path": self._repo_path,
        }
