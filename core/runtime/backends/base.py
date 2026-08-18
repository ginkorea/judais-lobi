# core/runtime/backends/base.py — Backend ABC + capabilities dataclass

"""What every backend is, and what every backend reports.

Four things live here.  :class:`BackendCapabilities` is what a backend
can do, asked before a call.  :class:`Usage` is what one call **cost**,
read after it — the provider's own count of the tokens it billed, and
never this repo's guess at them.  :func:`tool_calls_from` and
:class:`ToolCallAccumulator` are what one call **decided**, read after it
off :attr:`Backend.last_tool_calls`: the native tool calls a provider
returned, as plain dicts.  :class:`SideChannels` and :func:`capturing`
are **whose** those two are — the slot one call files them in, so two
calls in flight at once cannot be read for each other.

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
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Mapping, Optional, Tuple

from core.runtime.backends import policy, state as model_state
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


@dataclass
class SideChannels:
    """One model call's ``last_usage`` and ``last_tool_calls``, captured
    where they were produced.

    A slot the *caller* makes before the call and reads after it — see
    :func:`capturing` — rather than a second place a backend keeps state.
    Written into by :class:`Backend`'s two setters below, so no backend in
    this tree grew a line for it and neither will a platform's own.

    ``filled`` is not decoration: a slot nobody wrote to means "the object
    that answered was not a :class:`Backend`" — a replayed run, a library
    caller's client, a test's lambda — and the caller must then fall back
    to reading the attribute, which is what it always did.  Distinguishing
    that from a backend that ran and reported nothing is the difference
    between "no report" and "no reporter".
    """

    usage: Optional[Usage] = None
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    filled: bool = False


#: The slot the call running *on this context* writes into, if any.
#:
#: The fix for a misattribution that had the same cause as the sandbox
#: race in :mod:`core.tools.executor`: a fact about ONE call kept in ONE
#: slot on an object several calls share.  ``last_usage`` is written by
#: the backend when a call finishes and read by ``Model.spend`` when the
#: caller is next scheduled, and between those two moments a sibling
#: call — two children of one ``Run``, gathered, sharing a client by
#: identity — can finish and overwrite it.  Measured, before the fix: a
#: child whose call the provider priced at 100 prompt tokens billed 1,
#: because its sibling's cheaper call landed in the slot first.
#:
#: A :class:`~contextvars.ContextVar` holding a **mutable slot the caller
#: made** rather than holding the value: a context is *copied* onto the
#: worker thread :func:`asyncio.to_thread` runs ``ask`` on, so a value
#: written there would never come back — but a slot written *into* is the
#: caller's own object.  The same shape :meth:`Model.watching` already
#: uses for ``model_state``, and for the same reason.
_capture: "ContextVar[Optional[SideChannels]]" = ContextVar(
    "judais_lobi_model_side_channels", default=None)


@contextmanager
def capturing() -> "Iterator[SideChannels]":
    """A slot for the next model call's side channels, scoped to this block.

    Opened by the ONE place a run touches a backend
    (:meth:`core.runtime.run.Run._model_reply`) and closed when the reply
    and its deltas are complete, so what comes out belongs to the call
    that produced it and to no other.
    """
    slot = SideChannels()
    token = _capture.set(slot)
    try:
        yield slot
    finally:
        _capture.reset(token)


class Backend(ABC):
    #: The word this backend is asked for by, and the word that reaches
    #: ``model_state.provider`` on the wire.  The same vocabulary
    #: :class:`core.unified_client.UnifiedClient` routes on — ``openai``,
    #: ``anthropic``, ``mistral``, ``local`` — because a consumer reading
    #: "which provider is this" off a record and an operator reading it
    #: off ``--provider`` must be reading the same word.
    #:
    #: Empty on a backend that never said, which is what an injected stub
    #: or a platform's own adapter is: a required field on the record, and
    #: the empty string is an honest answer where a guess would not be.
    provider_name: str = ""

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
    #:
    #: A **property** now, and every backend below still writes it
    #: with a plain ``self.last_usage = …``.  Reading it still answers "the
    #: last completion through this backend", which is what a library
    #: caller and ``core.cli``'s ``usage_fn`` have always asked it; writing
    #: it now *also* files the value with the call that produced it, when
    #: something opened a slot for it (:func:`capturing`).  One assignment,
    #: two readers, and the per-call reader cannot be clobbered by a
    #: sibling call because it is not a slot a sibling can reach.
    _last_usage: Optional[Usage] = None

    @property
    def last_usage(self) -> Optional[Usage]:
        return self._last_usage

    @last_usage.setter
    def last_usage(self, usage: Optional[Usage]) -> None:
        self._last_usage = usage
        slot = _capture.get()
        if slot is not None:
            slot.usage = usage
            slot.filled = True

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
    #:
    #: A property for the same reason :attr:`last_usage` is, and it matters
    #: more here: a misread cost is a wrong invoice, a misread *decision*
    #: is a sibling's tool call dispatched under this turn's name.
    _last_tool_calls: List[Dict[str, Any]] = []

    @property
    def last_tool_calls(self) -> List[Dict[str, Any]]:
        return self._last_tool_calls

    @last_tool_calls.setter
    def last_tool_calls(self, calls: List[Dict[str, Any]]) -> None:
        self._last_tool_calls = calls
        slot = _capture.get()
        if slot is not None:
            slot.tool_calls = list(calls or [])
            slot.filled = True

    @property
    @abstractmethod
    def capabilities(self) -> BackendCapabilities: ...

    @abstractmethod
    def chat(self, model: str, messages: List[Dict], stream: bool = False):
        """Returns str (non-streaming) or iterator of SimpleNamespace (streaming)."""
        ...

    # ── the third side channel: what the MODEL is doing ──────────────────

    def report_state(self, state: str, *, model: str = "", detail: str = "",
                     retry_after_s: Optional[float] = None) -> None:
        """Say what the thing on the other end of the socket is doing.

        The third side channel, beside :attr:`last_usage` and
        :attr:`last_tool_calls`, and the only one that is reported *while*
        a call is in flight rather than read after it — which is the whole
        point of it.  A cost is worth knowing afterwards; that the server
        is loading weights is worth knowing at second twelve of ninety.

        A **push** rather than an attribute for exactly that reason, and
        it pushes into :mod:`core.runtime.backends.state`, which drops
        every word when nobody installed a sink.  So a backend reports
        from each of the four or five places it actually learns something
        and never asks whether it is inside a mission: a chat session, a
        capability probe and a library caller with no observer all cost
        one context lookup each.

        *state* is one of :data:`core.runtime.backends.state.STATES` and
        anything else raises.  *model* is what this call is about — the
        name that was sent, or on ``loaded`` the id the server itself
        reported, which are not always the same string and where they
        differ the server's is the true one.
        """
        model_state.report(state, provider=self.provider_name, model=model,
                           detail=detail, retry_after_s=retry_after_s)

    def report_connect_error(self, exc: BaseException, *,
                             model: str = "") -> None:
        """Report a connect that never happened as ``absent``.

        The one translation from "this exception" to that word, so the
        backends that share
        :func:`core.runtime.backends.policy.retry_on_connect` cannot come
        to two views of what a refused socket means.  The word itself is
        :data:`~core.runtime.backends.policy.ERROR_POLICY`'s ``connect``
        row and is read off it rather than written here again.

        The exception's type is in the detail because the three that
        arrive here — refused, reset, unresolved — read very differently
        to whoever has to fix one, and the sentence is scrubbed by the
        observer like every other free-text field on the stream.
        """
        self.report_state(policy.ERROR_POLICY["connect"].state, model=model,
                          detail=f"{type(exc).__name__}: {exc}")

    def report_failure(self, exc: BaseException, *, model: str = "") -> None:
        """Report an SDK exception as whatever its status code means.

        For the two backends whose transport belongs to a vendor's SDK
        rather than to this repo.  They do not get to read a response
        object at the point of failure — they get an exception — so the
        status is taken off it (``status_code``, or the one on a
        ``response`` it carries) and put through
        :func:`~core.runtime.backends.policy.state_for_status`, which is
        the same table the raw-HTTP backends read.  A provider's 429 is
        therefore ``queued`` here exactly as it is there, and an
        exception carrying no status at all is ``failed``, which is the
        honest answer for "the SDK raised and did not say why".

        A connect failure that reaches an SDK caller as a vendor
        exception is not special-cased into ``absent``: this repo cannot
        tell one from a proxy's 502 without reading somebody else's
        exception hierarchy, and a wrong word is worse than a general
        one.  See :meth:`report_connect_error` for the case where this
        repo owns the socket and does know.
        """
        status = getattr(exc, "status_code", None)
        if status is None:
            status = getattr(getattr(exc, "response", None), "status_code", None)
        word = policy.state_for_status(status) if status is not None \
            else policy.ERROR_POLICY["5xx"].state
        self.report_state(
            word or policy.ERROR_POLICY["5xx"].state, model=model,
            detail=f"{type(exc).__name__}: {exc}",
            retry_after_s=model_state.retry_after_seconds(
                getattr(getattr(exc, "response", None), "headers", None)))
