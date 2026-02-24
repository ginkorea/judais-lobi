# core/tools/fs_tools.py — Consolidated filesystem tool

import json
import os
import shutil
from pathlib import Path
from typing import Optional, Tuple


class FsTool:
    """Consolidated filesystem tool. Action-based dispatch.

    Each action returns (exit_code, stdout, stderr).
    Pure Python pathlib I/O — no subprocess calls.
    """

    def __call__(self, action: str, path: str, **kwargs) -> Tuple[int, str, str]:
        handler = getattr(self, f"_do_{action}", None)
        if handler is None:
            return (1, "", f"Unknown fs action: {action}")
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
