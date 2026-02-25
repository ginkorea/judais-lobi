# core/patch/worktree.py — Git worktree lifecycle management

import json
import shlex
import uuid
from pathlib import Path
from typing import Optional, Tuple

from core.tools.executor import run_subprocess


class PatchWorktree:
    """Manages a git worktree for atomic patch application.

    One worktree per PatchSet. Cross-file changes land together.
    State persisted via .judais-lobi/worktrees/active.json for crash recovery.
    """

    def __init__(self, repo_path: str, subprocess_runner=None):
        self._repo_path = repo_path
        self._subprocess_runner = subprocess_runner
        self._worktree_path: Optional[str] = None
        self._branch_name: Optional[str] = None
        # Attempt state recovery from disk
        self._recover_state()

    def _state_file(self) -> Path:
        return Path(self._repo_path) / ".judais-lobi" / "worktrees" / "active.json"

    def _recover_state(self) -> None:
        """Recover worktree state from active.json if it exists."""
        state_file = self._state_file()
        if state_file.exists():
            try:
                data = json.loads(state_file.read_text(encoding="utf-8"))
                self._worktree_path = data.get("worktree_path")
                self._branch_name = data.get("branch_name")
            except (json.JSONDecodeError, OSError):
                pass

    def _write_state(self) -> None:
        """Persist worktree state to active.json."""
        state_file = self._state_file()
        state_file.parent.mkdir(parents=True, exist_ok=True)
        import datetime
        data = {
            "worktree_path": self._worktree_path,
            "branch_name": self._branch_name,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        state_file.write_text(json.dumps(data), encoding="utf-8")

    def _delete_state(self) -> None:
        """Remove active.json."""
        state_file = self._state_file()
        if state_file.exists():
            state_file.unlink()

    def _run(self, cmd: str, cwd: Optional[str] = None,
             timeout: int = 30) -> Tuple[int, str, str]:
        """Run a git command via run_subprocess."""
        if cwd:
            cmd = f"cd {shlex.quote(cwd)} && {cmd}"
        return run_subprocess(
            cmd, shell=True, timeout=timeout,
            subprocess_runner=self._subprocess_runner,
        )

    def create(self, name: str = None) -> str:
        """Create a new git worktree for patch application.

        Returns the worktree path.
        """
        if self._worktree_path:
            raise RuntimeError("Worktree already active; discard or merge first")

        if name is None:
            name = uuid.uuid4().hex[:12]

        branch_name = f"patch-{name}"
        wt_dir = Path(self._repo_path) / ".judais-lobi" / "worktrees" / name
        wt_path = str(wt_dir)

        # Ensure parent directory exists
        wt_dir.parent.mkdir(parents=True, exist_ok=True)

        rc, out, err = self._run(
            f"git worktree add -b {shlex.quote(branch_name)} "
            f"{shlex.quote(wt_path)} HEAD",
            cwd=self._repo_path,
        )
        if rc != 0:
            raise RuntimeError(f"git worktree add failed: {err}")

        self._worktree_path = wt_path
        self._branch_name = branch_name
        self._write_state()

        return wt_path

    def discard(self) -> Tuple[int, str, str]:
        """Discard the active worktree and delete its branch."""
        if not self._worktree_path:
            return (0, "", "No active worktree")

        wt_path = self._worktree_path
        branch = self._branch_name

        # Remove worktree
        rc, out, err = self._run(
            f"git worktree remove {shlex.quote(wt_path)} --force",
            cwd=self._repo_path,
        )

        # Delete branch (ignore failure if already gone)
        if branch:
            self._run(
                f"git branch -D {shlex.quote(branch)}",
                cwd=self._repo_path,
            )

        self._worktree_path = None
        self._branch_name = None
        self._delete_state()

        return (rc, out, err)

    def merge_back(self, message: str = "") -> Tuple[int, str, str]:
        """Merge the worktree branch back into the current branch."""
        if not self._worktree_path:
            raise RuntimeError("No active worktree to merge")

        branch = self._branch_name
        wt_path = self._worktree_path

        if not message:
            message = f"Merge {branch}"

        # Merge from repo root
        rc, out, err = self._run(
            f"git merge --no-ff {shlex.quote(branch)} "
            f"-m {shlex.quote(message)}",
            cwd=self._repo_path,
        )

        if rc != 0:
            return (rc, out, err)

        # Cleanup: remove worktree and branch
        self._run(
            f"git worktree remove {shlex.quote(wt_path)}",
            cwd=self._repo_path,
        )
        self._run(
            f"git branch -D {shlex.quote(branch)}",
            cwd=self._repo_path,
        )

        self._worktree_path = None
        self._branch_name = None
        self._delete_state()

        return (rc, out, err)

    def diff(self) -> Tuple[int, str, str]:
        """Run git diff inside the worktree (real git diff, ground truth)."""
        if not self._worktree_path:
            return (1, "", "No active worktree")

        return self._run("git diff", cwd=self._worktree_path)

    @property
    def active(self) -> bool:
        """True if a worktree is currently active."""
        return self._worktree_path is not None

    @property
    def path(self) -> Optional[str]:
        """Current worktree path."""
        return self._worktree_path

    @property
    def branch(self) -> Optional[str]:
        """Current worktree branch name."""
        return self._branch_name
