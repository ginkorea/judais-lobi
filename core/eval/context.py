# core/eval/context.py — what a mission's context costs, and what is in it

"""``python -m core.eval context`` — the owner's bloat criterion, measured.

The commissioning sentence, verbatim: *"one thing we need to ensure. is that
all of this we add, does not make the context bloated and the agent less
capable"*.  Everything ROADMAP §2.9 has added since Phase 17 — the compiled
view, the frontier's OWED lines, the rule packs that make them — is
**characters in front of a model**, and until this module the only way to
answer the first half of that sentence was to guess.  ``ablation`` already
answers the second half: it says whether an arm moved the pass rate.  This
module puts the price beside it, so *"this arm gained four missions and cost
2.1 KB a step"* is one line rather than two beliefs.

**It is pure and offline.**  Nothing here spawns anything, asks a model
anything or adds a byte to a runtime path.  Its raw material is what the
recorder already writes: ``model.jsonl``, one line per model call, carrying
the **full request** — see :class:`core.runtime.replay.Recorder`.  So a
profile can be computed for a run that happened last month, on somebody
else's machine, with no GPU and no endpoint.  That is the same no-model rule
``score``, ``corpus`` and ``registry`` keep, and for the same reason.

What one call is measured as
----------------------------

A recorded request is rendered into **one string, in the order a chat
template renders it** — the tool declarations first, then every message's
content in wire order — and the parts are measured as spans of that string.
Three things are then attributed and they do not overlap:

``pinned``
    The **longest common prefix** of the requests of this run's calls,
    computed and never assumed.  That is the region a provider's prefix
    cache can key on: the leading text that did not change.  A run is
    grouped into conversations by the recorded ``kind`` first (a swarm's
    router and its children are not one conversation and averaging them
    into a single prefix would be a number about nothing), and each
    conversation's prefix is its own.
``block``
    The compiled view, identified by **two** things and not one: a part
    whose text begins with :data:`core.cognition.compile.TITLE` *and*
    which sits under :data:`BLOCK_ROLE`, the role the runtime injects it
    under.  A title is a string, and a tool result that echoes the block
    back begins with the same words.  Which of the view's sections rode
    along is read off :data:`~core.cognition.compile.HEADINGS`, so a
    section a later phase adds is counted here with no edit.
``rest``
    Everything else: the transcript, the tool results, the steering.

**The attribution adds up, by construction and by check.**  ``pinned +
block-outside-the-prefix + rest == chars``, every call, because the three
are computed from one interval algebra over the same spans rather than from
three tallies that agree by convention.  A block whose text did not change
between two steps would be *inside* the pinned prefix, and it is charged to
the prefix and not a second time to itself — a reader shown a 900-character
view twice would conclude it cost twice what it did.
:attr:`CallCost.block_chars` keeps the raw figure beside it, so nothing is
lost.

**That overlap is not reachable in a recording made today**, and the
algebra is kept anyway.  :meth:`core.runtime.run.Run._compile_context` appends the
view LAST, after the whole transcript, so the common prefix always stops
before it and ``block_unpinned_chars == block_chars`` in every run this
release can produce.  The union is what makes the three regions provably
disjoint rather than disjoint by argument, and the day a lane pins the view
into the head — a cached preamble, a view that leads the request — a tally
of three independent sums would silently report a request larger than the
request.  The invariant costs one interval merge and holds either way.

Characters, and tokens when the recording has them
--------------------------------------------------

**Characters, and never bytes.**  Everything counted here is Python
characters; a request in a non-Latin script is up to three times its
character count in UTF-8, so the two are not interchangeable and every
figure is labelled ``chars`` for that reason.  It is the right unit for
this instrument — what a lane adds to a prompt is text — and it is not the
unit a wire is billed in.  Tokens are what a window is actually spent in,
and the only honest source for them is the
provider's own ``usage`` — :class:`core.runtime.backends.base.Usage`'s
``prompt_tokens``, which the recorder copies into every line whose provider
reported one.  So: tokens where the recording carries them, characters
always, and a report over a recording with no usage **says** it is
characters only rather than dividing by four and calling the result a
measurement.

What the profile is read for
----------------------------

* the **growth curve** — chars per call, in call order, with the mean, the
  peak and the per-step slope.  A runtime that is quietly quadratic shows
  here before it shows in a timeout;
* the **block's share** — what fraction of a request the compiled view is,
  per step;
* **prefix stability** — whether the system-side head was *identical*
  across a conversation's calls, and the first call where it was not.
  Identity, so this one really is byte-for-byte.  It is a regression
  detector and it is the one an inserted timestamp, a shuffled tool
  catalogue or a per-step rewrite of the system prompt trips: the caching
  claim in ROADMAP §2.6 is exactly the claim that this stays YES.  A
  conversation of one call answers **neither** yes nor no, and says so.

A run directory with no ``model.jsonl`` is **refused by name** rather than
scored as zero: nothing was recorded, which is a different fact from a
mission that was cheap.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import (Any, Dict, Iterable, List, Mapping, Optional, Sequence,
                    Tuple)

from core.cognition.compile import HEADINGS, SECTIONS, TITLE
from core.durable import atomic_write_text
from core.eval.measure import _table, report_paths
from core.runtime.replay import MODEL_LOG, canonical

__all__ = [
    "BLOCK_ROLE", "CRITERION", "SEPARATOR", "NO_MODEL_LOG", "NO_CALLS",
    "Part", "CallCost",
    "Conversation", "RunCost", "ContextSummary", "ContextProfile",
    "render_request", "parts_of", "common_prefix", "head_of", "is_block",
    "sections_in", "cost_of_run", "profile", "run_shaped", "summarise",
    "summarise_runs", "add_parser", "from_args",
]

#: What :func:`render_request` puts between two parts of one request.
#:
#: One character, and the same one every provider's template puts there, so
#: the rendered length is the payload's length plus a constant per part
#: rather than a number this module invented.  It is not the wire encoding:
#: role names, JSON punctuation and a provider's own framing are per-message
#: overhead a context budget is not spent on and cannot be attributed to
#: anything a lane added.
SEPARATOR = "\n"

#: A run directory that recorded no model calls at all.  Named rather than
#: scored as zero: a run that was never recorded and a run that was cheap
#: are two different facts, and one of them is not a measurement.
NO_MODEL_LOG = (
    "no {log} — a context profile is computed from the requests the "
    "recorder wrote, and this directory holds none. A mission spawned with "
    "JUDAIS_LOBI_RUNS unset records no model log")

#: A model log that exists and holds nothing this module can read.
NO_CALLS = (
    "{log} holds no readable call — every line was empty, unparseable, or "
    "carried no request messages")

#: The role the runtime injects the compiled view under, and the second
#: half of recognising one.
#:
#: There is exactly one injection point —
#: :meth:`core.runtime.run.Run._compile_context` appends ``{"role": "user",
#: "content": block}`` after everything else — so a part under any other
#: role that happens to begin with the title is something else wearing the
#: view's first words: a tool result that echoed it back, an assistant turn
#: that quoted it, a receipt from a platform that renders it.  Matching on
#: the title alone would charge those to the view and inflate the two
#: figures an arm is read by.  If a later lane injects the block under a
#: different role, this constant moves with it and the tests say so.
#:
#: The residual the guard cannot close: the role that carries the block is
#: also the role a person speaks in, so an operator who pastes a whole
#: compiled view back into a mission IS charged to the view.  Accepted, on
#: purpose — this instrument counts what rode the context under the view's
#: name, and a pasted view did.
BLOCK_ROLE = "user"

#: The files that make a directory look like a run, for the walk below.  A
#: directory holding any of them is reported on; a directory holding none is
#: not a run and is not news.
RUN_MARKERS: Tuple[str, ...] = (MODEL_LOG, "events.jsonl", "meta.json")

#: How deep under a ``--runs`` root a run directory is looked for.  Bounded
#: because everything this harness walks is: an ablation's layout is
#: ``<out>/<arm>/<rep>/<mission>/runs/<run id>``, which is five, and a walk
#: with no floor under it is one symlink away from being the measurement.
MAX_DEPTH = 6


# ── one request, rendered ────────────────────────────────────────────────────

@dataclass(frozen=True)
class Part:
    """One piece of a rendered request, and where it sits in the string."""

    #: ``"tools"`` for the declarations, otherwise the message's role.
    label: str
    text: str
    start: int
    end: int
    #: Whether this part is the compiled view — see :func:`is_block`.
    block: bool = False
    #: The view's sections that appear in it, in render order.  Empty for
    #: every part that is not a block.
    sections: Tuple[str, ...] = ()


def is_block(text: str) -> bool:
    """Whether *text* BEGINS with the compiled view's title.

    Half of the test and never all of it — see :data:`BLOCK_ROLE` and
    :func:`render_request`, which is where the two halves are put
    together.  A title is a string, and a string can appear at the front
    of anything: a tool result that echoes the block back, an assistant
    turn that quotes it.  Charging either to the view would inflate
    exactly the two figures a lane is read by, and the role guard closes
    both.

    Exact on the one string the compiler declares for the purpose:
    :data:`core.cognition.compile.TITLE` is the block's first words and
    the module that owns it says in as many words that it is the string a
    reader of ``model.jsonl`` recognises the block by.  Leading whitespace
    is tolerated because a renderer may indent a paragraph; nothing else
    is.
    """
    return text.lstrip().startswith(TITLE)


def sections_in(text: str) -> Tuple[str, ...]:
    """Which of the view's sections *text* carries, in render order.

    Read off :data:`core.cognition.compile.HEADINGS` rather than matched by
    a copy of the words, so the section Phase 20 adds is counted here the
    day it lands and this module is not edited for it.

    Matched as a **whole line**, which is how
    :func:`core.cognition.compile._render` emits one: a heading quoted
    mid-sentence inside a fact line is a fact line that mentions a
    section, not a section.
    """
    lines = set(text.splitlines())
    return tuple(name for name, heading in zip(SECTIONS, HEADINGS)
                 if heading in lines)


def parts_of(request: Mapping[str, Any]) -> Tuple[Tuple[str, str], ...]:
    """``(label, text)`` for every part of *request*, in template order.

    The tool declarations first and the messages after them, because that
    is where a chat template renders them and therefore where a prefix
    cache meets them.  A provider that renders them elsewhere would have
    this module attributing the same characters to a different region of
    the same request — the total is unaffected, and the docstring says so
    rather than the report claiming a precision it has not got.
    """
    extra = request.get("extra")
    out: List[Tuple[str, str]] = []
    tools = extra.get("tools") if isinstance(extra, Mapping) else None
    if tools:
        # The one spelling of "this value as a string" in this tree, so two
        # readers of the same catalogue measure the same characters.
        out.append(("tools", canonical(tools)))
    for message in (request.get("messages") or ()):
        if not isinstance(message, Mapping):
            continue
        content = message.get("content")
        out.append((str(message.get("role") or "?"),
                    content if isinstance(content, str)
                    else canonical(content)))
    return tuple(out)


def render_request(request: Mapping[str, Any]) -> Tuple[str, Tuple[Part, ...]]:
    """*request* as one string, and the spans its parts occupy in it."""
    pieces = parts_of(request)
    spans: List[Part] = []
    cursor = 0
    for index, (label, text) in enumerate(pieces):
        if index:
            cursor += len(SEPARATOR)
        # BOTH halves: the title AND the role the runtime injects the view
        # under. A tool result that echoes the block back begins with the
        # same words and is not the view — see `BLOCK_ROLE`.
        block = label == BLOCK_ROLE and is_block(text)
        spans.append(Part(label=label, text=text, start=cursor,
                          end=cursor + len(text), block=block,
                          sections=sections_in(text) if block else ()))
        cursor += len(text)
    return SEPARATOR.join(text for _label, text in pieces), tuple(spans)


def head_of(parts: Sequence[Part]) -> str:
    """The system-side head of a rendered request.

    The tool declarations and the leading ``system`` message(s), and it
    stops at the first part that is neither.  This is the region a
    deployment intends to pin; :func:`common_prefix` measures what was
    *actually* pinned, and :attr:`Conversation.stable` is the two of them
    compared across a conversation's calls.
    """
    out: List[str] = []
    for part in parts:
        if part.label not in ("tools", "system"):
            break
        out.append(part.text)
    return SEPARATOR.join(out)


def common_prefix(texts: Sequence[str]) -> int:
    """The length of the longest common prefix of *texts*.

    ``0`` for fewer than two: a single request is trivially its own
    prefix, and reporting a run of one call as 100% pinned would be the
    most flattering number in the report and the least true one — nothing
    was reused because nothing was repeated.
    """
    if len(texts) < 2:
        return 0
    first, last = min(texts), max(texts)     # the extremes bound every pair
    limit = min(len(first), len(last))
    index = 0
    while index < limit and first[index] == last[index]:
        index += 1
    return index


# ── the interval algebra the attribution rests on ────────────────────────────

def _merged_length(spans: Iterable[Tuple[int, int]]) -> int:
    """The length of the union of *spans*, counted once each.

    The whole honesty of this module is here.  ``pinned``, ``block`` and
    ``rest`` are three readings of one string, and two of them can overlap
    — a compiled view that did not change between two steps lies *inside*
    the pinned prefix.  Adding three tallies that were each computed on
    their own produces a request larger than the request, which is the
    bug a reader cannot see and would read as bloat.
    """
    total = 0
    reach = 0
    for start, end in sorted((s, e) for s, e in spans if e > s):
        start = max(start, reach)
        if end > start:
            total += end - start
        reach = max(reach, end)
    return total


# ── one call ─────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CallCost:
    """What one model call was asked to carry."""

    call: int
    kind: str
    #: The rendered request's length.
    chars: int
    #: How much of it was the conversation's pinned prefix.
    prefix_chars: int
    #: The compiled view's own characters, whether or not they were pinned.
    block_chars: int
    #: The view's characters that were NOT already in the pinned prefix —
    #: the half of the block this call actually paid for.
    #:
    #: Equal to :attr:`block_chars` in every recording this release can
    #: produce, because the runtime appends the view after the transcript
    #: and the common prefix therefore stops before it.  The two are kept
    #: apart so that the attribution stays provably disjoint if a later
    #: lane ever pins the view into the head — see the module docstring.
    block_unpinned_chars: int
    #: Everything that is neither.  ``prefix + block_unpinned + rest ==
    #: chars``, always; see :func:`_merged_length`.
    rest_chars: int
    #: Parts in the request, for a reader wondering what grew.
    parts: int
    #: The provider's own ``prompt_tokens``, or ``None`` where it reported
    #: no usage.  Never estimated from characters.
    prompt_tokens: Optional[int] = None
    #: The view's sections that rode along, in render order.
    sections: Tuple[str, ...] = ()

    @property
    def new_chars(self) -> int:
        """What was not already pinned — what a cache hit would not save."""
        return self.chars - self.prefix_chars

    @property
    def block_share(self) -> float:
        return self.block_chars / self.chars if self.chars else 0.0

    @property
    def pinned_share(self) -> float:
        return self.prefix_chars / self.chars if self.chars else 0.0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "call": self.call, "kind": self.kind, "chars": self.chars,
            "prefix_chars": self.prefix_chars,
            "block_chars": self.block_chars,
            "block_unpinned_chars": self.block_unpinned_chars,
            "rest_chars": self.rest_chars, "parts": self.parts,
            "prompt_tokens": self.prompt_tokens,
            "sections": list(self.sections),
            "block_share": round(self.block_share, 4),
            "pinned_share": round(self.pinned_share, 4),
        }


@dataclass(frozen=True)
class Conversation:
    """One ``kind`` of call within a run, and what it pinned.

    A run is not always one conversation.  A swarm records its router, its
    children and its synthesis in one ``model.jsonl``, under the ``kind``
    the recorder wrote, and they do not share a system prompt — so a single
    "longest common prefix of this run" would be the few words three
    unrelated prompts happen to start with, reported as the thing a cache
    keeps.  Grouping by the recorded kind is the cheapest split that is
    right, and it is the recorder's own field rather than a heuristic.
    """

    kind: str
    #: The call ordinals in this conversation, in order.
    calls: Tuple[int, ...]
    #: The longest common prefix of its requests, in characters.
    prefix_chars: int
    #: Whether a prefix could be measured at all — two calls or more.
    measured: bool
    #: Whether the system-side head was identical across every call.
    #: ``None`` where there was nothing to compare (a conversation of one
    #: call), which is not the same answer as "yes".
    stable: Optional[bool]
    #: The first call whose head differed from the first call's, or ``None``.
    diverged_at: Optional[int] = None

    def as_dict(self) -> Dict[str, Any]:
        return {"kind": self.kind, "calls": list(self.calls),
                "prefix_chars": self.prefix_chars, "measured": self.measured,
                "stable": self.stable, "diverged_at": self.diverged_at}


# ── one run ──────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class RunCost:
    """One recorded run's context profile, or the reason it has none."""

    run: str
    path: str
    calls: Tuple[CallCost, ...] = ()
    conversations: Tuple[Conversation, ...] = ()
    #: Non-empty exactly when nothing was measured.  The sentence names
    #: what was wanted.
    refused: str = ""

    @property
    def measured(self) -> bool:
        return bool(self.calls)

    @property
    def chars(self) -> int:
        return sum(call.chars for call in self.calls)

    @property
    def block_chars(self) -> int:
        return sum(call.block_chars for call in self.calls)

    @property
    def peak_chars(self) -> int:
        return max((call.chars for call in self.calls), default=0)

    @property
    def mean_chars(self) -> float:
        return self.chars / len(self.calls) if self.calls else 0.0

    @property
    def block_share(self) -> float:
        return self.block_chars / self.chars if self.chars else 0.0

    @property
    def slope(self) -> Optional[float]:
        """Mean characters added per step, or ``None`` under two calls.

        First to last over the steps between them — the number a reader
        wants for "what does one more step cost me here".  ``None`` and
        not ``0.0`` for one call, because a slope nobody could measure and
        a flat one are different answers.
        """
        if len(self.calls) < 2:
            return None
        return ((self.calls[-1].chars - self.calls[0].chars)
                / (len(self.calls) - 1))

    @property
    def prompt_tokens(self) -> Optional[int]:
        """Every call's ``prompt_tokens``, or ``None`` if any lacked one.

        All or nothing: a total over the calls that happened to report is
        a smaller number wearing the shape of the whole run's cost.
        """
        seen = [call.prompt_tokens for call in self.calls]
        if not seen or any(value is None for value in seen):
            return None
        return sum(int(value) for value in seen if value is not None)

    @property
    def stable(self) -> Optional[bool]:
        """Whether every MEASURED conversation's head held identical.

        ``None`` where no conversation had two calls to compare.  A run of
        one model call has not got a stable prefix and has not got an
        unstable one; reporting ``true`` there would put a caching claim
        in the JSON that the Markdown, which says *no prefix measurable*,
        declines to make.
        """
        seen = [conversation.stable for conversation in self.conversations
                if conversation.stable is not None]
        return all(seen) if seen else None

    @property
    def diverged_at(self) -> Optional[int]:
        """The earliest call at which a head moved, or ``None``."""
        seen = [conversation.diverged_at
                for conversation in self.conversations
                if conversation.diverged_at is not None]
        return min(seen) if seen else None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "run": self.run, "path": self.path, "refused": self.refused,
            "calls": [call.as_dict() for call in self.calls],
            "conversations": [conversation.as_dict()
                              for conversation in self.conversations],
            "chars": self.chars, "peak_chars": self.peak_chars,
            "mean_chars": round(self.mean_chars, 1),
            "block_chars": self.block_chars,
            "block_share": round(self.block_share, 4),
            "slope": None if self.slope is None else round(self.slope, 1),
            "prompt_tokens": self.prompt_tokens,
            "stable": self.stable, "diverged_at": self.diverged_at,
        }


def _finite_int(value: Any) -> Optional[int]:
    """*value* as an ``int``, or ``None`` when it is not a finite number.

    The one guard in this module, because every number it reads comes off
    a log line somebody else wrote and a reader of recordings must never
    be the thing that raises.  ``"two"``, ``[1]``, ``{"a": 1}``, ``NaN``
    and the infinities are all *absent* rather than fatal — which is the
    discipline the rest of the file already keeps for a torn line.

    ``bool`` is excluded on purpose.  It is an ``int`` in Python, and a
    ``call: true`` silently read as ordinal 1 would collide with the real
    first call rather than being noticed.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return int(value)
    except (ValueError, OverflowError):        # NaN, ±inf
        return None


def _ordinal(record: Mapping[str, Any], fallback: int) -> int:
    """This call's ``call`` ordinal, or *fallback*.

    Every read of ``call`` goes through here — the sort key and the three
    places an ordinal is printed — because a single malformed line
    otherwise raises **at report time**, after every arm of an ablation
    has been spawned: :meth:`core.eval.ablation.Ablation.context` reaches
    :func:`cost_of_run` from both ``as_dict`` and the Markdown, so one
    corrupt line in one arm's recording would take the whole report down
    and lose the hours that produced it.

    *fallback* is the call's position in the file, which is the honest
    substitute: the order is still the order things happened in, and the
    report prints a number a reader can find.
    """
    value = _finite_int(record.get("call"))
    return fallback if value is None else value


def _model_calls(path: Path) -> List[Mapping[str, Any]]:
    """Every parseable ``model.jsonl`` line, in call order.

    A torn last line is skipped rather than fatal, the way every other
    reader of a durable log in this tree treats one — see
    :func:`core.runtime.replay._read_log`, which states the rule.
    """
    out: List[Mapping[str, Any]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except ValueError:
            continue
        if isinstance(parsed, Mapping):
            out.append(parsed)
    # A line whose ordinal will not read as a number sorts by the position
    # the file gave it, rather than to the front under a zero it never had.
    order = sorted(enumerate(out),
                   key=lambda pair: _ordinal(pair[1], pair[0] + 1))
    return [record for _position, record in order]


def _prompt_tokens(record: Mapping[str, Any]) -> Optional[int]:
    """The provider's own ``prompt_tokens`` for this call, or ``None``.

    Read off the recorded ``usage``, which is
    :meth:`core.runtime.backends.base.Usage.as_record`'s shape and nobody
    else's.  A recording with no usage gets ``None`` and the report says
    characters only — a token count divided out of a character count is a
    guess with a provider's authority on it.
    """
    reply = record.get("reply")
    usage = reply.get("usage") if isinstance(reply, Mapping) else None
    if not isinstance(usage, Mapping):
        return None
    return _finite_int(usage.get("prompt_tokens"))


def cost_of_run(directory: Path) -> RunCost:
    """One run directory's profile, or a :attr:`RunCost.refused` naming why."""
    directory = Path(directory)
    log = directory / MODEL_LOG
    if not log.exists():
        return RunCost(run=directory.name, path=str(directory),
                       refused=NO_MODEL_LOG.format(log=MODEL_LOG))

    rendered: List[Tuple[Mapping[str, Any], str, Tuple[Part, ...]]] = []
    for record in _model_calls(log):
        request = record.get("request")
        if not isinstance(request, Mapping):
            continue
        text, parts = render_request(request)
        if not parts:
            continue
        rendered.append((record, text, parts))
    if not rendered:
        return RunCost(run=directory.name, path=str(directory),
                       refused=NO_CALLS.format(log=MODEL_LOG))

    # One conversation per recorded `kind`, in the order the kinds first
    # appear, so a report reads in the order the run happened.
    grouped: Dict[str, List[int]] = {}
    for index, (record, _text, _parts) in enumerate(rendered):
        grouped.setdefault(str(record.get("kind") or ""), []).append(index)

    conversations: List[Conversation] = []
    prefix_for: Dict[int, int] = {}
    for kind, indexes in grouped.items():
        texts = [rendered[index][1] for index in indexes]
        prefix = common_prefix(texts)
        heads = [head_of(rendered[index][2]) for index in indexes]
        diverged = None
        for position, head in enumerate(heads[1:], start=1):
            if head != heads[0]:
                diverged = _ordinal(rendered[indexes[position]][0],
                                    indexes[position] + 1)
                break
        for index in indexes:
            prefix_for[index] = prefix
        measured = len(indexes) > 1
        conversations.append(Conversation(
            kind=kind,
            calls=tuple(_ordinal(rendered[index][0], index + 1)
                        for index in indexes),
            prefix_chars=prefix, measured=measured,
            # `None`, not `True`, where nothing was compared: one call
            # cannot have held stable, and a JSON reader shown `true`
            # would read a claim the Markdown correctly declines to make.
            stable=(diverged is None) if measured else None,
            diverged_at=diverged))

    calls: List[CallCost] = []
    for index, (record, text, parts) in enumerate(rendered):
        total = len(text)
        prefix = min(prefix_for.get(index, 0), total)
        blocks = [(part.start, part.end) for part in parts if part.block]
        block_chars = sum(end - start for start, end in blocks)
        unpinned = sum(max(0, end - max(start, prefix))
                       for start, end in blocks)
        covered = _merged_length([(0, prefix), *blocks])
        calls.append(CallCost(
            call=_ordinal(record, index + 1),
            kind=str(record.get("kind") or ""),
            chars=total, prefix_chars=prefix, block_chars=block_chars,
            block_unpinned_chars=unpinned, rest_chars=total - covered,
            parts=len(parts), prompt_tokens=_prompt_tokens(record),
            # Deduped: two block parts in one request would otherwise
            # report `facts` twice, which reads as two sections.
            sections=tuple(dict.fromkeys(
                name for part in parts for name in part.sections))))

    return RunCost(run=directory.name, path=str(directory),
                   calls=tuple(calls), conversations=tuple(conversations))


# ── many runs ────────────────────────────────────────────────────────────────

def run_shaped(root: Path) -> List[Path]:
    """The run directories at or under *root*, in a stable order.

    *root* itself when it looks like one — so a single recorded run can be
    pointed at directly — and otherwise a bounded walk (:data:`MAX_DEPTH`),
    because an ablation's runs sit five directories down and a walk with no
    floor under it is one symlink away from being the measurement.

    A directory that looks like a run but has a recorded run **beneath** it
    is not reported: that is the harness's own per-mission directory, which
    holds the captured stream and, under ``runs/``, the child's recording.
    Refusing it by name would put a false negative beside every real run.
    """
    root = Path(root)
    if (root / MODEL_LOG).exists():
        return [root]
    if not root.is_dir():
        return []

    found: List[Path] = [root] if any((root / marker).exists()
                                     for marker in RUN_MARKERS) else []
    frontier = [(root, 0)]
    while frontier:
        here, depth = frontier.pop(0)
        try:
            children = sorted(child for child in here.iterdir()
                              if child.is_dir() and not child.is_symlink())
        except OSError:                       # pragma: no cover - defensive
            continue
        for child in children:
            if any((child / marker).exists() for marker in RUN_MARKERS):
                found.append(child)
            if depth + 1 < MAX_DEPTH:
                frontier.append((child, depth + 1))

    recorded = {str(path) for path in found if (path / MODEL_LOG).exists()}
    keep = [path for path in found
            if str(path) in recorded
            or not any(below.startswith(str(path) + os.sep)
                       for below in recorded)]
    return sorted(set(keep), key=str)


@dataclass(frozen=True)
class ContextSummary:
    """Several runs' cost as the one row a table prints.

    The figures an ablation arm is read by, and the reason this dataclass
    exists rather than each caller summing what it wants: one owner of
    *mean chars per call* means the ablation table and the ``context``
    report cannot start disagreeing about the same arm.
    """

    runs: int = 0
    calls: int = 0
    chars: int = 0
    block_chars: int = 0
    prefix_chars: int = 0
    peak_chars: int = 0
    #: Every call's ``prompt_tokens`` summed, or ``None`` when any call in
    #: any run reported no usage.
    prompt_tokens: Optional[int] = None
    #: Runs that recorded nothing, with the sentence naming what was wanted.
    refusals: Tuple[Tuple[str, str], ...] = ()

    @property
    def measured(self) -> bool:
        return self.calls > 0

    @property
    def mean_chars(self) -> float:
        return self.chars / self.calls if self.calls else 0.0

    @property
    def mean_block_chars(self) -> float:
        return self.block_chars / self.calls if self.calls else 0.0

    @property
    def block_share(self) -> float:
        return self.block_chars / self.chars if self.chars else 0.0

    @property
    def pinned_share(self) -> float:
        return self.prefix_chars / self.chars if self.chars else 0.0

    @property
    def mean_tokens(self) -> Optional[float]:
        if self.prompt_tokens is None or not self.calls:
            return None
        return self.prompt_tokens / self.calls

    def as_dict(self) -> Dict[str, Any]:
        return {
            "runs": self.runs, "calls": self.calls, "chars": self.chars,
            "block_chars": self.block_chars,
            "prefix_chars": self.prefix_chars, "peak_chars": self.peak_chars,
            "mean_chars": round(self.mean_chars, 1),
            "mean_block_chars": round(self.mean_block_chars, 1),
            "block_share": round(self.block_share, 4),
            "pinned_share": round(self.pinned_share, 4),
            "prompt_tokens": self.prompt_tokens,
            "mean_tokens": (None if self.mean_tokens is None
                            else round(self.mean_tokens, 1)),
            "refusals": [{"path": path, "why": why}
                         for path, why in self.refusals],
        }


def summarise(runs: Sequence[RunCost]) -> ContextSummary:
    """*runs* as one row.  The ONE owner of every figure in that row."""
    measured = [run for run in runs if run.measured]
    calls = [call for run in measured for call in run.calls]
    tokens: Optional[int] = None
    if calls and all(call.prompt_tokens is not None for call in calls):
        tokens = sum(int(call.prompt_tokens or 0) for call in calls)
    return ContextSummary(
        runs=len(measured), calls=len(calls),
        chars=sum(call.chars for call in calls),
        block_chars=sum(call.block_chars for call in calls),
        prefix_chars=sum(call.prefix_chars for call in calls),
        peak_chars=max((call.chars for call in calls), default=0),
        prompt_tokens=tokens,
        refusals=tuple((run.path, run.refused) for run in runs
                       if run.refused))


def summarise_runs(roots: Sequence[Path]) -> ContextSummary:
    """Every recorded run under each of *roots*, as one row.

    The entry point ``ablation`` calls, so the column in its table and the
    tables in this module's own report are computed by the same code over
    the same directories.  A root that does not exist contributes nothing
    and is not an error: an arm that was skipped has no runs, and a table
    cell of ``—`` is the honest rendering of that.
    """
    found: List[RunCost] = []
    for root in roots:
        root = Path(root)
        if not root.exists():
            continue
        found += [cost_of_run(directory) for directory in run_shaped(root)]
    return summarise(found)


@dataclass(frozen=True)
class ContextProfile:
    """Every run under one root, and the aggregate over them."""

    root: str
    runs: Tuple[RunCost, ...] = ()

    @property
    def summary(self) -> ContextSummary:
        return summarise(self.runs)

    @property
    def tokens_recorded(self) -> bool:
        return self.summary.prompt_tokens is not None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "root": self.root,
            "summary": self.summary.as_dict(),
            "tokens_recorded": self.tokens_recorded,
            "runs": [run.as_dict() for run in self.runs],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.as_dict(), indent=indent, sort_keys=False)

    def to_markdown(self) -> str:
        return _markdown(self)


def profile(root: Path) -> ContextProfile:
    """Every run at or under *root*, profiled.  Pure, offline, no model."""
    root = Path(root)
    runs = [cost_of_run(directory) for directory in run_shaped(root)]
    return ContextProfile(root=str(root), runs=tuple(runs))


# ── the table ────────────────────────────────────────────────────────────────

#: The sentence this whole module answers, in the words it was asked in.
CRITERION = ("all of this we add, does not make the context bloated and the "
             "agent less capable")


def _thousands(value: float) -> str:
    return f"{value:,.0f}"


def _share(value: float) -> str:
    return f"{value:.1%}"


def _prefix_line(run: RunCost) -> str:
    """One conversation's prefix finding, in a sentence a reader can act on."""
    lines: List[str] = []
    for conversation in run.conversations:
        where = f"`{conversation.kind or '—'}` ({len(conversation.calls)} call"
        where += "s)" if len(conversation.calls) != 1 else ")"
        if not conversation.measured:
            lines.append(f"- {where}: **no prefix measurable** — one call, so "
                         f"nothing was repeated and nothing was reused")
            continue
        if conversation.stable:
            lines.append(f"- {where}: pinned prefix "
                         f"**{_thousands(conversation.prefix_chars)} chars**, "
                         f"system-side head **byte-stable: YES**")
        else:
            lines.append(f"- {where}: pinned prefix "
                         f"**{_thousands(conversation.prefix_chars)} chars**, "
                         f"system-side head **byte-stable: NO** — it first "
                         f"differed at call **{conversation.diverged_at}**. "
                         f"A head that moves is a prefix cache that misses "
                         f"from that call on")
    return "\n".join(lines)


def _markdown(profile_: ContextProfile) -> str:
    summary = profile_.summary
    lines = [f"# context — `{profile_.root}`", ""]
    lines += [
        "What this measures, and why it exists: *“" + CRITERION
        + "”*. Every figure below is characters in front of a model, "
          "computed from the requests the recorder wrote — nothing here ran "
          "anything.",
        "",
    ]
    if not summary.measured:
        lines.append("**No run under this root recorded a model call.** Each "
                     "directory and what it was missing:")
        lines.append("")
        lines += [f"- `{run.path}`: {run.refused}" for run in profile_.runs]
        if not profile_.runs:
            lines.append(f"- `{profile_.root}`: no run directory at or under "
                         f"it — a run directory holds one of "
                         f"{list(RUN_MARKERS)}")
        return "\n".join(lines)

    lines.append("## Aggregate")
    lines.append("")
    lines += _table(
        [[str(summary.runs), str(summary.calls),
          _thousands(summary.mean_chars), _thousands(summary.peak_chars),
          _thousands(summary.mean_block_chars), _share(summary.block_share),
          _share(summary.pinned_share),
          ("—" if summary.mean_tokens is None
           else _thousands(summary.mean_tokens))]],
        ["runs", "calls", "mean chars/call", "peak chars", "block chars/call",
         "block share", "pinned share", "prompt tokens/call"])
    lines.append("")
    if summary.prompt_tokens is None:
        lines.append("**Characters only.** At least one recorded call carried "
                     "no provider `usage`, so there is no token figure for "
                     "this root and none is estimated: a character count "
                     "divided by four is a guess wearing a provider's "
                     "authority.")
        lines.append("")

    for run in profile_.runs:
        if not run.measured:
            continue
        lines.append(f"## `{run.run}`")
        lines.append("")
        lines.append(_prefix_line(run))
        lines.append("")
        lines += _table(
            [[str(call.call), call.kind or "—", _thousands(call.chars),
              ("—" if call.prompt_tokens is None
               else _thousands(call.prompt_tokens)),
              _thousands(call.prefix_chars), _thousands(call.new_chars),
              _thousands(call.block_chars), _share(call.block_share),
              _thousands(call.rest_chars),
              ", ".join(call.sections) or "—"]
             for call in run.calls],
            ["call", "kind", "chars", "tokens", "pinned", "new", "block",
             "block share", "rest", "view sections"])
        lines.append("")
        lines.append(
            f"mean **{_thousands(run.mean_chars)}** chars/call, peak "
            f"**{_thousands(run.peak_chars)}**"
            + ("" if run.slope is None
               else f", growth **{run.slope:+,.0f}** chars/step")
            + ". All figures are **characters**, not bytes — a non-Latin "
              "script runs to three times this in UTF-8. *pinned* is what a "
              "prefix cache could have kept; *new* is what every call paid "
              "for regardless. *block* is the compiled view's own "
              "characters; it is charged to *pinned* instead, once, in the "
              "case where a view did not change between two steps and the "
              "prefix therefore covered it — which is why `pinned + "
              "block-outside-pinned + rest` is the whole request and "
              "`pinned + block + rest` is not. The runtime appends the view "
              "after the transcript, so in a recording made by this release "
              "that case does not arise and *block* is entirely *new*.")
        lines.append("")

    refused = [run for run in profile_.runs if run.refused]
    if refused:
        lines.append("## Runs refused")
        lines.append("")
        lines += [f"- `{run.path}`: {run.refused}" for run in refused]
        lines.append("")

    lines.append("Nothing here is a verdict. A block that costs characters "
                 "and buys capability is the trade this runtime is for; the "
                 "arm that costs them and buys nothing is what `ablation` "
                 "flags, with this profile beside its pass rate.")
    return "\n".join(lines)


# ── the command line ─────────────────────────────────────────────────────────

def add_parser(subs) -> argparse.ArgumentParser:
    """Register ``context`` on :func:`core.eval.run._parser`'s subparsers.

    From here rather than written out in ``run.py``, the way ``measure``,
    ``ablation``, ``extraction``, ``corpus`` and ``registry`` register
    themselves.  Deliberately without ``common``: a context profile is
    computed from recordings that already exist, so there is no suite to
    grade, no half to hold out and no model to spend.
    """
    parser = subs.add_parser(
        "context",
        help="profile what the recorded runs under a directory cost in "
             "context: growth per step, the compiled view's share, and "
             "whether the pinned prefix held")
    parser.add_argument("--runs", required=True, type=Path, metavar="DIR",
                        help="a run directory, or a directory of them; the "
                             "walk is bounded and finds an ablation's runs "
                             "under <out>/<arm>/<rep>/<mission>/runs/")
    parser.add_argument("--json", action="store_true",
                        help="print JSON instead of the Markdown tables")
    parser.add_argument("--report", type=Path, metavar="STEM",
                        help="also write the Markdown here and the same "
                             "profile as JSON beside it")
    return parser


def from_args(args: argparse.Namespace) -> int:
    """``context`` as :func:`core.eval.run.main` reaches it."""
    found = profile(args.runs)
    text = found.to_json() if args.json else found.to_markdown()
    print(text)
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        markdown, beside = report_paths(args.report)
        atomic_write_text(markdown, found.to_markdown())
        atomic_write_text(beside, found.to_json())
    if not found.summary.measured:
        print(f"context: nothing under {args.runs} recorded a "
              f"{MODEL_LOG} — a profile is computed from the requests the "
              f"recorder wrote", file=sys.stderr)
        return 2
    return 0
