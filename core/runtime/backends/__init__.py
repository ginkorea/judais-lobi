# core/runtime/backends/__init__.py

from core.runtime.backends.base import Backend, BackendCapabilities
from core.runtime.backends.openai_backend import OpenAIBackend
from core.runtime.backends.mistral_backend import MistralBackend
from core.runtime.backends.local_backend import LocalBackend
# Safe to import unconditionally: the module soft-imports the `anthropic`
# SDK and only refuses when someone actually builds a backend without it.
from core.runtime.backends.anthropic_backend import AnthropicBackend

__all__ = [
    "Backend",
    "BackendCapabilities",
    "OpenAIBackend",
    "AnthropicBackend",
    "MistralBackend",
    "LocalBackend",
]
