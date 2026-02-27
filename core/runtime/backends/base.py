# core/runtime/backends/base.py — Backend ABC + capabilities dataclass

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List


@dataclass(frozen=True)
class BackendCapabilities:
    supports_streaming: bool = True
    supports_json_mode: bool = False
    supports_tool_calls: bool = False
    max_context_tokens: int | None = None
    max_output_tokens: int | None = None


class Backend(ABC):
    @property
    @abstractmethod
    def capabilities(self) -> BackendCapabilities: ...

    @abstractmethod
    def chat(self, model: str, messages: List[Dict], stream: bool = False):
        """Returns str (non-streaming) or iterator of SimpleNamespace (streaming)."""
        ...
