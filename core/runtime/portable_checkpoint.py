"""Detached validation of a captured, scoped checkpoint/receipt closure.

The caller owns quiescence, filesystem safety and export authorization. This
module opens no files and executes nothing. Hashes bind original bytes; they
are not authentication. The returned bundle is evidence, never a resume grant.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Mapping, Sequence

from core.durable import valid_run_id
from core.runtime import history_checkpoint
from core.runtime.receipt_checkpoint import ReceiptCheckpoint, ReceiptReference, _safe_json
from core.runtime.results import StoredResult, walk_path
from core.runtime.task_state import (
    TaskCheckpoint, TaskHandoff, TaskReference, TaskScope, decode_task_state,
)

_HASH = re.compile(r"[0-9a-f]{64}\Z")
_RECEIPT = re.compile(r"[0-9a-f]{32}\.json\Z")
REFUSED = "Portable checkpoint is incomplete, unsafe or inconsistent."


@dataclass(frozen=True)
class CheckpointLimits:
    max_bytes: int = 64 * 1024 * 1024
    max_files: int = 4096
    max_runs: int = 256

    def __post_init__(self) -> None:
        if any(type(value) is not int or value < 1 for value in (
                self.max_bytes, self.max_files, self.max_runs)):
            raise ValueError("checkpoint limits must be positive integers")


@dataclass(frozen=True)
class CheckpointPart:
    name: str
    content: bytes
    sha256: str


@dataclass(frozen=True)
class PortableCheckpoint:
    scope: TaskScope
    handoffs: tuple[TaskHandoff, ...]
    parts: tuple[CheckpointPart, ...]


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(REFUSED)
        result[key] = value
    return result


def _constant(value: str) -> object:
    raise ValueError(REFUSED)


def _document(raw: bytes) -> dict[str, object]:
    value = json.loads(raw, object_pairs_hook=_unique, parse_constant=_constant)
    if not isinstance(value, dict) or _safe_json(value) != value:
        # Never redact here: that would change a persisted receipt identity.
        raise ValueError(REFUSED)
    return value


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


class PortableCheckpointValidator:
    """All-or-nothing validation; no silent drops or filesystem race window.

    Supply immutable captured bytes, relative to the existing runs root. Locks,
    heartbeats, credentials and unknown files are not portable checkpoint data.
    Missing evidence refuses the bundle rather than inviting a tool re-execution.
    """

    def __init__(self, limits: CheckpointLimits | None = None) -> None:
        self.limits = limits if limits is not None else CheckpointLimits()

    def validate(self, scope: TaskScope, handoffs: Sequence[TaskHandoff],
                 files: Mapping[str, bytes]) -> PortableCheckpoint:
        try:
            if len(handoffs) > self.limits.max_files or len(files) > self.limits.max_files:
                raise ValueError(REFUSED)
            return self._validate(scope, tuple(handoffs), dict(files))
        except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
            # Neither corrupted bytes nor credential-bearing values reach errors.
            raise ValueError(REFUSED) from None

    def _validate(self, scope: TaskScope, handoffs: tuple[TaskHandoff, ...],
                  files: dict[str, bytes]) -> PortableCheckpoint:
        if (not handoffs or len(handoffs) > self.limits.max_files
                or not files or len(files) > self.limits.max_files
                or any(type(raw) is not bytes for raw in files.values())
                or sum(len(raw) for raw in files.values()) > self.limits.max_bytes):
            raise ValueError(REFUSED)
        runs: set[str] = set()
        documents: dict[str, dict[str, object]] = {}
        for name, raw in files.items():
            pieces = name.split("/")
            run = pieces[0]
            if not valid_run_id(run) or "\n" in run:
                raise ValueError(REFUSED)
            runs.add(run)
            leaf = "/".join(pieces[1:])
            if len(pieces) == 2 and leaf in {
                    "meta.json", "events.jsonl", "task-state.json",
                    history_checkpoint.FILENAME}:
                pass
            elif (len(pieces) == 3 and pieces[1] == "receipts"
                  and _RECEIPT.fullmatch(pieces[2])):
                pass
            elif (len(pieces) == 3 and pieces[1] == "task-states"
                  and pieces[2].endswith(".json") and _HASH.fullmatch(pieces[2][:-5])):
                pass
            else:
                raise ValueError(REFUSED)
            if leaf != "events.jsonl":
                documents[name] = _document(raw)
        if len(runs) > self.limits.max_runs:
            raise ValueError(REFUSED)
        references: list[TaskReference] = []
        dependencies: dict[str, set[str]] = {run: set() for run in runs}
        receipts: dict[tuple[str, str, str], StoredResult] = {}
        used_receipts: set[str] = set()
        for run in sorted(runs):
            meta = documents[f"{run}/meta.json"]
            run_meta = meta.get("meta")
            if (meta.get("run_id") != run or type(meta.get("last_seq")) is not int
                    or not isinstance(run_meta, dict)):
                raise ValueError(REFUSED)
            task_names = [name for name in files if name == f"{run}/task-state.json"
                          or name.startswith(f"{run}/task-states/")]
            if f"{run}/task-state.json" not in task_names:
                raise ValueError(REFUSED)
            for name in task_names:
                digest = name.rsplit("/", 1)[1][:-5] if "/task-states/" in name else ""
                document = TaskCheckpoint.decode(run, files[name], digest=digest)
                state = decode_task_state(document, scope)
                references.extend(state.references)
                dependencies[run].update(ref.source_run_id for ref in state.references)
            history_name = f"{run}/{history_checkpoint.FILENAME}"
            if history_checkpoint.META_KEY in run_meta:
                history, notice = history_checkpoint.decode(run, run_meta, files[history_name])
                if history is None or notice == history_checkpoint.UNAVAILABLE:
                    raise ValueError(REFUSED)
            elif history_name in files:
                raise ValueError(REFUSED)
            events = files[f"{run}/events.jsonl"]
            if events and not events.endswith(b"\n"):
                raise ValueError(REFUSED)
            lines = events.splitlines()
            if len(lines) != meta["last_seq"]:
                raise ValueError(REFUSED)
            for seq, line in enumerate(lines, 1):
                event = _document(line)
                record = event.get("record")
                if (type(event.get("seq")) is not int or event["seq"] != seq
                        or not isinstance(record, dict)):
                    raise ValueError(REFUSED)
                ref = ReceiptReference.from_record(record)
                if ref is None:
                    continue
                name = f"{run}/receipts/{ref.id}.json"
                result = ReceiptCheckpoint.decode(run, record, files[name]).receipt
                if result is None or name in used_receipts:
                    raise ValueError(REFUSED)
                used_receipts.add(name)
                receipts[(run, ref.id, ref.sha256)] = result
        if any("/receipts/" in name and name not in used_receipts for name in files):
            raise ValueError(REFUSED)
        for source in references:
            result = receipts[(source.source_run_id, source.receipt_id, source.receipt_sha256)]
            identity = hashlib.sha256(_canonical([
                source.source_run_id, source.receipt_id, source.path, source.value_sha256])).hexdigest()
            value, problem = walk_path(result.structured, source.path)
            if (identity != source.id or result.redacted or result.quoted_history
                    or not result.succeeded or problem
                    or hashlib.sha256(_canonical(value)).hexdigest() != source.value_sha256):
                raise ValueError(REFUSED)
        reachable: set[str] = set()
        pending: list[str] = []
        for pointer in handoffs:
            checked = TaskHandoff.from_record(pointer.as_record())
            if checked.scope != scope:
                raise ValueError(REFUSED)
            name = f"{checked.source_run_id}/task-states/{checked.sha256}.json"
            if name not in files:
                raise ValueError(REFUSED)
            pending.append(checked.source_run_id)
        while pending:
            run = pending.pop()
            if run not in reachable:
                reachable.add(run)
                pending.extend(dependencies[run] - reachable)
        if reachable != runs:
            raise ValueError(REFUSED)
        return PortableCheckpoint(scope, handoffs, tuple(
            CheckpointPart(name, raw, hashlib.sha256(raw).hexdigest())
            for name, raw in sorted(files.items())))
