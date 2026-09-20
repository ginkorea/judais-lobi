"""Explicit additive expectations for old recordings, not ignored fields."""

from copy import deepcopy
from datetime import datetime
from uuid import UUID
from unittest.mock import ANY


def with_request_telemetry(result, run_id, fresh_run_id=None):
    """Historical records plus the one explicitly specified additive field.

    Keep the original recordings intact. These direct fixtures each contain
    two replayed calls with no usage report. Assert the full new object rather
    than removing telemetry from the comparator or weakening field checks.
    """
    if run_id in {"run_corpusjson-0001", "run_corpusnative-0001"}:
        finished = next(r for r in result if r["event"] == "mission_finished")
        assert "telemetry" not in finished
        finished["telemetry"] = {
            "version": 1,
            "coverage": "ledger_observations_only",
            "observed_calls": 2,
            "usage_reporting_calls": 0,
            "usage_missing_calls": 2,
            "peak_reported_prompt_tokens": None,
            "peak_reported_call_tokens": None,
            "latest_reported_call": None,
            "retained_usage_records": 0,
            "omitted_usage_records": 0,
        }
        # This replay fixture's mock backend has a one-token capacity. Keep
        # those negative headrooms visible; they are not live endpoint facts.
        estimates, overhead = ((1050, 1109), 180) if run_id == "run_corpusjson-0001" else ((1531, 1605), 610)
        requests = [{
            "request_id": f"{fresh_run_id or run_id}:direct:{index + 1}",
            "step_index": index, "started_at": ANY, "finished_at": ANY,
            "status": "returned", "compaction": None, "reported_usage": None,
            "phase": "mission", "parent_request_id": None, "parent_call_id": None,
            "call_id": f"call:{index}", "logical_run_id": "run", "branch": "direct",
            "identity_source": "harness", "usage_detail": None, "ending": "unavailable",
            "call": {"provider": None, "model": None, "model_source": "unavailable",
                     "endpoint_origin": None, "raw_stop_reason": None,
                     "stop_reason": "unavailable", "stop_reason_source": "unavailable",
                     "physical_attempts": None, "physical_attempt_coverage": "unavailable",
                     "physical_attempt_usage": "unavailable"},
            "budget": {"context_limit_tokens": 1, "context_limit_source": "backend",
                       "output_reserve_tokens": 1, "estimated_input_tokens": estimated,
                       "estimated_tool_schema_tokens": overhead,
                       "estimated_headroom_tokens": -estimated,
                       "estimate_method": "characters_plus_message_framing"},
        } for index, estimated in enumerate(estimates)]
        finished["telemetry"]["request_tracking"] = {
            "coverage": "instrumented_harness_calls_only", "attempts": 2,
            "phases": ["mission"], "nested_tool_provider_calls": "unavailable",
            "internal_retry_usage": "unavailable",
            "compaction_coverage": "instrumented_window_fits_only",
            "compaction_events": 0, "records": requests, "omitted_records": 0,
            "latest": requests[-1]}
    return result


def comparable_request_clocks(records, run_id):
    """Normalize only freshly minted IDs and validated UTC clocks for replay."""
    result = deepcopy(records)
    call_ids = {}

    def call_identity(value):
        assert UUID(value).hex == value
        if value not in call_ids:
            call_ids[value] = f"call:{len(call_ids)}"
        return call_ids[value]

    for record in result:
        tracking = record.get("telemetry", {}).get("request_tracking", {})
        attempts = tracking.get("records", [])
        if tracking.get("latest"):
            attempts = [*attempts, tracking["latest"]]
        for request in attempts:
            if request["started_at"] is ANY:
                continue
            started = datetime.fromisoformat(request["started_at"])
            finished = datetime.fromisoformat(request["finished_at"])
            assert started.utcoffset().total_seconds() == 0
            assert finished.utcoffset().total_seconds() == 0
            assert finished >= started
            assert request["request_id"].startswith(run_id + ":")
            if "call_id" in request:
                request["call_id"] = call_identity(request["call_id"])
                if request["parent_call_id"] is not None:
                    request["parent_call_id"] = call_identity(request["parent_call_id"])
                if request["logical_run_id"] is not None:
                    assert request["logical_run_id"] == run_id
                    request["logical_run_id"] = "run"
                if request["parent_request_id"] is not None:
                    assert request["parent_request_id"].startswith(run_id + ":")
                    request["parent_request_id"] = "run" + request["parent_request_id"][len(run_id):]
            request["request_id"] = "run" + request["request_id"][len(run_id):]
            request["started_at"] = request["finished_at"] = ANY
    return result
