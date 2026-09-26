"""The cross-runtime seam stays bounded and returns only validated original bytes."""
import base64
import json
import os
import subprocess
import sys
from dataclasses import asdict

import pytest

from core.runtime.checkpoint_export import MAX_REQUEST_BYTES, capture_request
from core.runtime.portable_checkpoint import CheckpointLimits, REFUSED
from tests.test_portable_checkpoint import captured
from tests.test_task_state import SCOPE


def request_for(tmp_path):
    store, run, pointer, files, _ = captured(tmp_path, multi=True, history=True)
    request = {"version": 1, "root": str(store.directory(run).parent),
               "scope": asdict(SCOPE), "handoffs": [pointer.as_record()],
               "limits": asdict(CheckpointLimits())}
    return request, files


def test_wire_preserves_all_original_bytes(tmp_path):
    request, files = request_for(tmp_path)
    response = json.loads(capture_request(json.dumps(request).encode()))
    assert response["version"] == 1 and response["scope"] == asdict(SCOPE)
    assert {p["path"]: base64.b64decode(p["content_b64"], validate=True)
            for p in response["parts"]} == files


@pytest.mark.parametrize("change", ["unknown", "version", "relative", "scope", "limit",
                                   "pointers", "empty", "oversize", "duplicate"])
def test_bad_wire_refuses_before_any_file_is_opened(tmp_path, monkeypatch, change):
    request, _ = request_for(tmp_path)
    if change == "unknown":
        request["execute"] = True
    elif change == "version":
        request["version"] = True
    elif change == "relative":
        request["root"] = "relative/path"
    elif change == "scope":
        request["scope"]["owner"] = "foreign"
    elif change == "limit":
        request["limits"]["max_bytes"] += 1
    elif change == "pointers":
        request["handoffs"] = {}
    raw = json.dumps(request).encode()
    if change == "empty":
        raw = b""
    elif change == "oversize":
        raw = b" " * (MAX_REQUEST_BYTES + 1)
    elif change == "duplicate":
        raw = b'{"version":1,' + raw[1:]
    monkeypatch.setattr(os, "open", lambda *a, **k: pytest.fail("invalid request opened files"))
    with pytest.raises(ValueError, match=REFUSED):
        capture_request(raw)


@pytest.mark.parametrize("valid", [True, False])
def test_module_process_has_no_partial_stdout_on_refusal(tmp_path, valid):
    request, files = request_for(tmp_path)
    if not valid:
        request["handoffs"][0]["sha256"] = "0" * 64
    result = subprocess.run([sys.executable, "-m", "core.runtime.checkpoint_export"],
                            input=json.dumps(request).encode(), capture_output=True, timeout=30)
    if valid:
        assert result.returncode == 0, result.stderr
        assert not result.stderr
        assert len(json.loads(result.stdout)["parts"]) == len(files)
    else:
        assert result.returncode == 2
        assert not result.stdout
        assert result.stderr.decode().strip() == REFUSED
