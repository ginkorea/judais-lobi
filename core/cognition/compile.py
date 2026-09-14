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
conflict``.  A receipt here is a distinct evidence *locator* under the live
propositions — the leaves of the proofs, not the propositions themselves —
so a derived figure counts the receipts it rests on and not itself.

**Truncation is never silent.**  When the budget drops anything the block
says so in as many words, and says where the dropped material still is:
the transcript above it.  That is v1's *widening escape*, which §2.9.5
requires from day one — the compiled view may omit the decisive clue, and
the model must be able to reach past it.  It is deliberately the cheapest
possible one (the raw history is still in the window), and a real
``hydrate``-shaped widening is Phase 20's, behind its own gate.

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
#: render at all — see :func:`compile_view`); and the *escape* stated every
#: single time, because the receipts really are still in the transcript
#: above this block and that is what the model must be able to reach for.
OMITTED = ("{what} not shown at this budget; the receipts remain in the "
           "transcript above.")

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
    #: How many distinct receipts the facts rest on.
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


def compile_view(state: CognitiveState, *,
                 budget_chars: int = BUDGET_CHARS) -> CompiledView:
    """*state* as one block of at most *budget_chars* characters.

    Deterministic: the same state compiles to the same bytes, every time,
    in any process.  The only inputs are the store and the budget.

    **What is dropped first when the budget bites**, and the order is the
    argument: hypotheses (a guess is the cheapest thing to lose), then
    facts, oldest entity first (the receipt the mission just took is the
    one the next step is about), and conflicts **last** — an unresolved
    disagreement the model cannot see is the failure this whole block
    exists to prevent, and silence about it is worse than silence about a
    fact whose receipt is still in the transcript.
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
    receipts = {ref.locator
                for prop in live
                for ref in support[prop.id].evidence_leaves}

    by_entity: Dict[str, List[Proposition]] = {}
    for prop in live:
        by_entity.setdefault(prop.entity or "", []).append(prop)
    fact_lines = [_fact_line(prop, support[prop.id])
                  for entity in _entity_order(live)
                  for prop in by_entity[entity]]

    clash_lines = [_conflict_line(state, clash) for clash in open_clashes]
    guess_lines = [f"{_claim(prop)}  [{band(prop.authority)}]"
                   for prop in guesses]

    kept_facts, kept_clashes, kept_guesses = (len(fact_lines),
                                              len(clash_lines),
                                              len(guess_lines))
    # Drop one line at a time and re-render, because the omission sentence
    # itself costs characters: a block that dropped exactly enough lines to
    # fit and then added a line saying so would be over the cap it was
    # obeying. Bounded by construction — every pass drops one line and
    # there are finitely many — which is the property a loop inside a
    # mission step has to have.
    while True:
        text = _render(fact_lines[:kept_facts], clash_lines[:kept_clashes],
                       guess_lines[:kept_guesses], len(receipts),
                       len(fact_lines) - kept_facts,
                       len(clash_lines) - kept_clashes,
                       len(guess_lines) - kept_guesses)
        if len(text) <= budget:
            break
        if kept_guesses:
            kept_guesses -= 1
        elif kept_facts:
            kept_facts -= 1
        elif kept_clashes:
            kept_clashes -= 1
        else:
            # Nothing left to drop and it still does not fit: the budget is
            # too small to hold even the header and the sentence saying
            # what was dropped. An empty view, not an over-budget one — see
            # the module docstring.
            return CompiledView()
    return CompiledView(
        text=text, receipts=len(receipts),
        facts=kept_facts, conflicts=kept_clashes, hypotheses=kept_guesses,
        facts_omitted=len(fact_lines) - kept_facts,
        conflicts_omitted=len(clash_lines) - kept_clashes,
        hypotheses_omitted=len(guess_lines) - kept_guesses,
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


def _render(facts: Sequence[str], clashes: Sequence[str],
            guesses: Sequence[str], receipts: int,
            facts_out: int, clashes_out: int, guesses_out: int) -> str:
    """The block, from lines that have already been chosen.

    One renderer, so the budget loop measures exactly the bytes the model
    is shown — a second spelling for "what this will look like" is the
    cheapest way to ship a block that is one line over its own cap.

    A section with no lines is not rendered at all: a heading over nothing
    is the shape that tells a model a thing was searched for and not found,
    which is a claim this block has no business making.  What *was* dropped
    is said once, at the end, in :data:`OMITTED`.
    """
    head = (f"{TITLE} — compiled from {_plural(receipts, 'receipts')}, "
            f"{_plural(len(facts), 'facts')}, "
            f"{_plural(len(clashes), 'conflicts')}.")
    out: List[str] = [head]
    for heading, lines in ((FACTS_HEADING, facts),
                           (CONFLICTS_HEADING, clashes),
                           (HYPOTHESES_HEADING, guesses)):
        if not lines:
            continue
        out.append("")
        out.append(heading)
        out.extend(lines)
    lost = [f"+{_plural(dropped, kind)}"
            for dropped, kind in ((facts_out, "facts"),
                                  (clashes_out, "conflicts"),
                                  (guesses_out, "hypotheses")) if dropped]
    if lost:
        out.append("")
        out.append(OMITTED.format(what=", ".join(lost)))
    return "\n".join(out)
