# core/runtime/reading.py — was the field read for what it is?

"""Ask whether a claim read its field correctly, not whether the number is there.

:mod:`core.runtime.grounding` asks *is this value in the evidence?*  That
question has a measured ceiling, and 10 August 2026 established exactly
where it is.

Two agents on the same 20B base model, in two different harnesses, on two
different runs, independently reported a **wall-clock duration as an
influence score**:

* Tai, run ``a971d4c4149c`` — ``total_s: 80.847`` became "the overall
  influence score … reached 80.847, indicating a relatively high magnitude
  of propagated influence";
* Goose, run ``202ec79ab74c`` — ``total_s: 80.889`` became "the influence
  score metric, named *Total_S* … summed to 80.89, placing this run among
  the highest-impact scores we have processed to date."

Both figures **are in the evidence**.  They are the honest contents of
``data.runs[0].total_s`` in what ``runs_list`` returned.  A membership
check reports both as ``SUPPORTED`` and is *right to*: the value was read
out of a real payload, at a real path, without a digit changed.  The
run's actual influence figure, ``blocks[*].total_causal_influence``, is
``0.0``.

So this is not hallucination and no stricter arithmetic reaches it.  The
error is **semantic**: the right number from the wrong field.  It is the
one class where a model is the better instrument, because deciding that
``total_s`` beside ``created_at`` and ``mode`` is elapsed seconds and not
a centrality blend is reading comprehension, and a regex has no purchase
on it at all.

**The unit is the claim, not the call.**  Most tool results say nothing
worth checking at the moment they arrive — there is no claim yet.  The
misreading appears when the agent *asserts*.  So a reading check fires
wherever a claim exists, as early as one exists, and that timing is the
substance rather than a detail: a misreading at turn 2 sits in the
context of turns 3 through 8 and is quoted onward by all of them.
Catching it in the final draft is worth much less than catching it at the
turn it was made, which is the same adjacency result the platform's own
refusals demonstrated — instructions fail at distance and bind up close.

**The prompt is small on purpose.**  Not the payload: the path, the
value, the names of the fields beside it, and the sentence.  On the order
of two hundred tokens in and a few out, which is what makes a check per
claim affordable on a local model.  :class:`FieldContext` is that extract
and :func:`field_context` builds it with the same
:func:`~core.runtime.results.walk_path` a claim table is verified with,
so what a claim *means* cannot disagree with what ``mission_result``
returns for the same path.

**The answer is a repair, not a verdict.**  ``false`` is unactionable.
"``total_s`` is the run's elapsed seconds; the influence figure is
``blocks[0].total_causal_influence`` = 0.0" is a repair turn's worth of
information, and a refusal that teaches was the most effective control
anyone measured that day.

What is *not* here is a model.  :class:`ReadingCheck` is handed an
``ask`` callable and has no opinion about what answers it, so the tier
can run on the mission's own backend, on a smaller one, or — in
:mod:`tests` — on a recorded fixture with no backend at all.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Iterable, List, Mapping, Optional, Sequence, Tuple

from core.runtime.results import walk_path

#: How many sibling field names travel with a claim.  Enough to establish
#: what kind of object this is — ``created_at``, ``mode``, ``question``
#: beside ``total_s`` is what makes it recognisably a run summary row —
#: and few enough that the prompt stays small.  Truncation is announced in
#: the prompt rather than silent, because a reader that thinks it has seen
#: the whole object will rule out a field that is merely off the end.
MAX_SIBLINGS = 24

#: How much of a sibling's own value is worth showing. Names alone are
#: often enough, but ``communities_confidence`` next to ``0.7446`` and
#: ``total_s`` next to ``80.847`` is what lets a reader say which of the
#: two a "confidence" sentence was about.
MAX_SIBLING_VALUE = 40


@dataclass(frozen=True)
class FieldContext:
    """One field, and just enough of its neighbourhood to judge it by.

    Deliberately not the payload.  A tool result on this platform runs to
    222,000 characters; the question "is ``total_s`` an influence score?"
    is answerable from a dozen field names, and the whole cost argument
    for a check per claim rests on not sending the rest.
    """

    path: str
    value: Any
    #: ``(name, rendered value)`` for the fields beside this one.
    siblings: Tuple[Tuple[str, str], ...] = ()
    #: Whether :attr:`siblings` was cut down from the object's real width.
    siblings_truncated: bool = False
    #: Why the path did not resolve, when it did not.  A context with a
    #: problem is not sent to a reader: the mechanical tier already
    #: rejected that claim and a second opinion on a path that does not
    #: exist is a wasted call.
    problem: str = ""

    @property
    def resolved(self) -> bool:
        return not self.problem

    @property
    def parent_path(self) -> str:
        """The path of the object this field sits in, or ``""``."""
        head, sep, _ = self.path.rpartition(".")
        return head if sep else ""

    def render(self) -> str:
        """The neighbourhood as the prompt shows it."""
        if not self.siblings:
            return "(no other fields beside it)"
        lines = [f"  {name}: {value}" for name, value in self.siblings]
        if self.siblings_truncated:
            lines.append("  … (more fields not shown)")
        return "\n".join(lines)


def _render_value(value: Any, limit: int = MAX_SIBLING_VALUE) -> str:
    """A value as one short line.  Containers become their shape.

    A sibling's *shape* carries most of the signal — ``nodes: [127 items]``
    beside ``node_count: 127`` is what tells a reader the count is a count
    — and pasting 127 node objects into a 200-token prompt would defeat
    the point of the prompt being small.
    """
    if isinstance(value, Mapping):
        return f"{{{len(value)} fields}}"
    if isinstance(value, (list, tuple)):
        return f"[{len(value)} items]"
    text = json.dumps(value, ensure_ascii=False, default=str)
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return text


def field_context(
    payloads: Sequence[Any], path: str, *, max_siblings: int = MAX_SIBLINGS,
) -> FieldContext:
    """Find *path* in the first payload that has it, with its neighbours.

    Several payloads because a mission reads several tools and a claim
    carries the path, not the handle — the same reason
    :meth:`~core.runtime.grounding.ClaimGroundingCheck.supported` searches
    them all.  The first payload the path resolves in wins; a path that
    resolves nowhere comes back with the last walker's problem, which
    names the fields that *were* there.
    """
    problem = f"no payload in this mission has a path {path!r}"
    for payload in payloads:
        value, trouble = walk_path(payload, path)
        if trouble:
            problem = trouble
            continue
        siblings, truncated = _siblings(payload, path, max_siblings)
        return FieldContext(
            path=path, value=value,
            siblings=siblings, siblings_truncated=truncated,
        )
    return FieldContext(path=path, value=None, problem=problem)


def _siblings(
    payload: Any, path: str, limit: int,
) -> Tuple[Tuple[Tuple[str, str], ...], bool]:
    """The other fields of the object *path* points into.

    The claimed field itself is left out — it is quoted above them in the
    prompt, and repeating it would spend the sibling budget on the one
    thing the reader already has.
    """
    head, sep, leaf = path.rpartition(".")
    if not sep:
        return (), False
    parent, trouble = walk_path(payload, head)
    if trouble or not isinstance(parent, Mapping):
        return (), False
    leaf = re.sub(r"\[\d+\]$", "", leaf).strip()
    names = [key for key in parent if str(key) != leaf]
    shown = names[:limit]
    return (
        tuple((str(key), _render_value(parent[key])) for key in shown),
        len(names) > len(shown),
    )


# ---------------------------------------------------------------------------
# The question
# ---------------------------------------------------------------------------

#: The whole prompt.  One string, like ``mission.PROTOCOL``, because a
#: contract split across f-strings is a contract that drifts from the
#: parser below it.
#:
#: The phrasing is doing work.  It does **not** ask "is this value in the
#: payload" — that question is already answered, mechanically, and asking
#: it again invites a reader to confirm the membership it can see and stop
#: there.  It asks what the field *is*, which is the part that was wrong
#: in both recorded cases.
READER_PROMPT = """\
A field was read out of a tool result and a sentence was written about it.
The value is definitely in the payload — that has already been checked. \
Your job is the other half: does the sentence describe the field for what \
it actually is?

  path:  {path}
  value: {value}

The object it sits in also holds:
{siblings}

The sentence that was written:
  "{sentence}"

Field names carry meaning. A duration is not a score, a count of edges is \
not a count of actors, and a confidence in one decision is not an accuracy \
of another. If the sentence calls this field something it is not, say so \
and name what it really is.

Judge the QUANTITY, not the wording. Answer false only if the sentence \
attributes the value to a different quantity, unit, subject or scope than \
this field holds. Loose, informal or paraphrased language for the RIGHT \
quantity is read correctly — an actor and a node, or a count and a total, \
may be the same thing said two ways, and a field name you cannot fully \
decode is not by itself a misreading. You are not reviewing the prose.

Reply with exactly one JSON object and no other text:
{{"read_correctly": true or false,
  "why": "<one sentence>",
  "correction": "<if it was misread: what this field actually is, and the \
path of the field the sentence should have used if one is visible above. \
Otherwise an empty string.>"}}
"""


def reader_question(context: FieldContext, sentence: str) -> str:
    """The prompt for one claim.  Small by construction; see the module doc."""
    return READER_PROMPT.format(
        path=context.path,
        value=json.dumps(context.value, ensure_ascii=False, default=str),
        siblings=context.render(),
        sentence=(sentence or "").strip().replace('"', "'"),
    )


# ---------------------------------------------------------------------------
# The answer
# ---------------------------------------------------------------------------

#: A reader that did not answer usably.  Not ``read_correctly=False``:
#: an unparseable reply is an absent opinion, and reporting it as a
#: misreading would make the tier's failures look like the agent's. Same
#: ``UNKNOWN``-not-``0.5`` rule the judge and the grounding checks follow.
UNREADABLE = "unreadable"

_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.MULTILINE)


@dataclass(frozen=True)
class ReadingVerdict:
    """What a reader said about one claim."""

    path: str
    sentence: str
    #: ``True`` read correctly, ``False`` misread, ``None`` no opinion.
    read_correctly: Optional[bool] = None
    why: str = ""
    correction: str = ""
    #: Why there is no opinion, when there is none.
    problem: str = ""

    @property
    def misread(self) -> bool:
        """Only an explicit ``false`` is a misreading.

        An absent opinion is not one.  A tier whose parse failures counted
        as findings would put its own flakiness into a governance report.
        """
        return self.read_correctly is False

    def as_repair_line(self) -> str:
        """One line a repair turn can quote.  See the module docstring."""
        parts = [f"{self.path} = misread"]
        if self.why:
            parts.append(self.why.strip().rstrip("."))
        if self.correction:
            parts.append(self.correction.strip().rstrip("."))
        return "; ".join(parts) + "."


def parse_reader_reply(reply: str, *, path: str = "", sentence: str = "") -> ReadingVerdict:
    """A reader's reply as a verdict, or an explicit lack of one."""
    text = _FENCE.sub("", str(reply or "").strip()).strip()
    if not text:
        return ReadingVerdict(path=path, sentence=sentence,
                              problem="the reader replied with nothing")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return ReadingVerdict(
            path=path, sentence=sentence,
            problem=f"the reader's reply is not JSON ({exc.msg})")
    if not isinstance(data, Mapping):
        return ReadingVerdict(
            path=path, sentence=sentence,
            problem=f"the reader replied with a {type(data).__name__}, not an object")

    verdict = data.get("read_correctly")
    if not isinstance(verdict, bool):
        return ReadingVerdict(
            path=path, sentence=sentence,
            why=str(data.get("why") or ""),
            problem=f"`read_correctly` is {verdict!r}; it is true or false")

    return ReadingVerdict(
        path=path, sentence=sentence,
        read_correctly=verdict,
        why=str(data.get("why") or ""),
        correction=str(data.get("correction") or ""),
    )


# ---------------------------------------------------------------------------
# The tier
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ReadingReport:
    """Every claim a reader looked at, and what it said."""

    verdicts: Tuple[ReadingVerdict, ...] = ()
    #: Claims not sent to a reader because the mechanical tier had already
    #: rejected them.  Named rather than dropped: "checked 2 of 5 claims"
    #: is a different report from "checked 5".
    skipped: Tuple[str, ...] = ()

    @property
    def ran(self) -> bool:
        return any(v.read_correctly is not None for v in self.verdicts)

    @property
    def misread(self) -> Tuple[ReadingVerdict, ...]:
        return tuple(v for v in self.verdicts if v.misread)

    @property
    def unanswered(self) -> Tuple[ReadingVerdict, ...]:
        return tuple(v for v in self.verdicts if v.read_correctly is None)

    @property
    def clean(self) -> bool:
        """No misreadings **and** somebody actually looked.

        The ``verified``-not-``grounded`` distinction, for the same reason:
        a tier where every call failed to parse has found no misreadings
        and has also checked nothing, and those must not report alike.
        """
        return self.ran and not self.misread


class ReadingCheck:
    """Ask a reader, per claim, whether the field was read for what it is.

    The third tier, and the order is the cost order: the mechanical
    path-and-value check is free and runs first, this is cheap and runs on
    what survives it, and the critic is expensive and triggered.  A claim
    the mechanical tier already rejected is **not** sent here — it is
    named in :attr:`ReadingReport.skipped` — because a second opinion on a
    path that does not resolve buys nothing and the whole affordability
    argument is that this tier only pays for claims that look fine.
    """

    def __init__(
        self,
        ask: Callable[[str], str],
        *,
        max_claims: int = 12,
        max_siblings: int = MAX_SIBLINGS,
    ):
        self._ask = ask
        self._max_claims = max(0, int(max_claims))
        self._max_siblings = max_siblings

    def review(
        self,
        claims: Iterable[Tuple[str, str]],
        payloads: Sequence[Any],
    ) -> ReadingReport:
        """*claims* is ``(path, sentence)`` pairs, in the order to check them."""
        verdicts: List[ReadingVerdict] = []
        skipped: List[str] = []
        for path, sentence in list(claims)[: self._max_claims]:
            context = field_context(payloads, path,
                                    max_siblings=self._max_siblings)
            if not context.resolved:
                skipped.append(path)
                continue
            question = reader_question(context, sentence)
            try:
                reply = self._ask(question)
            except Exception as exc:                # pragma: no cover - defensive
                verdicts.append(ReadingVerdict(
                    path=path, sentence=sentence,
                    problem=f"the reader could not be reached: {exc}"))
                continue
            verdicts.append(parse_reader_reply(
                reply, path=path, sentence=sentence))
        return ReadingReport(verdicts=tuple(verdicts), skipped=tuple(skipped))

    @staticmethod
    def repair_prompt(report: ReadingReport) -> str:
        """One turn naming every misread field and what it really is.

        Written like the platform's own refusals — the control that was
        measured teaching a 20B model a rule verbatim, at the turn it
        bound — rather than as a verdict the model has to interpret.
        """
        lines = [
            "One or more figures in that answer are real values read from the "
            "wrong field. The numbers are genuine; what they were called is "
            "not:",
        ]
        for verdict in report.misread:
            lines.append("  " + verdict.as_repair_line())
        lines.append(
            "Do not delete the sentence and move on — restate each figure as "
            "what the field actually is, or use the field named above and "
            "quote its value. If neither is what you meant, say the run does "
            "not report that quantity."
        )
        lines.append("Reply with one JSON object as before.")
        return "\n".join(lines)
