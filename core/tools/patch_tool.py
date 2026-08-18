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
        self, *, patch_set_json: str = "", use_worktree: bool = False, **kw
    ) -> Tuple[int, str, str]:
        """Apply patches to the repository, or into a worktree if asked.

        **The default is the repository and not a worktree**, which reverses
        :meth:`core.patch.engine.PatchEngine.apply`'s own default, and the
        reason is one the kernel already wrote down (see
        ``core.kernel.roles.PatchRole``): the tests run where the repository
        is. A worktree makes the change real, on disk, and in a directory
        nothing verifies, so the verify that follows goes green — or stays
        red — against the tree the patch never touched. That is the exact
        shape of the seam ``tests/test_coding_loop_end_to_end.py`` exists to
        catch, and the kernel's one caller passes ``use_worktree=False`` by
        hand to avoid it.

        A second caller having to pass it by hand is how a default becomes a
        trap: a mission agent that omits the argument gets the silent wrong
        answer, and the transcript looks ordinary. So the safe thing is the
        default here, at the model-facing surface, and the worktree is what
        somebody asks for. The engine's default is untouched — a library
        caller that wants create/merge/discard, like
        ``core.judge.candidates``, still reaches it directly.
        """
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
