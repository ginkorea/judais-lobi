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

   **Subjects fold.**  Where a platform declared which fields identify
   what (``core.runtime.declarations``) the runtime links receipts to the
   subject they are about, and the kernel projects their facts onto it —
   so one figure is in the store twice, at the receipt and at the
   subject.  It is shown **once, at the subject**, with the receipt handle
   on the line: ``job:jl-731 · state = "completed"  [sourced · via
   mcp.job_status#r5]``.  Every line still carries its citation, the
   budget pays once for one figure, and the line a rule joins on and a
   goal is about is the one the model reads.  :func:`_folding` owns which
   receipt lines that suppresses and the two cases where it suppresses
   none.
2. **CONFLICTS** — every *open* contradiction, one line, **both sides
   named, each with its handle** — and where the two sides are one
   subject, each side names the call it was read from, which is what
   turns ``job:jl-731 · state = x ⇄ job:jl-731 · state = y`` into two
   tools disagreeing.  The owner's rule of 13 September 2026:
   surfacing both sides beats silence, and a compiled view that quietly
   picked a side would be the laundering the kernel's walls exist to stop.
   Settled rows are history and are not here — see
   :meth:`~core.cognition.state.CognitiveState.settle`.

   **Constraint violations render here too**, after the contradictions, and
   the caller passes them in (:func:`compile_view`'s ``violations``) because
   they are not in the store: see
   :func:`core.cognition.constraints.check_constraints` for why v1 keeps
   them outside the kernel.  A violation belongs in this section on the
   reader's terms rather than on the implementation's — it is a
   disagreement the block is showing, one line, naming what disagrees with
   what — and the header's ``N conflicts`` counts the lines this section
   holds, which is the population the heading is about.  They are **last**
   in it, so the budget takes a violation before it takes a contradiction
   the store itself recorded.
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
   no-empty-headings rule the other three keep.  A caller that passes
   *resolvers* — the plane's ``establishes``/``produces`` declarations,
   read by the runtime and handed over as a plain mapping because this
   module imports nothing from :mod:`core.runtime` — adds one clause
   naming what the plane says would answer the line
   (:data:`RESOLVABLE`).  Still state: a declaration is the platform's
   claim about its own tools, and naming one is not asking for it.
4. **HYPOTHESES** — what a model claimed, marked as claimed and never
   mixed in with the facts, and **only if the budget has room left after
   the facts and the conflicts**.  A guess crowding out a receipt is the
   one trade this block must never make.
5. **RELATED** — ``--graph-context`` (``ROADMAP.md`` §2.9.7, Phase 20a),
   and empty in every run without it.  The entities a bounded walk of the
   run's own topology reaches from **what is owed**, one edge to a line,
   with the relation named and the authority the edge arrived on.  It is
   the one section that is not about what the store *believes*: an edge
   says two things are related, which is a reason to look and never a
   finding.  The caller passes the edges in (:func:`compile_view`'s
   ``related``) for :data:`~core.cognition.constraints.VIOLATION_KIND`'s
   reason one door further out — the graph is a sibling package this one
   does not import, the runtime holds both, and a compiler that reached
   for a topology store would have acquired the dependency the kernel's
   constitution refuses.

## What goes first when it does not fit

:data:`DROP_ORDER`, which is data because it is the one thing in this
module somebody will want to move after Phase 19 measures the block.
Related goes first, then hypotheses (a guess is the next cheapest thing
to lose), then facts **from the end** — the oldest entity — then owed,
and conflicts last.

Related **before** hypotheses, and the argument is the one the whole
order runs on: what is the least this block can afford to lose.  A
hypothesis is at least a claim somebody made about the problem; a related
line is the runtime saying two names are connected, with no claim in it
at all — it is a pointer to a *question*, the most speculative thing the
block can carry, and the first thing a reader would skip.  It is also the
only section whose loss costs nothing at all in reachability: the walk is
re-hydrated from the frontier at every step, so what does not fit now
renders as soon as there is room.

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

from core.cognition.constraints import VIOLATION_KIND, Violation
from core.cognition.state import PROJECTION_RULE_ID, CognitiveState
from core.cognition.types import (EvidenceAuthority, LIVE_STATUSES,
                                  Obligation, ObligationState, Proposition,
                                  PropositionStatus, Support, subject_parts)

__all__ = [
    "BANDS", "BUDGET_CHARS", "CONFLICTS_HEADING", "DERIVED", "DISPUTED",
    "DROP_ORDER",
    "FACTS_HEADING", "FRONTIER_CAPPED", "HYPOTHESES_HEADING", "MORE",
    "OMITTED", "OWED_OMITTED",
    "OWED_HEADING", "RELATED", "RELATED_ARROW", "RELATED_CAPPED",
    "RELATED_HEADING", "RELATED_OMITTED",
    "RESOLVABLE", "RESOLVER_CAP", "SECTIONS",
    "STEERING_CAPPED", "STEERING_GROUP", "STEERING_GROUPS", "STEERING_LINES",
    "STEERING_MORE", "STEERING_OVERFLOW", "STEERING_SENTENCE",
    "STEERING_TITLE", "TITLE",
    "UNGRADED", "VIA", "VIA_CAP", "VIOLATIONS_OMITTED",
    "CompiledView", "RelatedEdge", "band", "compile_view", "owed_line",
    "related_line", "steering_hint", "violation_line",
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
RELATED_HEADING = ("RELATED — what the run's own topology connects to what "
                   "is owed; a reason to look, not a finding")

#: The sections, in the order they are **rendered**, and the order every
#: tuple of per-section numbers in this module is written in.  One spelling,
#: because five parallel tuples whose order is a convention is the shape
#: where a heading ends up over the wrong lines.
SECTIONS: Tuple[str, ...] = ("facts", "conflicts", "owed", "hypotheses",
                             "related")

#: The order sections are **lost** in when the budget bites — first to go,
#: first in the list.  Data rather than five lines of arithmetic: the module
#: docstring argues every position, and this is the one constant Phase 19's
#: measurement is allowed to move.
DROP_ORDER: Tuple[str, ...] = ("related", "hypotheses", "facts", "owed",
                               "conflicts")

#: What the headings are, in :data:`SECTIONS` order.
HEADINGS: Tuple[str, ...] = (FACTS_HEADING, CONFLICTS_HEADING, OWED_HEADING,
                             HYPOTHESES_HEADING, RELATED_HEADING)

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

#: The clause a dropped **violation** leaves behind, beside the other two.
#:
#: A third sentence for a third truth, and the review is why there are three.
#: A violation shares the CONFLICTS section with the store's own
#: contradictions, so a dropped one used to leave :data:`OMITTED` behind —
#: *ask the mission's result store, every receipt this run took is still in
#: it, whole*.  That is false of a violation and expensively so: a violation
#: is **computed** from a pack's arithmetic against the store, it is in no
#: tool's output and no receipt, and a model that spent a call asking for one
#: would learn only that the runtime was wrong about itself.
#:
#: What is true of it is what is true of an owed line — it is recomputed
#: every step, nothing was lost, and it renders again as soon as there is
#: room — so this says that, in its own clause rather than inside
#: :data:`OWED_OMITTED`, because a reader counting owed lines should not find
#: violations in the number.
#:
#: **What a third clause costs, measured**: the floor below which no block
#: can be rendered at all — because dropping the first line adds a sentence
#: longer than the line it saved — rises from about 330 characters to about
#: 520 when all three clauses are in play.  At the shipped
#: :data:`BUDGET_CHARS` of 4,000 that is unreachable, and below it the
#: failure is the one this module already chooses: an empty view rather than
#: a block over its cap.  Worth knowing for a deployment that sets a very
#: small budget deliberately.
VIOLATIONS_OMITTED = ("{what} not shown at this budget — nothing to ask for: "
                      "a constraint is checked against the store again at "
                      "every step, and what is not shown renders as soon as "
                      "there is room.")

#: The clause a dropped **related** line leaves behind, and the fourth
#: truth in this family.
#:
#: It is :data:`VIOLATIONS_OMITTED`'s shape for
#: :data:`OWED_OMITTED`'s reason: a related line is *computed* — the working
#: set is hydrated from the frontier against the graph at every step — so it
#: is in no receipt and no result store, and the sentence that sent a model
#: there would be the block promising what it knows is not there.  Its own
#: clause and not folded into either neighbour, because a reader counting
#: owed lines should not find edges in the number, and a reader counting
#: violations should not either.
#:
#: **What a fourth clause costs**, in :data:`VIOLATIONS_OMITTED`'s own
#: terms: the floor below which no block renders at all rises again, by
#: about the length of this sentence, for a block that is losing all four
#: kinds at once.  At the shipped :data:`BUDGET_CHARS` that is unreachable,
#: and RELATED is the section that goes first — so in the ordinary tight
#: block this clause is the only one of the four in play, and it is shorter
#: than the line it replaced.
RELATED_OMITTED = ("{what} not shown at this budget — nothing to ask for: "
                   "the working set is hydrated from what is owed again at "
                   "every step, and what is not shown renders as soon as "
                   "there is room.")

#: How each kind of line is counted, singular and plural, in one place so
#: the header and the omission sentence cannot disagree about a word.
KINDS: Mapping[str, Tuple[str, str]] = MappingProxyType({
    "receipts": ("receipt", "receipts"),
    "facts": ("fact", "facts"),
    "conflicts": ("conflict", "conflicts"),
    "owed": ("owed line", "owed lines"),
    "hypotheses": ("hypothesis", "hypotheses"),
    "related": ("related line", "related lines"),
    "violations": ("constraint violation", "constraint violations"),
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

#: :data:`FRONTIER_CAPPED`'s sibling for the RELATED section: the **walk**
#: hit its own budget (:attr:`core.cognition.graph.hydrate.WorkingSet
#: .truncated`), so there is more connected to what is owed than this
#: section holds.
#:
#: A third truncation with a third sentence, for the reason there are
#: already two: the budget's answer points at the result store, the
#: frontier's points nowhere because the rest was never computed, and this
#: one points at the graph — which is still there, whole, and simply was not
#: walked this far.  Saying "not shown at this budget" here would name the
#: wrong cap and send a reader to the wrong number.
#:
#: **First** in the section, and **only over rows**, both for
#: :data:`FRONTIER_CAPPED`'s reasons: lines go from the end, so the flag is
#: the last thing lost, and a cap note over an empty section would announce
#: a neighbourhood the block is not showing at all.
RELATED_CAPPED = ("+ more connected than these — the working set reached its "
                  "own node or edge budget and stopped")

#: What a RELATED line begins with.  The line's own word, in the idiom of
#: ``owed:`` and ``constraint:`` — a reader scanning a block should be able
#: to tell what kind of statement a line is from its first token.
RELATED = "related: "

#: The relation, rendered between the two ends of a related line:
#: ``mcp.job_status#r5 —about→ job:jl-731``.  The arrow carries the
#: relation's name because a topology with one relation today will have
#: several tomorrow, and a line that showed only the direction would make
#: two different kinds of connection look like one.
RELATED_ARROW = " —{relation}→ "

# ── the planner's hint (ROADMAP §2.9.7, Phase 20b) ───────────────────────────
#
# A second, much smaller rendering of the same frontier, for one reader: the
# staged turn's planner, once per planning round. It is not a section of the
# compiled view and it never rides in a mission step — see
# `core.runtime.cognition.ShadowCognition.planning_hint`, which is the only
# caller — and it is here rather than in the runtime because `owed_line` is
# here and one spelling of an owed line is the whole point of that function.

#: The hint's first words — what a reader (and a test) recognises it by.
STEERING_TITLE = "INDEPENDENT WORK STILL OWED"

#: The one sentence of the hint that is not a line of the frontier, and the
#: only place in this module where the shape of the *answer* is discussed.
#:
#: **A fact, in the indicative.**  Nothing here says to write a step per
#: group, to write one at all, or that a plan ignoring this is wrong: the
#: owner's ruling of 13 September 2026 is that the cognitive layer is shadow
#: and additive, and a hint in the imperative is the layer planning rather
#: than reporting.  What it states is a property of the partition the store
#: computed — the groups share no subject — and the consequence a planner can
#: draw from it on its own.  The planner is free to ignore every word of it;
#: there is no path from this string to a rejected plan, and
#: :meth:`core.runtime.swarm.SwarmRunner._read_plan` has never heard of it.
STEERING_SENTENCE = (
    "Nothing in one group shares a subject with anything in another, so "
    "work drawn from different groups does not depend on work in the rest.")

#: One group's own line.  Numbered from 1, in the order
#: :meth:`~core.cognition.state.CognitiveState.independent_frontier` gave
#: them, which is the ranked frontier's order.
STEERING_GROUP = "group {number}:"

#: How many groups the hint shows.  A cap and not a budget in characters:
#: what bounds this block is how many *distinct* things it claims can be
#: worked at once, and a planner told about nine of them is a planner being
#: handed a plan it could not fit under its own step cap
#: (:data:`~core.runtime.swarm.MAX_PLAN_STEPS` is 8, and a real ceiling is
#: usually smaller).  Four is the shape of a staged turn, not a guess about
#: width.
STEERING_GROUPS = 4

#: How many owed lines the hint shows **per group**.  A group is named by
#: what is owed in it, and three lines name it; the rest of the group is
#: what the group is *for*, and a planner does not need the whole of it to
#: write one step about it.
STEERING_LINES = 3

#: What a group with more owed than :data:`STEERING_LINES` says, inside the
#: group, so the overflow is attached to the thing it overflowed from.
STEERING_MORE = "+{count} more owed in this group"

#: What the hint says when there were more groups than :data:`STEERING_GROUPS`
#: — named, and never dropped in silence, which is this repository's rule
#: about every budget it spends (see :data:`OMITTED`).
STEERING_OVERFLOW = "+{count} more independent group(s) not shown here"

#: What the hint says when the frontier walk itself stopped short.  It is a
#: stronger statement than :data:`FRONTIER_CAPPED` makes about the OWED
#: section and it is deliberately worded that way: an obligation the walk
#: never reached could have been the one that joined two of these groups, so
#: a capped walk does not just mean *more* groups, it means the groups shown
#: may not really be independent.
STEERING_CAPPED = ("+ the frontier walk reached the store's cap and stopped, "
                   "so something not shown here may join two of these groups")

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

#: What a **subject** line says instead of :data:`DERIVED`: the receipt (or
#: receipts) its figure was read off, folded into the line that shows it
#: once.
#:
#: ``job:jl-731 · state = "completed"  [sourced · via mcp.job_status#r5]``.
#:
#: A subject fact is derived — the store concluded it from a receipt fact and
#: a link — and by :data:`DERIVED`'s own argument a derived line must not
#: impersonate a receipt.  The argument turns on a fact about *rule*
#: conclusions: their premises are other claims, they are unbounded in
#: number, and naming their receipts would need a second citation vocabulary
#: (evidence locators) beside the handles every other line prints.  A
#: projection is the one derivation where none of that holds.  It has exactly
#: one premise, the premise is one receipt fact saying this field and this
#: value, and the citation is a **handle** — the same word, in the same
#: vocabulary, that the receipt's own line would have printed.  So the line
#: names it, and the receipt's duplicate line is suppressed rather than
#: printed twice at two entities: the budget pays once for one figure, and
#: the citation discipline is kept rather than apologised for.
#:
#: The word ``derived`` is therefore **not** added to a folded line.  It
#: exists to say *there is no receipt behind this*; there is one, and it is
#: on the line.
#:
#: **And only where there really is one.**  A projection's premise can
#: itself be a conclusion — a pack rule firing at the receipt level — and
#: naming the receipt for a figure it never returned would be this module
#: writing, in its own voice, the fabricated attribution the grounding
#: checks exist to catch in the model's.  :func:`_via` names a handle only
#: for an un-derived premise, and a claim with none falls back to
#: :data:`DERIVED`, which is then simply true.
VIA = "via "

#: How many receipt handles a folded line names before it stops naming them
#: — and, because the two decisions have to agree, **the most a line may
#: fold**.  Beyond it the subject line still renders with its first
#: :data:`VIA_CAP` handles and a :data:`MORE` tail, and the receipts' own
#: lines are **kept**: a fold is only honest while the line that replaces
#: those lines can still name every one of them, and a subject agreed by
#: twenty receipts is exactly where a reader needs the list it is not being
#: shown.  Three, because that is a sentence a reader takes in at a glance
#: and is more receipts than any real agreement this store has seen.
VIA_CAP = 3

#: The tail a capped list of names ends in — one spelling for the two lists
#: that have a cap (:data:`VIA_CAP`, :data:`RESOLVER_CAP`), so a reader
#: meets one shape and a test matches one string.
MORE = "+{count} more"

#: What an OWED line says about the calls that could answer it, from the
#: plane's ``establishes``/``produces`` declarations.
#:
#: ``owed: (?j, label_set, ?a) — for goal g1, open — resolvable via:
#: job_status``.
#:
#: **State, like the rest of the line** (see :func:`owed_line`): it names
#: the tools that *declare* they can establish this field, which is a fact
#: about the plane, not an instruction to call one.  The declaration may be
#: wrong — a plane's schema can drift from its behaviour — and that is
#: exactly why this is a hint in a line of state rather than anything the
#: runtime acts on: a wrong ``establishes`` costs one phrase, never a call
#: and never a fact.
RESOLVABLE = " — resolvable via: "

#: How many tools a :data:`RESOLVABLE` clause names before the
#: :data:`MORE` tail.  Same argument as :data:`VIA_CAP` and a different
#: number is not worth a second constant: an owed line whose hint is longer
#: than the obligation is a line that buries what it is about.
RESOLVER_CAP = 3

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
    """A triple's value, rendered so its *type* survives.  **Total.**

    Through :func:`json.dumps`, which is the one rendering in which ``8``
    and ``"8"`` do not look alike — the distinction the shadow's whole
    string bound exists to protect (see
    :mod:`core.runtime.cognition`).  Anything JSON cannot carry falls back
    to ``repr``, which cannot happen for a value the kernel accepted and is
    here so a view never raises inside a render.

    Total is load-bearing, because this runs while a line of model input
    is being built and the store CAN hold an integer big enough to trip
    CPython's decimal-conversion limit (``sys.set_int_max_str_digits``,
    4,300 digits by default) — the harvest takes whatever figure a
    receipt carried.  ``json.dumps`` raises ``ValueError`` out of ``str``
    itself on such an int, and so would a ``repr`` fallback, so the limit
    is described rather than hit: the same named escape
    :func:`core.cognition.constraints._show` renders — DIGITS and not
    bits called digits, through the same integer arithmetic (``643/2136``
    is log10(2) to ten places).  A container carrying one gets a typed
    escape instead of its contents, because the only bounded sentence
    about it that is true is what it is.
    """
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:                           # pragma: no cover - defensive
        return repr(value)
    except ValueError:
        if isinstance(value, int) and not isinstance(value, bool):
            return f"a {value.bit_length() * 643 // 2136 + 1}-digit integer"
        return f"a {type(value).__name__} too large to print"


@dataclass(frozen=True)
class _Projection:
    """What one subject claim was projected from — see :func:`_via`."""

    #: The receipt handles the line may name: the entities of premises the
    #: store **read** rather than concluded.
    handles: Tuple[str, ...] = ()
    #: The claims whose own line the subject's line replaces.  A subset of
    #: :attr:`premises`: a derived premise is never folded away, because
    #: the subject's line is not saying what that premise says.
    facts: Tuple[str, ...] = ()
    #: Every projection premise, derived ones included — the population the
    #: header counts receipts through.
    premises: Tuple[str, ...] = ()


def _entity(name: Any) -> str:
    """An entity name as a line may print it — **visibly**, or escaped.

    An entity is ASCII in every deployment this framework has met: a tool
    name and a handle on one side of the ``#``, and on the other a subject
    spelled ``kind:value`` out of a *payload string a platform declared to
    be an identity*.  That last half is the new one, and it is the reason
    this function exists: a value carrying a zero-width joiner, a Cyrillic
    ``а`` or a right-to-left override renders as a line **visually
    identical** to another subject's, and a reader comparing two lines of a
    CONFLICTS section would be deciding about identity on a rendering that
    cannot show the difference.  The kernel refuses whitespace and control
    characters in a subject and nothing more — no store can own a table of
    confusables — so the view says it here, where the reading happens.

    Printable ASCII passes through untouched, which is every line this
    block has ever rendered.  Anything else is rendered through
    :func:`json.dumps` with ``ensure_ascii``: the confusable becomes a
    ``\\uXXXX`` escape inside quotes, so two lines that looked the same
    stop looking the same.  Ugly on purpose, and only where it matters.

    **Values are not escaped**, and that bound is deliberate rather than
    forgotten: ``_value`` renders with ``ensure_ascii=False`` because a
    figure's *type* is what that rendering protects and a payload's prose
    is not an identity anybody joins on.  A confusable inside a value can
    still mislead a reader; what it cannot do is make two different
    subjects look like one, which is the failure this lane introduced the
    surface for.
    """
    text = str(name)
    if all(" " <= char <= "~" for char in text):
        return text
    return json.dumps(text, ensure_ascii=True)


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
    text = f"{_entity(entity)}{FIELD_SEP}{field_} = {_value(value)}"
    return text if prop.text is None else f"{text} “{prop.text}”"


def _named(names: Sequence[str], cap: int) -> str:
    """*names*, up to *cap* of them, and how many did not fit.

    The one owner of a capped list of names, for the two lines that have
    one: a folded fact's receipts (:data:`VIA_CAP`) and an owed line's
    resolvers (:data:`RESOLVER_CAP`).  Two spellings of "and three more"
    is the shape where a reader learns one of them and misreads the other.
    """
    shown = list(names[:cap])
    rest = len(names) - len(shown)
    if rest > 0:
        shown.append(MORE.format(count=rest))
    return ", ".join(shown)


def _via(state: CognitiveState, prop: Proposition) -> "_Projection":
    """What a subject claim was projected from: handles, folds, premises.

    Three readings of one walk because they are one fact about the claim:
    a subject claim the store derived through
    :data:`~core.cognition.state.PROJECTION_RULE_ID` rests on one claim per
    proof, and *which receipts may be named*, *which lines the subject's
    line therefore replaces*, and *which claims the header counts through*
    are that same list read three ways.  One owner, so a folded line and
    the receipt line it replaces can never disagree about what was folded.

    **A handle is named only where the premise is itself un-derived**, and
    this is the line between a citation and a fabrication.  A pack's rule
    can conclude a *receipt-level* claim — ``job_status#r5 · fast = true``
    out of ``elapsed < 10`` — and that conclusion projects like any other
    live triple.  Naming the receipt on the subject's line would say the
    call returned a ``fast`` field it never returned: the framework
    generating, in its own voice, exactly the attribution the grounding
    checks exist to catch in the model's.  So a projection whose premise
    is ``DERIVED`` names nothing, the line falls back to :data:`DERIVED`
    (there is no receipt behind it, which is true), and the premise keeps
    its own line saying the same thing one level down.

    ``premises`` keeps **every** projection premise, derived ones included,
    because the header's question is different: how many receipts does this
    line rest on.  A derived premise's own leaves are the receipts under
    *its* proof, which is the honest count, and counting the projection's
    own leaves instead would count the link's declaration as a call.

    Handles are **sorted**.  The walk order is the store's history — which
    proof was recorded first — and a line whose word order depends on which
    of two identical receipts arrived first is a line that renders two ways
    for one belief.  Sorting costs nothing and makes the line a function of
    the claim.
    """
    if prop.entity is None or subject_parts(prop.entity) is None:
        return _Projection()
    handles: List[str] = []
    facts: List[str] = []
    premises: List[str] = []
    for derivation in state.derivations_for(prop.id):
        if derivation.rule != PROJECTION_RULE_ID:
            continue
        for pid in derivation.premises:
            if pid not in premises:
                premises.append(pid)
            source = state.proposition(pid)
            if source.status is PropositionStatus.DERIVED:
                # A conclusion, not a reading. The receipt never said it.
                continue
            if source.entity and source.entity not in handles:
                handles.append(source.entity)
                facts.append(pid)
    return _Projection(handles=tuple(sorted(handles)), facts=tuple(facts),
                       premises=tuple(premises))


def _via_mark(handles: Sequence[str]) -> str:
    """``via mcp.job_status#r5`` — the one spelling, for both sections.

    A fact line carries it as a mark inside the brackets and a conflict
    line carries it beside each side, and both come through here: the
    finding-D pair (two status tools, one job, two answers) is only worth
    rendering if the two sides say **which call** said each, in the same
    words the FACTS section uses for the same thing.
    """
    return VIA + _named([_entity(handle) for handle in handles], VIA_CAP)


def _fact_line(prop: Proposition, support: Support,
               handles: Sequence[str] = ()) -> str:
    """One live proposition as one line, with its band and its marks.

    Band first — it is the thing a reader decides on — then where it came
    from (:data:`VIA` for a subject fact folded out of its receipts,
    :data:`DERIVED` for a conclusion that has no receipt to name), then
    :data:`DISPUTED` where something contradicts it.  The order is
    strongest claim about the line to weakest: what it is worth, where it
    came from, and who disagrees.

    A projected line takes ``via`` **instead of** ``derived``, and
    :data:`VIA` argues why: the word exists to say there is no receipt
    behind the line, and here the receipt is on it.  A subject claim that
    is *also* concluded by a pack's rule is still named by its receipts —
    the projection is a true account of where the figure was read — and
    the rule's proof stays one ``prove`` away, as it is for every other
    line in this section.
    """
    marks = [band(support.grade)]
    if handles:
        marks.append(_via_mark(handles))
    elif prop.status is PropositionStatus.DERIVED:
        marks.append(DERIVED)
    if support.contested_by or support.hypothesis:
        marks.append(DISPUTED)
    return f"{_claim(prop)}  [{' · '.join(marks)}]"


def _resolvable(obligation: Obligation,
                resolvers: Optional[Mapping[str, Sequence[str]]]) -> str:
    """The :data:`RESOLVABLE` clause for one obligation, or ``""``.

    *resolvers* is ``{field: tool names}`` — what the plane **declared** it
    can establish — and it arrives as a plain mapping because this module
    is pure: :class:`core.runtime.declarations.PlaneDeclarations` lives in
    :mod:`core.runtime`, the kernel imports nothing from there, and a
    compiler that reached for a tool plane would have acquired the
    dependency this package's constitution exists to refuse.  The runtime
    reads the declarations and hands over the answer.

    **This does not share an owner with the grounding checks' remedy**
    (``core.runtime.grounding``'s ``CheckResult.remedy``, which names the
    code-plane tools a repair should use), and the reason is worth writing
    down rather than leaving as a layering accident.  Two reasons, and
    either alone would be enough:

    * the layer.  ``grounding`` is runtime — it holds a mission's offered
      set, its sandbox and its conduct — and importing it here would drag
      all of that into a module whose whole testable property is that a
      state and a budget are its only inputs;
    * the question.  The remedy answers *which tool on this table could
      compute a figure the model derived in prose*; this answers *which
      tool declares it establishes this field*.  One is about the
      code plane and an answer already written, the other about a plane's
      declarations and a fact nobody holds yet.  A shared owner would be
      one function with two meanings, which is the second answer to each of
      them — the failure "one owner per fact" is about, arrived at from the
      other side.

    Where they would genuinely meet is a platform wanting the remedy to
    name a *declared* establisher.  That is the runtime's call to make,
    with both in hand, and it belongs on the runtime side of this wall.

    Only a literal field binds: an obligation missing the field itself
    (``(?e, ?f, ?v)``) is a hole a declaration cannot name.
    """
    if not resolvers:
        return ""
    field = obligation.pattern[1]
    if not isinstance(field, str):
        return ""
    names = [str(name) for name in resolvers.get(field, ())]
    return f"{RESOLVABLE}{_named(names, RESOLVER_CAP)}" if names else ""


def owed_line(obligation: Obligation,
              resolvers: Optional[Mapping[str, Sequence[str]]] = None) -> str:
    """One unresolved obligation as one line of **state**.

    ``owed: (alice, payment_link, ?c) — for goal g1, open``, and when
    something has to come first: ``… — for goal g1, blocked on 2``.

    With *resolvers* — what the plane declares it can establish — the line
    ends in :data:`RESOLVABLE` and the tools that said so.  It is a fourth
    fact of the same kind as the other three (what is missing, which goal
    wants it, whether it can be worked, and what the plane says would
    answer it), and it is still not an instruction: a declaration is the
    platform's claim about its own tools, and a line naming one steers no
    more than a line naming a goal does.

    The goal is named by its **id**, which is what the reasoning log, the
    obligation's own id and every other reader call it.  Its ``note`` is
    free text a pack author wrote and may be a paragraph; a line that
    sometimes carries one and sometimes does not is a line nothing can
    parse and nobody can predict the width of.

    Facts and no instruction: what is missing, which goal wants it,
    whether it can be worked now, and — where a plane declared one — what
    would establish it.  Not "call the payments tool", not "you should" —
    the owner's ruling of 13 September 2026 is that the cognitive layer is
    shadow and additive, and a line in the imperative is the layer steering
    with a verb rather than reporting.  The state is named even when it is
    ``open``, because a reader should not have to know that *absence* means
    workable.

    **Public, and the one owner of this spelling.**
    :meth:`core.runtime.cognition.ShadowCognition.progress` renders the top
    of the frontier with it for the supervisor's stall sentence, so the line
    the model reads and the line a review quotes are the same line — which
    is why *resolvers* is a parameter here and not a thing the block adds
    afterwards: the runtime hands the same mapping to both calls.
    """
    blocked = obligation.state is ObligationState.BLOCKED
    where = (f"blocked on {len(obligation.depends_on)}" if blocked
             else obligation.state.value)
    return (f"owed: {obligation.render()} — for goal {obligation.goal}, "
            f"{where}{_resolvable(obligation, resolvers)}")


def steering_hint(groups: Sequence[Sequence[Obligation]],
                  resolvers: Optional[Mapping[str, Sequence[str]]] = None,
                  *, max_groups: int = STEERING_GROUPS,
                  max_lines: int = STEERING_LINES) -> str:
    """The independent groups of the frontier, as one bounded block.

    *groups* is what
    :meth:`~core.cognition.state.CognitiveState.independent_frontier`
    returns.  The result is the block the staged turn's planner is shown
    once per planning round (ROADMAP §2.9.7), and ``""`` whenever there is
    nothing a *planner* can do with it: no groups, or one.

    **One group is not a hint.**  A frontier that is all one problem has
    nothing independent in it, and rendering it here would be the second
    emitter of the OWED section — which ``--compiled-context`` already owns,
    in the one place the model reads the frontier as state.  So this returns
    the empty string, and a run that wanted the frontier in front of its
    planner asks for the view.

    Bounded twice and **both overflows are named**: :data:`STEERING_GROUPS`
    groups, :data:`STEERING_LINES` owed lines inside each, with
    :data:`STEERING_OVERFLOW` and :data:`STEERING_MORE` saying what is not
    shown.  A walk that was itself cut short adds :data:`STEERING_CAPPED`,
    which says the stronger thing — that the *independence* is what the cap
    put in doubt.  The flag is read off the first group, which carries the
    whole walk's, exactly as ``independent_frontier`` documents.

    Every owed line is :func:`owed_line`'s, so the planner's hint, the
    compiled view's OWED section and the supervisor's stall sentence quote
    one another word for word.  *resolvers* travels for the same reason it
    travels there.
    """
    if len(groups) < 2:
        return ""
    shown = [group for group in groups[:max(1, int(max_groups))] if group]
    if len(shown) < 2:
        return ""
    lines = [STEERING_TITLE, STEERING_SENTENCE]
    for number, group in enumerate(shown, start=1):
        lines.append(STEERING_GROUP.format(number=number))
        kept = list(group)[:max(1, int(max_lines))]
        lines.extend(f"  {owed_line(item, resolvers)}" for item in kept)
        if len(group) > len(kept):
            lines.append("  " + STEERING_MORE.format(
                count=len(group) - len(kept)))
    if len(groups) > len(shown):
        lines.append(STEERING_OVERFLOW.format(count=len(groups) - len(shown)))
    if getattr(groups[0], "truncated", False):
        lines.append(STEERING_CAPPED)
    return "\n".join(lines)


def violation_line(violation: Violation) -> str:
    """One constraint violation as one CONFLICTS line.

    ``constraint: share_bounded — mcp.ledger#r3  ⇄  share 121.2 > 100``: the
    same shape as :func:`_conflict_line` — a kind, then the two sides across
    :data:`SIDE_SEP` — because a reader of this section should not have to
    learn a second grammar to read one of its lines.  The kind is
    :data:`~core.cognition.constraints.VIOLATION_KIND`, which is the one
    owner of that word.

    The two sides are *what was constrained* and *what the store says*.  The
    **required expression is not on the line**, and that is the budget
    argument the whole block runs on: the constraint's name is its address in
    the manifest, the detail already states what is true, and the expression
    is on the record in ``reasoning.jsonl`` for a reader who wants to read the
    two side by side.  A line that carried all three would be a third longer
    and would say nothing the first two do not.

    **Public, and the one owner of this spelling**, for
    :func:`owed_line`'s reason: the day something else renders a violation —
    a console line, a report — it renders the line the model reads.
    """
    return (f"{VIOLATION_KIND}: {violation.constraint} — "
            f"{violation.entity}{SIDE_SEP}{violation.detail}")


@dataclass(frozen=True)
class RelatedEdge:
    """One edge of a working set, as this module needs to render it.

    **Declared here rather than imported**, and it is not a preference.
    :mod:`core.cognition.graph` is a *sibling* package that imports this
    one's :mod:`~core.cognition.events` and :mod:`~core.cognition.types`; a
    compiler that imported :class:`~core.cognition.graph.store.Edge` would
    close that loop through :mod:`core.cognition`'s own facade, which
    imports this module — an import cycle, and, underneath it, the wall the
    package docstring states in one line: *nothing in the kernel imports the
    graph*.  So the runtime, which holds both, hands over four fields, in
    exactly the way it hands over ``resolvers`` for the same reason
    (:func:`_resolvable` argues that one at length).  This is not a second
    owner of an edge: nothing here is stored, compared or walked — it is the
    shape of a line.

    ``authority`` is the kernel's enum, because it is the kernel's enum in
    the graph too: an edge carries where it came from, every read that
    returns one returns it, and a rendering that dropped it would be the one
    place in this block where a reader could not tell a reference from a
    guess.  ``None`` renders as :data:`UNGRADED`, which is
    :func:`band`'s rule and not a new one.
    """

    src: str
    relation: str
    dst: str
    authority: Optional[EvidenceAuthority] = None


def related_line(edge: RelatedEdge) -> str:
    """One edge as one RELATED line.  **The one owner of this spelling.**

    ``related: mcp.job_status#r5 —about→ job:jl-731  [sourced]``

    Both ends go through :func:`_entity`, the same escape every fact line
    uses, and for the same reason it exists: a subject whose value carries a
    confusable renders as a line visually identical to another subject's,
    and a reader deciding *which* thing to look at next on a line of pure
    identity has nothing else to go on.

    **A line of state, like every other line in this block.**  It says two
    names are connected and on whose word; it does not say to follow the
    edge, and nothing in the runtime does either.  The owner's ruling of 13
    September 2026 binds here as it binds on :func:`owed_line`: the
    cognitive layer reports, and a line in the imperative is the layer
    steering with a verb.
    """
    return (f"{RELATED}{_entity(edge.src)}"
            f"{RELATED_ARROW.format(relation=edge.relation)}"
            f"{_entity(edge.dst)}  [{band(edge.authority)}]")


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
    #: Facts, conflicts, owed lines, hypotheses and related lines
    #: **rendered**.  ``owed``
    #: counts LINES and not obligations, so :data:`FRONTIER_CAPPED` is one
    #: of them: it is a line about what is owed, it costs the budget like
    #: one, and a counter that skipped it would disagree with the omission
    #: sentence about how many lines the section lost.  ``conflicts`` counts
    #: the section's lines for the same reason, so a constraint violation
    #: rendered into it is one of them, and so is :data:`RELATED_CAPPED` in
    #: ``related``.
    facts: int = 0
    conflicts: int = 0
    owed: int = 0
    hypotheses: int = 0
    related: int = 0
    #: And the same five, **dropped** for the budget.
    #:
    #: **Five, and no sixth pair for violations**, although the omission
    #: sentence does tell them apart inside the conflicts count.  The counters
    #: here are the *sections*, one spelling shared with :data:`SECTIONS`, and
    #: a sixth pair that was not a section would be the shape this class is
    #: arranged to avoid (``test_and_the_view_carries_the_same_five_twice_over``
    #: states it).  A caller that wants to know how many of its violations
    #: were dropped passed them in and can say ``min(conflicts_omitted,
    #: len(violations))`` — which is exactly what the renderer does.
    facts_omitted: int = 0
    conflicts_omitted: int = 0
    owed_omitted: int = 0
    hypotheses_omitted: int = 0
    related_omitted: int = 0

    def __bool__(self) -> bool:
        return bool(self.text)

    @property
    def truncated(self) -> bool:
        """Whether the budget dropped anything at all."""
        return bool(self.facts_omitted or self.conflicts_omitted
                    or self.owed_omitted or self.hypotheses_omitted
                    or self.related_omitted)

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
    related: int = 0
    facts_out: int = 0
    conflicts_out: int = 0
    owed_out: int = 0
    hypotheses_out: int = 0
    related_out: int = 0

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


def _violations_lost(cut: "_Cut", violations: int) -> int:
    """How many of the dropped conflict lines were violations.  One owner.

    Violations are last in the CONFLICTS section and a section loses its
    lines from the end, so the dropped ones are the violations first.  Both
    the measurer and the renderer ask this, because a sentence measured under
    one answer and rendered under another is a block one clause over its cap.
    """
    return min(cut.conflicts_out, int(violations))


def _size(cut: _Cut, prefixes: Sequence[Sequence[int]],
          receipts: Sequence[int], violations: int = 0) -> int:
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
    sentence = _omission(cut.out, _violations_lost(cut, violations))
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
            receipts: Sequence[int], violations: int = 0) -> Optional[_Cut]:
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
    if _size(nothing, prefixes, receipts, violations) <= budget:
        return nothing
    for dropped in range(max(1, _floor(budget, totals, prefixes)),
                         lines + 1):
        cut = _cut_at(dropped, totals)
        if _size(cut, prefixes, receipts, violations) <= budget:
            return cut
    return None


@dataclass(frozen=True)
class _Folding:
    """What the subject spine does to one block's fact lines.

    Three readings of one walk, kept together because they are one fact
    about each claim and three parallel dicts is the shape where a line is
    folded away by one of them and still counted by another.
    """

    #: ``{subject claim: the receipt handles its line names}``.
    handles: Mapping[str, Tuple[str, ...]]
    #: ``{subject claim: the receipt FACTS it was projected from}`` — the
    #: claims whose evidence is the receipt evidence, which is what the
    #: header counts rather than the projection's own leaves (a link's
    #: declaration is a leaf of the proof and is not a receipt).
    premises: Mapping[str, Tuple[str, ...]]
    #: Receipt facts whose line the subject's line replaces.
    hidden: frozenset


def _folding(state: CognitiveState, live: Sequence[Proposition],
             support: Mapping[str, Support]) -> _Folding:
    """What folds into what, for one block's live claims.

    **The subject spine, in the one place a reader meets it.**  A link says
    a receipt is about a subject and the kernel projects the receipt's
    facts onto it, so the store now holds one figure twice: once where it
    was read (``mcp.job_status#r5 · state = "completed"``) and once about
    the thing it is about (``job:jl-731 · state = "completed"``).  Printing
    both would pay the budget twice for one figure and would teach a reader
    that the store believes two things.  So the subject line is printed —
    it is the one a rule joins on, a cardinality contests at, and a goal is
    about — with the receipt handle folded into it, and the receipt's own
    line goes.

    Two bounds, each one a case where folding would lose something a line
    was carrying:

    * **a disputed receipt fact is never folded away.**  Its line carries
      :data:`DISPUTED` because something contradicts *it*, and the subject
      copy need not be contested at all (a model's hypothesis against one
      receipt does not reach the projection).  The subject line still names
      the receipt; the receipt's line still says it is disputed;
    * **nothing is folded that the line cannot name** — more than
      :data:`VIA_CAP` receipts agreeing on one subject fact keeps every
      receipt line, because the replacement would be naming three of them
      and silently standing for twenty.

    What folding *does* cost, stated rather than discovered: the subject
    line is now the only line for that figure, so a budget that cuts it
    cuts both.  The escape is unchanged and is the one the block already
    prints — the handle is on the line, and the result store holds the
    receipt whole — and the alternative (print both, cut the receipt line
    first) spends the budget twice on every linked figure a mission holds.

    **And what it costs to compute**, beside the module docstring's
    numbers: one :meth:`~core.cognition.state.CognitiveState
    .derivations_for` lookup per live claim and one
    :meth:`~core.cognition.state.CognitiveState.proposition` per
    projection premise — dictionary reads, no second DAG walk and no
    second render.  It is dominated by the ``support`` pass that was
    already there, and a store with no links pays for the lookup and
    nothing else.
    """
    handles: Dict[str, Tuple[str, ...]] = {}
    premises: Dict[str, Tuple[str, ...]] = {}
    folded: set = set()
    shown = {prop.id for prop in live}
    for prop in live:
        projection = _via(state, prop)
        if projection.premises:
            # The header counts through every premise — a derived one
            # included, whose own leaves are the receipts under its proof.
            premises[prop.id] = projection.premises
        names = projection.handles
        if not names:
            continue
        handles[prop.id] = names
        if len(names) > VIA_CAP:
            continue
        for pid in projection.facts:
            grade = support.get(pid)
            if pid not in shown or grade is None:
                continue
            if grade.contested_by or grade.hypothesis:
                continue
            folded.add(pid)
    return _Folding(handles=handles, premises=premises,
                    hidden=frozenset(folded))


def compile_view(state: CognitiveState, *,
                 budget_chars: int = BUDGET_CHARS,
                 violations: Sequence[Violation] = (),
                 resolvers: Optional[Mapping[str, Sequence[str]]] = None,
                 related: Sequence[RelatedEdge] = (),
                 related_capped: bool = False,
                 ) -> CompiledView:
    """*state* as one block of at most *budget_chars* characters.

    Deterministic: the same state compiles to the same bytes, every time,
    in any process.  The only inputs are the store, the budget and the
    violations the caller checked.

    *violations* is a **parameter and not a read**, which is the honest
    shape while the store has no door to record one through: they are
    computed by :func:`core.cognition.constraints.check_constraints` against
    this same state, and the caller that ran the check is the caller that
    holds them.  Defaulting to nothing is what keeps every existing caller —
    and the recorded corpus — byte for byte what it was.

    *related* is a parameter for a stronger version of the same reason: the
    edges are in a **sibling package this one does not import** (see
    :class:`RelatedEdge`), they are chosen by a walk whose bounds are that
    package's (:func:`core.cognition.graph.harvest.working_set`), and the
    runtime that holds both hands the result over.  *related_capped* is that
    walk's own truncation flag, rendered as :data:`RELATED_CAPPED` — it is
    not the budget's cap and not the frontier's, and the three say three
    different things.  Both default to nothing, so a run without
    ``--graph-context`` compiles the bytes it compiled before this section
    existed, and the corpus is the proof.

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
    owed_lines = [owed_line(item, resolvers) for item in frontier]
    if frontier.truncated and owed_lines:
        # The note is about lines there are more of, so it needs one. A
        # walk that stopped at the cap having resolved everything it
        # reached leaves nothing owed, and "+ more owed than these" over
        # no rows is a heading over nothing twice over: it announces a
        # section the block is not showing and claims a frontier the run
        # does not have. No lines, no section — the same rule the other
        # three keep.
        owed_lines.insert(0, FRONTIER_CAPPED)
    # The violations the caller checked, after the store's own conflicts:
    # the budget drops a section from the end, so a pack's arithmetic goes
    # before a disagreement the kernel itself recorded.
    clash_rows = [violation_line(item) for item in (violations or ())]
    # The working set the caller hydrated, with its own cap note first — the
    # same "flag first, and only over rows" rule the frontier's note keeps,
    # and for the same two reasons: a section loses its lines from the end,
    # so the flag is the last of them to go, and a note about more than
    # these over nothing at all is a heading over nothing twice over.
    related_lines = [related_line(edge) for edge in (related or ())]
    if related_capped and related_lines:
        related_lines.insert(0, RELATED_CAPPED)
    if not (live or guesses or open_clashes or owed_lines or clash_rows
            or related_lines):
        return CompiledView()

    support = _supports(state, live)
    # One figure, one line: a receipt fact whose subject copy is shown is
    # folded into that line with its handle on it — see `_folding`, which
    # owns both halves of that decision.
    folding = _folding(state, live, support)
    visible = [prop for prop in live if prop.id not in folding.hidden]
    by_entity: Dict[str, List[Proposition]] = {}
    for prop in visible:
        by_entity.setdefault(prop.entity or "", []).append(prop)
    ordered = [prop for entity in _entity_order(visible)
               for prop in by_entity[entity]]
    fact_lines = [_fact_line(prop, support[prop.id],
                             folding.handles.get(prop.id, ()))
                  for prop in ordered]
    # Beside each fact line, the receipts that fact rests on — so that the
    # header can count the receipts of the facts it is ABOUT. Counting all
    # of them there would state two numbers over two different populations
    # in one sentence, and the reader has no way to see which.
    clash_lines = [_conflict_line(state, clash)
                   for clash in open_clashes] + clash_rows
    guess_lines = [f"{_claim(prop)}  [{band(prop.authority)}]"
                   for prop in guesses]

    # How many distinct receipts the first n fact lines rest on, for every
    # n: the header's figure, at any cut, for a lookup. Built once here
    # because the scan below asks for it per candidate and a re-union per
    # candidate is the quadratic shape this whole function stopped having.
    receipts, seen = [0], set()
    for prop in ordered:
        # A projected claim is counted by the RECEIPT FACTS it projects,
        # not by its own leaves. Both are correct answers to different
        # questions: the leaves of a subject fact include the link's
        # declaration — which is why the store believes two receipts are
        # about one thing, and is emphatically not a receipt — and the
        # header's word is `receipts`. Counting the leaves would have made
        # a plane's declaration file show up in this block as a call the
        # mission made.
        for pid in folding.premises.get(prop.id, ()) or (prop.id,):
            grade = support.get(pid)
            if grade is not None:
                seen.update(ref.locator for ref in grade.evidence_leaves)
        receipts.append(len(seen))

    sections = (fact_lines, clash_lines, owed_lines, guess_lines,
                related_lines)
    totals = tuple(len(lines) for lines in sections)
    prefixes = tuple(_prefix(lines) for lines in sections)

    cut = _choose(budget, totals, prefixes, receipts, len(clash_rows))
    if cut is None:
        # Not even the header and the sentence saying what went will fit.
        # An empty view, not an over-budget one — a cap that is exceeded to
        # apologise for itself is not a cap.
        return CompiledView()
    lost_rows = _violations_lost(cut, len(clash_rows))
    text = _render([lines[:kept] for lines, kept in zip(sections, cut.kept)],
                   receipts[cut.facts], cut.out, lost_rows)
    if len(text) > budget:
        # The arithmetic and the renderer disagreed, which is the one thing
        # a second reader of a shape can do wrong. No block, rather than a
        # block over the cap somebody set.
        return CompiledView()
    return CompiledView(
        text=text, receipts=receipts[cut.facts],
        facts=cut.facts, conflicts=cut.conflicts, owed=cut.owed,
        hypotheses=cut.hypotheses, related=cut.related,
        facts_omitted=cut.facts_out, conflicts_omitted=cut.conflicts_out,
        owed_omitted=cut.owed_out, hypotheses_omitted=cut.hypotheses_out,
        related_omitted=cut.related_out,
    )


def _conflict_line(state: CognitiveState, clash: Any) -> str:
    """One open contradiction, **both sides named**.

    ``right`` is ``None`` only for a refutation, where the other side is
    not a claim in the store but the evidence somebody refuted it with, and
    the detail is what says so.  Every other kind names two propositions
    and both of them are rendered with their handles — the rule this
    section exists for.

    **A contest at a subject names the call behind each side.**  That is
    the whole point of the subject spine on this section: two status tools
    disagreeing about one job collide at ``job:jl-731``, so both sides of
    the line are that same entity and a reader without the handles is
    looking at ``x ⇄ x``.  Through :func:`_via_mark`, the same spelling a
    folded fact line uses, because it is the same fact — which call said
    this — and two spellings of it is the one a reader learns and the one
    they misread.
    """
    left = _sided(state, clash.left)
    if clash.right is None:
        other = f"refuted — {clash.detail}" if clash.detail else "refuted"
    else:
        other = _sided(state, clash.right)
    return f"{clash.kind}: {left}{SIDE_SEP}{other}"


def _sided(state: CognitiveState, pid: str) -> str:
    """One side of a conflict: the claim, and the call behind it if any.

    Through :func:`_via`, so the un-derived rule holds here too: a side
    the store *concluded* names no call, because no call said it.
    """
    prop = state.proposition(pid)
    handles = _via(state, prop).handles
    text = _claim(prop)
    return f"{text}  [{_via_mark(handles)}]" if handles else text


def _head(receipts: int, facts: int, clashes: int) -> str:
    """The header line.  One owner, because :func:`_size` measures it."""
    return (f"{TITLE} — compiled from {_plural(receipts, 'receipts')}, "
            f"{_plural(facts, 'facts')}, "
            f"{_plural(clashes, 'conflicts')}.")


def _omission(dropped: Sequence[int], violations: int = 0) -> str:
    """The sentence a dropped line leaves behind, or ``""``.  One owner.

    *dropped* is per section, in :data:`SECTIONS` order — so the sentence
    names its losses in the order the block renders them, not in the order
    it lost them.  *violations* is how many of the dropped **conflict** lines
    were constraint violations rather than contradictions the store recorded;
    they are last in that section and a section loses its lines from the end,
    so they are also the first of it to go.

    **Four clauses and not one**, on one line, because four kinds of loss
    have four different truths: what came off a receipt is still in the
    result store (:data:`OMITTED`), an owed line is in no store at all
    (:data:`OWED_OMITTED`), a violation is computed rather than stored
    (:data:`VIOLATIONS_OMITTED`), and a related line is hydrated from the
    frontier every step (:data:`RELATED_OMITTED`).  Each clause appears only
    when something it is true of was dropped, so a block that lost only owed
    lines never points at a store, a block that lost no violations reads
    exactly as it did before they existed, and no sentence ever sends a model
    to look for something that was never there.
    """
    # The violations come OUT of the conflicts count in place, so the losses
    # stay in `SECTIONS` order: the sentence names them in the order the
    # block renders them, which is a property a reader depends on and a
    # re-ordering would quietly take away.
    lost = [(count - (violations if kind == "conflicts" else 0), kind)
            for count, kind in zip(dropped, SECTIONS)]
    # `stored` is what the result store really holds — so `owed` and
    # `related` are named out of it rather than filtered by a `!=` chain
    # somebody would add a section to and forget: a kind that is not in one
    # of the three lists below is a kind nothing says anything about, which
    # is louder than a kind quietly pointed at the wrong place.
    computed = ("owed", "related")
    stored = [f"+{_plural(count, kind)}"
              for count, kind in lost if count > 0 and kind not in computed]
    owed = [f"+{_plural(count, kind)}"
            for count, kind in lost if count > 0 and kind == "owed"]
    related = [f"+{_plural(count, kind)}"
               for count, kind in lost if count > 0 and kind == "related"]
    clauses = []
    if stored:
        clauses.append(OMITTED.format(what=", ".join(stored)))
    if owed:
        clauses.append(OWED_OMITTED.format(what=", ".join(owed)))
    if violations:
        clauses.append(VIOLATIONS_OMITTED.format(
            what=f"+{_plural(violations, 'violations')}"))
    if related:
        clauses.append(RELATED_OMITTED.format(what=", ".join(related)))
    return " ".join(clauses)


def _render(sections: Sequence[Sequence[str]], receipts: int,
            dropped: Sequence[int], violations: int = 0) -> str:
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
    sentence = _omission(dropped, violations)
    if sentence:
        out.append("")
        out.append(sentence)
    return "\n".join(out)
