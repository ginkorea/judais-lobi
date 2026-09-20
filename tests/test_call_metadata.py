"""Generic request facts, not prompts or a second accounting ledger."""

from concurrent.futures import ThreadPoolExecutor
import json
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import requests

from core.runtime.backends.base import (
    Backend, BackendCapabilities, CallMetadata, SideChannels, Usage, capturing,
    endpoint_origin,
)
from core.runtime.backends.local_backend import LocalBackend
from core.runtime.backends.openai_backend import OpenAIBackend
from core.runtime.backends.anthropic_backend import AnthropicBackend
from core.runtime.backends.mistral_backend import MistralBackend
from core.runtime.context_window import ContextConfig, MissionWindow
from core.runtime.usage import Ledger, RequestContext
from tests.test_local_backend import stub  # noqa: F401
from tests.test_request_telemetry import run_fixture
from tests.test_backends import _RecordingClient, _StubResponse
from tests.test_answer_continuation import runner as continuation_runner
from tests.test_swarm import (
    STAGED, TWO_STEP_PLAN, ScriptedModel, bus, calls, swarm, tool_call,  # noqa: F401
)


@pytest.mark.parametrize("value,expected", [
    ("https://person:password@example.com:8443/v1/consumers/secret?key=private#secret", "https://example.com:8443"),
    ("http://[::1]:8000/private", "http://[::1]:8000"),
    ("file:///secret", None), ("https://example.com:wrong", None),
    ("not-a-url", None), (None, None),
])
def test_endpoint_identity_contains_only_an_origin(value, expected):
    assert endpoint_origin(value) == expected


def test_known_secret_model_or_origin_is_not_published(monkeypatch):
    monkeypatch.setenv("EXAMPLE_API_KEY", "test-sensitive-secret-value")
    record = CallMetadata.for_request(
        "local", "test-sensitive-secret-value", "https://test-sensitive-secret-value.example").as_record()
    assert record["model"] is None
    assert record["endpoint_origin"] is None
    assert "test-sensitive-secret-value" not in json.dumps(record)
    assert CallMetadata.for_request("local", "https://host/consumer/secret").model is None


@pytest.mark.parametrize("raw,normalized", [
    ("stop", "completed"), ("end_turn", "completed"), ("tool_use", "tool_call"),
    ("LENGTH", "output_limit"), ("max_tokens", "output_limit"),
    ("model_context_window_exceeded", "context_limit"),
    ("content_filter", "provider_refusal"),
])
def test_stop_codes_are_reported_independently_of_usage(raw, normalized):
    ledger = Ledger()
    request = ledger.begin_request(run_id="r", branch="", index=0, budget={}, compaction=None,
                                   context=RequestContext())
    capture = SideChannels(metadata=CallMetadata().stopped(raw))
    ledger.add(None)
    ledger.end_request(request, status="returned", capture=capture)
    assert request["call"]["raw_stop_reason"] == raw
    assert request["ending"] == normalized
    assert request["reported_usage"] is None
    assert ledger.as_record() is None


@pytest.mark.parametrize("raw", ["provider secret text", "Bearer private-key", "sk-" + "x" * 40, {}, 1])
def test_unknown_stop_values_do_not_become_a_metadata_exfiltration_channel(raw):
    record = CallMetadata().stopped(raw).as_record()
    assert record["raw_stop_reason"] is None
    assert record["stop_reason"] == "unavailable"


def test_subsets_and_separate_cache_components_never_double_count():
    usage = Usage.from_payload({
        "prompt_tokens": 100, "completion_tokens": 40,
        "prompt_tokens_details": {"cached_tokens": 60, "private": "secret"},
        "completion_tokens_details": {"reasoning_tokens": 30},
        "cache_read_input_tokens": 7, "cache_creation_input_tokens": 3,
        "private": "secret",
    })
    ledger = Ledger()
    request = ledger.begin_request(run_id="r", branch="", index=0, budget={}, compaction=None,
                                   context=RequestContext())
    ledger.add(usage)
    ledger.end_request(request, status="returned", usage_reported=True)
    assert ledger.total == 140
    detail = request["usage_detail"]
    assert detail["count_sources"]["total_tokens"] == "derived"
    assert detail["provider_breakdown"]["prompt_tokens_details.cached_tokens"]["relation"] == "prompt_subset"
    assert detail["provider_breakdown"]["cache_read_input_tokens"]["relation"] == "separate_input_component"
    assert detail["visible_output_tokens"] is None
    assert "secret" not in json.dumps(ledger.telemetry_record())
    assert usage.as_record()["private"] == "secret"  # Legacy provider payload contract unchanged.


@pytest.mark.parametrize("value", [True, -1, "4", None])
def test_invalid_numeric_breakdown_is_not_promoted(value):
    ledger = Ledger()
    ledger.add(Usage(1, 2, 3, extra={"completion_tokens_details": {"reasoning_tokens": value}}))
    assert ledger.latest_usage_detail["provider_breakdown"] == {}


def test_call_ids_distinguish_a_resumed_legacy_request_identifier():
    records = [Ledger().begin_request(run_id="same-run", branch="", index=0, budget={},
                                      compaction=None, context=RequestContext()) for _ in range(2)]
    assert records[0]["request_id"] == records[1]["request_id"]  # Legacy spelling preserved.
    assert records[0]["call_id"] != records[1]["call_id"]
    parent = records[0]
    child = Ledger().begin_request(run_id="same-run", branch="", index=1, budget={}, compaction=None,
                                  context=RequestContext("continuation", parent["request_id"], parent["call_id"]))
    assert child["parent_call_id"] == parent["call_id"]


@pytest.mark.parametrize("protocol", ["json", "native"])
def test_real_continuation_links_requests_without_recounting(protocol):
    run, _, requests, _ = continuation_runner([
        ('{"answer":"First. ', "length", []),
        ('{"answer":"Second."}', None, []),
    ], protocol=protocol)
    transcript = run.run("Explain.")
    first, second = transcript.usage.request_records
    assert first["phase"] == "mission" and second["phase"] == "continuation"
    assert second["parent_request_id"] == first["request_id"]
    assert second["parent_call_id"] == first["call_id"]
    assert second["call_id"] != first["call_id"]
    assert transcript.usage.total == 240 and len(requests) == 2
    assert transcript.answer == "First. Second."


def test_cancelled_request_is_not_a_successful_provider_stop():
    ledger = Ledger()
    request = ledger.begin_request(run_id="r", branch="", index=0, budget={}, compaction=None,
                                   context=RequestContext())
    ledger.end_request(request, status="cancelled",
                       capture=SideChannels(metadata=CallMetadata().stopped("stop")))
    assert request["call"]["stop_reason"] == "completed"
    assert request["ending"] == "cancelled" and request["reported_usage"] is None
    assert ledger.as_record() is None


@pytest.mark.parametrize("stream", [False, True])
def test_real_local_backend_keeps_stop_without_usage(stub, stream):  # noqa: F811
    stub.usage = None
    stub.finish_reason = "length"
    backend = LocalBackend(endpoint=stub.base)
    with capturing() as captured:
        reply = backend.chat("fixture-model", [{"role": "user", "content": "private prompt"}], stream=stream)
        if stream:
            list(reply)
    assert captured.usage is None
    assert captured.metadata.raw_stop_reason == "length"
    assert captured.metadata.physical_attempts == 1
    assert captured.metadata.endpoint == stub.base.removesuffix("/v1")
    assert "private prompt" not in json.dumps(captured.metadata.as_record())


def test_local_connect_retries_are_not_extra_token_spend(stub, monkeypatch):  # noqa: F811
    stub.message = {"content": '{"answer":"Hello."}'}
    backend = LocalBackend(endpoint=stub.base)
    original = backend._session.post
    attempts = 0

    def post(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise requests.ConnectionError("dummy connection failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(backend, "CONNECT_RETRIES", (0,))
    monkeypatch.setattr(backend._session, "post", post)
    run, _ = run_fixture(lambda messages: backend.chat("fixture-model", messages))
    transcript = run.run("Hello")
    detail = transcript.usage.latest_request
    assert detail["call"]["physical_attempts"] == 2
    assert transcript.usage.calls == 1
    assert transcript.usage.total == 15
    assert detail["call"]["physical_attempt_usage"] == "unavailable"


@pytest.mark.parametrize("stream", [False, True])
def test_openai_stop_side_channel_without_usage(stream):
    client = MagicMock()
    client.base_url = "https://name:secret@provider.example/v1/private?key=secret"
    choice = SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content="ok", tool_calls=[]),
                             delta=SimpleNamespace(tool_calls=[]))
    payload = SimpleNamespace(choices=[choice], usage=None, model="fixture")
    client.chat.completions.create.return_value = iter([payload]) if stream else payload
    with capturing() as captured:
        result = OpenAIBackend(openai_client=client).chat("fixture", [], stream=stream)
        if stream:
            list(result)
    assert captured.metadata.stop_reason == "completed"
    assert captured.metadata.endpoint == "https://provider.example"
    assert captured.metadata.physical_attempts is None
    assert captured.usage is None


@pytest.mark.parametrize("stream", [False, True])
def test_anthropic_stop_side_channel_without_usage(stream):
    client = MagicMock()
    client.base_url = "https://provider.example/v1"
    client.messages.create.return_value = (iter([
        {"type": "message_delta", "delta": {"stop_reason": "max_tokens"}},
    ]) if stream else {"content": [{"type": "text", "text": "ok"}], "stop_reason": "max_tokens"})
    with capturing() as captured:
        result = AnthropicBackend(client=client).chat("fixture", [], stream=stream)
        if stream:
            list(result)
    assert captured.metadata.stop_reason == "output_limit"
    assert captured.metadata.physical_attempts is None
    assert captured.usage is None


@pytest.mark.parametrize("backend,key", [(OpenAIBackend, "OPENAI_API_KEY"),
                                         (AnthropicBackend, "ANTHROPIC_API_KEY")])
@pytest.mark.parametrize("stream", [False, True])
def test_lazy_client_failure_keeps_existing_failure_reporting(monkeypatch, backend, key, stream):
    monkeypatch.delenv(key, raising=False)
    client = backend()
    failures = []
    monkeypatch.setattr(client, "report_failure", lambda error, **kw: failures.append(type(error)))
    with capturing() as captured, pytest.raises(RuntimeError):
        result = client.chat("fixture", [], stream=stream)
        if stream:
            list(result)
    assert failures == [RuntimeError]
    assert captured.metadata.model == "fixture"
    assert captured.metadata.endpoint is None
    assert captured.metadata.physical_attempts is None


def test_parallel_backend_metadata_is_call_local():
    barrier = threading.Barrier(2)

    class Shared(Backend):
        @property
        def capabilities(self):
            return BackendCapabilities()

        def chat(self, model, messages, **extra):
            self.start_call_metadata(model, "https://provider.example/private")
            self.note_transport_attempt()
            barrier.wait(timeout=5)
            self.report_stop("length" if model == "a" else "stop")
            return "ok"

    backend = Shared()

    def call(model):
        with capturing() as captured:
            backend.chat(model, [])
        return captured.metadata

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(call, ["a", "b"]))
    assert (first.model, first.stop_reason) == ("a", "output_limit")
    assert (second.model, second.stop_reason) == ("b", "completed")
    assert first.physical_attempts == second.physical_attempts == 1


@pytest.mark.parametrize("stream", [False, True])
def test_mistral_stop_and_actual_transport_attempt_without_usage(monkeypatch, stream):
    monkeypatch.setenv("MISTRAL_API_KEY", "fixture-secret-key")
    choice = {"finish_reason": "stop", "message": {"content": "ok"}, "delta": {"content": "ok"}}
    payload = {"choices": [choice]}
    client = _RecordingClient(response=_StubResponse(payload=payload),
                              stream_response=_StubResponse(lines=["data: " + json.dumps(payload), "data: [DONE]"]))
    with capturing() as captured:
        result = MistralBackend(client=client).chat("fixture", [], stream=stream)
        if stream:
            list(result)
    assert captured.metadata.stop_reason == "completed"
    assert captured.metadata.physical_attempts == 1
    assert captured.usage is None
    assert "fixture-secret-key" not in json.dumps(captured.metadata.as_record())


def test_failed_local_retry_keeps_coverage_without_spend_or_previous_stop(monkeypatch):
    backend = LocalBackend(endpoint="https://fixture.example/consumer/private")
    backend.start_call_metadata("old", backend.endpoint)
    backend.report_stop("length")

    def failure(*args, **kwargs):
        raise requests.ConnectionError("secret failure text")

    monkeypatch.setattr(backend, "CONNECT_RETRIES", (0,))
    monkeypatch.setattr(backend._session, "post", failure)
    run, records = run_fixture(lambda messages: backend.chat("new", messages))
    with pytest.raises(requests.ConnectionError):
        run.run("private question")
    finished = next(record for record in records if record["event"] == "mission_finished")
    request = finished["telemetry"]["request_tracking"]["latest"]
    assert request["status"] == "failed"
    assert request["call"]["physical_attempts"] == 2
    assert request["call"]["raw_stop_reason"] is None
    assert request["call"]["model"] == "new"
    assert request["reported_usage"] is None
    assert "usage" not in finished
    assert "secret failure text" not in json.dumps(request)


@pytest.mark.parametrize("error,expected", [(requests.ReadTimeout("private"), "transport_timeout"),
                                           (TimeoutError("private"), "request_timeout"),
                                           (RuntimeError("private timeout"), "request_failed")])
def test_failure_cause_uses_exception_types_not_words(error, expected):
    def fail(_):
        raise error

    run, records = run_fixture(fail)
    with pytest.raises(type(error)):
        run.run("hello")
    final = next(record for record in records if record["event"] == "mission_finished")
    request = final["telemetry"]["request_tracking"]["latest"]
    assert request["ending"] == expected
    assert "private" not in json.dumps(request)


def test_staged_phases_share_the_existing_ledger(bus, calls):  # noqa: F811
    plain = ScriptedModel(STAGED, TWO_STEP_PLAN, '{"pass": true}', "Final answer")
    executor = ScriptedModel(tool_call("catalog.search", q="corpus"), '{"answer":"found"}',
                             tool_call("run_code", code="plot()"), '{"answer":"charted"}')
    window = MissionWindow(config=ContextConfig(max_context_tokens=32000, max_output_tokens=2000),
                           request_tools=lambda: [{"name": "fixture", "description": "some schema"}])
    transcript = swarm(plain, executor, bus, window=window,
                       usage_fn=lambda: Usage(10, 2, 12)).run("find and chart")
    ledger = transcript.usage
    tracking = ledger.telemetry_record()["request_tracking"]
    assert tracking["phases"] == ["mission", "planning", "routing", "synthesis", "verification"]
    assert tracking["attempts"] == ledger.calls == plain.calls + executor.calls == 8
    assert ledger.total == 96
    assert len({record["call_id"] for record in tracking["records"]}) == 8
    assert tracking["nested_tool_provider_calls"] == "unavailable"
    for record in tracking["records"]:
        schemas = record["budget"]["estimated_tool_schema_tokens"]
        assert (schemas > 0) if record["phase"] == "mission" else schemas == 0


def test_compaction_trigger_and_retained_categories_are_structural():
    window = MissionWindow(config=ContextConfig(max_context_tokens=500, max_output_tokens=100))
    messages = [{"role": "system", "content": "rules"},
                {"role": "user", "content": "private old words " * 1000},
                {"role": "assistant", "content": "old answer"},
                {"role": "user", "content": "recent"},
                {"role": "assistant", "content": "recent answer"},
                {"role": "user", "content": "objective"}]
    _, compacted = window.fit(messages, pinned=len(messages), history_start=1)
    record = compacted.as_record()
    assert record["trigger"] == "history_headroom"
    assert record["trigger_tokens"] == 360
    assert record["target_tokens"] == 300
    assert {"current_objective", "latest_history_exchange", "history_quotations"} <= set(record["retained_categories"])
    assert "private old words" not in json.dumps(record)
