# core/runtime/backends/openai_backend.py — OpenAI SDK wrapper

import os
from typing import Any, Dict, Iterator, List

from openai import OpenAI

from core.runtime.backends.base import Backend, BackendCapabilities, Usage


class OpenAIBackend(Backend):
    def __init__(self, openai_client=None):
        if openai_client is not None:
            self.client = openai_client
        else:
            key = os.getenv("OPENAI_API_KEY")
            if not key:
                raise RuntimeError("Missing OPENAI_API_KEY")
            self.client = OpenAI(api_key=key)
        self.last_usage = None

    def chat(self, model: str, messages: List[Dict], stream: bool = False):
        # Cleared FIRST: a call that raises must not leave the previous
        # call's numbers standing, or a ledger counts them twice.
        self.last_usage = None
        if stream:
            return self._track(self.client.chat.completions.create(
                model=model, messages=messages, stream=True
            ))
        result = self.client.chat.completions.create(model=model, messages=messages)
        self.last_usage = Usage.from_payload(getattr(result, "usage", None))
        return result.choices[0].message.content

    def _track(self, chunks: Any) -> Iterator[Any]:
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
        """
        seen = None
        try:
            for chunk in chunks:
                found = Usage.from_payload(getattr(chunk, "usage", None))
                if found is not None:
                    seen = found
                yield chunk
        finally:
            self.last_usage = seen

    @property
    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            supports_streaming=True,
            supports_json_mode=True,
            supports_tool_calls=True,
            max_context_tokens=None,
            max_output_tokens=None,
        )
