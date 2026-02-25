# core/tools/patch_tool.py — ToolBus-compatible multi-action patch tool

import json
from typing import Tuple

from core.contracts.schemas import PatchSet
from core.patch.engine import PatchEngine


class PatchTool:
    """Patch engine tool. Action-based dispatch.

    Actions: validate, apply, diff, merge, rollback, status.
    All actions return (exit_code, stdout, stderr).
    JSON stdout for machine-friendly kernel orchestration.
    exit_code=0 only on success.
    """

    def __init__(self, repo_path: str = ".", subprocess_runner=None):
        self._engine = PatchEngine(repo_path, subprocess_runner)

    def __call__(self, action: str, **kwargs) -> Tuple[int, str, str]:
        handler = getattr(self, f"_do_{action}", None)
        if handler is None:
            return (1, "", f"Unknown patch action: {action}")
        try:
            return handler(**kwargs)
        except Exception as exc:
            return (1, "", f"{type(exc).__name__}: {exc}")

    def _parse_patch_set(self, patch_set_json: str) -> PatchSet:
        """Parse JSON string into PatchSet."""
        data = json.loads(patch_set_json)
        return PatchSet(**data)

    def _do_validate(self, *, patch_set_json: str = "", **kw) -> Tuple[int, str, str]:
        """Dry-run match check."""
        patch_set = self._parse_patch_set(patch_set_json)
        result = self._engine.validate(patch_set)
        stdout = json.dumps(result.to_dict())
        return (0 if result.success else 1, stdout, "")

    def _do_apply(
        self, *, patch_set_json: str = "", use_worktree: bool = True, **kw
    ) -> Tuple[int, str, str]:
        """Apply patches, optionally in a worktree."""
        patch_set = self._parse_patch_set(patch_set_json)
        result = self._engine.apply(patch_set, use_worktree=use_worktree)
        stdout = json.dumps(result.to_dict())
        return (0 if result.success else 1, stdout, "")

    def _do_diff(self, **kw) -> Tuple[int, str, str]:
        """Return real git diff from active worktree."""
        diff_text = self._engine.diff()
        if diff_text.startswith("diff failed:"):
            return (1, "", diff_text)
        return (0, diff_text, "")

    def _do_merge(self, *, message: str = "", **kw) -> Tuple[int, str, str]:
        """Merge active worktree back."""
        rc, out, err = self._engine.merge(message=message)
        status = json.dumps({"merged": rc == 0, "output": out})
        return (rc, status, err)

    def _do_rollback(self, **kw) -> Tuple[int, str, str]:
        """Discard active worktree."""
        self._engine.rollback()
        status = json.dumps({"rolled_back": True})
        return (0, status, "")

    def _do_status(self, **kw) -> Tuple[int, str, str]:
        """Report engine state."""
        info = self._engine.status()
        return (0, json.dumps(info), "")
