# core/eval/extraction.py — can this model turn a receipt into propositions?

"""``python -m core.eval extraction`` — Phase 16's gatekeeper, as a number.

ROADMAP §2.9.3 puts one measurement in front of the whole 1.0→2.0 cognitive
arc, and this module is it: *take real receipts from the replay corpus, ask
the target model for propositions with abstention, and score them.*  Nothing
in Phases 17–21 begins until that number exists, because everything in them
derives from an epistemic store with deterministic machinery, and **a wrong
proposition in a store is worse than a wrong sentence in a transcript** — a
sentence is read by a person who can disbelieve it, and a proposition is
joined, closed over and cited by code that cannot.

So the question this subcommand answers is narrow and prior to all the rest:
handed one genuine tool receipt and one question, does the model produce
typed propositions that are (a) parseable, (b) *grounded* — the value it
asserts is in the receipt, under the field it names, quoted from a span that
is really there — and (c) **abstaining where the receipt is silent**.  The
third is the one that decides the phase order.  A model that asserts
confidently where there is nothing to assert does not become safe by having
its output typed; it becomes harder to catch, because the type says a fact
was extracted.

**Why this is not another eval framework.**  ROADMAP §2.9.3 says *"on the
existing core/eval machinery — no second eval framework"*, and the seams
here are the package's own:

* the **backend** is :class:`core.unified_client.UnifiedClient`, the same
  door :func:`core.eval.measure.probe_capabilities` opens — one place where
  a provider name becomes a backend, or the matrix and this measurement
  could be run against two different endpoints while naming one;
* the **header** is :func:`core.eval.measure.header`'s vocabulary, scrubbed
  by :func:`core.eval.measure.scrubbed` and stamped with
  :func:`core.eval.measure.commit_of`;
* the **evidence walk** is :func:`core.runtime.grounding.harvest_fields` and
  :func:`core.runtime.grounding.json_blocks`, and the value comparison is
  :func:`core.runtime.grounding.same_value` over
  :func:`core.runtime.grounding.plain_figure`.  A second JSON harvester here
  would be the six-of-ten-fields defect one layer down: this measurement
  would disagree with the grounding check it exists to predict, and nobody
  reading either number would know which.

**Why the interval, and why the identity beside it.**  The 1.0.0 final gate
measured a 20-scenario tier at a 20B landing 14–16 and taught the lesson in
one sentence: *a number without its interpreter beside it is not evidence*.
Every rate this module prints therefore carries ``k/n`` and a 95% Wilson
interval, and every table carries the provider, the model, the temperature,
the endpoint, the commit and the SHA of the prompt that produced it.  The
prompt is part of the interpreter: changing it changes the number, and a
report that did not say which prompt ran could be compared with one that
ran a different one.

**The instrument measures a spectrum and never collapses it.**  The standing
design rule for this module, and the one that shapes every column below:
there are five things an extractor can do with a fact — be **confidently
right**, **hedged right**, **hedged wrong**, **confidently wrong**, or
**silent** — and each is reported as itself.  A pass/fail is taken only where
one column genuinely needs one, and never further.

Four consequences, each of them a correction to an earlier and worse version
of this file:

* **Marking confidence is not the same as being wrong, and is not scored as
  if it were.**  A model that says ``HYPOTHESIZE`` over a trap field has done
  something different from one that ``ASSERT``s it: the first published its
  uncertainty and the second published a fact.  Both are wrong about the
  world; only one of them is wrong in a way a downstream store will act on.
  So :data:`CATEGORIES` carries ``hedged`` beside ``trap``, in its own column
  with its own interval, and it is deliberately **not** folded into the
  headline.  *Mark confidence, don't punish it.*
* **Silence is not the only right answer to a conflict.**  Where two receipts
  disagree, an extractor that surfaces **both** sides, each tied to its own
  source, has served the reader better than one that says nothing — and much
  better than one that quietly picks a winner, which is the real failure.
  See :func:`both_sides_surfaced` and the ``conflict_surfaced`` rate.
* **Transcribing a mask is honest.**  Where a receipt says a value is
  ``"masked"``, an extractor that asserts *that* — the receipt's own token,
  under the receipt's own key — has reported exactly what is there.  The
  fabrication would be a concrete number in its place.  See
  :attr:`Attempt.mask_faithful`.
* **The headline under repeats is per PROBE, not per attempt.**  A
  gatekeeper is a question about reliability, so with ``--repeats N`` the
  number to quote is ``probe_reliable``: probes where *every* attempt was
  right.  No majority voting — a store fed by a model that is right two
  times in three is a store with a third of its propositions wrong.

The reason is not generosity, it is measurement.  A gate is a deployment's
dial; an instrument that scored only silence as safe would teach silence, and
a harness that returns *no result* too often returns no finding either.  A
non-perfect answer beats a perfect nothing.

**The baseline is the plain ask, and the lift is a flag beside it.**  No
few-shot examples, and no constrained decoding *by default*: §2.9.3 names
both as the lift to try if the number is bad, and a baseline that already
had them would have nothing to be measured against.  §2.9.5's half of that
has now landed as ``--constrained`` — :func:`proposition_schema` compiles
this module's own reply language into a JSON schema and
:attr:`core.runtime.backends.base.BackendCapabilities.supports_json_schema`
is the door it goes through — and it is **off unless asked for**, refused
up front on a backend that cannot enforce it, and stamped into the report's
identity and prompt fingerprint so the A/B is two experiments and not one
number moving.  One reprompt is allowed either way, because a structurally
invalid reply is a failure class whose **repair rate** is itself part of the
finding, and it is counted and printed rather than folded into the success —
a schema-shaped reply can still be wrong about the receipt, and repair is
about content.

The probe corpus is data and lives in ``tests/fixtures/extraction``; this
module names no probe, no tool and no deployment.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import os
import sys
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import (Any, Callable, Dict, List, Mapping, Optional, Sequence,
                    Tuple)

from core.durable import atomic_write_text
from core.runtime.grounding import (as_decimal, harvest_fields, json_blocks,
                                    plain_figure, same_value)

__all__ = [
    "ASSERT", "CONTRADICTED", "HEDGING", "STATUSES", "KINDS", "FAMILIES",
    "CATEGORIES", "FIRST", "REPAIRED", "INVALID",
    "PROPOSITION_FIELDS", "PROPOSITION_KEYS", "SCHEMA_NAME",
    "SCHEMA_ROOT_KEY", "CONSTRAINED_YET_INVALID", "proposition_schema",
    "Evidence", "Probe", "ProbeMisdeclared", "Proposition", "Attempt", "Rate",
    "ExtractionReport", "Unextractable",
    "PROMPT", "REPAIR", "prompt_for", "repair_for", "prompt_fingerprint",
    "load_probes", "parse_propositions", "grounds", "both_sides_surfaced",
    "score_attempt", "rates_of", "wilson", "run_probes", "asker", "header",
    "report_stem", "add_parser", "from_args",
]


# ── the vocabulary ───────────────────────────────────────────────────────────

#: The one status that is a claim about the world.  Everything else in
#: :data:`STATUSES` is a way of not making one, and the difference is the
#: whole measurement: a store may take an ``ASSERT`` and derive from it.
ASSERT = "ASSERT"

#: The status for *this receipt disagrees with that one*.  Named because two
#: things read it: the contradiction rule in :func:`both_sides_surfaced`, and
#: the prompt, which asks for a proposition per side rather than a winner.
CONTRADICTED = "CONTRADICTED"

#: The two ways to put a fact on the record **with its uncertainty marked**.
#: Everything in this module that distinguishes hedged wrongness from
#: confident wrongness reads this tuple, so the distinction has one owner —
#: see ``hedged`` in :data:`CATEGORIES`.
HEDGING: Tuple[str, ...] = ("HYPOTHESIZE", "AMBIGUOUS")

#: The one way to say *nothing here answers this*.
INSUFFICIENT = "INSUFFICIENT_EVIDENCE"

#: The status vocabulary ROADMAP §2.9.3 names, in the order the prompt
#: offers them.  A reply using a word that is not here is a **structural**
#: failure and not a wrong answer: a downstream store would not know what
#: to do with it, which is a different defect from knowing and being wrong.
STATUSES: Tuple[str, ...] = (ASSERT, *HEDGING, CONTRADICTED, INSUFFICIENT)

#: The three things a probe can expect.  ``assert`` — the facts are in the
#: receipt.  ``abstain`` — they are not, and the correct extractor says so
#: (or, where the probe declares an alternative, does the better thing).
#: ``trap`` — they are, and beside them sits a plausible-but-wrong field
#: that a model reaching for the shape of an answer takes instead.
KINDS: Tuple[str, ...] = ("assert", "abstain", "trap")

#: The measured failure taxonomy: family → the kind it must be written as,
#: and why that family is in the corpus.  Data rather than prose, because
#: the report breaks the rates down by it and §2.9.3's go/no-go is a
#: statement about *which class* fails — "the extraction number was 0.61"
#: does not tell anyone whether to move Phase 21 forward, and "it abstains
#: fine and falls for every unit trap" does.
FAMILIES: Mapping[str, Tuple[str, str]] = {
    "present": (
        "assert",
        "the fact is in the receipt under a key of its own; the extractor "
        "has only to copy it without deriving anything"),
    "absent": (
        "abstain",
        "the receipt carries no key for the fact asked about — the plain "
        "abstention case, and the floor for every other one"),
    "contradiction": (
        "abstain",
        "two receipts about one subject disagree; asserting ONE side alone, "
        "as if uncontested, is the failure — surfacing both, each tied to "
        "its own source, passes and is the better answer. Measured live on "
        "a deployment 6 Sep 2026 (one status tool says the id is unknown, "
        "another says it completed)"),
    "masked": (
        "abstain",
        "the record exists and its material is withheld by handling. Two "
        "right answers: say nothing, or transcribe the receipt's own mask "
        "token faithfully under the key that holds it. The failure is a "
        "concrete value — a zero, a count — where the receipt published a "
        "mask"),
    "cause_absent": (
        "abstain",
        "a failure receipt that explicitly establishes no cause; asking "
        "WHY invites one to be invented"),
    "partial_coverage": (
        "abstain",
        "the receipt says its own search was partial, so an empty result "
        "is not an absence — asserting one is the coverage caveat being "
        "read past"),
    "unit_semantics": (
        "trap",
        "a field whose NAME reads like the question and whose meaning is "
        "something else — the recorded `total_s`, elapsed seconds, served "
        "as a total score (tests/fixtures/field_misreadings.json)"),
    "optional_filter": (
        "trap",
        "a question about a record's own state, asked of a receipt that "
        "also carries an optional descriptive field whose value reads like "
        "an answer — `submitted_via: \"unknown\"` beside `state`, `mode` "
        "beside `stage`. What these probes measure is whether the "
        "plausible-wrong field is asserted in place of the real one. The "
        "family is named for what MOTIVATED it, which is a different "
        "defect one layer up: a 20b filled that same optional field as a "
        "query FILTER on 8 of 8 attempts and hid the rows it was looking "
        "for. Nothing here measures filling a filter — these are receipts, "
        "not calls"),
}

#: Every key a probe's ``expect`` block may carry.  Module level because the
#: loader reads it to refuse a key nobody implemented — a probe declaring
#: ``trap_field`` (singular) would otherwise be scored as a probe with no
#: trap at all, and read as a model that never falls for one.
EXPECT_KEYS = frozenset({
    "kind", "gold", "trap_fields", "absent_fields", "sides", "mask_tokens",
})


class ProbeMisdeclared(ValueError):
    """A probe file this module refuses to measure anything with.

    Loud rather than skipped, for :class:`core.eval.suite.Mission`'s
    reason: a probe whose gold is not in its own evidence would score every
    correct extractor as a fabricator, and the number would be about the
    corpus.
    """


class Unextractable(RuntimeError):
    """There is no number to print, and the reason is not the model.

    Raised rather than scored — an endpoint that fell over halfway is not a
    model that abstained, and recording its silence as an abstention is the
    one way this measurement could flatter a model by breaking.  Also the
    wall budget: a run cut short is a partial sample, not a low score.
    """


# ── the evidence ─────────────────────────────────────────────────────────────

def _squashed(text: Any) -> str:
    """*text* with every run of whitespace collapsed to one space.

    Applied to both sides of the quote check.  A quote is supposed to be a
    **copy of a span**, and this is the one difference from a copy that is
    not a change of content: a model re-indenting a JSON fragment it is
    quoting has quoted it.  Anything else — a word swapped, a digit moved,
    a span that is not in the receipt at all — still fails.
    """
    return " ".join(str(text).split())


def _text_key(value: Any) -> str:
    """A scalar as one comparable string.

    Case-folded always, because a status word re-cased is the same fact and
    a measurement that counted ``Pass`` against ``pass`` would be measuring
    capitalisation.

    :func:`core.runtime.grounding.plain_figure`'s separators are stripped
    **only from something that is then a number**.  ``12,481`` and ``12481``
    are one figure and a measurement of fabrication must not report a
    thousands separator — but the same stripping applied to words makes
    ``job_not_found``, ``jobnotfound`` and ``job not found`` one string,
    and they are three different values.  One of them is the receipt's;
    the other two are not, and a comparison that could not tell them apart
    would ground a fabricated status word against a real one.  The test is
    the strip, not the guess: strip, ask whether what is left parses as a
    decimal, and keep the stripping only if it does.
    """
    text = str(value).strip()
    stripped = plain_figure(text)
    if stripped and as_decimal(stripped) is not None:
        return stripped.casefold()
    return text.casefold()


@dataclass(frozen=True)
class Evidence:
    """One probe's receipt, walked once.

    A bundle rather than three loose arguments because every check that
    reads a receipt needs all three — the field names, the scalars under
    them, and the raw text the quote rule is checked against — and a
    function that took two of them would be a function that could not
    enforce the third.
    """

    #: The receipt verbatim, as the tool recorded it.
    text: str
    #: Every mapping key anywhere in it.
    keys: frozenset
    #: Key → every scalar seen under it, in encounter order.
    scalars: Mapping[str, Tuple[Any, ...]]

    @classmethod
    def of(cls, text: str) -> "Evidence":
        """Walk *text* once.

        One walker, and it is not this module's:
        :func:`core.runtime.grounding.json_blocks` parses and
        :func:`core.runtime.grounding.harvest_fields` walks, with its
        ``scalars`` sink so a string value — a status word, an outcome, a
        handle — comes back as well as a figure.  See that function: the
        second reader it was promoted for is this one.
        """
        keys: set = set()
        numbers: dict = {}
        scalars: Dict[str, List[Any]] = {}
        for payload in json_blocks(text):
            try:
                harvest_fields(payload, keys, numbers, scalars=scalars)
            except RecursionError:               # pragma: no cover - guard
                continue
        return cls(text=str(text), keys=frozenset(keys),
                   scalars={name: tuple(values)
                            for name, values in scalars.items()})

    def quotes(self, quote: str) -> bool:
        """Whether *quote* is really a span of this receipt."""
        quote = _squashed(quote)
        return bool(quote) and quote in _squashed(self.text)

    def holds(self, field: str, value: Any) -> bool:
        """Whether some scalar under *field* is *value*.

        **Any record under that key, not a particular one.**  A listing of
        three jobs puts three ``state`` values in one bucket, so this
        answers *the receipt has this value under this key somewhere* and
        not *this row has it*.  Stated rather than hidden: a probe whose
        correct answer depends on which row a value came from is a probe
        this check cannot grade, and the corpus does not contain one.
        """
        name = str(field).strip()
        if not name or name not in self.keys:
            return False
        found = self.scalars.get(name)
        if not found:
            # The key is real and holds an object or a list. The value
            # beside it cannot be confirmed from a scalar, and an
            # unconfirmable assertion is not a grounded one — the
            # difference from `FieldAttributionCheck`, which must not
            # ACCUSE on that evidence where this must not COUNT it.
            return False
        return any(_same_scalar(value, seen) for seen in found)


def _same_scalar(claimed: Any, found: Any) -> bool:
    """Whether a model's value is the value the payload holds.

    **A string in the payload is compared as a string.**  That ordering is
    the rule, and it is there for two recorded shapes:
    :func:`core.runtime.grounding.as_decimal` parses ``"007"`` as seven, so
    a numeric-first comparison would ground a claimed ``7`` against an
    identifier the payload spells ``"007"``; and it parses ``"nan"`` as a
    decimal NaN, which is not equal to itself, so a numeric-first
    comparison would report a faithfully copied ``"nan"`` as fabricated.

    Where the payload holds a number, :func:`core.runtime.grounding
    .same_value` answers — ``338`` and ``338.0`` are one out-weight — and
    the text form is accepted beside it so ``12,481`` matches ``12481``.
    """
    if isinstance(found, str):
        return _text_key(claimed) == _text_key(found)
    return same_value(claimed, found) or _text_key(claimed) == _text_key(found)


def grounds(proposition: "Proposition", evidence: Evidence) -> bool:
    """Whether the receipt supports *proposition*, all three ways.

    **The quote must be a real span.**  Global since the review of the
    first draft, and load-bearing: a proposition carries the span it was
    read off precisely so a reader can check it, and a quote that is not in
    the receipt is a citation to nothing.  It is also what makes the
    contradiction rule mean anything — two assertions of opposite values
    are two sources only if each one's quote came out of the receipt.

    **The field must exist, and must hold the value.**  A large receipt
    answers "is this number in here" yes for a great many numbers; what a
    downstream store joins on is the LABEL, and an extraction that put a
    real value under the wrong key has produced a proposition that is wrong
    in exactly the way nothing later can catch.  Weakening this to "the
    value is somewhere in the evidence" is the mutation this check exists
    to fail.
    """
    if not evidence.quotes(proposition.quote):
        return False
    return evidence.holds(proposition.field, proposition.value)


# ── the probe ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Probe:
    """One receipt, one question, and what a correct extractor answers."""

    #: Unique in the file; the row name in every table and the key a
    #: baseline is paired against.
    id: str
    #: One of :data:`FAMILIES`.
    family: str
    #: Where the receipt came from, so a reader can go and look at it.
    source: str
    #: The receipt, verbatim, as a tool recorded it.
    evidence: str
    #: What is being asked of it.
    question: str
    #: One of :data:`KINDS`; derived from *family* and checked against the
    #: file's own declaration, so the two cannot drift.
    kind: str
    #: ``(field, value)`` pairs a correct extractor ASSERTs, and nothing
    #: else.  Empty on an ``abstain`` probe.
    gold: Tuple[Tuple[str, Any], ...] = ()
    #: The plausible-but-wrong fields this probe exists to count.
    trap_fields: Tuple[str, ...] = ()
    #: On an ``absent`` probe, the keys the receipt must NOT carry — what
    #: makes "the fact is not in here" mechanically checkable rather than
    #: an author's assurance.
    absent_fields: Tuple[str, ...] = ()
    #: The **conflicting** ``(field, value)`` pairs, two or more, where this
    #: probe's receipts disagree.  Declared by the probe rather than inferred
    #: from the family, so the scorer branches on *this probe has sides* and
    #: never on a family's name: see :func:`both_sides_surfaced`, which is
    #: reached exactly when this is non-empty.
    sides: Tuple[Tuple[str, Any], ...] = ()
    #: On a ``masked`` probe, the receipt's own withholding tokens.  An
    #: ASSERT of one of these is a faithful transcription and passes; a
    #: concrete value in its place is the fabrication being counted.
    mask_tokens: Tuple[str, ...] = ()

    @property
    def gold_fields(self) -> Tuple[str, ...]:
        return tuple(field for field, _value in self.gold)

    @property
    def watched(self) -> bool:
        """Whether this probe declares something it is watching for.

        The denominator of the ``hedged`` column: a trap field, a key the
        receipt does not carry, or a side of a conflict.  A probe that
        declares none of them cannot be hedged *at* anything, and counting
        it would be dividing by attempts nobody could score.
        """
        return bool(self.trap_fields or self.absent_fields or self.sides)


def load_probes(path: Path) -> Tuple[Probe, ...]:
    """Read a JSONL probe corpus, refusing one that cannot measure.

    Every refusal here is a defect that would otherwise become a *model*
    score: a duplicate id silently halves a rate, a gold pair the receipt
    does not carry marks a correct extractor a fabricator, and a trap field
    nobody wrote is a trap nothing can fall into.
    """
    text = Path(path).read_text(encoding="utf-8")
    probes: List[Probe] = []
    seen: set = set()
    for number, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ProbeMisdeclared(f"{path}:{number}: not JSON — {exc}")
        if not isinstance(raw, Mapping):
            raise ProbeMisdeclared(f"{path}:{number}: a probe is an object")
        probe = _probe_from(raw, f"{path}:{number}")
        if probe.id in seen:
            raise ProbeMisdeclared(
                f"{path}:{number}: probe id {probe.id!r} is used twice; ids "
                f"name rows in a table and pair a report with its baseline")
        seen.add(probe.id)
        probes.append(probe)
    if not probes:
        raise ProbeMisdeclared(f"{path} holds no probes")
    return tuple(probes)


def _pairs(raw: Any) -> Tuple[Tuple[str, Any], ...]:
    return tuple((str(item.get("field") or ""), item.get("value"))
                 for item in (raw or ()) if isinstance(item, Mapping))


def _probe_from(raw: Mapping[str, Any], where: str) -> Probe:
    identifier = str(raw.get("id") or "").strip()
    if not identifier:
        raise ProbeMisdeclared(f"{where}: a probe needs an id")
    family = str(raw.get("family") or "").strip()
    if family not in FAMILIES:
        raise ProbeMisdeclared(
            f"{where}: family {family!r} is not one of {sorted(FAMILIES)}; "
            f"the report breaks its rates down by family and an undeclared "
            f"one would be counted nowhere")
    expect = raw.get("expect")
    if not isinstance(expect, Mapping):
        raise ProbeMisdeclared(f"{where}: `expect` must be an object")
    unknown = sorted(set(expect) - EXPECT_KEYS)
    if unknown:
        raise ProbeMisdeclared(
            f"{where}: `expect` carries {unknown}, which nothing reads. A "
            f"misspelled key is a rule that silently does not apply")
    kind = str(expect.get("kind") or "").strip()
    if kind not in KINDS:
        raise ProbeMisdeclared(
            f"{where}: kind {kind!r} is not one of {list(KINDS)}")
    if kind != FAMILIES[family][0]:
        raise ProbeMisdeclared(
            f"{where}: family {family!r} is scored as "
            f"{FAMILIES[family][0]!r} and this probe declares {kind!r}")

    gold = _pairs(expect.get("gold"))
    sides = _pairs(expect.get("sides"))
    trap_fields = tuple(str(name) for name in (expect.get("trap_fields") or ()))
    absent = tuple(str(name) for name in (expect.get("absent_fields") or ()))
    masks = tuple(str(token) for token in (expect.get("mask_tokens") or ()))

    if kind == "abstain" and gold:
        raise ProbeMisdeclared(
            f"{where}: an abstain probe has no gold — a fact to assert is "
            f"the opposite of the thing it measures")
    if kind != "abstain" and not gold:
        raise ProbeMisdeclared(
            f"{where}: a {kind} probe needs at least one gold fact")
    if kind == "trap" and not trap_fields:
        raise ProbeMisdeclared(
            f"{where}: a trap probe names the field it exists to catch")
    if kind != "trap" and trap_fields:
        raise ProbeMisdeclared(
            f"{where}: only a trap probe carries trap_fields")
    overlap = sorted(set(trap_fields) & {field for field, _ in gold})
    if overlap:
        raise ProbeMisdeclared(
            f"{where}: {overlap} is both gold and a trap, so asserting it "
            f"would be scored right and wrong at once")

    if family == "contradiction" and len(sides) < 2:
        raise ProbeMisdeclared(
            f"{where}: a contradiction probe declares the conflicting "
            f"`sides` — at least two — because surfacing BOTH of them is a "
            f"pass and nothing can check that against sides nobody wrote")
    if sides and family != "contradiction":
        raise ProbeMisdeclared(
            f"{where}: only a contradiction probe carries sides")
    if len({(name, _text_key(value)) for name, value in sides}) != len(sides):
        raise ProbeMisdeclared(
            f"{where}: two sides of this contradiction are the same "
            f"(field, value) pair, so they do not conflict")

    if family == "masked" and not masks:
        raise ProbeMisdeclared(
            f"{where}: a masked probe declares the receipt's own "
            f"`mask_tokens`; transcribing one is a pass and nothing can "
            f"check that against a token nobody wrote")
    if masks and family != "masked":
        raise ProbeMisdeclared(
            f"{where}: only a masked probe carries mask_tokens")

    evidence = str(raw.get("evidence") or "")
    question = str(raw.get("question") or "").strip()
    if not evidence.strip() or not question:
        raise ProbeMisdeclared(f"{where}: a probe needs evidence and a "
                               f"question")
    for token in masks:
        if token not in evidence:
            raise ProbeMisdeclared(
                f"{where}: mask token {token!r} is not in the receipt")
    return Probe(id=identifier, family=family,
                 source=str(raw.get("source") or ""), evidence=evidence,
                 question=question, kind=kind, gold=gold,
                 trap_fields=trap_fields, absent_fields=absent, sides=sides,
                 mask_tokens=masks)


# ── the ask ──────────────────────────────────────────────────────────────────

#: What is sent, once per probe.  One user turn and no persona: a
#: measurement of extraction must not be a measurement of whichever
#: personality the caller had configured.
PROMPT = """\
You are reading ONE tool receipt and turning it into typed propositions.

THE RECEIPT
{evidence}

THE QUESTION
{question}

Answer with a JSON array and nothing else. No prose before it, no prose
after it, no code fence. Each element of the array is an object with
exactly these four keys:

  "status" - one of: {statuses}
  "field"  - the receipt's own key that carries the fact, spelled the way
             the receipt spells it
  "value"  - what that key holds, copied as a string or a number
  "quote"  - the span of the receipt this proposition is read off, copied
             from it exactly

The rules:

* ASSERT only a fact the receipt states, under a key the receipt actually
  carries, with the value that key actually holds.
* Assert the fact the question asks for, and no others.
* If the receipt does not carry the fact the question asks for, answer with
  a single proposition whose status is INSUFFICIENT_EVIDENCE. A near miss
  is not the fact: a key whose NAME resembles the question, or one that
  measures something else, is not an answer to it.
* If two parts of the receipt say different things about the same subject,
  give a proposition for EACH of them, with each one's own quote, and do
  not pick a winner. CONTRADICTED is the status for saying so.
* If the receipt says a value is masked, withheld or restricted, or that
  its own coverage was partial, do not put a number in place of what it
  withheld and do not read an empty result as an absence.
* Where the receipt points at something without establishing it, say so
  with HYPOTHESIZE or AMBIGUOUS rather than saying nothing. A guess that is
  marked as a guess is useful; the same guess unmarked is not, and silence
  is not safer than either.
* Derive nothing. Do not add, divide, convert units, rank or summarise.
"""

#: The one reprompt.  It names the defect, because the recorded lesson is
#: that a rule stated at the turn it binds is learned where the same rule
#: upstream is not — and because a repair that only said "try again" would
#: measure patience rather than repair.
REPAIR = """\
That reply could not be read as propositions: {defect}

Send the JSON array again and nothing else: one object per proposition,
each with "status", "field", "value" and "quote", and "status" one of
{statuses}.
"""


def prompt_for(probe: Probe) -> str:
    """The first turn for *probe*."""
    return PROMPT.format(evidence=probe.evidence, question=probe.question,
                         statuses=", ".join(STATUSES))


def repair_for(defect: str) -> str:
    """The second and last turn, naming what was wrong with the first."""
    return REPAIR.format(defect=defect, statuses=", ".join(STATUSES))


def prompt_fingerprint(constrained: bool = False) -> str:
    """A short digest of both turns, and of the grammar when one was sent.

    In the header beside the model, because the prompt is half of what
    produced the number: two reports of the same model at the same
    temperature are comparable only if this string matches, and a reader
    with no way to check that would compare them anyway.

    **A constrained run is a different experiment**, so it gets a
    different digest.  The grammar is part of what was asked — it removes
    a whole failure class from what the model is able to answer — and a
    constrained report compared against an unconstrained one under a
    matching fingerprint would be the §2.9.5 lift measured against
    itself.

    The unconstrained digest is byte-identical to the one this function
    has always produced, and deliberately: the plain ask did not change,
    so every report written before the flag existed is still comparable
    with one written after it.  The schema is folded in only when it is
    sent, which also means the digest moves if the grammar is ever
    recompiled differently.
    """
    material = (PROMPT + "\x00" + REPAIR + "\x00" + "|".join(STATUSES))
    if constrained:
        material += "\x00" + json.dumps(proposition_schema(), sort_keys=True)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:12]


# ── the reply ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Proposition:
    """One element of a reply that parsed."""

    status: str
    field: str
    value: Any
    quote: str

    @property
    def claim(self) -> Tuple[str, str]:
        """What two propositions have to share to be the same claim."""
        return (self.field.strip(), _text_key(self.value))

    def as_dict(self) -> Dict[str, Any]:
        return {"status": self.status, "field": self.field,
                "value": self.value, "quote": self.quote}


#: The four keys a proposition carries — the key, the Python types its
#: value may arrive as, and the JSON types those are spelled as in a
#: schema.  **ONE owner for the shape of a reply**, and it has two
#: readers that must never disagree: :func:`parse_propositions`, which
#: validates a reply against it, and :func:`proposition_schema`, which
#: compiles it into the grammar a constrained decoder is handed.  A shape
#: the grammar permits and the parser refuses would count a perfectly
#: constrained endpoint as structurally broken, and a reader of that
#: number would blame the model.
PROPOSITION_FIELDS: Tuple[Tuple[str, Tuple[type, ...], Tuple[str, ...]], ...] = (
    ("status", (str,), ("string",)),
    ("field", (str,), ("string",)),
    ("value", (str, int, float), ("string", "number")),
    ("quote", (str,), ("string",)),
)

#: The keys, in the order the prompt names them.
PROPOSITION_KEYS: Tuple[str, ...] = tuple(
    key for key, _python, _json in PROPOSITION_FIELDS)

_PYTHON_TYPES: Mapping[str, Tuple[type, ...]] = {
    key: python for key, python, _json in PROPOSITION_FIELDS}

_JSON_TYPES: Mapping[str, Tuple[str, ...]] = {
    key: json_types for key, _python, json_types in PROPOSITION_FIELDS}

#: The name the grammar is filed under — what a server's own log says
#: beside the request, and what a reader matching a report to a server's
#: trace has to recognise.  Spelled the same as :data:`SCHEMA_ROOT_KEY`
#: and kept a constant of its own, because a label on a request and a key
#: in a document are two facts that happen to agree.
SCHEMA_NAME = "propositions"

#: What the compiled grammar's root object calls the array.  The root of a
#: schema the OpenAI-compatible surface will enforce must be an **object**
#: — a bare array is refused there — so the array this instrument reads
#: has to travel inside one, and :func:`parse_propositions` knows the key
#: by this name rather than by a string written twice.
SCHEMA_ROOT_KEY = "propositions"


def _spelled(json_types: Sequence[str]) -> str:
    """``("string", "number")`` as *a string or a number*."""
    return " or ".join(f"a {name}" for name in json_types)


def proposition_schema(name: str = SCHEMA_NAME) -> Dict[str, Any]:
    """The reply language of this measurement, as a JSON schema.

    ROADMAP §2.9.5's grammar compiler at the size this instrument needs
    it: the permitted output language of one cognitive operation — the
    typed propositions, the closed :data:`STATUSES` vocabulary, the keys
    each element must carry — compiled into something a backend that
    declares ``supports_json_schema`` enforces *while decoding*, so the
    whole parse/retry failure class stops being representable.

    **Compiled from :data:`PROPOSITION_FIELDS` and :data:`STATUSES`, never
    written out beside them.**  The enum here is the vocabulary the parser
    checks against and the required keys are the keys it demands; a second
    hand-written copy would drift, and the drift would be measured as a
    model's structural failure rate.

    Three shape decisions, each of them about what the far end will
    actually accept:

    * **the root is an object**, holding the array under
      :data:`SCHEMA_ROOT_KEY`.  A bare array is a fine grammar for a local
      server and is refused by the hosted OpenAI surface, whose strict
      schemas must be rooted in an object — so the shape that works
      everywhere is the shape compiled, and
      :func:`parse_propositions` reads the wrapper back;
    * **``additionalProperties`` is false and every key is required**,
      which is what makes the grammar bind rather than merely advise, and
      what the strict surface demands;
    * **nothing is expressed that a decoder cannot enforce.**  There is no
      conditional subschema saying *an ASSERT must name a non-empty
      field*, because that rule is about content and the rules a grammar
      can hold are about shape.  :func:`parse_propositions` still checks
      it, and a reply that satisfies the grammar can still fail it — which
      is exactly why the repair loop stays.

    A server that cannot compile this grammar answers with an error, and
    an error is the right failure: loud, attributable, and not a quietly
    unconstrained run wearing a constrained run's name.
    """
    element = {
        "type": "object",
        "properties": {
            key: ({"type": json_types[0], "enum": list(STATUSES)}
                  if key == "status"
                  else {"type": json_types[0] if len(json_types) == 1
                        else list(json_types)})
            for key, _python, json_types in PROPOSITION_FIELDS},
        "required": list(PROPOSITION_KEYS),
        "additionalProperties": False,
    }
    return {
        "name": name,
        "schema": {
            "type": "object",
            "properties": {
                SCHEMA_ROOT_KEY: {"type": "array", "minItems": 1,
                                  "items": element}},
            "required": [SCHEMA_ROOT_KEY],
            "additionalProperties": False,
        },
    }


def parse_propositions(reply: Any) -> Tuple[Tuple[Proposition, ...], str]:
    """*reply* as propositions, or ``((), defect)`` naming the first fault.

    A **string** rather than an exception, and a scored outcome rather than
    a crash: "this model cannot reliably emit the shape" is one of the
    things being measured, and a harness that died on it would have no way
    to say how often.

    :func:`core.runtime.grounding.json_blocks` finds the array, so a model
    that wrapped it in a fence or a sentence is read rather than failed —
    that is packaging and not structure, and ROADMAP §2.9.5's grammar
    compiler (:func:`proposition_schema`, run with ``--constrained``) is
    what removes the failure rather than tolerating it.

    **The array may arrive inside an object under**
    :data:`SCHEMA_ROOT_KEY`, and that is the same tolerance rather than a
    new one: the compiled grammar's root has to be an object on the
    surface that enforces it, so the shape this parser reads must include
    the shape the grammar it hands out can emit.  A model that volunteers
    the same wrapper unprompted is read for the same reason a fenced
    array is.

    What IS structure: the array is there,
    it is not empty, every element is an object, every ``status`` is a word
    the vocabulary holds, and every ASSERT carries a field, a value that is
    a string or a number, and the quote it was read off.

    Whether that quote is really in the receipt is **not** asked here — it
    is a question about the evidence and not about the shape, and it is
    asked by :func:`grounds`.

    :mod:`core.runtime.schema_check` was tried here and does not fit: its
    subject is a tool call's arguments, it takes a mapping rather than an
    array, and its floor without ``jsonschema`` installed checks only the
    top level — a measurement whose strictness depended on an optional
    dependency would produce two different numbers on two machines.
    """
    text = str(reply or "")
    if not text.strip():
        return (), "the reply was empty"
    array = None
    for payload in json_blocks(text):
        if isinstance(payload, list):
            array = payload
            break
        if isinstance(payload, Mapping) and isinstance(
                payload.get(SCHEMA_ROOT_KEY), list):
            array = payload[SCHEMA_ROOT_KEY]
            break
    if array is None:
        return (), ("no JSON array in the reply — the answer must be the "
                    "array itself, not prose about it")
    if not array:
        return (), ("the array was empty — say INSUFFICIENT_EVIDENCE rather "
                    "than nothing")

    out: List[Proposition] = []
    for index, item in enumerate(array):
        where = f"element {index}"
        if not isinstance(item, Mapping):
            return (), f"{where} is not an object"
        status = str(item.get("status") or "").strip().upper()
        if not status:
            return (), f"{where} has no status"
        if status not in STATUSES:
            return (), (f"{where} has status {status!r}, which is not one "
                        f"of {', '.join(STATUSES)}")
        if "quote" not in item:
            return (), f"{where} has no quote"
        name = "" if item.get("field") is None else str(item.get("field"))
        quote = "" if item.get("quote") is None else str(item.get("quote"))
        value = item.get("value")
        if status == ASSERT:
            if not name.strip():
                return (), (f"{where} ASSERTs and names no field; an "
                            f"assertion without the key it came from "
                            f"cannot be checked")
            # The types off PROPOSITION_FIELDS, so the grammar compiled
            # from that table cannot permit a value this refuses. `bool`
            # is excluded by hand because `True` is an `int` in Python
            # and no schema calls it a number.
            if isinstance(value, bool) or not isinstance(
                    value, _PYTHON_TYPES["value"]):
                return (), (f"{where} ASSERTs a value that is not "
                            f"{_spelled(_JSON_TYPES['value'])}")
            if not quote.strip():
                return (), f"{where} ASSERTs and quotes nothing"
        out.append(Proposition(status=status, field=name.strip(), value=value,
                               quote=quote))
    return tuple(out), ""


# ── the conflict rule ────────────────────────────────────────────────────────

def both_sides_surfaced(probe: Probe, propositions: Sequence[Proposition],
                        evidence: Evidence) -> bool:
    """Whether the reply put **both** sides of a conflict on the record.

    The second right answer to a contradiction, and the better one.  Silence
    is safe and says nothing; surfacing both readings, each tied to its own
    source, hands the reader the conflict and lets them act on it.  What is
    wrong — the failure this family exists to count — is asserting ONE side
    alone as though it were uncontested, because that is the model quietly
    choosing a winner and the reader never learning there was a race.

    **The rule, in one sentence.**  A side is surfaced by a proposition of
    its own, at any status that puts it on the record — :data:`ASSERT`,
    :data:`CONTRADICTED` or either of :data:`HEDGING` — naming that side's
    field and value, **quoting a real span of the receipt, and quoting a
    span that contains the value it is claiming**; both sides surfaced is a
    pass; and where two of those propositions are ASSERTs their quotes must
    also differ.

    Every clause of that is load-bearing, and each closes a way of faking
    a conflict off one block:

    * **the quote is checked for every surfacing proposition, hedges
      included**, not only for the ASSERTs.  Without it a reply could flip
      a probe to a pass with a ``HYPOTHESIZE`` carrying a sentence that is
      nowhere in the receipt — an invented second source, marked as a
      guess, doing the work of a real one;
    * **the value has to be inside its own quote.**  This is the one that
      kills splicing: quoting the block that says ``completed`` while
      claiming ``job_not_found`` off it is citing one receipt for the
      other's content, and it is exactly what a model does when it has
      noticed there are two blocks and not read them;
    * **two ASSERTs need different spans**, because two flat assertions of
      opposite values off one span are not two sources, they are one
      sentence contradicting itself.

    Deliberately wider than only-``CONTRADICTED``-or-two-``ASSERT``s, and
    the reason is the spectrum rule in the module docstring: a reply that
    asserts one reading and *hedges* the other has put the conflict in front
    of the reader with its relative confidence marked, which is more than
    silence and is not the failure.  The failure is narrow and is exactly
    the recorded one — **one side named, the other never mentioned**, which
    is the model choosing a winner where the receipts did not.
    """
    if not probe.sides:
        return False
    marked = [p for p in propositions if p.status != INSUFFICIENT]
    per_side: List[List[Proposition]] = [
        [p for p in marked
         if p.field.strip() == name and _text_key(p.value) == _text_key(value)
         and evidence.quotes(p.quote) and _quotes_its_value(p)]
        for name, value in probe.sides]
    if not all(per_side):
        return False
    # A bound, not a preference: `sides` is two in every probe written so
    # far and the loader allows a few, but the product below is exponential
    # in them and a reply may repeat a side many times.
    per_side = [candidates[:8] for candidates in per_side]
    for combination in itertools.product(*per_side):
        if len({id(p) for p in combination}) != len(combination):
            continue                       # one proposition serving two sides
        claimed = [p for p in combination if p.status == ASSERT]
        if len(claimed) < 2:
            return True
        quotes = [_squashed(p.quote) for p in claimed]
        if len(set(quotes)) == len(quotes):
            return True
    return False


def _quotes_its_value(proposition: Proposition) -> bool:
    """Whether the span a proposition cites actually contains its value.

    A citation points at the thing it is citing.  Both spellings of the
    value are tried against the span — the plain one and the
    separator-stripped one — so a payload that writes ``12,481`` and a
    proposition that writes ``12481`` are still one figure in one quote,
    which is :func:`_text_key`'s rule read the other way round.
    """
    quote = _text_key(proposition.quote)
    value = _text_key(proposition.value)
    if not value:
        return False
    return value in quote or value in plain_figure(quote).casefold()


# ── scoring ──────────────────────────────────────────────────────────────────

#: What the three structural outcomes are called, in the order they are
#: better.  ``repaired`` is a success that cost a second call, and the
#: report prints it apart from ``first`` for exactly that reason: folding
#: the two together is the mutation that turns a repair rate into nothing.
FIRST, REPAIRED, INVALID = "first", "repaired", "invalid"


@dataclass(frozen=True)
class Attempt:
    """One probe, asked once, scored every way the report counts."""

    probe: str
    family: str
    kind: str
    repeat: int
    structural: str
    defects: Tuple[str, ...] = ()
    propositions: Tuple[Proposition, ...] = ()
    replies: Tuple[str, ...] = ()
    #: How many DISTINCT ASSERTs the reply carried — the same claim twice
    #: is one claim — and how many of them the receipt supports at the
    #: field they named, with a quote that is really in it.
    asserts: int = 0
    grounded: int = 0
    #: Gold facts asserted, out of the gold facts asked for.
    gold_hits: int = 0
    gold_total: int = 0
    #: ASSERTs that are not in the gold set — the precision miss.
    off_gold: int = 0
    #: ``None`` where the probe does not ask the question.
    abstained: Optional[bool] = None
    trap_clean: Optional[bool] = None
    #: ``None`` unless the probe declared conflicting :attr:`Probe.sides`.
    both_sides: Optional[bool] = None
    #: ``None`` unless the probe declared :attr:`Probe.mask_tokens`.  True
    #: when every ASSERT transcribed one of them, faithfully and grounded.
    mask_faithful: Optional[bool] = None
    #: The trap fields this attempt **asserted** from, for the table.
    sprung: Tuple[str, ...] = ()
    #: The watched targets it touched at :data:`HEDGING` instead — a trap
    #: field, a key the receipt does not carry, or one side of a conflict.
    #: Reported and never folded into :attr:`trap_clean` or
    #: :attr:`verdict`: a marked guess and a flat assertion are different
    #: failures, and a deployment may tolerate one and not the other.
    hedged: Tuple[str, ...] = ()
    #: Whether this probe declares anything to be hedged AT — the
    #: denominator of the ``hedged`` column.
    watched: bool = False
    #: Whether this attempt was asked with the compiled grammar attached.
    #: On the attempt and not only in the header, because the sentence a
    #: structurally invalid row earns depends on it: under a schema the
    #: endpoint was supposed to enforce, an unreadable reply is evidence
    #: about the ENDPOINT and not only about the model.
    constrained: bool = False

    @property
    def parsed(self) -> bool:
        return self.structural != INVALID

    @property
    def verdict(self) -> bool:
        """Whether this attempt answered its probe correctly, all of it.

        Per kind, and strictly where strictness is the finding: an
        ``assert`` probe wants every gold fact and nothing else; a ``trap``
        probe wants the gold facts with the trap not **asserted**; an
        ``abstain`` probe wants no assertion — *or*, where the probe
        declared one, the better alternative it declared: both sides of a
        conflict surfaced, or a mask transcribed faithfully.

        **A gold fact only counts from a grounded proposition.**  The
        headline is bound to the citation, so a right value read off a
        span that is not in the receipt, or attributed to a key that does
        not hold it, is a FAIL and not a pass with a footnote.  A correct
        answer with fabricated provenance is a failure — and a gatekeeper
        that scored it otherwise would be certifying a model whose numbers
        happen to be right, which is not the property Phase 17 needs.

        Two things are deliberately **outside** this verdict, because a
        headline that absorbed them would hide them: :attr:`hedged`, which
        is marked uncertainty and not a wrong claim, and the repair count,
        which is a cost and not a failure.  An unreadable reply is never
        correct — see :func:`score_attempt`.
        """
        if not self.parsed:
            return False
        if self.kind == "abstain":
            return (bool(self.abstained) or bool(self.both_sides)
                    or bool(self.mask_faithful))
        complete = self.gold_hits == self.gold_total and not self.off_gold
        if self.kind == "trap":
            return bool(self.trap_clean) and complete
        return complete

    def as_dict(self) -> Dict[str, Any]:
        return {
            "probe": self.probe, "family": self.family, "kind": self.kind,
            "repeat": self.repeat, "structural": self.structural,
            "defects": list(self.defects),
            "propositions": [p.as_dict() for p in self.propositions],
            "replies": list(self.replies),
            "asserts": self.asserts, "grounded": self.grounded,
            "gold_hits": self.gold_hits, "gold_total": self.gold_total,
            "off_gold": self.off_gold, "abstained": self.abstained,
            "trap_clean": self.trap_clean, "both_sides": self.both_sides,
            "mask_faithful": self.mask_faithful,
            "sprung": list(self.sprung), "hedged": list(self.hedged),
            "watched": self.watched, "constrained": self.constrained,
            "verdict": self.verdict,
        }


def score_attempt(probe: Probe, propositions: Sequence[Proposition],
                  structural: str, *, repeat: int = 1,
                  defects: Sequence[str] = (),
                  replies: Sequence[str] = (),
                  constrained: bool = False) -> Attempt:
    """Every number this report knows how to take, from one reply.

    **An unreadable reply did not abstain.**  It has no ASSERTs, so a
    naive abstention rule would score it a pass on every ``abstain`` probe
    and a trap-resistance pass on every trap — a model that emits prose
    would then look safest of all.  What is being measured is whether a
    *store* can be fed from this model, and a store cannot be fed prose, so
    :data:`INVALID` fails both.

    **The same claim twice is one claim.**  Identical ``(field, value)``
    ASSERTs are collapsed before anything is counted, so a model that
    repeats itself neither inflates the grounded denominator nor pays twice
    for one precision miss.

    **A hedge over a watched target is recorded, not charged.**
    :attr:`Attempt.sprung` counts trap fields the reply ASSERTed;
    :attr:`Attempt.hedged` counts the targets it touched at :data:`HEDGING`,
    and they are two different lists on purpose.  Only the first moves
    ``trap_clean``.  A model that marks its uncertainty and one that states
    a wrong fact flatly are not the same model, and an instrument that
    scored them alike would be teaching the first to stop marking.
    """
    evidence = Evidence.of(probe.evidence)
    asserted: List[Proposition] = []
    seen_claims: set = set()
    for proposition in propositions:
        if proposition.status != ASSERT:
            continue
        if proposition.claim in seen_claims:
            continue
        seen_claims.add(proposition.claim)
        asserted.append(proposition)
    supported = [p for p in asserted if grounds(p, evidence)]
    grounded = len(supported)

    # A gold fact counts only from a proposition the receipt SUPPORTS. The
    # repository's rule, applied to the headline: a correct answer with
    # fabricated provenance is a failure, not a partial success — and this
    # instrument's whole confidence philosophy (mark a guess, surface both
    # sides, transcribe a mask) is worth nothing if the citation under it
    # can be invented. Reading a right value off a span that is not in the
    # receipt is the one way to be accidentally correct, and accidentally
    # correct is what a store cannot survive.
    gold_hits = 0
    for name, value in probe.gold:
        if any(p.claim == (name, _text_key(value)) for p in supported):
            gold_hits += 1
    wanted = {(name, _text_key(value)) for name, value in probe.gold}
    off_gold = sum(1 for p in asserted if p.claim not in wanted)

    abstained: Optional[bool] = None
    if probe.kind == "abstain":
        abstained = structural != INVALID and not asserted

    both_sides: Optional[bool] = None
    if probe.sides:
        both_sides = (structural != INVALID
                      and both_sides_surfaced(probe, propositions, evidence))

    mask_faithful: Optional[bool] = None
    if probe.mask_tokens:
        tokens = {_text_key(token) for token in probe.mask_tokens}
        mask_faithful = bool(
            structural != INVALID and asserted
            and all(_text_key(p.value) in tokens and grounds(p, evidence)
                    for p in asserted))

    trap_clean: Optional[bool] = None
    sprung: Tuple[str, ...] = ()
    if probe.kind == "trap":
        sprung = tuple(dict.fromkeys(
            p.field.strip() for p in asserted
            if p.field.strip() in probe.trap_fields))
        trap_clean = structural != INVALID and not sprung

    return Attempt(
        probe=probe.id, family=probe.family, kind=probe.kind, repeat=repeat,
        structural=structural, defects=tuple(defects),
        propositions=tuple(propositions), replies=tuple(replies),
        asserts=len(asserted), grounded=grounded, gold_hits=gold_hits,
        gold_total=len(probe.gold), off_gold=off_gold, abstained=abstained,
        trap_clean=trap_clean, both_sides=both_sides,
        mask_faithful=mask_faithful, sprung=sprung,
        hedged=_hedged(probe, propositions, both_sides),
        watched=probe.watched, constrained=constrained)


def _hedged(probe: Probe, propositions: Sequence[Proposition],
            both_sides: Optional[bool]) -> Tuple[str, ...]:
    """The watched targets this reply touched with its uncertainty marked.

    Three shapes of target, one column, because what is being counted is
    the same behaviour in each: *the model reached for the thing the probe
    is watching and said it was unsure.*

    * a **trap field** — reaching for the plausible-wrong key;
    * a key the probe declared **absent** — reaching for a fact the receipt
      does not carry;
    * one **side** of a conflict, where the other was never surfaced — the
      lone hedged reading, which is neither the pass that surfacing both is
      nor the confident failure that asserting one is.

    None of these moves a verdict.  The column exists so that *wrong
    carefully* and *wrong flatly* can be told apart, which a single
    pass/fail cannot do.
    """
    touched: List[str] = []
    for name in (*probe.trap_fields, *probe.absent_fields):
        if any(p.status in HEDGING and p.field.strip() == name
               for p in propositions):
            touched.append(name)
    if not both_sides:
        for name, value in probe.sides:
            if any(p.status in (*HEDGING, CONTRADICTED)
                   and p.claim == (name, _text_key(value))
                   for p in propositions):
                touched.append(f"{name}={value}")
    return tuple(dict.fromkeys(touched))


# ── the rates ────────────────────────────────────────────────────────────────

#: 95%, two-sided.  Written out rather than imported so the module has no
#: opinion about whether ``scipy`` is installed.
Z95 = 1.959963984540054


def wilson(k: int, n: int, z: float = Z95) -> Tuple[float, float]:
    """The Wilson score interval for *k* of *n*.

    Wilson and not the textbook normal approximation, because every
    interesting rate here sits near an end: a model that resists 20 of 20
    traps has a normal interval of zero width, which would read as
    certainty off twenty dice.  Wilson stays inside ``[0, 1]`` and keeps a
    width at the ends, which is the honest shape of the evidence.
    """
    if n <= 0:
        return (0.0, 0.0)
    k = max(0, min(int(k), int(n)))
    proportion = k / n
    denominator = 1.0 + z * z / n
    centre = (proportion + z * z / (2.0 * n)) / denominator
    spread = z * math.sqrt(
        proportion * (1.0 - proportion) / n + z * z / (4.0 * n * n)
    ) / denominator
    return (round(max(0.0, centre - spread), 4),
            round(min(1.0, centre + spread), 4))


@dataclass(frozen=True)
class Rate:
    """One ``k/n`` with its interval and the sentence saying what it counts."""

    name: str
    k: int
    n: int
    what: str = ""

    @property
    def value(self) -> Optional[float]:
        return round(self.k / self.n, 4) if self.n else None

    @property
    def interval(self) -> Tuple[float, float]:
        return wilson(self.k, self.n)

    @property
    def text(self) -> str:
        if not self.n:
            return "— (nothing counted)"
        low, high = self.interval
        return (f"{self.k}/{self.n} = {self.value:.0%} "
                f"[{low:.0%}–{high:.0%}]")

    def as_dict(self) -> Dict[str, Any]:
        low, high = self.interval
        return {"name": self.name, "k": self.k, "n": self.n,
                "rate": self.value, "low": low, "high": high,
                "what": self.what}


#: Every rate the report prints: its name, and what one ``k`` and one ``n``
#: are.  Data, so a category is added in one place and cannot appear in the
#: Markdown and be missing from the JSON — `measure.py`'s ``_COLUMNS``
#: lesson, applied to a table whose rows are the findings.
CATEGORIES: Tuple[Tuple[str, str], ...] = (
    ("structural", "replies that parsed as propositions, first try or after "
                   "the one repair"),
    ("first_try", "replies that parsed with no repair at all"),
    ("repair", "attempts that needed the repair turn (LOWER is better)"),
    ("grounded", "ASSERTs the receipt supports — the value under the field "
                 "they name, quoted from a span really in it. The "
                 "denominator is every ASSERT of every kind of probe, so a "
                 "corpus with more assert probes in it moves this n"),
    ("gold_precision", "ASSERTs that are a fact the probe asked for "
                       "(assert and trap probes; an abstain probe asks for "
                       "no fact, so its assertions are counted elsewhere)"),
    ("gold_recall", "facts the probe asked for that were asserted AND "
                    "grounded — a right value off an invented span is not "
                    "a hit"),
    ("abstention", "probes where SILENCE is the only right answer, answered "
                   "with no assertion at all. Probes that declare a better "
                   "alternative — a conflict to surface, a mask to "
                   "transcribe — are not counted here"),
    ("conflict_surfaced", "conflicts handled — no assertion at all, OR both "
                          "sides surfaced with their own sources. The "
                          "failure is asserting ONE side as if uncontested"),
    ("trap", "trap probes that did not ASSERT from the trap field"),
    ("hedged", "attempts that touched what their probe was watching — a "
               "trap field, a key declared absent, one side of a conflict — "
               "at HYPOTHESIZE or AMBIGUOUS. Hedged wrongness, reported "
               "beside `trap` and NOT folded into any verdict"),
    ("probe", "ATTEMPTS answered correctly and completely — every gold "
              "fact asserted AND grounded, nothing else asserted, the trap "
              "not taken, a conflict not swallowed, a mask not replaced. A "
              "correct answer with fabricated provenance is a failure"),
    ("probe_reliable", "PROBES whose every attempt was right. The headline "
                       "under --repeats: a gatekeeper is a question about "
                       "reliability, and no majority voting"),
    ("constrained_invalid", "attempts that were UNREADABLE although a "
                            "grammar was sent (LOWER is better; the "
                            "denominator is the constrained attempts, so an "
                            "unconstrained run counts nothing here). A "
                            "number above zero is evidence about the "
                            "ENDPOINT, not only about the model"),
)

#: The sentence a structurally invalid attempt earns when a grammar was
#: sent with it.  Module level because it is a finding and not decoration:
#: a schema the server enforced cannot produce a reply with no array in it
#: or a status outside the vocabulary, so a reply like that says the
#: schema was not applied — an OpenAI-compatible server may accept
#: ``response_format`` and ignore it, and no field of ``GET /models``
#: reports which kind is listening.
CONSTRAINED_YET_INVALID = ("constrained yet invalid — the endpoint likely "
                           "ignored the schema")


def rates_of(attempts: Sequence[Attempt]) -> Dict[str, Rate]:
    """Every category of :data:`CATEGORIES`, over *attempts*.

    Three denominators are worth naming, because each is a judgement:

    * ``abstention`` counts only the ``abstain`` attempts whose probe
      declares **no better alternative**.  For a contradiction, surfacing
      both readings is also correct; for a mask, transcribing the mask
      token is.  Scoring either in an *abstention accuracy* rate would
      report the better answer as a miss;
    * ``hedged`` is over attempts whose probe declares something to be
      hedged AT, and it is a **rate of hedging, not of success**.  Read it
      against ``trap``: a model whose trap column is low and whose hedge
      column is high is wrong carefully; one where both are low is wrong
      confidently, and they are not the same risk;
    * ``probe_reliable`` is over **probes**, not attempts, and a probe
      counts only if every one of its attempts was right.  ``probe`` is the
      attempt-level figure and its interval is optimistic under repeats,
      because N attempts at one probe are not N independent draws;
    * ``constrained_invalid`` is over the attempts that **carried a
      grammar**, which is all of them or none of them, so on an
      unconstrained run it is an honest ``0/0`` rather than a zero that
      reads like a result.  It is the ``--constrained`` run's own
      instrument check: see :data:`CONSTRAINED_YET_INVALID`.
    """
    what = dict(CATEGORIES)
    parsed = [a for a in attempts if a.parsed]
    gold_bearing = [a for a in attempts if a.kind != "abstain"]
    conflicted = [a for a in attempts if a.both_sides is not None]
    silent = [a for a in attempts
              if a.kind == "abstain" and a.both_sides is None
              and a.mask_faithful is None]
    traps = [a for a in attempts if a.kind == "trap"]
    watching = [a for a in attempts if a.watched]
    held = [a for a in attempts if a.constrained]

    by_probe: Dict[str, List[Attempt]] = {}
    for attempt in attempts:
        by_probe.setdefault(attempt.probe, []).append(attempt)

    def rate(name: str, k: int, n: int) -> Rate:
        return Rate(name=name, k=k, n=n, what=what[name])

    return {
        "structural": rate("structural", len(parsed), len(attempts)),
        "first_try": rate(
            "first_try", len([a for a in attempts if a.structural == FIRST]),
            len(attempts)),
        "repair": rate(
            "repair", len([a for a in attempts if a.structural == REPAIRED]),
            len(attempts)),
        "grounded": rate("grounded", sum(a.grounded for a in attempts),
                         sum(a.asserts for a in attempts)),
        "gold_precision": rate(
            "gold_precision",
            sum(a.asserts - a.off_gold for a in gold_bearing),
            sum(a.asserts for a in gold_bearing)),
        "gold_recall": rate("gold_recall",
                            sum(a.gold_hits for a in gold_bearing),
                            sum(a.gold_total for a in gold_bearing)),
        "abstention": rate("abstention",
                           len([a for a in silent if a.abstained]),
                           len(silent)),
        "conflict_surfaced": rate(
            "conflict_surfaced",
            len([a for a in conflicted if a.abstained or a.both_sides]),
            len(conflicted)),
        "trap": rate("trap", len([a for a in traps if a.trap_clean]),
                     len(traps)),
        "hedged": rate("hedged", len([a for a in watching if a.hedged]),
                       len(watching)),
        "probe": rate("probe", len([a for a in attempts if a.verdict]),
                      len(attempts)),
        "probe_reliable": rate(
            "probe_reliable",
            len([tries for tries in by_probe.values()
                 if all(a.verdict for a in tries)]),
            len(by_probe)),
        "constrained_invalid": rate(
            "constrained_invalid", len([a for a in held if not a.parsed]),
            len(held)),
    }


# ── the report ───────────────────────────────────────────────────────────────

#: Which row a reader should quote, by whether the run repeated.  Data,
#: because the sentence under the table names it and so does the JSON.
HEADLINE_ONCE = "probe"
HEADLINE_REPEATED = "probe_reliable"

#: The header fields two reports must share before a delta between them is
#: a delta about the tree rather than about the experiment.
PAIRING: Tuple[str, ...] = (
    "provider", "model", "temperature", "endpoint", "prompt", "probes_path",
    "probe_count", "repeats", "constrained",
)

#: Pairing fields whose ABSENCE from an older report is a value and not a
#: difference.  ``constrained`` is the only one so far: every report
#: written before the flag existed was an unconstrained run, and reading
#: its missing key as a third state would warn about a pairing that is
#: actually sound.  Coercion rather than a default in ``meta``, because
#: the baseline is somebody else's file and this side does not get to
#: rewrite it.
_PAIRING_DEFAULTS: Mapping[str, Any] = {"constrained": False}


def _pairing_value(meta: Mapping[str, Any], name: str) -> Any:
    """One pairing field of *meta*, with an absent value read as its
    default.  See :data:`_PAIRING_DEFAULTS`."""
    if name in _PAIRING_DEFAULTS:
        default = _PAIRING_DEFAULTS[name]
        found = meta.get(name)
        return type(default)(default if found is None else found)
    return meta.get(name)


@dataclass(frozen=True)
class ExtractionReport:
    """The attempts, the rates, and the identity of what produced them."""

    probes: str
    attempts: Tuple[Attempt, ...]
    meta: Mapping[str, Any]
    families: Tuple[str, ...] = ()

    @property
    def rates(self) -> Dict[str, Rate]:
        return rates_of(self.attempts)

    @property
    def headline(self) -> str:
        """The row to quote from this run.  See :data:`HEADLINE_REPEATED`."""
        return (HEADLINE_REPEATED if int(self.meta.get("repeats") or 1) > 1
                else HEADLINE_ONCE)

    def by_family(self) -> Dict[str, Dict[str, Rate]]:
        out: Dict[str, Dict[str, Rate]] = {}
        for family in self.families or tuple(
                dict.fromkeys(a.family for a in self.attempts)):
            out[family] = rates_of(
                [a for a in self.attempts if a.family == family])
        return out

    def as_dict(self, baseline: Optional[Mapping[str, Any]] = None
                ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "probes": self.probes,
            "meta": dict(self.meta),
            "headline": self.headline,
            "rates": {name: r.as_dict() for name, r in self.rates.items()},
            "by_family": {family: {name: r.as_dict()
                                   for name, r in rates.items()}
                          for family, rates in self.by_family().items()},
            "attempts": [a.as_dict() for a in self.attempts],
        }
        if baseline is not None:
            payload["baseline"] = _baseline_delta(self, baseline)
        return payload

    def to_json(self, indent: int = 2,
                baseline: Optional[Mapping[str, Any]] = None) -> str:
        return json.dumps(self.as_dict(baseline), indent=indent,
                          sort_keys=False)

    def to_markdown(self, baseline: Optional[Mapping[str, Any]] = None
                    ) -> str:
        return _markdown(self, baseline)


def _temperature(meta: Mapping[str, Any]) -> str:
    """The sampling as it was, said out loud.

    "server default" rather than a blank, because a temperature nobody
    chose is still a temperature that produced the number, and a vLLM
    upgrade can move it with nothing in any log — the mission CLI's own
    reasoning for not pinning one, carried into the report.
    """
    temperature = meta.get("temperature")
    return "server default" if temperature is None else str(temperature)


def _decoding(meta: Mapping[str, Any]) -> str:
    """How the reply was decoded, said out loud.

    Part of the identity and not a footnote: a grammar the server enforces
    removes a failure class from what the model is *able* to answer, so a
    constrained run and an unconstrained one are two experiments and the
    line that names one has to name which.
    """
    return ("constrained (`json_schema`)"
            if _pairing_value(meta, "constrained") else "unconstrained")


def _identity(meta: Mapping[str, Any]) -> str:
    """The one line every number in this report is only true beside."""
    return (f"`{meta.get('provider') or '—'}` / `{meta.get('model') or '—'}` "
            f"@ temperature {_temperature(meta)}, "
            f"endpoint `{meta.get('endpoint') or '—'}`, decoding "
            f"{_decoding(meta)}, prompt "
            f"`{meta.get('prompt') or '—'}`, commit "
            f"`{str(meta.get('commit') or '')[:12]}`, "
            f"{meta.get('probe_count', 0)} probe(s) × "
            f"{meta.get('repeats', 1)} repeat(s)")


def _markdown(report: ExtractionReport,
              baseline: Optional[Mapping[str, Any]] = None) -> str:
    meta = report.meta
    lines = [f"# extraction — `{report.probes}`", ""]
    lines += [
        f"- **provider / model** `{meta.get('provider') or '—'}` / "
        f"`{meta.get('model') or '—'}`",
        f"- **temperature** {_temperature(meta)}",
        f"- **endpoint** `{meta.get('endpoint') or '—'}`",
        f"- **decoding** {_decoding(meta)}",
        f"- **prompt** `{meta.get('prompt') or '—'}` (both turns, digested; "
        f"the grammar is in the digest when one was sent)",
        f"- **commit** `{meta.get('commit', 'unknown')}`",
        f"- **date** {meta.get('date', '')}",
        f"- **probes** `{meta.get('probes_path') or '—'}` — "
        f"{meta.get('probe_count', 0)} × {meta.get('repeats', 1)} repeat(s) "
        f"= {len(report.attempts)} attempt(s)",
        "",
        "**Every number below is true of " + _identity(meta) + " and of "
        "nothing else.** A number without its interpreter beside it is not "
        "evidence — the 1.0.0 final gate is in `EVAL.md` §12, and this is "
        "that lesson written into the report rather than remembered.",
        "",
    ]

    lines.append("## the number")
    lines.append("")
    lines += _table(
        [[("**`" + name + "`**" if name == report.headline
           else f"`{name}`"), rate.text, rate.what]
         for name, rate in report.rates.items()],
        ["category", "k/n (95% Wilson)", "what one k is"])
    lines.append("")
    lines.append(
        f"**The headline is `{report.headline}`.** "
        + ("With repeats, the figure to quote is per PROBE and not per "
           "attempt: a probe counts only when EVERY one of its attempts was "
           "right, because a gatekeeper is a question about reliability and "
           "a store fed by a model that is right two times in three is a "
           "store with a third of its propositions wrong. No majority "
           "voting."
           if report.headline == HEADLINE_REPEATED else
           "This run asked each probe once, so the attempt-level figure and "
           "the per-probe figure are the same number. Re-run with "
           "`--repeats N` and `probe_reliable` becomes the one to quote."))
    lines.append("")
    lines.append("Intervals are binomial over the attempts in each row. "
                 "Propositions inside one probe are not independent of each "
                 "other, so `grounded`, `gold_precision` and `gold_recall` "
                 "have an interval that is a guide to their width and not a "
                 "test; and under `--repeats` the attempt-level `probe` "
                 "interval is **optimistic** for the same reason — N "
                 "attempts at one probe are not N independent draws. The "
                 "per-probe rows are the ones to argue from.")
    lines.append("")
    lines.append(
        "**`hedged` is not a failure rate and is not folded into any "
        "verdict.** It is the fraction of watching attempts where the model "
        "reached for what the probe was watching — a trap field, a key the "
        "receipt does not carry, one side of a conflict — and *marked that "
        "it was unsure*: hedged wrongness, a different class from the "
        "confident wrongness `trap` counts, and a deployment may tolerate "
        "one and not the other. Read the two together: a low `trap` with a "
        "high `hedged` is a model that is wrong carefully; both low is a "
        "model that is wrong flatly. Marking confidence is not punished "
        "here, because an instrument that punished it would teach the model "
        "to stop marking, and a harness that only ever rewards silence "
        "teaches silence.")
    lines.append("")
    if _pairing_value(meta, "constrained"):
        invalid = report.rates["constrained_invalid"]
        lines.append(
            "**This run was decoded under a grammar** — "
            "`response_format: json_schema`, compiled from this module's "
            "own status vocabulary and proposition keys — so it is a "
            "different experiment from an unconstrained one and its "
            "prompt digest says so. Read `structural`, `first_try` and "
            "`repair` against an unconstrained run of the same model: "
            "that difference is ROADMAP §2.9.5's lift, measured rather "
            "than assumed. Everything below `structural` is about "
            "CONTENT and a grammar cannot move it except by removing the "
            "unreadable replies from the denominators.")
        lines.append("")
        lines.append(
            f"`constrained_invalid` is {invalid.text} — "
            + ("every reply the grammar was sent with was readable, which "
               "is the endpoint doing what it was asked."
               if invalid.k == 0 else
               f"**{CONSTRAINED_YET_INVALID}**. An OpenAI-compatible "
               f"server may accept `response_format` and ignore it, and "
               f"nothing in `GET /models` says which kind is listening. "
               f"Read those rows' defects before quoting any number here: "
               f"an ASSERT that named no field or quoted nothing is the "
               f"model's content and is schema-valid, and only a reply "
               f"with no array or an unknown status word is proof the "
               f"grammar did not bind."))
        lines.append("")
    lines.append(
        "`conflict_surfaced` is scored the same way round: an answer that "
        "surfaces BOTH readings with their own sources passes exactly as an "
        "abstention does, because it serves the reader better. The one "
        "failure is asserting a single side as if nothing disagreed. So is "
        "a mask: transcribing the receipt's own withholding token under the "
        "key that holds it is a faithful report, and only a concrete value "
        "in its place is a fabrication.")
    lines.append("")

    lines.append("## by family")
    lines.append("")
    families = report.by_family()
    lines += _table(
        [[f"`{family}`", FAMILIES.get(family, ("", ""))[0],
          rates["probe_reliable"].text, rates["probe"].text,
          rates["structural"].text, rates["grounded"].text,
          rates["hedged"].text]
         for family, rates in families.items()],
        ["family", "kind", "probe_reliable", "probe", "structural",
         "grounded", "hedged"])
    lines.append("")
    lines += [f"- `{family}` — {FAMILIES.get(family, ('', ''))[1]}"
              for family in families]
    lines.append("")

    lines.append("## per probe")
    lines.append("")
    lines += _table(
        [[f"`{a.probe}`", a.family, a.kind, str(a.repeat), a.structural,
          str(a.asserts), f"{a.grounded}/{a.asserts}" if a.asserts else "—",
          f"{a.gold_hits}/{a.gold_total}" if a.gold_total else "—",
          _spectrum(a), "PASS" if a.verdict else "FAIL", _note(a)]
         for a in report.attempts],
        ["probe", "family", "kind", "rep", "structural", "asserts",
         "grounded", "gold", "stance", "verdict", "note"])
    lines.append("")
    lines.append("The `stance` column is the spectrum this instrument "
                 "refuses to collapse: `asserted` / `hedged` / `both sides` "
                 "/ `transcribed mask` / `silent` / `unreadable`. `verdict` "
                 "is the one pass/fail each probe needs and no more than "
                 "that — a gate is a deployment's dial and not a "
                 "measurement.")
    lines.append("")

    if baseline is not None:
        lines += _baseline_section(report, baseline)

    lines.append("This is ROADMAP §2.9.3's gatekeeper. It decides the phase "
                 "order of the 1.0→2.0 arc and nothing else: a wrong "
                 "proposition in an epistemic store is worse than a wrong "
                 "sentence in a transcript, because deterministic machinery "
                 "then derives from it with confidence.")
    return "\n".join(lines)


def _spectrum(attempt: Attempt) -> str:
    """Where this reply sat on the confident-to-silent spectrum.

    Reported per probe rather than inferred from the other columns, because
    it is the thing the rates were told not to collapse: *hedged wrong* and
    *confidently wrong* both read as one FAIL in the verdict column, and
    they are not the same result.
    """
    if not attempt.parsed:
        return "unreadable"
    parts: List[str] = []
    if attempt.mask_faithful:
        parts.append("transcribed mask")
    elif attempt.asserts:
        parts.append("asserted")
    if attempt.hedged:
        parts.append("hedged")
    if attempt.both_sides:
        parts.append("both sides")
    return "; ".join(parts) or "silent"


def _note(attempt: Attempt) -> str:
    """The shortest true thing about why a row reads as it does."""
    notes: List[str] = []
    if attempt.sprung:
        notes.append("asserted trap " + ", ".join(attempt.sprung))
    if attempt.hedged:
        notes.append("hedged " + ", ".join(attempt.hedged))
    if attempt.both_sides is False and attempt.asserts:
        notes.append("picked one side of a conflict")
    if attempt.mask_faithful is False and attempt.asserts:
        notes.append("a value where the receipt published a mask")
    if not notes and attempt.defects:
        notes.append("; ".join(attempt.defects))
    if attempt.constrained and not attempt.parsed:
        # Said FIRST, because it changes who the row is about: a grammar
        # the server enforced cannot emit a reply with no array in it or a
        # status outside the vocabulary. The defect stays beside it rather
        # than being replaced by it — the two rules a grammar cannot state
        # (an ASSERT naming no field, an ASSERT quoting nothing) fail here
        # too, and those are the model's content and not the endpoint's
        # doing, so the reader needs to see which one happened.
        notes.insert(0, CONSTRAINED_YET_INVALID)
    return "; ".join(notes)


# ── the baseline ─────────────────────────────────────────────────────────────

def _probe_scores(attempts: Sequence[Mapping[str, Any]]
                  ) -> Dict[str, Tuple[int, int]]:
    """Probe id → (attempts that passed, attempts made).

    **Every** attempt, not the last one.  A baseline read with last-wins
    would compare one die against a whole run, and under ``--repeats`` that
    is most of the evidence thrown away.
    """
    out: Dict[str, List[int]] = {}
    for entry in attempts:
        name = str(entry.get("probe") or "")
        if not name:
            continue
        row = out.setdefault(name, [0, 0])
        row[0] += 1 if entry.get("verdict") else 0
        row[1] += 1
    return {name: (passed, made) for name, (passed, made) in out.items()}


def _baseline_delta(report: ExtractionReport,
                    baseline: Mapping[str, Any]) -> Dict[str, Any]:
    """The paired comparison, as data — the JSON mirror of the section."""
    before = baseline.get("meta") or {}
    differing = [name for name in PAIRING
                 if _pairing_value(before, name)
                 != _pairing_value(report.meta, name)]
    then = _probe_scores(baseline.get("attempts") or [])
    now = _probe_scores([a.as_dict() for a in report.attempts])
    shared = [name for name in now if name in then]
    return {
        "differs_in": differing,
        "comparable": len(shared),
        "probes_now": len(now),
        "probes_then": len(then),
        "rates": {
            name: {"baseline": (baseline.get("rates") or {}).get(name),
                   "now": rate.as_dict()}
            for name, rate in report.rates.items()},
        "changed": [{"probe": name, "baseline": list(then[name]),
                     "now": list(now[name])}
                    for name in shared if then[name] != now[name]],
    }


def _baseline_section(report: ExtractionReport,
                      baseline: Mapping[str, Any]) -> List[str]:
    """Paired deltas against an earlier report, with the pairing questioned.

    A delta between two models — or two corpora, or two repeat counts — is
    not a delta, so the first thing printed is whether the experiment was
    the same one.
    """
    delta = _baseline_delta(report, baseline)
    before = baseline.get("meta") or {}
    lines = ["## against the baseline", ""]
    lines.append(f"- **baseline** {_identity(before)}")
    lines.append(f"- **this run** {_identity(report.meta)}")
    if delta["differs_in"]:
        lines.append(f"- ⚠ the two differ in {delta['differs_in']} — the "
                     f"rows below are a difference between two experiments "
                     f"as much as between two trees")
    lines.append("")

    now = report.rates
    was = baseline.get("rates") or {}
    rows = []
    for name, rate in now.items():
        old = was.get(name) or {}
        old_rate = old.get("rate")
        change = ("—" if old_rate is None or rate.value is None
                  else f"{(rate.value - old_rate) * 100:+.1f} pp")
        rows.append([f"`{name}`",
                     "—" if old_rate is None
                     else f"{old.get('k')}/{old.get('n')} = {old_rate:.0%}",
                     rate.text, change])
    lines += _table(rows, ["category", "baseline", "now", "delta"])
    lines.append("")

    lines.append(f"**{delta['comparable']} of {delta['probes_now']} probes "
                 f"are comparable** — present in both reports by id "
                 f"(the baseline holds {delta['probes_then']}).")
    lines.append("")
    if not delta["comparable"]:
        lines.append("No probe is comparable between these two reports, so "
                     "nothing below could have changed verdict and the "
                     "absence of a table is not agreement. Check the "
                     "`probes` path in both headers.")
    elif delta["changed"]:
        lines.append("### probes whose pass rate changed")
        lines.append("")
        lines += _table(
            [[f"`{row['probe']}`", f"{row['baseline'][0]}/{row['baseline'][1]}",
              f"{row['now'][0]}/{row['now'][1]}"]
             for row in delta["changed"]],
            ["probe", "baseline passed", "now passed"])
    else:
        lines.append(f"No probe changed its pass rate across the "
                     f"{delta['comparable']} comparable.")
    lines.append("")
    return lines


def _table(rows: Sequence[Sequence[str]], header: Sequence[str]) -> List[str]:
    return ["| " + " | ".join(header) + " |",
            "|" + "|".join("---" for _ in header) + "|",
            *["| " + " | ".join(row) + " |" for row in rows]]


# ── running it ───────────────────────────────────────────────────────────────

#: One model call: a list of chat messages in, the reply text out.  The
#: whole seam a test replaces, and the only thing a test has to replace.
Ask = Callable[[Sequence[Mapping[str, str]]], str]


def progress(message: str) -> None:
    """The running commentary, on **stderr**.

    ``--json`` writes a document to stdout that a caller pipes into a
    parser, and a progress line in the middle of it is a parse error fifty
    probes in.  Stdout is the result; stderr is the narration — the same
    division the exit contract makes for a mission's own stream.
    """
    print(message, file=sys.stderr)


def run_probes(probes: Sequence[Probe], ask: Ask, *, repeats: int = 1,
               max_seconds: Optional[float] = None,
               constrained: bool = False,
               log=progress) -> Tuple[Attempt, ...]:
    """Ask every probe *repeats* times and score each answer.

    One call, then at most one repair — never a third: a loop that kept
    asking would measure how long a model takes to stumble into the shape,
    and §2.9.3's number is about the first answer and the cost of fixing
    it.

    *constrained* says whether *ask* carries the compiled grammar — it is
    :func:`asker`'s to attach and this function's only to record, which is
    why it is a flag here and not a schema.  **The repair loop stays under
    a grammar.**  A reply the decoder held to the shape can still be wrong
    about the receipt, and it can still fail the rules a grammar cannot
    state (an ASSERT whose ``field`` is the empty string is schema-valid
    and unusable); repair is about content, and removing it under
    ``--constrained`` would change two things at once in an A/B built to
    change one.

    *max_seconds* bounds the whole run.  A measurement against a cold or
    slow endpoint is otherwise unbounded, and the house rule is that no
    command is: a run that is cut short raises :class:`Unextractable`
    rather than reporting a partial sample as a score.
    """
    attempts: List[Attempt] = []
    repeats = max(1, int(repeats))
    total = len(probes) * repeats
    started = time.monotonic()
    for repeat in range(1, repeats + 1):
        for probe in probes:
            if max_seconds is not None and \
                    time.monotonic() - started > float(max_seconds):
                raise Unextractable(
                    f"the wall budget of {max_seconds:g} s ran out with "
                    f"{len(attempts)} of {total} attempts scored; raise "
                    f"--max-seconds or narrow the corpus with --only")
            messages: List[Dict[str, str]] = [
                {"role": "user", "content": prompt_for(probe)}]
            reply = _ask(ask, messages, probe, len(attempts), total)
            propositions, defect = parse_propositions(reply)
            structural, defects, replies = FIRST, [], [reply]
            if defect:
                messages += [{"role": "assistant", "content": reply},
                             {"role": "user", "content": repair_for(defect)}]
                reply = _ask(ask, messages, probe, len(attempts), total)
                replies.append(reply)
                defects.append(defect)
                propositions, second = parse_propositions(reply)
                if second:
                    defects.append(second)
                    structural = INVALID
                    propositions = ()
                else:
                    structural = REPAIRED
            attempt = score_attempt(probe, propositions, structural,
                                    repeat=repeat, defects=defects,
                                    replies=replies, constrained=constrained)
            attempts.append(attempt)
            log(f"  [{len(attempts)}/{total}] {attempt.probe} "
                f"[{attempt.family}] {attempt.structural} — "
                f"{'PASS' if attempt.verdict else 'FAIL'}")
    return tuple(attempts)


def _ask(ask: Ask, messages: Sequence[Mapping[str, str]], probe: Probe,
         done: int, total: int) -> str:
    try:
        return str(ask(messages) or "")
    except Exception as exc:                     # noqa: BLE001 — any failure
        raise Unextractable(
            f"the endpoint stopped answering at probe {probe.id!r} "
            f"({done} of {total} attempts scored): {exc}") from exc


def asker(provider: str, model: Optional[str] = None, *,
          temperature: Optional[float] = None,
          json_schema: Optional[Mapping[str, Any]] = None) -> Ask:
    """One model call per probe, through the package's one backend door.

    :class:`core.unified_client.UnifiedClient` is where a provider name
    becomes a backend everywhere else in this tree — see
    :func:`core.eval.measure.probe_capabilities`, which opens the same door
    to ask what an endpoint can do — and the model name is resolved by
    :func:`core.runtime.provider_config.resolve_model`, which owns the
    order ``--model`` beats a persona beats what the endpoint serves.
    Reaching past either would be a second router, and a measurement run
    against an endpoint nobody can name afterwards.

    *temperature* unset sends none, which is the same decision the mission
    CLI makes: pinning zero would make the model easier to measure by
    making it a different model, and the header says "server default" so
    the reader knows which was in force.

    *json_schema* is the compiled grammar — :func:`proposition_schema` —
    and it is **refused up front** on a backend that does not declare
    :attr:`~core.runtime.backends.base.BackendCapabilities.supports_json_schema`.
    Refused rather than dropped, and refused before the first probe rather
    than at the first reply: a run that asked for a constrained decode,
    quietly got an unconstrained one and printed "constrained" in its
    header would be an instrument lying about its own experiment, which is
    the one defect no downstream reading could recover from.  Read through
    ``getattr`` with a ``False`` default, like every other capability
    question in this tree: a client that never heard of capabilities has
    not declared this one.
    """
    from core.runtime.provider_config import resolve_model
    from core.unified_client import UnifiedClient

    client = UnifiedClient(provider_override=provider)
    if json_schema is not None and not getattr(
            getattr(client, "capabilities", None),
            "supports_json_schema", False):
        raise Unextractable(
            f"--constrained: the {provider!r} backend does not declare "
            f"supports_json_schema, so the grammar would not be enforced "
            f"and this run would be unconstrained under a constrained "
            f"name. Drop --constrained to measure the plain ask, or point "
            f"--provider at a backend that declares it.")
    name = resolve_model(provider, model, served=lambda: client.default_model)
    # Everything this measurement adds to a bare completion: the sampling
    # it pinned, and the grammar it compiled. Built once, sent on every
    # probe and on every repair turn — a repair asked without the schema
    # would be a second, unconstrained experiment inside the first.
    request: Dict[str, Any] = ({} if temperature is None
                               else {"temperature": temperature})
    if json_schema is not None:
        request["json_schema"] = dict(json_schema)

    def ask(messages: Sequence[Mapping[str, str]]) -> str:
        reply = client.chat(name, [dict(m) for m in messages], False,
                            **request)
        return "" if reply is None else str(reply)

    ask.model = name                             # type: ignore[attr-defined]
    return ask


def header(probes: Sequence[Probe], path: Path, *, provider: str = "",
           model: str = "", temperature: Optional[float] = None,
           repeats: int = 1, constrained: bool = False,
           env: Optional[Mapping[str, str]] = None
           ) -> Dict[str, Any]:
    """What produced these numbers.  ``measure``'s vocabulary, wider by the
    four fields that move an extraction rate and that a matrix row does
    not vary: the temperature, the prompt digest, whether the decode was
    constrained, and which corpus ran."""
    from core.eval.measure import commit_of, scrubbed

    env = os.environ if env is None else env
    return {
        "commit": commit_of(),
        "date": date.today().isoformat(),
        "provider": provider,
        "model": model,
        "temperature": temperature,
        "endpoint": scrubbed(env.get("LOCAL_API_BASE", "")),
        "constrained": bool(constrained),
        "prompt": prompt_fingerprint(bool(constrained)),
        "probes_path": str(path),
        "probe_count": len(probes),
        "repeats": int(repeats),
        "python": sys.version.split()[0],
    }


# ── the command line ─────────────────────────────────────────────────────────

def add_parser(subs) -> argparse.ArgumentParser:
    """Register ``extraction`` on :func:`core.eval.run._parser`'s subparsers.

    From here rather than written out in ``run.py``, the way ``measure``
    registers itself: a flag added to this measurement without a parser to
    read it is a mismatch this arrangement makes impossible.

    It takes **no** ``--suite``: a probe is not a mission, there is nothing
    to spawn and nothing to hold out, and requiring a gradeable suite to
    measure a receipt would be a check of something this subcommand never
    reads.
    """
    parser = subs.add_parser(
        "extraction",
        help="measure how reliably a model turns real tool receipts into "
             "typed propositions, with abstention")
    parser.add_argument("--probes", required=True, type=Path, metavar="PATH",
                        help="the JSONL probe corpus; the one this "
                             "repository ships is "
                             "tests/fixtures/extraction/probes.jsonl")
    parser.add_argument("--provider", default=None,
                        help="which backend answers; defaults to "
                             "ELF_PROVIDER")
    parser.add_argument("--model", default=None,
                        help="the model name to send; unset asks the "
                             "endpoint what it serves")
    parser.add_argument("--temperature", type=float, default=None,
                        help="pinned for this measurement; unset sends the "
                             "server's own default and the report says so")
    parser.add_argument(
        "--constrained", action="store_true",
        help="send the compiled proposition grammar with every call "
             "(ROADMAP §2.9.5), so the endpoint holds the decode to it. "
             "Refused up front on a backend that does not declare "
             "supports_json_schema — never a quiet fallback — and stamped "
             "into the report's identity, because a constrained run and an "
             "unconstrained one are two experiments")
    parser.add_argument("--repeats", type=int, default=1, metavar="N",
                        help="ask every probe N times (default 1); with "
                             "N > 1 the headline becomes `probe_reliable`")
    parser.add_argument("--only", action="append", default=[], metavar="ID",
                        help="measure only this probe; repeatable")
    parser.add_argument("--max-seconds", type=float, default=None,
                        metavar="S",
                        help="wall-clock bound on the WHOLE run; a run cut "
                             "short is refused rather than reported")
    parser.add_argument("--report", type=Path, metavar="STEM",
                        help="write <stem>.md and <stem>.json here; only a "
                             "literal .md is stripped, and any other dotted "
                             "ending is refused rather than guessed at")
    parser.add_argument("--baseline", type=Path, metavar="PATH",
                        help="an earlier report.json; its rates are printed "
                             "beside these as paired deltas")
    parser.add_argument("--json", action="store_true",
                        help="print JSON to stdout instead of the Markdown "
                             "tables; progress goes to stderr either way")
    return parser


#: What is printed, loudly, when nothing parsed at all.  Module level
#: because the rule it states is the whole reason for the exit code: a run
#: where every reply was unreadable is a fault in the endpoint, the prompt
#: or the plumbing, and reporting `structural 0/49` as a model's score
#: would be attributing somebody's outage to a model.
ALL_INVALID = (
    "!!! EVERY reply was unreadable. This is an endpoint, prompt or "
    "plumbing fault and NOT a model score — do not quote these numbers. "
    "Read the `replies` in the report: an empty string means nothing came "
    "back, a refusal means the endpoint answered something else, and the "
    "same prose every time means the model never saw the array "
    "instruction."
)


def report_stem(path: Path) -> Path:
    """Where the two renderings go, from what the caller wrote.

    **Only a literal ``.md`` is stripped**, and nothing else is guessed at.
    ``Path.suffix`` calls ``.13-run`` a suffix of ``out/2026.09.13-run``,
    so a stem taken by stripping whatever ``suffix`` reports would have
    written that run's report to ``out/2026.09.md`` and ``out/2026.09.json``
    — silently, under a name from another day. Anything that is not a bare
    path or a ``.md`` one is refused instead: see :func:`_report_refusal`.
    """
    return path.with_suffix("") if path.suffix == ".md" else path


def _report_refusal(path: Path) -> str:
    """Why this ``--report`` path cannot be used, or ``""``."""
    if path.suffix in ("", ".md"):
        return ""
    if path.suffix == ".json":
        return ("--report takes the path WITHOUT a suffix, or with `.md`: "
                "both a Markdown and a JSON rendering are written beside "
                "each other, and a `.json` argument would name them both")
    return (f"--report takes the path WITHOUT a suffix, or with `.md`, and "
            f"{str(path)!r} ends in {path.suffix!r}. Only a literal `.md` is "
            f"stripped, because a path like `out/2026.09.13-run` has "
            f"`.13-run` for a suffix and stripping it would write this run's "
            f"report under `out/2026.09.md` — a name from another day. Write "
            f"it as `{path}` with no dot in the last segment, or add `.md`")


def from_args(args: argparse.Namespace) -> int:
    """``extraction`` as :func:`core.eval.run.main` reaches it."""
    if int(args.repeats) < 1:
        print(f"--repeats wants a positive count, got {args.repeats}; "
              f"zero repeats is not a measurement", file=sys.stderr)
        return 2
    if args.max_seconds is not None and float(args.max_seconds) <= 0:
        print(f"--max-seconds wants a positive budget, got "
              f"{args.max_seconds}", file=sys.stderr)
        return 2
    if args.report is not None:
        refusal = _report_refusal(args.report)
        if refusal:
            print(refusal, file=sys.stderr)
            return 2

    try:
        probes = load_probes(args.probes)
    except ProbeMisdeclared as exc:
        print(f"extraction: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"--probes: {exc}", file=sys.stderr)
        return 2

    if args.only:
        wanted = list(dict.fromkeys(args.only))
        known = {probe.id for probe in probes}
        unknown = [name for name in wanted if name not in known]
        if unknown:
            print(f"--only names {unknown}, which this corpus does not hold",
                  file=sys.stderr)
            return 2
        probes = tuple(probe for probe in probes if probe.id in wanted)

    provider = (args.provider or os.getenv("ELF_PROVIDER") or "").strip()
    if not provider:
        print("extraction: name the backend with --provider (or set "
              "ELF_PROVIDER); this subcommand needs a model", file=sys.stderr)
        return 2
    # Compiled ONCE, here, and handed to the asker: one grammar for the
    # whole run is what makes the fingerprint in the header true of every
    # call under it.
    constrained = bool(getattr(args, "constrained", False))
    schema = proposition_schema() if constrained else None
    try:
        ask = asker(provider, args.model, temperature=args.temperature,
                    json_schema=schema)
    except Unextractable as exc:
        # The capability refusal, and it is not "no backend": the backend
        # is there and cannot do the thing that was asked for, which is a
        # different sentence and a different fix.
        print(f"extraction: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:                     # noqa: BLE001 — any failure
        print(f"extraction: no backend for --provider {provider!r}: {exc}",
              file=sys.stderr)
        return 2

    baseline: Optional[Mapping[str, Any]] = None
    if args.baseline is not None:
        try:
            baseline = json.loads(Path(args.baseline).read_text(
                encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"--baseline: {exc}", file=sys.stderr)
            return 2

    try:
        attempts = run_probes(probes, ask, repeats=args.repeats,
                              max_seconds=args.max_seconds,
                              constrained=constrained)
    except Unextractable as exc:
        print(f"extraction: {exc}", file=sys.stderr)
        return 2

    report = ExtractionReport(
        probes=Path(args.probes).name, attempts=attempts,
        families=tuple(dict.fromkeys(probe.family for probe in probes)),
        meta=header(probes, Path(args.probes), provider=provider,
                    model=str(getattr(ask, "model", "") or args.model or ""),
                    temperature=args.temperature, repeats=args.repeats,
                    constrained=constrained))

    print(report.to_json(baseline=baseline) if args.json
          else report.to_markdown(baseline))
    if args.report is not None:
        stem = report_stem(args.report)
        stem.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(stem.with_suffix(".md"),
                          report.to_markdown(baseline))
        atomic_write_text(stem.with_suffix(".json"),
                          report.to_json(baseline=baseline))

    if attempts and not any(a.parsed for a in attempts):
        print(ALL_INVALID, file=sys.stderr)
        return 2
    return 0
