"""Portable evidence is complete and unchanged, never an execution grant."""

import hashlib
import json
from pathlib import Path

import pytest

from core.runtime import history_checkpoint
from core.runtime.portable_checkpoint import (
    CheckpointLimits, PortableCheckpointValidator, REFUSED,
)
from core.runtime.receipt_checkpoint import ReceiptCheckpoint
from core.runtime.task_state import TaskCheckpoint, TaskContext, TaskScope
from tests.test_task_state import SCOPE, imported, selected


def captured(tmp_path, *, multi=False, history=False, payload=None):
    kwargs = {} if payload is None else {"payload": payload}
    store, run, results, context, receipt = selected(tmp_path, **kwargs)
    if history:
        history_checkpoint.save(store, run, [{"role": "user", "content": "Earlier question"}])
    pointer = context.export_handoff()
    if multi:
        context, _ = imported(store, pointer)
        pointer = context.export_handoff()
    root = store.directory(run).parent
    files = {str(path.relative_to(root)): path.read_bytes()
             for path in root.rglob("*") if path.is_file()}
    return store, run, pointer, files, receipt


def validate(pointer, files, *, scope=SCOPE, limits=None):
    return PortableCheckpointValidator(limits).validate(scope, [pointer], files)


@pytest.mark.parametrize("multi", [False, True])
@pytest.mark.parametrize("history", [False, True])
def test_complete_closure_keeps_exact_original_bytes_and_receipt_ids(tmp_path, multi, history):
    _, run, pointer, files, receipt = captured(tmp_path, multi=multi, history=history)
    result = validate(pointer, files)
    assert result.scope == SCOPE and result.handoffs == (pointer,)
    assert {part.name: part.content for part in result.parts} == files
    assert all(part.sha256 == hashlib.sha256(part.content).hexdigest() for part in result.parts)
    assert f"{run}/receipts/{receipt['id']}.json" in files
    assert len({part.name.split('/')[0] for part in result.parts}) == (2 if multi else 1)


def test_validation_never_opens_or_creates_files_or_resumes_a_context(tmp_path, monkeypatch):
    _, _, pointer, files, _ = captured(tmp_path, multi=True, history=True)

    def forbidden(*args, **kwargs):
        pytest.fail("detached validation performed a side effect")

    monkeypatch.setattr(Path, "open", forbidden)
    monkeypatch.setattr(TaskContext, "begin", forbidden)
    monkeypatch.setattr(ReceiptCheckpoint, "save", forbidden)
    monkeypatch.setattr(TaskCheckpoint, "save", forbidden)
    assert validate(pointer, files).parts


@pytest.mark.parametrize("damage", [
    "receipt_missing", "receipt_changed", "task_missing", "snapshot_missing",
    "meta_run", "meta_sequence", "event_sequence", "event_bool_sequence",
    "event_truncated", "event_duplicate_key", "event_nonfinite", "receipt_orphan",
    "lock", "heartbeat", "path_traversal", "absolute_path", "foreign_scope",
    "snapshot_changed", "task_duplicate_key", "history_missing", "history_changed",
])
def test_unsafe_or_incomplete_bundle_refuses_without_dropping_parts(tmp_path, damage):
    _, run, pointer, files, receipt = captured(tmp_path, history=True)
    original = dict(files)
    receipt_name = f"{run}/receipts/{receipt['id']}.json"
    task_name = f"{run}/task-state.json"
    snapshot_name = f"{run}/task-states/{pointer.sha256}.json"
    events_name = f"{run}/events.jsonl"
    if damage == "receipt_missing":
        files.pop(receipt_name)
    elif damage == "receipt_changed":
        files[receipt_name] += b" "
    elif damage == "receipt_orphan":
        files[f"{run}/receipts/{'0' * 32}.json"] = files[receipt_name]
    elif damage == "task_missing":
        files.pop(task_name)
    elif damage == "snapshot_missing":
        files.pop(snapshot_name)
    elif damage == "snapshot_changed":
        files[snapshot_name] += b" "
    elif damage == "task_duplicate_key":
        files[task_name] = b'{"version": 99,' + files[task_name][1:]
    elif damage == "foreign_scope":
        value = json.loads(files[task_name])
        value["scope"]["owner"] = "another-owner"
        files[task_name] = json.dumps(value).encode()
    elif damage.startswith("meta_"):
        name = f"{run}/meta.json"
        value = json.loads(files[name])
        value["run_id" if damage == "meta_run" else "last_seq"] = "run_other"
        files[name] = json.dumps(value).encode()
    elif damage.startswith("event_"):
        event = json.loads(files[events_name])
        if damage == "event_sequence":
            event["seq"] = 2
        elif damage == "event_bool_sequence":
            event["seq"] = True
        raw = json.dumps(event).encode() + b"\n"
        if damage == "event_truncated":
            raw = raw[:-1]
        elif damage == "event_duplicate_key":
            raw = b'{"seq": 50,' + raw[1:]
        elif damage == "event_nonfinite":
            raw = b'{"unexpected": NaN,' + raw[1:]
        files[events_name] = raw
    elif damage == "history_missing":
        files.pop(f"{run}/{history_checkpoint.FILENAME}")
    elif damage == "history_changed":
        files[f"{run}/{history_checkpoint.FILENAME}"] += b" "
    else:
        name = {"lock": f"{run}/lock", "heartbeat": f"{run}/heartbeat",
                "path_traversal": f"{run}/../meta.json",
                "absolute_path": f"/{run}/meta.json"}[damage]
        files[name] = b"{}"
    changed = dict(files)
    with pytest.raises(ValueError, match=REFUSED):
        validate(pointer, files)
    assert files == changed and original != files


def test_cross_owner_pointer_and_unrelated_runs_refuse(tmp_path):
    _, _, pointer, files, _ = captured(tmp_path)
    with pytest.raises(ValueError, match=REFUSED):
        validate(pointer, files, scope=TaskScope("different", SCOPE.thread))
    _, _, other, extra, _ = captured(tmp_path / "other")
    with pytest.raises(ValueError, match=REFUSED):
        validate(pointer, {**files, **extra})
    assert PortableCheckpointValidator().validate(SCOPE, [pointer, other], {**files, **extra})


@pytest.mark.parametrize("limit", ["max_bytes", "max_files", "max_runs"])
def test_aggregate_bounds_include_all_source_runs(tmp_path, limit):
    _, _, pointer, files, _ = captured(tmp_path, multi=True)
    with pytest.raises(ValueError, match=REFUSED):
        validate(pointer, files, limits=CheckpointLimits(**{limit: 1}))


@pytest.mark.parametrize("value", [0, -1, True, 2.5])
def test_invalid_limits_refuse(value):
    with pytest.raises(ValueError):
        CheckpointLimits(max_files=value)


def test_newly_recognized_secret_refuses_instead_of_rewriting_receipt(tmp_path, monkeypatch):
    secret = "newly-recognized-portable-secret-123456789"
    _, _, pointer, files, _ = captured(
        tmp_path, payload={"records": [{"name": "Ordinary", "note": secret}]})
    validate(pointer, files)
    original = dict(files)
    monkeypatch.setenv("TAIPAN_TOKEN", secret)
    with pytest.raises(ValueError) as caught:
        validate(pointer, files)
    assert str(caught.value) == REFUSED and files == original
    assert secret not in str(caught.value)


def test_stale_reference_refuses_even_when_all_receipt_hashes_match(tmp_path):
    _, run, pointer, files, _ = captured(tmp_path)
    name = f"{run}/task-state.json"
    document = json.loads(files[name])
    document["state"]["references"][0]["value_sha256"] = "0" * 64
    files[name] = json.dumps(document).encode()
    with pytest.raises(ValueError, match=REFUSED):
        validate(pointer, files)


@pytest.mark.parametrize("field", ["references", "staged", "delivered", "last_delivered", "prior_staged"])
def test_empty_objects_cannot_masquerade_as_task_lists(tmp_path, field):
    _, run, pointer, files, _ = captured(tmp_path)
    name = f"{run}/task-state.json"
    document = json.loads(files[name])
    document["state"][field] = {}
    files[name] = json.dumps(document).encode()
    with pytest.raises(ValueError, match=REFUSED):
        validate(pointer, files)


@pytest.mark.parametrize("surface", ["meta", "event", "history"])
def test_credential_fields_and_new_secrets_in_nonreceipt_surfaces_refuse(tmp_path, monkeypatch, surface):
    store, run, pointer, files, _ = captured(tmp_path, history=True)
    secret = "late-recognized-history-secret-456789"
    if surface == "meta":
        name = f"{run}/meta.json"
        value = json.loads(files[name])
        value["meta"]["password"] = "not-an-exportable-field"
        files[name] = json.dumps(value).encode()
    elif surface == "event":
        name = f"{run}/events.jsonl"
        value = json.loads(files[name])
        value["record"]["password"] = "not-an-exportable-field"
        files[name] = json.dumps(value).encode() + b"\n"
    else:
        name = f"{run}/{history_checkpoint.FILENAME}"
        value = json.loads(files[name])
        value["messages"][0]["content"] = secret
        files[name] = json.dumps(value).encode()
        meta_name = f"{run}/meta.json"
        meta = json.loads(files[meta_name])
        meta["meta"][history_checkpoint.META_KEY]["sha256"] = hashlib.sha256(files[name]).hexdigest()
        files[meta_name] = json.dumps(meta).encode()
        validate(pointer, files)
        monkeypatch.setenv("TAIPAN_TOKEN", secret)
    with pytest.raises(ValueError, match=REFUSED):
        validate(pointer, files)


def test_detached_decoders_agree_with_local_readers(tmp_path):
    store, run, _, files, _ = captured(tmp_path, history=True)
    record = store.records(run)[0]
    raw = files[f"{run}/receipts/{record['receipt']['id']}.json"]
    assert ReceiptCheckpoint.decode(run, record, raw) == ReceiptCheckpoint(store, run).load(record)
    assert TaskCheckpoint.decode(run, files[f"{run}/task-state.json"]) == TaskCheckpoint(store).load(run)
    meta = store.meta(run).meta
    assert history_checkpoint.decode(run, meta, files[f"{run}/{history_checkpoint.FILENAME}"]) == (
        history_checkpoint.load(store, run, meta))
