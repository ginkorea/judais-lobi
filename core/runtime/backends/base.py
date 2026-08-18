# core/runtime/backends/base.py — Backend ABC + capabilities dataclass

"""What every backend is, and what every backend reports.

Three things live here.  :class:`BackendCapabilities` is what a backend
can do, asked before a call.  :class:`Usage` is what one call **cost**,
read after it — the provider's own count of the tokens it billed, and
never this repo's guess at them.  :func:`tool_calls_from` and
:class:`ToolCallAccumulator` are what one call **decided**, read after it
off :attr:`Backend.last_tool_calls`: the native tool calls a provider
returned, as plain dicts.

Both post-call facts are side channels for the same reason.  ``chat``
returns a ``str`` or an iterator of deltas and every caller in this tree
branches on exactly those two shapes, so a third return shape would be a
breaking change to all of them for the sake of something most of them
ignore.  The tool calls stay **plain dicts** rather than a class of their
own so that the runtime never has to import a backend type to read a
decision — the seam between the two halves of this repo is data.

That distinction is the whole design of :class:`Usage`.  The only token
number in this tree before it was ``core.context.formatter.estimate_tokens``
— characters over four — which exists to keep a prompt inside a context
window and is honest about being an estimate.  A ledger a platform meters
on cannot be an estimate: it is either what the provider said or it is
absent.  So ``last_usage`` is ``None`` when nothing was reported, and a
zero is never manufactured to stand in for silence.  A zero is a claim.
"""

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple

from core.runtime.messages import (
    CALL_KEYS,
    merge_extra,
    opaque_extra,
    plain_mapping,
    tool_call_object,
)

#: The three counts an OpenAI-shaped ``usage`` object always names, and the
#: three this dataclass gives fields to.  Everything else the provider sent
#: — ``prompt_tokens_details`` with its cached-token breakdown, a queue
#: time, a provider's own cost field — travels in :attr:`Usage.extra`
#: rather than being dropped, because the thing a platform meters on next
#: is usually the thing this repo did not think to name.
NAMED_COUNTS = ("prompt_tokens", "completion_tokens", "total_tokens")


def _as_int(value: Any) -> Optional[int]:
    """An integer count, or ``None`` for anything that is not one.

    ``bool`` is excluded on purpose: ``True`` is an ``int`` in Python and a
    provider field that arrived as a flag must not be counted as one token.
    """
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_mapping(payload: Any) -> Optional[Dict[str, Any]]:
    """The provider's ``usage`` as a plain dict, whatever shape it arrived in.

    A JSON backend hands over a ``dict``; the OpenAI SDK hands over a
    pydantic model.  Both are read here rather than at three call sites,
    and an object that answers to none of these is read attribute by
    attribute for the three named counts before being given up on.
    """
    if payload is None:
        return None
    plain = plain_mapping(payload)
    if plain is not None:
        return plain
    named = {name: getattr(payload, name, None) for name in NAMED_COUNTS}
    return named if any(v is not None for v in named.values()) else None


@dataclass(frozen=True)
class Usage:
    """What the provider said one completion cost.

    Constructed only from a provider's own report — see
    :meth:`from_payload`, which returns ``None`` rather than a zeroed
    instance when there was nothing to read.  Frozen because it is a
    statement about a call that has already happened.
    """

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    #: Every other key the provider put in its ``usage`` object, verbatim.
    extra: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: Any) -> Optional["Usage"]:
        """Read a provider's ``usage``, or ``None`` when it reported none.

        ``None`` for an absent object and ``None`` for an object carrying
        no count at all: a ``{}`` where the counts should be is silence
        wearing the shape of a report, and treating it as three zeros
        would put a fabricated number on a stream a platform bills from.

        ``total_tokens`` is derived from the other two only when the
        provider omitted it — llama.cpp's server has been known to — and
        that is arithmetic on numbers the provider did give, not a guess.
        """
        raw = _as_mapping(payload)
        if raw is None:
            return None
        prompt = _as_int(raw.get("prompt_tokens"))
        completion = _as_int(raw.get("completion_tokens"))
        total = _as_int(raw.get("total_tokens"))
        if prompt is None and completion is None and total is None:
            return None
        prompt = prompt or 0
        completion = completion or 0
        if total is None:
            total = prompt + completion
        extra = {key: value for key, value in raw.items()
                 if key not in NAMED_COUNTS and value is not None}
        return cls(prompt_tokens=prompt, completion_tokens=completion,
                   total_tokens=total, extra=extra)

    def as_record(self) -> Dict[str, Any]:
        """The shape this rides the event stream in.

        The three counts by name, then the provider's extras flattened
        beside them — the same layout the provider used, so a consumer
        that already reads ``prompt_tokens_details`` off an OpenAI
        response reads it off this without a second mapping.
        """
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            **dict(self.extra),
        }


def attr_or_key(payload: Any, name: str) -> Any:
    """One field of a provider object, whether it is a dict or an SDK model.

    A JSON backend hands over nested ``dict``s; the OpenAI SDK hands over
    pydantic models.  Reading both here is the same bargain
    :func:`~core.runtime.messages.plain_mapping` strikes: one owner, rather
    than the same ``isinstance`` at three call sites that will drift.

    Public because the frames themselves are read outside this package
    too: :mod:`core.runtime.answer_stream` walks ``choices[0].delta`` off
    the very objects :class:`ToolCallAccumulator` folds in here, and a
    second copy of this four-line rule is a second copy of "what shape a
    provider speaks in".
    """
    if isinstance(payload, Mapping):
        return payload.get(name)
    return getattr(payload, name, None)


def _as_arguments(value: Any) -> Tuple[Dict[str, Any], Optional[str]]:
    """A tool call's arguments as an object, and what could not be read.

    Providers send arguments as a **JSON string**, which is the one place
    in a native reply a model can still be wrong: an unterminated brace, a
    trailing comma, a bare list where an object belongs.  A caller needs a
    dict to dispatch with, so an unreadable one becomes ``{}`` — but the
    text is returned alongside rather than dropped, because "the model
    asked for something and we could not parse it" is a different fact
    from "the model asked for nothing", and only the first is worth
    putting back in front of the model.

    ``None`` as the second element means nothing was lost: the arguments
    round-tripped, or there were none to begin with.  An empty string is
    the common no-argument call and loses nothing either.
    """
    if isinstance(value, Mapping):
        return dict(value), None
    if value is None:
        return {}, None
    text = value if isinstance(value, str) else str(value)
    if not text.strip():
        return {}, None
    try:
        parsed = json.loads(text)
    except ValueError:
        return {}, text
    if isinstance(parsed, Mapping):
        return dict(parsed), None
    # Valid JSON that is not an object — `[1, 2]`, `"hi"`, `7`.  There is
    # nothing to dispatch with and the text is the only evidence left.
    return {}, text


def tool_calls_from(payload: Any) -> List[Dict[str, Any]]:
    """Every native tool call in a provider's message, as plain dicts.

    ``[{"id": …, "name": …, "arguments": {…}}]`` in the order the
    provider returned them, and **all** of them.  A protocol that runs one
    tool per turn is free to use only the first — see
    :meth:`~core.runtime.backends.local_backend.LocalBackend._as_mission_json`
    — but that is the protocol's decision to make and it cannot make it
    about calls it was never shown.

    Anything the provider put on a call **beside** those three travels on
    an ``extra`` key, collected by
    :func:`~core.runtime.messages.opaque_extra` and given back verbatim by
    :func:`~core.runtime.messages.tool_call_object` when the assistant turn
    is rebuilt.  A provider may require a field it invented to come back
    with the call it belongs to — a signature over the reasoning behind it,
    most recently — and a normaliser that dropped what it did not
    understand made the round trip a 400 rather than a conversation.
    Never interpreted here, and **absent when there is nothing extra**, so
    a provider that sends none produces exactly the dict this function has
    always produced.

    A provider whose calls are not OpenAI-shaped says what *it* understands
    before it gets here, by spreading its own unknown keys onto the shaped
    call — see
    :func:`~core.runtime.backends.anthropic_backend.tool_calls_from_blocks`,
    where the name and the arguments live on the block rather than under a
    ``function``.
    """
    if not isinstance(payload, (list, tuple)):
        # No calls, or a field of a shape no provider sends.  Not an
        # error to raise in the middle of somebody's turn: a message
        # without a readable `tool_calls` list simply made no calls.
        return []
    calls: List[Dict[str, Any]] = []
    for raw in payload:
        if raw is None:
            continue
        function = attr_or_key(raw, "function")
        arguments, unread = _as_arguments(attr_or_key(function, "arguments"))
        call: Dict[str, Any] = {
            "id": str(attr_or_key(raw, "id") or ""),
            "name": str(attr_or_key(function, "name") or ""),
            "arguments": arguments,
        }
        if unread is not None:
            call["arguments_raw"] = unread
        extra = opaque_extra(raw, function, known=CALL_KEYS)
        if extra:
            call["extra"] = extra
        calls.append(call)
    return calls


class ToolCallAccumulator:
    """Streamed tool-call fragments, reassembled by index.

    A streamed native call does not arrive whole.  The first frame carries
    the id and the function name with the opening brace of the arguments;
    every frame after it carries a few more characters of that JSON
    string, keyed only by ``index``.  Concatenating by index is the whole
    algorithm, and it is written once here because every streaming
    backend in this tree needs it and two copies of it would disagree
    about the awkward frame.

    ``index`` is what the provider says, and a fragment without one falls
    back to its position in the frame.  Order out is first-appearance
    order, which for every provider seen so far is index order.

    Opaque provider fields are folded the same way and for the same
    reason.  Which frame carries one is the provider's business — the
    opening frame with the id, or the last one with the closing brace —
    so each frame's unknown keys are merged into the slot as they arrive
    and the reassembled call carries all of them.  ``index`` is not one of
    them: it is how a fragment says where it goes and is meaningless on a
    call that has arrived.
    """

    #: The keys a *fragment* carries that this repo understands.
    #: :data:`~core.runtime.messages.CALL_KEYS` plus the one that only a
    #: streamed frame has.
    FRAGMENT_KEYS = ("index",) + CALL_KEYS

    def __init__(self) -> None:
        self._by_index: Dict[Any, Dict[str, Any]] = {}

    def add(self, fragments: Any) -> None:
        """Fold one frame's ``delta.tool_calls`` in.  ``None`` is a no-op."""
        if not isinstance(fragments, (list, tuple)):
            return
        for position, fragment in enumerate(fragments):
            if fragment is None:
                continue
            index = attr_or_key(fragment, "index")
            if not isinstance(index, int) or isinstance(index, bool):
                index = f"position-{position}"
            slot = self._by_index.setdefault(
                index, {"id": "", "name": "", "arguments": "", "extra": {}})
            call_id = attr_or_key(fragment, "id")
            if call_id:
                slot["id"] = str(call_id)
            function = attr_or_key(fragment, "function")
            slot["extra"] = merge_extra(
                slot["extra"],
                opaque_extra(fragment, function, known=self.FRAGMENT_KEYS))
            name = attr_or_key(function, "name")
            if name:
                slot["name"] = str(name)
            arguments = attr_or_key(function, "arguments")
            if isinstance(arguments, str):
                slot["arguments"] += arguments
            elif arguments is not None:
                # A server that sends the object whole rather than in
                # pieces. Nothing to concatenate; take it as it stands.
                slot["arguments"] = arguments

    def result(self) -> List[Dict[str, Any]]:
        """The reassembled calls, in the shape :func:`tool_calls_from` makes.

        Through the same function, deliberately: a streamed call and a
        non-streamed one must not be two dialects of the same dict, and
        the unparseable-arguments rule has one owner.  The folded extras
        are put back on the wire shape first and read off it again, for
        the same reason — one owner of where an opaque field sits.
        """
        return tool_calls_from([
            tool_call_object(slot["id"], slot["name"], slot["arguments"],
                             slot["extra"])
            for slot in self._by_index.values()
        ])


@dataclass(frozen=True)
class BackendCapabilities:
    supports_streaming: bool = True
    supports_json_mode: bool = False
    supports_tool_calls: bool = False
    #: Whether the provider honours ``parallel_tool_calls`` — more than one
    #: native call in a single reply.  Separate from
    #: :attr:`supports_tool_calls` because a server can speak ``tools`` and
    #: still answer one call at a time, and a caller that must fan out
    #: needs to know which it is holding before it asks.
    supports_parallel_tool_calls: bool = False
    #: Whether the provider honours ``tool_choice="required"`` — the
    #: constrained decode that makes an unparseable or out-of-namespace
    #: tool name unrepresentable rather than merely unlikely.  Probed, not
    #: assumed; see each backend's ``capabilities``.
    supports_tool_choice_required: bool = False
    max_context_tokens: int | None = None
    max_output_tokens: int | None = None


class Backend(ABC):
    #: What the provider said the **last** completion through this backend
    #: cost, or ``None`` when it said nothing.  A side channel and not a
    #: return value, because ``chat`` returns a ``str`` or an iterator and
    #: every caller in this tree depends on exactly those two shapes.
    #:
    #: Cleared at the start of every call, so a call that raised — or a
    #: provider that stopped reporting — leaves ``None`` behind rather
    #: than the previous call's numbers, which would be counted twice by
    #: anything accumulating them.  On a streamed call it is filled when
    #: the iterator is exhausted or closed: usage arrives in the last
    #: frame, and there is nothing honest to say before it does.
    last_usage: Optional[Usage] = None

    #: The native tool calls the **last** completion carried, as plain
    #: dicts — ``{"id": str, "name": str, "arguments": dict}``, with
    #: ``arguments_raw`` added when the provider's argument text could not
    #: be read and ``extra`` added when the provider put fields on the call
    #: that this repo does not name.  Every call the provider returned, in
    #: its order, whatever the caller's protocol then chooses to do with
    #: them.
    #:
    #: The same lifecycle as :attr:`last_usage`, for the same reasons:
    #: rebound to ``[]`` at the start of every call so a raised call
    #: cannot leave the previous turn's decision standing to be dispatched
    #: twice, and filled on a streamed call only when the iterator is
    #: exhausted or closed, because a half-arrived tool call is a
    #: fragment of a JSON string and not yet a decision.
    #:
    #: Always **rebound**, never mutated in place — the class default is a
    #: shared list and an ``append`` on it would leak one backend's calls
    #: into every other.
    last_tool_calls: List[Dict[str, Any]] = []

    @property
    @abstractmethod
    def capabilities(self) -> BackendCapabilities: ...

    @abstractmethod
    def chat(self, model: str, messages: List[Dict], stream: bool = False):
        """Returns str (non-streaming) or iterator of SimpleNamespace (streaming)."""
        ...
