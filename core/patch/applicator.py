# core/patch/applicator.py — Apply patches to files with strict preconditions

import os
import stat
from pathlib import Path
from typing import Union

from core.contracts.schemas import FilePatch
from core.patch.matcher import canonicalize, match_file
from core.patch.models import FileMatchResult


class PathJailError(Exception):
    """Raised when a file path escapes the repo root."""


def jail_path(file_path: str, repo_root: Path) -> Path:
    """Resolve file path against repo root. Reject escapes.

    Rejects:
    - Absolute paths
    - Paths with .. traversal
    - Symlink escapes (resolved path must be under repo_root)

    Returns the resolved Path.
    """
    stripped = file_path.strip()
    if not stripped:
        raise PathJailError("Empty file path")
    if stripped.startswith("/") or stripped.startswith("\\"):
        raise PathJailError(f"Absolute path rejected: {stripped}")

    # Check for .. components
    parts = stripped.replace("\\", "/").split("/")
    for part in parts:
        if part == "..":
            raise PathJailError(f"Path traversal rejected: {stripped}")

    resolved = (repo_root / stripped).resolve()
    repo_resolved = repo_root.resolve()

    # Ensure resolved path is under repo root
    try:
        resolved.relative_to(repo_resolved)
    except ValueError:
        raise PathJailError(
            f"Path escapes repo root: {stripped} resolves to {resolved}"
        )

    return resolved


def apply_modify(file_path: Path, search_block: str, replace_block: str) -> FileMatchResult:
    """Apply a modify patch: read, match, replace, write."""
    str_path = str(file_path)

    if not file_path.exists():
        return FileMatchResult(
            file_path=str_path,
            action="modify",
            success=False,
            error=f"File does not exist: {str_path}",
        )

    # Read and canonicalize
    content = file_path.read_text(encoding="utf-8", errors="replace")
    content = canonicalize(content)
    search_block = canonicalize(search_block)
    replace_block = canonicalize(replace_block)

    # Match
    result = match_file(content, search_block, file_path=str_path, action="modify")

    if not result.success:
        return result

    # Replace (exactly 1 match guaranteed)
    start, end = result.match_offsets[0]
    new_content = content[:start] + replace_block + content[end:]

    # Preserve file mode bits
    mode_bits = file_path.stat().st_mode

    file_path.write_text(new_content, encoding="utf-8")

    # Reapply mode
    os.chmod(file_path, stat.S_IMODE(mode_bits))

    return result


def apply_create(file_path: Path, content: str) -> FileMatchResult:
    """Create a new file. Fails if file already exists."""
    str_path = str(file_path)

    if file_path.exists():
        return FileMatchResult(
            file_path=str_path,
            action="create",
            success=False,
            error=f"File already exists: {str_path}",
        )

    # Create parent directories if needed
    file_path.parent.mkdir(parents=True, exist_ok=True)

    # Canonicalize line endings on write
    content = canonicalize(content)
    file_path.write_text(content, encoding="utf-8")

    return FileMatchResult(
        file_path=str_path,
        action="create",
        success=True,
        match_count=0,
    )


def apply_delete(file_path: Path) -> FileMatchResult:
    """Delete a file. Fails if file doesn't exist."""
    str_path = str(file_path)

    if not file_path.exists():
        return FileMatchResult(
            file_path=str_path,
            action="delete",
            success=False,
            error=f"File does not exist: {str_path}",
        )

    file_path.unlink()

    return FileMatchResult(
        file_path=str_path,
        action="delete",
        success=True,
        match_count=0,
    )


def apply_patch(repo_root: Union[str, Path], patch: FilePatch) -> FileMatchResult:
    """Apply a single FilePatch. Dispatches by action type.

    Validates path safety via jail_path() first.
    """
    repo_root = Path(repo_root)

    try:
        resolved = jail_path(patch.file_path, repo_root)
    except PathJailError as exc:
        return FileMatchResult(
            file_path=patch.file_path,
            action=patch.action,
            success=False,
            error=str(exc),
        )

    if patch.action == "modify":
        return apply_modify(resolved, patch.search_block, patch.replace_block)
    elif patch.action == "create":
        return apply_create(resolved, patch.replace_block)
    elif patch.action == "delete":
        return apply_delete(resolved)
    else:
        return FileMatchResult(
            file_path=patch.file_path,
            action=patch.action,
            success=False,
            error=f"Unknown action: {patch.action}",
        )
