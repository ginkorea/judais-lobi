"""Read an unchanged native checkpoint closure without executing or restoring it.

The caller must exclude new conversation workers for the entire call. Existing
run locks are held non-blockingly as an additional check, not a replacement for
that admission barrier. No lock, directory, metadata or receipt is created.
Enrolled parent directories and the service account remain trusted.
"""

from __future__ import annotations

from contextlib import ExitStack
import os
from pathlib import Path
import stat
from typing import Sequence

from core import durable
from core.runtime import history_checkpoint
from core.runtime.portable_checkpoint import (
    CheckpointLimits, PortableCheckpoint, PortableCheckpointValidator, REFUSED,
)
from core.runtime.task_state import TaskCheckpoint, TaskHandoff, TaskScope, decode_task_state


def _identity(value: os.stat_result) -> tuple[int, ...]:
    return (value.st_dev, value.st_ino, value.st_mode, value.st_uid,
            value.st_nlink, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def _root_identity(value: os.stat_result) -> tuple[int, ...]:
    # Unrelated conversations may add runs while this conversation is idle.
    # Pin the root incarnation and security, not its membership timestamps.
    return value.st_dev, value.st_ino, value.st_mode, value.st_uid, value.st_gid


class NativeCheckpointCapture:
    """Source-owned filesystem adapter for the detached checkpoint validator.

    Selects only runs reachable from the supplied scope-bound handoffs. Unknown
    files in a selected run refuse capture instead of silently losing work.
    Native run locks are deliberately excluded from the portable parts.
    """

    def __init__(self, root: Path, limits: CheckpointLimits | None = None) -> None:
        self.root = Path(root).absolute()
        self.limits = limits if limits is not None else CheckpointLimits()

    def capture(self, scope: TaskScope, handoffs: Sequence[TaskHandoff]) -> PortableCheckpoint:
        try:
            if not handoffs or len(handoffs) > self.limits.max_files:
                raise ValueError(REFUSED)
            pointers = tuple(TaskHandoff.from_record(item.as_record()) for item in handoffs)
            if any(item.scope != scope for item in pointers):
                raise ValueError(REFUSED)
            with ExitStack() as stack:
                reader = _NativeRead(self.root, self.limits, stack)
                files = reader.closure(scope, pointers)
                result = PortableCheckpointValidator(self.limits).validate(scope, pointers, files)
                reader.verify()
                return result
        except (OSError, ValueError, TypeError, AttributeError, KeyError, RecursionError):
            raise ValueError(REFUSED) from None


class _NativeRead:
    def __init__(self, root: Path, limits: CheckpointLimits, stack: ExitStack) -> None:
        if durable.fcntl is None:
            raise ValueError(REFUSED)
        self.root, self.limits, self.stack = root, limits, stack
        self.entries: list[tuple[int, str, tuple[int, ...]]] = []
        self.directories: list[tuple[int, tuple[int, ...]]] = []
        self.used_bytes = 0
        self.files: dict[str, bytes] = {}
        self.root_fd = self._directory(str(root))
        self.root_identity = _root_identity(os.fstat(self.root_fd))

    @staticmethod
    def _safe(value: os.stat_result, *, directory: bool) -> None:
        matches = stat.S_ISDIR(value.st_mode) if directory else stat.S_ISREG(value.st_mode)
        if (not matches or value.st_uid != os.geteuid() or value.st_mode & 0o022
                or (not directory and value.st_nlink != 1)):
            raise ValueError(REFUSED)

    def _directory(self, name: str, parent: int | None = None) -> int:
        fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        self.stack.callback(os.close, fd)
        observed = os.fstat(fd)
        self._safe(observed, directory=True)
        identity = _identity(observed)
        if parent is not None:
            self.directories.append((fd, identity))
            self.entries.append((parent, name, identity))
        return fd

    def _names(self, fd: int) -> set[str]:
        names: set[str] = set()
        with os.scandir(fd) as entries:
            for entry in entries:
                names.add(entry.name)
                if len(names) > self.limits.max_files + 3:
                    raise ValueError(REFUSED)
        return names

    def _read(self, parent: int, name: str, key: str) -> bytes:
        if len(self.files) >= self.limits.max_files:
            raise ValueError(REFUSED)
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        try:
            before = os.fstat(fd)
            self._safe(before, directory=False)
            remaining = self.limits.max_bytes - self.used_bytes
            if before.st_size > remaining:
                raise ValueError(REFUSED)
            chunks: list[bytes] = []
            bound = remaining + 1
            while bound:
                chunk = os.read(fd, min(bound, 1024 * 1024))
                if not chunk:
                    break
                chunks.append(chunk)
                bound -= len(chunk)
            raw = b"".join(chunks)
            if len(raw) > remaining or _identity(before) != _identity(os.fstat(fd)):
                raise ValueError(REFUSED)
            self.entries.append((parent, name, _identity(before)))
            self.used_bytes += len(raw)
            self.files[key] = raw
            return raw
        finally:
            os.close(fd)

    def _hold(self, parent: int) -> None:
        fd = os.open(durable.LOCK_FILENAME, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                     dir_fd=parent)
        self.stack.callback(os.close, fd)
        before = os.fstat(fd)
        self._safe(before, directory=False)
        if durable.fcntl is None:
            raise ValueError(REFUSED)
        durable.fcntl.flock(fd, durable.fcntl.LOCK_EX | durable.fcntl.LOCK_NB)
        self.entries.append((parent, durable.LOCK_FILENAME, _identity(before)))

    def closure(self, scope: TaskScope, pointers: tuple[TaskHandoff, ...]) -> dict[str, bytes]:
        pending = {item.source_run_id for item in pointers}
        captured: set[str] = set()
        while pending:
            run = min(pending)
            pending.remove(run)
            if run in captured:
                continue
            if len(captured) >= self.limits.max_runs or not durable.valid_run_id(run):
                raise ValueError(REFUSED)
            captured.add(run)
            run_fd = self._directory(run, self.root_fd)
            names = self._names(run_fd)
            allowed = {"meta.json", "events.jsonl", "task-state.json",
                       history_checkpoint.FILENAME, "receipts", "task-states",
                       durable.LOCK_FILENAME}
            if names - allowed:
                raise ValueError(REFUSED)
            if durable.LOCK_FILENAME in names:
                self._hold(run_fd)
            for name in sorted(names - {"receipts", "task-states", durable.LOCK_FILENAME}):
                self._read(run_fd, name, f"{run}/{name}")
            for name in ("receipts", "task-states"):
                if name not in names:
                    continue
                child = self._directory(name, run_fd)
                for leaf in sorted(self._names(child)):
                    self._read(child, leaf, f"{run}/{name}/{leaf}")
            for name, raw in tuple(self.files.items()):
                if name == f"{run}/task-state.json" or name.startswith(f"{run}/task-states/"):
                    digest = name.rsplit("/", 1)[1][:-5] if "/task-states/" in name else ""
                    state = decode_task_state(TaskCheckpoint.decode(run, raw, digest=digest), scope)
                    pending.update(ref.source_run_id for ref in state.references if ref.source_run_id not in captured)
        return self.files

    def verify(self) -> None:
        for parent, name, identity in self.entries:
            if _identity(os.stat(name, dir_fd=parent, follow_symlinks=False)) != identity:
                raise ValueError(REFUSED)
        for fd, identity in self.directories:
            if _identity(os.fstat(fd)) != identity:
                raise ValueError(REFUSED)
        if (_root_identity(os.fstat(self.root_fd)) != self.root_identity
                or _root_identity(self.root.lstat()) != self.root_identity):
            raise ValueError(REFUSED)
