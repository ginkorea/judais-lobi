# core/runtime/backends/local_backend.py — OpenAI-compatible local endpoint

"""A backend for a locally served, OpenAI-compatible chat endpoint.

This is what ``vllm serve`` (and llama.cpp's server, and LM Studio, and
Ollama's ``/v1`` shim) puts on a socket: ``POST {base}/chat/completions``
speaking the OpenAI request and response shape, and ``GET {base}/models``
listing what is loaded.

Deliberately **not** the ``openai`` SDK.  The SDK is a fine client for a
remote provider with an API key; here it would add a mandatory
``api_key`` to talk to a loopback port, and it hides the one thing this
backend exists to expose — the served model's real ``max_model_len``.
``requests`` is already a hard dependency of this package.

``base`` includes the version prefix.  ``http://127.0.0.1:8000/v1``, not
``http://127.0.0.1:8000`` — that is what an OpenAI-compatible server
advertises and what ``LOCAL_API_BASE`` is expected to hold.  A base that
omits it is repaired at construction with a warning rather than
producing a 404 an hour later.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Dict, Iterator, List, Optional

import requests

from core.runtime.backends.base import Backend, BackendCapabilities

DEFAULT_LOCAL_API_BASE = "http://127.0.0.1:8000/v1"
DEFAULT_LOCAL_MODEL = "local-model"

#: Seconds to wait on ``GET /models``.  Short: the probe is a convenience,
#: and a capabilities lookup must never be the thing that hangs a CLI.
PROBE_TIMEOUT = 5.0
#: Seconds to wait on ``POST /chat/completions``.  Long: a cold vLLM
#: server loads weights for ~100s before it answers the first request.
CHAT_TIMEOUT = 600.0


@dataclass(frozen=True)
class ServedModel:
    """What ``GET {base}/models`` said, or why it said nothing.

    ``reachable`` is the honest bit.  An unreachable server yields a
    ``ServedModel`` with ``reachable=False`` and ``max_model_len=None``
    — never a guessed context length, because a guessed context window
    is how a request gets truncated silently.
    """

    model_id: str
    max_model_len: Optional[int] = None
    reachable: bool = False
    error: str = ""


class LocalBackend(Backend):
    """Chat against an OpenAI-compatible endpoint on this host.

    Parameters
    ----------
    endpoint:
        Base URL **including** the version prefix.  Defaults to
        ``LOCAL_API_BASE`` then :data:`DEFAULT_LOCAL_API_BASE`.
    model:
        Served model name.  Defaults to ``LOCAL_MODEL``, then whatever
        ``GET {base}/models`` reports, then :data:`DEFAULT_LOCAL_MODEL`.
        The ``model`` argument to :meth:`chat` still wins when given.
    api_key:
        Sent as ``Authorization: Bearer`` when set.  Most local servers
        want no key; some are started with ``--api-key``.
    supports_tool_calls:
        Declared, not probed — see :attr:`capabilities`.
    """

    def __init__(
        self,
        endpoint: Optional[str] = None,
        model: Optional[str] = None,
        max_context_tokens: Optional[int] = None,
        max_output_tokens: Optional[int] = None,
        api_key: Optional[str] = None,
        supports_tool_calls: bool = True,
        session: Any = None,
    ):
        raw = endpoint or os.getenv("LOCAL_API_BASE") or DEFAULT_LOCAL_API_BASE
        self.endpoint = self._normalize_base(raw)
        self._model = model or os.getenv("LOCAL_MODEL") or None
        self._max_context_tokens = max_context_tokens
        self._max_output_tokens = max_output_tokens
        self._api_key = api_key or os.getenv("LOCAL_API_KEY") or None
        self._supports_tool_calls = supports_tool_calls
        self._session = session if session is not None else requests
        self._probed: Optional[ServedModel] = None

    # ── configuration ────────────────────────────────────────────────────

    @staticmethod
    def _normalize_base(base: str) -> str:
        """Strip a trailing slash; append ``/v1`` when it is missing.

        A base without the version prefix is the single most common
        misconfiguration of this backend, and it fails as a 404 on the
        first chat rather than at construction.  Repairing it here keeps
        that hour.
        """
        base = (base or "").strip().rstrip("/")
        if not base:
            return DEFAULT_LOCAL_API_BASE
        tail = base.rsplit("/", 1)[-1]
        if not tail.startswith("v") or not tail[1:].isdigit():
            base = f"{base}/v1"
        return base

    @property
    def model(self) -> str:
        """The model name this backend will send when the caller gives none."""
        if self._model:
            return self._model
        probed = self.probe()
        return probed.model_id or DEFAULT_LOCAL_MODEL

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    # ── probe ────────────────────────────────────────────────────────────

    def probe(self, refresh: bool = False) -> ServedModel:
        """``GET {base}/models``, cached.

        Never raises: an unreachable server is a fact about the server,
        and a backend that explodes when asked what it can do is useless
        for exactly the case you asked.
        """
        if self._probed is not None and not refresh:
            return self._probed

        fallback = self._model or ""
        try:
            res = self._session.get(
                f"{self.endpoint}/models",
                headers=self._headers(),
                timeout=PROBE_TIMEOUT,
            )
            res.raise_for_status()
            payload = res.json() or {}
        except Exception as exc:  # noqa: BLE001 — any failure is "unreachable"
            self._probed = ServedModel(
                model_id=fallback, reachable=False, error=f"{type(exc).__name__}: {exc}",
            )
            return self._probed

        entries = payload.get("data") or []
        entry: Dict[str, Any] = {}
        if self._model:
            entry = next(
                (e for e in entries if isinstance(e, dict) and e.get("id") == self._model),
                {},
            )
        if not entry and entries and isinstance(entries[0], dict):
            entry = entries[0]

        self._probed = ServedModel(
            model_id=str(entry.get("id") or fallback),
            max_model_len=self._as_int(entry.get("max_model_len")),
            reachable=True,
        )
        return self._probed

    @staticmethod
    def _as_int(value: Any) -> Optional[int]:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    # ── chat ─────────────────────────────────────────────────────────────

    def chat(
        self,
        model: str,
        messages: List[Dict],
        stream: bool = False,
        max_tokens: Optional[int] = None,
        **extra: Any,
    ):
        """POST ``{base}/chat/completions``.

        Returns a ``str`` when ``stream`` is false and an iterator of
        SSE deltas when it is true — the same two return types
        ``OpenAIBackend.chat`` has, because ``core.cli`` branches on
        ``chunk.choices[0].delta.content`` and does not know which
        backend it is draining.
        """
        body: Dict[str, Any] = {
            "model": model or self.model,
            "messages": messages,
        }
        limit = max_tokens if max_tokens is not None else self._max_output_tokens
        if limit is not None:
            body["max_tokens"] = limit
        body.update(extra)

        if stream:
            body["stream"] = True
            return self._stream(body)
        return self._complete(body)

    def _post(self, body: Dict[str, Any], stream: bool):
        return self._session.post(
            f"{self.endpoint}/chat/completions",
            headers=self._headers(),
            json=body,
            timeout=CHAT_TIMEOUT,
            stream=stream,
        )

    def _complete(self, body: Dict[str, Any]) -> str:
        res = self._post(body, stream=False)
        res.raise_for_status()
        payload = res.json() or {}
        choices = payload.get("choices") or []
        if not choices:
            return ""
        return (choices[0].get("message") or {}).get("content") or ""

    def _stream(self, body: Dict[str, Any]) -> Iterator[SimpleNamespace]:
        res = self._post(body, stream=True)
        res.raise_for_status()
        for line in res.iter_lines():
            if not line:
                continue
            if isinstance(line, bytes):
                line = line.decode("utf-8", errors="replace")
            if not line.startswith("data:"):
                continue
            data = line[len("data:"):].strip()
            if not data or data == "[DONE]":
                if data == "[DONE]":
                    break
                continue
            try:
                chunk = json.loads(data)
            except json.JSONDecodeError:
                continue
            yield self._as_delta(chunk)

    @staticmethod
    def _as_delta(chunk: Dict[str, Any]) -> SimpleNamespace:
        """Reshape one SSE chunk into what ``core.cli`` walks.

        ``SimpleNamespace`` and not a dataclass on purpose: the consumer
        is ``getattr`` chains written against the OpenAI SDK's objects,
        and matching that shape is the whole job.
        """
        choices = []
        for raw in chunk.get("choices") or []:
            delta = raw.get("delta") or {}
            choices.append(
                SimpleNamespace(
                    index=raw.get("index", 0),
                    finish_reason=raw.get("finish_reason"),
                    delta=SimpleNamespace(
                        role=delta.get("role"),
                        content=delta.get("content"),
                        tool_calls=delta.get("tool_calls"),
                    ),
                )
            )
        return SimpleNamespace(
            id=chunk.get("id"),
            model=chunk.get("model"),
            choices=choices,
        )

    # ── capabilities ─────────────────────────────────────────────────────

    @property
    def capabilities(self) -> BackendCapabilities:
        """What this endpoint can do, probed where probing can answer.

        ``max_context_tokens`` is the served model's ``max_model_len``
        when ``GET /models`` reports one, an explicit constructor value
        otherwise, and ``None`` when neither — never a guess.

        ``supports_tool_calls`` is **declared, not probed**: no field of
        ``/models`` answers it, and the OpenAI-compatible contract this
        backend speaks includes ``tools``.  A vLLM-served gpt-oss-20b
        honours it, which is why the default is ``True`` and why the old
        stub's ``False`` was wrong rather than cautious.  A server that
        does not, gets ``supports_tool_calls=False`` at construction.
        """
        probed = self.probe()
        max_context = self._max_context_tokens
        if max_context is None:
            max_context = probed.max_model_len
        return BackendCapabilities(
            supports_streaming=True,
            supports_json_mode=True,
            supports_tool_calls=self._supports_tool_calls,
            max_context_tokens=max_context,
            max_output_tokens=self._max_output_tokens,
        )
