"""Current-task state and source-bound references, owned by one run context.

Caller scope is a binding, not authentication. Portable handoffs point to
private, immutable RunStore snapshots; message text is never imported as state.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
import hashlib
import json
import re
import uuid
from threading import RLock
from typing import TYPE_CHECKING, Any, Dict, Iterator, List, Mapping, Optional, Tuple

from core.durable import RunStore, atomic_write_text
from core.runtime.receipt_checkpoint import ReceiptCheckpoint, _safe_json
from core.runtime.results import MissionResultStore, StoredResult, walk_path
from core.tools.descriptors import ToolDescriptor

if TYPE_CHECKING:
    from core.tools.bus import ToolBus

TASK_TOOL = "mission_task"
MAX_STATE_BYTES = 4 * 1024 * 1024
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


def _bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False,
                      sort_keys=True, separators=(",", ":")).encode("utf-8")


@dataclass(frozen=True)
class TaskScope:
    owner: str
    thread: str

    def __post_init__(self) -> None:
        if not all(isinstance(v, str) and v.strip() for v in (self.owner, self.thread)):
            raise ValueError("task scope needs an owner and thread")


@dataclass(frozen=True)
class TaskIntent:
    deliverable: str = ""
    requested_count: Optional[int] = None
    provenance: str = "unknown"

    def __post_init__(self) -> None:
        if not isinstance(self.deliverable, str):
            raise ValueError("deliverable must be text")
        if self.provenance not in {"caller", "model", "unknown"}:
            raise ValueError("unknown intent provenance")
        if self.requested_count is not None and (
                type(self.requested_count) is not int or self.requested_count < 0):
            raise ValueError("requested count must be a nonnegative integer or unknown")


@dataclass(frozen=True)
class TaskHandoff:
    scope: TaskScope
    source_run_id: str
    sha256: str
    version: int = 1

    def as_record(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_record(cls, value: Any) -> TaskHandoff:
        if (not isinstance(value, dict)
                or set(value) != {"version", "scope", "source_run_id", "sha256"}
                or type(value["version"]) is not int or value["version"] != 1
                or not isinstance(value["scope"], dict)
                or set(value["scope"]) != {"owner", "thread"}
                or not isinstance(value["source_run_id"], str)
                or not isinstance(value["sha256"], str)
                or not _DIGEST.fullmatch(value["sha256"])):
            raise ValueError("invalid task handoff")
        return cls(TaskScope(**value["scope"]), value["source_run_id"], value["sha256"])


@dataclass(frozen=True)
class TaskReference:
    id: str
    source_run_id: str
    receipt_id: str
    receipt_sha256: str
    path: str
    value_sha256: str
    label: str = ""

    def __post_init__(self) -> None:
        if (any(not isinstance(v, str) for v in asdict(self).values())
                or not _DIGEST.fullmatch(self.id) or not _DIGEST.fullmatch(self.value_sha256)):
            raise ValueError("invalid typed reference")


@dataclass(frozen=True)
class TaskItem:
    reference_id: str
    text: str

    def __post_init__(self) -> None:
        if (not isinstance(self.reference_id, str) or not _DIGEST.fullmatch(self.reference_id)
                or not isinstance(self.text, str) or not self.text.strip()):
            raise ValueError("invalid source-bound item")


@dataclass
class CurrentTask:
    objective: str = ""
    intent: TaskIntent = field(default_factory=TaskIntent)
    references: List[TaskReference] = field(default_factory=list)
    staged: List[TaskItem] = field(default_factory=list)
    delivered: List[TaskItem] = field(default_factory=list)
    unresolved: List[str] = field(default_factory=list)
    declared_todo: List[str] = field(default_factory=list)
    completion: str = "unknown"
    interpreted_intent: Optional[TaskIntent] = None
    selection_known: bool = False
    last_delivered: List[TaskItem] = field(default_factory=list)
    prior_staged: List[TaskItem] = field(default_factory=list)
    selected_reference_ids: List[str] = field(default_factory=list)
    selection_current: bool = False
    last_mapping_current: bool = False


class TaskCheckpoint:
    """Mutable restart state and immutable exported snapshots in RunStore."""

    def __init__(self, store: RunStore) -> None:
        self.store = store

    def save(self, run_id: str, document: Mapping[str, Any], *, export: bool = False) -> str:
        safe = _safe_json(dict(document))
        if safe != document:
            # A changed objective/ref identity cannot quietly become the original.
            raise ValueError("task checkpoint contains credential-shaped content")
        raw = _bytes(safe)
        if len(raw) > MAX_STATE_BYTES:
            raise ValueError("task checkpoint exceeds archive bound")
        digest = hashlib.sha256(raw).hexdigest()
        root = self.store.directory(run_id)
        path = root / "task-state.json"
        if export:
            path = root / "task-states" / (digest + ".json")
        atomic_write_text(path, raw.decode("utf-8"))
        return digest

    def load(self, run_id: str, digest: str = "") -> Dict[str, Any]:
        root = self.store.directory(run_id)
        path = root / "task-state.json"
        if digest:
            if not _DIGEST.fullmatch(digest):
                raise ValueError("invalid checkpoint digest")
            path = root / "task-states" / (digest + ".json")
        with path.open("rb") as stream:
            raw = stream.read(MAX_STATE_BYTES + 1)
        if len(raw) > MAX_STATE_BYTES or (digest and hashlib.sha256(raw).hexdigest() != digest):
            raise ValueError("task checkpoint unavailable")
        document = json.loads(raw)
        if (not isinstance(document, dict) or type(document.get("version")) is not int
                or document.get("version") != 1
                or document.get("source_run_id") != run_id
                or _safe_json(document) != document):
            raise ValueError("invalid task checkpoint")
        return document


class TaskContext:
    """Opt-in library state; CLI creates local state by default.

    The private result store remains the payload owner. This object keeps
    selectors and progress, never a competing copy of structured evidence.
    """

    def __init__(self, scope: Optional[TaskScope] = None,
                 handoff: Optional[TaskHandoff] = None,
                 intent: Optional[TaskIntent] = None) -> None:
        self.scope = scope
        self.handoff = handoff
        self.caller_intent = intent
        if handoff is not None and (scope is None or handoff.scope != scope):
            raise ValueError("task handoff does not match caller scope")
        self.state = CurrentTask()
        self.run_id = ""
        self.runs: Optional[RunStore] = None
        self._sources: Dict[str, Tuple[StoredResult, str, str]] = {}
        self._resolved: Dict[str, Tuple[StoredResult, Any]] = {}
        self._active: ContextVar[Optional[MissionResultStore]] = ContextVar(
            "mission_task_results", default=None)
        self._lock = RLock()
        self._leases = 0
        self._local_id = uuid.uuid4().hex
        self._rendered: List[TaskItem] = []
        self._rendered_block = ""
        self._redacted_sources: set[int] = set()
        self._source_records: Dict[str, Dict[Tuple[str, str], Mapping[str, Any]]] = {}
        self._loaded_receipts: Dict[Tuple[str, str, str], StoredResult] = {}

    @classmethod
    def local(cls) -> TaskContext:
        return cls()

    def begin(self, objective: str, results: MissionResultStore, *,
              runs: Optional[RunStore] = None, run_id: str = "", resume: bool = False) -> None:
        with self._lock:
            self.runs, self.run_id = runs, run_id
            self.state = CurrentTask(objective=objective, intent=self.caller_intent or TaskIntent())
            self._sources.clear()
            self._redacted_sources.clear()
            self._source_records.clear()
            self._loaded_receipts.clear()
            self._resolved.clear()
            self._rendered.clear()
            self._rendered_block = ""
            self._local_id = uuid.uuid4().hex
            if runs is not None and (resume or self.handoff is not None):
                try:
                    source = run_id if self.handoff is None or resume else self.handoff.source_run_id
                    digest = "" if self.handoff is None or resume else self.handoff.sha256
                    document = TaskCheckpoint(runs).load(source, digest)
                    self._restore(document, results, resume=resume)
                except (OSError, ValueError, TypeError, KeyError, RecursionError):
                    self.state.unresolved.append("Prior task state unavailable; do not reconstruct it by repeating actions.")
            if not resume:
                self._replace_objective(objective, self.caller_intent)
            self.checkpoint()

    def _replace_objective(self, objective: str, intent: Optional[TaskIntent]) -> None:
        delivered_ids = {item.reference_id for item in self.state.delivered}
        pending = [item for item in self.state.staged if item.reference_id not in delivered_ids]
        prior = {item.reference_id: item for item in self.state.prior_staged}
        prior.update((item.reference_id, item) for item in pending)
        self.state.prior_staged = list(prior.values())
        self.state.objective = objective
        self.state.intent = intent or TaskIntent()
        self.state.staged.clear()
        self.state.delivered.clear()
        self.state.declared_todo.clear()
        self.state.completion = "unknown"
        self.state.interpreted_intent = None
        self.state.selection_current = False
        self.state.last_mapping_current = False
        self._rendered.clear()
        self._rendered_block = ""

    def revise_objective(self, objective: str) -> None:
        """An explicit injected owner turn supersedes old intent, not evidence."""
        with self._lock:
            self._replace_objective(objective, None)
            self.checkpoint()

    def _restore(self, document: Mapping[str, Any], results: MissionResultStore,
                 *, resume: bool) -> None:
        expected = asdict(self.scope) if self.scope is not None else None
        if document.get("scope") != expected or not isinstance(document.get("state"), dict):
            raise ValueError("task checkpoint scope mismatch")
        data = document["state"]
        if not isinstance(data.get("objective"), str):
            raise ValueError("invalid task objective")
        intent = TaskIntent(**data["intent"])
        references = [TaskReference(**row) for row in data["references"]]
        staged = [TaskItem(**row) for row in data["staged"]]
        delivered = [TaskItem(**row) for row in data["delivered"]]
        unresolved, todo = data["unresolved"], data["declared_todo"]
        if (not isinstance(unresolved, list) or not isinstance(todo, list)
                or any(not isinstance(v, str) for v in [*unresolved, *todo])):
            raise ValueError("invalid task work list")
        interpreted = data.get("interpreted_intent")
        last_delivered = [TaskItem(**row) for row in data.get("last_delivered", [])]
        prior_staged = [TaskItem(**row) for row in data.get("prior_staged", [])]
        reference_ids = {ref.id for ref in references}
        for items in (staged, delivered, last_delivered, prior_staged):
            if (any(item.reference_id not in reference_ids for item in items)
                    or len({item.reference_id for item in items}) != len(items)):
                raise ValueError("invalid delivered reference list")
        selection_known = data.get("selection_known", bool(references))
        if type(selection_known) is not bool or len({r.id for r in references}) != len(references):
            raise ValueError("invalid reference selection")
        selected = data.get("selected_reference_ids", [ref.id for ref in references])
        selection_current = data.get("selection_current", False)
        last_current = data.get("last_mapping_current", False)
        if (not isinstance(selected, list) or any(not isinstance(v, str) for v in selected)
                or any(v not in reference_ids for v in selected)
                or len(set(selected)) != len(selected)
                or type(selection_current) is not bool or type(last_current) is not bool):
            raise ValueError("invalid active reference ordering")
        self.state = CurrentTask(
            objective=data["objective"], intent=intent, references=references,
            staged=staged, delivered=delivered, unresolved=list(unresolved),
            declared_todo=list(todo), interpreted_intent=(
                TaskIntent(**interpreted) if interpreted is not None else None),
            selection_known=selection_known, last_delivered=last_delivered,
            prior_staged=prior_staged, selected_reference_ids=list(selected),
            selection_current=selection_current, last_mapping_current=last_current)
        for ref in references:
            try:
                self._resolve(ref, results)
            except (OSError, ValueError, TypeError, KeyError):
                self._unavailable(ref.id)
        # Items whose source no longer resolves are not confirmed deliverables.
        prior = {item.reference_id: item for item in self.state.prior_staged}
        prior.update((item.reference_id, item) for item in staged
                     if item.reference_id not in self._resolved)
        self.state.prior_staged = list(prior.values())
        self.state.staged = [item for item in staged if item.reference_id in self._resolved]
        self.state.delivered = [item for item in delivered if item.reference_id in self._resolved]

    def _resolve(self, ref: TaskReference, results: MissionResultStore) -> None:
        if self.runs is None:
            raise ValueError("source run store unavailable")
        identity = hashlib.sha256(_bytes([ref.source_run_id, ref.receipt_id,
                                         ref.path, ref.value_sha256])).hexdigest()
        if ref.id != identity:
            raise ValueError("reference identity changed")
        if ref.source_run_id not in self._source_records:
            source = TaskCheckpoint(self.runs).load(ref.source_run_id)
            expected = asdict(self.scope) if self.scope is not None else None
            if source.get("scope") != expected:
                raise ValueError("source scope mismatch")
            self._source_records[ref.source_run_id] = {
                (row["receipt"]["id"], row["receipt"]["sha256"]): row
                for row in self.runs.records(ref.source_run_id)
                if isinstance(row.get("receipt"), dict)
                and isinstance(row["receipt"].get("id"), str)
                and isinstance(row["receipt"].get("sha256"), str)}
        record = self._source_records[ref.source_run_id].get((ref.receipt_id, ref.receipt_sha256))
        if record is None:
            raise ValueError("source receipt unavailable")
        key = (ref.source_run_id, ref.receipt_id, ref.receipt_sha256)
        loaded = self._loaded_receipts.get(key)
        if loaded is None:
            loaded = ReceiptCheckpoint(self.runs, ref.source_run_id).load(record).receipt
        if loaded is None or loaded.quoted_history or loaded.redacted or not loaded.succeeded:
            raise ValueError("source receipt is not unaltered observed evidence")
        self._loaded_receipts[key] = loaded
        value, problem = walk_path(loaded.structured, ref.path)
        if problem or hashlib.sha256(_bytes(value)).hexdigest() != ref.value_sha256:
            raise ValueError("source record changed or disappeared")
        # One imported result per source receipt, even for several ordered rows.
        existing = next((r for r in results.results if r.origin is not None
                         and r.origin.receipt_id == ref.receipt_id
                         and r.origin.run_id == ref.source_run_id), None)
        if existing is None:
            existing = results.record(loaded.tool, loaded.arguments, text=loaded.text,
                                      evidence=loaded.evidence, exit_code=loaded.exit_code,
                                      origin=loaded.origin)
        self._resolved[ref.id] = (existing, value)

    def _unavailable(self, reference_id: str) -> None:
        message = f"Reference {reference_id} is unavailable or redacted; it is not confirmed evidence."
        if message not in self.state.unresolved:
            self.state.unresolved.append(message)

    def import_sources(self, results: MissionResultStore) -> None:
        """Make restored bound evidence visible to a branch's existing validator."""
        seen: set[int] = set()
        for source, _ in self._resolved.values():
            if id(source) in seen:
                continue
            seen.add(id(source))
            if source.origin is not None and not any(
                    row.origin == source.origin for row in results.results):
                results.record(source.tool, source.arguments, text=source.text,
                               evidence=source.evidence, exit_code=source.exit_code,
                               origin=source.origin)

    def observe(self, result: StoredResult, receipt: Mapping[str, Any], *, branch: str = "") -> None:
        if receipt.get("redacted") or receipt.get("identity_redacted"):
            self._redacted_sources.add(id(result))
        if result.quoted_history or result.redacted or not result.succeeded:
            return
        if receipt.get("state") == "ready" and not receipt.get("redacted"):
            self._sources[f"{branch}:{result.handle}"] = (
                result, str(receipt["id"]), str(receipt["sha256"]))

    @contextmanager
    def using(self, results: MissionResultStore) -> Iterator[None]:
        token = self._active.set(results)
        try:
            yield
        finally:
            self._active.reset(token)

    def acquire(self, bus: ToolBus) -> None:
        with self._lock:
            if self._leases == 0:
                if bus.get_descriptor(TASK_TOOL) is not None:
                    raise ValueError("mission_task is already registered")
                bus.register(self.descriptor(), self.execute)
            self._leases += 1

    def release(self, bus: ToolBus) -> None:
        with self._lock:
            self._leases -= 1
            if self._leases == 0:
                bus.unregister(TASK_TOOL)

    def descriptor(self) -> ToolDescriptor:
        return ToolDescriptor(tool_name=TASK_TOOL,
            description="Track the current task without guessing completion. plan records MODEL-INTERPRETED intent/todo; select binds ordered references to an actual result handle and JSON path, replacing the active selection by default; mode=append adds another batch in order. Historical references are retained separately. stage pairs a reference ID with item text included BEFORE grounding the final answer. read retrieves ordered references; collection=last_answer follows the last source-bound delivered list, with mapping_current=false if a later unstructured answer has no confirmed mapping. Never repeat a completed action to rebuild prose. Counts come from bound records and rendered items, not a completed=N claim.",
            input_schema={"type": "object", "properties": {
                "operation": {"type": "string", "enum": ["plan", "select", "stage", "read"]},
                "deliverable": {"type": "string"}, "requested_count": {"type": "integer", "minimum": 0},
                "todo": {"type": "array", "items": {"type": "string"}},
                "handle": {"type": "string"}, "path": {"type": "string"},
                "label": {"type": "string"}, "expand": {"type": "boolean"},
                "mode": {"type": "string", "enum": ["replace", "append"]},
                "reference_id": {"type": "string"}, "text": {"type": "string"},
                "collection": {"type": "string", "enum": ["selected", "last_answer", "prior_staged"]},
                "offset": {"type": "integer", "minimum": 0},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100}},
                "required": ["operation"], "additionalProperties": False})

    def execute(self, operation: str, **kwargs: Any) -> Tuple[int, str, str]:
        with self._lock:
            try:
                result = self._execute(operation, kwargs)
                self.checkpoint()
                return 0, json.dumps(result, ensure_ascii=False), ""
            except (ValueError, TypeError, KeyError, RecursionError):
                return 1, "", "Task operation could not be applied: check its operation, arguments and available source reference."

    def _execute(self, operation: str, args: Mapping[str, Any]) -> Dict[str, Any]:
        allowed = {"deliverable", "requested_count", "todo", "handle", "path", "label",
                   "expand", "reference_id", "text", "collection", "offset", "limit", "mode"}
        if set(args) - allowed:
            raise ValueError("unknown task argument")
        for key in ("handle", "path", "label", "reference_id", "text"):
            if key in args and not isinstance(args[key], str):
                raise ValueError("task selectors and text must be strings")
        if "expand" in args and type(args["expand"]) is not bool:
            raise ValueError("expand must be boolean")
        if _safe_json(dict(args)) != args:
            raise ValueError("task arguments contain credential-shaped content")
        offset, limit = args.get("offset", 0), args.get("limit", 20)
        collection = args.get("collection", "selected")
        mode = args.get("mode", "replace")
        if mode not in {"replace", "append"}:
            raise ValueError("unknown selection mode")
        if collection not in {"selected", "last_answer", "prior_staged"}:
            raise ValueError("unknown reference collection")
        if type(offset) is not int or type(limit) is not int or offset < 0 or not 1 <= limit <= 100:
            raise ValueError("read needs offset >= 0 and limit between 1 and 100")
        if operation == "plan":
            interpreted = TaskIntent(args.get("deliverable", ""), args.get("requested_count"), "model")
            todo = args.get("todo", [])
            if not isinstance(todo, list) or any(not isinstance(v, str) for v in todo):
                raise ValueError("todo must be a list of model-declared work descriptions")
            self.state.interpreted_intent = interpreted
            if self.state.intent.provenance != "caller":
                self.state.intent = interpreted
            self.state.declared_todo = list(todo)
        elif operation == "select":
            results = self._active.get()
            found = results.get(args.get("handle", "")) if results is not None else None
            if (found is None or found.quoted_history or found.redacted or not found.succeeded
                    or id(found) in self._redacted_sources or found.tool == TASK_TOOL):
                raise ValueError("select requires an observed successful result, not quoted history")
            source = next((v for v in self._sources.values() if v[0] is found), None)
            if source is None and found.origin is not None and not found.origin.redacted:
                source = (found, found.origin.receipt_id, found.origin.sha256)
            path = args.get("path", "")
            value, problem = walk_path(found.structured, path)
            if problem or not found.evidence:
                raise ValueError("selected structured path is unavailable")
            values: List[Tuple[Optional[int], Any]] = (list(enumerate(value))
                if args.get("expand", True) and isinstance(value, list) else [(None, value)])
            selected_refs = []
            for index, item in values:
                item_path = f"{path}[{index}]" if index is not None else path
                value_digest = hashlib.sha256(_bytes(item)).hexdigest()
                run_id = found.origin.run_id if found.origin is not None else self.run_id or self._local_id
                receipt_id, digest = (source[1], source[2]) if source is not None else ("local:" + found.handle, "")
                identity = hashlib.sha256(_bytes([run_id, receipt_id, item_path, value_digest])).hexdigest()
                ref = TaskReference(identity, run_id, receipt_id, digest, item_path,
                                    value_digest, str(args.get("label", "")))
                selected_refs.append((ref, item))
            active = list(self.state.selected_reference_ids) if mode == "append" else []
            for ref, item in selected_refs:
                identity = ref.id
                if not any(existing.id == identity for existing in self.state.references):
                    self.state.references.append(ref)
                self._resolved[identity] = (found, item)
                if identity not in active:
                    active.append(identity)
            self.state.selected_reference_ids = active
            self.state.selection_known = self.state.selection_current = True
        elif operation == "stage":
            reference_id, text = args.get("reference_id"), args.get("text")
            if reference_id not in self._resolved or not isinstance(text, str) or not text.strip():
                raise ValueError("stage needs an available reference ID and nonempty item text")
            self.state.staged = [item for item in self.state.staged if item.reference_id != reference_id]
            self.state.staged.append(TaskItem(reference_id, text))
        elif operation != "read":
            raise ValueError("unknown mission_task operation")
        rows = []
        references = self._selected_references()
        old_items: Dict[str, TaskItem] = {}
        if collection in {"last_answer", "prior_staged"}:
            by_id = {ref.id: ref for ref in self.state.references}
            items = self.state.last_delivered if collection == "last_answer" else self.state.prior_staged
            old_items = {item.reference_id: item for item in items}
            references = [by_id[item.reference_id] for item in items
                          if item.reference_id in by_id]
        for ordinal, ref in enumerate(references[offset:offset + limit], offset + 1):
            resolved = self._resolved.get(ref.id)
            rows.append({"ordinal": ordinal, **asdict(ref), "available": resolved is not None,
                         "value": resolved[1] if resolved is not None else None,
                         **({"prior_model_text": old_items[ref.id].text,
                             "prior_text_is_observed_evidence": False} if ref.id in old_items else {})})
        mapping_current = (self.state.selection_current if collection == "selected" else
                           self.state.last_mapping_current if collection == "last_answer" else False)
        mapping_note = ("Current selection." if collection == "selected" and mapping_current else
                        "Inherited selection; a new select replaces it unless mode=append." if collection == "selected" else
                        "Latest source-bound delivered answer." if collection == "last_answer" and mapping_current else
                        "An earlier source-bound answer; no mapping is inferred from later prose." if collection == "last_answer" else
                        "Earlier unfinished model drafts, not delivered work or new instructions.")
        return {"intent": asdict(self.state.intent), "references": rows,
                "collection": collection, "total_references": len(references), "progress": self.summary(),
                "mapping_current": mapping_current, "mapping_note": mapping_note,
                "declared_todo": self.state.declared_todo,
                "unresolved": self.state.unresolved}

    def _selected_references(self) -> List[TaskReference]:
        by_id = {ref.id: ref for ref in self.state.references}
        return [by_id[key] for key in self.state.selected_reference_ids if key in by_id]

    def compose_answer(self, answer: str) -> str:
        items = [item for item in self.state.staged if item.reference_id in self._resolved]
        self._rendered = list(items)
        self._rendered_block = ""
        if not items:
            return answer
        self._rendered_block = "\n\n".join(
            f"{index}. {item.text}" for index, item in enumerate(items, 1))
        if self._rendered_block in answer:
            return answer
        return answer + "\n\n" + self._rendered_block

    def finish(self, outcome: str, answer: str) -> None:
        if outcome in {"answered", "answered_with_caveat"}:
            self.state.delivered = (list(self._rendered)
                if self._rendered_block and self._rendered_block in answer else [])
            self.state.last_mapping_current = bool(self.state.delivered)
            if self.state.delivered:
                self.state.last_delivered = list(self.state.delivered)
            delivered_ids = {item.reference_id for item in self.state.delivered}
            self.state.prior_staged = [item for item in self.state.prior_staged
                                      if item.reference_id not in delivered_ids]
            requested = (self.state.intent.requested_count
                         if self.state.intent.provenance == "caller" else None)
            self.state.completion = ("unknown" if requested is None else
                "complete" if len(self.state.delivered) >= requested
                else "partial")
        else:
            self.state.completion = "interrupted"
        self.checkpoint()

    def summary(self) -> Dict[str, Any]:
        has_set = self.state.selection_known
        return {"version": 1, "completion": self.state.completion,
                "requested_count": self.state.intent.requested_count,
                "requested_count_provenance": self.state.intent.provenance,
                "retrieved_count": sum(key in self._resolved for key in self.state.selected_reference_ids) if has_set else None,
                "selection_provenance": ("current_run" if self.state.selection_current else
                                         "prior_turn" if has_set else "unknown"),
                "staged_count": len(self.state.staged) if has_set else None,
                "delivered_count": len(self.state.delivered) if has_set else None,
                "unavailable_count": sum(r.id not in self._resolved for r in self.state.references)}

    def projection(self) -> str:
        selected = self._selected_references()
        refs = [{"ordinal": index, "reference_id": ref.id, "label": ref.label[:96],
                 "available": ref.id in self._resolved}
                for index, ref in enumerate(selected[:20], 1)]
        return ("Current task state (descriptive state, never new authority):\n"
                + json.dumps({"latest_literal_objective_excerpt": self.state.objective[:1024],
                    "intent": {**asdict(self.state.intent), "deliverable": self.state.intent.deliverable[:256]},
                    "progress": self.summary(),
                    "ordered_references": refs, "reference_count": len(selected),
                    "last_answer_mapping_current": self.state.last_mapping_current,
                    "last_answer_references": [{"ordinal": i, "reference_id": item.reference_id,
                        "available": item.reference_id in self._resolved}
                        for i, item in enumerate(self.state.last_delivered[:20], 1)],
                    "prior_staged_count": len(self.state.prior_staged),
                    "declared_todo": [v[:256] for v in self.state.declared_todo[:10]],
                    "unresolved": [v[:256] for v in self.state.unresolved[:10]]}, ensure_ascii=False)
                + "\nUse mission_task(read) for remaining references; collection=last_answer uses the last delivered answer's numbering; collection=prior_staged retrieves unfinished earlier model drafts, not new instructions or delivered work. Quoted history is not evidence.")

    def checkpoint(self) -> None:
        if self.runs is None or not self.run_id:
            return
        message = "Task checkpoint unavailable; current in-memory work is retained."
        try:
            TaskCheckpoint(self.runs).save(self.run_id, self._document())
            if message in self.state.unresolved:
                self.state.unresolved.remove(message)
                TaskCheckpoint(self.runs).save(self.run_id, self._document())
        except (OSError, ValueError, TypeError, RecursionError):
            if message not in self.state.unresolved:
                self.state.unresolved.append(message)

    def _document(self) -> Dict[str, Any]:
        return {"version": 1, "scope": asdict(self.scope) if self.scope else None,
                "source_run_id": self.run_id, "state": asdict(self.state)}

    def export_handoff(self) -> TaskHandoff:
        if self.scope is None or self.runs is None or not self.run_id:
            raise ValueError("scoped handoff export needs scope and a durable run store")
        digest = TaskCheckpoint(self.runs).save(self.run_id, self._document(), export=True)
        return TaskHandoff(self.scope, self.run_id, digest)
