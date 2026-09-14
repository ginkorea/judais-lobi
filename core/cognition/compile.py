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

   A line the store *concluded* rather than read is marked
   :data:`DERIVED` — ``[verified · derived]`` — because otherwise it is
   the same shape and the same band as an observation, and the one thing
   the band cannot say is that there is no receipt behind this line at
   all.  Its receipts are its premises'; the heading says so and
   :data:`DERIVED` argues why they are not listed on it.
2. **CONFLICTS** — every *open* contradiction, one line, **both sides
   named, each with its handle**.  The owner's rule of 13 September 2026:
   surfacing both sides beats silence, and a compiled view that quietly
   picked a side would be the laundering the kernel's walls exist to stop.
   Settled rows are history and are not here — see
   :meth:`~core.cognition.state.CognitiveState.settle`.
3. **OWED** — the proof frontier: every unresolved obligation the run's
   goals imply, one line, naming the goal it serves and whether anything
   is blocking it.  ``ROADMAP.md`` §2.9.6 (Phase 19) is the argument —
   *the frontier drives* — and the wording is the constitution's: these
   are lines of **state**, not instructions.  "owed: (alice,
   payment_link, ?c) — for goal g1, open" says what is missing; it does
   not tell anybody what to call.  Nothing here gates: a model
   that ignores the whole section answers exactly as it would have.
   Ordered by :meth:`~core.cognition.state.CognitiveState.ranked_frontier`
   — the order the runtime itself would work them in — so the line a
   reader's eye lands on first is the cheapest true thing to do next.
   Empty frontier, no section: a run with no goals loaded is not told
   that nothing is owed, it is told nothing, which is the same
   no-empty-headings rule the other three keep.
4. **HYPOTHESES** — what a model claimed, marked as claimed and never
   mixed in with the facts, and **only if the budget has room left after
   the facts and the conflicts**.  A guess crowding out a receipt is the
   one trade this block must never make.

## What goes first when it does not fit

:data:`DROP_ORDER`, which is data because it is the one thing in this
module somebody will want to move after Phase 19 measures the block.
Hypotheses go first (a guess is the cheapest thing to lose), then facts
**from the end** — the oldest entity — then owed, and conflicts last.

The interesting placement is owed *above* facts, and the argument is the
escape.  A dropped fact is still reachable: its line printed the handle,
and the mission's result store holds that receipt whole — which is what
:data:`OMITTED` tells the model in as many words.  A dropped **owed**
line is reachable from nowhere.  It is not in the transcript, not in the
store and not in any tool's output; it is computed from goals and rules
against the store, and no deployment has an interface that serves it.
The rule this repository truncates by is that what goes must leave a way
back, and for the frontier there is none.  The counter-argument is real
and is written here so the next reader does not have to reconstruct it:
receipts are the evidence and the frontier is only guidance, so a block
of owed lines over no facts would be a runtime talking about itself.
What settles it at this size is that the frontier is *bounded* by goals
× rules × premises while facts grow with every receipt — so keeping owed
above facts costs a handful of lines, never the block.  One constant,
one place, and Phase 19's A/B is what is allowed to move it.

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

Except for the owed lines, which get a clause of their own
(:data:`OWED_OMITTED`) saying the thing that is true of *them*: there is
nowhere to ask, because the frontier is recomputed from the goals every
step and nothing about it was lost.  Two losses, two truths, one line —
a single sentence that sent a model to the store for an obligation would
be the block promising what it knows is not there.

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
                                  Obligation, ObligationState, Proposition,
                                  PropositionStatus, Support)

__all__ = [
    "BANDS", "BUDGET_CHARS", "CONFLICTS_HEADING", "DERIVED", "DISPUTED",
    "DROP_ORDER",
    "FACTS_HEADING", "FRONTIER_CAPPED", "HYPOTHESES_HEADING", "OMITTED",
    "OWED_OMITTED",
    "OWED_HEADING", "SECTIONS", "TITLE", "UNGRADED",
    "CompiledView", "band", "compile_view", "owed_line",
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

FACTS_HEADING = ("FACTS — established, with the receipt each came from; "
                 "a derived line rests on others")
CONFLICTS_HEADING = "CONFLICTS — both sides, unresolved"
OWED_HEADING = "OWED — what the goals still require, cheapest first"
HYPOTHESES_HEADING = "HYPOTHESES — claimed by a model, not established"

#: The sections, in the order they are **rendered**, and the order every
#: tuple of per-section numbers in this module is written in.  One spelling,
#: because four parallel tuples whose order is a convention is the shape
#: where a heading ends up over the wrong lines.
SECTIONS: Tuple[str, ...] = ("facts", "conflicts", "owed", "hypotheses")

#: The order sections are **lost** in when the budget bites — first to go,
#: first in the list.  Data rather than four lines of arithmetic: the module
#: docstring argues every position, and this is the one constant Phase 19's
#: measurement is allowed to move.
DROP_ORDER: Tuple[str, ...] = ("hypotheses", "facts", "owed", "conflicts")

#: What the headings are, in :data:`SECTIONS` order.
HEADINGS: Tuple[str, ...] = (FACTS_HEADING, CONFLICTS_HEADING, OWED_HEADING,
                             HYPOTHESES_HEADING)

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

#: The clause a dropped **owed** line leaves behind — its own, beside
#: :data:`OMITTED` and never inside it.
#:
#: The escape in :data:`OMITTED` is true of three of the four sections and
#: false of this one: an owed line is not in the result store, not in the
#: transcript and not in any tool's output.  It is computed from the goals
#: and the rules against the store, and the module docstring's drop-order
#: argument turns on exactly that — *a dropped owed line is reachable from
#: nowhere*.  Sending a model to the store for one would be the block
#: promising something it knows is not there, which is worse than saying
#: nothing: a model that asks and finds nothing has spent a tool call
#: learning the runtime was wrong about itself.
#:
#: So this says what IS true.  The frontier is recomputed from the goals
#: at every step — it is not a log, and nothing about it was lost when a
#: line went — and the lines that did not fit render as soon as the ones
#: above them are resolved or the budget has room.  There is nothing to
#: ask for and nothing to recover; there is work to do, and doing it is
#: what shows the rest.
OWED_OMITTED = ("{what} not shown at this budget — nothing to ask for: the "
                "frontier is recomputed from the goals at every step, and "
                "what is not shown renders as soon as the lines above it "
                "are resolved or there is room.")

#: How each kind of line is counted, singular and plural, in one place so
#: the header and the omission sentence cannot disagree about a word.
KINDS: Mapping[str, Tuple[str, str]] = MappingProxyType({
    "receipts": ("receipt", "receipts"),
    "facts": ("fact", "facts"),
    "conflicts": ("conflict", "conflicts"),
    "owed": ("owed line", "owed lines"),
    "hypotheses": ("hypothesis", "hypotheses"),
})

#: The line an :data:`OWED` section begins with when the kernel's own walk
#: stopped short — :attr:`core.cognition.types.Frontier.truncated`, which is
#: the environment cap in
#: :meth:`~core.cognition.state.CognitiveState.obligations` and **not** this
#: module's budget.  Two different truncations and two different sentences,
#: because a reader asking "is this everything?" is owed the reason: the
#: budget's answer is :data:`OMITTED` and points at the result store, and
#: this one points nowhere because there is nowhere to point — the rest of
#: the frontier was never computed.
#:
#: No count: the kernel reports that it stopped, not how much it did not
#: reach, and a number invented here would be the second owner of a fact
#: nobody holds.
#:
#: **First** in the section, which is where a line that must not disappear
#: goes: lines are dropped from the end, so this is the last owed line to be
#: lost, and when even it goes the block's one omission sentence still says
#: ``+N owed lines`` — the flag is never silently dropped.
#:
#: **Only over rows.**  A truncated walk that left nothing unresolved
#: renders no OWED section at all rather than this line alone: the note
#: says there is more than what is shown, and over an empty section it
#: would be saying it about nothing at all.
FRONTIER_CAPPED = ("+ more owed than these — the frontier walk reached the "
                   "store's cap and stopped")

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

#: Appended to a fact's band when the store *concluded* it rather than read
#: it: :attr:`~core.cognition.types.PropositionStatus.DERIVED`.
#:
#: The first lane in which derived facts reached a model found them
#: rendering **identically to observations** — same shape, same band, same
#: line — and that is the one confusion this block cannot afford.  The band
#: says how good the evidence is and it is already honest about a chain (a
#: conclusion carries its weakest premise's authority); what it cannot say
#: is that there is no receipt behind *this* line at all.  A model asked to
#: quote a figure with where it came from will happily quote the entity
#: handle on a derived line, and no such receipt exists.
#:
#: **The mark, and not a list of the premises' receipts.**  The leaves are
#: there — :attr:`~core.cognition.types.Support.evidence_leaves`, which is
#: what :meth:`~core.cognition.state.CognitiveState.prove` walks to — but
#: rendering them on the line would put a *second* citation vocabulary in
#: the block: every other line cites the entity handle the shadow minted,
#: and an evidence locator is whatever the caller's world calls it.  It is
#: also unbounded — one conclusion over twenty premises is one very long
#: line — against a budget whose whole discipline is that a line is worth
#: what it costs.  So the line says *derived*, the heading says a derived
#: line rests on others, and the receipts stay one ``prove`` away for a
#: reader who has the store.  A shorter ``via …`` rendering is a thing
#: Phase 19's measurement may buy; it is not a thing to guess at.
DERIVED = "derived"

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
    """One live proposition as one line, with its band and its marks.

    Band first — it is the thing a reader decides on — then
    :data:`DERIVED` where the store concluded this rather than read it,
    then :data:`DISPUTED` where something contradicts it.  The order is
    strongest claim about the line to weakest: what it is worth, where it
    came from, and who disagrees.
    """
    marks = [band(support.grade)]
    if prop.status is PropositionStatus.DERIVED:
        marks.append(DERIVED)
    if support.contested_by or support.hypothesis:
        marks.append(DISPUTED)
    return f"{_claim(prop)}  [{' · '.join(marks)}]"


def owed_line(obligation: Obligation) -> str:
    """One unresolved obligation as one line of **state**.

    ``owed: (alice, payment_link, ?c) — for goal g1, open``, and when
    something has to come first: ``… — for goal g1, blocked on 2``.

    The goal is named by its **id**, which is what the reasoning log, the
    obligation's own id and every other reader call it.  Its ``note`` is
    free text a pack author wrote and may be a paragraph; a line that
    sometimes carries one and sometimes does not is a line nothing can
    parse and nobody can predict the width of.

    Three facts and no fourth: what is missing, which goal wants it, and
    whether it can be worked now.  Not "call the payments tool", not "you
    should" — the owner's ruling of 13 September 2026 is that the cognitive
    layer is shadow and additive, and a line in the imperative is the layer
    steering with a verb rather than reporting.  The state is named even
    when it is ``open``, because a reader should not have to know that
    *absence* means workable.

    **Public, and the one owner of this spelling.**
    :meth:`core.runtime.cognition.ShadowCognition.progress` renders the top
    of the frontier with it for the supervisor's stall sentence, so the line
    the model reads and the line a review quotes are the same line.
    """
    blocked = obligation.state is ObligationState.BLOCKED
    where = (f"blocked on {len(obligation.depends_on)}" if blocked
             else obligation.state.value)
    return (f"owed: {obligation.render()} — for goal {obligation.goal}, "
            f"{where}")


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
    #: Facts, conflicts, owed lines and hypotheses **rendered**.  ``owed``
    #: counts LINES and not obligations, so :data:`FRONTIER_CAPPED` is one
    #: of them: it is a line about what is owed, it costs the budget like
    #: one, and a counter that skipped it would disagree with the omission
    #: sentence about how many lines the section lost.
    facts: int = 0
    conflicts: int = 0
    owed: int = 0
    hypotheses: int = 0
    #: And the same four, **dropped** for the budget.
    facts_omitted: int = 0
    conflicts_omitted: int = 0
    owed_omitted: int = 0
    hypotheses_omitted: int = 0

    def __bool__(self) -> bool:
        return bool(self.text)

    @property
    def truncated(self) -> bool:
        """Whether the budget dropped anything at all."""
        return bool(self.facts_omitted or self.conflicts_omitted
                    or self.owed_omitted or self.hypotheses_omitted)

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
    owed: int = 0
    hypotheses: int = 0
    facts_out: int = 0
    conflicts_out: int = 0
    owed_out: int = 0
    hypotheses_out: int = 0

    @property
    def kept(self) -> Tuple[int, ...]:
        """Lines surviving, in :data:`SECTIONS` order."""
        return tuple(getattr(self, name) for name in SECTIONS)

    @property
    def out(self) -> Tuple[int, ...]:
        """Lines dropped, in :data:`SECTIONS` order."""
        return tuple(getattr(self, f"{name}_out") for name in SECTIONS)


def _prefix(lines: Sequence[str]) -> List[int]:
    """``[0, len(l0), len(l0)+len(l1), …]`` — the cost of keeping a prefix."""
    out = [0]
    for line in lines:
        out.append(out[-1] + len(line))
    return out


def _cut_at(dropped: int, totals: Sequence[int]) -> _Cut:
    """The cut after *dropped* lines have gone, in :data:`DROP_ORDER`.

    The order is data and the module docstring argues every position; this
    walks it. Each section loses lines from its **end** — for facts that is
    the oldest entity, because the receipt the mission just took is the one
    the next step is about, and for owed it is the most blocked, because the
    ranking put the workable ones first.
    """
    kept = dict(zip(SECTIONS, totals))
    gone = {name: 0 for name in SECTIONS}
    left = int(dropped)
    for name in DROP_ORDER:
        taken = min(left, kept[name])
        kept[name] -= taken
        gone[name] = taken
        left -= taken
    return _Cut(**kept, **{f"{name}_out": count
                           for name, count in gone.items()})


def _size(cut: _Cut, prefixes: Sequence[Sequence[int]],
          receipts: Sequence[int]) -> int:
    """What :func:`_render` of *cut* will measure, without rendering it.

    The one thing in this module that knows the shape of the block without
    building it, and it exists for one reason: the drop loop used to
    re-render the whole block once per dropped line, which is quadratic in
    a store that only grows.  A line's cost is its length plus the newline
    that joins it, a section costs its heading and a blank line **only if
    it keeps a line**, and the omission sentence costs its own two.

    **Exact, and every part of it built by the renderer's own owner.**  The
    header and the sentence are the two pieces whose length depends on the
    cut being measured, and both are asked for *at this cut* — through
    :func:`_head` and :func:`_omission`, which is what :func:`_render`
    calls — rather than reserved at some upper bound.  The first version
    reserved, and the review measured what that cost: 44 of 1,941 (state,
    budget) pairs kept one line fewer than a renderer alone would have,
    and two produced no block where one fits.  A reserve cannot be
    iterated out of, either, because the reserve is computed from a cut
    that was itself chosen under it — the fixed point is the conservative
    answer.  Exact has no such corner: this function computes, part for
    part, the number :func:`_render` would produce, so the cut it chooses
    is the one brute force chooses (``test_the_cut_is_what_brute_force_
    would_have_chosen`` is that claim, against a renderer and no
    arithmetic at all).

    *receipts* is the running count of distinct receipts under the first
    *n* fact lines, so the header's figure costs a lookup rather than a
    re-union per candidate.

    It remains a second reader of :func:`_render`'s shape, which is a thing
    this package otherwise refuses to have — so it is never *trusted*: the
    cut it chooses is rendered and **measured** before it is returned, and
    a disagreement between the two yields no block rather than one over its
    own cap.
    """
    total, parts = len(_head(receipts[cut.facts], cut.facts,
                             cut.conflicts)), 1
    for heading, kept, prefix in zip(HEADINGS, cut.kept, prefixes):
        if not kept:
            continue
        total += len(heading) + prefix[kept]
        parts += 2 + kept
    sentence = _omission(cut.out)
    if sentence:
        total += len(sentence)
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
    whole = sum(prefix[-1] for prefix in prefixes)
    lines = sum(totals)
    # The drop order's cumulative cost, read as "what is still here by the
    # time d lines have gone" — through :func:`_cut_at`, which owns the
    # order, rather than a second walk of :data:`DROP_ORDER` here.
    def kept_at(dropped: int) -> int:
        cut = _cut_at(dropped, totals)
        return sum(prefix[kept]
                   for kept, prefix in zip(cut.kept, prefixes))

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
            prefixes: Sequence[Sequence[int]],
            receipts: Sequence[int]) -> Optional[_Cut]:
    """The fewest lines to drop so that the block fits, or ``None``.

    **Brute force, computed instead of rendered.**  Every cut in the
    documented drop order, in order, and the first one that fits — which
    is the definition, and is what a renderer alone would find.  What this
    changes is only the cost: a candidate is a handful of additions and two
    short strings against the prefix sums, so a store with ten thousand
    live facts is arithmetic rather than ten thousand joins of ten thousand
    strings.  Bounded by construction — there are finitely many lines and
    each step drops one more — which is the property a loop inside a
    mission step has to have.

    The scan starts at :func:`_floor`, which is the first candidate that is
    not already impossible, and it is not itself a binary search because
    :func:`_size` is not monotone at the two places that matter: the
    omission sentence appears when the first line goes, and a section's
    heading disappears when its last one does.  Searching a function that
    steps up as well as down is how a block ends up one line over the cap
    it was obeying.
    """
    lines = sum(totals)
    nothing = _cut_at(0, totals)
    if _size(nothing, prefixes, receipts) <= budget:
        return nothing
    for dropped in range(max(1, _floor(budget, totals, prefixes)),
                         lines + 1):
        cut = _cut_at(dropped, totals)
        if _size(cut, prefixes, receipts) <= budget:
            return cut
    return None


def compile_view(state: CognitiveState, *,
                 budget_chars: int = BUDGET_CHARS) -> CompiledView:
    """*state* as one block of at most *budget_chars* characters.

    Deterministic: the same state compiles to the same bytes, every time,
    in any process.  The only inputs are the store and the budget.

    **One render, whatever the store holds.**  The cut is chosen
    arithmetically — :func:`_choose` walks the same candidates a renderer
    would, measuring each with :func:`_size` instead of building it — and
    only the chosen one is rendered.  The rendering is then **measured**
    against the budget before it is returned, so the arithmetic is checked
    against the renderer on every single call rather than trusted.

    The original re-rendered the whole block once per dropped line, which
    is quadratic against a store that only grows: 482 ms at four thousand
    live facts, on the model-call path.  Its first replacement rendered a
    fixed three times and reserved upper bounds for the header and the
    omission sentence, and the review measured what reserving costs — 44 of
    1,941 (state, budget) pairs kept a line they had room for, two produced
    no block at all — and reserving cannot be iterated away, because the
    reserve is derived from a cut that was chosen under it.  So nothing is
    reserved: :func:`_size` asks :func:`_head` and :func:`_omission` for
    the cut in hand, which is what :func:`_render` will ask them for.

    **What is O(N) here is the cut, and it is not what this call costs.**
    Choosing the cut is a walk of prefix sums and a binary search
    (:func:`_floor`); what dominates is upstream of it and always was —
    one :meth:`~core.cognition.state.CognitiveState.support` per live
    claim, each a memoised DAG walk, plus one rendered line per claim.
    Measured on this tree (median of five, warm): 40 ms at two thousand
    live facts, **95 ms** at four thousand and **244 ms** at eight —
    roughly 2.6× for twice the store, which is super-linear in the
    *grading* and not in the cut.  A block bounded to
    four thousand characters is therefore *not* bounded in what it costs
    to produce: the bound is on what the model reads, and the price is
    paid on what the runtime believes.  Phase 19's measurement is where
    that number gets watched.

    The OWED section adds one
    :meth:`~core.cognition.state.CognitiveState.ranked_frontier`, which is
    the obligation walk — **cached per epoch by the kernel**, and asked for
    at the same epoch by
    :meth:`core.runtime.cognition.ShadowCognition.progress`, so a step that
    both compiles a block and reads its progress pays for the walk once.
    A store with no goals pays nothing: there is nothing to walk.
    """
    budget = int(budget_chars)
    live = [prop for prop in state.propositions()
            if prop.status in LIVE_STATUSES]
    guesses = [prop for prop in state.propositions()
               if prop.status is PropositionStatus.HYPOTHESIZED]
    open_clashes = [clash for clash in state.contradictions()
                    if not clash.settled]
    # The frontier in the order the runtime would work it — one owner, in
    # the kernel — and the cap note first where the walk stopped short. A
    # store with goals and no receipts yet compiles to a block that is
    # nothing but OWED, which is the honest thing for a run that knows what
    # it wants and has established none of it.
    frontier = state.ranked_frontier()
    owed_lines = [owed_line(item) for item in frontier]
    if frontier.truncated and owed_lines:
        # The note is about lines there are more of, so it needs one. A
        # walk that stopped at the cap having resolved everything it
        # reached leaves nothing owed, and "+ more owed than these" over
        # no rows is a heading over nothing twice over: it announces a
        # section the block is not showing and claims a frontier the run
        # does not have. No lines, no section — the same rule the other
        # three keep.
        owed_lines.insert(0, FRONTIER_CAPPED)
    if not (live or guesses or open_clashes or owed_lines):
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
    clash_lines = [_conflict_line(state, clash) for clash in open_clashes]
    guess_lines = [f"{_claim(prop)}  [{band(prop.authority)}]"
                   for prop in guesses]

    # How many distinct receipts the first n fact lines rest on, for every
    # n: the header's figure, at any cut, for a lookup. Built once here
    # because the scan below asks for it per candidate and a re-union per
    # candidate is the quadratic shape this whole function stopped having.
    receipts, seen = [0], set()
    for prop in ordered:
        seen.update(ref.locator for ref in support[prop.id].evidence_leaves)
        receipts.append(len(seen))

    sections = (fact_lines, clash_lines, owed_lines, guess_lines)
    totals = tuple(len(lines) for lines in sections)
    prefixes = tuple(_prefix(lines) for lines in sections)

    cut = _choose(budget, totals, prefixes, receipts)
    if cut is None:
        # Not even the header and the sentence saying what went will fit.
        # An empty view, not an over-budget one — a cap that is exceeded to
        # apologise for itself is not a cap.
        return CompiledView()
    text = _render([lines[:kept] for lines, kept in zip(sections, cut.kept)],
                   receipts[cut.facts], cut.out)
    if len(text) > budget:
        # The arithmetic and the renderer disagreed, which is the one thing
        # a second reader of a shape can do wrong. No block, rather than a
        # block over the cap somebody set.
        return CompiledView()
    return CompiledView(
        text=text, receipts=receipts[cut.facts],
        facts=cut.facts, conflicts=cut.conflicts, owed=cut.owed,
        hypotheses=cut.hypotheses,
        facts_omitted=cut.facts_out, conflicts_omitted=cut.conflicts_out,
        owed_omitted=cut.owed_out, hypotheses_omitted=cut.hypotheses_out,
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


def _omission(dropped: Sequence[int]) -> str:
    """The sentence a dropped line leaves behind, or ``""``.  One owner.

    *dropped* is per section, in :data:`SECTIONS` order — so the sentence
    names its losses in the order the block renders them, not in the order
    it lost them.

    **Two clauses and not one**, on one line, because the two kinds of
    loss have two different truths: what came off a receipt is still in
    the result store (:data:`OMITTED`), and an owed line is in no store at
    all (:data:`OWED_OMITTED`).  Each clause appears only when something
    it is true of was dropped, so a block that lost only owed lines never
    points at a store, and a block that lost no owed lines reads exactly
    as it did before this existed.
    """
    lost = [(count, kind) for count, kind in zip(dropped, SECTIONS) if count]
    stored = [f"+{_plural(count, kind)}"
              for count, kind in lost if kind != "owed"]
    owed = [f"+{_plural(count, kind)}"
            for count, kind in lost if kind == "owed"]
    clauses = []
    if stored:
        clauses.append(OMITTED.format(what=", ".join(stored)))
    if owed:
        clauses.append(OWED_OMITTED.format(what=", ".join(owed)))
    return " ".join(clauses)


def _render(sections: Sequence[Sequence[str]], receipts: int,
            dropped: Sequence[int]) -> str:
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
    out: List[str] = [_head(receipts, len(sections[0]), len(sections[1]))]
    for heading, lines in zip(HEADINGS, sections):
        if not lines:
            continue
        out.append("")
        out.append(heading)
        out.extend(lines)
    sentence = _omission(dropped)
    if sentence:
        out.append("")
        out.append(sentence)
    return "\n".join(out)
