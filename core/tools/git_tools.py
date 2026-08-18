# core/tools/git_tools.py — Consolidated git tool

import os
import shlex
from typing import List, Optional, Tuple

from core.tools.executor import run_subprocess
from core.tools.root import MissionRoot, rooted


class GitTool:
    """Consolidated git tool. Action-based dispatch via run_subprocess.

    Every action returns (exit_code, stdout, stderr).
    repo_path sets the working directory for the git command.

    *root* confines **which repository** this tool operates on: with one
    set, a ``repo_path`` outside the mission's root is refused.  It does
    not confine the paths inside that repository — git does, and a
    ``git add`` of something outside the work tree is git's own refusal
    rather than a rule this harness has to restate.  See
    :mod:`core.tools.root`; ``None`` is chat's behaviour and the default.
    """

    def __init__(self, subprocess_runner=None,
                 root: Optional[MissionRoot] = None):
        self._subprocess_runner = subprocess_runner
        self._root = root

    def __call__(self, action: str, **kwargs) -> Tuple[int, str, str]:
        handler = getattr(self, f"_do_{action}", None)
        if handler is None:
            return (1, "", f"Unknown git action: {action}")
        # `repo_path` is the one path a model writes to this tool, and
        # every action takes it by that name — so the guard is here rather
        # than in fourteen handlers. An action that names none runs where
        # the process is, which under a mission IS the root.
        outside = rooted(self._root, kwargs.get("repo_path"), os.getcwd())
        if outside:
            return (1, "", f"git {action}: {outside}")
        try:
            return handler(**kwargs)
        except Exception as exc:
            return (1, "", f"{type(exc).__name__}: {exc}")

    def _run(self, cmd: str, repo_path: Optional[str] = None,
             timeout: int = 30) -> Tuple[int, str, str]:
        """Run a git command. Prepends 'cd <repo_path> &&' if given."""
        if repo_path:
            cmd = f"cd {shlex.quote(str(repo_path))} && {cmd}"
        return run_subprocess(
            cmd, shell=True, timeout=timeout,
            subprocess_runner=self._subprocess_runner,
        )

    # --- Read actions ---

    def _do_status(self, *, repo_path=None) -> Tuple[int, str, str]:
        return self._run("git status --porcelain", repo_path=repo_path)

    def _do_diff(self, *, staged: bool = False, path_spec: Optional[str] = None,
                 repo_path=None) -> Tuple[int, str, str]:
        cmd = "git diff"
        if staged:
            cmd += " --cached"
        if path_spec:
            cmd += f" -- {shlex.quote(path_spec)}"
        return self._run(cmd, repo_path=repo_path)

    def _do_log(self, *, n: int = 10, oneline: bool = True,
                repo_path=None) -> Tuple[int, str, str]:
        cmd = f"git log -n {int(n)}"
        if oneline:
            cmd += " --oneline"
        return self._run(cmd, repo_path=repo_path)

    # --- Write actions ---

    def _do_add(self, *, paths: Optional[List[str]] = None,
                repo_path=None) -> Tuple[int, str, str]:
        if paths:
            quoted = " ".join(shlex.quote(p) for p in paths)
            cmd = f"git add {quoted}"
        else:
            cmd = "git add -A"
        return self._run(cmd, repo_path=repo_path)

    def _do_commit(self, *, message: str, repo_path=None) -> Tuple[int, str, str]:
        cmd = f"git commit -m {shlex.quote(message)}"
        return self._run(cmd, repo_path=repo_path)

    def _do_branch(self, *, name: Optional[str] = None, delete: bool = False,
                   repo_path=None) -> Tuple[int, str, str]:
        if name is None:
            cmd = "git branch"
        elif delete:
            cmd = f"git branch -d {shlex.quote(name)}"
        else:
            cmd = f"git branch {shlex.quote(name)}"
        return self._run(cmd, repo_path=repo_path)

    def _do_stash(self, *, sub_action: str = "push", message: Optional[str] = None,
                  repo_path=None) -> Tuple[int, str, str]:
        if sub_action == "push":
            cmd = "git stash push"
            if message:
                cmd += f" -m {shlex.quote(message)}"
        elif sub_action == "pop":
            cmd = "git stash pop"
        elif sub_action == "list":
            cmd = "git stash list"
        else:
            return (1, "", f"Unknown stash sub-action: {sub_action}")
        return self._run(cmd, repo_path=repo_path)

    def _do_tag(self, *, name: Optional[str] = None, message: Optional[str] = None,
                list_tags: bool = False, repo_path=None) -> Tuple[int, str, str]:
        if list_tags or name is None:
            cmd = "git tag"
        elif message:
            cmd = f"git tag -a {shlex.quote(name)} -m {shlex.quote(message)}"
        else:
            cmd = f"git tag {shlex.quote(name)}"
        return self._run(cmd, repo_path=repo_path)

    def _do_reset(self, *, mode: str = "mixed", ref: str = "HEAD",
                  repo_path=None) -> Tuple[int, str, str]:
        if mode not in ("soft", "mixed", "hard"):
            return (1, "", f"Invalid reset mode: {mode}")
        cmd = f"git reset --{mode} {shlex.quote(ref)}"
        return self._run(cmd, repo_path=repo_path)

    # --- Network actions ---

    def _do_push(self, *, remote: str = "origin", branch: Optional[str] = None,
                 repo_path=None) -> Tuple[int, str, str]:
        cmd = f"git push {shlex.quote(remote)}"
        if branch:
            cmd += f" {shlex.quote(branch)}"
        return self._run(cmd, repo_path=repo_path)

    def _do_pull(self, *, remote: str = "origin", branch: Optional[str] = None,
                 repo_path=None) -> Tuple[int, str, str]:
        cmd = f"git pull {shlex.quote(remote)}"
        if branch:
            cmd += f" {shlex.quote(branch)}"
        return self._run(cmd, repo_path=repo_path)

    def _do_fetch(self, *, remote: str = "origin",
                  repo_path=None) -> Tuple[int, str, str]:
        cmd = f"git fetch {shlex.quote(remote)}"
        return self._run(cmd, repo_path=repo_path)
