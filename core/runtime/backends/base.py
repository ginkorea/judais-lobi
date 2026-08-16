# core/runtime/backends/base.py — Backend ABC + capabilities dataclass

"""What every backend is, and what every backend reports.

Two things live here.  :class:`BackendCapabilities` is what a backend can
do, asked before a call.  :class:`Usage` is what one call **cost**, read
after it — the provider's own count of the tokens it billed, and never
this repo's guess at them.

That distinction is the whole design of :class:`Usage`.  The only token
number in this tree before it was ``core.context.formatter.estimate_tokens``
— characters over four — which exists to keep a prompt inside a context
window and is honest about being an estimate.  A ledger a platform meters
on cannot be an estimate: it is either what the provider said or it is
absent.  So ``last_usage`` is ``None`` when nothing was reported, and a
zero is never manufactured to stand in for silence.  A zero is a claim.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional

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
    if isinstance(payload, Mapping):
        return dict(payload)
    for name in ("model_dump", "to_dict", "dict"):
        method = getattr(payload, name, None)
        if not callable(method):
            continue
        try:
            got = method()
        except Exception:               # pragma: no cover - defensive
            continue
        if isinstance(got, Mapping):
            return dict(got)
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


@dataclass(frozen=True)
class BackendCapabilities:
    supports_streaming: bool = True
    supports_json_mode: bool = False
    supports_tool_calls: bool = False
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

    @property
    @abstractmethod
    def capabilities(self) -> BackendCapabilities: ...

    @abstractmethod
    def chat(self, model: str, messages: List[Dict], stream: bool = False):
        """Returns str (non-streaming) or iterator of SimpleNamespace (streaming)."""
        ...
