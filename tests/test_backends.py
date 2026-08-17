# tests/test_backends.py — Tests for backend implementations

import ast
import pathlib

import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock

from core.runtime.backends import policy
from core.runtime.backends.base import (
    BackendCapabilities,
    ToolCallAccumulator,
    Usage,
    tool_calls_from,
)
from core.runtime.backends.anthropic_backend import (
    DEFAULT_ANTHROPIC_MODEL,
    DEFAULT_MAX_TOKENS,
    AnthropicBackend,
    from_anthropic_messages,
    to_anthropic_messages,
    to_anthropic_tool_choice,
    to_anthropic_tools,
)
from core.runtime.backends.openai_backend import OpenAIBackend
from core.runtime.backends.mistral_backend import MistralBackend
from core.runtime.backends.local_backend import LocalBackend

REPO = pathlib.Path(__file__).resolve().parent.parent


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

    def test_timeout_is_the_shared_policy(self):
        """One owner: the two raw-HTTP backends do not drift on how long
        to wait, and the owner is `policy` rather than the other backend."""
        from core.runtime.backends import local_backend, mistral_backend

        assert mistral_backend.CHAT_TIMEOUT is policy.CHAT_TIMEOUT
        assert local_backend.CHAT_TIMEOUT is policy.CHAT_TIMEOUT
        assert mistral_backend.CONNECT_RETRIES is policy.CONNECT_RETRIES
        assert LocalBackend.CONNECT_RETRIES is policy.CONNECT_RETRIES

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
            "core.runtime.backends.policy.time.sleep", waits.append)
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


class TestTheHTTPPolicyHasOneOwner:
    """`policy` owns the timeout, the retry loop and the error message.

    Mistral used to import all three from the local backend — the right
    instinct (one owner per fact) pointed at the wrong owner. These tests
    pin the owner rather than the value: the numbers may change, but a
    fourth hand-written retry loop must not appear.
    """

    def _imports(self, rel):
        tree = ast.parse((REPO / rel).read_text(encoding="utf-8"))
        return {node.module for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom) and node.module}

    def test_mistral_no_longer_imports_the_local_backend(self):
        """Asserted on the import graph, not on the text: the module
        docstring still *mentions* local_backend, because saying where a
        rule used to live is how the next person avoids putting it back."""
        assert not [m for m in self._imports("core/runtime/backends/mistral_backend.py")
                    if m.endswith("local_backend")]

    def test_the_policy_imports_nothing_from_core(self):
        """The bottom of the stack. A policy that can reach up into the
        runtime is not a policy, it is a second opinion about it."""
        assert not [m for m in self._imports("core/runtime/backends/policy.py")
                    if m.split(".")[0] == "core"]

    def test_the_error_class_table_is_data(self):
        """Four classes, one retried. Stated so a reader cannot mistake an
        accident for a decision — and so this test can read it."""
        assert set(policy.ERROR_POLICY) == {"connect", "timeout", "4xx", "5xx"}
        assert policy.ERROR_POLICY["connect"].retry is True
        assert [name for name, row in policy.ERROR_POLICY.items()
                if not row.retry] == ["timeout", "4xx", "5xx"]
        assert all(row.why.strip() for row in policy.ERROR_POLICY.values())

    def test_a_refused_connect_is_retried_on_the_stated_budget(self):
        waits = []
        attempts = []

        def flaky():
            attempts.append(1)
            if len(attempts) < 3:
                raise httpx_connect_error()
            return "ok"

        assert policy.retry_on_connect(flaky, sleep=waits.append) == "ok"
        assert len(attempts) == 3
        assert waits == list(policy.CONNECT_RETRIES[:2])

    def test_the_budget_is_spent_and_then_it_raises(self):
        import httpx

        waits = []
        attempts = []

        def dead():
            attempts.append(1)
            raise httpx_connect_error()

        with pytest.raises(httpx.ConnectError):
            policy.retry_on_connect(dead, sleep=waits.append)
        assert len(attempts) == 1 + len(policy.CONNECT_RETRIES)

    def test_a_timeout_is_never_resent(self):
        """The request IS in flight — see ERROR_POLICY['timeout']."""
        import httpx

        attempts = []

        def slow():
            attempts.append(1)
            raise httpx.ReadTimeout("mid-body")

        with pytest.raises(httpx.ReadTimeout):
            policy.retry_on_connect(slow, sleep=lambda _: None)
        assert len(attempts) == 1

    def test_both_libraries_connect_errors_are_the_policys(self):
        """One place says which failures never left this host."""
        import httpx
        import requests

        assert set(policy.CONNECT_ERRORS) == {
            requests.exceptions.ConnectionError, httpx.ConnectError}

    def test_the_body_is_the_diagnosis(self):
        res = _StubResponse(status_code=500, payload={"message": "bad max_tokens"})
        with pytest.raises(Exception) as exc:
            policy.raise_for_status(res, "http://x/v1/chat/completions")
        assert "500" in str(exc.value)
        assert "http://x/v1/chat/completions" in str(exc.value)
        assert "bad max_tokens" in str(exc.value)

    def test_a_server_that_said_nothing_is_reported_as_saying_nothing(self):
        res = _StubResponse(status_code=502, text="")
        with pytest.raises(Exception, match="said nothing"):
            policy.raise_for_status(res, "http://x")

    def test_an_unparseable_body_is_still_evidence(self):
        res = _StubResponse(status_code=400, text="<html>nginx</html>")
        with pytest.raises(Exception, match="nginx"):
            policy.raise_for_status(res, "http://x")

    def test_the_detail_is_bounded(self):
        res = _StubResponse(status_code=500, payload={"message": "x" * 5000})
        detail = policy.error_detail(res)
        assert len(detail) == policy.ERROR_DETAIL_CHARS

    def test_below_400_raises_nothing(self):
        policy.raise_for_status(_StubResponse(status_code=204), "http://x")


def httpx_connect_error():
    import httpx

    return httpx.ConnectError("refused")


# ── Anthropic ───────────────────────────────────────────────────────────


class _StubEvents:
    """An SDK stream: iterable once, closable, and it remembers being closed."""

    def __init__(self, events):
        self._events = list(events)
        self.closed = False

    def __iter__(self):
        return iter(self._events)

    def close(self):
        self.closed = True


class _StubAnthropic:
    """The one call this backend makes, and what it was called with.

    Mirrors `_RecordingClient` above: most of these tests are about the
    REQUEST — which parameter carried the system prompt, what the tool
    choice was translated into — and not about what came back.
    """

    def __init__(self, result=None, events=()):
        self.result = result
        self.events = events
        self.calls = []
        self.streams = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs.get("stream"):
            stream = _StubEvents(self.events)
            self.streams.append(stream)
            return stream
        return self.result


def _reply(blocks, usage=None):
    return SimpleNamespace(content=list(blocks), usage=usage)


def _text(text):
    return {"type": "text", "text": text}


def _use(call_id, name, payload):
    return {"type": "tool_use", "id": call_id, "name": name, "input": payload}


class TestAnthropicBackend:
    """The Messages API behind this repo's Backend contract."""

    def _backend(self, client, **kw):
        return AnthropicBackend(client=client, **kw)

    # ── construction ─────────────────────────────────────────────────────

    def test_missing_key_raises(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with pytest.raises(RuntimeError, match="Missing ANTHROPIC_API_KEY"):
            AnthropicBackend()

    def test_construction_contacts_nothing(self):
        client = _StubAnthropic()
        self._backend(client)
        assert client.calls == []

    def test_an_injected_client_needs_no_key(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        assert self._backend(_StubAnthropic()).model == DEFAULT_ANTHROPIC_MODEL

    # ── capabilities ─────────────────────────────────────────────────────

    def test_capabilities(self):
        caps = self._backend(_StubAnthropic()).capabilities
        assert caps.supports_streaming is True
        assert caps.supports_tool_calls is True
        assert caps.supports_parallel_tool_calls is True
        assert caps.supports_tool_choice_required is True

    def test_there_is_no_json_mode_because_there_is_no_response_format(self):
        """A statement about a parameter, not about the model: the
        Messages API has no `response_format`, so a caller that asks
        `capabilities` before sending one is told the truth."""
        assert self._backend(_StubAnthropic()).capabilities.supports_json_mode is False

    def test_the_context_window_comes_from_the_table(self):
        caps = self._backend(_StubAnthropic(), model="claude-haiku-4-5").capabilities
        assert caps.max_context_tokens == 200_000
        assert caps.max_output_tokens == 64_000

    def test_a_dated_snapshot_inherits_its_familys_window(self):
        caps = self._backend(_StubAnthropic(),
                             model="claude-haiku-4-5-20251001").capabilities
        assert caps.max_context_tokens == 200_000
        assert caps.max_output_tokens == 64_000

    def test_an_unknown_model_claims_no_window_rather_than_guessing(self):
        caps = self._backend(_StubAnthropic(), model="claude-next").capabilities
        assert caps.max_context_tokens is None
        assert caps.max_output_tokens is None

    # ── non-streaming ────────────────────────────────────────────────────

    def test_non_streaming_returns_the_text_blocks(self):
        client = _StubAnthropic(result=_reply([_text("hello "), _text("there")]))
        backend = self._backend(client)
        assert backend.chat("m", [{"role": "user", "content": "hi"}]) == "hello there"

    def test_max_tokens_is_always_sent_because_the_api_demands_one(self):
        client = _StubAnthropic(result=_reply([]))
        self._backend(client).chat("m", [{"role": "user", "content": "hi"}])
        assert client.calls[0]["max_tokens"] == DEFAULT_MAX_TOKENS

    def test_a_callers_max_tokens_wins(self):
        client = _StubAnthropic(result=_reply([]))
        self._backend(client).chat("m", [{"role": "user", "content": "hi"}],
                                   max_tokens=99)
        assert client.calls[0]["max_tokens"] == 99

    def test_the_model_defaults_and_then_remembers(self):
        client = _StubAnthropic(result=_reply([]))
        backend = self._backend(client)
        backend.chat("", [{"role": "user", "content": "hi"}])
        assert client.calls[0]["model"] == DEFAULT_ANTHROPIC_MODEL
        backend.chat("claude-haiku-4-5", [{"role": "user", "content": "hi"}])
        assert client.calls[1]["model"] == "claude-haiku-4-5"
        assert backend.capabilities.max_context_tokens == 200_000

    def test_a_provider_extra_travels_rather_than_being_dropped(self):
        client = _StubAnthropic(result=_reply([]))
        self._backend(client).chat("m", [{"role": "user", "content": "hi"}],
                                   stop_sequences=["</done>"])
        assert client.calls[0]["stop_sequences"] == ["</done>"]

    # ── the system parameter ─────────────────────────────────────────────

    def test_a_system_message_becomes_the_system_parameter(self):
        client = _StubAnthropic(result=_reply([]))
        self._backend(client).chat("m", [
            {"role": "system", "content": "be brief"},
            {"role": "user", "content": "hi"}])
        call = client.calls[0]
        assert call["system"] == "be brief"
        assert call["messages"] == [{"role": "user", "content": "hi"}]

    def test_a_later_system_turn_is_not_dropped(self):
        """A runtime that appends a reminder mid-conversation must not
        have it silently thrown away."""
        client = _StubAnthropic(result=_reply([]))
        self._backend(client).chat("m", [
            {"role": "system", "content": "be brief"},
            {"role": "user", "content": "hi"},
            {"role": "system", "content": "and cite sources"}])
        assert client.calls[0]["system"] == "be brief\n\nand cite sources"

    def test_no_system_message_sends_no_system_parameter(self):
        client = _StubAnthropic(result=_reply([]))
        self._backend(client).chat("m", [{"role": "user", "content": "hi"}])
        assert "system" not in client.calls[0]

    # ── tools and the choice ─────────────────────────────────────────────

    def test_openai_tools_become_input_schema(self):
        schema = {"type": "object", "properties": {"path": {"type": "string"}}}
        assert to_anthropic_tools([{
            "type": "function",
            "function": {"name": "read", "description": "read a file",
                         "parameters": schema}}]) == [
            {"name": "read", "input_schema": schema, "description": "read a file"}]

    def test_a_tool_already_in_anthropics_shape_is_left_alone(self):
        spec = {"name": "read", "input_schema": {"type": "object"}}
        assert to_anthropic_tools([spec]) == [spec]

    def test_no_tools_sends_no_tools(self):
        assert to_anthropic_tools([]) is None

    def test_required_becomes_any(self):
        assert to_anthropic_tool_choice("required") == {"type": "any"}

    def test_auto_and_none_survive(self):
        assert to_anthropic_tool_choice("auto") == {"type": "auto"}
        assert to_anthropic_tool_choice("none") == {"type": "none"}

    def test_a_named_function_becomes_a_named_tool(self):
        assert to_anthropic_tool_choice(
            {"type": "function", "function": {"name": "read"}}) == {
                "type": "tool", "name": "read"}

    def test_no_choice_is_no_choice_and_not_auto(self):
        """Sending nothing leaves the request as it would have been."""
        assert to_anthropic_tool_choice(None) is None
        assert to_anthropic_tool_choice("something-else") is None

    def test_parallel_off_becomes_the_disable_flag(self):
        assert to_anthropic_tool_choice("required", False) == {
            "type": "any", "disable_parallel_tool_use": True}

    def test_parallel_off_with_no_choice_invents_one_to_hang_it_on(self):
        assert to_anthropic_tool_choice(None, False) == {
            "type": "auto", "disable_parallel_tool_use": True}

    def test_parallel_on_says_nothing_because_it_is_the_default(self):
        assert to_anthropic_tool_choice("required", True) == {"type": "any"}

    def test_the_native_kwargs_are_translated_on_the_way_out(self):
        client = _StubAnthropic(result=_reply([]))
        self._backend(client).chat(
            "m", [{"role": "user", "content": "hi"}],
            tools=[{"type": "function",
                    "function": {"name": "f", "parameters": {"type": "object"}}}],
            tool_choice="required", parallel_tool_calls=True)
        call = client.calls[0]
        assert call["tools"] == [{"name": "f", "input_schema": {"type": "object"}}]
        assert call["tool_choice"] == {"type": "any"}
        assert "parallel_tool_calls" not in call

    def test_a_call_with_no_extras_still_sends_no_extras(self):
        client = _StubAnthropic(result=_reply([]))
        self._backend(client).chat("m", [{"role": "user", "content": "hi"}])
        assert set(client.calls[0]) == {"model", "messages", "max_tokens"}

    # ── message translation, both ways ───────────────────────────────────

    NATIVE = [
        {"role": "system", "content": "be brief"},
        {"role": "user", "content": "read it"},
        {"role": "assistant", "content": "on it",
         "tool_calls": [{"id": "t1", "type": "function",
                         "function": {"name": "read_file",
                                      "arguments": '{"path": "/tmp/a"}'}}]},
        {"role": "tool", "tool_call_id": "t1", "content": "contents"},
        {"role": "user", "content": "thanks"},
    ]

    def test_an_assistant_turns_calls_become_tool_use_blocks(self):
        _, out = to_anthropic_messages(self.NATIVE)
        assert out[1] == {"role": "assistant", "content": [
            {"type": "text", "text": "on it"},
            {"type": "tool_use", "id": "t1", "name": "read_file",
             "input": {"path": "/tmp/a"}}]}

    def test_a_tool_result_becomes_a_user_turn(self):
        _, out = to_anthropic_messages(self.NATIVE)
        assert out[2] == {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1",
             "content": "contents"}]}
        assert out[3] == {"role": "user", "content": "thanks"}

    def test_parallel_results_are_gathered_into_one_user_turn(self):
        """Splitting them teaches the model to stop calling in parallel."""
        _, out = to_anthropic_messages([
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": "a", "function": {"name": "f", "arguments": "{}"}},
                {"id": "b", "function": {"name": "g", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "a", "content": "1"},
            {"role": "tool", "tool_call_id": "b", "content": "2"},
        ])
        assert len(out) == 2
        assert [b["tool_use_id"] for b in out[1]["content"]] == ["a", "b"]

    def test_an_empty_assistant_turn_is_not_sent(self):
        """The API refuses empty content, and a turn with nothing in it
        said nothing."""
        _, out = to_anthropic_messages([
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": ""}])
        assert out == [{"role": "user", "content": "hi"}]

    def test_the_translation_round_trips(self):
        system, out = to_anthropic_messages(self.NATIVE)
        back = from_anthropic_messages(out, system=system)
        assert back == [
            {"role": "system", "content": "be brief"},
            {"role": "user", "content": "read it"},
            {"role": "assistant", "content": "on it",
             "tool_calls": [{"id": "t1", "type": "function",
                             "function": {"name": "read_file",
                                          "arguments": '{"path": "/tmp/a"}'}}]},
            {"role": "tool", "tool_call_id": "t1", "content": "contents"},
            {"role": "user", "content": "thanks"},
        ]

    def test_the_missions_synthetic_functions_round_trip(self):
        """`mission_result` and `mission_answer` are just tools, and the
        translator gets no special case for them — this is the test that
        says so."""
        native = [
            {"role": "user", "content": "go"},
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": "m1", "type": "function",
                 "function": {"name": "mission_answer",
                              "arguments": '{"text": "done"}'}}]},
            {"role": "tool", "tool_call_id": "m1", "content": "ok"},
        ]
        system, out = to_anthropic_messages(native)
        assert out[1]["content"][0]["name"] == "mission_answer"
        assert from_anthropic_messages(out, system=system) == native

    # ── what a reply reports ─────────────────────────────────────────────

    def test_tool_use_blocks_arrive_beside_the_return_value(self):
        client = _StubAnthropic(result=_reply(
            [_use("t1", "read_file", {"path": "/tmp/a"})]))
        backend = self._backend(client)
        assert backend.chat("m", [{"role": "user", "content": "hi"}]) == ""
        assert backend.last_tool_calls == [
            {"id": "t1", "name": "read_file", "arguments": {"path": "/tmp/a"}}]

    def test_every_call_is_reported_in_the_order_they_came(self):
        client = _StubAnthropic(result=_reply([
            _text("both"), _use("a", "f", {}), _use("b", "g", {"n": 1})]))
        backend = self._backend(client)
        assert backend.chat("m", [{"role": "user", "content": "hi"}]) == "both"
        assert [c["id"] for c in backend.last_tool_calls] == ["a", "b"]
        assert backend.last_tool_calls[1]["arguments"] == {"n": 1}

    def test_a_reply_with_no_calls_is_an_empty_list(self):
        client = _StubAnthropic(result=_reply([_text("hi")]))
        backend = self._backend(client)
        backend.chat("m", [{"role": "user", "content": "hi"}])
        assert backend.last_tool_calls == []

    def test_usage_is_read_off_input_and_output_tokens(self):
        client = _StubAnthropic(result=_reply([_text("hi")], usage={
            "input_tokens": 12, "output_tokens": 3,
            "cache_read_input_tokens": 7}))
        backend = self._backend(client)
        backend.chat("m", [{"role": "user", "content": "hi"}])
        assert backend.last_usage.prompt_tokens == 12
        assert backend.last_usage.completion_tokens == 3
        assert backend.last_usage.total_tokens == 15
        assert backend.last_usage.extra["cache_read_input_tokens"] == 7

    def test_an_sdk_shaped_usage_object_is_read_the_same_way(self):
        client = _StubAnthropic(result=_reply([_text("hi")], usage=SimpleNamespace(
            input_tokens=4, output_tokens=1)))
        backend = self._backend(client)
        backend.chat("m", [{"role": "user", "content": "hi"}])
        assert backend.last_usage.total_tokens == 5

    def test_a_reply_without_usage_reports_nothing_not_zero(self):
        client = _StubAnthropic(result=_reply([_text("hi")]))
        backend = self._backend(client)
        backend.chat("m", [{"role": "user", "content": "hi"}])
        assert backend.last_usage is None

    def test_a_usage_object_carrying_no_counts_is_silence_too(self):
        """`{}` where the counts should be is silence wearing the shape
        of a report, and three zeros would be a fabricated number on a
        stream a platform bills from."""
        client = _StubAnthropic(result=_reply([_text("hi")], usage={}))
        backend = self._backend(client)
        backend.chat("m", [{"role": "user", "content": "hi"}])
        assert backend.last_usage is None

    def test_a_usage_object_with_only_a_cache_field_still_reports_nothing(self):
        client = _StubAnthropic(result=_reply(
            [_text("hi")], usage={"cache_read_input_tokens": 7}))
        backend = self._backend(client)
        backend.chat("m", [{"role": "user", "content": "hi"}])
        assert backend.last_usage is None

    def test_a_raised_call_leaves_nothing_behind(self):
        client = _StubAnthropic(result=_reply([_use("a", "f", {})], usage={
            "input_tokens": 1, "output_tokens": 1}))
        backend = self._backend(client)
        backend.chat("m", [{"role": "user", "content": "hi"}])
        assert backend.last_usage is not None and backend.last_tool_calls

        def boom(**kwargs):
            raise RuntimeError("nope")

        client.messages.create = boom
        with pytest.raises(RuntimeError):
            backend.chat("m", [{"role": "user", "content": "hi"}])
        assert backend.last_usage is None
        assert backend.last_tool_calls == []

    # ── streaming ────────────────────────────────────────────────────────

    STREAM = [
        {"type": "message_start",
         "message": {"usage": {"input_tokens": 12, "output_tokens": 1}}},
        {"type": "content_block_start", "index": 0,
         "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "text_delta", "text": "he"}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "text_delta", "text": "llo"}},
        {"type": "content_block_stop", "index": 0},
        {"type": "message_delta", "delta": {"stop_reason": "end_turn"},
         "usage": {"output_tokens": 9}},
        {"type": "message_stop"},
    ]

    def test_stream_yields_text_deltas(self):
        client = _StubAnthropic(events=self.STREAM)
        backend = self._backend(client)
        chunks = list(backend.chat("m", [{"role": "user", "content": "x"}],
                                   stream=True))
        assert [c.choices[0].delta.content for c in chunks] == ["he", "llo"]
        assert client.calls[0]["stream"] is True

    def test_nothing_is_sent_until_the_stream_is_iterated(self):
        client = _StubAnthropic(events=self.STREAM)
        self._backend(client).chat("m", [{"role": "user", "content": "x"}],
                                   stream=True)
        assert client.calls == []

    def test_a_streams_usage_is_merged_from_both_frames(self):
        """`input_tokens` rides message_start and the final
        `output_tokens` rides message_delta; either alone is half a
        ledger entry."""
        client = _StubAnthropic(events=self.STREAM)
        backend = self._backend(client)
        stream = backend.chat("m", [{"role": "user", "content": "x"}], stream=True)
        assert backend.last_usage is None, "nothing honest to say yet"
        list(stream)
        assert backend.last_usage.prompt_tokens == 12
        assert backend.last_usage.completion_tokens == 9
        assert backend.last_usage.total_tokens == 21

    def test_streamed_tool_calls_are_assembled_from_their_fragments(self):
        events = [
            {"type": "message_start", "message": {"usage": {"input_tokens": 3}}},
            {"type": "content_block_start", "index": 0,
             "content_block": {"type": "tool_use", "id": "t1",
                               "name": "read_file"}},
            {"type": "content_block_delta", "index": 0,
             "delta": {"type": "input_json_delta", "partial_json": '{"path"'}},
            {"type": "content_block_delta", "index": 0,
             "delta": {"type": "input_json_delta", "partial_json": ': "/tmp/a"}'}},
            {"type": "content_block_stop", "index": 0},
            {"type": "message_delta", "usage": {"output_tokens": 5}},
        ]
        client = _StubAnthropic(events=events)
        backend = self._backend(client)
        assert list(backend.chat("m", [{"role": "user", "content": "x"}],
                                 stream=True)) == []
        assert backend.last_tool_calls == [
            {"id": "t1", "name": "read_file", "arguments": {"path": "/tmp/a"}}]

    def test_two_streamed_calls_are_kept_apart_by_index(self):
        events = [
            {"type": "content_block_start", "index": 0,
             "content_block": {"type": "tool_use", "id": "a", "name": "f"}},
            {"type": "content_block_start", "index": 1,
             "content_block": {"type": "tool_use", "id": "b", "name": "g"}},
            {"type": "content_block_delta", "index": 1,
             "delta": {"type": "input_json_delta", "partial_json": '{"n": 2}'}},
            {"type": "content_block_delta", "index": 0,
             "delta": {"type": "input_json_delta", "partial_json": '{"n": 1}'}},
        ]
        backend = self._backend(_StubAnthropic(events=events))
        list(backend.chat("m", [{"role": "user", "content": "x"}], stream=True))
        assert backend.last_tool_calls == [
            {"id": "a", "name": "f", "arguments": {"n": 1}},
            {"id": "b", "name": "g", "arguments": {"n": 2}}]

    def test_an_abandoned_stream_is_closed_and_leaves_what_arrived(self):
        client = _StubAnthropic(events=self.STREAM)
        backend = self._backend(client)
        stream = backend.chat("m", [{"role": "user", "content": "x"}], stream=True)
        next(stream)
        stream.close()
        assert client.streams[0].closed is True
        # The prompt's cost had been reported by then; the completion's
        # had not, and nothing is invented to stand in for it.
        assert backend.last_usage.prompt_tokens == 12
        assert backend.last_usage.completion_tokens == 1

    def test_a_stream_that_reported_nothing_reports_nothing(self):
        events = [{"type": "content_block_delta", "index": 0,
                   "delta": {"type": "text_delta", "text": "hi"}}]
        backend = self._backend(_StubAnthropic(events=events))
        list(backend.chat("m", [{"role": "user", "content": "x"}], stream=True))
        assert backend.last_usage is None
