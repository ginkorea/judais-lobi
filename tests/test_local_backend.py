# tests/test_local_backend.py — LocalBackend against a stub OpenAI-compatible server

"""A real socket, a real HTTP round trip, no GPU and no pool.

The stub speaks the parts of the OpenAI contract this backend uses:
``GET /v1/models`` with ``max_model_len``, and ``POST
/v1/chat/completions`` in both plain-JSON and SSE modes.  Mocking
``requests`` instead would test the mock's idea of SSE framing, which is
the one thing here that is easy to get wrong.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from core.runtime.backends.base import Backend
from core.runtime.backends.local_backend import (
    DEFAULT_LOCAL_API_BASE,
    LocalBackend,
    ServedModel,
)


class _StubState:
    """What the stub serves and what it was asked for."""

    def __init__(self):
        self.models = {
            "object": "list",
            "data": [{"id": "gpt-oss-20b", "object": "model", "max_model_len": 131072}],
        }
        self.models_status = 200
        self.last_body = None
        self.last_headers = None
        #: What the stub puts in `usage`, on both paths. ``None`` is a
        #: server that reports nothing — which many local servers are, and
        #: which the ledger has to keep distinct from a server that
        #: reported zeros.
        self.usage = {"prompt_tokens": 12, "completion_tokens": 3,
                      "total_tokens": 15}
        #: The assistant message to answer with, or ``None`` for the
        #: plain ``"hello from local"`` reply.  Set it to serve a native
        #: ``tool_calls`` reply — the shape a model returns when the
        #: request declared ``tools``.
        self.message = None
        #: The ``delta`` objects to stream, or ``None`` for the two
        #: content pieces.  A streamed tool call arrives as fragments of
        #: a JSON string spread over several of these.
        self.deltas = None


def _make_handler(state: _StubState):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_args):  # keep pytest output clean
            pass

        def _send(self, status, payload: bytes, content_type="application/json"):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            state.last_headers = dict(self.headers)
            if self.path != "/v1/models":
                self._send(404, b'{"error":"not found"}')
                return
            if state.models_status != 200:
                self._send(state.models_status, b'{"error":"boom"}')
                return
            self._send(200, json.dumps(state.models).encode())

        def do_POST(self):
            state.last_headers = dict(self.headers)
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
            state.last_body = body
            if self.path != "/v1/chat/completions":
                self._send(404, b'{"error":"not found"}')
                return
            if body.get("stream"):
                self._stream(body)
                return
            payload = {
                "id": "cmpl-1",
                "model": body.get("model"),
                "choices": [{
                    "index": 0,
                    "message": state.message if state.message is not None else {
                        "role": "assistant", "content": "hello from local"},
                    "finish_reason": "stop",
                }],
            }
            if state.usage is not None:
                payload["usage"] = state.usage
            self._send(200, json.dumps(payload).encode())

        def _stream(self, body):
            frames = []
            deltas = (state.deltas if state.deltas is not None
                      else [{"content": piece} for piece in ("he", "llo")])
            for delta in deltas:
                frames.append("data: " + json.dumps({
                    "id": "cmpl-1",
                    "model": body.get("model"),
                    "choices": [{"index": 0, "delta": delta}],
                }) + "\n\n")
            frames.append(": a comment nobody should parse\n\n")
            # The OpenAI convention, which vLLM and llama.cpp follow: a
            # usage frame arrives LAST, carries no choices, and only when
            # the request asked for it with `stream_options`.
            wants_usage = bool(
                (body.get("stream_options") or {}).get("include_usage"))
            if wants_usage and state.usage is not None:
                frames.append("data: " + json.dumps({
                    "id": "cmpl-1",
                    "model": body.get("model"),
                    "choices": [],
                    "usage": state.usage,
                }) + "\n\n")
            frames.append("data: [DONE]\n\n")
            payload = "".join(frames).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    return Handler


@pytest.fixture
def stub():
    state = _StubState()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(state))
    server.daemon_threads = True
    # poll_interval bounds shutdown(); the 0.5s default is a wall-clock
    # half-second of teardown on every test in this module.
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01},
                              daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    state.base = f"http://{host}:{port}/v1"
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class TestBaseNormalization:
    def test_default_when_unset(self, monkeypatch):
        monkeypatch.delenv("LOCAL_API_BASE", raising=False)
        assert LocalBackend().endpoint == DEFAULT_LOCAL_API_BASE

    def test_env_var_is_read(self, monkeypatch):
        monkeypatch.setenv("LOCAL_API_BASE", "http://box:9001/v1")
        assert LocalBackend().endpoint == "http://box:9001/v1"

    def test_explicit_wins_over_env(self, monkeypatch):
        monkeypatch.setenv("LOCAL_API_BASE", "http://box:9001/v1")
        assert LocalBackend(endpoint="http://other:1/v1").endpoint == "http://other:1/v1"

    def test_trailing_slash_stripped(self):
        assert LocalBackend(endpoint="http://h:8000/v1/").endpoint == "http://h:8000/v1"

    def test_missing_version_prefix_is_repaired(self):
        """The commonest misconfiguration, caught here and not as a 404."""
        assert LocalBackend(endpoint="http://h:8000").endpoint == "http://h:8000/v1"

    def test_existing_version_prefix_not_doubled(self):
        assert LocalBackend(endpoint="http://h:8000/v2").endpoint == "http://h:8000/v2"


class TestProbe:
    def test_reports_served_model_and_context(self, stub):
        backend = LocalBackend(endpoint=stub.base)
        probed = backend.probe()
        assert probed == ServedModel(
            model_id="gpt-oss-20b", max_model_len=131072, reachable=True,
        )

    def test_unreachable_is_a_fact_not_an_exception(self):
        backend = LocalBackend(endpoint="http://127.0.0.1:1/v1")
        probed = backend.probe()
        assert probed.reachable is False
        assert probed.max_model_len is None
        assert probed.error

    def test_server_error_is_unreachable(self, stub):
        stub.models_status = 500
        backend = LocalBackend(endpoint=stub.base)
        assert backend.probe().reachable is False

    def test_result_is_cached(self, stub):
        backend = LocalBackend(endpoint=stub.base)
        first = backend.probe()
        stub.models_status = 500
        assert backend.probe() is first

    def test_refresh_reprobes(self, stub):
        backend = LocalBackend(endpoint=stub.base)
        backend.probe()
        stub.models_status = 500
        assert backend.probe(refresh=True).reachable is False

    def test_named_model_is_preferred_over_first_entry(self, stub):
        stub.models["data"].insert(
            0, {"id": "some-other-model", "max_model_len": 4096},
        )
        backend = LocalBackend(endpoint=stub.base, model="gpt-oss-20b")
        assert backend.probe().max_model_len == 131072

    def test_model_falls_back_to_served_name(self, stub, monkeypatch):
        monkeypatch.delenv("LOCAL_MODEL", raising=False)
        assert LocalBackend(endpoint=stub.base).model == "gpt-oss-20b"

    def test_local_model_env_wins(self, stub, monkeypatch):
        monkeypatch.setenv("LOCAL_MODEL", "from-env")
        assert LocalBackend(endpoint=stub.base).model == "from-env"


class TestCapabilities:
    def test_context_comes_from_max_model_len(self, stub):
        caps = LocalBackend(endpoint=stub.base).capabilities
        assert caps.max_context_tokens == 131072

    def test_tool_calls_are_true_unlike_the_old_stub(self, stub):
        """The gap this replaces: the stub said False for a server that can."""
        assert LocalBackend(endpoint=stub.base).capabilities.supports_tool_calls is True

    def test_tool_calls_can_be_declared_false(self, stub):
        backend = LocalBackend(endpoint=stub.base, supports_tool_calls=False)
        assert backend.capabilities.supports_tool_calls is False

    def test_the_constrained_decode_flags_are_true(self, stub):
        """`tool_choice="required"` was exercised against vLLM 0.14.1 on
        10 Aug 2026; `parallel_tool_calls` is declared on the same grounds
        as `tools` itself. See `capabilities`."""
        caps = LocalBackend(endpoint=stub.base).capabilities
        assert caps.supports_parallel_tool_calls is True
        assert caps.supports_tool_choice_required is True

    def test_they_cannot_outrun_the_tool_call_declaration(self, stub):
        """A server told it does not speak `tools` must not be reported as
        speaking a constrained form of them."""
        caps = LocalBackend(endpoint=stub.base,
                            supports_tool_calls=False).capabilities
        assert caps.supports_parallel_tool_calls is False
        assert caps.supports_tool_choice_required is False

    def test_streaming_is_true(self, stub):
        assert LocalBackend(endpoint=stub.base).capabilities.supports_streaming is True

    def test_unreachable_does_not_guess_a_context_window(self):
        caps = LocalBackend(endpoint="http://127.0.0.1:1/v1").capabilities
        assert caps.max_context_tokens is None

    def test_explicit_context_overrides_the_probe(self, stub):
        backend = LocalBackend(endpoint=stub.base, max_context_tokens=8192)
        assert backend.capabilities.max_context_tokens == 8192

    def test_is_a_backend(self, stub):
        assert isinstance(LocalBackend(endpoint=stub.base), Backend)


class TestChat:
    def test_non_streaming_returns_content(self, stub):
        backend = LocalBackend(endpoint=stub.base)
        out = backend.chat("gpt-oss-20b", [{"role": "user", "content": "hi"}])
        assert out == "hello from local"
        assert stub.last_body["model"] == "gpt-oss-20b"
        assert stub.last_body["messages"] == [{"role": "user", "content": "hi"}]
        assert "stream" not in stub.last_body

    def test_max_tokens_is_forwarded(self, stub):
        backend = LocalBackend(endpoint=stub.base)
        backend.chat("m", [{"role": "user", "content": "hi"}], max_tokens=64)
        assert stub.last_body["max_tokens"] == 64

    def test_max_tokens_omitted_when_unset(self, stub):
        LocalBackend(endpoint=stub.base).chat("m", [{"role": "user", "content": "x"}])
        assert "max_tokens" not in stub.last_body

    def test_constructor_output_limit_is_the_default(self, stub):
        backend = LocalBackend(endpoint=stub.base, max_output_tokens=32)
        backend.chat("m", [{"role": "user", "content": "x"}])
        assert stub.last_body["max_tokens"] == 32

    def test_model_defaults_to_the_served_one(self, stub, monkeypatch):
        monkeypatch.delenv("LOCAL_MODEL", raising=False)
        LocalBackend(endpoint=stub.base).chat("", [{"role": "user", "content": "x"}])
        assert stub.last_body["model"] == "gpt-oss-20b"

    def test_streaming_yields_openai_shaped_deltas(self, stub):
        """core.cli walks chunk.choices[0].delta.content and knows no backends."""
        backend = LocalBackend(endpoint=stub.base)
        chunks = list(backend.chat("m", [{"role": "user", "content": "x"}], stream=True))
        assert [c.choices[0].delta.content for c in chunks] == ["he", "llo"]
        assert stub.last_body["stream"] is True

    def test_streaming_stops_at_done_and_skips_comments(self, stub):
        backend = LocalBackend(endpoint=stub.base)
        chunks = list(backend.chat("m", [{"role": "user", "content": "x"}], stream=True))
        assert len(chunks) == 2

    def test_bearer_token_is_sent_when_configured(self, stub):
        backend = LocalBackend(endpoint=stub.base, api_key="s3cret")
        backend.chat("m", [{"role": "user", "content": "x"}])
        assert stub.last_headers["Authorization"] == "Bearer s3cret"

    def test_no_authorization_header_without_a_key(self, stub, monkeypatch):
        monkeypatch.delenv("LOCAL_API_KEY", raising=False)
        LocalBackend(endpoint=stub.base).chat("m", [{"role": "user", "content": "x"}])
        assert "Authorization" not in stub.last_headers

    def test_http_error_raises(self, stub):
        backend = LocalBackend(endpoint=stub.base.replace("/v1", "/v9"))
        with pytest.raises(Exception):
            backend.chat("m", [{"role": "user", "content": "x"}])


class TestWhatTheCallCost:
    """Reported by the server, or reported as nothing.

    A local endpoint is the one this repo runs most and the one most
    likely to say nothing at all, which makes it the place where the
    difference between "no usage" and "zero usage" is easiest to lose.
    """

    def test_the_non_streaming_usage_is_read(self, stub):
        backend = LocalBackend(endpoint=stub.base)
        backend.chat("m", [{"role": "user", "content": "hi"}])
        assert backend.last_usage.as_record() == {
            "prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15}

    def test_a_server_that_reports_nothing_reports_nothing(self, stub):
        stub.usage = None
        backend = LocalBackend(endpoint=stub.base)
        backend.chat("m", [{"role": "user", "content": "hi"}])
        assert backend.last_usage is None

    def test_streaming_asks_for_the_counts(self, stub):
        """An OpenAI-compatible server sends NO usage on a stream unless
        this is set, so a streamed ledger would otherwise always be empty."""
        backend = LocalBackend(endpoint=stub.base)
        list(backend.chat("m", [{"role": "user", "content": "x"}], stream=True))
        assert stub.last_body["stream_options"] == {"include_usage": True}

    def test_a_caller_can_still_override_stream_options(self, stub):
        backend = LocalBackend(endpoint=stub.base)
        list(backend.chat("m", [{"role": "user", "content": "x"}], stream=True,
                          stream_options={"include_usage": False}))
        assert stub.last_body["stream_options"] == {"include_usage": False}
        assert backend.last_usage is None

    def test_the_final_usage_frame_is_read(self, stub):
        backend = LocalBackend(endpoint=stub.base)
        stream = backend.chat("m", [{"role": "user", "content": "x"}],
                              stream=True)
        assert backend.last_usage is None, "nothing honest to say yet"
        list(stream)
        assert backend.last_usage.total_tokens == 15

    def test_the_usage_frame_is_not_yielded_as_a_delta(self, stub):
        """It carries no choices. `core.cli` walks `choices[0]` and would
        raise on a frame that has none — and it was never a delta anyway."""
        backend = LocalBackend(endpoint=stub.base)
        chunks = list(backend.chat("m", [{"role": "user", "content": "x"}],
                                   stream=True))
        assert [c.choices[0].delta.content for c in chunks] == ["he", "llo"]

    def test_an_abandoned_stream_leaves_what_was_reported(self, stub):
        backend = LocalBackend(endpoint=stub.base)
        stream = backend.chat("m", [{"role": "user", "content": "x"}],
                              stream=True)
        next(stream)
        stream.close()
        # Nothing had been reported by the first frame, and the honest
        # answer to "what did it cost" is still nothing.
        assert backend.last_usage is None

    def test_a_failed_call_does_not_leave_the_last_ones_numbers(self, stub):
        backend = LocalBackend(endpoint=stub.base)
        backend.chat("m", [{"role": "user", "content": "x"}])
        assert backend.last_usage is not None
        dead = LocalBackend(endpoint=stub.base.replace("/v1", "/v9"))
        dead.last_usage = backend.last_usage
        with pytest.raises(Exception):
            dead.chat("m", [{"role": "user", "content": "x"}])
        assert dead.last_usage is None

    def test_the_client_surfaces_it(self, stub, monkeypatch):
        """`UnifiedClient.last_usage` is what a mission reads; the backend
        attribute is not something a caller should have to reach for."""
        monkeypatch.setenv("LOCAL_API_BASE", stub.base)
        from core.unified_client import UnifiedClient

        client = UnifiedClient(provider_override="local")
        assert client.last_usage is None
        client.chat("m", [{"role": "user", "content": "x"}])
        assert client.last_usage.total_tokens == 15


class TestWhatTheCallDecided:
    """Native tool calls, and the one rule about who gets to see them.

    Every call the model made is on ``last_tool_calls`` whatever the
    request asked for.  What the request decides is the ``str`` that comes
    back: the mission protocol's one JSON object by default — which is
    what every deployed run has received and still receives — or the
    content untouched for a caller **speaking native**, meaning it sent
    ``tool_choice="required"`` or ``parallel_tool_calls=True``.
    """

    #: A reply with no text and two native calls: what a served model
    #: returns when the request declared `tools`.
    TWO_CALLS = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {"id": "call_1", "type": "function",
             "function": {"name": "catalog_search_assets",
                          "arguments": '{"text": "assets we hold"}'}},
            {"id": "call_2", "type": "function",
             "function": {"name": "list_files", "arguments": '{"path": "/"}'}},
        ],
    }

    def test_the_default_still_synthesizes_mission_json(self, stub):
        """The kernel reads one JSON object, and this is the adapter that
        keeps it able to. Nothing about that has changed."""
        stub.message = self.TWO_CALLS
        backend = LocalBackend(endpoint=stub.base)
        out = backend.chat("m", [{"role": "user", "content": "x"}],
                           tools=[{"type": "function"}], tool_choice="auto")
        decision = json.loads(out)
        assert decision["tool"] == "catalog_search_assets"
        assert decision["arguments"] == {"text": "assets we hold"}
        assert "2 tool calls were offered" in decision["note"]

    def test_the_calls_are_reported_even_in_the_default_mode(self, stub):
        """The rendering drops the second call; the side channel does not."""
        stub.message = self.TWO_CALLS
        backend = LocalBackend(endpoint=stub.base)
        backend.chat("m", [{"role": "user", "content": "x"}],
                     tool_choice="auto")
        assert backend.last_tool_calls == [
            {"id": "call_1", "name": "catalog_search_assets",
             "arguments": {"text": "assets we hold"}},
            {"id": "call_2", "name": "list_files",
             "arguments": {"path": "/"}}]

    def test_tool_choice_required_gets_the_content_unsynthesized(self, stub):
        """A caller that constrained the decoder is reading the calls
        itself, and a manufactured JSON object would be a second copy of
        the same decision, free to disagree with it."""
        stub.message = self.TWO_CALLS
        backend = LocalBackend(endpoint=stub.base)
        out = backend.chat("m", [{"role": "user", "content": "x"}],
                           tool_choice="required")
        assert out == ""
        assert [c["name"] for c in backend.last_tool_calls] == [
            "catalog_search_assets", "list_files"]

    def test_parallel_tool_calls_is_native_speech_too(self, stub):
        """Asking for more calls than a one-per-turn protocol can dispatch
        is telling this backend you are not speaking that protocol."""
        stub.message = self.TWO_CALLS
        backend = LocalBackend(endpoint=stub.base)
        assert backend.chat("m", [{"role": "user", "content": "x"}],
                            parallel_tool_calls=True) == ""

    def test_tool_choice_auto_is_not_native_speech(self, stub):
        """`auto` beside `tools` is what every deployed mission sends —
        it is there to stop vLLM 500ing on its own harmony output — and
        those runs must keep getting mission JSON back."""
        stub.message = self.TWO_CALLS
        backend = LocalBackend(endpoint=stub.base)
        out = backend.chat("m", [{"role": "user", "content": "x"}],
                           tool_choice="auto")
        assert json.loads(out)["tool"] == "catalog_search_assets"

    def test_a_native_reply_that_had_text_keeps_its_text(self, stub):
        stub.message = {"role": "assistant", "content": "thinking out loud",
                        "tool_calls": self.TWO_CALLS["tool_calls"]}
        backend = LocalBackend(endpoint=stub.base)
        assert backend.chat("m", [{"role": "user", "content": "x"}],
                            tool_choice="required") == "thinking out loud"

    def test_the_harmony_scrub_still_runs_in_native_mode(self, stub):
        """It repairs a server's own parser bug and has nothing to do with
        which protocol is being spoken."""
        stub.message = {
            "role": "assistant",
            "content": "<|start|>assistant<|channel|>final<|message|>done"}
        backend = LocalBackend(endpoint=stub.base)
        assert backend.chat("m", [{"role": "user", "content": "x"}],
                            tool_choice="required") == "done"

    def test_unreadable_arguments_survive_as_the_text_that_arrived(self, stub):
        stub.message = {"role": "assistant", "content": None, "tool_calls": [
            {"id": "call_1", "function": {"name": "f",
                                          "arguments": '{"path": "/tm'}}]}
        backend = LocalBackend(endpoint=stub.base)
        backend.chat("m", [{"role": "user", "content": "x"}],
                     tool_choice="required")
        assert backend.last_tool_calls == [
            {"id": "call_1", "name": "f", "arguments": {},
             "arguments_raw": '{"path": "/tm'}]

    def test_a_reply_with_no_calls_reports_none(self, stub):
        backend = LocalBackend(endpoint=stub.base)
        backend.chat("m", [{"role": "user", "content": "x"}])
        assert backend.last_tool_calls == []

    def test_the_previous_turns_decision_is_gone_by_the_next_call(self, stub):
        """Or the loop dispatches a tool nobody asked for, twice."""
        stub.message = self.TWO_CALLS
        backend = LocalBackend(endpoint=stub.base)
        backend.chat("m", [{"role": "user", "content": "x"}])
        assert backend.last_tool_calls
        stub.message = None
        backend.chat("m", [{"role": "user", "content": "x"}])
        assert backend.last_tool_calls == []

    def test_a_failed_call_leaves_no_decision_behind(self, stub):
        dead = LocalBackend(endpoint=stub.base.replace("/v1", "/v9"))
        dead.last_tool_calls = [{"id": "stale", "name": "f", "arguments": {}}]
        with pytest.raises(Exception):
            dead.chat("m", [{"role": "user", "content": "x"}])
        assert dead.last_tool_calls == []

    def test_a_streamed_call_is_assembled_from_its_fragments(self, stub):
        stub.deltas = [
            {"tool_calls": [{"index": 0, "id": "call_1", "type": "function",
                             "function": {"name": "list_files",
                                          "arguments": '{"path":'}}]},
            {"tool_calls": [{"index": 0,
                             "function": {"arguments": ' "/tmp"}'}}]},
        ]
        backend = LocalBackend(endpoint=stub.base)
        stream = backend.chat("m", [{"role": "user", "content": "x"}],
                              stream=True)
        assert backend.last_tool_calls == [], "nothing has fully arrived yet"
        chunks = list(stream)
        assert backend.last_tool_calls == [
            {"id": "call_1", "name": "list_files",
             "arguments": {"path": "/tmp"}}]
        assert [c.choices[0].delta.tool_calls is not None
                for c in chunks[:2]] == [True, True], "the frames still arrive"
        # And one more the server did not send: this caller is not speaking
        # native and nothing came through as content, so the reply is the
        # mission-protocol rendering of the call. See
        # `TestAStreamedReplyIsTheSameReply`.
        assert json.loads(chunks[2].choices[0].delta.content) == {
            "tool": "list_files", "arguments": {"path": "/tmp"}}

    def test_two_streamed_calls_are_kept_apart_by_index(self, stub):
        stub.deltas = [
            {"tool_calls": [
                {"index": 0, "id": "a", "function": {"name": "f",
                                                     "arguments": '{"n":'}},
                {"index": 1, "id": "b", "function": {"name": "g",
                                                     "arguments": '{"n":'}}]},
            {"tool_calls": [{"index": 1, "function": {"arguments": " 2}"}},
                            {"index": 0, "function": {"arguments": " 1}"}}]},
        ]
        backend = LocalBackend(endpoint=stub.base)
        list(backend.chat("m", [{"role": "user", "content": "x"}], stream=True))
        assert backend.last_tool_calls == [
            {"id": "a", "name": "f", "arguments": {"n": 1}},
            {"id": "b", "name": "g", "arguments": {"n": 2}}]

    def test_an_abandoned_stream_leaves_only_what_fully_arrived(self, stub):
        stub.deltas = [
            {"tool_calls": [{"index": 0, "id": "call_1",
                             "function": {"name": "f",
                                          "arguments": '{"path":'}}]},
            {"tool_calls": [{"index": 0,
                             "function": {"arguments": ' "/tmp"}'}}]},
        ]
        backend = LocalBackend(endpoint=stub.base)
        stream = backend.chat("m", [{"role": "user", "content": "x"}],
                              stream=True)
        next(stream)
        stream.close()
        assert backend.last_tool_calls == [
            {"id": "call_1", "name": "f", "arguments": {},
             "arguments_raw": '{"path":'}]

    def test_a_content_only_stream_decided_nothing(self, stub):
        backend = LocalBackend(endpoint=stub.base)
        list(backend.chat("m", [{"role": "user", "content": "x"}], stream=True))
        assert backend.last_tool_calls == []

    def test_a_streamed_reply_reads_the_same_as_a_completed_one(self, stub):
        """The regression turning streaming on would otherwise have caused.

        A served model given `tools` answers in `tool_calls` with no text,
        and `_as_mission_json` is the whole reason the JSON-protocol loop
        can work against one. A streamed call that dropped the rendering
        would hand the loop an empty reply and spend the turn on a parse
        error — for every mission on the reference deployment, which sends
        `tool_choice="auto"` beside `tools` on every single call.
        """
        arguments = '{"text": "assets we hold"}'
        stub.deltas = [
            {"tool_calls": [{"index": 0, "id": "call_1",
                             "function": {"name": "catalog_search_assets",
                                          "arguments": arguments}}]},
        ]
        backend = LocalBackend(endpoint=stub.base)
        streamed = "".join(
            chunk.choices[0].delta.content or ""
            for chunk in backend.chat("m", [{"role": "user", "content": "x"}],
                                      stream=True, tools=[{"type": "function"}],
                                      tool_choice="auto"))
        stub.message = {"role": "assistant", "content": None,
                        "tool_calls": [
                            {"id": "call_1", "type": "function",
                             "function": {"name": "catalog_search_assets",
                                          "arguments": arguments}}]}
        completed = backend.chat("m", [{"role": "user", "content": "x"}],
                                 tools=[{"type": "function"}],
                                 tool_choice="auto")
        assert streamed == completed
        assert json.loads(streamed)["tool"] == "catalog_search_assets"

    def test_a_caller_speaking_native_gets_no_synthesized_frame(self, stub):
        """It reads `last_tool_calls` itself, and a manufactured JSON
        object would be a second, disagreeing copy of the same decision."""
        stub.deltas = [
            {"tool_calls": [{"index": 0, "id": "c",
                             "function": {"name": "f", "arguments": "{}"}}]},
        ]
        backend = LocalBackend(endpoint=stub.base)
        chunks = list(backend.chat("m", [{"role": "user", "content": "x"}],
                                   stream=True, tool_choice="required"))
        assert all(chunk.choices[0].delta.content is None
                   for chunk in chunks)
        assert backend.last_tool_calls == [
            {"id": "c", "name": "f", "arguments": {}}]

    def test_a_stream_that_spoke_gets_nothing_added(self, stub):
        """`content or rendering` on the completed path; the same rule
        here — a reply with text is a reply, whatever else it carried."""
        stub.deltas = [
            {"content": "here you go ",
             "tool_calls": [{"index": 0, "id": "c",
                             "function": {"name": "f", "arguments": "{}"}}]},
        ]
        backend = LocalBackend(endpoint=stub.base)
        chunks = list(backend.chat("m", [{"role": "user", "content": "x"}],
                                   stream=True))
        assert [chunk.choices[0].delta.content for chunk in chunks] == [
            "here you go "]

    def test_the_native_kwargs_reach_the_body_verbatim(self, stub):
        backend = LocalBackend(endpoint=stub.base)
        backend.chat("m", [{"role": "user", "content": "x"}],
                     tool_choice="required", parallel_tool_calls=True,
                     response_format={"type": "json_object"})
        assert stub.last_body["tool_choice"] == "required"
        assert stub.last_body["parallel_tool_calls"] is True
        assert stub.last_body["response_format"] == {"type": "json_object"}

    def test_the_client_surfaces_the_calls(self, stub, monkeypatch):
        """`UnifiedClient.last_tool_calls` is what a runner reads."""
        stub.message = self.TWO_CALLS
        monkeypatch.setenv("LOCAL_API_BASE", stub.base)
        from core.unified_client import UnifiedClient

        client = UnifiedClient(provider_override="local")
        assert client.last_tool_calls == []
        client.chat("m", [{"role": "user", "content": "x"}],
                    tool_choice="required")
        assert [c["name"] for c in client.last_tool_calls] == [
            "catalog_search_assets", "list_files"]


class TestUnifiedClientWiring:
    def test_local_provider_builds_a_local_backend(self, monkeypatch):
        monkeypatch.setenv("LOCAL_API_BASE", "http://127.0.0.1:1/v1")
        from core.unified_client import UnifiedClient

        client = UnifiedClient(provider_override="local")
        assert client.provider == "local"
        assert isinstance(client._backend, LocalBackend)

    def test_constructing_does_not_need_the_server_up(self, monkeypatch):
        """Building a client must never depend on a server being warm."""
        monkeypatch.setenv("LOCAL_API_BASE", "http://127.0.0.1:1/v1")
        from core.unified_client import UnifiedClient

        UnifiedClient(provider_override="local")  # no raise

    def test_chat_goes_through_to_the_stub(self, stub, monkeypatch):
        monkeypatch.setenv("LOCAL_API_BASE", stub.base)
        from core.unified_client import UnifiedClient

        client = UnifiedClient(provider_override="local")
        assert client.chat("m", [{"role": "user", "content": "x"}]) == "hello from local"


class TestProviderResolution:
    def test_local_is_a_known_provider(self):
        from core.runtime.provider_config import DEFAULT_MODELS, PROVIDERS

        assert "local" in DEFAULT_MODELS
        assert "local" in PROVIDERS

    def test_local_is_never_fallen_back_from(self, monkeypatch):
        """A missing OpenAI key must not silently send a mission off-host."""
        from core.runtime.provider_config import resolve_provider

        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
        assert resolve_provider(requested="local", has_injected_client=False) == "local"

    def test_local_has_no_api_key_env(self):
        from core.runtime.provider_config import API_KEY_ENV

        assert "local" not in API_KEY_ENV


class TestConnectRetry:
    """A refused connect gets a bounded retry; an answering server does not.

    Measured 12 Aug 2026 on the pool: one mid-eval turn died at step 0 on a
    single refused connect to the served endpoint while the turns on either
    side succeeded. The endpoint blipped; the turn paid with its life.
    `_post` now retries CONNECT_RETRIES times on ConnectionError only.
    """

    def _backend(self, monkeypatch):
        b = LocalBackend(endpoint="http://127.0.0.1:1/v1")
        # No real sleeping in a unit test; record the waits instead.
        waits = []
        monkeypatch.setattr(
            "core.runtime.backends.local_backend.time.sleep", waits.append)
        return b, waits

    def test_a_refused_connect_is_retried_then_succeeds(self, monkeypatch):
        import requests as rq
        b, waits = self._backend(monkeypatch)
        calls = []

        def post(url, **kw):
            calls.append(url)
            if len(calls) < 3:
                raise rq.exceptions.ConnectionError("refused")
            from types import SimpleNamespace
            return SimpleNamespace(status_code=200)

        monkeypatch.setattr(b._session, "post", post)
        out = b._post({"messages": []}, stream=False)
        assert out.status_code == 200
        assert len(calls) == 3
        assert waits == list(b.CONNECT_RETRIES[:2])

    def test_a_dead_endpoint_still_raises_after_the_budget(self, monkeypatch):
        import requests as rq
        b, waits = self._backend(monkeypatch)
        calls = []

        def post(url, **kw):
            calls.append(url)
            raise rq.exceptions.ConnectionError("refused")

        monkeypatch.setattr(b._session, "post", post)
        import pytest as _pytest
        with _pytest.raises(rq.exceptions.ConnectionError):
            b._post({"messages": []}, stream=False)
        assert len(calls) == 1 + len(b.CONNECT_RETRIES)

    def test_an_http_error_is_never_resent(self, monkeypatch):
        """The server ANSWERED — re-sending could double a decode."""
        import requests as rq
        b, _ = self._backend(monkeypatch)
        calls = []

        def post(url, **kw):
            calls.append(url)
            raise rq.exceptions.ReadTimeout("mid-body")

        monkeypatch.setattr(b._session, "post", post)
        import pytest as _pytest
        with _pytest.raises(rq.exceptions.ReadTimeout):
            b._post({"messages": []}, stream=False)
        assert len(calls) == 1
