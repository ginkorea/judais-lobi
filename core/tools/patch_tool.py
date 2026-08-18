# core/tools/patch_tool.py — ToolBus-compatible multi-action patch tool

import json
from typing import Optional, Tuple

from core.contracts.schemas import PatchSet
from core.patch.engine import PatchEngine
from core.tools.root import MissionRoot, rooted


class PatchTool:
    """Patch engine tool. Action-based dispatch.

    Actions: validate, apply, diff, merge, rollback, status.
    All actions return (exit_code, stdout, stderr).
    JSON stdout for machine-friendly kernel orchestration.
    exit_code=0 only on success.

    *root* confines every ``file_path`` in a patch set to one directory
    tree, for the reason :mod:`core.tools.root` states: the engine writes
    in this process, so the sandbox never sees it.  ``None`` — the default
    — is the unconfined behaviour every existing caller has.

    It is not the only guard and does not replace one:
    :func:`core.patch.applicator.jail_path` already refuses an absolute
    path, a ``..`` component and a symlink escape.  It refuses them
    against ``repo_path`` — the directory this tool was *constructed*
    with — and in the engine's words, at the bottom of a JSON result.
    The root is the **mission's** answer to the same question: checked
    before the engine is reached, and the one that bites when the two
    directories are not the same.

    Checked **here** and not in :class:`~core.patch.engine.PatchEngine`:
    the engine is a library that a judge, a kernel role and this tool all
    reach directly with paths their own callers chose, and a root is a
    property of a *mission*, not of applying a patch.  This is the
    model-facing surface — the same argument that put ``use_worktree``'s
    safe default here rather than in the engine.
    """

    def __init__(self, repo_path: str = ".", subprocess_runner=None,
                 root: Optional[MissionRoot] = None):
        self._engine = PatchEngine(repo_path, subprocess_runner)
        self._repo_path = repo_path
        self._root = root

    def _outside_root(self, patch_set: PatchSet) -> str:
        """The refusal for the first file outside the root, or ``""``.

        Every patch is checked before any is applied: a patch set is one
        call because a half-applied change is a repository nobody asked
        for, and refusing it halfway through would be exactly that.
        """
        for patch in patch_set.patches:
            outside = rooted(self._root, getattr(patch, "file_path", ""),
                             self._repo_path)
            if outside:
                return f"patch: {outside}"
        return ""

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
        outside = self._outside_root(patch_set)
        if outside:
            return (1, "", outside)
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
        outside = self._outside_root(patch_set)
        if outside:
            return (1, "", outside)
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
