# core/runtime/__init__.py

from core.runtime.backends import (
    Backend,
    BackendCapabilities,
    OpenAIBackend,
    MistralBackend,
    LocalBackend,
)
from core.runtime.messages import build_system_prompt, build_chat_context
from core.runtime.context_window import (
    Compaction,
    ContextWindowManager,
    ContextConfig,
    MissionWindow,
)
from core.runtime.gpu import GPUProfile, detect_gpu_profile
from core.runtime.provider_config import DEFAULT_MODELS, resolve_provider

__all__ = [
    "Backend",
    "BackendCapabilities",
    "OpenAIBackend",
    "MistralBackend",
    "LocalBackend",
    "build_system_prompt",
    "build_chat_context",
    "ContextWindowManager",
    "ContextConfig",
    "MissionWindow",
    "Compaction",
    "GPUProfile",
    "detect_gpu_profile",
    "DEFAULT_MODELS",
    "resolve_provider",
]
