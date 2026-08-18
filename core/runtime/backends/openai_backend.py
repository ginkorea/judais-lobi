# core/runtime/backends/openai_backend.py — OpenAI SDK wrapper

import os
from typing import Any, Dict, Iterator, List

from openai import OpenAI

from core.runtime.backends.base import (
    Backend,
    BackendCapabilities,
    ToolCallAccumulator,
    Usage,
    tool_calls_from,
)
from core.runtime.backends import state


class OpenAIBackend(Backend):
    #: The word :class:`core.unified_client.UnifiedClient` routes on.
    provider_name = "openai"

    def __init__(self, openai_client=None):
        if openai_client is not None:
            self.client = openai_client
        else:
            key = os.getenv("OPENAI_API_KEY")
            if not key:
                raise RuntimeError("Missing OPENAI_API_KEY")
            self.client = OpenAI(api_key=key)
        self.last_usage = None
        self.last_tool_calls = []

    def chat(self, model: str, messages: List[Dict], stream: bool = False,
             **extra: Any):
        """Create a chat completion, returning content or a stream of chunks.

        ``**extra`` reaches ``chat.completions.create`` verbatim — it is
        where ``tools``, ``tool_choice``, ``parallel_tool_calls`` and
        ``response_format`` travel, all of them ordinary parameters of
        that call.  Nothing is added when the caller passes nothing: the
        request this backend has always sent is still the request it sends.

        Native tool calls come back on :attr:`last_tool_calls` rather than
        in the return value, which stays a ``str`` (or an iterator) for
        every caller that has ever read it.

        What the model itself is doing goes out on the third side
        channel — :meth:`~core.runtime.backends.base.Backend.report_state`
        — and for a hosted provider that is a short story: ``asking``,
        then ``loaded``, unless the SDK raises, in which case the status
        it carries is read through
        :func:`~core.runtime.backends.policy.state_for_status` so that a
        429 says ``queued`` rather than ``failed``.  No first-byte alarm
        here, unlike the local backend: a hosted endpoint does not load
        weights while you wait, and the wait this repo could not explain
        was never theirs.
        """
        # Cleared FIRST: a call that raises must not leave the previous
        # call's numbers — or its decisions — standing, or a ledger counts
        # them twice and a runner dispatches a tool nobody asked for.
        self.last_usage = None
        self.last_tool_calls = []
        self.report_state(state.ASKING, model=model)
        try:
            if stream:
                return self._track(self.client.chat.completions.create(
                    model=model, messages=messages, stream=True, **extra
                ), model)
            result = self.client.chat.completions.create(
                model=model, messages=messages, **extra)
        except Exception as exc:
            self.report_failure(exc, model=model)
            raise
        self.report_state(state.LOADED,
                          model=str(getattr(result, "model", "") or model))
        self.last_usage = Usage.from_payload(getattr(result, "usage", None))
        message = result.choices[0].message
        self.last_tool_calls = tool_calls_from(
            getattr(message, "tool_calls", None))
        return message.content

    def _track(self, chunks: Any, model: str = "") -> Iterator[Any]:
        """Pass every chunk through, keeping the last usage any of them carried.

        The SDK's own iterator is what a caller has always received, so
        this yields its objects untouched — ``core.cli`` walks
        ``chunk.choices[0].delta.content`` and must not learn a second
        shape.  What it adds is the ``finally``: usage rides the last
        frame, and a consumer that abandons the stream still leaves
        behind whatever the provider had reported by then.

        Nothing is *requested* here.  The OpenAI API sends a usage frame
        on a streamed completion only when asked with
        ``stream_options``, and adding that to every streamed call would
        change the request this backend has always sent.  The local
        backend, which serves this repo's own endpoints, does ask; see
        :meth:`~core.runtime.backends.local_backend.LocalBackend.chat`.

        A streamed tool call is read the same way and on the same
        schedule.  Its arguments arrive as a JSON string in pieces across
        many frames, so there is nothing to publish until the last one:
        the accumulator folds each frame's ``delta.tool_calls`` in, and
        the ``finally`` puts the reassembled calls on
        ``last_tool_calls`` — including for a consumer that walks away,
        who then sees exactly the calls that had fully arrived.
        """
        seen = None
        calls = ToolCallAccumulator()
        arrived = False
        try:
            for chunk in chunks:
                if not arrived:
                    # The first frame is the provider answering. Said here
                    # rather than where the stream was opened, because the
                    # SDK returns its iterator before the first token.
                    arrived = True
                    self.report_state(
                        state.LOADED,
                        model=str(getattr(chunk, "model", "") or model))
                found = Usage.from_payload(getattr(chunk, "usage", None))
                if found is not None:
                    seen = found
                for choice in getattr(chunk, "choices", None) or []:
                    delta = getattr(choice, "delta", None)
                    calls.add(getattr(delta, "tool_calls", None))
                yield chunk
        except Exception as exc:
            self.report_failure(exc, model=model)
            raise
        finally:
            self.last_usage = seen
            self.last_tool_calls = calls.result()

    @property
    def capabilities(self) -> BackendCapabilities:
        """What the OpenAI API does, which is all of it.

        ``parallel_tool_calls`` and ``tool_choice="required"`` are both
        documented parameters of ``chat.completions.create`` and both are
        honoured by the models this backend is pointed at, so they are
        declared here rather than probed — there is no endpoint to ask.
        """
        return BackendCapabilities(
            supports_streaming=True,
            supports_json_mode=True,
            supports_tool_calls=True,
            supports_parallel_tool_calls=True,
            supports_tool_choice_required=True,
            max_context_tokens=None,
            max_output_tokens=None,
        )
