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
            self._send(200, json.dumps({
                "id": "cmpl-1",
                "model": body.get("model"),
                "choices": [{
                    "index": 0,
                    "message": {"role": "assistant", "content": "hello from local"},
                    "finish_reason": "stop",
                }],
            }).encode())

        def _stream(self, body):
            frames = []
            for piece in ("he", "llo"):
                frames.append("data: " + json.dumps({
                    "id": "cmpl-1",
                    "model": body.get("model"),
                    "choices": [{"index": 0, "delta": {"content": piece}}],
                }) + "\n\n")
            frames.append(": a comment nobody should parse\n\n")
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
