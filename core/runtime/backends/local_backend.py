# core/runtime/backends/local_backend.py — Stub for Phase 8

from typing import Dict, List

from core.runtime.backends.base import Backend, BackendCapabilities


class LocalBackend(Backend):
    def __init__(self, endpoint: str = "http://localhost:8000"):
        self.endpoint = endpoint

    def chat(self, model: str, messages: List[Dict], stream: bool = False):
        raise NotImplementedError(
            "Local inference not yet implemented. See Phase 8."
        )

    @property
    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            supports_streaming=False,
            supports_json_mode=False,
            supports_tool_calls=False,
        )
