# core/cognition/compile.py — the runtime's view of the problem, in one block

"""What is believed, what disagrees, and what is only guessed — rendered.

``ROADMAP.md`` §2.9.5 (Phase 18) asks for the *context compiler*: the problem
state compiled into the smallest useful model input, instead of the model
re-reading an accumulating transcript for facts the runtime already holds.
This module is the whole of the compiling, and it is **pure** — a
:class:`~core.cognition.state.CognitiveState` in, a :class:`CompiledView`
out.  No I/O, no clock, no randomness, and nothing imported from
:mod:`core.runtime`: the kernel's constitution (see
:mod:`core.cognition`) applies here unchanged, and it is what lets a test
state exactly what a state is worth as a block without running a mission.

**It is a read, and a read flushes.**  Every public reader on the kernel
calls :meth:`~core.cognition.state.CognitiveState.derive` first — the
implicit flush the kernel documents — so a view compiled with something
staged appends the ``derive`` event that staging was going to produce
anyway.  That is why the runtime compiles *after* its one defined flush
point (:meth:`core.runtime.cognition.ShadowCognition.close_step`): the
flush is then a no-op, and the reasoning log's shape stays a function of
the writes rather than of who looked.

## What is in the block, and why in this order

1. **FACTS** — the live (``OBSERVED``/``DERIVED``) propositions, one per
   line, ``entity · field = value  [band]``.  The entity is the receipt
   handle the shadow minted (``mcp.ledger_entry#r3``), so **every line
   carries its own citation**: a model quoting a figure out of this block
   can quote where it came from without looking anything up, which is the
   whole discipline the grounding checks exist to enforce.  Repeating the
   handle on each line costs budget and buys a line that is true on its
   own; a grouped rendering with the handle in a heading is one scroll away
   from a figure attributed to nothing.  Lines of one entity are
   contiguous, and entities are ordered **most recent first**, because the
   receipt the mission just took is the one the next step is about.
2. **CONFLICTS** — every *open* contradiction, one line, **both sides
   named, each with its handle**.  The owner's rule of 13 September 2026:
   surfacing both sides beats silence, and a compiled view that quietly
   picked a side would be the laundering the kernel's walls exist to stop.
   Settled rows are history and are not here — see
   :meth:`~core.cognition.state.CognitiveState.settle`.
3. **HYPOTHESES** — what a model claimed, marked as claimed and never
   mixed in with the facts, and **only if the budget has room left after
   the facts and the conflicts**.  A guess crowding out a receipt is the
   one trade this block must never make.

The header names the source: ``compiled from 3 receipts, 7 facts, 1
conflict``.  A receipt here is a distinct evidence *locator* under the
facts **this block shows** — the leaves of their proofs, not the
propositions themselves, so a derived figure counts the receipts it rests
on and not itself.  Counted over the shown facts and not over everything
live, because the three numbers are one sentence: a header that counted
receipts over the whole store beside a count of the rendered facts would
be two populations in one breath, with nothing on the line to say which
was which.

**Truncation is never silent.**  When the budget drops anything the block
says so in as many words, and says where the dropped material still is:
the mission's **result store**, under the handle every fact line already
prints.  That is v1's *widening escape*, which §2.9.5 requires from day
one — the compiled view may omit the decisive clue, and the model must be
able to reach past it.

**Not the transcript, and the difference is a measurement.**  The obvious
escape — "the receipts are still above you" — is falsifiable by this very
block: the view is window pressure like anything else, and at a tight
window two tool round trips were measured evicted to make room for one.
A sentence whose truth the block can destroy is not an escape.  The result
store is the half that cannot be evicted: it is on disk, it is addressed
by the same handle the entity names are built from, and the harness
already tells a model so when it compacts.  A real ``hydrate``-shaped
widening — asking the *store* for more state rather than for one receipt —
is Phase 20's, behind its own gate.

**The budget is a hard cap in characters** — :data:`BUDGET_CHARS`, and a
caller may pass another.  Characters and not tokens: this package has no
tokenizer, will not grow one, and a character cap is a bound a tokenizer
can only make *smaller*.  4,000 is about a thousand tokens, which is the
size at which the block is worth a step's attention beside a system turn
several times that and a transcript larger again; it is a default rather
than a discovery, and the number to move when Phase 19 measures what the
block is worth.  If the budget is too small to state even what it dropped,
the view is **empty** — a cap that is exceeded to explain itself is not a
cap, and a block that is all apology is not worth a step.

**Determinism is testable and tested**: :meth:`CompiledView.digest` is the
same string for the same state, and the same state twice is the same block
byte for byte.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from core.cognition.state import CognitiveState
from core.cognition.types import (EvidenceAuthority, LIVE_STATUSES,
                                  Proposition, PropositionStatus, Support)

__all__ = [
    "BANDS", "BUDGET_CHARS", "CONFLICTS_HEADING", "DISPUTED", "FACTS_HEADING",
    "HYPOTHESES_HEADING", "OMITTED", "TITLE", "UNGRADED",
    "CompiledView", "band", "compile_view",
]


#: The default hard cap, in characters.  See the module docstring for the
#: argument; it is one number in one place so that a deployment moving it
#: moves it once.
BUDGET_CHARS = 4000

#: The block's first words.  A constant because it is the one string a
#: reader — a person reading ``model.jsonl``, or a test — recognises the
#: block by; the runtime that injects it tracks its own message by identity
#: and does not match on this.
TITLE = "THE RUNTIME'S VIEW OF THIS PROBLEM"

FACTS_HEADING = "FACTS — established, with the receipt each came from"
CONFLICTS_HEADING = "CONFLICTS — both sides, unresolved"
HYPOTHESES_HEADING = "HYPOTHESES — claimed by a model, not established"

#: The sentence a dropped line leaves behind — **one** line for the whole
#: block, naming each kind it lost.  One spelling, so that a reader can find
#: every truncated view without matching on prose; one line, so that the
#: floor of a block is a header and a sentence rather than three of them
#: (a view whose apology does not fit is a view this module refuses to
#: render at all — see :func:`compile_view`).
#:
#: **It points at the result store and not at the transcript**, and the
#: correction is the review's: this block is itself window pressure, so a
#: sentence promising that the receipts are "above" can be falsified by the
#: block that promised it — two tool round trips were measured evicted to
#: make room for one view at a tight window.  What cannot be evicted is the
#: mission's *result store*: every receipt it took is still in it, under the
#: handle every fact line already prints.  So the escape names the thing
#: that is durably there.  The store's tool has a different name in every
#: deployment and this module is pure, so the sentence says what to ask for
#: rather than what to call — the harness's own compaction notice names the
#: tool, and one owner of that name is enough.
OMITTED = ("{what} not shown at this budget; ask the mission's result store "
           "for a receipt by the handle its facts are named with "
           "(entity `tool#handle`) — every receipt this run took is still "
           "in it, whole.")

#: How each kind of line is counted, singular and plural, in one place so
#: the header and the omission sentence cannot disagree about a word.
KINDS: Mapping[str, Tuple[str, str]] = MappingProxyType({
    "receipts": ("receipt", "receipts"),
    "facts": ("fact", "facts"),
    "conflicts": ("conflict", "conflicts"),
    "hypotheses": ("hypothesis", "hypotheses"),
})

#: The five authorities as the four bands a reader is asked to tell apart.
#: The two model-only authorities below extraction collapse into one word:
#: a reader deciding whether to trust a figure needs "a model interpreted
#: this" and "a model guessed this" to land in the same place, and the
#: kernel still holds the difference for anything that needs it.
BANDS: Mapping[EvidenceAuthority, str] = MappingProxyType({
    EvidenceAuthority.DETERMINISTIC: "verified",
    EvidenceAuthority.SOURCE: "sourced",
    EvidenceAuthority.MODEL_EXTRACTION: "model-extracted",
    EvidenceAuthority.MODEL_INTERPRETATION: "speculative",
    EvidenceAuthority.MODEL_HYPOTHESIS: "speculative",
})

#: What a claim the store declines to grade is called.  **Not a low band.**
#: :meth:`~core.cognition.state.CognitiveState.support` returns ``None``
#: for a claim it has stopped standing behind, and its docstring says what
#: rendering that as a weak grade would be: a refusal turned into an
#: opinion.
UNGRADED = "ungraded"

#: Appended to a fact's band when a contradiction names it.  The line still
#: renders — a contested figure the model cannot see is a figure it quotes
#: — and the mark is what says not to quote it alone.
DISPUTED = "disputed"

#: The separator between an entity and its field on a fact line, and
#: between the two sides of a conflict.  Constants because the corpus and
#: three tests read them.
FIELD_SEP = " · "
SIDE_SEP = "  ⇄  "


# ── one claim, one line ──────────────────────────────────────────────────────


def band(grade: Optional[EvidenceAuthority]) -> str:
    """One :class:`~core.cognition.types.EvidenceAuthority` as its band.

    ``None`` is :data:`UNGRADED` and is not the bottom of the scale: see
    that constant.  An authority this table has never heard of renders as
    its own value rather than raising — a view is not the place a mission
    finds out the enum grew — and the table is exhaustive over the enum
    today, with a test that says so.
    """
    if grade is None:
        return UNGRADED
    return BANDS.get(grade, getattr(grade, "value", str(grade)))


def _value(value: Any) -> str:
    """A triple's value, rendered so its *type* survives.

    Through :func:`json.dumps`, which is the one rendering in which ``8``
    and ``"8"`` do not look alike — the distinction the shadow's whole
    string bound exists to protect (see
    :mod:`core.runtime.cognition`).  Anything JSON cannot carry falls back
    to ``repr``, which cannot happen for a value the kernel accepted and is
    here so a view never raises inside a render.
    """
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):             # pragma: no cover - defensive
        return repr(value)


def _claim(prop: Proposition) -> str:
    """One proposition as ``entity · field = value``, or as its text.

    A text-only proposition — no triple — has no entity to cite and is
    rendered as the sentence somebody asserted.  The v1 harvest never makes
    one (it reads JSON figures and nothing else), and this branch is here
    so that a rule pack or a later extractor that does make one is not
    dropped silently out of the runtime's own view of the problem.
    """
    triple = prop.triple
    if triple is None:
        return f"“{prop.text}”"
    entity, field_, value = triple
    text = f"{entity}{FIELD_SEP}{field_} = {_value(value)}"
    return text if prop.text is None else f"{text} “{prop.text}”"


def _fact_line(prop: Proposition, support: Support) -> str:
    marks = [band(support.grade)]
    if support.contested_by or support.hypothesis:
        marks.append(DISPUTED)
    return f"{_claim(prop)}  [{' · '.join(marks)}]"


def _entity_order(props: Sequence[Proposition]) -> List[str]:
    """The entities of *props*, most recently written first.

    Recency is **insertion order in the store**, which is the order the
    kernel hands propositions back in, and an entity is as recent as its
    newest proposition.  Not a clock: there is none in this package, and a
    view that sorted on one could not be replayed.
    """
    last: Dict[str, int] = {}
    for position, prop in enumerate(props):
        last[prop.entity or ""] = position
    return sorted(last, key=lambda name: -last[name])


# ── the view ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CompiledView:
    """One rendering of a state, with what it cost and what it left out.

    Falsy when there is nothing to say: an empty state compiles to an empty
    view, and the runtime injects **no block at all** rather than a heading
    over nothing.  A mission that has taken no receipt yet gains nothing
    from this feature and pays nothing for it.
    """

    #: The block, ready to be a message.  ``""`` when there is nothing.
    text: str = ""
    #: How many distinct receipts the **rendered** facts rest on — the
    #: number the header states, over the population the header's other
    #: numbers are about.
    receipts: int = 0
    #: Facts, conflicts and hypotheses **rendered**.
    facts: int = 0
    conflicts: int = 0
    hypotheses: int = 0
    #: And the same three, **dropped** for the budget.
    facts_omitted: int = 0
    conflicts_omitted: int = 0
    hypotheses_omitted: int = 0

    def __bool__(self) -> bool:
        return bool(self.text)

    @property
    def truncated(self) -> bool:
        """Whether the budget dropped anything at all."""
        return bool(self.facts_omitted or self.conflicts_omitted
                    or self.hypotheses_omitted)

    def digest(self) -> str:
        """A short, stable hash of the block.

        For a test that wants to say "the same state compiles to the same
        view" without pasting the view into the assertion, and for a caller
        that wants to know whether the view *changed* since the last step
        without diffing prose.  Of the rendered text, because the text is
        what a model is shown — a digest over the counts would call two
        different blocks the same.
        """
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()[:16]


def _plural(count: int, kind: str) -> str:
    one, many = KINDS[kind]
    return f"{count} {one}" if count == 1 else f"{count} {many}"


def _supports(state: CognitiveState,
              props: Sequence[Proposition]) -> Dict[str, Support]:
    """:meth:`~core.cognition.state.CognitiveState.support` once per claim.

    Once, and reused for the grade, the disputed mark and the receipt
    count, because all three are questions about the same DAG walk and
    asking three times would be three walks per step.
    """
    return {prop.id: state.support(prop.id) for prop in props}


@dataclass(frozen=True)
class _Cut:
    """How many lines of each section survive, and how many did not."""

    facts: int = 0
    conflicts: int = 0
    hypotheses: int = 0
    facts_out: int = 0
    conflicts_out: int = 0
    hypotheses_out: int = 0

    @property
    def lost(self) -> bool:
        return bool(self.facts_out or self.conflicts_out
                    or self.hypotheses_out)


def _prefix(lines: Sequence[str]) -> List[int]:
    """``[0, len(l0), len(l0)+len(l1), …]`` — the cost of keeping a prefix."""
    out = [0]
    for line in lines:
        out.append(out[-1] + len(line))
    return out


def _cut_at(dropped: int, totals: Sequence[int]) -> _Cut:
    """The cut after *dropped* lines have gone, in the documented order.

    Hypotheses first (a guess is the cheapest thing to lose), then facts
    from the **end**, which is the oldest entity (the receipt the mission
    just took is the one the next step is about), and conflicts last — an
    unresolved disagreement the model cannot see is the failure this whole
    block exists to prevent.
    """
    facts, conflicts, hypotheses = totals
    out_guesses = min(dropped, hypotheses)
    out_facts = min(dropped - out_guesses, facts)
    out_clashes = min(dropped - out_guesses - out_facts, conflicts)
    return _Cut(facts=facts - out_facts, conflicts=conflicts - out_clashes,
                hypotheses=hypotheses - out_guesses, facts_out=out_facts,
                conflicts_out=out_clashes, hypotheses_out=out_guesses)


def _size(cut: _Cut, prefixes: Sequence[Sequence[int]], head: int,
          omission: int) -> int:
    """What :func:`_render` of *cut* will measure, without rendering it.

    The one thing in this module that knows the shape of the block without
    building it, and it exists for one reason: the drop loop used to
    re-render the whole block once per dropped line, which is quadratic in
    a store that only grows.  A line's cost is its length plus the newline
    that joins it, a section costs its heading and a blank line **only if
    it keeps a line**, and the omission sentence costs its own two.

    It is a second reader of :func:`_render`'s shape, which is a thing this
    package otherwise refuses to have — so it is never *trusted*: the cut
    it chooses is rendered and **measured** before it is returned, and a
    disagreement between the two yields no block rather than one over its
    own cap.  ``test_the_cut_is_tight`` is the other half of that guard: it
    says the cut is not merely safe but the largest one that fits, which is
    the half a conservative bug would pass.
    """
    total, parts = head, 1
    for heading, kept, prefix in ((FACTS_HEADING, cut.facts, prefixes[0]),
                                  (CONFLICTS_HEADING, cut.conflicts,
                                   prefixes[1]),
                                  (HYPOTHESES_HEADING, cut.hypotheses,
                                   prefixes[2])):
        if not kept:
            continue
        total += len(heading) + prefix[kept]
        parts += 2 + kept
    if cut.lost:
        total += omission
        parts += 2
    return total + parts - 1


def _floor(budget: int, totals: Sequence[int],
           prefixes: Sequence[Sequence[int]]) -> int:
    """The fewest drops that could *conceivably* fit — a binary search.

    The kept lines and the newlines between them are a **lower bound** on
    :func:`_size` (which adds a header, the headings and possibly a
    sentence on top), and that bound falls as more is dropped, so it can be
    searched where the real size cannot: every ``d`` below this answer is
    provably too big, and the caller's exact scan can start here instead of
    at zero.  Against four thousand live facts that is the difference
    between four thousand candidates and about a dozen.

    Monotone by construction, which is why it is the thing searched: each
    further drop removes a line and its newline and adds nothing at all.
    """
    whole = prefixes[0][-1] + prefixes[1][-1] + prefixes[2][-1]
    lines = sum(totals)
    # The drop order's cumulative cost: hypotheses from the end, then
    # facts, then conflicts — the same order :func:`_cut_at` walks, read as
    # "what has gone by the time d lines have gone".
    def kept_at(dropped: int) -> int:
        cut = _cut_at(dropped, totals)
        return (prefixes[0][cut.facts] + prefixes[1][cut.conflicts]
                + prefixes[2][cut.hypotheses])

    if whole + lines <= budget:
        return 0
    low, high = 0, lines
    while low < high:
        middle = (low + high) // 2
        if kept_at(middle) + (lines - middle) <= budget:
            high = middle
        else:
            low = middle + 1
    return low


def _choose(budget: int, totals: Sequence[int],
            prefixes: Sequence[Sequence[int]], head: int,
            omission: int) -> Optional[_Cut]:
    """The fewest lines to drop so that the block fits, or ``None``.

    A scan over the *number* dropped, not over renderings: every candidate
    costs a handful of additions against the prefix sums, so a store with
    ten thousand live facts is arithmetic rather than ten thousand joins of
    ten thousand strings.  Bounded by construction — there are finitely
    many lines and each step drops one more — which is the property a loop
    inside a mission step has to have.

    The scan is **exact** and starts at :func:`_floor`, which is the first
    candidate that is not already impossible.  It is not itself a binary
    search because :func:`_size` is not monotone at the two places that
    matter: the omission sentence appears when the first line goes, and a
    section's heading disappears when its last one does.  Searching a
    function that steps up as well as down is how a block ends up one line
    over the cap it was obeying.

    *head* and *omission* are **upper bounds** on those two variable-length
    pieces rather than their exact lengths, because both depend on the
    counts the scan is choosing.  Reserving the widest they could be makes
    the answer safe; the caller then spends its second render recovering
    what that reservation over-reserved.
    """
    lines = sum(totals)
    nothing = _cut_at(0, totals)
    if _size(nothing, prefixes, head, omission) <= budget:
        return nothing
    for dropped in range(max(1, _floor(budget, totals, prefixes)),
                         lines + 1):
        cut = _cut_at(dropped, totals)
        if _size(cut, prefixes, head, omission) <= budget:
            return cut
    return None


def _widest_head(totals: Sequence[int]) -> int:
    """The longest the header line can be for any cut of these totals.

    Every count the header states is between zero and its total, and a
    number's width grows with its value — so the extremes bound the middle.
    Zero is in the set as well as the total because ``0 facts`` is *longer*
    than ``1 fact``: the plural is the one place where a smaller number
    takes more room.
    """
    facts, conflicts, _hypotheses = totals
    return max(len(_head(receipts, kept_facts, kept_clashes))
               for receipts in (0, sum(totals))
               for kept_facts in (0, facts)
               for kept_clashes in (0, conflicts))


def compile_view(state: CognitiveState, *,
                 budget_chars: int = BUDGET_CHARS) -> CompiledView:
    """*state* as one block of at most *budget_chars* characters.

    Deterministic: the same state compiles to the same bytes, every time,
    in any process.  The only inputs are the store and the budget.

    **Two renders, whatever the store holds.**  The cut is chosen
    arithmetically (:func:`_choose`, over prefix sums) and rendered twice:
    once under upper bounds for the header and the omission sentence, whose
    lengths depend on the very counts being chosen, and once more with the
    lengths that first pass actually produced — which gives back the room
    the upper bound reserved and did not need.  The second is used only if
    it **measures** within the budget, so the arithmetic is checked against
    the renderer on every call rather than trusted.  This is the shape the
    review asked for: the previous version re-rendered the whole block once
    per dropped line, which is quadratic against a store that only grows —
    482 ms at four thousand live facts, on the model-call path.
    """
    budget = int(budget_chars)
    live = [prop for prop in state.propositions()
            if prop.status in LIVE_STATUSES]
    guesses = [prop for prop in state.propositions()
               if prop.status is PropositionStatus.HYPOTHESIZED]
    open_clashes = [clash for clash in state.contradictions()
                    if not clash.settled]
    if not (live or guesses or open_clashes):
        return CompiledView()

    support = _supports(state, live)
    by_entity: Dict[str, List[Proposition]] = {}
    for prop in live:
        by_entity.setdefault(prop.entity or "", []).append(prop)
    ordered = [prop for entity in _entity_order(live)
               for prop in by_entity[entity]]
    fact_lines = [_fact_line(prop, support[prop.id]) for prop in ordered]
    # Beside each fact line, the receipts that fact rests on — so that the
    # header can count the receipts of the facts it is ABOUT. Counting all
    # of them there would state two numbers over two different populations
    # in one sentence, and the reader has no way to see which.
    fact_receipts = [tuple(ref.locator
                           for ref in support[prop.id].evidence_leaves)
                     for prop in ordered]
    clash_lines = [_conflict_line(state, clash) for clash in open_clashes]
    guess_lines = [f"{_claim(prop)}  [{band(prop.authority)}]"
                   for prop in guesses]

    totals = (len(fact_lines), len(clash_lines), len(guess_lines))
    prefixes = (_prefix(fact_lines), _prefix(clash_lines),
                _prefix(guess_lines))

    def receipts_of(kept: int) -> int:
        return len({locator for refs in fact_receipts[:kept]
                    for locator in refs})

    def render(cut: _Cut) -> str:
        return _render(fact_lines[:cut.facts], clash_lines[:cut.conflicts],
                       guess_lines[:cut.hypotheses], receipts_of(cut.facts),
                       cut.facts_out, cut.conflicts_out, cut.hypotheses_out)

    first = _choose(budget, totals, prefixes, _widest_head(totals),
                    len(_omission(*totals)))
    if first is None:
        # Not even the header and the sentence saying what went will fit.
        # An empty view, not an over-budget one — a cap that is exceeded to
        # apologise for itself is not a cap.
        return CompiledView()
    text, cut = render(first), first

    # The second pass, and the only thing it is for: the first reserved the
    # widest sentence any cut of this store could need, and the cut it made
    # says which sentence is really wanted. Never a longer one — a pass
    # that keeps MORE lines drops fewer, and fewer drops cannot make that
    # sentence grow — so the room given back here is room the block is
    # entitled to.
    wider = _choose(budget, totals, prefixes, _widest_head(totals),
                    len(_omission(first.facts_out, first.conflicts_out,
                                  first.hypotheses_out)) if first.lost else 0)
    if wider is not None:
        second = render(wider)
        if len(second) <= budget:
            text, cut = second, wider
    if len(text) > budget:
        # The arithmetic and the renderer disagreed, which is the one thing
        # a second reader of a shape can do wrong. No block, rather than a
        # block over the cap somebody set.
        return CompiledView()
    return CompiledView(
        text=text, receipts=receipts_of(cut.facts),
        facts=cut.facts, conflicts=cut.conflicts, hypotheses=cut.hypotheses,
        facts_omitted=cut.facts_out, conflicts_omitted=cut.conflicts_out,
        hypotheses_omitted=cut.hypotheses_out,
    )


def _conflict_line(state: CognitiveState, clash: Any) -> str:
    """One open contradiction, **both sides named**.

    ``right`` is ``None`` only for a refutation, where the other side is
    not a claim in the store but the evidence somebody refuted it with, and
    the detail is what says so.  Every other kind names two propositions
    and both of them are rendered with their handles — the rule this
    section exists for.
    """
    left = _claim(state.proposition(clash.left))
    if clash.right is None:
        other = f"refuted — {clash.detail}" if clash.detail else "refuted"
    else:
        other = _claim(state.proposition(clash.right))
    return f"{clash.kind}: {left}{SIDE_SEP}{other}"


def _head(receipts: int, facts: int, clashes: int) -> str:
    """The header line.  One owner, because :func:`_size` measures it."""
    return (f"{TITLE} — compiled from {_plural(receipts, 'receipts')}, "
            f"{_plural(facts, 'facts')}, "
            f"{_plural(clashes, 'conflicts')}.")


def _omission(facts_out: int, clashes_out: int, guesses_out: int) -> str:
    """The sentence a dropped line leaves behind, or ``""``.  One owner."""
    lost = [f"+{_plural(dropped, kind)}"
            for dropped, kind in ((facts_out, "facts"),
                                  (clashes_out, "conflicts"),
                                  (guesses_out, "hypotheses")) if dropped]
    return OMITTED.format(what=", ".join(lost)) if lost else ""


def _render(facts: Sequence[str], clashes: Sequence[str],
            guesses: Sequence[str], receipts: int,
            facts_out: int, clashes_out: int, guesses_out: int) -> str:
    """The block, from lines that have already been chosen.

    One renderer, so what a caller measures is exactly the bytes the model
    is shown — a second spelling for "what this will look like" is the
    cheapest way to ship a block that is one line over its own cap.  The
    two pieces whose *length* is needed before the lines are chosen —
    :func:`_head` and :func:`_omission` — are functions rather than
    f-strings in here for the same reason: :func:`_size` calls the same two.

    A section with no lines is not rendered at all: a heading over nothing
    is the shape that tells a model a thing was searched for and not found,
    which is a claim this block has no business making.  What *was* dropped
    is said once, at the end, in :data:`OMITTED`.
    """
    out: List[str] = [_head(receipts, len(facts), len(clashes))]
    for heading, lines in ((FACTS_HEADING, facts),
                           (CONFLICTS_HEADING, clashes),
                           (HYPOTHESES_HEADING, guesses)):
        if not lines:
            continue
        out.append("")
        out.append(heading)
        out.extend(lines)
    sentence = _omission(facts_out, clashes_out, guesses_out)
    if sentence:
        out.append("")
        out.append(sentence)
    return "\n".join(out)
