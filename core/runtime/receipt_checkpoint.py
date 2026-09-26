"""Private typed receipts owned by the run store, addressed by safe references.

The event stream still owns execution order. It carries only a fixed-shape
checkpoint reference, never another copy of structured evidence. A checkpoint
does not authorize dispatch, and restoring one never dispatches anything.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import re
from typing import Any, Dict, Mapping, Optional, Union, List
import uuid

from core.durable import RunStore, atomic_write_text
from core.redact import is_credential_name, scrub_secrets
from core.runtime.results import ReceiptOrigin, StoredResult

JsonValue = Union[None, bool, int, float, str, List["JsonValue"], Dict[str, "JsonValue"]]
DIRECTORY = "receipts"
MAX_BYTES = 64 * 1024 * 1024
_ID = re.compile(r"^[0-9a-f]{32}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
UNAVAILABLE = ("A private tool receipt could not be restored; only its recorded "
               "event text is available. Its structured fields are unavailable. "
               "Do not repeat an action just to reconstruct this receipt.")
REDACTED = ("A private tool receipt was restored with credential redaction; "
            "redacted fields are not original values and must not be used as "
            "identifiers or claimed as observed measurements.")


def _safe_json(value: Any, *, secret: bool = False, path: str = "",
               changed: Optional[List[str]] = None) -> JsonValue:
    """Narrow JSON values before serialization; never redact serialized JSON.

    Credential-named scalar values are omitted as null (strings use a visible
    marker). All other JSON scalar types survive exactly. Keys that themselves
    contain a credential make the archive unavailable: renaming them could
    merge distinct records or silently rebind a later field path.
    """
    if isinstance(value, str):
        text = "<redacted:credential-field>" if secret and value else scrub_secrets(value)
        if text != value and changed is not None:
            changed.append(path)
        return text
    if value is None or type(value) in (bool, int):
        if secret and value is not None and changed is not None:
            changed.append(path)
        return None if secret else value
    if type(value) is float and math.isfinite(value):
        if secret and changed is not None:
            changed.append(path)
        return None if secret else value
    if isinstance(value, list):
        return [_safe_json(item, secret=secret, path=f"{path}/{index}", changed=changed)
                for index, item in enumerate(value)]
    if isinstance(value, dict):
        safe: Dict[str, JsonValue] = {}
        for key, item in value.items():
            if not isinstance(key, str) or scrub_secrets(key) != key:
                raise ValueError("receipt keys cannot be safely preserved")
            pointer = key.replace("~", "~0").replace("/", "~1")
            safe[key] = _safe_json(item, secret=secret or is_credential_name(key),
                                   path=f"{path}/{pointer}", changed=changed)
        return safe
    raise ValueError("receipt is not finite JSON")


@dataclass(frozen=True)
class ReceiptLoad:
    receipt: Optional[StoredResult] = None
    notice: str = ""
    error: str = ""


@dataclass(frozen=True)
class ReceiptReference:
    """A validated event pointer, not permission to read or replay a tool."""

    id: str
    sha256: str
    size_bytes: int
    redacted: bool

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> Optional[ReceiptReference]:
        if "receipt" not in record:
            return None
        ref = record["receipt"]
        if (not isinstance(ref, dict) or type(ref.get("version")) is not int
                or ref["version"] != 1 or ref.get("state") != "ready"
                or not isinstance(ref.get("id"), str) or not _ID.fullmatch(ref["id"])
                or not isinstance(ref.get("sha256"), str)
                or not _DIGEST.fullmatch(ref["sha256"])
                or type(ref.get("bytes")) is not int
                or not 0 < ref["bytes"] <= MAX_BYTES
                or type(ref.get("redacted")) is not bool):
            raise ValueError("invalid receipt reference")
        return cls(ref["id"], ref["sha256"], ref["bytes"], ref["redacted"])


class ReceiptCheckpoint:
    """One persistence adapter over the existing RunStore directory contract."""

    def __init__(self, store: RunStore, run_id: str) -> None:
        self.store = store
        self.run_id = run_id

    def save(self, result: StoredResult, *, index: int, call: int = 0,
             branch: str = "", error: str = "") -> Dict[str, JsonValue]:
        """Ready only after atomic replacement; failure leaves work in memory.

        No exception values are returned or logged. A file whose reference
        never reaches the event stream is an orphan, never replayed work.
        """
        try:
            self.store.meta(self.run_id)
            receipt_id = uuid.uuid4().hex
            identity = {"tool": result.tool, "handle": result.handle, "branch": branch}
            safe_identity = _safe_json(identity)
            if safe_identity != identity:
                return {"version": 1, "state": "unavailable", "identity_redacted": True}
            evidence = json.loads(result.evidence) if result.evidence else None
            original = {"arguments": result.arguments, "text": result.text,
                        "error": error, "evidence": evidence}
            changed: List[str] = []
            safe = _safe_json(original, changed=changed)
            document = {"version": 1, "run_id": self.run_id, "receipt_id": receipt_id,
                        "index": index, "call": call, **identity,
                        "exit_code": result.exit_code, "quoted_history": result.quoted_history,
                        "has_evidence": bool(result.evidence), "payload": safe,
                        "source_redacted": result.redacted,
                        "redacted": safe != original or result.redacted,
                        "redacted_paths": changed}
            raw = json.dumps(document, ensure_ascii=False, allow_nan=False,
                             separators=(",", ":")).encode("utf-8")
            if len(raw) > MAX_BYTES:
                return {"version": 1, "state": "unavailable"}
            digest = hashlib.sha256(raw).hexdigest()
            atomic_write_text(self.store.directory(self.run_id) / DIRECTORY /
                              (receipt_id + ".json"), raw.decode("utf-8"))
            return {"version": 1, "state": "ready", "id": receipt_id,
                    "sha256": digest, "bytes": len(raw),
                    "redacted": safe != original or result.redacted}
        except Exception:
            return {"version": 1, "state": "unavailable"}

    def load(self, record: Mapping[str, Any]) -> ReceiptLoad:
        """Bind a safe fixed-path archive to exactly this event and run.

        Hashes detect damage/mixed files, not an attacker controlling both log
        and checkpoint. Legacy events have no reference and retain old behavior.
        """
        try:
            ref = ReceiptReference.from_record(record)
            if ref is None:
                return ReceiptLoad()
            path = self.store.directory(self.run_id) / DIRECTORY / (ref.id + ".json")
            with path.open("rb") as stream:
                raw = stream.read(ref.size_bytes + 1)
            return self.decode(self.run_id, record, raw)
        except (OSError, ValueError, TypeError, KeyError, RecursionError):
            return ReceiptLoad(notice=UNAVAILABLE)

    @staticmethod
    def decode(run_id: str, record: Mapping[str, Any], raw: bytes) -> ReceiptLoad:
        """Validate already captured bytes without opening a store or dispatching.

        Uses the same event binding and redaction as local recovery. A caller
        transporting original bytes must separately refuse newly found secrets;
        this result may contain a safely redacted projection of those bytes.
        """
        try:
            ref = ReceiptReference.from_record(record)
            if ref is None:
                return ReceiptLoad()
            if len(raw) != ref.size_bytes or hashlib.sha256(raw).hexdigest() != ref.sha256:
                return ReceiptLoad(notice=UNAVAILABLE)
            doc = json.loads(raw)
            expected = {"version": 1, "run_id": run_id, "receipt_id": ref.id,
                        "index": record.get("index"), "call": record.get("call", 0),
                        "branch": record.get("branch", ""), "handle": record.get("handle"),
                        "tool": record.get("tool"), "exit_code": record.get("exit_code"),
                        "quoted_history": record.get("quoted_history") is True,
                        "source_redacted": record.get("redacted_receipt") is True}
            if not isinstance(doc, dict) or any(doc.get(k) != v for k, v in expected.items()):
                return ReceiptLoad(notice=UNAVAILABLE)
            identity = {key: doc[key] for key in ("tool", "handle", "branch")}
            if (any(not isinstance(value, str) for value in identity.values())
                    or _safe_json(identity) != identity):
                return ReceiptLoad(notice=UNAVAILABLE)
            if (type(doc.get("redacted")) is not bool or doc["redacted"] != ref.redacted
                    or type(doc.get("has_evidence")) is not bool
                    or type(doc.get("exit_code")) is not int
                    or type(doc.get("index")) is not int or type(doc.get("call")) is not int
                    or type(doc.get("quoted_history")) is not bool
                    or type(doc.get("source_redacted")) is not bool):
                return ReceiptLoad(notice=UNAVAILABLE)
            paths = doc.get("redacted_paths")
            if (not isinstance(paths, list) or any(not isinstance(p, str) for p in paths)
                    or (bool(paths) or doc["source_redacted"]) != doc["redacted"]):
                return ReceiptLoad(notice=UNAVAILABLE)
            payload = doc["payload"]
            if (not isinstance(payload, dict) or not isinstance(payload.get("arguments"), dict)
                    or not isinstance(payload.get("text"), str)
                    or not isinstance(payload.get("error"), str) or "evidence" not in payload):
                return ReceiptLoad(notice=UNAVAILABLE)
            # Narrow and re-scrub for secrets newly known by this process.
            newly_changed: List[str] = []
            safe = _safe_json(payload, changed=newly_changed)
            if not isinstance(safe, dict):
                return ReceiptLoad(notice=UNAVAILABLE)
            arguments, text, error = safe["arguments"], safe["text"], safe["error"]
            if (not isinstance(arguments, dict) or not isinstance(text, str)
                    or not isinstance(error, str)):
                return ReceiptLoad(notice=UNAVAILABLE)
            changed = doc["redacted"] or safe != payload
            origin = ReceiptOrigin(run_id, ref.id, doc["handle"], doc["branch"],
                                   doc["index"], doc["call"], ref.sha256, changed,
                                   tuple(dict.fromkeys([*paths, *newly_changed])))
            restored = StoredResult(
                handle=doc["handle"], tool=doc["tool"], arguments=arguments,
                text=text, evidence=(json.dumps(safe["evidence"], ensure_ascii=False,
                                                      allow_nan=False)
                                           if doc["has_evidence"] else ""),
                exit_code=doc["exit_code"], quoted_history=doc["quoted_history"], origin=origin,
                redacted=changed)
            return ReceiptLoad(restored, REDACTED if changed else "", error)
        except (OSError, ValueError, TypeError, KeyError, RecursionError):
            return ReceiptLoad(notice=UNAVAILABLE)
