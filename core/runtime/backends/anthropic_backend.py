# core/runtime/backends/anthropic_backend.py — Anthropic Messages API

"""Chat against Anthropic's Messages API, in this repo's own shape.

The critic tier has spoken Anthropic since February — see
:class:`core.critic.backends.AnthropicCritic` — but only as a one-shot
auditor: one user turn in, one text block out. This is the other half: a
:class:`~core.runtime.backends.base.Backend` a mission can actually run
on, with streaming, native tool calls and a token ledger.

**The SDK, not httpx.**  ``anthropic`` owns its transport, its retries and
its error types, and re-deriving those against a documented wire format
would be a second opinion about all three. That is the same bargain
:mod:`core.runtime.backends.openai_backend` strikes, and
:mod:`core.runtime.backends.policy` states the rule the four backends
follow: an SDK where the provider ships one, one shared policy module for
the two that speak HTTP by hand. The import is **soft**, like
``core.tools.mcp_client``'s — ``judais --help`` has to keep working on an
install that never asked for ``[anthropic]``.

**Everything else here is translation.**  The Messages API is not the
OpenAI chat-completions shape, and the mission speaks the latter
everywhere: OpenAI-shaped ``tools``, ``tool_choice``,
``parallel_tool_calls``, a ``role: system`` first message, assistant turns
carrying ``tool_calls``, and ``role: tool`` results. Each of those has an
Anthropic spelling and the mapping lives in the module-level functions
below rather than inside :meth:`AnthropicBackend.chat`, so that it can be
tested in both directions and read without a client:

===========================  =========================================
OpenAI shape (what we send)  Anthropic shape (what goes on the wire)
===========================  =========================================
``{"role": "system", ...}``  the top-level ``system`` parameter
``tools[].function``         ``tools[]`` with ``input_schema``
``tool_choice="required"``   ``{"type": "any"}``
``tool_choice={"type":       ``{"type": "tool", "name": …}``
"function", …}``
``parallel_tool_calls``      ``tool_choice.disable_parallel_tool_use``
assistant ``tool_calls``     ``tool_use`` blocks in the assistant turn
``{"role": "tool", …}``      ``tool_result`` blocks in a **user** turn
``usage.prompt_tokens``      ``usage.input_tokens``
===========================  =========================================

``max_tokens`` is **required** by the Messages API — there is no "as much
as it takes" — so this module supplies :data:`DEFAULT_MAX_TOKENS` when a
caller names none, and any ``max_tokens`` in ``**extra`` wins.

There is no ``response_format``.  Anthropic constrains output through
``output_config.format`` (structured outputs) and through ``strict`` tool
schemas, neither of which is the OpenAI parameter the runtime sends, so
:attr:`AnthropicBackend.capabilities` reports ``supports_json_mode=False``
rather than translating a request whose semantics differ. A caller that
sends ``response_format`` anyway gets the provider's 400, unedited — a
loud refusal beats a silently dropped constraint.
"""

from __future__ import annotations

import json
import os
from types import SimpleNamespace
from typing import Any, Dict, Iterator, List, Mapping, Optional, Tuple

from core.runtime.backends.base import (
    Backend,
    BackendCapabilities,
    ToolCallAccumulator,
    Usage,
    attr_or_key,
    tool_calls_from,
)

try:  # pragma: no cover - exercised by the install that lacks it
    from anthropic import Anthropic as _Anthropic
except Exception:  # noqa: BLE001 - any import failure is "not installed"
    _Anthropic = None

#: The model used when a caller names none.  Sonnet tier on purpose: the
#: sibling defaults are ``gpt-4o-mini`` and ``codestral-latest``, and a
#: framework default that quietly costs Opus money is a decision a
#: deployment should make rather than inherit.  Undated, because a dated
#: snapshot pinned here goes stale silently — ``--model`` and
#: ``DEFAULT_MODELS`` are where a deployment says otherwise.
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-5"

#: What to send as ``max_tokens`` when the caller names none.  The API
#: refuses a request without it, so there is no "unset" to pass through.
#: 16k keeps a non-streamed call inside the SDK's own HTTP timeout; a
#: caller streaming a long answer raises it in ``**extra``.
DEFAULT_MAX_TOKENS = 16000

#: ``model -> (max_context_tokens, max_output_tokens)``.  A small table,
#: deliberately: there is no ``GET /models`` in this SDK's hot path and a
#: guessed context window is how a prompt gets truncated silently, so a
#: model that is not listed reports ``None`` rather than a plausible
#: number.  Matched by longest prefix, so a dated snapshot
#: (``claude-sonnet-5-20260101``) inherits its family's limits.
MODEL_LIMITS: Dict[str, Tuple[int, int]] = {
    "claude-fable-5": (1_000_000, 128_000),
    "claude-mythos-5": (1_000_000, 128_000),
    "claude-opus-5": (1_000_000, 128_000),
    "claude-opus-4-8": (1_000_000, 128_000),
    "claude-opus-4-7": (1_000_000, 128_000),
    "claude-opus-4-6": (1_000_000, 128_000),
    "claude-sonnet-5": (1_000_000, 128_000),
    "claude-sonnet-4-6": (1_000_000, 128_000),
    "claude-haiku-4-5": (200_000, 64_000),
}


def model_limits(model: str) -> Tuple[Optional[int], Optional[int]]:
    """``(context, output)`` for *model*, or ``(None, None)`` for an unknown one.

    Exact match first, then the longest listed prefix — a dated snapshot
    of a listed family has that family's window, and a name from a
    generation this table has never heard of reports nothing.
    """
    name = (model or "").strip()
    if name in MODEL_LIMITS:
        return MODEL_LIMITS[name]
    matches = [key for key in MODEL_LIMITS if name.startswith(key)]
    if not matches:
        return (None, None)
    return MODEL_LIMITS[max(matches, key=len)]


# ── translation: what a message is ──────────────────────────────────────


def _as_text(content: Any) -> str:
    """A content field flattened to text, whatever shape it arrived in."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, (list, tuple)):
        return "".join(
            str(attr_or_key(part, "text") or "")
            for part in content
            if attr_or_key(part, "type") in (None, "text")
        )
    return str(content)


def to_anthropic_messages(
    messages: List[Dict],
) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    """OpenAI-shaped messages in; ``(system, messages)`` out.

    Four rules, and they are the whole difference between the two APIs:

    * **``role: system`` is not a message.**  Anthropic takes the system
      prompt as a top-level parameter, so every system turn is lifted out
      and joined — *every* one, not just the first, because a runtime
      that appends a system reminder mid-conversation must not have it
      silently dropped.
    * **An assistant turn's decisions are blocks.**  ``content`` becomes a
      ``text`` block and each entry of ``tool_calls`` a ``tool_use``
      block, in that order, in one assistant message. An assistant turn
      that carries neither is skipped: the API refuses empty content, and
      a turn with nothing in it says nothing.
    * **A tool result is a user turn.**  OpenAI gives a tool result its
      own ``role: tool`` message; Anthropic puts ``tool_result`` blocks in
      the *user* turn that answers the assistant. Consecutive results are
      therefore gathered into **one** user message — which is also what
      parallel tool use requires, and splitting them teaches the model to
      stop making parallel calls.
    * **Order survives.**  Results are flushed before any other turn is
      appended, so a user message that follows a tool result stays after
      it.

    Arguments arrive as a JSON *string* in the OpenAI shape and must be an
    object in Anthropic's, and that parse has one owner already:
    :func:`~core.runtime.backends.base.tool_calls_from`, the same function
    :attr:`Backend.last_tool_calls` is built with. Unreadable arguments
    become ``{}`` there rather than a raise here.
    """
    system_parts: List[str] = []
    out: List[Dict[str, Any]] = []
    pending: List[Dict[str, Any]] = []

    def flush() -> None:
        if pending:
            out.append({"role": "user", "content": list(pending)})
            pending.clear()

    for raw in messages or []:
        role = str(attr_or_key(raw, "role") or "").lower()
        content = attr_or_key(raw, "content")

        if role == "system":
            text = _as_text(content).strip()
            if text:
                system_parts.append(text)
            continue

        if role == "tool":
            pending.append({
                "type": "tool_result",
                "tool_use_id": str(attr_or_key(raw, "tool_call_id") or ""),
                "content": _as_text(content),
            })
            continue

        flush()

        if role == "assistant":
            blocks: List[Dict[str, Any]] = []
            text = content if isinstance(content, str) else _as_text(content)
            if text:
                blocks.append({"type": "text", "text": text})
            for call in tool_calls_from(attr_or_key(raw, "tool_calls")):
                blocks.append({
                    "type": "tool_use",
                    "id": call["id"],
                    "name": call["name"],
                    "input": call["arguments"],
                })
            if blocks:
                out.append({"role": "assistant", "content": blocks})
            continue

        # Everything else is a user turn.  A list content is passed
        # through untouched: it is already blocks, and this module has no
        # business rewriting an image the caller assembled.
        out.append({
            "role": "user",
            "content": content if isinstance(content, (str, list)) else _as_text(content),
        })

    flush()
    return ("\n\n".join(system_parts) or None), out


def from_anthropic_messages(
    messages: List[Dict],
    system: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """The inverse of :func:`to_anthropic_messages`.

    Anthropic-shaped turns back into the OpenAI shape the rest of this
    tree reads: *system* becomes a leading ``role: system`` message,
    ``tool_use`` blocks become an assistant ``tool_calls`` list with their
    input re-serialized as a JSON string, and ``tool_result`` blocks
    become ``role: tool`` messages — emitted **before** any text in the
    same user turn, because that is where OpenAI requires them.

    Written and tested alongside the forward direction rather than added
    when something needed it. A translator only ever exercised one way is
    a translator whose round trip nobody has checked, and this one has a
    round-trip test.
    """
    out: List[Dict[str, Any]] = []
    if system:
        out.append({"role": "system", "content": system})

    for raw in messages or []:
        role = str(attr_or_key(raw, "role") or "")
        content = attr_or_key(raw, "content")

        if isinstance(content, str):
            out.append({"role": role, "content": content})
            continue

        blocks = list(content or [])

        if role == "assistant":
            message: Dict[str, Any] = {
                "role": "assistant",
                "content": _as_text(blocks) or None,
            }
            calls = [
                {
                    "id": str(attr_or_key(block, "id") or ""),
                    "type": "function",
                    "function": {
                        "name": str(attr_or_key(block, "name") or ""),
                        "arguments": json.dumps(attr_or_key(block, "input") or {}),
                    },
                }
                for block in blocks
                if attr_or_key(block, "type") == "tool_use"
            ]
            if calls:
                message["tool_calls"] = calls
            out.append(message)
            continue

        for block in blocks:
            if attr_or_key(block, "type") != "tool_result":
                continue
            out.append({
                "role": "tool",
                "tool_call_id": str(attr_or_key(block, "tool_use_id") or ""),
                "content": _as_text(attr_or_key(block, "content")),
            })
        text = _as_text([b for b in blocks
                         if attr_or_key(b, "type") in (None, "text")])
        if text:
            out.append({"role": role or "user", "content": text})

    return out


# ── translation: what a request asks for ────────────────────────────────


def to_anthropic_tools(tools: Any) -> Optional[List[Dict[str, Any]]]:
    """OpenAI ``tools`` in, Anthropic ``tools`` out.

    ``{"type": "function", "function": {"name", "description",
    "parameters"}}`` becomes ``{"name", "description", "input_schema"}``.
    A spec that already carries ``input_schema`` is passed through, so a
    caller that speaks Anthropic natively is not made to speak OpenAI
    first.

    The mission's two synthetic functions — ``mission_result`` and
    ``mission_answer`` — need no special case here and get none: they are
    ordinary tool declarations and they round-trip as ordinary tool calls.
    """
    if not tools:
        return None
    out: List[Dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, Mapping):
            continue
        if "input_schema" in tool:
            out.append(dict(tool))
            continue
        function = tool.get("function") if tool.get("type") == "function" else tool
        function = function if isinstance(function, Mapping) else {}
        spec: Dict[str, Any] = {
            "name": str(function.get("name") or ""),
            "input_schema": function.get("parameters")
            or {"type": "object", "properties": {}},
        }
        description = function.get("description")
        if description:
            spec["description"] = description
        out.append(spec)
    return out or None


def to_anthropic_tool_choice(
    tool_choice: Any = None,
    parallel_tool_calls: Any = None,
) -> Optional[Dict[str, Any]]:
    """The two OpenAI knobs that constrain tool use, as Anthropic's one.

    ``"auto"`` stays ``auto``; ``"required"`` — and Anthropic's own
    ``"any"`` — becomes ``{"type": "any"}``, which is the constrained
    decode the mission's ``--protocol native`` is written against;
    ``"none"`` stays ``none``; a named function becomes ``{"type":
    "tool", "name": …}``. A mapping that is already Anthropic-shaped is
    passed through.

    ``parallel_tool_calls`` is not a parameter of the Messages API at
    all: the negative of it is, as ``disable_parallel_tool_use`` **on the
    tool choice**. So ``parallel_tool_calls=False`` sets that flag —
    inventing an ``auto`` choice to hang it on if the caller named none —
    and ``True`` sets nothing, because more than one call per reply is
    already the default and a flag that restates the default is noise.

    ``None`` out means "send no ``tool_choice``", which is not the same
    as sending ``auto``: it leaves the request exactly as it would have
    been, and an unrecognized value is treated the same way rather than
    guessed at.
    """
    choice: Optional[Dict[str, Any]] = None

    if isinstance(tool_choice, str):
        name = tool_choice.strip().lower()
        if name == "auto":
            choice = {"type": "auto"}
        elif name in ("required", "any"):
            choice = {"type": "any"}
        elif name == "none":
            choice = {"type": "none"}
    elif isinstance(tool_choice, Mapping):
        kind = tool_choice.get("type")
        if kind == "function":
            function = tool_choice.get("function")
            function = function if isinstance(function, Mapping) else {}
            choice = {"type": "tool", "name": str(function.get("name") or "")}
        elif kind in ("auto", "any", "tool", "none"):
            choice = dict(tool_choice)

    if parallel_tool_calls is False:
        choice = dict(choice or {"type": "auto"})
        choice["disable_parallel_tool_use"] = True

    return choice


# ── translation: what a reply reports ───────────────────────────────────


def _as_dict(payload: Any) -> Optional[Dict[str, Any]]:
    """A provider object as a plain dict, whether it is one or an SDK model."""
    if payload is None:
        return None
    if isinstance(payload, Mapping):
        return dict(payload)
    for name in ("model_dump", "to_dict", "dict"):
        method = getattr(payload, name, None)
        if not callable(method):
            continue
        try:
            got = method()
        except Exception:  # pragma: no cover - defensive
            continue
        if isinstance(got, Mapping):
            return dict(got)
    named = {name: getattr(payload, name, None)
             for name in ("input_tokens", "output_tokens",
                          "cache_creation_input_tokens",
                          "cache_read_input_tokens")}
    return named if any(v is not None for v in named.values()) else None


def usage_from(payload: Any) -> Optional[Usage]:
    """Anthropic's ``usage`` as this repo's :class:`Usage`, or ``None``.

    ``input_tokens``/``output_tokens`` are the same two counts OpenAI
    calls ``prompt_tokens``/``completion_tokens``; there is no
    ``total_tokens`` on the wire and :meth:`Usage.from_payload` derives it
    from the two the provider did give. Everything else the provider sent
    — ``cache_creation_input_tokens``, ``cache_read_input_tokens``, a
    service tier — rides in ``extra`` verbatim, because the field a
    platform meters on next is usually the one this repo did not name.

    ``None`` when the provider reported nothing, never three zeros: see
    :class:`core.runtime.backends.base.Usage`.
    """
    raw = _as_dict(payload)
    if raw is None:
        return None
    prompt = raw.get("input_tokens")
    completion = raw.get("output_tokens")
    if prompt is None and completion is None:
        return None
    record = {key: value for key, value in raw.items()
              if key not in ("input_tokens", "output_tokens")}
    record["prompt_tokens"] = prompt
    record["completion_tokens"] = completion
    return Usage.from_payload(record)


def tool_calls_from_blocks(blocks: Any) -> List[Dict[str, Any]]:
    """Every ``tool_use`` block, as the plain dicts the runtime reads.

    Routed through :func:`~core.runtime.backends.base.tool_calls_from`
    rather than built here, so that an Anthropic decision and an OpenAI
    one are the same dict and not two dialects of it. **All** of them, in
    the order they arrived — what a protocol then does with the second
    one is the protocol's decision, and it cannot make it about calls it
    was never shown.
    """
    shaped = [
        {
            "id": attr_or_key(block, "id"),
            "function": {
                "name": attr_or_key(block, "name"),
                "arguments": attr_or_key(block, "input"),
            },
        }
        for block in (blocks or [])
        if attr_or_key(block, "type") == "tool_use"
    ]
    return tool_calls_from(shaped)


def text_from_blocks(blocks: Any) -> str:
    """The ``text`` blocks of a reply, concatenated; nothing else."""
    return "".join(
        str(attr_or_key(block, "text") or "")
        for block in (blocks or [])
        if attr_or_key(block, "type") == "text"
    )


class AnthropicBackend(Backend):
    """Anthropic's Messages API, behind this repo's ``Backend`` contract.

    Parameters
    ----------
    client:
        Anything with ``messages.create`` in the SDK's shape — a real
        ``anthropic.Anthropic`` by default, a stub when injected. Mirrors
        ``OpenAIBackend(openai_client=…)`` and ``MistralBackend(client=…)``:
        constructing a backend must not open a socket, and a test must
        not need a key.
    model:
        The model :attr:`capabilities` answers for, and the one sent when
        :meth:`chat` is given none. The ``model`` argument to ``chat``
        still wins, and becomes this afterwards.
    max_tokens:
        The ceiling sent when a call names none. Defaults to
        :data:`DEFAULT_MAX_TOKENS`; the API has no "unset".
    """

    def __init__(
        self,
        client: Any = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ):
        if client is not None:
            self.client = client
        else:
            key = api_key or os.getenv("ANTHROPIC_API_KEY")
            if not key:
                raise RuntimeError("Missing ANTHROPIC_API_KEY")
            if _Anthropic is None:
                raise RuntimeError(
                    "The `anthropic` SDK is not installed. "
                    "Install it with: pip install 'judais-lobi[anthropic]'")
            self.client = _Anthropic(api_key=key)
        self._model = model or DEFAULT_ANTHROPIC_MODEL
        self._max_tokens = max_tokens or DEFAULT_MAX_TOKENS
        self.last_usage = None
        self.last_tool_calls = []

    @property
    def model(self) -> str:
        """The model this backend will send when the caller gives none."""
        return self._model

    def chat(
        self,
        model: str,
        messages: List[Dict],
        stream: bool = False,
        **extra: Any,
    ):
        """Create a message, returning content or a stream of deltas.

        The same two return types every backend here has — a ``str``, or
        an iterator of frames shaped like the OpenAI SDK's — because
        ``core.cli`` walks ``chunk.choices[0].delta.content`` and does not
        know which backend filled it.

        ``tools``, ``tool_choice`` and ``parallel_tool_calls`` are
        **translated** out of ``**extra`` (see the module docstring);
        everything else in it reaches ``messages.create`` verbatim, which
        is how ``temperature``, ``thinking``, ``stop_sequences`` and
        anything this repo has not heard of get through. Nothing is
        silently dropped: a parameter the Messages API does not have —
        ``response_format`` is the one the runtime might reach for —
        comes back as the provider's own 400 rather than as a constraint
        that quietly did not apply.

        Native tool calls come back on :attr:`last_tool_calls` and the
        counts on :attr:`last_usage`, never in the return value.
        """
        # Cleared FIRST: a call that raises must not leave the previous
        # call's numbers — or its decisions — standing, or a ledger counts
        # them twice and a runner dispatches a tool nobody asked for.
        self.last_usage = None
        self.last_tool_calls = []

        self._model = model or self._model
        system, translated = to_anthropic_messages(messages)

        body: Dict[str, Any] = {
            "model": self._model,
            "messages": translated,
            "max_tokens": self._max_tokens,
        }
        if system:
            body["system"] = system

        tools = to_anthropic_tools(extra.pop("tools", None))
        if tools:
            body["tools"] = tools
        choice = to_anthropic_tool_choice(
            extra.pop("tool_choice", None),
            extra.pop("parallel_tool_calls", None),
        )
        if choice:
            body["tool_choice"] = choice

        # Last, so that an explicit `max_tokens` — or `system` — from the
        # caller beats the one derived above.
        body.update(extra)

        if stream:
            return self._stream(body)
        return self._complete(body)

    def _complete(self, body: Dict[str, Any]) -> str:
        result = self.client.messages.create(**body)
        # Before anything is returned: a reply that produced no text still
        # spent the prompt, and a call nobody could use is exactly the one
        # worth finding in the ledger.
        self.last_usage = usage_from(attr_or_key(result, "usage"))
        blocks = attr_or_key(result, "content") or []
        self.last_tool_calls = tool_calls_from_blocks(blocks)
        return text_from_blocks(blocks)

    def _stream(self, body: Dict[str, Any]) -> Iterator[SimpleNamespace]:
        """Yield one delta per ``text_delta``, and keep what the rest said.

        A Messages stream is an event stream, not a stream of partial
        chat completions, so three of its event types are read and only
        one is passed on:

        * ``message_start`` carries the prompt's cost, and
          ``message_delta`` the completion's — merged rather than
          replaced, because ``input_tokens`` appears only on the first
          and the final ``output_tokens`` only on the last. Nothing has
          to be *asked for*: unlike an OpenAI-compatible stream, which
          reports no usage at all without ``stream_options``, this one
          always says what it cost.
        * ``content_block_start`` for a ``tool_use`` block opens a call;
          the ``input_json_delta`` frames that follow carry its arguments
          a few characters of JSON at a time. That is exactly the shape
          :class:`~core.runtime.backends.base.ToolCallAccumulator` folds,
          so it is folded by the same accumulator every other streaming
          backend here uses rather than by a second one that would
          disagree about the awkward frame.
        * ``text_delta`` is the only thing yielded, wrapped in the frame
          shape ``core.cli`` walks.

        Both side channels are published in a ``finally``, and the SDK's
        stream is closed there too: a consumer that walks away mid-answer
        is the case that has to work, and it must leave behind exactly
        what had fully arrived — a half-arrived tool call is a fragment of
        a JSON string, not a decision.
        """
        events = self.client.messages.create(stream=True, **body)
        seen: Dict[str, Any] = {}
        calls = ToolCallAccumulator()
        try:
            for event in events:
                kind = attr_or_key(event, "type")

                if kind == "message_start":
                    self._merge_usage(
                        seen, attr_or_key(attr_or_key(event, "message"), "usage"))
                    continue

                if kind == "message_delta":
                    self._merge_usage(seen, attr_or_key(event, "usage"))
                    continue

                if kind == "content_block_start":
                    block = attr_or_key(event, "content_block")
                    if attr_or_key(block, "type") == "tool_use":
                        calls.add([{
                            "index": attr_or_key(event, "index"),
                            "id": attr_or_key(block, "id"),
                            "function": {"name": attr_or_key(block, "name"),
                                         "arguments": ""},
                        }])
                    continue

                if kind == "content_block_delta":
                    delta = attr_or_key(event, "delta")
                    shape = attr_or_key(delta, "type")
                    if shape == "text_delta":
                        text = attr_or_key(delta, "text")
                        if text:
                            yield self._as_delta(text)
                    elif shape == "input_json_delta":
                        piece = attr_or_key(delta, "partial_json")
                        if piece:
                            calls.add([{
                                "index": attr_or_key(event, "index"),
                                "function": {"arguments": piece},
                            }])
        finally:
            close = getattr(events, "close", None)
            if callable(close):
                close()
            self.last_usage = usage_from(seen) if seen else None
            self.last_tool_calls = calls.result()

    @staticmethod
    def _merge_usage(into: Dict[str, Any], payload: Any) -> None:
        """Fold one event's ``usage`` in, keeping what it did not restate.

        Overlay and not replace: ``message_start`` reports the prompt and
        an ``output_tokens`` that is only the first few, and
        ``message_delta`` reports the final ``output_tokens`` and nothing
        about the prompt. Either alone is half a ledger entry.
        """
        raw = _as_dict(payload)
        if not raw:
            return
        into.update({key: value for key, value in raw.items()
                     if value is not None})

    @staticmethod
    def _as_delta(text: str) -> SimpleNamespace:
        """One text fragment in the frame shape ``core.cli`` walks.

        ``SimpleNamespace`` and not a dataclass on purpose: the consumer
        is ``getattr`` chains written against the OpenAI SDK's objects,
        and matching that shape is the whole job. The fields the other
        backends fill are filled — with ``None``, honestly, because an
        Anthropic frame carries no chat-completion id and no per-choice
        finish reason.
        """
        return SimpleNamespace(
            id=None, model=None,
            choices=[SimpleNamespace(
                index=0, finish_reason=None,
                delta=SimpleNamespace(role=None, content=text,
                                      tool_calls=None))],
        )

    @property
    def capabilities(self) -> BackendCapabilities:
        """What the Messages API does, and the one thing it does not.

        ``supports_json_mode`` is **False**, and that is a statement about
        a parameter rather than about the model: there is no
        ``response_format`` on this API. Anthropic constrains output
        through ``output_config.format`` and ``strict`` tool schemas,
        which are different requests with different semantics, and
        answering "yes" here would have the runtime send an OpenAI
        parameter that comes back a 400. A caller that wants structured
        output today asks for it with ``tools`` and
        ``tool_choice="required"``, which this backend does support.

        The tool-call flags are all **True** and all documented
        parameters: ``tools`` with ``input_schema``, ``tool_choice``
        ``{"type": "any"}`` for the constrained decode this repo spells
        ``"required"``, and more than one ``tool_use`` block per reply as
        the default rather than an opt-in.

        ``max_context_tokens`` comes from :data:`MODEL_LIMITS` for the
        model this backend is pointed at, and is ``None`` for a model the
        table has never heard of — never a guess, because a guessed
        context window is how a prompt gets truncated silently.
        """
        context, output = model_limits(self._model)
        return BackendCapabilities(
            supports_streaming=True,
            supports_json_mode=False,
            supports_tool_calls=True,
            supports_parallel_tool_calls=True,
            supports_tool_choice_required=True,
            max_context_tokens=context,
            max_output_tokens=output,
        )
