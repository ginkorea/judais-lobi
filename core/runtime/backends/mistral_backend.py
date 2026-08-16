# core/runtime/backends/mistral_backend.py — Mistral over httpx

"""Chat against Mistral's hosted OpenAI-compatible endpoint.

This used to shell out to ``curl`` with the request body in a temp file,
and it cost three things that had nothing to do with Mistral:

* **The key was an argv element.** ``-H "Authorization: Bearer sk-…"`` is
  readable in ``ps`` by every user on the host, for as long as the request
  runs. The CLI's own ``--mcp-token`` help says *"prefer the env var; an
  argument is visible in ps"* — the backend was doing the thing the CLI
  warns operators against. A header set in-process is visible to nobody.
* **No timeout.** ``subprocess.run`` without one waits forever, so a hung
  connection hung the whole agent with no step, no event and no way back.
* **A temp file per call.** In streaming mode the ``os.unlink`` sat inside
  the generator, after the loop: a consumer that stopped iterating early —
  which is every abandoned stream, every ``break``, every exception in the
  render loop — left a world-readable file holding the entire prompt.

``httpx`` is already a hard dependency (``setup.py`` ``install_requires``),
speaks SSE, and takes the body from memory. Not the ``mistralai`` SDK:
this is one POST against a documented shape, and the SDK would be a second
opinion about retries and errors alongside the one
:mod:`core.runtime.backends.local_backend` already owns.

The timeout and connect-retry policy are **imported** from that module
rather than restated here. One owner per fact: two backends that both
POST a chat completion should not drift apart on how long they wait.
"""

from __future__ import annotations

import json
import os
import time
from types import SimpleNamespace
from typing import Any, Dict, Iterator, List, Optional

import httpx

from core.runtime.backends.base import (
    Backend,
    BackendCapabilities,
    ToolCallAccumulator,
    Usage,
    tool_calls_from,
)
from core.runtime.backends.local_backend import CHAT_TIMEOUT, LocalBackend

CHAT_URL = "https://api.mistral.ai/v1/chat/completions"
DEFAULT_MISTRAL_MODEL = "codestral-latest"

#: Backoff (seconds) before each retry of a refused connect. The same tuple
#: the local backend retries on, imported and not copied — the reasoning
#: there ("a whole turn is too much to pay for one blip") is about the cost
#: of losing a turn, not about vLLM, and it is identical here.
CONNECT_RETRIES = LocalBackend.CONNECT_RETRIES

#: How much of the provider's error body to put in front of a caller.
#: Same bound, and the same reason, as ``LocalBackend.ERROR_DETAIL_CHARS``:
#: enough for a real sentence, short enough that a stack trace does not
#: become the error message.
ERROR_DETAIL_CHARS = LocalBackend.ERROR_DETAIL_CHARS


class MistralBackend(Backend):
    """Mistral's ``/v1/chat/completions``, spoken in-process.

    Parameters
    ----------
    client:
        Anything with ``post`` and ``stream`` in :mod:`httpx`'s shape —
        the module itself by default, an ``httpx.Client`` or a stub when
        injected. Mirrors ``LocalBackend(session=…)``: constructing a
        backend must not open a socket, and a test must not need one.
    """

    def __init__(self, client: Any = None):
        self.api_key = os.getenv("MISTRAL_API_KEY")
        if not self.api_key:
            raise RuntimeError("Missing MISTRAL_API_KEY")
        self._client = client if client is not None else httpx
        self.last_usage = None
        self.last_tool_calls = []

    # ── request ──────────────────────────────────────────────────────────

    def _headers(self) -> Dict[str, str]:
        """Auth in a header, built per call and never in an argument list."""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def chat(
        self,
        model: str,
        messages: List[Dict],
        stream: bool = False,
        **extra: Any,
    ):
        """POST a chat completion.

        Returns a ``str`` when ``stream`` is false and an iterator of SSE
        deltas when it is true — the two return types every backend here
        has, because ``core.cli`` walks ``chunk.choices[0].delta.content``
        without knowing which backend filled it.
        """
        # Cleared before anything is sent: a call that raises must not
        # leave the previous call's numbers — or its tool calls — standing
        # for a ledger to count, or a runner to dispatch, a second time.
        self.last_usage = None
        self.last_tool_calls = []
        body: Dict[str, Any] = {
            "model": model or DEFAULT_MISTRAL_MODEL,
            "messages": messages,
            "stream": stream,
        }
        body.update(extra)

        if stream:
            return self._stream(body)
        return self._complete(body)

    def _post(self, body: Dict[str, Any]) -> Any:
        last: Optional[Exception] = None
        for wait in (0.0, *CONNECT_RETRIES):
            if wait:
                time.sleep(wait)
            try:
                return self._client.post(
                    CHAT_URL,
                    headers=self._headers(),
                    json=body,
                    timeout=CHAT_TIMEOUT,
                )
            except httpx.ConnectError as exc:
                # Refused/unresolved connect only. A status code or a
                # mid-body timeout is the provider ANSWERING, and resending
                # those would bill and possibly duplicate a completion.
                last = exc
        raise last  # type: ignore[misc]

    def _open_stream(self, body: Dict[str, Any]):
        """Enter ``client.stream`` under the same connect-retry policy.

        Returns the entered context manager alongside its response: the
        request happens in ``__enter__``, so retrying means building and
        entering a fresh one. The caller owns the exit — see
        :meth:`_stream`, where it is a ``finally``.
        """
        last: Optional[Exception] = None
        for wait in (0.0, *CONNECT_RETRIES):
            if wait:
                time.sleep(wait)
            ctx = self._client.stream(
                "POST",
                CHAT_URL,
                headers=self._headers(),
                json=body,
                timeout=CHAT_TIMEOUT,
            )
            try:
                return ctx, ctx.__enter__()
            except httpx.ConnectError as exc:
                last = exc
        raise last  # type: ignore[misc]

    # ── responses ────────────────────────────────────────────────────────

    def _raise_for_status(self, res: Any) -> None:
        """Fail with what the provider SAID, not just the number it returned.

        The curl version could not do this: a non-2xx body arrived on
        stdout, ``parsed["choices"]`` raised ``KeyError``, and the ``except``
        handed the error JSON back to the caller *as the assistant's reply*.
        An authentication failure read as an answer. Same treatment as
        ``LocalBackend._raise_for_status`` now: the body is the diagnosis.
        """
        if res.status_code < 400:
            return
        # A streamed response has not read its body yet; a read one is a
        # no-op. Either way `.text` needs this first.
        res.read()
        try:
            detail = (res.json() or {}).get("message") or res.text
        except ValueError:
            detail = res.text
        if not isinstance(detail, str):
            detail = json.dumps(detail)
        detail = (detail or "").strip()[:ERROR_DETAIL_CHARS]
        message = (f"{res.status_code} from {CHAT_URL}"
                   + (f": {detail}" if detail
                      else " (and the provider said nothing)"))
        raise httpx.HTTPStatusError(
            message, request=getattr(res, "request", None), response=res,
        )

    def _complete(self, body: Dict[str, Any]) -> str:
        res = self._post(body)
        self._raise_for_status(res)
        payload = res.json() or {}
        # Before the empty-choices return, not after it: a completion that
        # produced no content still cost tokens, and a reply nobody could
        # use is exactly the call an operator wants to find billed.
        self.last_usage = Usage.from_payload(payload.get("usage"))
        choices = payload.get("choices") or []
        if not choices:
            return ""
        message = choices[0].get("message") or {}
        # Read even though `capabilities` declares no tool-call support:
        # `**extra` has always reached the body, so a caller CAN send
        # `tools` here, and a reply this backend refused to look at would
        # be silently thrown away. Reporting what arrived costs nothing
        # and claims nothing — see `capabilities` for why the flag stays
        # False regardless.
        self.last_tool_calls = tool_calls_from(message.get("tool_calls"))
        return message.get("content") or ""

    def _stream(self, body: Dict[str, Any]) -> Iterator[SimpleNamespace]:
        """Yield one delta per SSE frame that carries content.

        The ``finally`` is the whole point of the rewrite. A consumer that
        abandons this iterator — ``break``, an exception, a dropped
        reference — gets ``GeneratorExit`` thrown in at the ``yield``, and
        the connection is released on the way out. The old code released
        its temp file *after* the loop, so exactly the case that needed
        cleanup was the case that never ran it.
        """
        ctx, res = self._open_stream(body)
        seen: Optional[Usage] = None
        calls = ToolCallAccumulator()
        try:
            self._raise_for_status(res)
            for line in res.iter_lines():
                if isinstance(line, bytes):
                    line = line.decode("utf-8", errors="replace")
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                data = line[len("data:"):].strip()
                if data == "[DONE]":
                    break
                if not data:
                    continue
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                # Mistral puts `usage` on the last content frame rather
                # than on a frame of its own, so every chunk is read and
                # the last one to carry counts wins. Read BEFORE the
                # yield: a consumer that stops on the frame that happened
                # to carry the counts still leaves them behind.
                found = Usage.from_payload(chunk.get("usage"))
                if found is not None:
                    seen = found
                for choice in chunk.get("choices") or []:
                    calls.add(((choice or {}).get("delta") or {}).get(
                        "tool_calls"))
                content = self._delta_content(chunk)
                if content:
                    yield self._as_delta(content)
        finally:
            # In the same `finally` that releases the connection, for the
            # same reason: abandonment is the case that has to work.
            self.last_usage = seen
            self.last_tool_calls = calls.result()
            ctx.__exit__(None, None, None)

    @staticmethod
    def _delta_content(chunk: Dict[str, Any]) -> Optional[str]:
        choices = chunk.get("choices") or []
        if not choices:
            return None
        return ((choices[0] or {}).get("delta") or {}).get("content")

    @staticmethod
    def _as_delta(content: str) -> SimpleNamespace:
        """The shape ``core.cli`` walks, and only frames that fill it.

        Narrower than ``LocalBackend._as_delta`` on purpose: this backend
        has always dropped empty frames rather than passing them on with
        ``content=None``, and callers that count chunks would notice the
        difference. ``SimpleNamespace`` because the consumer is a
        ``getattr`` chain written against the OpenAI SDK's objects.
        """
        return SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content=content))]
        )

    # ── capabilities ─────────────────────────────────────────────────────

    @property
    def capabilities(self) -> BackendCapabilities:
        """What this backend will stand behind, which is less than the API does.

        All three tool-call flags are ``False``, and that is a statement
        about this repository rather than about Mistral. Their API does
        document ``tools`` and a ``tool_choice``, and ``**extra`` already
        forwards both — a caller who sends them will get whatever the
        provider does, and :attr:`last_tool_calls` will report it. What is
        missing is a verified round trip: nothing here has been run against
        the live endpoint with tools declared, and their ``tool_choice``
        vocabulary is not the OpenAI one this repo's ``"required"`` rule is
        written against.

        A capability flag is a promise a caller plans against — the runtime
        reads these to decide whether a native protocol may run at all — and
        a promise made from documentation alone is how a mission refuses at
        step six instead of at the door. Flipping any of these is a
        one-line change for whoever runs that round trip and can say what
        came back.
        """
        return BackendCapabilities(
            supports_streaming=True,
            supports_json_mode=True,
            supports_tool_calls=False,
            supports_parallel_tool_calls=False,
            supports_tool_choice_required=False,
            max_context_tokens=None,
            max_output_tokens=None,
        )
