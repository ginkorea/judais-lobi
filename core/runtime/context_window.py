# core/runtime/context_window.py — Context window tracking + auto-compaction

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from core.context.formatter import estimate_tokens
from core.runtime.gpu import GPUProfile, detect_gpu_profile, vram_to_context_cap
from core.tools.config_loader import load_project_config


@dataclass(frozen=True)
class ModelContextProfile:
    max_context_tokens: int
    max_output_tokens: int
    source: str = "default"

    @property
    def max_input_tokens(self) -> int:
        return max(self.max_context_tokens - self.max_output_tokens, 0)


@dataclass
class ContextConfig:
    max_context_tokens: Optional[int] = None
    max_output_tokens: Optional[int] = None
    min_tail_messages: int = 6
    max_summary_chars: int = 2400
    model_overrides: Dict[str, int] = field(default_factory=dict)

    @staticmethod
    def from_project(project_root=None) -> "ContextConfig":
        cfg = load_project_config(project_root)
        ctx = cfg.get("context", {}) if isinstance(cfg, dict) else {}
        return ContextConfig(
            max_context_tokens=ctx.get("max_context_tokens"),
            max_output_tokens=ctx.get("max_output_tokens"),
            min_tail_messages=int(ctx.get("min_tail_messages", 6)),
            max_summary_chars=int(ctx.get("max_summary_chars", 2400)),
            model_overrides=dict(ctx.get("model_overrides", {}) or {}),
        )


DEFAULT_MODEL_CONTEXTS: Dict[str, ModelContextProfile] = {
    # Conservative defaults; override in .judais-lobi.yml if needed.
    "gpt-4o": ModelContextProfile(128000, 4096, source="default"),
    "gpt-4o-mini": ModelContextProfile(128000, 4096, source="default"),
    "gpt-4.1": ModelContextProfile(128000, 4096, source="default"),
    "gpt-4.1-mini": ModelContextProfile(128000, 4096, source="default"),
    "gpt-4-turbo": ModelContextProfile(128000, 4096, source="default"),
    "gpt-4": ModelContextProfile(8192, 2048, source="default"),
    "gpt-3.5-turbo": ModelContextProfile(16384, 2048, source="default"),
    "codestral-latest": ModelContextProfile(32768, 4096, source="default"),
    "mistral-large-latest": ModelContextProfile(32768, 4096, source="default"),
}


@dataclass
class ContextStats:
    total_tokens: int
    limit_tokens: int
    was_compacted: bool
    summary_tokens: int = 0
    removed_messages: int = 0
    profile_source: str = "default"


class ContextWindowManager:
    """Builds a token-bounded message list with optional compaction."""

    def __init__(self, config: Optional[ContextConfig] = None, project_root=None):
        self._config = config or ContextConfig.from_project(project_root)

    def build_messages(
        self,
        system_prompt: str,
        history: List[Dict[str, str]],
        invoked_tools: Optional[List[str]],
        provider: str,
        model: str,
        backend_caps=None,
        gpu_profile: Optional[GPUProfile] = None,
    ) -> Tuple[List[Dict[str, str]], ContextStats]:
        from core.runtime.messages import build_chat_context

        messages = build_chat_context(system_prompt, history, invoked_tools)
        profile = self._resolve_profile(provider, model, backend_caps, gpu_profile)
        compacted, stats = self._compact(messages, profile)
        return compacted, stats

    def _resolve_profile(
        self,
        provider: str,
        model: str,
        backend_caps=None,
        gpu_profile: Optional[GPUProfile] = None,
    ) -> ModelContextProfile:
        cfg = self._config
        # Backend capabilities override (instance-aware)
        if backend_caps is not None:
            max_ctx = getattr(backend_caps, "max_context_tokens", None)
            max_out = getattr(backend_caps, "max_output_tokens", None)
            if max_ctx and max_out:
                return ModelContextProfile(max_ctx, max_out, source="backend")

        # Model overrides from config
        if cfg.model_overrides and model in cfg.model_overrides:
            max_ctx = int(cfg.model_overrides[model])
            max_out = int(cfg.max_output_tokens or 4096)
            return ModelContextProfile(max_ctx, max_out, source="config")

        # Global config overrides
        if cfg.max_context_tokens:
            max_ctx = int(cfg.max_context_tokens)
            max_out = int(cfg.max_output_tokens or 4096)
            return ModelContextProfile(max_ctx, max_out, source="config")

        # Default model lookup
        base = DEFAULT_MODEL_CONTEXTS.get(model, ModelContextProfile(16384, 2048, source="fallback"))

        # GPU-aware cap for local inference (or explicit provider)
        if provider == "local":
            profile = gpu_profile or detect_gpu_profile()
            cap = vram_to_context_cap(profile.total_vram_gb)
            if cap:
                return ModelContextProfile(min(base.max_context_tokens, cap), base.max_output_tokens, source="gpu_cap")

        return base

    def _compact(
        self, messages: List[Dict[str, str]], profile: ModelContextProfile
    ) -> Tuple[List[Dict[str, str]], ContextStats]:
        limit = profile.max_input_tokens
        total_tokens = _estimate_messages_tokens(messages)
        if total_tokens <= limit:
            return messages, ContextStats(total_tokens, limit, False, profile_source=profile.source)

        if len(messages) <= 2:
            return messages, ContextStats(total_tokens, limit, False, profile_source=profile.source)

        system = messages[0]
        tail = messages[1:][-self._config.min_tail_messages :]
        head = messages[1:-self._config.min_tail_messages]
        summary = _summarize_messages(head, self._config.max_summary_chars)

        compacted = [system, summary] + tail
        new_tokens = _estimate_messages_tokens(compacted)

        # Shrink summary until within limit or minimal
        while new_tokens > limit and len(summary["content"]) > 120:
            summary["content"] = summary["content"][: max(120, int(len(summary["content"]) * 0.8))] + "…"
            compacted = [system, summary] + tail
            new_tokens = _estimate_messages_tokens(compacted)

        stats = ContextStats(
            total_tokens=new_tokens,
            limit_tokens=limit,
            was_compacted=True,
            summary_tokens=_estimate_messages_tokens([summary]),
            removed_messages=len(head),
            profile_source=profile.source,
        )
        return compacted, stats


def _estimate_messages_tokens(messages: List[Dict[str, str]]) -> int:
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        total += estimate_tokens(content) + 4
    return total


def _summarize_messages(messages: List[Dict[str, str]], max_chars: int) -> Dict[str, str]:
    lines: List[str] = []
    for msg in messages:
        role = msg.get("role", "unknown")
        content = (msg.get("content") or "").strip().replace("\n", " ")
        snippet = content[:220]
        if len(content) > 220:
            snippet += "…"
        lines.append(f"{role}: {snippet}")

    body = "\n".join(lines)
    if len(body) > max_chars:
        body = body[: max_chars - 1] + "…"

    return {
        "role": "assistant",
        "content": (
            "Context summary (auto-compacted for context window):\n"
            f"{body}"
        ),
    }
