"""Private, run-bound conversation checkpoints; never a second event stream.

History remains quotation, not tool evidence or renewed authorization. The
existing run store owns the directory; only a digest/status goes into its
listable metadata. Credential redaction happens before bytes reach disk.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional, Tuple

from core.durable import RunStore, atomic_write_text
from core.redact import scrub_secrets
from core.runtime.mission import HISTORY_MAX_CHARS, validate_history


FILENAME = "conversation-history.json"
META_KEY = "conversation_history"
UNAVAILABLE = ("The original conversation history could not be restored. "
               "Earlier h-handles are unavailable; do not guess their text "
               "or substitute a different conversation.")
# JSON escaping can expand each input character to six bytes. The extra
# space accommodates the bounded turn envelopes, run ID and redaction labels.
MAX_BYTES = HISTORY_MAX_CHARS * 8 + 65536


def save(store: RunStore, run_id: str, turns: Any) -> None:
    """Checkpoint once, before the first request. Never overwrite a run's seed.

    Caller reports failures but can continue in memory. A pending marker means
    that a crash/write failure cannot make resume treat this as a legacy run.
    Empty history needs no checkpoint, preserving the old no-history layout.
    """
    messages = validate_history(turns)
    if not messages:
        return
    if META_KEY in store.meta(run_id).meta:
        raise ValueError("this run already has a conversation history checkpoint")
    safe = [{"role": item["role"], "content": scrub_secrets(item["content"])}
            for item in messages]
    value = {"version": 1, "run_id": run_id, "messages": safe}
    data = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if len(data.encode("utf-8")) > MAX_BYTES:
        raise ValueError("redacted history exceeds the checkpoint byte allowance")
    digest = hashlib.sha256(data.encode("utf-8")).hexdigest()
    store.update_meta(run_id, **{META_KEY: {"state": "pending", "version": 1}})
    # atomic_write_text stages beside the destination with mode 0600, flushes
    # and fsyncs the file, then replaces it. Do not change that owner here.
    atomic_write_text(store.directory(run_id) / FILENAME, data)
    store.update_meta(run_id, **{META_KEY: {
        "state": "ready", "version": 1, "sha256": digest,
        "turns": len(safe), "redacted": safe != messages,
    }})


def load(store: RunStore, run_id: str, meta: Dict[str, Any]
         ) -> Tuple[Optional[List[Dict[str, str]]], str]:
    """None means legacy/no checkpoint; [] plus a notice means lost history.

    Only the fixed file in this run is read. Digest and embedded run ID detect
    torn/mixed snapshots; neither is a claim of authenticity against a writer
    who already controls the run directory. A damaged archive does not kill
    usable tool receipts or invite a replay of side effects.
    """
    if META_KEY not in meta:
        return None, ""
    ref = meta[META_KEY]
    try:
        if not isinstance(ref, dict) or ref.get("state") != "ready":
            return [], UNAVAILABLE
        with (store.directory(run_id) / FILENAME).open("rb") as handle:
            data = handle.read(MAX_BYTES + 1)
        return decode(run_id, meta, data)
    except (OSError, ValueError, TypeError):
        return [], UNAVAILABLE


def decode(run_id: str, meta: Dict[str, Any], data: bytes
           ) -> Tuple[Optional[List[Dict[str, str]]], str]:
    """Validate captured history without filesystem access or execution state."""
    if META_KEY not in meta:
        return None, ""
    ref = meta[META_KEY]
    try:
        if (not isinstance(ref, dict) or ref.get("state") != "ready"
                or type(ref.get("version")) is not int or ref["version"] != 1
                or type(ref.get("turns")) is not int):
            return [], UNAVAILABLE
        if len(data) > MAX_BYTES or hashlib.sha256(data).hexdigest() != ref.get("sha256"):
            return [], UNAVAILABLE
        value = json.loads(data)
        if (not isinstance(value, dict) or value.get("version") != 1
                or value.get("run_id") != run_id):
            return [], UNAVAILABLE
        # Redaction labels can be longer than the credential they replace.
        # Input admission used the original cap; do not reject its safe copy.
        turns = validate_history(value.get("messages"), max_chars=MAX_BYTES)
        if len(turns) != ref.get("turns"):
            return [], UNAVAILABLE
    except (OSError, ValueError, TypeError):
        return [], UNAVAILABLE
    notice = ("Conversation history restored with credentials redacted."
              if ref.get("redacted") else "")
    return turns, notice
