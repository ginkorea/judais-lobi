"""Current objectives and ordered evidence survive without replaying work."""

import hashlib
import json
import stat
from types import SimpleNamespace

import pytest

from core.cli import _recorded_task_context, _run_meta_flags, _task_context
from core.durable import RunStore
from core.runtime import task_state as module
from core.runtime.mission import MissionRunner
from core.runtime.receipt_checkpoint import ReceiptCheckpoint
from core.runtime.results import MissionResultStore
from core.runtime.run import NO_SUPERVISOR
from core.runtime.task_state import TaskContext, TaskHandoff, TaskIntent, TaskScope
from core.tools.descriptors import ToolDescriptor
from tests.test_history_recall import bus
from tests.test_mission import ScriptedModel, tool_call
from tests.test_conversation_compaction import history, window
from tests.test_resume import ScriptedModel as StoppableModel, Stop, hard_kill
from core.runtime.resume import open_for_resume, rebuild
from core.runtime.swarm import SwarmRunner
from core.runtime.grounding import GroundingConfig, GroundingValidator
from tests.test_swarm import DIRECT, STAGED, plan


DATA = {"records": [{"name": "First", "value": 1, "valid": True},
                    {"name": "Second", "value": None, "valid": False}]}
SCOPE = TaskScope("owner-a", "thread-a")


def invoke(context, results, operation, **kwargs):
    with context.using(results):
        code, text, error = context.execute(operation, **kwargs)
    assert code == 0, error
    return json.loads(text)


def prepared(tmp_path, *, payload=DATA, scope=SCOPE, intent=None):
    runs = RunStore(tmp_path / "runs")
    run_id = runs.create().run_id
    results = MissionResultStore()
    context = TaskContext(scope, intent=intent)
    context.begin("Original question", results, runs=runs, run_id=run_id)
    result = results.record("lookup", {}, text="Observed records", evidence=json.dumps(payload))
    receipt = ReceiptCheckpoint(runs, run_id).save(result, index=1)
    runs.append(run_id, {"event": "tool_result", "index": 1, "tool": "lookup",
        "handle": result.handle, "arguments": {}, "output": result.text,
        "error": "", "exit_code": 0, "receipt": receipt})
    context.observe(result, receipt)
    return runs, run_id, results, context, receipt


def selected(tmp_path, **kwargs):
    runs, run_id, results, context, receipt = prepared(tmp_path, **kwargs)
    invoke(context, results, "select", handle="r1", path="records")
    return runs, run_id, results, context, receipt


def imported(runs, pointer, objective="Expand the second item"):
    results = MissionResultStore()
    context = TaskContext(SCOPE, pointer)
    run_id = runs.create().run_id
    context.begin(objective, results, runs=runs, run_id=run_id)
    return context, results


def add_observation(runs, context, results, records):
    result = results.record("lookup", evidence=json.dumps({"records": records}))
    receipt = ReceiptCheckpoint(runs, context.run_id).save(result, index=len(results))
    runs.append(context.run_id, {"event": "tool_result", "index": len(results),
        "tool": "lookup", "handle": result.handle, "arguments": {},
        "output": "", "error": "", "exit_code": 0, "receipt": receipt})
    context.observe(result, receipt)
    return result.handle


def test_new_task_selection_replaces_active_order_without_deleting_history(tmp_path):
    runs, _, results, context, _ = selected(tmp_path)
    first = context.state.references[0]
    invoke(context, results, "stage", reference_id=first.id, text="First finding.")
    context.finish("answered", context.compose_answer("Findings"))
    restored, current = imported(runs, context.export_handoff(), "Assess other records")
    handle = add_observation(runs, restored, current, [{"name": "Other1"}, {"name": "Other2"}])
    invoke(restored, current, "select", handle=handle, path="records")
    rows = invoke(restored, current, "read")["references"]
    assert [row["value"]["name"] for row in rows] == ["Other1", "Other2"]
    assert len(restored.state.references) == 4
    old = invoke(restored, current, "read", collection="last_answer")
    assert old["references"][0]["value"]["name"] == "First"
    assert old["mapping_current"] is False
    assert restored.summary()["retrieved_count"] == 2


def test_explicit_append_preserves_10_plus_100_batch_order_across_handoff(tmp_path):
    runs, _, results, context, _ = selected(tmp_path,
        payload={"records": [{"value": i} for i in range(10)]})
    handle = add_observation(runs, context, results, [{"value": i} for i in range(10, 110)])
    invoke(context, results, "select", handle=handle, path="records", mode="append")
    restored, current = imported(runs, context.export_handoff(), "Expand item 102")
    page = invoke(restored, current, "read", offset=99, limit=11)
    assert page["total_references"] == 110
    assert [row["value"]["value"] for row in page["references"]] == list(range(99, 110))
    assert page["references"][2]["ordinal"] == 102
    assert page["mapping_current"] is False


def test_unstaged_answer_retains_explicitly_stale_source_bound_numbering(tmp_path):
    runs, _, results, context, _ = selected(tmp_path)
    invoke(context, results, "stage", reference_id=context.state.references[1].id,
           text="Second source item was delivered first.")
    context.finish("answered", context.compose_answer("Findings"))
    restored, current = imported(runs, context.export_handoff(), "Thanks")
    restored.finish("answered", "You are welcome.")
    again, rows = imported(runs, restored.export_handoff(), "Expand that finding")
    page = invoke(again, rows, "read", collection="last_answer")
    assert page["references"][0]["value"]["name"] == "Second"
    assert page["mapping_current"] is False
    assert "earlier source-bound answer" in page["mapping_note"]


@pytest.mark.parametrize("payload,path,expand,expected", [
    ({"entries": []}, "entries", True, []),
    ({"measurement": 7}, "measurement", True, [7]),
    ({"items": [{"code": "one"}]}, "items", True, [{"code": "one"}]),
    ({"payload": {"rows": [True, None, {"amount": 3.5}]}}, "payload.rows", True,
     [True, None, {"amount": 3.5}]),
    ({"series": [1, 2]}, "series", False, [[1, 2]]),
])
def test_selection_shapes_refresh_and_deduplicated_append_are_generic(
        tmp_path, payload, path, expand, expected):
    runs, _, results, context, _ = prepared(tmp_path, payload=payload)
    for mode in ("replace", "replace", "append"):
        page = invoke(context, results, "select", handle="r1", path=path,
                      expand=expand, mode=mode)
        assert [row["value"] for row in page["references"]] == expected
        assert page["progress"]["retrieved_count"] == len(expected)
        assert page["mapping_current"] is True
    restored, current = imported(runs, context.export_handoff(), "Continue with that selection")
    page = invoke(restored, current, "read")
    assert [row["value"] for row in page["references"]] == expected
    assert page["progress"]["selection_provenance"] == "prior_turn"
    assert page["mapping_current"] is False


def test_bad_selection_mode_preserves_current_reference_order(tmp_path):
    _, _, results, context, _ = selected(tmp_path)
    before = list(context.state.selected_reference_ids)
    with context.using(results):
        code, _, _ = context.execute("select", handle="r1", mode="guess")
    assert code == 1
    assert context.state.selected_reference_ids == before


def test_unknown_is_distinct_from_a_confirmed_empty_set(tmp_path):
    _, _, results, context, _ = prepared(tmp_path, payload={"records": []})
    assert context.summary()["retrieved_count"] is None
    result = invoke(context, results, "select", handle="r1", path="records")
    assert result["progress"]["retrieved_count"] == 0
    assert result["progress"]["delivered_count"] == 0


def test_explicit_caller_intent_cannot_be_overwritten_by_model(tmp_path):
    _, _, results, context, _ = prepared(tmp_path,
        intent=TaskIntent("Two measured items", 2, "caller"))
    invoke(context, results, "plan", deliverable="invented", requested_count=100,
           todo=["model says work remains"])
    assert context.state.intent.requested_count == 2
    assert context.state.interpreted_intent.requested_count == 100
    assert context.summary()["completion"] == "unknown"


def test_model_interpretation_does_not_confirm_completion(tmp_path):
    _, _, results, context, _ = selected(tmp_path)
    invoke(context, results, "plan", requested_count=1)
    context.finish("answered", "Done.")
    assert context.summary()["requested_count_provenance"] == "model"
    assert context.summary()["completion"] == "unknown"
    assert context.summary()["delivered_count"] == 0


def test_rendered_items_are_unique_and_counted_only_after_existing_answer_owner(tmp_path):
    _, _, results, context, _ = selected(tmp_path, intent=TaskIntent("items", 2, "caller"))
    first, second = context.state.references
    for ref, text in [(first, "First has value 1."), (first, "First is valid."),
                      (second, "Second is invalid.")]:
        invoke(context, results, "stage", reference_id=ref.id, text=text)
    assert context.summary()["staged_count"] == 2
    context.finish("answered", "Unrelated answer")
    assert context.summary()["delivered_count"] == 0
    answer = context.compose_answer("Measured findings:")
    assert context.compose_answer(answer) == answer
    context.finish("answered", answer)
    assert context.summary()["delivered_count"] == 2
    assert context.summary()["completion"] == "complete"


def test_pointer_is_private_small_and_contains_no_payload(tmp_path):
    runs, run_id, _, context, _ = selected(tmp_path)
    pointer = context.export_handoff()
    assert set(pointer.as_record()) == {"version", "scope", "source_run_id", "sha256"}
    assert "First" not in json.dumps(pointer.as_record())
    path = runs.directory(run_id) / "task-states" / (pointer.sha256 + ".json")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert hashlib.sha256(path.read_bytes()).hexdigest() == pointer.sha256
    assert "Observed records" not in path.read_text()


def test_latest_literal_objective_overrides_history_but_ordered_references_survive(tmp_path):
    runs, _, results, context, _ = selected(tmp_path)
    invoke(context, results, "plan", deliverable="old model instruction", requested_count=99)
    pointer = context.export_handoff()
    next_context, next_results = imported(runs, pointer, "Find something completely different")
    assert next_context.state.objective == "Find something completely different"
    assert next_context.state.intent == TaskIntent()
    assert next_context.state.interpreted_intent is None
    rows = invoke(next_context, next_results, "read")["references"]
    assert [r["value"]["name"] for r in rows] == ["First", "Second"]
    assert rows[1]["ordinal"] == 2 and rows[1]["value"]["valid"] is False
    assert next_results.evidence_texts()


def test_imported_observations_are_not_counted_as_new_execution(tmp_path):
    runs, source_id, _, context, _ = selected(tmp_path)
    restored, results = imported(runs, context.export_handoff())
    assert results.evidence_texts()
    assert results.called_tools() == ["lookup"]  # legacy caller remains unchanged
    assert results.called_tools(restored.run_id) == []
    assert results.dispatch_count(restored.run_id) == 0
    assert results.called_tools(source_id) == ["lookup"]  # same-run resume still counts
    results.record("current_tool", text="Fresh observation", evidence='{"value":3}')
    assert results.called_tools(restored.run_id) == ["current_tool"]
    assert results.dispatch_count(restored.run_id) == 1
    assert len(results) == 2  # receipt availability is independent of execution count


def test_exported_snapshot_survives_source_advancing_and_a_second_restart(tmp_path):
    runs, run_id, results, context, _ = selected(tmp_path)
    pointer = context.export_handoff()
    context.state.references.reverse()
    context.state.objective = "Later changed question"
    context.checkpoint()
    restarted = TaskContext(SCOPE)
    restarted.begin("ignored on resume", results, runs=runs, run_id=run_id, resume=True)
    assert restarted.state.objective == "Later changed question"
    next_context, next_results = imported(RunStore(runs.root), pointer)
    assert invoke(next_context, next_results, "read")["references"][1]["value"]["name"] == "Second"
    second_pointer = next_context.export_handoff()
    again, again_results = imported(RunStore(runs.root), second_pointer)
    assert invoke(again, again_results, "read")["references"][0]["value"]["name"] == "First"


def test_last_answer_numbering_is_not_confused_with_source_selection_order(tmp_path):
    runs, _, results, context, _ = selected(tmp_path)
    second = context.state.references[1]
    invoke(context, results, "stage", reference_id=second.id, text="The second observed item.")
    answer = context.compose_answer("Findings:")
    context.finish("answered", answer)
    assert "1. The second observed item." in answer
    restored, restored_results = imported(runs, context.export_handoff(), "Expand item #1")
    rows = invoke(restored, restored_results, "read", collection="last_answer")["references"]
    assert len(rows) == 1 and rows[0]["ordinal"] == 1
    assert rows[0]["value"]["name"] == "Second"
    assert restored.summary()["delivered_count"] == 0


def test_continue_retains_unfinished_source_bound_draft_without_claiming_delivery(tmp_path):
    runs, _, results, context, _ = selected(tmp_path)
    invoke(context, results, "stage", reference_id=context.state.references[0].id,
           text="Unfinished model assessment of First.")
    context.finish("interrupted", "")
    restored, restored_results = imported(runs, context.export_handoff(), "Continue")
    rows = invoke(restored, restored_results, "read", collection="prior_staged")["references"]
    assert restored.state.objective == "Continue"
    assert rows[0]["prior_model_text"] == "Unfinished model assessment of First."
    assert rows[0]["prior_text_is_observed_evidence"] is False
    assert rows[0]["value"]["name"] == "First"
    assert restored.summary()["staged_count"] == restored.summary()["delivered_count"] == 0


@pytest.mark.parametrize("damage", ["missing", "json", "digest", "redacted"])
def test_unavailable_receipts_do_not_become_original_evidence(tmp_path, monkeypatch, damage):
    runs, run_id, _, context, receipt = selected(tmp_path)
    pointer = context.export_handoff()
    path = runs.directory(run_id) / "receipts" / (receipt["id"] + ".json")
    if damage == "missing":
        path.unlink()
    elif damage == "redacted":
        monkeypatch.setenv("NEW_SECRET_TOKEN", "Observed records")
    else:
        path.write_text("{" if damage == "json" else "{}")
    next_context, results = imported(runs, pointer)
    rows = invoke(next_context, results, "read")["references"]
    assert len(rows) == 2 and all(not row["available"] for row in rows)
    assert not results.evidence_texts()
    assert next_context.summary()["unavailable_count"] == 2
    assert next_context.summary()["delivered_count"] == 0


@pytest.mark.parametrize("damage", ["missing", "json", "digest", "oversize"])
def test_bad_snapshot_is_graceful_without_any_dispatch(tmp_path, damage):
    runs, run_id, _, context, _ = selected(tmp_path)
    pointer = context.export_handoff()
    path = runs.directory(run_id) / "task-states" / (pointer.sha256 + ".json")
    if damage == "missing":
        path.unlink()
    else:
        path.write_text({"json": "{", "digest": "{}", "oversize": "x" * (module.MAX_STATE_BYTES + 1)}[damage])
    next_context, results = imported(runs, pointer)
    assert next_context.state.objective == "Expand the second item"
    assert next_context.summary()["retrieved_count"] is None
    assert "do not reconstruct" in next_context.state.unresolved[0]
    assert not results.results


@pytest.mark.parametrize("quoted,redacted,failed", [(True, False, False), (False, True, False), (False, False, True)])
def test_quoted_redacted_and_failed_results_cannot_be_selected(quoted, redacted, failed):
    context, results = TaskContext.local(), MissionResultStore()
    context.begin("Read", results)
    result = results.record("lookup", evidence=json.dumps(DATA), quoted_history=quoted,
                            redacted=redacted, exit_code=1 if failed else 0)
    with context.using(results):
        assert context.execute("select", handle=result.handle, path="records")[0] == 1
    assert context.summary()["retrieved_count"] is None


def test_scope_is_binding_not_peer_text_authority(tmp_path):
    runs, _, _, context, _ = selected(tmp_path)
    pointer = context.export_handoff()
    with pytest.raises(ValueError, match="scope"):
        TaskContext(TaskScope("other-owner", "thread-a"), pointer)
    forged = TaskHandoff(TaskScope("other-owner", "thread-a"), pointer.source_run_id, pointer.sha256)
    other = TaskContext(forged.scope, forged)
    other.begin("New actual input", MissionResultStore(), runs=runs, run_id=runs.create().run_id)
    assert not other.state.references and other.state.unresolved


def test_invalid_arguments_do_not_mutate_or_echo_secret(tmp_path, monkeypatch):
    _, _, results, context, _ = prepared(tmp_path)
    secret = "dummy-task-secret-12345"
    monkeypatch.setenv("SERVICE_TOKEN", secret)
    with context.using(results):
        outcome = context.execute("plan", deliverable=secret, requested_count=2)
        assert outcome[0] == 1 and secret not in str(outcome)
        assert context.execute("plan", requested_count=2, limit=-1)[0] == 1
    assert context.state.intent == TaskIntent()


def test_checkpoint_failure_keeps_memory_and_does_not_log_exception(tmp_path, monkeypatch):
    _, _, results, context, _ = prepared(tmp_path)
    def fail(*args, **kwargs):
        raise OSError("dummy-sensitive-file-name")
    monkeypatch.setattr(module, "atomic_write_text", fail)
    result = invoke(context, results, "select", handle="r1", path="records")
    assert result["progress"]["retrieved_count"] == 2
    assert "dummy-sensitive" not in str(context.state)


def test_cli_default_local_and_explicit_legacy_disable():
    assert isinstance(_task_context(SimpleNamespace()), TaskContext)
    assert _task_context(SimpleNamespace(no_task_state=True)) is None


@pytest.mark.parametrize("kwargs", [{"task_owner": "owner"}, {"task_thread": "thread"},
    {"task_owner": " ", "task_thread": "thread"},
    {"no_task_state": True, "task_owner": "owner", "task_thread": "thread"}])
def test_cli_invalid_scope_refuses_before_work(kwargs):
    with pytest.raises(SystemExit):
        _task_context(SimpleNamespace(**kwargs))


def test_json_run_uses_actual_receipts_and_exports_after_answer(tmp_path):
    runs = RunStore(tmp_path / "runs")
    context = TaskContext(SCOPE)
    plane, calls = bus(), []
    plane.register(ToolDescriptor(tool_name="lookup"),
        lambda: calls.append(1) or (0, "Observed", "", json.dumps(DATA)))
    model = ScriptedModel(tool_call("lookup"),
        tool_call("mission_task", operation="select", handle="r1", path="records"),
        '{"answer":"Read the two records."}')
    runner = MissionRunner(model, plane, ["lookup"], task_context=context,
        run_store=runs, run_id=runs.create().run_id, max_steps=4, supervisor=NO_SUPERVISOR)
    transcript = runner.run("Read two records")
    assert transcript.outcome == "answered" and calls == [1]
    assert context.summary()["retrieved_count"] == 2
    assert plane.get_descriptor("mission_task") is None
    restored, results = imported(runs, context.export_handoff())
    assert invoke(restored, results, "read")["references"][1]["value"]["name"] == "Second"
    assert calls == [1]


def test_library_legacy_caller_does_not_offer_task_tool():
    runner = MissionRunner(ScriptedModel('{"answer":"hello"}'), bus(), [], supervisor=NO_SUPERVISOR)
    assert "mission_task" not in runner.seed("hello")[0]["content"]
    assert runner.run("hello").outcome == "answered"


@pytest.mark.parametrize("protocol", ["json", "native"])
def test_runtime_stages_before_grounding_and_counts_real_rendered_items(tmp_path, protocol):
    runs, context, plane = RunStore(tmp_path / "runs"), TaskContext(SCOPE), bus()
    plane.register(ToolDescriptor(tool_name="lookup"), lambda: (0, "Observed", "", json.dumps(DATA)))
    calls = []
    native_call = []
    def model(messages):
        index = len(calls)
        calls.append(messages)
        if index == 0:
            name, arguments = "lookup", {}
        elif index == 1:
            name, arguments = "mission_task", {"operation": "select", "handle": "r1", "path": "records"}
        elif index == 2:
            name, arguments = "mission_task", {"operation": "stage",
                "reference_id": context.state.references[1].id, "text": "Second has no value."}
        else:
            name, arguments = "mission_answer", {"text": "Measured findings."}
        native_call[:] = [{"id": str(index), "name": name, "arguments": arguments}]
        return ("" if protocol == "native" else json.dumps({"answer": arguments["text"]})
                if name == "mission_answer" else tool_call(name, **arguments))
    runner = MissionRunner(model, plane, ["lookup"], task_context=context,
        run_store=runs, run_id=runs.create().run_id, protocol=protocol,
        tool_calls_fn=lambda: native_call, max_steps=5, supervisor=NO_SUPERVISOR)
    transcript = runner.run("Assess the second record")
    assert transcript.outcome == "answered"
    assert "1. Second has no value." in transcript.answer
    assert context.summary()["delivered_count"] == 1
    finished = runs.records(context.run_id)[-1]
    assert finished["event"] == "mission_finished"
    assert finished["task_state"]["delivered_count"] == 1


def test_actual_process_resume_retains_refs_without_repeating_lookup(tmp_path):
    runs, context, plane, calls = RunStore(tmp_path / "runs"), TaskContext(SCOPE), bus(), []
    run_id = runs.create().run_id
    plane.register(ToolDescriptor(tool_name="lookup"),
        lambda: calls.append(1) or (0, "Observed", "", json.dumps(DATA)))
    runner = MissionRunner(StoppableModel(tool_call("lookup"),
        tool_call("mission_task", operation="select", handle="r1", path="records"), Stop),
        plane, ["lookup"], task_context=context, run_store=runs, run_id=run_id,
        max_steps=8, supervisor=NO_SUPERVISOR)
    with pytest.raises(StoppableModel.Stop):
        runner.run("Read these records")
    pointer = context.export_handoff()
    hard_kill(runs, run_id)
    fresh, restored = RunStore(runs.root), TaskContext(SCOPE)
    runner = MissionRunner(ScriptedModel(tool_call("mission_task", operation="read", offset=1),
        '{"answer":"Second retained."}'), plane, ["lookup"], task_context=restored,
        run_store=fresh, run_id=run_id, max_steps=8, supervisor=NO_SUPERVISOR)
    recorded = open_for_resume(fresh, run_id)
    state = rebuild(runner, recorded)
    assert runner.run(recorded.objective, state).outcome == "answered"
    assert calls == [1] and restored.state.references[1].id == context.state.references[1].id
    next_context, next_results = imported(fresh, pointer)
    assert invoke(next_context, next_results, "read")["references"][1]["value"]["name"] == "Second"


def test_forced_compaction_keeps_current_objective_and_ordered_reference_handles(tmp_path):
    runs, _, _, context, _ = selected(tmp_path)
    restored = TaskContext(SCOPE, context.export_handoff())
    model = ScriptedModel(tool_call("mission_task", operation="read", offset=1, limit=1),
                          '{"answer":"The second observed record is Second."}')
    runner = MissionRunner(model, bus(), [], history=history(count=20, size=2000),
        task_context=restored, run_store=runs, run_id=runs.create().run_id,
        window=window(), max_steps=3, supervisor=NO_SUPERVISOR)
    transcript = runner.run("Expand the second measured item")
    assert transcript.outcome == "answered"
    records = runs.records(restored.run_id)
    assert any(row["event"] == "step_started" and row.get("compacted") for row in records)
    shown = json.dumps(model.seen)
    assert "Expand the second measured item" in shown
    assert context.state.references[1].id in shown
    assert 'Second' in shown


@pytest.mark.parametrize("route", [DIRECT, STAGED])
def test_swarm_routes_share_task_receipts_and_release_local_tool(tmp_path, route):
    runs, context, plane = RunStore(tmp_path / "runs"), TaskContext(SCOPE), bus()
    plane.register(ToolDescriptor(tool_name="lookup"), lambda: (0, "Observed", "", json.dumps(DATA)))
    plain = ScriptedModel(route, plan({"id": "one", "goal": "Read rows", "rung": "tool"}),
                          '{"answer":"Read complete."}')
    executor = ScriptedModel(tool_call("lookup"),
        tool_call("mission_task", operation="select", handle="r1", path="records"),
        '{"answer":"Read complete."}')
    runner = SwarmRunner(executor, plane, ["lookup"], plain_chat_fn=plain,
        task_context=context, run_store=runs, run_id=runs.create().run_id,
        max_steps=10, supervisor=NO_SUPERVISOR)
    result = runner.run("Read all records")
    assert result.outcome == "answered"
    assert context.summary()["retrieved_count"] == 2
    assert plane.get_descriptor("mission_task") is None
    next_context, results = imported(runs, context.export_handoff())
    assert invoke(next_context, results, "read")["references"][1]["value"]["name"] == "Second"


def test_model_task_metadata_cannot_launder_invented_identifiers_into_evidence(tmp_path):
    context = TaskContext.local()
    validator = GroundingValidator.from_config(GroundingConfig(
        identifier_pattern=r"\basset\.[a-z0-9]+\b", max_repairs=0))
    runner = MissionRunner(ScriptedModel(
        tool_call("mission_task", operation="plan", deliverable="asset.fabricated"),
        tool_call("mission_result", handle="r1"),
        '{"answer":"The source is asset.fabricated."}'), bus(), [],
        task_context=context, validator=validator, max_steps=4, supervisor=NO_SUPERVISOR)
    result = runner.run("Describe only observed evidence")
    assert result.outcome == "answered_with_caveat"
    assert not result.grounding.grounded
    assert runner._run.results.get("r1").quoted_history
    assert runner._run.results.get("r2").quoted_history
    assert runner._run.results.evidence_texts() == []


def test_cli_writes_and_reads_private_scoped_pointer(tmp_path):
    from tests.test_facade import cli_elf, run_cli, write_skill
    first, second = tmp_path / "first.json", tmp_path / "second.json"
    mock, _ = cli_elf()
    skill = write_skill(tmp_path)
    run_cli(mock, "Read totals", "--mission", "--skill", skill,
            "--task-owner", SCOPE.owner, "--task-thread", SCOPE.thread,
            "--task-state-out", str(first))
    pointer = TaskHandoff.from_record(json.loads(first.read_text()))
    assert pointer.scope == SCOPE
    assert stat.S_IMODE(first.stat().st_mode) == 0o600
    mock, _ = cli_elf()
    run_cli(mock, "New objective", "--mission", "--skill", skill,
            "--task-owner", SCOPE.owner, "--task-thread", SCOPE.thread,
            "--task-state-in", str(first), "--task-state-out", str(second))
    next_pointer = TaskHandoff.from_record(json.loads(second.read_text()))
    assert next_pointer.source_run_id != pointer.source_run_id
    assert next_pointer.scope == pointer.scope


def test_native_cli_declares_task_tool_before_first_model_request(tmp_path):
    from tests.test_facade import local_bus, run_cli, write_skill
    from tests.test_record_replay import scripted_elf
    mock, agent = scripted_elf(("", ""), native=True, tool_calls=[
        [{"id": "c1", "name": "mission_task", "arguments": {"operation": "plan"}}],
        [{"id": "c2", "name": "mission_answer", "arguments": {"text": "Ready."}}],
    ])
    agent.tools.bus = local_bus()
    run_cli(mock, "Plan this task", "--mission", "--skill", write_skill(tmp_path),
            "--protocol", "native")
    for call in agent.client.chat.call_args_list:
        names = [row["function"]["name"] for row in call.kwargs["tools"]]
        assert names.count("mission_task") == 1
        assert names.count("mission_result") == 1
    assert agent.client.chat.call_count == 2
    assert agent.tools.bus.get_descriptor("mission_task") is None


def test_task_registration_rolls_back_when_function_namespace_update_fails():
    context, plane = TaskContext.local(), bus()

    def failed(_):
        raise RuntimeError("fixture namespace failure")

    runner = MissionRunner(ScriptedModel('{"answer":"unused"}'), plane, [],
        task_context=context, plane_changed=failed, supervisor=NO_SUPERVISOR)
    with pytest.raises(RuntimeError, match="fixture namespace failure"):
        runner.run("Question")
    assert plane.get_descriptor("mission_task") is None
    assert plane.get_descriptor("mission_result") is None


@pytest.mark.parametrize("flags,enabled", [({}, False),
    ({"task_state_enabled": False}, False), ({"task_state_enabled": True}, True)])
def test_recorded_mode_restores_legacy_or_enabled_without_inventing_scope(flags, enabled):
    args = SimpleNamespace(no_task_state=False)
    context = TaskContext.local()
    restored = _recorded_task_context(args, flags, context)
    assert (restored is context) is enabled
    assert _run_meta_flags(args)["task_state_enabled"] is enabled
    assert restored is None or restored.scope is None


@pytest.mark.parametrize("flags,current", [
    ({"task_state_enabled": "yes"}, TaskContext.local()),
    ({"task_state_enabled": True}, None),
    ({}, TaskContext(SCOPE)),
])
def test_recorded_mode_never_silently_changes_a_requested_scope_or_enabled_run(flags, current):
    with pytest.raises(SystemExit):
        _recorded_task_context(SimpleNamespace(no_task_state=False), flags, current)


@pytest.mark.parametrize("enabled", [False, True])
def test_cli_resume_restores_recorded_task_mode_without_repeating_flags(tmp_path, enabled):
    from tests.test_facade import cli_elf, run_cli, write_skill
    runs = RunStore(tmp_path / "runs")
    mock, agent = cli_elf()
    skill = write_skill(tmp_path)
    first = [tool_call("governed_view", run_id="asset.5f21", section="totals")]

    def interrupted(**kwargs):
        if first:
            return first.pop(0)
        raise RuntimeError("local fixture stopped")

    agent.client.chat.side_effect = interrupted
    with pytest.raises(SystemExit):
        run_cli(mock, "Read totals", "--mission", "--skill", skill,
                *([] if enabled else ["--no-task-state"]))
    run_id = runs.list()[0].run_id
    assert runs.meta(run_id).meta["flags"]["task_state_enabled"] is enabled
    resumed, next_agent = cli_elf(replies=('{"answer":"Done."}',))
    run_cli(resumed, "--mission", "--resume", run_id, "--skill", skill)
    seed = next_agent.seeds[0]
    assert any("Current task state" in row.get("content", "") for row in seed) is enabled
    records = runs.records(run_id)
    assert sum(row["event"] == "tool_call" for row in records) == 1
    assert ("task_state" in records[-1]) is enabled


@pytest.mark.parametrize("legacy", [False, True])
def test_cli_replay_retains_explicit_opt_out_and_legacy_namespace(tmp_path, legacy):
    from tests.test_facade import cli_elf, run_cli, write_skill
    runs, skill = RunStore(tmp_path / "runs"), write_skill(tmp_path)
    mock, _ = cli_elf()
    run_cli(mock, "Read totals", "--mission", "--skill", skill, "--no-task-state")
    source = runs.list()[0]
    if legacy:
        flags = dict(source.meta["flags"])
        flags.pop("task_state_enabled")
        runs.update_meta(source.run_id, flags=flags)
    replay, agent = cli_elf()
    agent.client.chat.side_effect = AssertionError("replay must not call a live model")
    run_cli(replay, "--mission", "--replay", source.run_id, "--skill", skill)
    child = next(run for run in runs.list() if run.run_id != source.run_id)
    records = runs.records(child.run_id)
    assert records[0]["catalogue"] == ["governed_view", "mission_result"]
    assert "task_state" not in records[-1]
    assert records[-1]["outcome"] == "answered"
    assert agent.client.chat.call_count == 0
