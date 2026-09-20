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

One thing that is asked *before* a call rather than read after it has a
door of its own here: :meth:`Backend.constrained_response_format`, which
turns a caller's ``json_schema=`` into the request a backend that
declares :attr:`BackendCapabilities.supports_json_schema` sends, and
raises :class:`UndeclaredCapability` on one that does not.  Refusing
rather than dropping, for the reason ``--protocol native`` is refused at
the CLI's door: a caller that asked for a constrained decode and quietly
got prose would report the run as the thing it was not running.

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
from dataclasses import dataclass, field, replace
from urllib.parse import urlsplit
from typing import Any, Dict, Iterator, List, Mapping, Optional, Tuple

from core.runtime.backends import policy, state as model_state
from core.redact import scrub_secrets
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

#: The key :meth:`Usage.as_record` puts the harness's own account of how
#: a call ended under.
#:
#: It is **not** reserved against the provider: a provider that puts a
#: ``finish_reason`` inside its own ``usage`` object gets it carried
#: verbatim like every other extra, because dropping it would be this
#: repo deleting the very field it is here to surface.  The harness's
#: word simply wins where both exist — :meth:`Usage.as_record` writes it
#: last — which is the right way round: one is read off the choice this
#: call actually produced and the other is whatever the provider
#: volunteered beside its counts.
FINISH_REASON = "finish_reason"

#: Every ``finish_reason`` this repo reads as *the completion was cut short
#: by a token ceiling* — OpenAI-compatible servers say ``length``, the
#: Anthropic Messages API says ``max_tokens``, and some OpenAI-compatible
#: servers in the wild say ``model_length``.
#:
#: ``model_context_window_exceeded`` is the Anthropic Messages API's word
#: for the same thing arriving from the other side — the prompt plus the
#: completion outgrew the window rather than the completion outgrowing
#: ``max_tokens``.  It is declared and **unreachable today**: the
#: Anthropic backend does not yet hand its stop reason to
#: :meth:`Usage.from_payload`, so nothing produces it.  Declared anyway,
#: because the set is what this repo means by *cut short* and a word
#: left out of it is the one that will arrive unrecognised.
#:
#: Matched case-insensitively; the provider's own spelling is what
#: travels.  Only these reach the stream: ``stop``, ``tool_calls`` and an
#: absent reason are a model that finished saying what it had to say, and
#: putting those on the wire would be a field on every record to state
#: the ordinary case — the rule ``model_state`` follows, for the same
#: reason.
TRUNCATED_REASONS = ("length", "max_tokens", "model_length",
                     "model_context_window_exceeded")


def truncation_of(finish_reason: Any) -> str:
    """The provider's own word when a completion was cut short, else ``""``.

    One owner for a question the request-bounding code and every backend
    that grows a bound have to answer the same way.  The provider's
    spelling is kept rather than normalised into a flag of this repo's
    own: a platform reading ``max_tokens`` off one turn and ``length``
    off another is reading what its provider said, which is the only
    thing this harness is in a position to report.

    The *match* is case-insensitive and the *answer* is not: a server
    that shouts ``LENGTH`` has said the same thing as one that does not,
    and a vocabulary this repo compares against is a poor reason to miss
    a truncation — but what travels is still the string the provider
    sent, because that is the thing a platform's own logs will have.
    """
    word = str(finish_reason or "").strip()
    return word if word.lower() in TRUNCATED_REASONS else ""


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
    """What the provider said one completion cost, and how the call ended.

    Constructed only from a provider's own report — see
    :meth:`from_payload`, which returns ``None`` rather than a zeroed
    instance when there was nothing to read.  Frozen because it is a
    statement about a call that has already happened.

    :attr:`finish_reason` is the one field here that does not come out of
    the provider's ``usage`` object, and it earns its place beside the
    counts rather than somewhere of its own: *2,306 completion tokens* and
    *2,306 completion tokens and then the ceiling* are different facts
    about the same call, and a consumer reading one without the other has
    been told an answer was complete when it was cut in half.  It is
    carried only when it says the completion was **cut short** — see
    :func:`truncation_of`.
    """

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    #: Every other key the provider put in its ``usage`` object, verbatim.
    extra: Mapping[str, Any] = field(default_factory=dict)
    #: The provider's own ``finish_reason``, and **only** when it is one of
    #: :data:`TRUNCATED_REASONS`; ``""`` for a completion that ended on its
    #: own terms, which is nearly all of them.
    finish_reason: str = ""
    #: Internal provenance for telemetry; the historical usage wire remains
    #: unchanged. Direct construction declares the counts the caller supplied.
    count_sources: Mapping[str, str] = field(default_factory=dict, compare=False)

    @classmethod
    def from_payload(cls, payload: Any,
                     finish_reason: Any = None) -> Optional["Usage"]:
        """Read a provider's ``usage``, or ``None`` when it reported none.

        ``None`` for an absent object and ``None`` for an object carrying
        no count at all: a ``{}`` where the counts should be is silence
        wearing the shape of a report, and treating it as three zeros
        would put a fabricated number on a stream a platform bills from.

        ``total_tokens`` is derived from the other two only when the
        provider omitted it — llama.cpp's server has been known to — and
        that is arithmetic on numbers the provider did give, not a guess.

        *finish_reason* is the provider's word for how the completion
        ended, read off the choice rather than off the usage object and
        passed in by the backend that had both in hand.  It is kept only
        when it names a truncation.  A provider that reported no usage
        still reports no usage: there is nothing to hang the word on, and
        manufacturing three zeros to carry it would be the claim this
        class exists to refuse.

        A ``finish_reason`` the provider put inside its own ``usage``
        object travels in :attr:`extra`, verbatim, like every other key
        it sent — see :data:`FINISH_REASON` for why it is not filtered
        out — and :meth:`as_record` lets the harness's word win when
        there are two.
        """
        raw = _as_mapping(payload)
        if raw is None:
            return None
        prompt = _as_int(raw.get("prompt_tokens"))
        completion = _as_int(raw.get("completion_tokens"))
        total = _as_int(raw.get("total_tokens"))
        if prompt is None and completion is None and total is None:
            return None
        sources = {
            name: "reported" if value is not None else "missing"
            for name, value in zip(NAMED_COUNTS, (prompt, completion, total),
                                   strict=True)
        }
        if total is None and prompt is not None and completion is not None:
            sources["total_tokens"] = "derived"
        prompt = prompt or 0
        completion = completion or 0
        if total is None:
            total = prompt + completion
        extra = {key: value for key, value in raw.items()
                 if key not in NAMED_COUNTS and value is not None}
        return cls(prompt_tokens=prompt, completion_tokens=completion,
                   total_tokens=total, extra=extra,
                   finish_reason=truncation_of(finish_reason),
                   count_sources=sources)

    def as_record(self) -> Dict[str, Any]:
        """The shape this rides the event stream in.

        The three counts by name, then the provider's extras flattened
        beside them — the same layout the provider used, so a consumer
        that already reads ``prompt_tokens_details`` off an OpenAI
        response reads it off this without a second mapping.

        The harness's ``finish_reason`` joins them **only when the
        completion was cut short**, and is written LAST so it wins over a
        provider that volunteered one of its own inside ``usage``: this
        one was read off the choice the call actually produced.  Absent,
        never ``""``, when the harness has nothing to say — a key on every
        record to state the ordinary case is the field this stream keeps
        declining to add — so a provider's own, if it sent one, is what a
        consumer then sees, verbatim, like every other extra.
        """
        record = {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            **dict(self.extra),
        }
        if self.finish_reason:
            record[FINISH_REASON] = self.finish_reason
        return record


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
    #: Whether the provider takes a **JSON schema it enforces while
    #: decoding** — ``response_format={"type": "json_schema", …}`` on the
    #: OpenAI-compatible surface, which is what vLLM, SGLang and
    #: TensorRT-LLM put behind that parameter and what the hosted OpenAI
    #: API calls structured outputs.  Wider than
    #: :attr:`supports_json_mode`, which promises only that the reply will
    #: be *some* JSON: this one promises the reply will be JSON of the
    #: shape the caller handed over, so a parse failure and an
    #: out-of-vocabulary status word become unrepresentable rather than
    #: merely unlikely — ROADMAP §2.9.5's grammar compiler, as a
    #: capability.
    #:
    #: Asked at the door by :meth:`Backend.constrained_response_format`,
    #: which REFUSES a schema a backend has not declared rather than
    #: dropping it: a caller that asked for a constrained decode and
    #: silently got an unconstrained one would measure, and report, a
    #: thing it was not running.
    supports_json_schema: bool = False
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
    context_limit_source: str = "backend"


#: The three keys a ``json_schema=`` argument carries.  ``name`` is what
#: the provider files the grammar under and what comes back in its logs;
#: ``schema`` is a plain JSON Schema object; ``strict`` is whether the
#: server must hold the decode to it rather than treat it as a hint.
JSON_SCHEMA_KEYS = ("name", "schema", "strict")

#: ``strict`` when the caller did not say.  True because a schema that is
#: only a suggestion is not the capability this door is about — a caller
#: wanting the hint can pass ``strict`` False and say so.
DEFAULT_STRICT = True


class UndeclaredCapability(RuntimeError):
    """A backend was asked for something its capabilities do not declare.

    Raised rather than downgraded.  The rule is the one
    :mod:`core.cli` states at its own door for ``--protocol native``: a
    run that asked for a constrained decoder and silently got an
    unconstrained one is MEASURED as the protocol it was not running,
    which is the single outcome an experiment must not produce.  So the
    ask fails, by name, before anything is sent.
    """


def json_schema_request(json_schema: Any) -> Dict[str, Any]:
    """A caller's ``json_schema=`` as the ``json_schema`` body of a request.

    The envelope is ``{"name": str, "schema": {...}}`` with an optional
    ``strict``, and an **envelope rather than a bare schema** on purpose:
    the OpenAI-compatible surface files a grammar under a name, that name
    is what appears in a server's own logs beside the request, and a name
    invented here would be a different one on every deployment.  Nothing
    is guessed — an argument that is not that shape is refused with what
    it is missing, because a schema that reached the wire malformed comes
    back as somebody else's 400 an hour later.

    Keys outside the three are refused rather than forwarded, and the
    reason is **not** that no provider reads them — OpenAI's own
    ``json_schema`` object takes a ``description`` as well.  It is that
    this envelope is what EVERY backend declaring the capability has to
    be able to send: a key passed through here is a promise about all of
    them, so the set widens deliberately, in a commit that says which
    backends honour the new key, and never by whatever a caller happened
    to spell.  The narrowing also catches the misspelling — the reason a
    probe's ``expect`` block refuses unknown keys in
    :mod:`core.eval.extraction` — since a constraint that silently does
    not apply is the failure mode both are guarding.
    """
    if not isinstance(json_schema, Mapping):
        raise ValueError(
            f"json_schema= takes a mapping "
            f"{{{', '.join(JSON_SCHEMA_KEYS)}}}, not a "
            f"{type(json_schema).__name__}")
    unknown = sorted(set(json_schema) - set(JSON_SCHEMA_KEYS))
    if unknown:
        raise ValueError(
            f"json_schema= carries {unknown}, which this door does not "
            f"pass on; it takes {list(JSON_SCHEMA_KEYS)}. The envelope is "
            f"narrowed on purpose — a provider may accept more (OpenAI's "
            f"`description`, for one) and every key added here has to be "
            f"true of every backend that declares the capability, so it "
            f"is widened deliberately rather than by whatever a caller "
            f"happened to pass")
    name = json_schema.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError(
            "json_schema= needs a `name`: it is what the server files the "
            "grammar under and what its own logs say beside the request")
    schema = json_schema.get("schema")
    if not isinstance(schema, Mapping) or not schema:
        raise ValueError(
            "json_schema= needs a non-empty `schema`: an empty one "
            "constrains nothing and would be reported as a constrained run")
    strict = json_schema.get("strict", DEFAULT_STRICT)
    return {"name": name.strip(), "schema": dict(schema),
            "strict": bool(strict)}


_STOP_CODES = {
    "stop": "completed", "end_turn": "completed", "stop_sequence": "completed",
    "tool_calls": "tool_call", "function_call": "tool_call", "tool_use": "tool_call",
    "length": "output_limit", "max_tokens": "output_limit",
    "model_length": "token_limit", "model_context_window_exceeded": "context_limit",
    "content_filter": "provider_refusal", "refusal": "provider_refusal",
    "pause_turn": "provider_pause",
}


def _safe_identity(value: Any) -> Optional[str]:
    """Metadata only; do not publish a changed or credential-shaped identity."""
    if not isinstance(value, str) or not value or len(value) > 256:
        return None
    if any(ord(char) < 32 for char in value) or scrub_secrets(value) != value:
        return None
    return value


def endpoint_origin(value: Any) -> Optional[str]:
    """Origin only: never userinfo, a consumer/bearer path, query or fragment."""
    if not isinstance(value, str):
        return None
    try:
        parts = urlsplit(value)
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            return None
        host = parts.hostname
        authority = f"[{host}]" if ":" in host else host
        if parts.port is not None:
            authority += f":{parts.port}"
        return _safe_identity(f"{parts.scheme}://{authority}")
    except ValueError:
        return None


@dataclass(frozen=True)
class CallMetadata:
    """Non-payload facts about a logical call, independent of token usage."""

    provider: Optional[str] = None
    model: Optional[str] = None
    endpoint: Optional[str] = None
    raw_stop_reason: Optional[str] = None
    stop_reason: str = "unavailable"
    stop_source: str = "unavailable"
    physical_attempts: Optional[int] = None

    @classmethod
    def for_request(cls, provider: str, model: Any, endpoint: Any = None) -> "CallMetadata":
        model_name = _safe_identity(model)
        if model_name and ("://" in model_name or model_name.startswith("/")):
            model_name = None
        return cls(provider=_safe_identity(provider), model=model_name,
                   endpoint=endpoint_origin(endpoint))

    def stopped(self, value: Any) -> "CallMetadata":
        # Provider codes are a closed machine vocabulary, not exception text.
        # An unknown value may itself contain a secret and is not copied.
        if isinstance(value, str) and value.lower() in _STOP_CODES:
            return replace(self, raw_stop_reason=value,
                           stop_reason=_STOP_CODES[value.lower()], stop_source="provider")
        return replace(self, raw_stop_reason=None, stop_reason="unavailable",
                       stop_source="unrecognized" if value else "unavailable")

    def as_record(self) -> Dict[str, Any]:
        return {
            "provider": self.provider, "model": self.model,
            "model_source": "requested" if self.model is not None else "unavailable",
            "endpoint_origin": self.endpoint,
            "raw_stop_reason": self.raw_stop_reason, "stop_reason": self.stop_reason,
            "stop_reason_source": self.stop_source,
            "physical_attempts": self.physical_attempts,
            "physical_attempt_coverage": ("backend_transport" if self.physical_attempts is not None
                                          else "unavailable"),
            "physical_attempt_usage": "unavailable",
        }

    @staticmethod
    def failure_reason(error: Optional[BaseException]) -> str:
        """Classify known timeout types, never inspect an exception message."""
        if isinstance(error, (policy.requests.exceptions.Timeout, policy.httpx.TimeoutException)):
            return "transport_timeout"
        if isinstance(error, TimeoutError):
            return "request_timeout"
        return "request_failed"


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
    metadata: Optional[CallMetadata] = None


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
def capturing(slot: Optional[SideChannels] = None) -> "Iterator[SideChannels]":
    """A slot for the next model call's side channels, scoped to this block.

    Opened by the ONE place a run touches a backend
    (:meth:`core.runtime.run.Run._model_reply`) and closed when the reply
    and its deltas are complete, so what comes out belongs to the call
    that produced it and to no other.
    """
    slot = slot if slot is not None else SideChannels()
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
    _last_call_metadata: Optional[CallMetadata] = None

    @property
    def last_call_metadata(self) -> Optional[CallMetadata]:
        slot = _capture.get()
        return slot.metadata if slot is not None else self._last_call_metadata

    def _metadata(self, value: CallMetadata) -> None:
        self._last_call_metadata = value
        slot = _capture.get()
        if slot is not None:
            slot.metadata = value

    def start_call_metadata(self, model: Any, endpoint: Any = None) -> None:
        self._metadata(CallMetadata.for_request(self.provider_name, model, endpoint))

    def report_stop(self, value: Any) -> None:
        self._metadata((self.last_call_metadata or CallMetadata()).stopped(value))

    def note_transport_attempt(self) -> None:
        current = self.last_call_metadata or CallMetadata()
        self._metadata(replace(current, physical_attempts=(current.physical_attempts or 0) + 1))

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

    # ── the door a constrained decode is asked through ───────────────────

    def constrained_response_format(
            self, json_schema: Any) -> Optional[Dict[str, Any]]:
        """The ``response_format`` for *json_schema*, or ``None`` for none.

        **The door, written once.**  Every backend below takes a
        ``json_schema=`` argument and starts by calling this, so the
        refusal sentence, the envelope's shape and the answer to "may this
        backend be asked at all" have one owner rather than four that will
        drift.  ``None`` in means ``None`` out and the request this
        backend has always sent is still the request it sends.

        The shape returned is the **OpenAI-compatible** one —
        ``{"type": "json_schema", "json_schema": {"name", "schema",
        "strict"}}`` — which is what every backend in this tree that
        declares :attr:`BackendCapabilities.supports_json_schema` speaks,
        hosted and local alike.  A provider that expressed the same
        capability differently would override this method; the two here
        that would have to (Anthropic's ``output_config``, and Mistral's
        own vocabulary) are exactly the two that declare ``False``, and a
        declaration is the honest place for that difference to live.

        Where it goes afterwards is the backend's, because it differs:
        a keyword argument to the SDK's ``create`` on one, a key in the
        JSON body on the other.  Same dict, two placements.
        """
        if json_schema is None:
            return None
        if not self.capabilities.supports_json_schema:
            raise UndeclaredCapability(
                f"json_schema=: this backend ({self.provider_name or '?'}) "
                f"does not declare supports_json_schema, so a schema sent "
                f"to it would not constrain the decode. Drop the schema, or "
                f"ask a backend that declares it — a run that fell back to "
                f"unconstrained decoding would be reported as the "
                f"constrained run it was not.")
        return {"type": "json_schema",
                "json_schema": json_schema_request(json_schema)}

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
