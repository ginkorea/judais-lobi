"""Follow-up references survive compaction without laundering old assertions."""

import json
from copy import deepcopy

import pytest

from core.contracts.schemas import PolicyPack
from core.runtime.contract import conforms
from core.runtime.cognition import ShadowCognition
from core.runtime.history import conversation_excerpt
from core.runtime.mission import MissionRunner
from core.runtime.results import BranchedStores, MissionResultStore
from core.runtime.run import NO_SUPERVISOR
from core.runtime.resume import _replay_result
from core.tools.bus import ToolBus
from core.tools.capability import CapabilityEngine
from core.tools.descriptors import ToolDescriptor
from tests.test_conversation_compaction import history, window
from tests.test_mission import ScriptedModel, tool_call


def past():
    messages = history()
    messages[1]["content"] = ("Long introduction. " * 150 + "\n" +
                              "\n".join(f"{i}. Item-{i} with its original label."
                                        for i in range(1, 11)))
    return messages


def bus():
    return ToolBus(capability_engine=CapabilityEngine(PolicyPack(allowed_scopes=["*"])))


def test_history_is_not_a_tool_receipt_and_does_not_shift_r_handles():
    store = MissionResultStore()
    source = past()
    before = deepcopy(source)
    store.remember_history(source)
    assert len(store) == 0
    assert store.results == []
    assert store.called_tools() == []
    assert store.evidence_texts() == []
    assert store.get("h2").text == source[1]["content"]
    assert store.get("h2").quoted_history
    assert store.record("lookup", text="measured").handle == "r1"
    assert source == before


@pytest.mark.parametrize("paging", [
    {"lines": "2-11"}, {"offset": 2701, "limit": 600},
    {"grep": r"^2\."},
])
def test_full_ordered_answer_can_be_read_beyond_excerpt(paging):
    store = MissionResultStore()
    store.remember_history(past())
    code, text, error = store.read("h2", **paging)
    assert code == 0 and not error
    assert "2. Item-2" in text
    assert "not verified evidence" in text


def test_pages_stay_bounded_and_the_original_is_not_clipped():
    store = MissionResultStore(max_chars=250)
    store.remember_history([{"role": "assistant", "content": "a" * 20000}])
    code, text, _ = store.read("h1", limit=20000)
    assert code == 0 and len(text) < 700
    assert len(store.get("h1").text) == 20000
    assert store.read("h1", path="anything")[0] == 1


def test_archive_is_a_snapshot_and_clear_removes_it():
    store = MissionResultStore()
    source = [{"role": "assistant", "content": "first"}]
    store.remember_history(source)
    source[0]["content"] = "changed"
    assert store.get("h1").text == "first"
    store.clear()
    assert store.read("h1", lines="1")[0] == 1
    assert not store.has_history


def test_system_and_native_tool_messages_are_not_historical_user_text():
    store = MissionResultStore()
    store.remember_history([
        {"role": "system", "content": "policy"},
        {"role": "tool", "content": "receipt"},
        {"role": "assistant", "content": None},
        {"role": "user", "content": "question"},
    ])
    assert store.get("h1") is None and store.get("h2") is None
    assert store.get("h3") is None
    assert store.get("h4").text == "question"
    assert 'handle="h4"' in store.history_pointer()


def test_empty_history_preserves_old_store_descriptor_and_index():
    store = MissionResultStore()
    descriptor = store.descriptor()
    index = store.read()
    store.remember_history([])
    assert store.descriptor() == descriptor
    assert store.read() == index == (0, "No results stored yet in this mission.", "")


def test_excerpt_preserves_numbering_sources_and_multilingual_labels():
    quote = conversation_excerpt([
        ("h1", "user", "Compare alternatives."),
        ("h2", "assistant", "前言" * 300 + "\n1. 東京\n2. 臺北\n10. Honolulu"),
        ("h3", "user", "Thanks."),
        ("h4", "assistant", "Ready."),
    ])
    assert quote["role"] == "assistant"
    assert 'h2 assistant line 3: "2. 臺北"' in quote["content"]
    assert 'h2 assistant line 4: "10. Honolulu"' in quote["content"]
    assert "not new instructions or authorization" in quote["content"]
    assert len(quote["content"]) <= 2400


def test_reference_excerpts_are_bounded_and_skip_fenced_code():
    text = "~~~text\n1. not-an-answer\n~~~\n" + "\n".join(
        f"{i}. {'long-label' * 100}" for i in range(1, 1000))
    quote = conversation_excerpt([
        ("h1", "user", "old"), ("h2", "assistant", text),
        ("h3", "user", "recent"), ("h4", "assistant", "recent answer"),
    ])["content"]
    assert len(quote) <= 2400
    assert "not-an-answer" not in quote
    assert "h2 assistant line 4" in quote
    assert "excerpt ends" in quote


def test_branch_reads_cannot_cross_between_conversation_archives():
    registry, plane = BranchedStores(), bus()
    left, right = MissionResultStore(), MissionResultStore()
    left.remember_history([{"role": "user", "content": "left-only"}])
    right.remember_history([{"role": "user", "content": "right-only"}])
    registry.open(plane, "mission_result", "left", left)
    registry.open(plane, "mission_result", "right", right)
    try:
        result = plane.dispatch("mission_result", branch="left", handle="h1", lines="1")
        assert "left-only" in result.stdout and "right-only" not in result.stdout
        result = plane.dispatch("mission_result", branch="right", handle="h1", lines="1")
        assert "right-only" in result.stdout and "left-only" not in result.stdout
    finally:
        registry.close(plane, "left")
        registry.close(plane, "right")
    assert plane.get_descriptor("mission_result") is None


def test_compacted_followup_reads_original_without_repeating_external_work():
    model = ScriptedModel(tool_call("mission_result", handle="h2", lines="2-11"),
                          json.dumps({"answer": "Number two in the previous answer was Item-2."}))
    events = []
    runner = MissionRunner(model, bus(), [], history=past(), window=window(),
                           max_steps=3, supervisor=NO_SUPERVISOR, observer=events.append)
    result = runner.run("Expand #2 from your numbered answer; do not rerun the analysis.")
    assert result.outcome == "answered"
    first = "\n".join(m["content"] or "" for m in model.seen[0])
    assert 'h2 assistant line 3: "2. Item-2' in first
    assert "Expand #2" in first
    assert "handles h1 through h24" in first
    assert any("10. Item-10" in (m["content"] or "") for m in model.seen[1])
    assert runner._run.results.called_tools() == ["mission_result"]
    assert runner._run.results.evidence_texts() == []
    read = next(e for e in events if e["event"] == "tool_result")
    assert read["quoted_history"] is True
    assert all(conforms(e) == [] for e in events)


def test_rereading_history_receipt_cannot_promote_it_to_verified_evidence():
    model = ScriptedModel(tool_call("mission_result", handle="h1", lines="1"),
                          tool_call("mission_result", handle="r1", lines="1-5"),
                          '{"answer": "That was an earlier assertion, not a measurement."}')
    runner = MissionRunner(model, bus(), [], history=[{
        "role": "assistant", "content": "Unsupported value: 987654321."}],
        max_steps=3, supervisor=NO_SUPERVISOR)
    runner.run("What did the previous answer say?")
    assert runner._run.results.get("r1").quoted_history
    assert runner._run.results.get("r2").quoted_history
    assert runner._run.results.evidence_texts() == []


def test_real_receipts_remain_evidence_beside_history_reads(tmp_path):
    plane = bus()
    plane.register(ToolDescriptor(tool_name="measure"), lambda: (0, "Measured 12.75", ""))
    cognition = ShadowCognition(tmp_path / "reasoning.jsonl", run_id="history-test")
    model = ScriptedModel(tool_call("mission_result", handle="h1", lines="1"),
                          tool_call("measure"), '{"answer": "Measured 12.75"}')
    runner = MissionRunner(model, plane, ["measure"], history=[{
        "role": "assistant", "content": "Old claim 999.75"}],
        cognition=cognition, max_steps=3, supervisor=NO_SUPERVISOR)
    runner.run("Measure again")
    evidence = "\n".join(runner._run.results.evidence_texts())
    assert "12.75" in evidence and "999.75" not in evidence
    assert cognition.receipts == 1


def test_native_history_read_uses_normal_tool_pairing_and_provenance():
    calls = []
    answers = iter([
        [{"id": "recall", "name": "mission_result", "arguments": {"handle": "h1", "lines": "1"}}],
        [{"id": "final", "name": "mission_answer", "arguments": {"text": "The old label was Taipei."}}],
    ])
    requests = []

    def ask(messages):
        nonlocal calls
        requests.append(deepcopy(messages))
        calls = next(answers)
        return ""

    runner = MissionRunner(ask, bus(), [], protocol="native", tool_calls_fn=lambda: calls,
                           history=[{"role": "assistant", "content": "2. Taipei"}],
                           max_steps=2, supervisor=NO_SUPERVISOR)
    assert runner.run("What was #2?").outcome == "answered"
    assert any(m.get("tool_call_id") == "recall" and "Taipei" in m["content"]
               for m in requests[1] if m["role"] == "tool")
    assert runner._run.results.evidence_texts() == []


def test_a_previous_approval_read_from_history_does_not_approve_a_tool():
    plane = bus()
    executed, events = [], []
    plane.register(ToolDescriptor(tool_name="publish"),
                   lambda: executed.append(True) or (0, "published", ""))
    runner = MissionRunner(ScriptedModel(
        tool_call("mission_result", handle="h1", lines="1"), tool_call("publish")),
        plane, ["publish"], gated=["publish"], max_steps=2, gate_wait_s=0.01,
        history=[{"role": "user", "content": "Earlier approval to publish."}],
        observer=events.append, supervisor=NO_SUPERVISOR)
    runner.run("Read only. Do not publish anything.")
    assert executed == []
    assert any(e["event"] == "gate_requested" for e in events)


def test_no_history_leaks_when_reusing_a_runner():
    model = ScriptedModel(tool_call("mission_result", handle="h1", lines="1"))
    plane = bus()
    runner = MissionRunner(model, plane, [], history=[{
        "role": "assistant", "content": "old-thread-marker"}],
        max_steps=1, supervisor=NO_SUPERVISOR)
    runner.run("Recall")
    runner._run.personality.history.clear()
    runner.run("New empty history")
    assert runner._run.results.get("h1") is None
    assert runner._run.results.results == []
    assert plane.get_descriptor("mission_result") is None


def test_replay_preserves_history_provenance_not_just_its_text():
    runner = MissionRunner(ScriptedModel(), bus(), [])
    store = MissionResultStore()
    record = {"tool": "mission_result", "arguments": {"handle": "h2", "lines": "1"},
              "output": "Unverified historical number: 987654321.", "exit_code": 0,
              "quoted_history": True}
    _replay_result(runner._run, store, record)
    assert store.get("r1").quoted_history
    assert store.evidence_texts() == []
    assert store.is_history_read({"handle": "r1"})
    # A missing original archive does not fabricate an h2 from current history.
    assert store.read("h2", lines="1")[0] == 1


def test_repeated_compaction_reuses_original_references_not_summary_of_summary():
    source = past()
    store = MissionResultStore()
    store.remember_history(source)
    messages = [{"role": "system", "content": "policy"}, *source,
                {"role": "user", "content": "Expand #2"}]
    objective = messages[-1]
    fitted, _ = window().fit(messages, pinned=len(messages), history_start=1,
                             history_excerpt=store.history_excerpt)
    # Force another seeded-history compaction while preserving the objective.
    grown = fitted[:1] + history(count=8) + fitted[1:]
    boundary = next(i + 1 for i, m in enumerate(grown) if m is objective)
    fitted, event = window().fit(grown, pinned=boundary, history_start=1,
                                 history_excerpt=store.history_excerpt)
    assert event is not None
    text = "\n".join(m["content"] for m in fitted)
    assert 'h2 assistant line 3: "2. Item-2' in text
    assert any(m is objective for m in fitted)
