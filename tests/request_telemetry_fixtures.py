"""Explicit additive expectations for old recordings, not ignored fields."""

from copy import deepcopy
from datetime import datetime
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
            "budget": {"context_limit_tokens": 1, "context_limit_source": "backend",
                       "output_reserve_tokens": 1, "estimated_input_tokens": estimated,
                       "estimated_tool_schema_tokens": overhead,
                       "estimated_headroom_tokens": -estimated,
                       "estimate_method": "characters_plus_message_framing"},
        } for index, estimated in enumerate(estimates)]
        finished["telemetry"]["request_tracking"] = {
            "coverage": "windowed_mission_loop_only", "attempts": 2,
            "compaction_events": 0, "records": requests, "omitted_records": 0,
            "latest": requests[-1]}
    return result


def comparable_request_clocks(records, run_id):
    """Normalize only freshly minted IDs and validated UTC clocks for replay."""
    result = deepcopy(records)
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
            request["request_id"] = "run" + request["request_id"][len(run_id):]
            request["started_at"] = request["finished_at"] = ANY
    return result

