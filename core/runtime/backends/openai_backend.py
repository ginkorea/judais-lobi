# core/runtime/backends/openai_backend.py — OpenAI SDK wrapper

import os
from typing import Dict, List

from openai import OpenAI

from core.runtime.backends.base import Backend, BackendCapabilities


class OpenAIBackend(Backend):
    def __init__(self, openai_client=None):
        if openai_client is not None:
            self.client = openai_client
        else:
            key = os.getenv("OPENAI_API_KEY")
            if not key:
                raise RuntimeError("Missing OPENAI_API_KEY")
            self.client = OpenAI(api_key=key)

    def chat(self, model: str, messages: List[Dict], stream: bool = False):
        if stream:
            return self.client.chat.completions.create(
                model=model, messages=messages, stream=True
            )
        result = self.client.chat.completions.create(model=model, messages=messages)
        return result.choices[0].message.content

    @property
    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            supports_streaming=True,
            supports_json_mode=True,
            supports_tool_calls=True,
            max_context_tokens=None,
            max_output_tokens=None,
        )
