"""Bounded local checkpoint capture wire for hosts in another Python runtime.

Invoke ``python -m core.runtime.checkpoint_export`` in the enrolled harness
environment. The caller owns authentication, conversation quiescence and export
policy. This command neither contacts a service nor resumes a run. stdin/stdout
are private pipes, not logs; errors never contain source content or paths.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path
import sys

from core.runtime.checkpoint_capture import NativeCheckpointCapture
from core.runtime.portable_checkpoint import CheckpointLimits, REFUSED, _document
from core.runtime.task_state import TaskHandoff, TaskScope

MAX_REQUEST_BYTES = 2 * 1024 * 1024


def capture_request(raw: bytes) -> bytes:
    """Versioned local-process boundary; no configuration is executed."""
    try:
        if not isinstance(raw, bytes) or not raw or len(raw) > MAX_REQUEST_BYTES:
            raise ValueError(REFUSED)
        request = _document(raw)
        if (set(request) != {"version", "root", "scope", "handoffs", "limits"}
                or type(request["version"]) is not int or request["version"] != 1
                or not isinstance(request["root"], str)
                or not Path(request["root"]).is_absolute()):
            raise ValueError(REFUSED)
        scope_record, limit_record = request["scope"], request["limits"]
        if (not isinstance(scope_record, dict) or set(scope_record) != {"owner", "thread"}
                or not isinstance(limit_record, dict)
                or set(limit_record) != {"max_bytes", "max_files", "max_runs"}):
            raise ValueError(REFUSED)
        scope = TaskScope(**scope_record)
        limits = CheckpointLimits(**limit_record)
        ceiling = CheckpointLimits()
        if (limits.max_bytes > ceiling.max_bytes or limits.max_files > ceiling.max_files
                or limits.max_runs > ceiling.max_runs):
            raise ValueError(REFUSED)
        handoffs = request["handoffs"]
        if not isinstance(handoffs, list) or not 1 <= len(handoffs) <= limits.max_files:
            raise ValueError(REFUSED)
        result = NativeCheckpointCapture(Path(request["root"]), limits).capture(
            scope, [TaskHandoff.from_record(item) for item in handoffs])
        response = {"version": 1, "scope": scope_record, "parts": [
            {"path": part.name, "content_b64": base64.b64encode(part.content).decode("ascii"),
             "sha256": part.sha256} for part in result.parts]}
        return json.dumps(response, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        raise ValueError(REFUSED) from None


def main() -> int:
    try:
        response = capture_request(sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1))
    except ValueError:
        print(REFUSED, file=sys.stderr)
        return 2
    sys.stdout.buffer.write(response)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
