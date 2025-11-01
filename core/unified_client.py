# core/unified_client.py
import os
from mistralai import Mistral
from mistralai.models.chat_completion import ChatMessage
from openai import OpenAI
from types import SimpleNamespace


class UnifiedClient:
    """
    Unified chat interface for OpenAI and Mistral.
    Supports provider override via CLI or environment.
    """

    def __init__(self, provider_override: str | None = None):
        self.provider = None
        self.client = None

        mistral_key = os.getenv("MISTRAL_API_KEY")
        openai_key = os.getenv("OPENAI_API_KEY")

        # Provider override via CLI or environment
        if provider_override:
            provider_override = provider_override.lower().strip()
            if provider_override not in ("openai", "mistral"):
                raise ValueError("provider_override must be 'openai' or 'mistral'")
            self.provider = provider_override

        # Auto-detect provider if not manually set
        if not self.provider:
            if mistral_key:
                self.provider = "mistral"
            elif openai_key:
                self.provider = "openai"
            else:
                raise RuntimeError("No API key found for OpenAI or Mistral.")

        # Initialize appropriate client
        if self.provider == "mistral":
            if not mistral_key:
                raise RuntimeError("MISTRAL_API_KEY not set.")
            self.client = Mistral(api_key=mistral_key)
        elif self.provider == "openai":
            if not openai_key:
                raise RuntimeError("OPENAI_API_KEY not set.")
            self.client = OpenAI(api_key=openai_key)
        else:
            raise RuntimeError(f"Unknown provider: {self.provider}")

    # ------------------------
    # Unified chat interface
    # ------------------------
    def chat(self, model, messages, stream=False):
        if self.provider == "openai":
            return self._chat_openai(model, messages, stream)
        elif self.provider == "mistral":
            return self._chat_mistral(model, messages, stream)
        else:
            raise RuntimeError("No valid provider initialized.")

    # ------------------------
    # OpenAI logic
    # ------------------------
    def _chat_openai(self, model, messages, stream=False):
        if stream:
            return self.client.chat.completions.create(
                model=model, messages=messages, stream=True
            )
        res = self.client.chat.completions.create(model=model, messages=messages)
        return res.choices[0].message.content

    # ------------------------
    # Mistral logic
    # ------------------------
    def _chat_mistral(self, model, messages, stream=False):
        if not all("role" in m and "content" in m for m in messages):
            raise ValueError("Messages must be list of dicts with 'role' and 'content'")

        if stream:
            stream_gen = self.client.chat.stream(model=model, messages=messages)
            for event in stream_gen:
                if event.data and event.data.choices:
                    delta_text = event.data.choices[0].delta.get("content", "")
                    if delta_text:
                        yield SimpleNamespace(
                            choices=[SimpleNamespace(delta=SimpleNamespace(content=delta_text))]
                        )
            return None

        res = self.client.chat.complete(model=model, messages=messages)
        if res and res.choices and res.choices[0].message:
            return res.choices[0].message.content
        return ""
