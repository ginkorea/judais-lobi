"""Request budgets are estimates; spend remains the provider ledger's fact."""

from types import SimpleNamespace
import asyncio

import pytest

from core.runtime.backends.base import Usage
from core.runtime.context_window import ContextConfig, MissionWindow
from core.runtime.usage import Ledger


def window(**kwargs):
    return MissionWindow(config=ContextConfig(max_context_tokens=8192, max_output_tokens=1024), **kwargs)


def test_budget_counts_native_schemas_and_reserve_without_measuring_them():
    messages = [{"role": "user", "content": "hello"}]
    plain = window().request_budget(messages)
    native = window(request_tools=lambda: [{"name": "lookup", "description": "x" * 200}])
    budget = native.request_budget(messages)
    assert budget["estimated_input_tokens"] > plain["estimated_input_tokens"]
    assert budget["estimated_input_tokens"] == plain["estimated_input_tokens"] + budget["estimated_tool_schema_tokens"]
    assert budget["estimated_headroom_tokens"] == 8192 - 1024 - budget["estimated_input_tokens"]
    assert budget["context_limit_source"] == "config"
    assert budget["estimate_method"] == "characters_plus_message_framing"
    assert "hello" not in str(budget)


@pytest.mark.parametrize("source", ["backend_probed", "backend_configured", "backend"])
def test_capacity_provenance_survives_resolution(source):
    client = SimpleNamespace(capabilities=SimpleNamespace(
        max_context_tokens=131072, max_output_tokens=8192, context_limit_source=source))
    budget = window(client=client).request_budget([])
    assert budget["context_limit_source"] == source
    assert budget["context_limit_tokens"] == 131072


def test_recovery_reserve_changes_headroom_not_capacity():
    fitted = window()
    fitted.reserve_output_tokens(2048)
    budget = fitted.request_budget([])
    assert budget["output_reserve_tokens"] == 2048
    assert budget["context_limit_tokens"] == 8192


def test_compaction_receipt_keeps_before_after_and_request_overhead():
    fitted = MissionWindow(config=ContextConfig(max_context_tokens=500, max_output_tokens=100))
    messages = [{"role": "system", "content": "Rules"},
                {"role": "user", "content": "old" * 1000},
                {"role": "assistant", "content": "answer" * 1000},
                {"role": "user", "content": "recent"},
                {"role": "assistant", "content": "reply"},
                {"role": "user", "content": "Current task"}]
    kept, compacted = fitted.fit(messages, pinned=len(messages), history_start=1)
    assert compacted is not None
    ledger = Ledger()
    request = ledger.begin_request(run_id="run_test", branch="", index=0,
                                   budget=fitted.request_budget(kept), compaction=compacted.as_record())
    assert request["compaction"]["tokens_before"] > request["compaction"]["tokens_after"]
    assert request["compaction"]["dropped_history_messages"] > 0
    assert ledger.telemetry_record()["request_tracking"]["compaction_events"] == 1
    assert len(messages) == 6


def test_attempts_do_not_double_count_spend_and_are_bounded():
    ledger = Ledger()
    for index in range(Ledger.MAX_PER_CALL + 1):
        request = ledger.begin_request(run_id="run_test", branch="child", index=index,
                                       budget={}, compaction=None)
        ledger.add(Usage(100, 10, 110))
        ledger.end_request(request, status="returned", usage_reported=True)
    detail = ledger.telemetry_record()["request_tracking"]
    assert detail["attempts"] == 257
    assert len(detail["records"]) == 256
    assert detail["omitted_records"] == 1
    assert detail["latest"]["request_id"] == "run_test:child:257"
    assert detail["latest"]["reported_usage"]["total_tokens"] == 110
    assert ledger.total == 257 * 110


def test_failed_child_attempts_survive_absorption_without_invented_usage():
    parent, child = Ledger(), Ledger()
    request = child.begin_request(run_id="run_test", branch="child", index=0, budget={}, compaction=None)
    child.end_request(request, status="failed")
    parent.absorb(child)
    detail = parent.telemetry_record()["request_tracking"]
    assert detail["attempts"] == 1
    assert detail["latest"] is None
    assert detail["records"][0]["status"] == "failed"
    assert parent.as_record() is None


def run_fixture(ask):
    from core.runtime.run import NO_SUPERVISOR, Bounds, Model, Observer, Personality, Run, Store, ToolPlane
    from core.tools.bus import ToolBus

    records = []
    run = Run(Personality(system_message="Answer the question."),
              ToolPlane(bus=ToolBus(), offered=[]), Bounds(max_steps=2, supervisor=NO_SUPERVISOR),
              Store(), Observer(records.append), Model(ask=ask, window=window(), usage_fn=lambda: Usage(100, 10, 110)))
    return run, records


def test_real_loop_pairs_request_and_usage_without_payload():
    run, records = run_fixture(lambda _: '{"answer": "Hello."}')
    assert run.run("Secret test question").outcome == "answered"
    finished = next(r for r in records if r["event"] == "mission_finished")
    detail = finished["telemetry"]["request_tracking"]
    assert detail["attempts"] == 1
    assert detail["latest"]["status"] == "returned"
    assert detail["latest"]["reported_usage"]["prompt_tokens"] == 100
    assert "Secret test question" not in str(detail)
    assert detail["latest"]["started_at"] <= detail["latest"]["finished_at"]


def test_real_loop_exception_preserves_attempt_without_exception_text():
    def failed(_):
        raise RuntimeError("private endpoint failure")

    run, records = run_fixture(failed)
    with pytest.raises(RuntimeError):
        run.run("Hello")
    finished = next(r for r in records if r["event"] == "mission_finished")
    detail = finished["telemetry"]["request_tracking"]
    assert detail["latest"]["status"] == "failed"
    assert detail["latest"]["reported_usage"] is None
    assert "private endpoint" not in str(detail)


def test_real_loop_cancellation_is_not_a_completed_zero_token_call():
    def cancelled(_):
        raise asyncio.CancelledError()

    run, records = run_fixture(cancelled)
    assert run.run("Hello").outcome == "incomplete"
    finished = next(r for r in records if r["event"] == "mission_finished")
    detail = finished["telemetry"]["request_tracking"]
    assert detail["latest"]["status"] == "cancelled"
    assert detail["latest"]["reported_usage"] is None
    assert finished["telemetry"]["observed_calls"] == 0
