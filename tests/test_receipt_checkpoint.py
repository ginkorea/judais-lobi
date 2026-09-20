"""Typed receipts survive process loss without replaying tool side effects."""

import hashlib
import json
import stat

import pytest

from core.durable import RunStore
from core.runtime import receipt_checkpoint as checkpoint
from core.runtime.contract import conforms
from core.runtime.mission import MissionRunner
from core.runtime.results import MissionResultStore
from core.runtime.resume import LOST_STRUCTURED, open_for_resume, rebuild
from core.runtime.run import NO_SUPERVISOR
from core.tools.descriptors import ToolDescriptor
from tests.test_history_recall import bus
from tests.test_resume import ScriptedModel, Stop, hard_kill, tool_call


PAYLOAD = {"rows": [{"id": "item-1", "score": 1.25, "rank": 1,
                     "enabled": True, "missing": None},
                    {"id": "item-2", "score": 0.0, "tags": ["α", False]}]}


def saved(tmp_path, *, payload=PAYLOAD, quoted=False, name="lookup", branch=""):
    store = RunStore(tmp_path / "runs")
    run_id = store.create().run_id
    result = MissionResultStore().record(name, {"limit": 2}, text="Two records.",
        evidence=json.dumps(payload), quoted_history=quoted)
    archive = checkpoint.ReceiptCheckpoint(store, run_id)
    ref = archive.save(result, index=2, call=1, branch=branch)
    record = {"event": "tool_result", "index": 2, "call": 1, "tool": name,
              "arguments": {"limit": 2}, "output": "Two records.", "error": "",
              "exit_code": 0, "handle": "r1", "receipt": ref}
    if quoted:
        record["quoted_history"] = True
    if branch:
        record["branch"] = branch
    return store, archive, record


def archive_path(store, run_id, record):
    return store.directory(run_id) / checkpoint.DIRECTORY / (record["receipt"]["id"] + ".json")


def test_roundtrip_preserves_json_types_and_private_identity(tmp_path):
    store, archive, record = saved(tmp_path)
    loaded = archive.load(record)
    assert loaded.notice == ""
    assert loaded.receipt.structured == PAYLOAD
    row = loaded.receipt.structured["rows"][0]
    assert type(row["rank"]) is int and type(row["enabled"]) is bool
    assert type(row["score"]) is float and row["missing"] is None
    assert loaded.receipt.origin.run_id == archive.run_id
    assert loaded.receipt.origin.handle == "r1"
    assert loaded.receipt.origin.index == 2 and loaded.receipt.origin.call == 1
    path = archive_path(store, archive.run_id, record)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert "item-1" not in store.meta_path(archive.run_id).read_text()
    assert "item-1" not in json.dumps(record["receipt"])
    assert store.records(archive.run_id) == []


@pytest.mark.parametrize("payload", [None, False, 0, 1.25, "ordinary text", [1, "two", None]])
def test_top_level_json_value_is_not_forced_into_an_object(tmp_path, payload):
    _, archive, record = saved(tmp_path, payload=payload)
    restored = archive.load(record).receipt.structured
    assert restored == payload and type(restored) is type(payload)


def test_recursive_redaction_keeps_json_valid_and_original_in_memory(tmp_path, monkeypatch):
    secret = "dummy-unknown-field-secret-123456"
    monkeypatch.setenv("TAIPAN_TOKEN", secret)
    payload = {"rows": [{"id": "item-1", "secret_note": secret}],
               "description": secret, "api_key": "short", "password": 1234,
               "url": "https://example.org/data?token=unseen-credential&limit=2",
               "normal": {"count": 2, "rate": 1.25, "active": True, "none": None}}
    store, archive, record = saved(tmp_path, payload=payload)
    raw = archive_path(store, archive.run_id, record).read_text()
    assert secret not in raw and "unseen-credential" not in raw and '"short"' not in raw
    assert '1234' not in raw
    loaded = archive.load(record)
    assert loaded.notice == checkpoint.REDACTED and loaded.receipt.origin.redacted
    assert loaded.receipt.structured["normal"] == payload["normal"]
    assert loaded.receipt.structured["password"] is None
    assert "/evidence/description" in loaded.receipt.origin.redacted_paths
    assert loaded.receipt.structured["rows"][0]["id"] == "item-1"
    assert payload["description"] == secret
    assert secret not in json.dumps(record["receipt"])


def test_newly_known_secret_is_redacted_again_on_read(tmp_path, monkeypatch):
    secret = "dummy-later-credential-99999"
    store, archive, record = saved(tmp_path, payload={"description": secret})
    assert record["receipt"]["redacted"] is False
    monkeypatch.setenv("NEW_SERVICE_TOKEN", secret)
    loaded = archive.load(record)
    assert secret not in loaded.receipt.evidence
    assert loaded.receipt.origin.redacted and loaded.notice == checkpoint.REDACTED


def test_credential_in_identity_or_json_key_is_not_silently_renamed(tmp_path, monkeypatch):
    secret = "dummy-sensitive-identity-123456"
    monkeypatch.setenv("NEW_SERVICE_TOKEN", secret)
    store, archive, record = saved(tmp_path, name=secret)
    assert record["receipt"] == {"version": 1, "state": "unavailable", "identity_redacted": True}
    assert not (store.directory(archive.run_id) / checkpoint.DIRECTORY).exists()
    _, archive, record = saved(tmp_path, payload={secret: "value"})
    assert record["receipt"]["state"] == "unavailable"
    assert archive.load(record).notice == checkpoint.UNAVAILABLE


@pytest.mark.parametrize("damage", ["missing", "truncated", "digest", "length", "oversize",
    "foreign_run", "foreign_id", "wrong_handle", "wrong_tool", "wrong_branch", "wrong_index",
    "wrong_call", "wrong_exit", "wrong_trust", "schema", "version", "redacted", "null", "traversal"])
def test_damaged_receipt_never_becomes_typed_evidence(tmp_path, damage):
    store, archive, record = saved(tmp_path)
    ref = record["receipt"]
    path = archive_path(store, archive.run_id, record)
    if damage == "missing":
        path.unlink()
    elif damage == "truncated":
        path.write_text("{")
    elif damage == "digest":
        ref["sha256"] = "0" * 64
    elif damage == "length":
        ref["bytes"] += 1
    elif damage == "oversize":
        ref["bytes"] = checkpoint.MAX_BYTES + 1
    elif damage == "null":
        record["receipt"] = None
    elif damage == "traversal":
        ref["id"] = "../meta"
    else:
        doc = json.loads(path.read_text())
        changes = {"foreign_run": ("run_id", store.create().run_id),
                   "foreign_id": ("receipt_id", "0" * 32), "wrong_handle": ("handle", "r2"),
                   "wrong_tool": ("tool", "other"), "wrong_branch": ("branch", "child"),
                   "wrong_index": ("index", 3), "wrong_call": ("call", 0),
                   "wrong_exit": ("exit_code", 1), "wrong_trust": ("quoted_history", True),
                   "schema": ("payload", {"text": 123}), "version": ("version", 2),
                   "redacted": ("redacted", True)}
        key, value = changes[damage]
        doc[key] = value
        raw = json.dumps(doc).encode()
        path.write_bytes(raw)
        ref["sha256"], ref["bytes"] = hashlib.sha256(raw).hexdigest(), len(raw)
    loaded = archive.load(record)
    assert loaded.receipt is None and loaded.notice == checkpoint.UNAVAILABLE


@pytest.mark.parametrize("failure", ["write", "fsync", "replace", "redact", "limit"])
def test_save_failures_are_explicit_and_do_not_claim_ready(tmp_path, monkeypatch, failure):
    def fail(*args, **kwargs):
        raise OSError("dummy-secret-error-never-reported")
    if failure in {"fsync", "replace"}:
        import core.durable as durable
        monkeypatch.setattr(durable.os, failure, fail)
    elif failure == "redact":
        monkeypatch.setattr(checkpoint, "scrub_secrets", fail)
    elif failure == "limit":
        monkeypatch.setattr(checkpoint, "MAX_BYTES", 1)
    else:
        monkeypatch.setattr(checkpoint, "atomic_write_text", fail)
    # Establish RunStore metadata before sabotaging its shared atomic writer.
    if failure in {"fsync", "replace"}:
        monkeypatch.undo()
        store, archive, record = saved(tmp_path)
        monkeypatch.setattr(durable.os, failure, fail)
        result = MissionResultStore().record("lookup", evidence='{"ok":true}')
        record["receipt"] = archive.save(result, index=2)
    else:
        store, archive, record = saved(tmp_path)
    assert record["receipt"] == {"version": 1, "state": "unavailable"}
    assert not list(store.directory(archive.run_id).rglob("*.tmp"))
    assert archive.load(record).notice == checkpoint.UNAVAILABLE


def interrupted(tmp_path, protocol="json", *, quoted=False, payload=PAYLOAD):
    store = RunStore(tmp_path / "runs")
    run_id = store.create().run_id
    plane, calls = bus(), []
    def lookup(**kwargs):
        calls.append(kwargs)
        return (0, "Two records.", "", json.dumps(payload))
    plane.register(ToolDescriptor(tool_name="lookup", input_schema={"type": "object"}), lookup)
    name, args = ("mission_result", {"handle": "h1"}) if quoted else ("lookup", {})
    if protocol == "native":
        reply = ""
        native = {"tool_calls_fn": lambda: [{"id": "read", "name": name, "arguments": args}]}
    else:
        reply = tool_call(name, **args)
        native = {}
    runner = MissionRunner(ScriptedModel(reply, Stop), plane, ["lookup"],
        history=[{"role": "assistant", "content": "Old unverified assertion."}] if quoted else (),
        run_store=store, run_id=run_id, max_steps=5, protocol=protocol, **native,
        supervisor=NO_SUPERVISOR)
    with pytest.raises(ScriptedModel.Stop):
        runner.run("Read the second record")
    hard_kill(store, run_id)
    return store, run_id, plane, calls


@pytest.mark.parametrize("protocol", ["json", "native"])
def test_actual_restart_restores_fields_without_repeating_dispatch(tmp_path, protocol):
    store, run_id, plane, calls = interrupted(tmp_path, protocol)
    records = store.records(run_id)
    assert all(not conforms(record) for record in records)
    event = next(r for r in records if r["event"] == "tool_result")
    assert event["receipt"]["state"] == "ready"
    assert "item-2" not in store.log_path(run_id).read_text()
    fresh = RunStore(store.root)
    recorded = open_for_resume(fresh, run_id)
    if protocol == "native":
        answer = ""
        native = {"tool_calls_fn": lambda: [{"id": "finish", "name": "mission_answer",
                                               "arguments": {"text": "Second record retained."}}]}
    else:
        answer = '{"answer":"Second record retained."}'
        native = {}
    runner = MissionRunner(ScriptedModel(answer), plane, ["lookup"],
        run_store=fresh, run_id=run_id, max_steps=5, protocol=protocol, **native,
        supervisor=NO_SUPERVISOR)
    state = rebuild(runner, recorded)
    assert LOST_STRUCTURED not in state.lost
    assert state.store.get("r1").structured == PAYLOAD
    assert "item-2" in state.store.read("r1", path="rows[1].id")[1]
    assert runner.run(recorded.objective, state).outcome == "answered"
    assert calls == [{}]


def test_archive_failure_keeps_recorded_text_and_continues(tmp_path):
    store, run_id, plane, calls = interrupted(tmp_path)
    event = next(r for r in store.records(run_id) if r["event"] == "tool_result")
    archive_path(store, run_id, event).unlink()
    runner = MissionRunner(ScriptedModel('{"answer":"Only recorded text remains."}'),
        plane, ["lookup"], max_steps=5, supervisor=NO_SUPERVISOR)
    state = rebuild(runner, open_for_resume(store, run_id))
    assert state.store.get("r1").structured is None
    assert state.store.get("r1").text == "Two records."
    assert checkpoint.UNAVAILABLE in state.lost
    assert checkpoint.UNAVAILABLE in json.dumps(state.tail)
    assert runner.run(state.objective, state).outcome == "answered"
    assert calls == [{}]


def test_checkpoint_write_failure_does_not_refuse_live_dispatch(tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise OSError("dummy-secret-error-never-reported")
    monkeypatch.setattr(checkpoint, "atomic_write_text", fail)
    store, run_id, plane, calls = interrupted(tmp_path)
    event = next(r for r in store.records(run_id) if r["event"] == "tool_result")
    assert event["exit_code"] == 0
    assert event["receipt"] == {"version": 1, "state": "unavailable"}
    assert "dummy-secret-error" not in store.log_path(run_id).read_text()
    assert calls == [{}]


@pytest.mark.parametrize("legacy", [False, True])
def test_partial_recovery_does_not_claim_healthy_receipts_were_lost(tmp_path, legacy):
    from core.runtime.resume import _note_receipt_loss, _restore_result
    store, archive, first = saved(tmp_path)
    result = MissionResultStore().record("lookup", text="Another record.",
                                       evidence=json.dumps(PAYLOAD))
    second = {**first, "index": 3, "output": "Another record.",
              "receipt": archive.save(result, index=3, call=1)}
    if legacy:
        del first["receipt"]
    else:
        archive_path(store, archive.run_id, first).unlink()
    restored, lost = MissionResultStore(), []
    _restore_result(restored, first, archive, lost)
    _restore_result(restored, second, archive, lost)
    _note_receipt_loss(restored, lost, LOST_STRUCTURED)
    assert restored.get("r1").structured is None
    assert restored.get("r2").structured == PAYLOAD
    assert restored.get("r2").origin.index == 3
    assert LOST_STRUCTURED not in lost
    assert any("1 replayed tool result(s)" in item for item in lost)


def test_redacted_source_reread_stays_marked_after_second_restart(tmp_path, monkeypatch):
    secret = "dummy-record-identity-secret-12345"
    monkeypatch.setenv("SERVICE_TOKEN", secret)
    store, run_id, plane, calls = interrupted(tmp_path, payload={"rows": [{"id": secret}]})
    runner = MissionRunner(ScriptedModel(tool_call("mission_result", handle="r1",
        path="rows[0].id"), Stop), plane, ["lookup"], run_store=store, run_id=run_id,
        max_steps=5, supervisor=NO_SUPERVISOR)
    state = rebuild(runner, open_for_resume(store, run_id))
    assert state.store.get("r1").redacted
    with pytest.raises(ScriptedModel.Stop):
        runner.run(state.objective, state)
    hard_kill(store, run_id)
    events = [r for r in store.records(run_id) if r["event"] == "tool_result"]
    assert len(events) == 2 and events[1]["redacted_receipt"] is True
    assert events[1]["receipt"]["redacted"] is True
    second = MissionRunner(ScriptedModel(), plane, ["lookup"], max_steps=5,
                           supervisor=NO_SUPERVISOR)
    restored = rebuild(second, open_for_resume(RunStore(store.root), run_id))
    assert restored.store.get("r2").redacted
    assert restored.store.get("r2").origin.redacted
    assert "not original identifiers" in restored.store.read("r2")[1]
    assert secret not in restored.store.read("r2")[1]
    assert checkpoint.REDACTED in restored.lost
    assert calls == [{}]


@pytest.mark.parametrize("protocol", ["json", "native"])
def test_quoted_history_receipt_stays_out_of_grounding(tmp_path, protocol):
    store, run_id, plane, calls = interrupted(tmp_path, protocol, quoted=True)
    runner = MissionRunner(ScriptedModel(), plane, ["lookup"], max_steps=5,
                           protocol=protocol, supervisor=NO_SUPERVISOR)
    state = rebuild(runner, open_for_resume(store, run_id))
    assert state.store.get("r1").quoted_history
    assert state.store.get("r1").origin is not None
    assert state.store.evidence_texts() == [] and calls == []


def test_legacy_record_without_descriptor_keeps_old_behavior(tmp_path):
    store, archive, record = saved(tmp_path)
    del record["receipt"]
    assert archive.load(record) == checkpoint.ReceiptLoad()


def test_staged_receipts_keep_same_local_handles_in_distinct_branches(tmp_path):
    from core.runtime.swarm import SwarmRunner
    from tests.test_swarm import STAGED, plan
    store = RunStore(tmp_path / "runs")
    run_id = store.create().run_id
    plane, calls = bus(), []
    def lookup(**kw):
        calls.append(kw)
        return (0, "A result.", "", json.dumps({"item": kw["item"]}))
    plane.register(ToolDescriptor(tool_name="lookup"), lookup)
    executor = ScriptedModel(tool_call("lookup", item="one"), '{"answer":"one"}',
                             tool_call("lookup", item="two"), Stop)
    runner = SwarmRunner(executor, plane, ["lookup"], plain_chat_fn=ScriptedModel(
        STAGED, plan({"id": "s1", "goal": "Read one", "rung": "tool"},
                     {"id": "s2", "goal": "Read two", "rung": "tool", "needs": ["s1"]})),
        run_store=store, run_id=run_id, max_steps=8, supervisor=NO_SUPERVISOR)
    try:
        runner.run("Read both")
    except ScriptedModel.Stop:
        pass
    hard_kill(store, run_id)
    events = [r for r in store.records(run_id) if r["event"] == "tool_result"]
    assert len(events) == 2
    assert events[0]["handle"] == events[1]["handle"] == "r1"
    assert events[0]["receipt"]["id"] != events[1]["receipt"]["id"]
    restored = rebuild(runner, open_for_resume(store, run_id))
    assert [r.structured["item"] for r in restored.store.results] == ["one", "two"]
    assert [r.origin.branch for r in restored.store.results] == ["s1", "s2"]
    assert all(r.origin.handle == "r1" for r in restored.store.results)
    assert not any("raw tool output" in item for item in restored.lost)
    assert len(calls) == 2
