"""Native capture keeps original evidence, refuses races and leaves stores alone."""

import os

import pytest

from core.runtime.checkpoint_capture import NativeCheckpointCapture
from core.runtime.portable_checkpoint import CheckpointLimits, PortableCheckpointValidator, REFUSED
from core.runtime.task_state import TaskScope
from tests.test_portable_checkpoint import captured
from tests.test_task_state import SCOPE


@pytest.mark.parametrize("multi", [False, True])
@pytest.mark.parametrize("history", [False, True])
def test_native_capture_is_exact_and_does_not_create_locks(tmp_path, multi, history):
    store, run, pointer, files, _ = captured(tmp_path, multi=multi, history=history)
    root = store.directory(run).parent
    before = sorted(str(path.relative_to(root)) for path in root.rglob("*"))
    result = NativeCheckpointCapture(root).capture(SCOPE, [pointer])
    assert {part.name: part.content for part in result.parts} == files
    assert sorted(str(path.relative_to(root)) for path in root.rglob("*")) == before


def test_unrelated_runs_are_not_read(tmp_path):
    store, run, pointer, files, _ = captured(tmp_path)
    root = store.directory(run).parent
    other = root / "run_unrelated"
    other.mkdir()
    (other / "private").write_text("not this conversation")
    result = NativeCheckpointCapture(root).capture(SCOPE, [pointer])
    assert {part.name: part.content for part in result.parts} == files


def test_unrelated_run_admission_during_capture_is_allowed(tmp_path, monkeypatch):
    store, run, pointer, files, _ = captured(tmp_path)
    root = store.directory(run).parent
    original = PortableCheckpointValidator.validate
    def changed(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        (root / "run_unrelated").mkdir()
        return result
    monkeypatch.setattr(PortableCheckpointValidator, "validate", changed)
    result = NativeCheckpointCapture(root).capture(SCOPE, [pointer])
    assert {part.name: part.content for part in result.parts} == files


def test_scope_refuses_before_filesystem_access(tmp_path, monkeypatch):
    _, _, pointer, _, _ = captured(tmp_path)
    def forbidden(*args, **kwargs):
        pytest.fail("foreign scope opened a file")
    monkeypatch.setattr(os, "open", forbidden)
    with pytest.raises(ValueError, match=REFUSED):
        NativeCheckpointCapture(tmp_path).capture(TaskScope("other", SCOPE.thread), [pointer])


@pytest.mark.parametrize("damage", ["root_symlink", "run_symlink", "file_symlink",
    "directory_symlink", "hardlink", "writable", "fifo", "unknown", "missing"])
def test_unsafe_layout_refuses_without_repair(tmp_path, damage):
    store, run, pointer, _, _ = captured(tmp_path)
    root = store.directory(run).parent
    directory = root / run
    target = directory / "task-state.json"
    if damage in {"root_symlink", "run_symlink", "directory_symlink", "file_symlink"}:
        path = {"root_symlink": root, "run_symlink": directory,
                "directory_symlink": directory / "receipts", "file_symlink": target}[damage]
        moved = path.with_name(path.name + "-original")
        path.rename(moved)
        path.symlink_to(moved)
    elif damage == "hardlink":
        os.link(target, tmp_path / "duplicate")
    elif damage == "writable":
        target.chmod(0o666)
    elif damage == "fifo":
        target.unlink()
        os.mkfifo(target)
    elif damage == "unknown":
        (directory / "unhandled-output.bin").write_bytes(b"private")
    elif damage == "missing":
        target.unlink()
    with pytest.raises(ValueError, match=REFUSED):
        NativeCheckpointCapture(root).capture(SCOPE, [pointer])

@pytest.mark.parametrize("limit", ["max_bytes", "max_files", "max_runs"])
def test_limits_cover_cross_run_dependency_closure(tmp_path, limit):
    store, run, pointer, _, _ = captured(tmp_path, multi=True)
    with pytest.raises(ValueError, match=REFUSED):
        NativeCheckpointCapture(store.directory(run).parent, CheckpointLimits(**{limit: 1})).capture(SCOPE, [pointer])


def test_active_native_run_refuses_then_released_lock_is_not_exported(tmp_path):
    store, run, pointer, files, _ = captured(tmp_path)
    root = store.directory(run).parent
    with store.hold(run, heartbeat_s=0):
        with pytest.raises(ValueError, match=REFUSED):
            NativeCheckpointCapture(root).capture(SCOPE, [pointer])
    result = NativeCheckpointCapture(root).capture(SCOPE, [pointer])
    assert {part.name: part.content for part in result.parts} == files
    assert not store.held(run)


@pytest.mark.parametrize("change", ["file", "new_file", "root", "run", "lock", "root_mode"])
def test_changes_after_validation_refuse_and_release_locks(tmp_path, monkeypatch, change):
    store, run, pointer, _, _ = captured(tmp_path)
    root = store.directory(run).parent
    with store.hold(run, heartbeat_s=0):
        pass
    original = PortableCheckpointValidator.validate
    def changed(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        directory = root / run
        if change == "file":
            (directory / "task-state.json").write_bytes(b"{}")
        elif change == "new_file":
            (directory / "new-data").write_bytes(b"new")
        elif change == "root_mode":
            root.chmod(0o777)
        else:
            path = {"root": root, "run": directory, "lock": directory / "lock"}[change]
            path.rename(path.with_name(path.name + "-old"))
            if change == "lock":
                path.write_bytes(b"")
            else:
                path.mkdir()
        return result
    monkeypatch.setattr(PortableCheckpointValidator, "validate", changed)
    with pytest.raises(ValueError, match=REFUSED):
        NativeCheckpointCapture(root).capture(SCOPE, [pointer])

    # The original lock may have moved with a run/root replacement.
    lock_root = root.with_name(root.name + "-old") if change == "root" else root
    lock_run = run + "-old" if change == "run" else run
    lock_name = "lock-old" if change == "lock" else "lock"
    from core import durable
    with (lock_root / lock_run / lock_name).open("rb") as stream:
        durable.fcntl.flock(stream.fileno(), durable.fcntl.LOCK_EX | durable.fcntl.LOCK_NB)


def test_failure_closes_all_open_descriptors(tmp_path, monkeypatch):
    store, run, pointer, _, _ = captured(tmp_path)
    root = store.directory(run).parent
    real_open, real_close = os.open, os.close
    opened = set()
    def track_open(*args, **kwargs):
        fd = real_open(*args, **kwargs)
        opened.add(fd)
        return fd
    def track_close(fd):
        opened.discard(fd)
        return real_close(fd)
    monkeypatch.setattr(os, "open", track_open)
    monkeypatch.setattr(os, "close", track_close)
    (root / run / "task-state.json").unlink()
    with pytest.raises(ValueError, match=REFUSED):
        NativeCheckpointCapture(root).capture(SCOPE, [pointer])
    assert not opened
