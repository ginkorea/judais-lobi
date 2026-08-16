# tests/test_backends.py — Tests for backend implementations

import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock

from core.runtime.backends.base import (
    BackendCapabilities,
    ToolCallAccumulator,
    Usage,
    tool_calls_from,
)
from core.runtime.backends.openai_backend import OpenAIBackend
from core.runtime.backends.mistral_backend import MistralBackend
from core.runtime.backends.local_backend import LocalBackend


class TestOpenAIBackend:
    def test_injected_client(self):
        mock = MagicMock()
        backend = OpenAIBackend(openai_client=mock)
        assert backend.client is mock

    def test_non_streaming(self):
        mock = MagicMock()
        mock.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="hi"))]
        )
        backend = OpenAIBackend(openai_client=mock)
        result = backend.chat("gpt-4o-mini", [{"role": "user", "content": "hello"}])
        assert result == "hi"
        mock.chat.completions.create.assert_called_once_with(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "hello"}],
        )

    def test_streaming(self):
        mock = MagicMock()
        chunks = [
            SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="a"))]),
            SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="b"))]),
        ]
        mock.chat.completions.create.return_value = iter(chunks)
        backend = OpenAIBackend(openai_client=mock)
        result = list(backend.chat("gpt-4o-mini", [{"role": "user", "content": "hi"}], stream=True))
        assert len(result) == 2
        mock.chat.completions.create.assert_called_once_with(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "hi"}],
            stream=True,
        )

    def test_missing_key_raises(self):
        with pytest.raises(RuntimeError, match="Missing OPENAI_API_KEY"):
            OpenAIBackend()

    def test_capabilities(self):
        mock = MagicMock()
        backend = OpenAIBackend(openai_client=mock)
        caps = backend.capabilities
        assert caps.supports_streaming is True
        assert caps.supports_json_mode is True
        assert caps.supports_tool_calls is True

    # ── what the call cost ───────────────────────────────────────────────

    def test_usage_is_read_off_the_response(self):
        """The SDK puts it on `response.usage`; this is the whole feature."""
        mock = MagicMock()
        mock.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="hi"))],
            usage=SimpleNamespace(prompt_tokens=11, completion_tokens=4,
                                  total_tokens=15),
        )
        backend = OpenAIBackend(openai_client=mock)
        backend.chat("gpt-4o-mini", [{"role": "user", "content": "hello"}])
        assert (backend.last_usage.prompt_tokens,
                backend.last_usage.completion_tokens,
                backend.last_usage.total_tokens) == (11, 4, 15)

    def test_a_provider_extra_travels_rather_than_being_dropped(self):
        """Cached tokens are the number a platform meters on next."""
        mock = MagicMock()
        mock.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="hi"))],
            usage={"prompt_tokens": 10, "completion_tokens": 2,
                   "total_tokens": 12,
                   "prompt_tokens_details": {"cached_tokens": 8}},
        )
        backend = OpenAIBackend(openai_client=mock)
        backend.chat("gpt-4o-mini", [{"role": "user", "content": "hello"}])
        assert backend.last_usage.as_record()["prompt_tokens_details"] == {
            "cached_tokens": 8}

    def test_a_response_without_usage_reports_nothing_not_zero(self):
        """A zero is a claim. Silence has to stay distinguishable from it."""
        mock = MagicMock()
        mock.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="hi"))]
        )
        backend = OpenAIBackend(openai_client=mock)
        backend.chat("gpt-4o-mini", [{"role": "user", "content": "hello"}])
        assert backend.last_usage is None

    def test_the_previous_calls_numbers_do_not_survive_a_silent_one(self):
        """Cleared at the top of `chat`, or a ledger counts them twice."""
        mock = MagicMock()
        mock.chat.completions.create.side_effect = [
            SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="a"))],
                usage={"prompt_tokens": 5, "completion_tokens": 5,
                       "total_tokens": 10}),
            SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="b"))]),
        ]
        backend = OpenAIBackend(openai_client=mock)
        backend.chat("m", [{"role": "user", "content": "x"}])
        assert backend.last_usage is not None
        backend.chat("m", [{"role": "user", "content": "x"}])
        assert backend.last_usage is None

    def test_a_raised_call_leaves_nothing_behind(self):
        mock = MagicMock()
        mock.chat.completions.create.side_effect = [
            SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="a"))],
                usage={"prompt_tokens": 5, "completion_tokens": 5,
                       "total_tokens": 10}),
            RuntimeError("boom"),
        ]
        backend = OpenAIBackend(openai_client=mock)
        backend.chat("m", [{"role": "user", "content": "x"}])
        with pytest.raises(RuntimeError):
            backend.chat("m", [{"role": "user", "content": "x"}])
        assert backend.last_usage is None

    def test_a_streams_usage_arrives_when_the_iterator_is_exhausted(self):
        """Usage rides the last frame, so there is nothing honest to say
        before it does."""
        mock = MagicMock()
        chunks = [
            SimpleNamespace(choices=[SimpleNamespace(
                delta=SimpleNamespace(content="a"))], usage=None),
            SimpleNamespace(choices=[], usage={"prompt_tokens": 9,
                                               "completion_tokens": 1,
                                               "total_tokens": 10}),
        ]
        mock.chat.completions.create.return_value = iter(chunks)
        backend = OpenAIBackend(openai_client=mock)
        stream = backend.chat("m", [{"role": "user", "content": "x"}],
                              stream=True)
        assert backend.last_usage is None
        collected = list(stream)
        assert len(collected) == 2, "every chunk is passed through untouched"
        assert backend.last_usage.total_tokens == 10

    def test_an_abandoned_stream_still_leaves_what_had_been_reported(self):
        mock = MagicMock()
        chunks = [
            SimpleNamespace(choices=[SimpleNamespace(
                delta=SimpleNamespace(content="a"))],
                usage={"prompt_tokens": 2, "completion_tokens": 1,
                       "total_tokens": 3}),
            SimpleNamespace(choices=[SimpleNamespace(
                delta=SimpleNamespace(content="b"))], usage=None),
        ]
        mock.chat.completions.create.return_value = iter(chunks)
        backend = OpenAIBackend(openai_client=mock)
        stream = backend.chat("m", [{"role": "user", "content": "x"}],
                              stream=True)
        next(stream)
        stream.close()
        assert backend.last_usage.total_tokens == 3

    # ── what the call decided ────────────────────────────────────────────

    @staticmethod
    def _call(index, name, arguments, call_id=None):
        """One tool call, or one fragment of one, in the SDK's shape."""
        return SimpleNamespace(
            index=index, id=call_id,
            function=SimpleNamespace(name=name, arguments=arguments))

    def _replies(self, message):
        mock = MagicMock()
        mock.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=message)])
        return OpenAIBackend(openai_client=mock), mock

    def test_a_native_call_arrives_beside_the_return_value(self):
        """`chat` still returns content; the decision is on the side channel."""
        backend, _ = self._replies(SimpleNamespace(
            content=None,
            tool_calls=[self._call(0, "list_files", '{"path": "/tmp"}',
                                   call_id="call_a")]))
        assert backend.chat("m", [{"role": "user", "content": "x"}]) is None
        assert backend.last_tool_calls == [
            {"id": "call_a", "name": "list_files",
             "arguments": {"path": "/tmp"}}]

    def test_every_call_is_reported_in_the_order_they_came(self):
        """Two calls are two dicts. Using only the first is a protocol's
        decision to make, and it cannot make it about calls it never saw."""
        backend, _ = self._replies(SimpleNamespace(
            content=None,
            tool_calls=[self._call(0, "first", '{"n": 1}', call_id="a"),
                        self._call(1, "second", '{"n": 2}', call_id="b")]))
        backend.chat("m", [{"role": "user", "content": "x"}])
        assert [(c["name"], c["arguments"])
                for c in backend.last_tool_calls] == [
            ("first", {"n": 1}), ("second", {"n": 2})]

    def test_unreadable_arguments_are_kept_rather_than_lost(self):
        """A truncated brace is the one mistake a native call can still
        make, and what was sent is the only evidence of it."""
        backend, _ = self._replies(SimpleNamespace(
            content=None,
            tool_calls=[self._call(0, "f", '{"path": "/tmp"', call_id="a")]))
        backend.chat("m", [{"role": "user", "content": "x"}])
        assert backend.last_tool_calls == [
            {"id": "a", "name": "f", "arguments": {},
             "arguments_raw": '{"path": "/tmp"'}]

    def test_a_reply_with_no_calls_is_an_empty_list(self):
        backend, _ = self._replies(SimpleNamespace(content="hi"))
        backend.chat("m", [{"role": "user", "content": "x"}])
        assert backend.last_tool_calls == []

    def test_the_previous_decision_does_not_survive_a_quiet_reply(self):
        """Cleared at the top of `chat`, or a runner dispatches a tool
        nobody asked for on the turn after."""
        mock = MagicMock()
        mock.chat.completions.create.side_effect = [
            SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                content=None,
                tool_calls=[self._call(0, "f", "{}", call_id="a")]))]),
            SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content="just prose"))]),
        ]
        backend = OpenAIBackend(openai_client=mock)
        backend.chat("m", [{"role": "user", "content": "x"}])
        assert backend.last_tool_calls
        backend.chat("m", [{"role": "user", "content": "x"}])
        assert backend.last_tool_calls == []

    def test_a_raised_call_leaves_no_decision_behind(self):
        mock = MagicMock()
        mock.chat.completions.create.side_effect = [
            SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                content=None,
                tool_calls=[self._call(0, "f", "{}", call_id="a")]))]),
            RuntimeError("boom"),
        ]
        backend = OpenAIBackend(openai_client=mock)
        backend.chat("m", [{"role": "user", "content": "x"}])
        with pytest.raises(RuntimeError):
            backend.chat("m", [{"role": "user", "content": "x"}])
        assert backend.last_tool_calls == []

    def test_the_native_kwargs_reach_create_verbatim(self):
        """`tools`, `tool_choice`, `parallel_tool_calls` and
        `response_format` are ordinary parameters of the SDK's `create`."""
        backend, mock = self._replies(SimpleNamespace(content="hi"))
        tools = [{"type": "function", "function": {"name": "f"}}]
        backend.chat("m", [{"role": "user", "content": "x"}], tools=tools,
                     tool_choice="required", parallel_tool_calls=True,
                     response_format={"type": "json_object"})
        mock.chat.completions.create.assert_called_once_with(
            model="m", messages=[{"role": "user", "content": "x"}],
            tools=tools, tool_choice="required", parallel_tool_calls=True,
            response_format={"type": "json_object"})

    def test_a_call_with_no_extras_still_sends_no_extras(self):
        """The request this backend has always sent is the one it sends."""
        backend, mock = self._replies(SimpleNamespace(content="hi"))
        backend.chat("m", [{"role": "user", "content": "x"}])
        assert mock.chat.completions.create.call_args.kwargs == {
            "model": "m", "messages": [{"role": "user", "content": "x"}]}

    def _streamed(self, chunks):
        mock = MagicMock()
        mock.chat.completions.create.return_value = iter(chunks)
        return OpenAIBackend(openai_client=mock)

    @staticmethod
    def _frame(*fragments):
        return SimpleNamespace(choices=[SimpleNamespace(
            delta=SimpleNamespace(content=None,
                                  tool_calls=list(fragments)))], usage=None)

    def test_a_streamed_call_is_assembled_from_its_fragments(self):
        """Arguments arrive as a JSON string a few characters at a time."""
        backend = self._streamed([
            self._frame(self._call(0, "search", '{"q": ', call_id="call_1")),
            self._frame(self._call(0, None, '"boats"}')),
        ])
        stream = backend.chat("m", [{"role": "user", "content": "x"}],
                              stream=True)
        assert backend.last_tool_calls == [], "nothing has fully arrived yet"
        assert len(list(stream)) == 2, "every chunk is still passed through"
        assert backend.last_tool_calls == [
            {"id": "call_1", "name": "search", "arguments": {"q": "boats"}}]

    def test_two_streamed_calls_are_kept_apart_by_index(self):
        backend = self._streamed([
            self._frame(self._call(0, "first", '{"a":', call_id="a"),
                        self._call(1, "second", '{"b":', call_id="b")),
            self._frame(self._call(1, None, " 2}"),
                        self._call(0, None, " 1}")),
        ])
        list(backend.chat("m", [{"role": "user", "content": "x"}], stream=True))
        assert backend.last_tool_calls == [
            {"id": "a", "name": "first", "arguments": {"a": 1}},
            {"id": "b", "name": "second", "arguments": {"b": 2}}]

    def test_an_abandoned_stream_leaves_only_what_fully_arrived(self):
        """Half a JSON string is not a decision, and it does not pretend
        to be one — it comes back as the raw text it is."""
        backend = self._streamed([
            self._frame(self._call(0, "search", '{"q": ', call_id="call_1")),
            self._frame(self._call(0, None, '"boats"}')),
        ])
        stream = backend.chat("m", [{"role": "user", "content": "x"}],
                              stream=True)
        next(stream)
        stream.close()
        assert backend.last_tool_calls == [
            {"id": "call_1", "name": "search", "arguments": {},
             "arguments_raw": '{"q": '}]

    def test_the_constrained_decode_flags_are_declared(self):
        backend = OpenAIBackend(openai_client=MagicMock())
        caps = backend.capabilities
        assert caps.supports_parallel_tool_calls is True
        assert caps.supports_tool_choice_required is True


class _StubResponse:
    """The parts of ``httpx.Response`` this backend touches.

    ``closed`` is the interesting field: a streamed response that nobody
    closes is the leak this stub exists to catch.
    """

    def __init__(self, status_code=200, payload=None, lines=(), text=""):
        self.status_code = status_code
        self._payload = payload
        self._lines = list(lines)
        self.text = text
        self.closed = False
        self.reads = 0
        self.request = None

    def read(self):
        self.reads += 1
        return b""

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload

    def iter_lines(self):
        yield from self._lines


class _StubStream:
    """What ``client.stream(...)`` returns: a context manager, entered once."""

    def __init__(self, response):
        self.response = response
        self.entered = False

    def __enter__(self):
        self.entered = True
        return self.response

    def __exit__(self, *exc_info):
        self.response.closed = True
        return False


class _RecordingClient:
    """An httpx-shaped stub that records how it was called.

    Every keyword the backend sends is kept, because the point of most of
    these tests is *what was in the request* — the header, the timeout —
    not what came back.
    """

    def __init__(self, response=None, stream_response=None):
        self.response = response
        self.stream_response = stream_response
        self.calls = []
        self.streams = []

    def post(self, url, *, headers, json, timeout):
        self.calls.append({"url": url, "headers": headers, "json": json,
                           "timeout": timeout})
        return self.response

    def stream(self, method, url, *, headers, json, timeout):
        self.calls.append({"method": method, "url": url, "headers": headers,
                           "json": json, "timeout": timeout})
        stream = _StubStream(self.stream_response)
        self.streams.append(stream)
        return stream


def _sse(*pieces):
    """SSE frames carrying one content delta each, then ``[DONE]``."""
    import json as _json

    lines = ["data: " + _json.dumps({"choices": [{"delta": {"content": p}}]})
             for p in pieces]
    return [*lines, "", "data: [DONE]"]


@pytest.fixture
def no_subprocess(monkeypatch):
    """Record any attempt to spawn a process, and refuse it.

    The backend used to run ``curl -H "Authorization: Bearer <key>"``, which
    put the key in ``ps`` for every user on the host. Recording the argv
    rather than only blocking it lets a test assert the stronger thing: not
    just that nothing was spawned, but that the key is in no argument list
    anywhere.
    """
    import subprocess

    attempts = []

    def refuse(cmd, *a, **kw):
        attempts.append(cmd)
        raise AssertionError(f"a process was spawned: {cmd!r}")

    monkeypatch.setattr(subprocess, "run", refuse)
    monkeypatch.setattr(subprocess, "Popen", refuse)
    monkeypatch.setattr(subprocess, "call", refuse)
    monkeypatch.setattr(subprocess, "check_output", refuse)
    return attempts


class TestMistralBackend:
    KEY = "test-key"

    def _backend(self, monkeypatch, client):
        monkeypatch.setenv("MISTRAL_API_KEY", self.KEY)
        return MistralBackend(client=client)

    def test_missing_key_raises(self):
        with pytest.raises(RuntimeError, match="Missing MISTRAL_API_KEY"):
            MistralBackend()

    def test_capabilities(self, monkeypatch):
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
        backend = MistralBackend()
        caps = backend.capabilities
        assert caps.supports_streaming is True
        assert caps.supports_json_mode is True
        assert caps.supports_tool_calls is False

    def test_construction_contacts_nothing(self, monkeypatch):
        """No socket at construction: a CLI must start with the net down."""
        client = _RecordingClient()
        self._backend(monkeypatch, client)
        assert client.calls == []

    # ── the key is not an argument ───────────────────────────────────────

    def test_no_process_is_spawned(self, monkeypatch, no_subprocess):
        """Neither path shells out — the curl wrapper is gone."""
        client = _RecordingClient(
            response=_StubResponse(payload={
                "choices": [{"message": {"content": "hi"}}]}),
            stream_response=_StubResponse(lines=_sse("a")),
        )
        backend = self._backend(monkeypatch, client)
        backend.chat("codestral-latest", [{"role": "user", "content": "x"}])
        list(backend.chat("codestral-latest", [{"role": "user", "content": "x"}],
                          stream=True))
        assert no_subprocess == []

    def test_key_rides_a_header_and_no_argv(self, monkeypatch, no_subprocess):
        client = _RecordingClient(
            response=_StubResponse(payload={
                "choices": [{"message": {"content": "hi"}}]}))
        backend = self._backend(monkeypatch, client)
        backend.chat("codestral-latest", [{"role": "user", "content": "x"}])

        headers = client.calls[0]["headers"]
        assert headers["Authorization"] == f"Bearer {self.KEY}"
        # ...and nowhere else. Every argv the process tried to build (none)
        # is searched for the key, so this fails the moment one appears.
        flattened = " ".join(str(a) for a in no_subprocess)
        assert self.KEY not in flattened

    def test_no_temp_file_is_written(self, monkeypatch):
        """The prompt never lands on disk; the body goes from memory."""
        import tempfile

        def refuse(*a, **kw):
            raise AssertionError("a temp file was created")

        monkeypatch.setattr(tempfile, "NamedTemporaryFile", refuse)
        monkeypatch.setattr(tempfile, "mkstemp", refuse)
        client = _RecordingClient(
            response=_StubResponse(payload={
                "choices": [{"message": {"content": "hi"}}]}),
            stream_response=_StubResponse(lines=_sse("a")),
        )
        backend = self._backend(monkeypatch, client)
        assert backend.chat("m", [{"role": "user", "content": "x"}]) == "hi"
        assert len(list(backend.chat("m", [{"role": "user", "content": "x"}],
                                     stream=True))) == 1

    # ── the request is bounded ───────────────────────────────────────────

    def test_a_timeout_is_sent_on_both_paths(self, monkeypatch):
        from core.runtime.backends.mistral_backend import CHAT_TIMEOUT

        client = _RecordingClient(
            response=_StubResponse(payload={"choices": []}),
            stream_response=_StubResponse(lines=_sse("a")),
        )
        backend = self._backend(monkeypatch, client)
        backend.chat("m", [{"role": "user", "content": "x"}])
        list(backend.chat("m", [{"role": "user", "content": "x"}], stream=True))

        assert [c["timeout"] for c in client.calls] == [CHAT_TIMEOUT, CHAT_TIMEOUT]
        assert 0 < CHAT_TIMEOUT < float("inf")

    def test_timeout_is_the_local_backend_policy(self):
        """One owner: the two HTTP backends do not drift on how long to wait."""
        from core.runtime.backends import local_backend, mistral_backend

        assert mistral_backend.CHAT_TIMEOUT is local_backend.CHAT_TIMEOUT
        assert mistral_backend.CONNECT_RETRIES is LocalBackend.CONNECT_RETRIES

    # ── non-streaming ────────────────────────────────────────────────────

    def test_non_streaming_returns_content(self, monkeypatch):
        client = _RecordingClient(response=_StubResponse(payload={
            "choices": [{"message": {"content": "hello from mistral"}}]}))
        backend = self._backend(monkeypatch, client)
        out = backend.chat("m", [{"role": "user", "content": "x"}])
        assert out == "hello from mistral"
        assert client.calls[0]["json"]["stream"] is False

    def test_empty_model_defaults_to_codestral(self, monkeypatch):
        client = _RecordingClient(response=_StubResponse(payload={"choices": []}))
        backend = self._backend(monkeypatch, client)
        backend.chat("", [{"role": "user", "content": "x"}])
        assert client.calls[0]["json"]["model"] == "codestral-latest"

    def test_extra_kwargs_reach_the_body(self, monkeypatch):
        """`UnifiedClient.chat` forwards **kwargs; the curl version had none."""
        client = _RecordingClient(response=_StubResponse(payload={"choices": []}))
        backend = self._backend(monkeypatch, client)
        backend.chat("m", [{"role": "user", "content": "x"}], max_tokens=7)
        assert client.calls[0]["json"]["max_tokens"] == 7

    def test_non_2xx_raises_with_the_body(self, monkeypatch):
        import httpx

        client = _RecordingClient(response=_StubResponse(
            status_code=401, payload={"message": "Unauthorized"}))
        backend = self._backend(monkeypatch, client)
        with pytest.raises(httpx.HTTPStatusError) as exc:
            backend.chat("m", [{"role": "user", "content": "x"}])
        # The curl version returned this string AS THE ASSISTANT'S REPLY.
        assert "401" in str(exc.value)
        assert "Unauthorized" in str(exc.value)

    def test_non_2xx_raises_in_stream_mode_too(self, monkeypatch):
        import httpx

        response = _StubResponse(status_code=429, payload={"message": "slow down"})
        client = _RecordingClient(stream_response=response)
        backend = self._backend(monkeypatch, client)
        with pytest.raises(httpx.HTTPStatusError, match="slow down"):
            list(backend.chat("m", [{"role": "user", "content": "x"}], stream=True))
        assert response.closed is True

    # ── streaming ────────────────────────────────────────────────────────

    def test_stream_yields_deltas(self, monkeypatch):
        response = _StubResponse(lines=_sse("he", "llo"))
        client = _RecordingClient(stream_response=response)
        backend = self._backend(monkeypatch, client)
        chunks = list(backend.chat("m", [{"role": "user", "content": "x"}],
                                   stream=True))
        assert [c.choices[0].delta.content for c in chunks] == ["he", "llo"]
        assert client.calls[0]["method"] == "POST"
        assert client.calls[0]["json"]["stream"] is True

    def test_stream_closes_when_exhausted(self, monkeypatch):
        response = _StubResponse(lines=_sse("a"))
        client = _RecordingClient(stream_response=response)
        backend = self._backend(monkeypatch, client)
        list(backend.chat("m", [{"role": "user", "content": "x"}], stream=True))
        assert response.closed is True

    def test_stream_closes_when_the_consumer_walks_away(self, monkeypatch):
        """The defect this rewrite exists for.

        The old generator released its temp file *after* the loop, so a
        consumer that stopped early — a ``break``, an exception in the render
        loop, a dropped reference — leaked the file holding the whole prompt.
        Whatever the resource is, abandonment must release it.
        """
        response = _StubResponse(lines=_sse("a", "b", "c"))
        client = _RecordingClient(stream_response=response)
        backend = self._backend(monkeypatch, client)

        chunks = backend.chat("m", [{"role": "user", "content": "x"}], stream=True)
        assert next(chunks).choices[0].delta.content == "a"
        assert response.closed is False
        chunks.close()
        assert response.closed is True

    def test_stream_closes_when_the_consumer_is_garbage_collected(self, monkeypatch):
        import gc

        response = _StubResponse(lines=_sse("a", "b"))
        client = _RecordingClient(stream_response=response)
        backend = self._backend(monkeypatch, client)

        chunks = backend.chat("m", [{"role": "user", "content": "x"}], stream=True)
        next(chunks)
        del chunks
        gc.collect()
        assert response.closed is True

    def test_nothing_is_sent_until_the_stream_is_iterated(self, monkeypatch):
        """Lazy, as the curl generator was: `chat()` alone opens nothing."""
        client = _RecordingClient(stream_response=_StubResponse(lines=_sse("a")))
        backend = self._backend(monkeypatch, client)
        backend.chat("m", [{"role": "user", "content": "x"}], stream=True)
        assert client.calls == []

    # ── connect retry ────────────────────────────────────────────────────

    def test_a_refused_connect_is_retried_then_succeeds(self, monkeypatch):
        import httpx
        from core.runtime.backends.mistral_backend import CONNECT_RETRIES

        waits = []
        monkeypatch.setattr(
            "core.runtime.backends.mistral_backend.time.sleep", waits.append)
        client = _RecordingClient()
        backend = self._backend(monkeypatch, client)
        attempts = []

        def post(url, **kw):
            attempts.append(url)
            if len(attempts) < 3:
                raise httpx.ConnectError("refused")
            return _StubResponse(payload={"choices": [{"message": {"content": "ok"}}]})

        monkeypatch.setattr(client, "post", post)
        assert backend.chat("m", [{"role": "user", "content": "x"}]) == "ok"
        assert len(attempts) == 3
        assert waits == list(CONNECT_RETRIES[:2])

    # ── what the call cost ───────────────────────────────────────────────

    def test_usage_is_read_off_the_json(self, monkeypatch):
        client = _RecordingClient(response=_StubResponse(payload={
            "choices": [{"message": {"content": "hi"}}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 6,
                      "total_tokens": 26}}))
        backend = self._backend(monkeypatch, client)
        backend.chat("m", [{"role": "user", "content": "x"}])
        assert backend.last_usage.as_record() == {
            "prompt_tokens": 20, "completion_tokens": 6, "total_tokens": 26}

    def test_a_reply_with_no_choices_is_still_billed(self, monkeypatch):
        """Read before the empty-choices return, not after it."""
        client = _RecordingClient(response=_StubResponse(payload={
            "choices": [],
            "usage": {"prompt_tokens": 20, "completion_tokens": 0,
                      "total_tokens": 20}}))
        backend = self._backend(monkeypatch, client)
        assert backend.chat("m", [{"role": "user", "content": "x"}]) == ""
        assert backend.last_usage.prompt_tokens == 20

    def test_no_usage_in_the_json_reports_nothing_not_zero(self, monkeypatch):
        client = _RecordingClient(response=_StubResponse(payload={
            "choices": [{"message": {"content": "hi"}}]}))
        backend = self._backend(monkeypatch, client)
        backend.chat("m", [{"role": "user", "content": "x"}])
        assert backend.last_usage is None

    def test_a_streams_usage_rides_its_last_frame(self, monkeypatch):
        """Mistral puts `usage` on the last content frame, not on one of
        its own — so it is read off every chunk and the last wins."""
        import json as _json

        lines = [
            "data: " + _json.dumps({"choices": [{"delta": {"content": "he"}}]}),
            "data: " + _json.dumps({
                "choices": [{"delta": {"content": "llo"}}],
                "usage": {"prompt_tokens": 7, "completion_tokens": 2,
                          "total_tokens": 9}}),
            "data: [DONE]",
        ]
        client = _RecordingClient(stream_response=_StubResponse(lines=lines))
        backend = self._backend(monkeypatch, client)
        stream = backend.chat("m", [{"role": "user", "content": "x"}],
                              stream=True)
        assert backend.last_usage is None
        chunks = list(stream)
        assert [c.choices[0].delta.content for c in chunks] == ["he", "llo"]
        assert backend.last_usage.total_tokens == 9

    def test_a_stream_that_reported_nothing_reports_nothing(self, monkeypatch):
        client = _RecordingClient(stream_response=_StubResponse(lines=_sse("a")))
        backend = self._backend(monkeypatch, client)
        list(backend.chat("m", [{"role": "user", "content": "x"}], stream=True))
        assert backend.last_usage is None

    def test_a_status_error_is_never_resent(self, monkeypatch):
        """The provider ANSWERED — resending would bill for it twice."""
        import httpx

        client = _RecordingClient(response=_StubResponse(
            status_code=500, payload={"message": "boom"}))
        backend = self._backend(monkeypatch, client)
        with pytest.raises(httpx.HTTPStatusError):
            backend.chat("m", [{"role": "user", "content": "x"}])
        assert len(client.calls) == 1

    # ── what the call decided ────────────────────────────────────────────

    def test_the_tool_call_flags_stay_false(self, monkeypatch):
        """Unverified is not the same as unsupported, and only one of the
        two is a promise this repo can keep. Mistral's API documents
        `tools`; nothing here has run a round trip against it."""
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
        caps = MistralBackend().capabilities
        assert caps.supports_tool_calls is False
        assert caps.supports_parallel_tool_calls is False
        assert caps.supports_tool_choice_required is False

    def test_tools_in_the_extras_do_not_break_the_call(self, monkeypatch):
        """`**extra` has always reached the body; a caller CAN send these."""
        client = _RecordingClient(response=_StubResponse(payload={
            "choices": [{"message": {"content": "hi"}}]}))
        backend = self._backend(monkeypatch, client)
        tools = [{"type": "function", "function": {"name": "f"}}]
        assert backend.chat("m", [{"role": "user", "content": "x"}],
                            tools=tools) == "hi"
        assert client.calls[0]["json"]["tools"] == tools

    def test_a_reply_that_carried_calls_is_reported_not_discarded(self,
                                                                  monkeypatch):
        """The flag says nobody should rely on this; it does not say the
        reply should be thrown away when it arrives anyway."""
        client = _RecordingClient(response=_StubResponse(payload={
            "choices": [{"message": {"content": None, "tool_calls": [
                {"id": "a", "function": {"name": "f",
                                         "arguments": '{"n": 1}'}},
                {"id": "b", "function": {"name": "g", "arguments": "{}"}}]}}]}))
        backend = self._backend(monkeypatch, client)
        assert backend.chat("m", [{"role": "user", "content": "x"}]) == ""
        assert backend.last_tool_calls == [
            {"id": "a", "name": "f", "arguments": {"n": 1}},
            {"id": "b", "name": "g", "arguments": {}}]

    def test_a_raised_call_leaves_no_decision_behind(self, monkeypatch):
        """Cleared before the request goes out, which is the only place
        that helps: a call that never returns never reaches the reader."""
        import httpx

        client = _RecordingClient(response=_StubResponse(
            status_code=500, payload={"message": "boom"}))
        backend = self._backend(monkeypatch, client)
        backend.last_tool_calls = [{"id": "stale", "name": "f",
                                    "arguments": {}}]
        with pytest.raises(httpx.HTTPStatusError):
            backend.chat("m", [{"role": "user", "content": "x"}])
        assert backend.last_tool_calls == []

    def test_streamed_fragments_are_assembled_too(self, monkeypatch):
        import json as _json

        lines = [
            "data: " + _json.dumps({"choices": [{"delta": {"tool_calls": [
                {"index": 0, "id": "a",
                 "function": {"name": "f", "arguments": '{"n":'}}]}}]}),
            "data: " + _json.dumps({"choices": [{"delta": {"tool_calls": [
                {"index": 0, "function": {"arguments": " 1}"}}]}}]}),
            "data: [DONE]",
        ]
        client = _RecordingClient(stream_response=_StubResponse(lines=lines))
        backend = self._backend(monkeypatch, client)
        stream = backend.chat("m", [{"role": "user", "content": "x"}],
                              stream=True)
        assert backend.last_tool_calls == []
        list(stream)
        assert backend.last_tool_calls == [
            {"id": "a", "name": "f", "arguments": {"n": 1}}]


class TestLocalBackend:
    """The Phase-8 stub is gone; see tests/test_local_backend.py.

    Those four tests asserted the *absence* of a local backend — a
    ``NotImplementedError``, three ``False`` capabilities, and a default
    endpoint with no ``/v1``.  They are replaced rather than deleted so
    the change is visible here, next to the other two backends, and what
    stays is only what still belongs in this file: that the class is a
    ``Backend`` and that constructing one contacts nothing.
    """

    def test_is_a_backend(self):
        from core.runtime.backends.base import Backend

        assert isinstance(LocalBackend(endpoint="http://127.0.0.1:1/v1"), Backend)

    def test_chat_no_longer_raises_not_implemented(self):
        backend = LocalBackend(endpoint="http://127.0.0.1:1/v1")
        with pytest.raises(Exception) as exc:
            backend.chat("local-model", [{"role": "user", "content": "hi"}])
        assert not isinstance(exc.value, NotImplementedError)

    def test_construction_contacts_nothing(self):
        """No probe at construction: a CLI must start with the server cold."""
        LocalBackend(endpoint="http://127.0.0.1:1/v1")


class TestUsageIsReportedNeverEstimated:
    """The one rule the whole ledger rests on.

    Every other token number in this tree is an estimate — characters over
    four, used to keep a prompt inside a window and honest about being a
    guess.  This one is a provider's own count or it is nothing, because a
    platform bills from it.
    """

    def test_an_absent_object_is_nothing(self):
        assert Usage.from_payload(None) is None

    def test_an_object_with_no_counts_is_nothing_not_three_zeros(self):
        """`{}` where the counts should be is silence wearing the shape of
        a report."""
        assert Usage.from_payload({}) is None
        assert Usage.from_payload({"queue_time": 0.4}) is None

    def test_a_real_zero_is_kept(self):
        """A provider that says zero completion tokens has SAID something."""
        usage = Usage.from_payload({"prompt_tokens": 8, "completion_tokens": 0})
        assert usage is not None
        assert usage.completion_tokens == 0

    def test_a_missing_total_is_derived_from_the_two_that_were_given(self):
        """Arithmetic on numbers the provider gave, not a guess at one."""
        assert Usage.from_payload(
            {"prompt_tokens": 8, "completion_tokens": 2}).total_tokens == 10

    def test_a_stated_total_is_never_recomputed(self):
        usage = Usage.from_payload({"prompt_tokens": 8, "completion_tokens": 2,
                                    "total_tokens": 99})
        assert usage.total_tokens == 99

    def test_a_pydantic_shaped_object_is_read_through_model_dump(self):
        class _Usage:
            def model_dump(self):
                return {"prompt_tokens": 1, "completion_tokens": 2,
                        "total_tokens": 3}

        assert Usage.from_payload(_Usage()).total_tokens == 3

    def test_a_plain_object_is_read_attribute_by_attribute(self):
        got = Usage.from_payload(
            SimpleNamespace(prompt_tokens=4, completion_tokens=1,
                            total_tokens=5))
        assert (got.prompt_tokens, got.total_tokens) == (4, 5)

    def test_a_boolean_is_not_a_count(self):
        """`True` is an `int` in Python, and a flag is not one token."""
        assert Usage.from_payload({"prompt_tokens": True}) is None

    def test_unparseable_counts_are_not_counts(self):
        assert Usage.from_payload({"prompt_tokens": "many"}) is None


class TestNativeCallsTravelAsPlainDicts:
    """The seam between a provider's reply and this repo's runtime.

    A tool call crosses it as data — three keys and a fourth when
    something could not be read — so that nothing in the runtime has to
    import a backend type to learn what a model decided.  One reader for
    both shapes providers send: nested ``dict``s from the JSON backends,
    pydantic models from the OpenAI SDK.
    """

    def test_a_backend_that_says_nothing_claims_nothing(self):
        """The defaults are the answer for every backend written next, and
        a capability nobody declared is one a caller must not plan on."""
        caps = BackendCapabilities()
        assert caps.supports_tool_calls is False
        assert caps.supports_parallel_tool_calls is False
        assert caps.supports_tool_choice_required is False

    def test_a_dict_shaped_call_is_read(self):
        assert tool_calls_from([
            {"id": "a", "function": {"name": "f", "arguments": '{"n": 1}'}}
        ]) == [{"id": "a", "name": "f", "arguments": {"n": 1}}]

    def test_an_object_shaped_call_is_read_the_same_way(self):
        got = tool_calls_from([SimpleNamespace(
            id="a", function=SimpleNamespace(name="f", arguments='{"n": 1}'))])
        assert got == [{"id": "a", "name": "f", "arguments": {"n": 1}}]

    def test_arguments_already_an_object_are_taken_as_they_are(self):
        """Some servers send the object rather than a string of it."""
        assert tool_calls_from([
            {"id": "a", "function": {"name": "f", "arguments": {"n": 1}}}
        ])[0]["arguments"] == {"n": 1}

    def test_a_missing_id_is_an_empty_string_not_a_none(self):
        """The field is always there; a caller matching results back to
        calls should not have to test for two kinds of absence."""
        assert tool_calls_from([{"function": {"name": "f"}}]) == [
            {"id": "", "name": "f", "arguments": {}}]

    def test_no_arguments_at_all_loses_nothing_and_says_so(self):
        """A no-argument call is the common case, not an error."""
        assert tool_calls_from([
            {"id": "a", "function": {"name": "f", "arguments": ""}}
        ]) == [{"id": "a", "name": "f", "arguments": {}}]

    def test_valid_json_that_is_not_an_object_is_kept_raw(self):
        """There is nothing to dispatch with, and the text is the
        evidence of what the model actually asked for."""
        assert tool_calls_from([
            {"id": "a", "function": {"name": "f", "arguments": "[1, 2]"}}
        ]) == [{"id": "a", "name": "f", "arguments": {},
                "arguments_raw": "[1, 2]"}]

    def test_a_tool_calls_field_of_the_wrong_shape_is_no_calls(self):
        """Not an exception in the middle of somebody's turn."""
        assert tool_calls_from(None) == []
        assert tool_calls_from("tool_calls") == []

    def test_the_accumulator_concatenates_by_index(self):
        acc = ToolCallAccumulator()
        acc.add([{"index": 0, "id": "a",
                  "function": {"name": "f", "arguments": '{"path":'}}])
        acc.add([{"index": 0, "function": {"arguments": ' "/tmp"}'}}])
        assert acc.result() == [
            {"id": "a", "name": "f", "arguments": {"path": "/tmp"}}]

    def test_the_accumulator_reports_nothing_before_it_is_fed(self):
        assert ToolCallAccumulator().result() == []

    def test_a_fragment_without_an_index_falls_back_to_its_position(self):
        acc = ToolCallAccumulator()
        acc.add([{"id": "a", "function": {"name": "f", "arguments": "{}"}},
                 {"id": "b", "function": {"name": "g", "arguments": "{}"}}])
        assert [c["name"] for c in acc.result()] == ["f", "g"]

    def test_the_accumulator_speaks_the_same_dict_as_a_whole_reply(self):
        """One owner for the unparseable-arguments rule: a streamed call
        and a non-streamed one must not be two dialects."""
        acc = ToolCallAccumulator()
        acc.add([{"index": 0, "id": "a",
                  "function": {"name": "f", "arguments": '{"n":'}}])
        assert acc.result() == tool_calls_from([
            {"id": "a", "function": {"name": "f", "arguments": '{"n":'}}])
