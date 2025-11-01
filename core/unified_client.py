# core/unified_client.py
import os
from mistralai import Mistral
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

        # Allow CLI/provider override
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

        # Initialize provider client
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

    # --------------------------------------------------
    # Unified chat interface
    # --------------------------------------------------
    def chat(self, model: str, messages: list[dict], stream: bool = False):
        """Run chat completion compatible with both providers."""
        if self.provider == "openai":
            return self._chat_openai(model, messages, stream)
        elif self.provider == "mistral":
            return self._chat_mistral(model, messages, stream)
        else:
            raise RuntimeError("No valid provider initialized.")

    # --------------------------------------------------
    # OpenAI backend
    # --------------------------------------------------
    def _chat_openai(self, model, messages, stream=False):
        if stream:
            return self.client.chat.completions.create(
                model=model,
                messages=messages,
                stream=True,
            )
        res = self.client.chat.completions.create(model=model, messages=messages)
        return res.choices[0].message.content

    # --------------------------------------------------
    # Mistral backend
    # --------------------------------------------------
    def _chat_mistral(self, model, messages, stream=False):
        """
        Mistral SDK ≥1.9.0 uses:
          client.chat.complete(model=..., messages=..., stream=True/False)
        Messages are simple dicts: [{"role": "user", "content": "..."}]
        """

        if not all("role" in m and "content" in m for m in messages):
            raise ValueError("Messages must be list of dicts with 'role' and 'content'")

        if stream:
            # Mistral streaming generator
            stream_gen = self.client.chat.complete(model=model, messages=messages, stream=True)
            for event in stream_gen:
                # Mistral stream yields delta chunks under event.data.choices[0].delta["content"]
                if hasattr(event, "data") and event.data and getattr(event.data, "choices", None):
                    delta_text = event.data.choices[0].delta.get("content", "")
                    if delta_text:
                        yield SimpleNamespace(
                            choices=[SimpleNamespace(delta=SimpleNamespace(content=delta_text))]
                        )
            return None

        # Non-streaming response
        res = self.client.chat.complete(model=model, messages=messages, stream=False)
        if hasattr(res, "choices") and res.choices and hasattr(res.choices[0], "message"):
            return res.choices[0].message.content
        return ""
