import os
from typing import List, Dict, Any, Optional

from core.runtime.backends.openai_backend import OpenAIBackend
from core.runtime.backends.mistral_backend import MistralBackend


class UnifiedClient:
    """
    Unified client — thin router that delegates to backend implementations.
    """

    def __init__(self, provider_override: Optional[str] = None, openai_client=None):
        self.provider = (provider_override or os.getenv("ELF_PROVIDER") or "openai").lower()

        if self.provider == "openai":
            self._backend = OpenAIBackend(openai_client=openai_client)
        elif self.provider == "mistral":
            self._backend = MistralBackend()
        else:
            raise ValueError(f"Unsupported provider: {self.provider}")

    def chat(self, model: str, messages: List[Dict[str, Any]], stream: bool = False):
        return self._backend.chat(model, messages, stream)

    @property
    def capabilities(self):
        return self._backend.capabilities
