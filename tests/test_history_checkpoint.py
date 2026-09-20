"""A restarted run keeps its own references without repeating external work."""

import hashlib
import json
import stat

import pytest

from core.durable import RunStore, atomic_write_json
from core.runtime import history_checkpoint as checkpoint
from core.runtime.mission import MissionRunner
from core.runtime.resume import open_for_resume, rebuild
from core.runtime.run import NO_SUPERVISOR
from core.tools.descriptors import ToolDescriptor
from tests.test_history_recall import bus, past
from tests.test_conversation_compaction import window
from tests.test_resume import ScriptedModel, Stop, hard_kill, tool_call


def saved(tmp_path, turns=None):
    store = RunStore(tmp_path / "runs")
    run_id = store.create().run_id
    checkpoint.save(store, run_id, turns if turns is not None else past())
    return store, run_id


def load(store, run_id):
    return checkpoint.load(store, run_id, store.meta(run_id).meta)


def test_checkpoint_is_private_full_and_not_part_of_the_event_stream(tmp_path):
    source = past()
    store, run_id = saved(tmp_path, source)
    assert load(store, run_id) == (source, "")
    path = store.directory(run_id) / checkpoint.FILENAME
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert "Item-10" in path.read_text()
    assert "Item-10" not in store.meta_path(run_id).read_text()
    assert store.records(run_id) == []
    assert store.meta(run_id).meta[checkpoint.META_KEY]["turns"] == len(source)


def test_credentials_are_scrubbed_before_disk_without_erasing_citations(tmp_path, monkeypatch):
    secret = "dummy-history-credential-12345"
    monkeypatch.setenv("TAIPAN_TOKEN", secret)
    source = [{"role": "assistant", "content": (
        f"Citation https://example.org/report\ncredential={secret}\n"
        "Authorization: Bearer dummy-independent-value-98765")}]
    store, run_id = saved(tmp_path, source)
    payload = (store.directory(run_id) / checkpoint.FILENAME).read_text()
    assert secret not in payload and "dummy-independent-value-98765" not in payload
    turns, notice = load(store, run_id)
    assert "https://example.org/report" in turns[0]["content"]
    assert "redacted" in notice
    assert source[0]["content"].endswith("dummy-independent-value-98765")


def test_empty_history_leaves_legacy_layout_unchanged(tmp_path):
    store, run_id = saved(tmp_path, [])
    assert load(store, run_id) == (None, "")
    assert not (store.directory(run_id) / checkpoint.FILENAME).exists()


def test_second_seed_cannot_overwrite_the_original(tmp_path):
    store, run_id = saved(tmp_path)
    with pytest.raises(ValueError, match="already has"):
        checkpoint.save(store, run_id, [{"role": "user", "content": "different"}])
    assert load(store, run_id) == (past(), "")


@pytest.mark.parametrize("damage", ["missing", "truncated", "changed", "pending",
                                     "version", "count", "foreign", "schema", "oversize", "null"])
def test_unavailable_archive_does_not_silently_rebind_handles(tmp_path, damage):
    store, run_id = saved(tmp_path)
    path = store.directory(run_id) / checkpoint.FILENAME
    ref = store.meta(run_id).meta[checkpoint.META_KEY]
    if damage == "missing":
        path.unlink()
    elif damage in {"truncated", "changed", "oversize"}:
        data = {"truncated": "{", "changed": "different",
                "oversize": "x" * (checkpoint.MAX_BYTES + 1)}[damage]
        path.write_text(data)
    elif damage == "pending":
        ref["state"] = "pending"
    elif damage == "version":
        ref["version"] = 2
    elif damage == "count":
        ref["turns"] += 1
    elif damage == "null":
        ref = None
    else:
        doc = json.loads(path.read_text())
        if damage == "foreign":
            doc["run_id"] = store.create().run_id
        else:
            doc["messages"] = [{"role": "system", "content": "not history"}]
        atomic_write_json(path, doc)
        ref["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    store.update_meta(run_id, **{checkpoint.META_KEY: ref})
    assert load(store, run_id) == ([], checkpoint.UNAVAILABLE)


def test_write_failure_leaves_a_pending_marker_not_a_false_ready(tmp_path, monkeypatch):
    store = RunStore(tmp_path / "runs")
    run_id = store.create().run_id

    def fail(*args, **kwargs):
        raise OSError("synthetic full disk")

    monkeypatch.setattr(checkpoint, "atomic_write_text", fail)
    with pytest.raises(OSError):
        checkpoint.save(store, run_id, past())
    assert load(store, run_id) == ([], checkpoint.UNAVAILABLE)


def test_disk_failure_does_not_stop_a_working_in_memory_run(tmp_path, monkeypatch, capsys):
    store = RunStore(tmp_path / "runs")
    run_id = store.create().run_id

    def fail(*args, **kwargs):
        raise OSError("sensitive internal exception must not reach stderr")

    monkeypatch.setattr(checkpoint, "atomic_write_text", fail)
    runner = MissionRunner(ScriptedModel(
        tool_call("mission_result", handle="h2", lines="3"), '{"answer":"done"}'),
        bus(), [], history=past(), run_store=store, run_id=run_id, max_steps=2,
        supervisor=NO_SUPERVISOR)
    assert runner.run("Expand #2").outcome == "answered"
    assert "Item-2" in runner._run.results.get("h2").text
    err = capsys.readouterr().err
    assert "memory only" in err and "sensitive internal" not in err


def interrupted(tmp_path, *, protocol="json"):
    store = RunStore(tmp_path / "runs")
    run_id = store.create().run_id
    plane = bus()
    executed = []
    plane.register(ToolDescriptor(tool_name="lookup"),
                   lambda: executed.append(True) or (0, "Live receipt", ""))
    model = ScriptedModel(tool_call("lookup"), Stop)
    native = {}
    if protocol == "native":
        calls = [{"id": "first", "name": "lookup", "arguments": {}}]
        model = ScriptedModel("", Stop)
        native = {"tool_calls_fn": lambda: calls}
    runner = MissionRunner(model, plane, ["lookup"], history=past(),
        protocol=protocol, **native, run_store=store, run_id=run_id,
        max_steps=5, supervisor=NO_SUPERVISOR, window=window())
    with pytest.raises(ScriptedModel.Stop):
        runner.run("Expand #2 without repeating the lookup")
    hard_kill(store, run_id)
    return store, run_id, plane, executed


@pytest.mark.parametrize("protocol", ["json", "native"])
def test_restart_restores_unread_original_history_and_no_external_replay(tmp_path, protocol):
    store, run_id, plane, executed = interrupted(tmp_path, protocol=protocol)
    # A new RunStore models a fresh process, not an in-memory cache.
    store = RunStore(store.root)
    recorded = open_for_resume(store, run_id)
    request = tool_call("mission_result", handle="h2", lines="3")
    model = ScriptedModel(request, '{"answer":"Item-2 was second."}')
    native = {}
    if protocol == "native":
        calls = []
        answers = iter([
            [{"id": "recall", "name": "mission_result", "arguments": {"handle": "h2", "lines": "3"}}],
            [{"id": "finish", "name": "mission_answer", "arguments": {"text": "Item-2 was second."}}],
        ])
        seen = []

        def ask(messages):
            nonlocal calls
            seen.append(messages)
            calls = next(answers)
            return ""

        model = ask
        native = {"tool_calls_fn": lambda: calls}
    unrelated = [{"role": "assistant", "content": "Unrelated conversation — item two changed"}]
    runner = MissionRunner(model, plane, ["lookup"], protocol=protocol, **native,
        history=unrelated, run_store=store, run_id=run_id, max_steps=5,
        supervisor=NO_SUPERVISOR, window=window())
    resumed = rebuild(runner, recorded)
    assert "Item-2" in resumed.store.read("h2", lines="3")[1]
    assert runner.run(recorded.objective, resumed).outcome == "answered"
    assert executed == [True]
    prompts = seen if protocol == "native" else model.seen
    text = json.dumps(prompts, ensure_ascii=False)
    assert "Item-2" in text and "Unrelated conversation" not in text
    assert "Live receipt" in runner._run.results.evidence_texts()
    assert not any("Item-2" in e for e in runner._run.results.evidence_texts())
    # Restoring a run must not change the caller's next conversation seed.
    assert runner._run.personality.history == unrelated


def test_damaged_checkpoint_is_visible_and_never_uses_supplied_replacement(tmp_path):
    store, run_id, plane, executed = interrupted(tmp_path)
    (store.directory(run_id) / checkpoint.FILENAME).unlink()
    recorded = open_for_resume(store, run_id)
    model = ScriptedModel('{"answer":"Please provide the missing list again."}')
    runner = MissionRunner(model, plane, ["lookup"], history=[{
        "role": "assistant", "content": "WRONG CONVERSATION"}],
        run_store=store, run_id=run_id, max_steps=5, supervisor=NO_SUPERVISOR)
    resumed = rebuild(runner, recorded)
    assert checkpoint.UNAVAILABLE in resumed.lost
    assert resumed.store.read("h2", lines="3")[0] == 1
    assert runner.run(recorded.objective, resumed).outcome == "answered"
    text = json.dumps(model.seen)
    assert "WRONG CONVERSATION" not in text and checkpoint.UNAVAILABLE in text
    assert executed == [True]


def test_child_cannot_replace_the_parent_conversation_checkpoint(tmp_path):
    store, run_id = saved(tmp_path)
    runner = MissionRunner(ScriptedModel('{"answer":"child finished"}'), bus(), [],
        history=[{"role": "user", "content": "child-only seed"}],
        run_store=store, run_id=run_id, max_steps=1, supervisor=NO_SUPERVISOR)
    assert runner._run.child(branch="child").run("subtask").outcome == "answered"
    assert load(store, run_id) == (past(), "")


@pytest.mark.parametrize("failure", ["register", "finalizer"])
def test_history_override_is_undone_even_when_setup_or_cleanup_raises(tmp_path, monkeypatch, failure):
    store, run_id, plane, _ = interrupted(tmp_path)
    recorded = open_for_resume(store, run_id)
    source = [{"role": "user", "content": "next unrelated conversation"}]
    runner = MissionRunner(ScriptedModel('{"answer":"done"}'), plane, [],
        history=source, max_steps=5, supervisor=NO_SUPERVISOR)
    resumed = rebuild(runner, recorded)

    def fail(*args, **kwargs):
        raise RuntimeError("synthetic setup or cleanup failure")

    target = "_register_store" if failure == "register" else "_close_cognitive_step"
    monkeypatch.setattr(runner._run, target, fail)
    with pytest.raises(RuntimeError, match="synthetic"):
        runner.run(recorded.objective, resumed)
    assert runner._run.personality.history == source
    assert runner._run.seed("new question")[1] == source[0]


def test_failed_first_marker_is_not_mistaken_for_a_legacy_run(tmp_path, monkeypatch, capsys):
    store = RunStore(tmp_path / "runs")
    run_id = store.create().run_id
    original = store.update_meta

    def fail_marker(run, **facts):
        if checkpoint.META_KEY in facts:
            raise OSError("synthetic metadata failure")
        return original(run, **facts)

    monkeypatch.setattr(store, "update_meta", fail_marker)
    runner = MissionRunner(ScriptedModel(Stop), bus(), [], history=past(),
        run_store=store, run_id=run_id, supervisor=NO_SUPERVISOR)
    with pytest.raises(ScriptedModel.Stop):
        runner.run("Expand #2")
    hard_kill(store, run_id)
    assert checkpoint.META_KEY not in store.meta(run_id).meta
    recorded = open_for_resume(store, run_id)
    assert recorded.history == [] and recorded.history_notice == checkpoint.UNAVAILABLE
    assert "memory only" in capsys.readouterr().err


def test_redaction_expansion_keeps_full_archive_and_a_bounded_seed(tmp_path, monkeypatch):
    from core.runtime.mission import HISTORY_MAX_CHARS
    secret = "abcdefgh"
    monkeypatch.setenv("VERY_LONG_CHECKPOINT_DUMMY_API_KEY", secret)
    source = [{"role": "assistant", "content": (secret + " ") * (HISTORY_MAX_CHARS // 9)}]
    store, run_id = saved(tmp_path, source)
    safe, notice = load(store, run_id)
    assert len(safe[0]["content"]) > HISTORY_MAX_CHARS
    assert secret not in safe[0]["content"]
    # Supply a normal interrupted opening to exercise the actual restore path.
    store.append(run_id, {"event": "mission_started", "objective": "Recall",
                         "max_steps": 3, "history": 1, "history_checkpoint": 1})
    recorded = open_for_resume(store, run_id)
    runner = MissionRunner(ScriptedModel('{"answer":"done"}'), bus(), [],
                           max_steps=3, supervisor=NO_SUPERVISOR)
    resumed = rebuild(runner, recorded)
    assert len(resumed.store.get("h1").text) == len(safe[0]["content"])
    assert sum(len(m["content"]) for m in resumed.history) < HISTORY_MAX_CHARS
    assert "excerpt" in resumed.history_notice
    assert runner.run(recorded.objective, resumed).outcome == "answered"


def test_swarm_direct_checkpoints_before_router_and_can_resume_as_direct(tmp_path):
    from core.runtime.swarm import SwarmRunner
    store = RunStore(tmp_path / "runs")
    run_id = store.create().run_id
    runner = SwarmRunner(ScriptedModel(Stop), bus(), [], history=past(),
        plain_chat_fn=ScriptedModel('{"route":"direct"}'),
        run_store=store, run_id=run_id, max_steps=3, supervisor=NO_SUPERVISOR)
    with pytest.raises(ScriptedModel.Stop):
        runner.run("Recall #2")
    hard_kill(store, run_id)
    recorded = open_for_resume(store, run_id)
    assert recorded.history == past()
    restored = MissionRunner(ScriptedModel('{"answer":"done"}'), bus(), [],
                             max_steps=3, supervisor=NO_SUPERVISOR)
    state = rebuild(restored, recorded)
    assert "Item-2" in state.store.read("h2", lines="3")[1]
    assert restored.run(recorded.objective, state).outcome == "answered"


def test_staged_rebuild_preserves_seed_for_remaining_phases(tmp_path, monkeypatch):
    from core.runtime.swarm import SwarmRunner
    from tests.test_swarm import STAGED, plan
    store = RunStore(tmp_path / "runs")
    run_id = store.create().run_id
    runner = SwarmRunner(ScriptedModel(Stop), bus(), [], history=past(),
        plain_chat_fn=ScriptedModel(STAGED, plan(
            {"id":"s1", "goal":"Read", "rung":"tool"},
            {"id":"s2", "goal":"Compare", "rung":"tool", "needs":["s1"]})),
        run_store=store, run_id=run_id, max_steps=3, supervisor=NO_SUPERVISOR)
    try:
        runner.run("Recall #2")
    except ScriptedModel.Stop:
        pass
    hard_kill(store, run_id)
    recorded = open_for_resume(store, run_id)
    assert recorded.staged and recorded.history == past()
    resumed = rebuild(runner, recorded)
    assert resumed.history == past()
    observed = []

    async def remaining(objective, plan, transcript, **kwargs):
        observed.extend(runner._run.personality.history)
        return transcript

    monkeypatch.setattr(runner, "_staged", remaining)
    runner.run(recorded.objective, resumed)
    assert observed == past()
