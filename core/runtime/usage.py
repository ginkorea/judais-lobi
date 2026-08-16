# core/runtime/usage.py — one run's token spend, and what it cost

"""The ledger a run accumulates, and the optional price list beside it.

:class:`~core.runtime.backends.base.Usage` is one call.  This module is
the *run*: a :class:`Ledger` that every model call in a mission is folded
into — the direct loop's steps, and on ``--swarm`` the router, the
planner, the gates, the synthesizer and every sub-mission's own steps as
well — so that ``mission_finished`` can say what the turn spent.

**One owner for the arithmetic.**  Everything that adds to a ledger goes
through :meth:`Ledger.add` or :meth:`Ledger.absorb`, and both go through
one private fold.  The swarm hand-listing six grounding fields where the
direct path emitted ten is the recorded cost of a second emitter; a
second *accumulator* would be the same defect with numbers, and numbers
are the half nobody notices is wrong.

**Cost is configuration, never a constant.**  There is no price table in
this repository and there must not be one: prices move, they differ per
account, and a framework that shipped a number would be quoting a figure
it cannot know.  A deployment that wants cost puts a ``pricing:`` block
in ``.judais-lobi.yml``; a deployment that does not gets tokens and no
``cost`` key at all.  An absent cost is honest — a wrong one is worse
than none, because somebody bills from it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional

from core.runtime.backends.base import Usage

__all__ = ["Ledger", "Rate", "PricingTable"]


@dataclass
class Ledger:
    """What a run has spent so far, as the providers reported it.

    ``calls`` counts the model calls that **reported** usage, not the
    calls that were made.  The difference matters: a run against a
    provider that reports nothing has a ledger of zero calls, and zero
    calls is what keeps ``usage`` off the wire entirely rather than
    putting three zeros there.  A zero is a claim; silence is not.
    """

    prompt: int = 0
    completion: int = 0
    total: int = 0
    calls: int = 0
    #: Each reported call's own record, oldest first, bounded by
    #: :data:`MAX_PER_CALL`.  Kept so a caller can see the shape of a run
    #: — one enormous prompt, or forty small ones — without re-reading
    #: the stream.  Bounded because a long mission is hundreds of calls
    #: and this list is held for the whole of it; the totals above are
    #: never bounded and remain exact past the cut.
    per_call: List[Dict[str, Any]] = field(default_factory=list)

    #: How many per-call records to keep. The totals do not stop at it.
    MAX_PER_CALL = 256

    # ── the only two ways in ─────────────────────────────────────────────

    def add(self, usage: Optional[Usage]) -> Optional[Usage]:
        """Fold one model call in and hand back what was folded.

        ``None`` in, ``None`` out and nothing counted — a provider that
        said nothing must not move a counter.  The return value is what
        lets a caller emit the same numbers it just accumulated without
        reading them back out, which is how the per-call field on
        ``tool_call`` and the totals on ``mission_finished`` stay two
        views of one fact.

        **Only a :class:`~core.runtime.backends.base.Usage` counts.**  The
        source is a caller-supplied callable reading a caller-supplied
        client, so anything at all can arrive here — a stub's default
        attribute, a mock, a dict somebody thought was close enough — and
        Python will cheerfully add most of it to an integer.  The numbers
        this produces reach a stream a platform bills from, so a shape
        that is not a report is treated as no report rather than as a
        number nobody can trace.
        """
        if not isinstance(usage, Usage):
            return None
        self._fold(usage.prompt_tokens, usage.completion_tokens,
                   usage.total_tokens, 1)
        if len(self.per_call) < self.MAX_PER_CALL:
            self.per_call.append(usage.as_record())
        return usage

    def absorb(self, other: "Ledger") -> None:
        """Fold a whole other ledger in — a sub-mission's, typically.

        Through the same fold as :meth:`add`, so a staged mission's total
        cannot drift from the sum of the calls it is made of.
        """
        if other is self or not other.calls:
            return
        self._fold(other.prompt, other.completion, other.total, other.calls)
        room = self.MAX_PER_CALL - len(self.per_call)
        if room > 0:
            self.per_call.extend(other.per_call[:room])

    def _fold(self, prompt: int, completion: int, total: int, calls: int) -> None:
        """The arithmetic, in one place and nowhere else."""
        self.prompt += prompt
        self.completion += completion
        self.total += total
        self.calls += calls

    # ── what a watcher is told ───────────────────────────────────────────

    @property
    def reported(self) -> bool:
        """Whether any provider reported anything at all this run."""
        return self.calls > 0

    def as_record(self, rate: Optional["Rate"] = None) -> Optional[Dict[str, Any]]:
        """The ``usage`` field for ``mission_finished``, or ``None``.

        ``None`` when nothing was reported, and the emitter then omits the
        field rather than sending zeros — the distinction the whole module
        is built around.

        ``cost`` appears only when a rate was configured for the provider
        and model that ran.  A local endpoint has no cost unless somebody
        priced it, which is the truth: the electricity is real and this
        harness has no idea what it costs.
        """
        if not self.calls:
            return None
        record: Dict[str, Any] = {
            "prompt_tokens": self.prompt,
            "completion_tokens": self.completion,
            "total_tokens": self.total,
            "calls": self.calls,
        }
        cost = rate.cost_of(self) if rate is not None else None
        if cost is not None:
            record["cost"] = cost
        return record

    def console_line(self, rate: Optional["Rate"] = None) -> str:
        """The one line stdout gets.  Empty when there is nothing to say."""
        if not self.calls:
            return ""
        line = (f"🧮 usage: {self.prompt} prompt + {self.completion} "
                f"completion tokens over {self.calls} "
                f"call{'' if self.calls == 1 else 's'}")
        cost = rate.cost_of(self) if rate is not None else None
        if cost is not None:
            line += f" — {cost['amount']} {cost['currency']}"
        return line


@dataclass(frozen=True)
class Rate:
    """What one (provider, model) charges per thousand tokens.

    Read from a deployment's own configuration and never from anything
    this repository knows.  ``currency`` is carried rather than assumed
    because a number without one is a number somebody will read in the
    wrong money.
    """

    prompt_per_1k: float = 0.0
    completion_per_1k: float = 0.0
    currency: str = "USD"

    #: Decimal places the amount is rounded to. Six, not two: a single
    #: cheap call is fractions of a cent, and rounding it to cents at the
    #: point of measurement would make every small run cost nothing.
    PLACES = 6

    @classmethod
    def from_mapping(cls, raw: Any) -> Optional["Rate"]:
        """One entry of the ``pricing:`` block, or ``None`` if unusable.

        A malformed entry is dropped rather than defaulted to zero: a
        zero rate reports a run as free, and "free" is a claim nobody
        made.
        """
        if not isinstance(raw, Mapping):
            return None
        prompt = _as_float(raw.get("prompt_per_1k"))
        completion = _as_float(raw.get("completion_per_1k"))
        if prompt is None and completion is None:
            return None
        currency = str(raw.get("currency") or "USD").strip() or "USD"
        return cls(prompt_per_1k=prompt or 0.0,
                   completion_per_1k=completion or 0.0,
                   currency=currency)

    def cost_of(self, ledger: Ledger) -> Optional[Dict[str, Any]]:
        """``{amount, currency}`` for a ledger, or ``None`` for an empty one."""
        if not ledger.calls:
            return None
        amount = (ledger.prompt / 1000.0) * self.prompt_per_1k
        amount += (ledger.completion / 1000.0) * self.completion_per_1k
        return {"amount": round(amount, self.PLACES), "currency": self.currency}


class PricingTable:
    """The ``pricing:`` block of ``.judais-lobi.yml``, if there is one.

    ``{provider: {model: {prompt_per_1k, completion_per_1k, currency}}}``.
    An empty table is the normal case and costs nothing to carry: every
    lookup returns ``None`` and no ``cost`` key is ever written.
    """

    def __init__(self, rates: Optional[Mapping[str, Mapping[str, Rate]]] = None):
        self._rates: Dict[str, Dict[str, Rate]] = {
            str(provider).strip().lower(): dict(models)
            for provider, models in (rates or {}).items()
        }

    @classmethod
    def from_project(cls, project_root=None) -> "PricingTable":
        """Read the block, tolerating every way it can be wrong.

        A pricing table is optional decoration on an agent framework.  A
        typo in it must cost a mission nothing — the run goes ahead
        without a cost figure, which is the state every run was in
        before the block existed.
        """
        from core.tools.config_loader import load_pricing

        rates: Dict[str, Dict[str, Rate]] = {}
        for provider, models in (load_pricing(project_root) or {}).items():
            if not isinstance(models, Mapping):
                continue
            for model, raw in models.items():
                rate = Rate.from_mapping(raw)
                if rate is None:
                    continue
                rates.setdefault(str(provider).strip().lower(), {})[
                    str(model).strip()] = rate
        return cls(rates)

    def rate_for(self, provider: str, model: str) -> Optional[Rate]:
        """The rate for exactly this provider and model, or ``None``.

        Exact on the model name, with one fallback: a ``*`` entry under
        the provider, for a deployment serving one priced endpoint under
        whatever name the server happens to advertise this week.  No
        prefix matching and no guessing beyond that — a rate found by
        approximate match is a bill computed from a coincidence.
        """
        models = self._rates.get(str(provider or "").strip().lower())
        if not models:
            return None
        return models.get(str(model or "").strip()) or models.get("*")

    def __bool__(self) -> bool:
        return bool(self._rates)


def _as_float(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
