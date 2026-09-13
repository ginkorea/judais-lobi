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
asserts is in the receipt, under the field it names — and (c) **abstaining
where the receipt is silent**.  The third is the one that decides the phase
order.  A model that asserts confidently where there is nothing to assert
does not become safe by having its output typed; it becomes harder to catch,
because the type says a fact was extracted.

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
  :func:`core.runtime.grounding.same_value`.  A second JSON harvester here
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

**What is deliberately not here.**  No few-shot examples and no constrained
decoding.  §2.9.3 names both as the lift to try *if the number is bad*, and
§2.9.5 makes the grammar compiler a phase of its own — so the baseline has
to be the plain ask, or the lift has nothing to be measured against.  One
reprompt is allowed, because a structurally invalid reply is a failure class
whose **repair rate** is itself part of the finding, and it is counted and
printed rather than folded into the success.

The probe corpus is data and lives in ``tests/fixtures/extraction``; this
module names no probe, no tool and no deployment.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import (Any, Callable, Dict, List, Mapping, Optional, Sequence,
                    Tuple)

from core.durable import atomic_write_text
from core.runtime.grounding import harvest_fields, json_blocks, same_value

__all__ = [
    "ASSERT", "STATUSES", "KINDS", "FAMILIES", "CATEGORIES",
    "FIRST", "REPAIRED", "INVALID",
    "Probe", "ProbeMisdeclared", "Proposition", "Attempt", "Rate",
    "ExtractionReport", "Unextractable",
    "PROMPT", "REPAIR", "prompt_for", "repair_for", "prompt_fingerprint",
    "load_probes", "parse_propositions", "fields_of", "grounds",
    "score_attempt", "rates_of", "wilson", "run_probes", "asker", "header",
    "add_parser", "from_args",
]


# ── the vocabulary ───────────────────────────────────────────────────────────

#: The one status that is a claim about the world.  Everything else in
#: :data:`STATUSES` is a way of not making one, and the difference is the
#: whole measurement: a store may take an ``ASSERT`` and derive from it.
ASSERT = "ASSERT"

#: The status vocabulary ROADMAP §2.9.3 names, in the order the prompt
#: offers them.  A reply using a word that is not here is a **structural**
#: failure and not a wrong answer: a downstream store would not know what
#: to do with it, which is a different defect from knowing and being wrong.
STATUSES: Tuple[str, ...] = (
    ASSERT, "HYPOTHESIZE", "AMBIGUOUS", "CONTRADICTED",
    "INSUFFICIENT_EVIDENCE",
)

#: The three things a probe can expect.  ``assert`` — the facts are in the
#: receipt.  ``abstain`` — they are not, and the correct extractor says so.
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
        "two receipts about one subject disagree; a single ASSERT of "
        "either one is the failure, measured live on a deployment "
        "6 Sep 2026 (one status tool says the id is unknown, another says "
        "it completed)"),
    "masked": (
        "abstain",
        "the record exists and its material is withheld by handling; the "
        "asserted zero is a fabrication and so is the mask text"),
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
        "an optional field that hides rather than selects: the measured "
        "20b filled `submitted_via` 8/8 and never saw the real rows"),
}


class ProbeMisdeclared(ValueError):
    """A probe file this module refuses to measure anything with.

    Loud rather than skipped, for :class:`core.eval.suite.Mission`'s
    reason: a probe whose gold is not in its own evidence would score every
    correct extractor as a fabricator, and the number would be about the
    corpus.
    """


class Unextractable(RuntimeError):
    """The endpoint stopped answering, so there is no number to print.

    Raised rather than scored.  An endpoint that fell over halfway is not
    a model that abstained, and recording its silence as an abstention is
    the one way this measurement could flatter a model by breaking.
    """


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

    @property
    def gold_fields(self) -> Tuple[str, ...]:
        return tuple(field for field, _value in self.gold)


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
    kind = str(expect.get("kind") or "").strip()
    if kind not in KINDS:
        raise ProbeMisdeclared(
            f"{where}: kind {kind!r} is not one of {list(KINDS)}")
    if kind != FAMILIES[family][0]:
        raise ProbeMisdeclared(
            f"{where}: family {family!r} is scored as "
            f"{FAMILIES[family][0]!r} and this probe declares {kind!r}")

    gold = tuple((str(item.get("field") or ""), item.get("value"))
                 for item in (expect.get("gold") or ())
                 if isinstance(item, Mapping))
    trap_fields = tuple(str(name) for name in (expect.get("trap_fields") or ()))
    absent = tuple(str(name) for name in (expect.get("absent_fields") or ()))

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

    evidence = str(raw.get("evidence") or "")
    question = str(raw.get("question") or "").strip()
    if not evidence.strip() or not question:
        raise ProbeMisdeclared(f"{where}: a probe needs evidence and a "
                               f"question")
    return Probe(id=identifier, family=family,
                 source=str(raw.get("source") or ""), evidence=evidence,
                 question=question, kind=kind, gold=gold,
                 trap_fields=trap_fields, absent_fields=absent)


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
  "quote"  - the span of the receipt this proposition is read off

The rules:

* ASSERT only a fact the receipt states, under a key the receipt actually
  carries, with the value that key actually holds.
* If the receipt does not carry the fact the question asks for, answer with
  a single proposition whose status is INSUFFICIENT_EVIDENCE. A near miss
  is not the fact: a key whose NAME resembles the question, or one that
  measures something else, is not an answer to it.
* If two parts of the receipt say different things about the same subject,
  say CONTRADICTED and give a proposition for each.
* If the receipt says a value is masked, withheld or restricted, or that
  its own coverage was partial, do not assert what it withheld and do not
  read an empty result as an absence.
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


def prompt_fingerprint() -> str:
    """A short digest of both turns.

    In the header beside the model, because the prompt is half of what
    produced the number: two reports of the same model at the same
    temperature are comparable only if this string matches, and a reader
    with no way to check that would compare them anyway.
    """
    material = (PROMPT + "\x00" + REPAIR + "\x00" + "|".join(STATUSES))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:12]


# ── the reply ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Proposition:
    """One element of a reply that parsed."""

    status: str
    field: str
    value: Any
    quote: str

    def as_dict(self) -> Dict[str, Any]:
        return {"status": self.status, "field": self.field,
                "value": self.value, "quote": self.quote}


def parse_propositions(reply: Any) -> Tuple[Tuple[Proposition, ...], str]:
    """*reply* as propositions, or ``((), defect)`` naming the first fault.

    A **string** rather than an exception, and a scored outcome rather than
    a crash: "this model cannot reliably emit the shape" is one of the
    things being measured, and a harness that died on it would have no way
    to say how often.

    :func:`core.runtime.grounding.json_blocks` finds the array, so a model
    that wrapped it in a fence or a sentence is read rather than failed —
    that is packaging and not structure, and ROADMAP §2.9.5's grammar
    compiler is the answer to it.  What IS structure: the array is there,
    it is not empty, every element is an object, every ``status`` is a word
    the vocabulary holds, and every ASSERT carries a field, a value that is
    a string or a number, and the quote it was read off.

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
            if isinstance(value, bool) or not isinstance(
                    value, (str, int, float)):
                return (), (f"{where} ASSERTs a value that is not a string "
                            f"or a number")
            if not quote.strip():
                return (), f"{where} ASSERTs and quotes nothing"
        out.append(Proposition(status=status, field=name.strip(), value=value,
                               quote=quote))
    return tuple(out), ""


# ── the evidence ─────────────────────────────────────────────────────────────

def fields_of(evidence: str) -> Tuple[set, Dict[str, List[Any]]]:
    """The receipt's keys, and every scalar each of them holds.

    One walker, and it is not this module's:
    :func:`core.runtime.grounding.json_blocks` parses and
    :func:`core.runtime.grounding.harvest_fields` walks, with its
    ``scalars`` sink so a string value — a status word, an outcome, a
    handle — comes back as well as a figure.  See that function: the second
    reader it was promoted for is this one.
    """
    keys: set = set()
    numbers: dict = {}
    scalars: Dict[str, List[Any]] = {}
    for payload in json_blocks(evidence):
        try:
            harvest_fields(payload, keys, numbers, scalars=scalars)
        except RecursionError:                   # pragma: no cover - guard
            continue
    return keys, scalars


def grounds(proposition: Proposition, keys: set,
            scalars: Mapping[str, Sequence[Any]]) -> bool:
    """Whether the receipt holds *proposition*'s value under its field.

    **Both halves, and the field half is the one that matters.**  A large
    receipt answers "is this number in here" yes for a great many numbers;
    what a downstream store joins on is the LABEL, and an extraction that
    put a real value under the wrong key has produced a proposition that is
    wrong in exactly the way nothing later can catch.  Weakening this to
    "the value is somewhere in the evidence" is the mutation this check
    exists to fail.

    The arithmetic is :func:`core.runtime.grounding.same_value` — the
    grounding module's rule, so a proposition this measurement calls
    grounded is one that module would too.  One loosening on top of it,
    stated rather than hidden: a string re-cased is the same fact, and a
    number that counted ``Pass`` against ``pass`` would be measuring
    capitalisation.
    """
    name = proposition.field.strip()
    if not name or name not in keys:
        return False
    found = scalars.get(name)
    if not found:
        # The key is real and holds an object or a list. The value beside
        # it cannot be confirmed from a scalar, and an unconfirmable
        # assertion is not a grounded one — the difference from
        # `FieldAttributionCheck`, which must not ACCUSE on that evidence
        # where this must not COUNT it.
        return False
    claimed = proposition.value
    for value in found:
        if same_value(claimed, value):
            return True
        if isinstance(claimed, str) and isinstance(value, str) and \
                claimed.strip().casefold() == value.strip().casefold():
            return True
    return False


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
    #: How many ASSERTs the reply carried, and how many of them the receipt
    #: actually supports at the field they named.
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
    #: The trap fields this attempt asserted from, for the table.
    sprung: Tuple[str, ...] = ()

    @property
    def parsed(self) -> bool:
        return self.structural != INVALID

    @property
    def verdict(self) -> bool:
        """Whether this attempt answered its probe correctly, all of it.

        Per kind, and strictly: an ``assert`` probe wants every gold fact
        and nothing else; an ``abstain`` probe wants no assertion at all; a
        ``trap`` probe wants the gold facts with the trap left alone.  An
        unreadable reply is never correct — see :func:`score_attempt`.
        """
        if not self.parsed:
            return False
        if self.kind == "abstain":
            return bool(self.abstained)
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
            "trap_clean": self.trap_clean, "sprung": list(self.sprung),
            "verdict": self.verdict,
        }


def score_attempt(probe: Probe, propositions: Sequence[Proposition],
                  structural: str, *, repeat: int = 1,
                  defects: Sequence[str] = (),
                  replies: Sequence[str] = ()) -> Attempt:
    """Every number this report knows how to take, from one reply.

    **An unreadable reply did not abstain.**  It has no ASSERTs, so a
    naive abstention rule would score it a pass on every ``abstain`` probe
    and a trap-resistance pass on every trap — a model that emits prose
    would then look safest of all.  What is being measured is whether a
    *store* can be fed from this model, and a store cannot be fed prose, so
    :data:`INVALID` fails both.
    """
    keys, scalars = fields_of(probe.evidence)
    asserted = [p for p in propositions if p.status == ASSERT]
    grounded = sum(1 for p in asserted if grounds(p, keys, scalars))

    gold_hits = 0
    for name, value in probe.gold:
        if any(p.field.strip() == name and _same_text(p.value, value)
               for p in asserted):
            gold_hits += 1
    off_gold = sum(1 for p in asserted
                   if not any(p.field.strip() == name
                              and _same_text(p.value, value)
                              for name, value in probe.gold))

    abstained: Optional[bool] = None
    if probe.kind == "abstain":
        abstained = structural != INVALID and not asserted
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
        trap_clean=trap_clean, sprung=sprung)


def _same_text(claimed: Any, gold: Any) -> bool:
    """Gold comparison: the grounding rule, plus the re-casing allowance.

    The same pair :func:`grounds` uses, so a proposition cannot be counted
    grounded and gold-missing for a reason that is only about case.
    """
    if same_value(claimed, gold):
        return True
    return (isinstance(claimed, str) and isinstance(gold, str)
            and claimed.strip().casefold() == gold.strip().casefold())


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
    ("grounded", "ASSERTs whose value the receipt holds under the field "
                 "they name"),
    ("gold_precision", "ASSERTs that are a fact the probe asked for"),
    ("gold_recall", "facts the probe asked for that were asserted"),
    ("abstention", "abstain probes answered with no assertion at all"),
    ("trap", "trap probes answered without asserting from the trap field"),
    ("probe", "probes answered correctly and completely, all kinds"),
)


def rates_of(attempts: Sequence[Attempt]) -> Dict[str, Rate]:
    """Every category of :data:`CATEGORIES`, over *attempts*."""
    what = dict(CATEGORIES)
    parsed = [a for a in attempts if a.parsed]
    gold_bearing = [a for a in attempts if a.kind != "abstain"]
    abstaining = [a for a in attempts if a.kind == "abstain"]
    traps = [a for a in attempts if a.kind == "trap"]

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
                           len([a for a in abstaining if a.abstained]),
                           len(abstaining)),
        "trap": rate("trap", len([a for a in traps if a.trap_clean]),
                     len(traps)),
        "probe": rate("probe", len([a for a in attempts if a.verdict]),
                      len(attempts)),
    }


# ── the report ───────────────────────────────────────────────────────────────

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

    def by_family(self) -> Dict[str, Dict[str, Rate]]:
        out: Dict[str, Dict[str, Rate]] = {}
        for family in self.families or tuple(
                dict.fromkeys(a.family for a in self.attempts)):
            out[family] = rates_of(
                [a for a in self.attempts if a.family == family])
        return out

    def as_dict(self) -> Dict[str, Any]:
        return {
            "probes": self.probes,
            "meta": dict(self.meta),
            "rates": {name: r.as_dict() for name, r in self.rates.items()},
            "by_family": {family: {name: r.as_dict()
                                   for name, r in rates.items()}
                          for family, rates in self.by_family().items()},
            "attempts": [a.as_dict() for a in self.attempts],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.as_dict(), indent=indent, sort_keys=False)

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


def _identity(meta: Mapping[str, Any]) -> str:
    """The one line every number in this report is only true beside."""
    return (f"`{meta.get('provider') or '—'}` / `{meta.get('model') or '—'}` "
            f"@ temperature {_temperature(meta)}, "
            f"endpoint `{meta.get('endpoint') or '—'}`, prompt "
            f"`{meta.get('prompt') or '—'}`, commit "
            f"`{str(meta.get('commit') or '')[:12]}`")


def _markdown(report: ExtractionReport,
              baseline: Optional[Mapping[str, Any]] = None) -> str:
    meta = report.meta
    lines = [f"# extraction — `{report.probes}`", ""]
    lines += [
        f"- **provider / model** `{meta.get('provider') or '—'}` / "
        f"`{meta.get('model') or '—'}`",
        f"- **temperature** {_temperature(meta)}",
        f"- **endpoint** `{meta.get('endpoint') or '—'}`",
        f"- **prompt** `{meta.get('prompt') or '—'}` (both turns, digested)",
        f"- **commit** `{meta.get('commit', 'unknown')}`",
        f"- **date** {meta.get('date', '')}",
        f"- **probes** {meta.get('probe_count', 0)} × {meta.get('repeats', 1)}"
        f" repeat(s) = {len(report.attempts)} attempt(s)",
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
        [[f"`{name}`", rate.text, rate.what]
         for name, rate in report.rates.items()],
        ["category", "k/n (95% Wilson)", "what one k is"])
    lines.append("")
    lines.append("Intervals are binomial over the attempts in each row. "
                 "Propositions inside one probe are not independent of each "
                 "other, so `grounded`, `gold_precision` and `gold_recall` "
                 "have an interval that is a guide to their width and not a "
                 "test — the per-probe rows are the ones to argue from.")
    lines.append("")

    lines.append("## by family")
    lines.append("")
    families = report.by_family()
    lines += _table(
        [[f"`{family}`", FAMILIES.get(family, ("", ""))[0],
          rates["probe"].text, rates["structural"].text,
          rates["grounded"].text]
         for family, rates in families.items()],
        ["family", "kind", "probe", "structural", "grounded"])
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
          "PASS" if a.verdict else "FAIL",
          "; ".join(a.sprung) or ("; ".join(a.defects) if a.defects else "")]
         for a in report.attempts],
        ["probe", "family", "kind", "rep", "structural", "asserts",
         "grounded", "gold", "verdict", "note"])
    lines.append("")

    if baseline is not None:
        lines += _baseline_section(report, baseline)

    lines.append("This is ROADMAP §2.9.3's gatekeeper. It decides the phase "
                 "order of the 1.0→2.0 arc and nothing else: a wrong "
                 "proposition in an epistemic store is worse than a wrong "
                 "sentence in a transcript, because deterministic machinery "
                 "then derives from it with confidence.")
    return "\n".join(lines)


def _baseline_section(report: ExtractionReport,
                      baseline: Mapping[str, Any]) -> List[str]:
    """Paired deltas against an earlier report, with the pairing questioned.

    A delta between two models is not a delta, so the first thing printed
    is whether the interpreter was the same one.
    """
    before = baseline.get("meta") or {}
    lines = ["## against the baseline", ""]
    lines.append(f"- **baseline** {_identity(before)}")
    lines.append(f"- **this run** {_identity(report.meta)}")
    differing = [name for name in
                 ("provider", "model", "temperature", "endpoint", "prompt")
                 if before.get(name) != report.meta.get(name)]
    if differing:
        lines.append(f"- ⚠ the two differ in {differing} — the rows below "
                     f"are a difference between two interpreters as much as "
                     f"between two trees")
    lines.append("")

    now = report.rates
    was = baseline.get("rates") or {}
    rows = []
    for name, rate in now.items():
        old = was.get(name) or {}
        old_rate = old.get("rate")
        delta = ("—" if old_rate is None or rate.value is None
                 else f"{(rate.value - old_rate) * 100:+.1f} pp")
        rows.append([f"`{name}`",
                     "—" if old_rate is None
                     else f"{old.get('k')}/{old.get('n')} = {old_rate:.0%}",
                     rate.text, delta])
    lines += _table(rows, ["category", "baseline", "now", "delta"])
    lines.append("")

    then = {entry.get("probe"): entry
            for entry in (baseline.get("attempts") or [])}
    flips = [(a.probe, then[a.probe].get("verdict"), a.verdict)
             for a in report.attempts
             if a.probe in then
             and bool(then[a.probe].get("verdict")) != a.verdict]
    if flips:
        lines.append("### probes that changed verdict")
        lines.append("")
        lines += _table(
            [[f"`{probe}`", "PASS" if was_ok else "FAIL",
              "PASS" if now_ok else "FAIL"]
             for probe, was_ok, now_ok in flips],
            ["probe", "baseline", "now"])
    else:
        lines.append("No probe changed verdict.")
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


def run_probes(probes: Sequence[Probe], ask: Ask, *, repeats: int = 1,
               log=print) -> Tuple[Attempt, ...]:
    """Ask every probe *repeats* times and score each answer.

    One call, then at most one repair — never a third: a loop that kept
    asking would measure how long a model takes to stumble into the shape,
    and §2.9.3's number is about the first answer and the cost of fixing
    it.
    """
    attempts: List[Attempt] = []
    total = len(probes) * max(1, int(repeats))
    for repeat in range(1, max(1, int(repeats)) + 1):
        for probe in probes:
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
                                    replies=replies)
            attempts.append(attempt)
            log(f"  {attempt.probe} [{attempt.family}] "
                f"{attempt.structural} — "
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
          temperature: Optional[float] = None) -> Ask:
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
    """
    from core.runtime.provider_config import resolve_model
    from core.unified_client import UnifiedClient

    client = UnifiedClient(provider_override=provider)
    name = resolve_model(provider, model, served=lambda: client.default_model)
    sampling: Dict[str, Any] = ({} if temperature is None
                                else {"temperature": temperature})

    def ask(messages: Sequence[Mapping[str, str]]) -> str:
        reply = client.chat(name, [dict(m) for m in messages], False,
                            **sampling)
        return "" if reply is None else str(reply)

    ask.model = name                             # type: ignore[attr-defined]
    return ask


def header(probes: Sequence[Probe], path: Path, *, provider: str = "",
           model: str = "", temperature: Optional[float] = None,
           repeats: int = 1, env: Optional[Mapping[str, str]] = None
           ) -> Dict[str, Any]:
    """What produced these numbers.  ``measure``'s vocabulary, one field
    wider: the temperature and the prompt digest, both of which move an
    extraction rate and neither of which a matrix row varies."""
    from core.eval.measure import commit_of, scrubbed

    env = os.environ if env is None else env
    return {
        "commit": commit_of(),
        "date": date.today().isoformat(),
        "provider": provider,
        "model": model,
        "temperature": temperature,
        "endpoint": scrubbed(env.get("LOCAL_API_BASE", "")),
        "prompt": prompt_fingerprint(),
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
    parser.add_argument("--repeats", type=int, default=1, metavar="N",
                        help="ask every probe N times (default 1); the "
                             "interval is over the attempts")
    parser.add_argument("--only", action="append", default=[], metavar="ID",
                        help="measure only this probe; repeatable")
    parser.add_argument("--report", type=Path, metavar="PATH",
                        help="write the table here as Markdown and the same "
                             "report as JSON beside it")
    parser.add_argument("--baseline", type=Path, metavar="PATH",
                        help="an earlier report.json; its rates are printed "
                             "beside these as paired deltas")
    parser.add_argument("--json", action="store_true",
                        help="print JSON instead of the Markdown tables")
    return parser


def from_args(args: argparse.Namespace) -> int:
    """``extraction`` as :func:`core.eval.run.main` reaches it."""
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
    try:
        ask = asker(provider, args.model, temperature=args.temperature)
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
        attempts = run_probes(probes, ask, repeats=args.repeats)
    except Unextractable as exc:
        print(f"extraction: {exc}", file=sys.stderr)
        return 2

    report = ExtractionReport(
        probes=Path(args.probes).name, attempts=attempts,
        families=tuple(dict.fromkeys(probe.family for probe in probes)),
        meta=header(probes, Path(args.probes), provider=provider,
                    model=str(getattr(ask, "model", "") or args.model or ""),
                    temperature=args.temperature, repeats=args.repeats))

    print(report.to_json() if args.json else report.to_markdown(baseline))
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(args.report, report.to_markdown(baseline))
        atomic_write_text(args.report.with_suffix(".json"), report.to_json())
    return 0
