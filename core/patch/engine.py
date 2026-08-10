# core/patch/engine.py — Top-level PatchEngine orchestrator

import shlex
from pathlib import Path
from typing import List, Optional, Tuple

from core.contracts.schemas import PatchSet
from core.patch.applicator import apply_patch
from core.patch.matcher import canonicalize, match_file
from core.patch.models import FileMatchResult, PatchResult
from core.patch.worktree import PatchWorktree
from core.tools.executor import run_subprocess


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

        The returned :class:`PatchResult` carries the **diff of what was
        actually written**. ``PatchResult.diff`` has existed since the
        engine was written and nothing ever assigned it, so every caller
        that serialised a result published an empty string as though the
        change had no content. A reviewer downstream cannot tell that
        apart from a change nobody made — which is the same shape as a
        phase that succeeds having done nothing.

        The diff is taken here, in the same call that did the writing,
        rather than by a later observation of the tree. A second,
        separate ``git diff`` would report whatever the tree holds *at
        that moment*, including edits this patch set did not make; bound
        to the application it reports this patch set and nothing else.
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
            diff=self._diff_of(apply_root, patch_set),
        )

    def _diff_of(self, root: str, patch_set: PatchSet) -> str:
        """``git diff`` restricted to the paths this patch set names.

        Restricted on purpose. A bare ``git diff`` in a repository that
        was already dirty hands back somebody else's work as though this
        patch set had done it, and a reviewer asked to judge "the change"
        would be judging edits the run never made.

        A tree that is not a git checkout yields ``""``. That is the
        honest answer and it is *visible*: the review tier reports "no
        diff reached the judge" rather than reviewing a fabrication.
        """
        paths = [p.file_path for p in patch_set.patches if p.file_path]
        if not paths:
            return ""

        # A created file is untracked, and `git diff` does not see
        # untracked files at all. --intent-to-add registers it in the
        # index without content, which is exactly enough for the diff to
        # show the whole file as added.
        created = [
            p.file_path for p in patch_set.patches
            if p.action == "create" and p.file_path
        ]
        if created:
            self._git(root, "add", "--intent-to-add", "--", *created)

        rc, out, _err = self._git(root, "diff", "--", *paths)
        return out if rc == 0 else ""

    def _git(self, root: str, *args: str) -> Tuple[int, str, str]:
        parts: List[str] = ["git", *args]
        cmd = f"cd {shlex.quote(root)} && {' '.join(shlex.quote(a) for a in parts)}"
        return run_subprocess(
            cmd, shell=True, timeout=30,
            subprocess_runner=self._subprocess_runner,
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
