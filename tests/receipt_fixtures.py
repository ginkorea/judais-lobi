"""Verify private receipt contents before normalizing only fresh locators."""

from copy import deepcopy
from dataclasses import asdict
import hashlib
import json

from core.runtime.receipt_checkpoint import ReceiptCheckpoint


def verified_receipts(records, runs):
    run_id = records[0]["run_id"]
    rows, payloads = deepcopy(records), []
    for row in rows:
        if row["event"] != "tool_result":
            continue
        ref = row["receipt"]
        assert set(ref) == {"version", "state", "id", "sha256", "bytes", "redacted"}
        assert ref["version"] == 1 and ref["state"] == "ready"
        raw = (runs.directory(run_id) / "receipts" / (ref["id"] + ".json")).read_bytes()
        assert len(raw) == ref["bytes"]
        assert hashlib.sha256(raw).hexdigest() == ref["sha256"]
        loaded = ReceiptCheckpoint(runs, run_id).load(row)
        assert loaded.receipt is not None and not loaded.notice
        receipt, origin = loaded.receipt, loaded.receipt.origin
        assert origin.run_id == run_id and origin.receipt_id == ref["id"]
        assert origin.sha256 == ref["sha256"] and origin.handle == row["handle"]
        assert origin.index == row["index"] and origin.branch == row.get("branch", "")
        assert origin.call == row.get("call", 0)
        assert receipt.tool == row["tool"] and receipt.arguments == row["arguments"]
        assert receipt.exit_code == row["exit_code"]
        assert receipt.quoted_history == row.get("quoted_history", False)
        assert receipt.redacted == ref["redacted"] == row.get("redacted_receipt", False)
        payload = asdict(receipt)
        # Replay canonicalizes JSON object key order. Compare typed values,
        # not an incidental serialization, after verifying exact archive bytes.
        payload["evidence"] = json.dumps(receipt.structured, sort_keys=True,
                                         ensure_ascii=False, allow_nan=False)
        payload["error"] = loaded.error
        payload["origin"] = {key: value for key, value in asdict(origin).items()
                             if key not in {"run_id", "receipt_id", "sha256"}}
        payloads.append(payload)
        row["receipt"] = {**ref, "id": "<random-receipt-id>", "sha256": "<verified-digest>"}
    assert payloads
    return rows, payloads


def historical_receipts(expected, actual, runs, recorded_tools):
    """Add a descriptor only after its full payload matches the old tool log.

    Historical recordings predate private archives. Their tool I/O log still
    owns the exact structured payload. No field is removed from either stream.
    """
    actual, payloads = verified_receipts(actual, runs)
    expected = deepcopy(expected)
    old = [row for row in expected if row["event"] == "tool_result"]
    new = [row for row in actual if row["event"] == "tool_result"]
    calls = [row for row in recorded_tools if "result" in row]
    assert len(old) == len(new) == len(payloads) == len(calls)
    for before, after, payload, call in zip(old, new, payloads, calls, strict=True):
        result = call["result"]
        assert payload["tool"] == call["tool"] == before["tool"]
        assert call["arguments"]["args"] == []
        assert payload["arguments"] == call["arguments"]["kwargs"] == before["arguments"]
        assert payload["text"] == result["stdout"]
        assert payload["error"] == result["stderr"]
        assert payload["evidence"] == json.dumps(result["structured"], sort_keys=True,
                                                 ensure_ascii=False, allow_nan=False)
        assert payload["exit_code"] == result["exit_code"] == before["exit_code"]
        assert payload["quoted_history"] is False and payload["redacted"] is False
        assert payload["handle"] == before["handle"]
        assert payload["origin"]["index"] == before["index"]
        assert payload["origin"]["branch"] == before.get("branch", "")
        assert payload["origin"]["call"] == before.get("call", 0)
        assert "receipt" not in before
        before["receipt"] = after["receipt"]
    return expected, actual
