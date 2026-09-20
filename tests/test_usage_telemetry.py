"""Cumulative work is not the context size of one request."""

from core.runtime.backends.base import Usage
from core.runtime.mission import _finished_record
from core.runtime.usage import Ledger


def test_cumulative_tokens_do_not_become_a_context_peak():
    ledger = Ledger()
    for _ in range(17):
        ledger.add(Usage(26000, 1000, 27000))
    detail = ledger.telemetry_record()
    assert ledger.as_record()["total_tokens"] == 459000
    assert detail["peak_reported_prompt_tokens"] == 26000
    assert detail["peak_reported_call_tokens"] == 27000
    assert detail["coverage"] == "ledger_observations_only"
    assert "context_limit" not in detail
    assert "compactions" not in detail


def test_missing_usage_is_not_zero_and_not_the_previous_call():
    ledger = Ledger()
    ledger.add(Usage(100, 10, 110))
    ledger.add(None)
    detail = ledger.telemetry_record()
    assert detail["observed_calls"] == 2
    assert detail["usage_reporting_calls"] == 1
    assert detail["usage_missing_calls"] == 1
    assert detail["latest_reported_call"] is None
    assert detail["peak_reported_prompt_tokens"] == 100


def test_no_reports_leave_peaks_unknown():
    ledger = Ledger()
    ledger.add(None)
    assert ledger.as_record() is None
    detail = ledger.telemetry_record()
    assert detail["usage_missing_calls"] == 1
    assert detail["peak_reported_prompt_tokens"] is None
    assert detail["peak_reported_call_tokens"] is None


def test_measured_zero_is_distinct_from_unknown():
    ledger = Ledger()
    ledger.add(Usage(0, 0, 0))
    detail = ledger.telemetry_record()
    assert detail["usage_reporting_calls"] == 1
    assert detail["peak_reported_call_tokens"] == 0


def test_partial_provider_report_does_not_turn_missing_counts_into_zero():
    ledger = Ledger()
    ledger.add(Usage.from_payload({"completion_tokens": 10}))
    detail = ledger.telemetry_record()
    assert detail["latest_reported_call"] == {
        "prompt_tokens": None, "completion_tokens": 10, "total_tokens": None}
    assert detail["peak_reported_prompt_tokens"] is None
    assert detail["peak_reported_call_tokens"] is None
    # Preserve the pre-existing cumulative wire; only the new measurements
    # distinguish unknown fields instead of claiming an observed zero.
    assert ledger.as_record()["total_tokens"] == 10


def test_total_derived_from_two_reported_counts_is_known():
    ledger = Ledger()
    ledger.add(Usage.from_payload({"prompt_tokens": 100, "completion_tokens": 10}))
    assert ledger.telemetry_record()["peak_reported_call_tokens"] == 110


def test_peaks_continue_after_record_retention_fills():
    ledger = Ledger()
    for _ in range(Ledger.MAX_PER_CALL):
        ledger.add(Usage(1, 1, 2))
    ledger.add(Usage(20000, 1000, 21000))
    detail = ledger.telemetry_record()
    assert detail["omitted_usage_records"] == 1
    assert detail["peak_reported_prompt_tokens"] == 20000
    assert detail["latest_reported_call"]["total_tokens"] == 21000


def test_child_missing_reports_survive_absorption():
    parent, child = Ledger(), Ledger()
    parent.add(Usage(10, 1, 11))
    child.add(None)
    parent.absorb(child)
    detail = parent.telemetry_record()
    assert detail["observed_calls"] == 2
    assert detail["usage_missing_calls"] == 1
    assert detail["latest_reported_call"] is None
    assert parent.total == 11


def test_child_peaks_are_maxima_not_sums():
    parent, child = Ledger(), Ledger()
    parent.add(Usage(10, 1, 11))
    child.add(Usage(20, 2, 22))
    parent.absorb(child)
    parent.absorb(parent)
    detail = parent.telemetry_record()
    assert detail["observed_calls"] == 2
    assert detail["peak_reported_call_tokens"] == 22
    assert parent.total == 33


def test_telemetry_is_additive_and_omitted_for_old_emitters():
    fields = dict(outcome="answered", steps=1, max_steps=24)
    assert _finished_record(**fields) == fields
    detail = Ledger().telemetry_record()
    assert _finished_record(**fields, telemetry=detail)["telemetry"] == detail


def test_provider_extra_fields_are_not_copied_into_telemetry():
    ledger = Ledger()
    ledger.add(Usage(1, 2, 3, extra={"private_payload": "not-for-the-ui"}))
    assert "private_payload" not in str(ledger.telemetry_record())


def test_absorbing_a_legacy_prepopulated_ledger_preserves_its_totals():
    parent = Ledger()
    parent.absorb(Ledger(prompt=100, completion=10, total=110, calls=1))
    assert parent.as_record()["total_tokens"] == 110
    assert parent.telemetry_record()["usage_missing_calls"] == 0
    assert parent.telemetry_record()["peak_reported_call_tokens"] is None


def test_mission_finished_carries_the_ledgers_observations():
    from core.runtime.run import (
        NO_SUPERVISOR, Bounds, Model, Observer, Personality, Run, Store, ToolPlane,
    )
    from core.tools.bus import ToolBus

    records = []
    run = Run(
        Personality(system_message="Answer the question."),
        ToolPlane(bus=ToolBus(), offered=[]),
        Bounds(max_steps=2, supervisor=NO_SUPERVISOR),
        Store(), Observer(records.append),
        Model(ask=lambda _: '{"answer": "Hello."}',
              usage_fn=lambda: Usage(100, 10, 110)),
    )
    assert run.run("Hello").outcome == "answered"
    finished = next(r for r in records if r["event"] == "mission_finished")
    assert finished["telemetry"]["peak_reported_prompt_tokens"] == 100
    assert finished["telemetry"]["usage_reporting_calls"] == 1
    assert finished["usage"]["total_tokens"] == 110
