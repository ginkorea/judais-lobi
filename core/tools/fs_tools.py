# core/tools/fs_tools.py — Consolidated filesystem tool

import json
import os
import shutil
from pathlib import Path
from typing import Optional, Tuple

from core.tools.root import MissionRoot, rooted


class FsTool:
    """Consolidated filesystem tool. Action-based dispatch.

    Each action returns (exit_code, stdout, stderr).
    Pure Python pathlib I/O — no subprocess calls.

    *root* confines every action to one directory tree.  It is ``None`` in
    chat, where a person asking for a file means the file they named, and
    it is the mission's working directory on the mission path — because
    this tool is in-process and bwrap, which isolates subprocesses, never
    sees it.  See :mod:`core.tools.root`; the guard is one line here and
    the rule is stated once there.
    """

    def __init__(self, root: Optional[MissionRoot] = None):
        self._root = root

    def __call__(self, action: str, path: str, **kwargs) -> Tuple[int, str, str]:
        handler = getattr(self, f"_do_{action}", None)
        if handler is None:
            return (1, "", f"Unknown fs action: {action}")
        # Before the handler and not inside each of them: every action this
        # tool has takes a path as its first argument, and a confinement
        # written five times is a confinement with four places to forget
        # it. Resolved against the WORKING DIRECTORY, because that is what
        # the handlers below resolve a relative path against — asking the
        # question about a different base than the one the write will use
        # is how a confinement passes a path it does not confine.
        outside = rooted(self._root, path, os.getcwd())
        if outside:
            return (1, "", f"fs {action}: {outside}")
        try:
            return handler(path, **kwargs)
        except Exception as exc:
            return (1, "", f"{type(exc).__name__}: {exc}")

    def _do_read(self, path: str, **kw) -> Tuple[int, str, str]:
        """Read file contents."""
        p = Path(path)
        if not p.exists():
            return (1, "", f"File not found: {path}")
        if not p.is_file():
            return (1, "", f"Not a file: {path}")
        content = p.read_text(encoding="utf-8", errors="replace")
        return (0, content, "")

    def _do_write(self, path: str, *, content: str = "", **kw) -> Tuple[int, str, str]:
        """Write content to a file. Creates parent directories if needed."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return (0, f"Written {len(content)} bytes to {path}", "")

    def _do_delete(self, path: str, **kw) -> Tuple[int, str, str]:
        """Delete a file or directory tree."""
        p = Path(path)
        if not p.exists():
            return (1, "", f"Path not found: {path}")
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink()
        return (0, f"Deleted: {path}", "")

    def _do_list(self, path: str, *, recursive: bool = False, **kw) -> Tuple[int, str, str]:
        """List directory contents."""
        p = Path(path)
        if not p.exists():
            return (1, "", f"Directory not found: {path}")
        if not p.is_dir():
            return (1, "", f"Not a directory: {path}")
        if recursive:
            entries = sorted(str(e.relative_to(p)) for e in p.rglob("*"))
        else:
            entries = sorted(e.name for e in p.iterdir())
        return (0, "\n".join(entries), "")

    def _do_stat(self, path: str, **kw) -> Tuple[int, str, str]:
        """Return stat info as JSON."""
        p = Path(path)
        if not p.exists():
            return (1, "", f"Path not found: {path}")
        st = p.stat()
        info = {
            "path": str(p),
            "size": st.st_size,
            "mtime": st.st_mtime,
            "is_file": p.is_file(),
            "is_dir": p.is_dir(),
            "mode": oct(st.st_mode),
        }
        return (0, json.dumps(info), "")
