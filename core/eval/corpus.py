# core/eval/corpus.py — validated traces in, fine-tune examples out

"""ROADMAP §2.9.8's first step, and `MODELS.md` §4's: the training corpus.

Phase 21 is a **per-model loop** — serve, declare, measure, tune the knobs,
fine-tune the residual — and step one of it is this: turn behaviour that was
*validated* into examples a tuner can train on.  Nothing here trains
anything and nothing here talks to a model.  It reads two kinds of evidence
this repository already produces and writes a JSONL a LoRA-class trainer
consumes.

**The one rule the whole module is built around: a completion is never
synthesised.**  Every completion written here is a string a model actually
emitted, copied out of a record, at a turn where an instrument that was not
looking at it afterwards said the behaviour was right.  The roadmap asks for
a corpus "from validated traces", and the difference between that and a
corpus of ideal answers somebody wrote is the difference between training a
model on what it can be got to do and training it on what its author wishes
it would do.  The second is how a tune moves prose quality and moves no
rate — `MODELS.md` §4's failure mode, stated before the tooling existed.

**Two inputs, one shape out.**

``--from-extraction report.json``
    The extraction instrument (:mod:`core.eval.extraction`) asks a model to
    turn one real tool receipt into typed propositions, and scores the reply
    against a probe that declared in advance what a correct extractor says.
    Every attempt whose ``verdict`` is true becomes one example: the turns
    are rebuilt through :func:`~core.eval.extraction.prompt_for` from the
    probe the report names, and the completion is the model's own passing
    reply, verbatim.  A failed attempt is excluded and counted — and the
    count is printed, because a corpus is a sample and a reader has to know
    what was dropped out of it.

``--from-runs DIR``
    Recorded missions (``EVAL.md`` §10).  A run that **answered**, whose
    grounding record (when there is one) says the answer was verified,
    yields one example per recorded model call: the request as it was sent,
    the reply as it came back, tagged by the position the reply took in the
    turn (planning, tool call, answer).  A run that does not meet that bar
    leaves whole, with its reason counted.  **v1 is deliberately simple: no
    synthetic repair, no editing, no reconstruction of what the model should
    have said.**  The honest bound is written into ``EVAL.md`` §17 rather
    than hidden here.

**Abstention-heavy, by discipline.**  §2.9.8 puts it above the rest: a
useful semantic compiler must know *when not to create a fact*.  The probe
corpus this repository ships is 51% abstain-or-trap by construction
(25 of 49), so :data:`ABSTENTION_FLOOR` is set at 0.40 — a fifth below that
design margin.  Below the floor the build **warns and still writes**: the
floor is a property of a sample nobody controls (a model that fails every
trap leaves few passing trap examples behind, which is the case where the
corpus is *least* balanced and the operator most needs to know), and a
refusal there would be this tool deciding a tuning question that belongs to
the person running it.  ``--balance`` is the opt-in fix: downsample the
``assert``-kind examples until the floor is met, deterministically, so two
people building the same corpus from the same report get the same file.

**Scrub before write, and a second opinion after it.**  Every string of
every example passes :func:`core.redact.scrub` — the established family:
credentials, absolute paths, this host's name.  Then :func:`residue_in`
looks again with patterns of its own, and an example that still carries a
credential shape is **refused and counted rather than written**.  The second
look is not redundant: the scrubber neutralises what it owns, and a bearer
token that arrives without the word ``Bearer`` in front of it (a bare JWT
under some other key) is a shape it has no rule for.  A corpus leaves the
building; a redactor nobody double-checks is how one leaves with a key in
it.

One bound, stated rather than implied: **principals inside a receipt's own
content are not renamed.**  ``scrub`` takes out this host, its paths and any
home directory's user name, but a handle or an account *inside a tool
result* is data the grounding checked byte for byte, and generalising it to
a role here would be editing the evidence a completion cites.  Principals
becoming roles (``MODELS.md`` §4) is the corpus author's call, made on the
receipts before they are recorded or on the file afterwards, and ``--note``
is where the deployment says which it did.

**The file.**  Line one is a header — schema version, the tool's version and
the tree's commit, the counts by source and kind, the floor, the scrub
statement — the way ``reasoning.jsonl`` puts its versions on line one
(:func:`core.runtime.cognition.header_record`).  Every line after it is one
example: ``{"messages": [...], "completion": "...", "meta": {...}}``.  Order
is input order, always, and a content digest of the whole file is printed at
the end: **the corpus is an experiment input**, and a number carries its
interpreter — a tuned checkpoint reported against "the corpus" names which
bytes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from core.durable import atomic_write_text
from core.eval.extraction import (ASSERT, CONTRADICTED, HEDGING, INSUFFICIENT,
                                  KINDS, REPAIRED, Probe, ProbeMisdeclared,
                                  load_probes, prompt_fingerprint, prompt_for,
                                  repair_for)
from core.redact import scrub

__all__ = [
    "CORPUS_SCHEMA_VERSION", "SCHEMA_KEY", "ABSTENTION_FLOOR", "ABSTAINING",
    "SOURCES", "POSITIONS", "STANCES", "EXCLUSIONS", "SCRUB_STATEMENT",
    "RESIDUE", "CorpusRefused", "Example",
    "stance_of", "position_of", "residue_in", "scrubbed",
    "from_extraction", "from_runs", "balance", "header_record", "render",
    "digest_of", "add_parser", "from_args",
]


# ── the shape of the file ────────────────────────────────────────────────────

#: The shape of a corpus file — the header, and what an example line carries.
#: Bumped when that shape changes.  Its own number, and emphatically not
#: :data:`core.runtime.contract.SCHEMA_VERSION`: the wire a platform consumes
#: and a training file a tuner consumes change for different reasons and on
#: different days, and one number standing for both would move one consumer
#: every time the other one was served.
CORPUS_SCHEMA_VERSION = 1

#: The key the header states :data:`CORPUS_SCHEMA_VERSION` under, and the key
#: that identifies the header line.  A reader tells the header from an
#: example by this key and never by position, for
#: :func:`core.runtime.cognition.read_reasoning`'s reason: a file that is
#: read by counting lines is a file misread exactly once.
SCHEMA_KEY = "corpus_schema"

#: Where an example may come from.  Both are *validated* traces; what
#: validated them differs, and the meta of every example says which.
SOURCES: Tuple[str, ...] = ("extraction", "runs")

#: What a recorded reply was doing in its turn.  Read off the reply itself
#: (:func:`position_of`) rather than off its ordinal: the last call of a run
#: is usually the answer and sometimes is not, and a tag that was right
#: "usually" would be a label a tuner trains against.
POSITIONS: Tuple[str, ...] = ("planning", "tool_call", "answer")

#: The epistemic stance a passing extraction reply took — what it *did* with
#: the receipt, as opposed to :data:`~core.eval.extraction.KINDS`, which is
#: what its probe *asked* for.  Both are on the example, because the pair is
#: the interesting one: an ``assert`` probe answered with ``abstained`` is a
#: failure and never reaches here, while a ``trap`` probe answered
#: ``asserted`` is the trap being resisted and is exactly what a tuner wants
#: to see.
STANCES: Tuple[str, ...] = ("asserted", "mixed", "hedged", "abstained",
                            "contradicted", "silent")

#: Every reason this builder declines to write something, and what it means.
#: Data rather than prose, so a reason is added in one place and shows up in
#: the summary, the header and the docs at once — and so that a reader of a
#: corpus can ask what was left out without reading this file.
EXCLUSIONS: Mapping[str, str] = {
    "failed_probe": (
        "an extraction attempt whose verdict was false. The corpus trains on "
        "validated behaviour; a wrong answer is evidence about the model and "
        "not an example for it"),
    "no_reply": (
        "an attempt that passed but carries no recorded reply, so there is "
        "nothing verbatim to copy. Never synthesised"),
    "unrebuildable_repair": (
        "an attempt the instrument marked `repaired` whose first reply or "
        "whose defect sentence was not recorded. Half the conversation is "
        "missing and inventing it would train the model on the half that "
        "was true"),
    "not_answered": (
        "a run whose mission_finished said anything but `answered` — "
        "`answered_with_caveat` included, because the caveat is the "
        "grounding saying it could not verify the answer"),
    "grounding_rejected": (
        "a run that answered, with a grounding record that ran and did not "
        "come back grounded and verified"),
    "reply_rejected": (
        "a run whose transcript holds a `reply_rejected` record. The rejected "
        "reply is in the model log beside the good ones and v1 does not "
        "reconstruct which call it was, so the whole run leaves rather than "
        "one bad completion being trained on"),
    "no_model_log": "a directory with no model.jsonl — nothing was recorded",
    "no_stream": (
        "a run directory with no events.jsonl, so there is no record of what "
        "the run did and no way to hold it to the bar"),
    "no_calls": "a run that met the bar and recorded no model call",
    "no_text_reply": (
        "a recorded call whose reply carries no text — a `--protocol native` "
        "turn puts its payload in `tool_calls`, which is a structure and not "
        "a completion. v1 writes text completions only, and rendering the "
        "structure into one would be inventing a target the model never "
        "emitted"),
    "unreadable_call": (
        "a model.jsonl line with no recorded request messages, so there is "
        "no conversation to train the reply against"),
    "flags": "a run that did not match every --flag-filter",
    "credential_residue": (
        "an example whose text still matched a credential shape AFTER the "
        "scrub. Refused, never written, and counted — see `residue_in`"),
    "balanced_out": (
        "an assert-kind example dropped by --balance to reach the abstention "
        "floor. Deterministic in the seed"),
}

#: The share of examples that must be abstain-or-trap before the build stops
#: warning.  0.40 against a probe corpus that is 0.51 by construction: a
#: fifth below the design margin is a sample that has drifted, and further
#: down the assert half dominates a corpus whose whole purpose (§2.9.8) is
#: teaching a model when *not* to create a fact.  A warning and not a
#: refusal — see the module docstring.
ABSTENTION_FLOOR = 0.40

#: The probe kinds that count toward the floor: the receipt does not hold the
#: fact, or holds a plausible wrong one beside it.  Named here rather than
#: spelled in the arithmetic, so "which kinds are the abstention half" has
#: one owner and the floor cannot be computed two ways.
ABSTAINING: Tuple[str, ...] = ("abstain", "trap")


class CorpusRefused(ValueError):
    """An input this builder will not turn into training data.

    Every refusal here is a defect that would otherwise become a *model's*
    weights: a report rebuilt against the wrong probe corpus trains the
    model on questions it was never asked, and a report written under a
    different prompt trains it to answer an instruction it will never see.
    """


# ── one example ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Example:
    """One training pair and where it came from.

    *messages* is the conversation as it was **sent** — rebuilt for an
    extraction attempt through the same :func:`prompt_for` the run used, and
    copied verbatim out of ``model.jsonl`` for a recorded mission.
    *completion* is what came back at that turn, verbatim.  *meta* is
    provenance: the file and its digest, the probe or run and the ordinal
    inside it, the interpreter identity where the source report carried one,
    and the operator's ``license_note``.
    """

    messages: Tuple[Mapping[str, Any], ...]
    completion: str
    meta: Mapping[str, Any]

    @property
    def key(self) -> str:
        """What orders a balanced drop, and what a second build sorts by.

        Provenance and not content: two attempts of the same probe that
        produced byte-identical replies are still two examples, and a key
        taken from the text would collapse them.

        **No file path in it**, deliberately.  ``--balance`` promises the
        same file from the same inputs, and a key carrying the directory
        somebody happened to download the report into would give two
        people the same corpus and a different sample of it.
        """
        meta = self.meta
        ordinal = (meta.get("repeat") if meta.get("repeat") is not None
                   else meta.get("seq"))
        return (f"{meta.get('source')}\x00"
                f"{meta.get('probe') or meta.get('run')}\x00{ordinal}")

    def as_dict(self) -> Dict[str, Any]:
        return {"messages": [dict(m) for m in self.messages],
                "completion": self.completion,
                "meta": dict(self.meta)}


# ── what a reply was doing ───────────────────────────────────────────────────

def stance_of(propositions: Sequence[Mapping[str, Any]]) -> str:
    """The epistemic stance of one passing extraction reply.

    Read off the statuses the reply used, in the order that makes the
    abstention half visible: a reply that surfaced a contradiction is
    reported as that and not as "it asserted two things", because §2.9.8's
    corpus is graded on what the model refused to collapse.
    """
    statuses = [str(p.get("status") or "") for p in propositions
                if isinstance(p, Mapping)]
    if not statuses:
        return "silent"
    if CONTRADICTED in statuses:
        return "contradicted"
    asserts = [s for s in statuses if s == ASSERT]
    if not asserts:
        if INSUFFICIENT in statuses:
            return "abstained"
        if any(s in HEDGING for s in statuses):
            return "hedged"
        return "silent"
    return "asserted" if len(asserts) == len(statuses) else "mixed"


def _payload(content: str) -> Optional[Mapping[str, Any]]:
    """*content* as a JSON object, or ``None``.

    No fence-stripping and no repair: this reads a recorded reply to label
    it, and a labeller that worked harder than the runtime's own parser
    would tag as a tool call a reply the runtime rejected.
    """
    try:
        parsed = json.loads(content)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, Mapping) else None


def position_of(reply: Mapping[str, Any]) -> str:
    """Which of :data:`POSITIONS` this recorded reply took.

    Native tool calls first, because a backend that returned them is not
    negotiating about it; then the ``json`` protocol's two shapes; then
    ``planning``, which is the honest name for a reply that is neither — the
    prose turn a model takes before it commits to a call.
    """
    if reply.get("tool_calls"):
        return "tool_call"
    payload = _payload(str(reply.get("content") or "").strip())
    if payload is not None:
        if "tool" in payload:
            return "tool_call"
        if "answer" in payload:
            return "answer"
    return "planning"


# ── the scrub, and the second opinion ────────────────────────────────────────

#: What the header says was done to every string in this file.
SCRUB_STATEMENT = (
    "every string of every example passed core.redact.scrub (credentials, "
    "absolute paths, this host's name) and was then re-read by "
    "core.eval.corpus.residue_in; an example still matching a credential "
    "shape was refused and counted, never written"
)

#: The second opinion.  Deliberately **not** :mod:`core.redact`'s own
#: patterns re-run: a scrubber is idempotent, so asking it again about its
#: own output answers a question nobody had.  These are the shapes that
#: survive a scrub because it has no rule for them — a bare JWT sitting under
#: a key nobody named ``_TOKEN``, a PEM block — plus the vendor prefixes,
#: whose presence here would mean the scrub never ran at all.
#:
#: The bearer rule wants length **and** a digit, so that the English words
#: "bearer authentication" in a receipt are not a refusal: a corpus builder
#: that cries wolf gets run with the check off.
RESIDUE: Tuple[Tuple[str, "re.Pattern"], ...] = (
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.")),
    ("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("bearer", re.compile(
        r"(?i)\bbearer\s+(?=[A-Za-z0-9._\-+/=]*\d)[A-Za-z0-9._\-+/=]{16,}")),
    ("api-key", re.compile(r"\bsk-[A-Za-z0-9_\-]{12,}")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}")),
    ("aws-access-key-id", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{12,}")),
    ("slack-token", re.compile(r"\bxox[bpsare]-[A-Za-z0-9\-]{8,}")),
)


def residue_in(value: Any) -> Optional[str]:
    """The name of the first credential shape still in *value*, or ``None``.

    Walks strings at any depth, so a secret inside a nested meta mapping is
    found — the walk :func:`core.runtime.replay.without_credentials` makes,
    for its reason: a redactor that only works on values nobody quoted is a
    redactor that misses the interesting one.
    """
    if isinstance(value, str):
        for name, pattern in RESIDUE:
            if pattern.search(value):
                return name
        return None
    if isinstance(value, Mapping):
        for item in value.values():
            found = residue_in(item)
            if found:
                return found
        return None
    if isinstance(value, (list, tuple)):
        for item in value:
            found = residue_in(item)
            if found:
                return found
    return None


def _walk_scrub(value: Any) -> Any:
    if isinstance(value, str):
        return scrub(value)
    if isinstance(value, Mapping):
        return {key: _walk_scrub(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_walk_scrub(item) for item in value]
    return value


def scrubbed(example: Example) -> Tuple[Example, bool]:
    """*example* with every string scrubbed, and whether anything moved.

    The boolean is reported rather than swallowed.  A corpus whose prompts
    were rewritten on the way out is still the right corpus to ship — a
    training file must not carry this host — but the operator is owed the
    count, because a *rebuilt* extraction prompt that the scrub then edited
    is no longer byte-identical to what the model was asked, and that is a
    fact about the sample and not a detail.
    """
    before = example.as_dict()
    after = _walk_scrub(before)
    clean = Example(messages=tuple(after["messages"]),
                    completion=after["completion"], meta=after["meta"])
    return clean, after != before


# ── extraction reports in ────────────────────────────────────────────────────

def _probe_for(attempt: Mapping[str, Any],
               probes: Mapping[str, Probe]) -> Probe:
    """The probe an attempt was asked, from the report or from the corpus.

    A report that embeds its own ``evidence`` and ``question`` is rebuilt
    from itself; today's reports do not, so the probe corpus is required and
    the refusal says so by name.  Either way the turns are built by
    :func:`prompt_for` and never formatted here: the prompt has one owner,
    and a second copy of it in this file would be the drift the roadmap's
    "one owner per fact" rule is about.
    """
    name = str(attempt.get("probe") or "")
    evidence, question = attempt.get("evidence"), attempt.get("question")
    if isinstance(evidence, str) and isinstance(question, str):
        return Probe(id=name, family=str(attempt.get("family") or ""),
                     source="(embedded in the report)", evidence=evidence,
                     question=question, kind=str(attempt.get("kind") or ""))
    probe = probes.get(name)
    if probe is None:
        raise CorpusRefused(
            f"the report names probe {name!r}, which the corpus passed to "
            f"--probes does not hold. Rebuilding a prompt from the wrong "
            f"corpus would train the model on a question it was never "
            f"asked; point --probes at the file the report's meta names "
            f"(`probes_path`)")
    return probe


def from_extraction(report: Mapping[str, Any], probes: Mapping[str, Probe], *,
                    source: str = "", digest: str = "", note: str = ""
                    ) -> Tuple[List[Example], Counter]:
    """Passing attempts out of one extraction report, and what was dropped.

    The turns are exactly the ones the run sent: the prompt, and — where the
    first reply could not be read — the failed reply and the repair that
    named the defect, because that is the conversation the passing completion
    was the answer to.  A repaired attempt is a real success and is kept,
    tagged ``structural`` so a tuner can hold it out if it would rather train
    only on first answers.

    Refused up front, before an example exists, when the report was written
    under a **different prompt** than this tree's: the fingerprint in the
    report's meta is what says so, and a corpus rebuilt against today's
    wording out of yesterday's replies is a file of answers to an
    instruction the model will never see again.
    """
    attempts = report.get("attempts")
    if not isinstance(attempts, Sequence) or isinstance(attempts, (str, bytes)):
        raise CorpusRefused(
            f"{source or 'the report'} carries no `attempts` list; this is "
            f"not a `core.eval extraction` report")
    meta = report.get("meta") if isinstance(report.get("meta"), Mapping) else {}

    recorded = meta.get("prompt")
    if recorded:
        here = prompt_fingerprint(bool(meta.get("constrained")))
        if str(recorded) != here:
            raise CorpusRefused(
                f"{source or 'the report'} was produced under prompt "
                f"{recorded!r} and this tree's prompt is {here!r}. The turns "
                f"would be rebuilt from today's wording around yesterday's "
                f"replies — build the corpus from a checkout whose "
                f"`extraction.PROMPT` matches, or re-run the instrument")

    interpreter = {key: meta.get(key) for key in
                   ("provider", "model", "temperature", "endpoint",
                    "constrained", "prompt", "scorer", "commit", "date")
                   if meta.get(key) is not None}

    examples: List[Example] = []
    excluded: Counter = Counter()
    for attempt in attempts:
        if not isinstance(attempt, Mapping):
            continue
        if not attempt.get("verdict"):
            excluded["failed_probe"] += 1
            continue
        replies = [r for r in (attempt.get("replies") or [])
                   if isinstance(r, str)]
        if not replies:
            excluded["no_reply"] += 1
            continue
        probe = _probe_for(attempt, probes)
        messages: List[Dict[str, str]] = [
            {"role": "user", "content": prompt_for(probe)}]
        if str(attempt.get("structural")) == REPAIRED:
            defects = [d for d in (attempt.get("defects") or [])
                       if isinstance(d, str)]
            if len(replies) < 2 or not defects:
                # A repaired attempt whose first reply or whose defect was
                # not recorded cannot have its second turn rebuilt, and
                # inventing either would be writing half the conversation —
                # then training the model on the half that was true.
                excluded["unrebuildable_repair"] += 1
                continue
            messages += [{"role": "assistant", "content": replies[0]},
                         {"role": "user", "content": repair_for(defects[0])}]
        examples.append(Example(
            messages=tuple(messages),
            completion=replies[-1],
            meta={
                "source": "extraction",
                "source_file": source,
                "source_digest": digest,
                "probe": probe.id,
                "repeat": int(attempt.get("repeat") or 1),
                "kind": str(attempt.get("kind") or ""),
                "family": str(attempt.get("family") or ""),
                "structural": str(attempt.get("structural") or ""),
                "stance": stance_of(attempt.get("propositions") or ()),
                "interpreter": interpreter,
                "license_note": note,
            }))
    return examples, excluded


# ── recorded runs in ─────────────────────────────────────────────────────────

def _flags_of(directory: Path) -> Dict[str, Any]:
    """A run's declared flags out of ``meta.json``, or ``{}``."""
    try:
        payload = json.loads((directory / "meta.json").read_text(
            encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    inner = payload.get("meta") if isinstance(payload, Mapping) else None
    flags = (inner or {}).get("flags") if isinstance(inner, Mapping) else None
    return dict(flags) if isinstance(flags, Mapping) else {}


def _matches(flags: Mapping[str, Any], wanted: Mapping[str, str]) -> bool:
    """Whether a run's flags satisfy every ``--flag-filter``.

    A list value matches when the wanted value is one of its members —
    ``flags.skill`` has been a list since 1.1.0 (skills compose), and a
    filter that only understood the old string would silently exclude every
    run written since.
    """
    for key, value in wanted.items():
        held = flags.get(key)
        if isinstance(held, (list, tuple)):
            if value not in [str(item) for item in held]:
                return False
        elif str(held) != value:
            return False
    return True


def _bar(records: Sequence[Mapping[str, Any]]) -> Optional[str]:
    """Why this run may not be trained on, or ``None``.

    The bar, in one place: it **answered**, no reply of it was rejected, and
    any grounding that ran came back grounded and verified.  ``answered``
    strictly — ``answered_with_caveat`` is the grounding saying out loud that
    it could not verify what it was shown, and a corpus of validated traces
    that trained on it would be training the model on the sentence the
    validator wrote about its own failure.
    """
    finished = [r for r in records if r.get("event") == "mission_finished"]
    if not finished:
        return "no_stream"
    if str(finished[-1].get("outcome")) != "answered":
        return "not_answered"
    if any(r.get("event") == "reply_rejected" for r in records):
        return "reply_rejected"
    for record in records:
        if record.get("event") != "grounding" or not record.get("ran"):
            continue
        if not (record.get("grounded") and record.get("verified")):
            return "grounding_rejected"
    return None


def _model_calls(path: Path) -> List[Mapping[str, Any]]:
    """Every parseable ``model.jsonl`` line, in call order.

    A torn last line is skipped rather than fatal, the way every other
    reader of a durable log in this tree treats one.
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
    out.sort(key=lambda record: int(record.get("call") or 0))
    return out


def run_directories(root: Path) -> List[Path]:
    """The run directories under *root*, in a stable order.

    *root* itself when it is one — so a single recorded run can be pointed
    at directly — and otherwise its immediate subdirectories, sorted by name
    so that two builds of the same tree write the same file.
    """
    root = Path(root)
    if (root / "model.jsonl").exists():
        return [root]
    if not root.is_dir():
        return []
    return sorted((child for child in root.iterdir() if child.is_dir()),
                  key=lambda child: child.name)


def from_runs(root: Path, *, flag_filter: Optional[Mapping[str, str]] = None,
              note: str = "") -> Tuple[List[Example], Counter]:
    """One example per model call of every run that met the bar.

    Simple on purpose (see the module docstring): the request is the request
    as recorded, the completion is the reply as recorded, and nothing is
    repaired, trimmed or re-ordered.  What this version does **not** do is
    pick the good calls out of a run that went wrong — a run with a rejected
    reply leaves whole rather than being edited into a version of itself
    that never happened.
    """
    from core.eval.score import records_from

    examples: List[Example] = []
    excluded: Counter = Counter()
    for directory in run_directories(root):
        model_log = directory / "model.jsonl"
        if not model_log.exists():
            excluded["no_model_log"] += 1
            continue
        if not (directory / "events.jsonl").exists():
            excluded["no_stream"] += 1
            continue
        flags = _flags_of(directory)
        if flag_filter and not _matches(flags, flag_filter):
            excluded["flags"] += 1
            continue
        try:
            records = records_from(directory)
        except Exception:                        # noqa: BLE001 — any failure
            excluded["no_stream"] += 1
            continue
        refusal = _bar(records)
        if refusal:
            excluded[refusal] += 1
            continue
        calls = _model_calls(model_log)
        if not calls:
            excluded["no_calls"] += 1
            continue
        digest = digest_of(model_log.read_bytes())
        run_id = _run_id(directory)
        for record in calls:
            request = record.get("request")
            reply = record.get("reply")
            messages = ([m for m in (request.get("messages") or ())
                         if isinstance(m, Mapping)]
                        if isinstance(request, Mapping) else [])
            if not messages or not isinstance(reply, Mapping):
                excluded["unreadable_call"] += 1
                continue
            content = reply.get("content")
            if not isinstance(content, str) or not content.strip():
                excluded["no_text_reply"] += 1
                continue
            examples.append(Example(
                # Every recorded key of every message, not a normalised
                # pair: a `--protocol native` transcript carries
                # `tool_calls` on an assistant turn and `tool_call_id` on
                # the result turn, and a conversation rebuilt without them
                # is a different conversation.
                messages=tuple(dict(m) for m in messages),
                completion=content,
                meta={
                    "source": "runs",
                    "source_file": str(model_log),
                    "source_digest": digest,
                    "run": run_id,
                    "seq": int(record.get("call") or 0),
                    "position": position_of(reply),
                    # `call_kind` and not `kind`: the recorder's word for
                    # what a model call was (`mission`, `plain`) and a
                    # probe's word for what was asked of it (`assert`,
                    # `abstain`, `trap`) are two vocabularies, and folding
                    # them into one field would put `mission` in the kind
                    # mix the abstention floor is read off.
                    "call_kind": str(record.get("kind") or ""),
                    "flags": flags,
                    "license_note": note,
                }))
    return examples, excluded


def _run_id(directory: Path) -> str:
    try:
        payload = json.loads((directory / "meta.json").read_text(
            encoding="utf-8"))
    except (OSError, ValueError):
        return directory.name
    held = payload.get("run_id") if isinstance(payload, Mapping) else None
    return str(held or directory.name)


# ── the abstention floor ─────────────────────────────────────────────────────

def abstention_share(examples: Sequence[Example]) -> Optional[float]:
    """The abstain-or-trap share of the kind-bearing examples, or ``None``.

    ``None`` when nothing in the corpus declares a kind — a corpus built
    from runs alone.  Reported as "not computed" rather than as zero: a
    build has no opinion about the abstention balance of a sample that
    never claimed to have one, and a floor warning printed against it would
    be an instrument inventing a finding.
    """
    kinds = [str(e.meta.get("kind") or "") for e in examples]
    graded = [k for k in kinds if k in KINDS]
    if not graded:
        return None
    return sum(1 for k in graded if k in ABSTAINING) / len(graded)


def balance(examples: Sequence[Example], *, floor: float = ABSTENTION_FLOOR,
            seed: int = 0) -> Tuple[List[Example], int]:
    """*examples* with assert-kind ones downsampled to reach *floor*.

    Deterministic in *seed* and in the examples' provenance keys: the order
    a drop is chosen in is the order of ``sha256(seed, key)``, so the same
    inputs give the same file on any machine and a different seed gives a
    different sample of the same corpus rather than a different corpus.
    Input order survives — only membership changes — because
    ``--balance`` is a subset and not a shuffle.

    Nothing is dropped when the floor is already met, when there is nothing
    kind-bearing to balance, or when there is **no** abstention half to
    balance toward — that last one is the rule the other two are special
    cases of: a corpus with too few abstentions is fixed by measuring more
    of them, and a builder that reached the ratio by deleting the sample
    would be reporting a share it had manufactured.
    """
    graded = [e for e in examples if str(e.meta.get("kind") or "") in KINDS]
    if not graded or floor <= 0:
        return list(examples), 0
    keeping = [e for e in graded if str(e.meta.get("kind")) in ABSTAINING]
    asserts = [e for e in graded if str(e.meta.get("kind")) not in ABSTAINING]
    if not asserts or not keeping:
        return list(examples), 0
    # Counted down rather than solved for: `o (1 - floor) / floor` is the
    # closed form and it is a float, and at floor 0.40 with two abstentions
    # it lands on 2.9999999999999996 and keeps one example fewer than the
    # floor allows. The loop is bounded by the assert count and asks the
    # SAME comparison the warning asks, so a corpus balanced to the floor
    # is never a corpus that then warns about the floor — and it is the one
    # place the ratio is decided, so the already-above-the-floor case falls
    # out of it rather than being a second rule that could disagree.
    allowed = len(asserts)
    while allowed > 0 and len(keeping) / (allowed + len(keeping)) < floor:
        allowed -= 1
    if allowed >= len(asserts):
        return list(examples), 0
    ordered = sorted(asserts,
                     key=lambda e: hashlib.sha256(
                         f"{seed}\x00{e.key}".encode("utf-8")).hexdigest())
    dropped = set(id(e) for e in ordered[allowed:])
    kept = [e for e in examples if id(e) not in dropped]
    return kept, len(dropped)


# ── the file ─────────────────────────────────────────────────────────────────

def digest_of(payload: Any) -> str:
    """``sha256:…`` of some bytes or text.

    One spelling, prefixed, because a bare hex string in a report is a
    number without its interpreter: a reader cannot tell a sha256 of a file
    from a sha1 of a commit by looking at it.
    """
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    return "sha256:" + hashlib.sha256(bytes(payload)).hexdigest()


def _tool_version() -> str:
    from core.cli import installed_version
    return installed_version()


def header_record(examples: Sequence[Example], excluded: Mapping[str, int], *,
                  floor: float = ABSTENTION_FLOOR, note: str = "",
                  sources: Sequence[str] = (), scrub_changed: int = 0,
                  ) -> Dict[str, Any]:
    """Line one: what this file is, what is in it, and what was done to it.

    The counts are here and not only on the console because a corpus
    outlives the terminal that built it: six months later the question
    "what was the abstention share of the file this checkpoint was tuned
    on" has to be answerable from the file.
    """
    from core.eval.measure import commit_of

    share = abstention_share(examples)
    return {
        SCHEMA_KEY: CORPUS_SCHEMA_VERSION,
        "tool": _tool_version(),
        "commit": commit_of(),
        "date": date.today().isoformat(),
        "examples": len(examples),
        "by_source": dict(Counter(str(e.meta.get("source") or "")
                                  for e in examples)),
        "by_kind": dict(Counter(str(e.meta.get("kind") or "")
                                for e in examples if e.meta.get("kind"))),
        "by_stance": dict(Counter(str(e.meta.get("stance") or "")
                                  for e in examples if e.meta.get("stance"))),
        "by_position": dict(Counter(str(e.meta.get("position") or "")
                                    for e in examples
                                    if e.meta.get("position"))),
        "excluded": dict(sorted(excluded.items())),
        "abstention_share": share,
        "abstention_floor": float(floor),
        "scrub": SCRUB_STATEMENT,
        "scrub_changed": int(scrub_changed),
        "sources": list(sources),
        "license_note": note,
    }


def render(header: Mapping[str, Any], examples: Sequence[Example]) -> str:
    """The whole file, header first, one example per line.

    ``sort_keys`` on every line and a trailing newline on the last one, so
    that the digest of a corpus is a property of its content and not of the
    dictionary order a particular Python happened to build.
    """
    lines = [json.dumps(dict(header), sort_keys=True, ensure_ascii=False)]
    lines += [json.dumps(example.as_dict(), sort_keys=True,
                         ensure_ascii=False) for example in examples]
    return "\n".join(lines) + "\n"


# ── the command line ─────────────────────────────────────────────────────────

def add_parser(subs) -> argparse.ArgumentParser:
    """Register ``corpus`` on :func:`core.eval.run._parser`'s subparsers.

    From here rather than written out in ``run.py``, the way ``measure``,
    ``ablation`` and ``extraction`` register themselves.  Deliberately
    without ``common``: a corpus is built from evidence that already exists,
    so there is no suite to grade, no split to hold out and no model to
    spend.
    """
    parser = subs.add_parser(
        "corpus",
        help="build a fine-tune corpus from validated traces: passing "
             "extraction attempts and recorded missions that answered")
    parser.add_argument("--out", required=True, type=Path, metavar="PATH",
                        help="where the JSONL is written; line one is the "
                             "header")
    parser.add_argument("--from-extraction", action="append", default=[],
                        type=Path, metavar="REPORT",
                        help="a `core.eval extraction` report.json; every "
                             "attempt that PASSED its probe becomes one "
                             "example. Repeatable")
    parser.add_argument("--probes", type=Path, metavar="PATH",
                        help="the probe corpus the report was run against — "
                             "its meta names it as `probes_path`. Required "
                             "unless the report embeds its own evidence")
    parser.add_argument("--from-runs", action="append", default=[], type=Path,
                        metavar="DIR",
                        help="a directory of recorded run directories (or "
                             "one run directory); a run that answered and "
                             "was not rejected yields one example per model "
                             "call. Repeatable")
    parser.add_argument("--flag-filter", action="append", default=[],
                        metavar="KEY=VALUE",
                        help="keep only runs whose meta.json flags carry "
                             "this; repeatable, and all of them must match")
    parser.add_argument("--note", default="",
                        help="the `license_note` written on the header and "
                             "on every example — whose data this is and "
                             "what may be done with it. Empty is allowed "
                             "and says so")
    parser.add_argument("--floor", type=float, default=ABSTENTION_FLOOR,
                        metavar="SHARE",
                        help=f"the abstain-or-trap share below which the "
                             f"build WARNS (default {ABSTENTION_FLOOR}); it "
                             f"never refuses")
    parser.add_argument("--balance", action="store_true",
                        help="downsample assert-kind examples until the "
                             "floor is met, deterministically")
    parser.add_argument("--seed", type=int, default=0, metavar="N",
                        help="the seed --balance drops by (default 0); the "
                             "same seed and inputs give the same file")
    parser.add_argument("--json", action="store_true",
                        help="print the summary as JSON on stdout instead "
                             "of lines; the corpus itself always goes to "
                             "--out")
    return parser


def _filters(pairs: Sequence[str]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for pair in pairs:
        if "=" not in pair:
            raise CorpusRefused(f"--flag-filter wants KEY=VALUE, got {pair!r}")
        key, value = pair.split("=", 1)
        out[key.strip()] = value
    return out


def _summary_lines(header: Mapping[str, Any], digest: str, out: Path,
                   warnings: Sequence[str]) -> List[str]:
    share = header.get("abstention_share")
    lines = [
        f"corpus: {header['examples']} example(s) → {out}",
        "  by source: " + (", ".join(f"{name} {count}" for name, count
                                     in sorted(header["by_source"].items()))
                           or "—"),
        "  by kind:   " + (", ".join(f"{name} {count}" for name, count
                                     in sorted(header["by_kind"].items()))
                           or "—"),
        "  by stance: " + (", ".join(f"{name} {count}" for name, count
                                     in sorted(header["by_stance"].items()))
                           or "—"),
        "  by position: " + (", ".join(
            f"{name} {count}" for name, count
            in sorted(header["by_position"].items())) or "—"),
        "  excluded:  " + (", ".join(f"{name} {count}" for name, count
                                     in sorted(header["excluded"].items()))
                           or "none"),
        "  abstention share: " + ("not computed (no kind-bearing examples)"
                                  if share is None
                                  else f"{share:.0%} "
                                       f"(floor {header['abstention_floor']:.0%})"),
        f"  scrub rewrote something in {header['scrub_changed']} example(s)",
        f"  digest: {digest}",
    ]
    return lines + [f"  ! {warning}" for warning in warnings]


def from_args(args: argparse.Namespace) -> int:
    """``corpus`` as :func:`core.eval.run.main` reaches it."""
    reports = list(getattr(args, "from_extraction", []) or [])
    roots = list(getattr(args, "from_runs", []) or [])
    if not reports and not roots:
        print("corpus: name at least one source — --from-extraction "
              "REPORT.json or --from-runs DIR", file=sys.stderr)
        return 2
    if float(args.floor) < 0 or float(args.floor) >= 1:
        print(f"--floor wants a share in [0, 1), got {args.floor}",
              file=sys.stderr)
        return 2
    try:
        wanted = _filters(args.flag_filter)
    except CorpusRefused as exc:
        print(str(exc), file=sys.stderr)
        return 2

    probes: Dict[str, Probe] = {}
    if args.probes is not None:
        try:
            probes = {probe.id: probe for probe in load_probes(args.probes)}
        except ProbeMisdeclared as exc:
            print(f"corpus: {exc}", file=sys.stderr)
            return 2
        except OSError as exc:
            print(f"--probes: {exc}", file=sys.stderr)
            return 2

    examples: List[Example] = []
    excluded: Counter = Counter()
    sources: List[str] = []
    for path in reports:
        try:
            raw = Path(path).read_bytes()
        except OSError as exc:
            print(f"--from-extraction: {exc}", file=sys.stderr)
            return 2
        try:
            report = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            print(f"--from-extraction {path}: not JSON — {exc}",
                  file=sys.stderr)
            return 2
        try:
            found, dropped = from_extraction(
                report, probes, source=str(path), digest=digest_of(raw),
                note=args.note)
        except CorpusRefused as exc:
            print(f"corpus: {exc}", file=sys.stderr)
            return 1
        examples += found
        excluded.update(dropped)
        sources.append(str(path))

    for root in roots:
        found, dropped = from_runs(Path(root), flag_filter=wanted,
                                   note=args.note)
        examples += found
        excluded.update(dropped)
        sources.append(str(root))

    # Scrub, then look again — in that order, and before the floor is
    # computed, so that a refused example is not counted in a share it will
    # not be part of.
    kept: List[Example] = []
    moved = 0
    for example in examples:
        clean, changed = scrubbed(example)
        found = residue_in(clean.as_dict())
        if found:
            excluded["credential_residue"] += 1
            continue
        moved += 1 if changed else 0
        kept.append(clean)

    warnings: List[str] = []
    if args.balance:
        kept, dropped = balance(kept, floor=float(args.floor), seed=args.seed)
        if dropped:
            excluded["balanced_out"] += dropped

    share = abstention_share(kept)
    if share is not None and share < float(args.floor):
        warnings.append(
            f"the abstain-or-trap share is {share:.0%}, below the floor of "
            f"{float(args.floor):.0%}. ROADMAP §2.9.8 wants this corpus "
            f"abstention-heavy — a compiler that cannot decline to create a "
            f"fact is the failure mode Phase 21 exists for. Written anyway; "
            f"--balance downsamples the assert half to reach it")
    if not kept:
        warnings.append("nothing met the bar; the file holds a header and no "
                        "examples")

    header = header_record(kept, excluded, floor=float(args.floor),
                           note=args.note, sources=sources,
                           scrub_changed=moved)
    text = render(header, kept)
    out = Path(args.out)
    if out.parent and not out.parent.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
    try:
        atomic_write_text(out, text)
    except OSError as exc:
        print(f"--out: {exc}", file=sys.stderr)
        return 2
    digest = digest_of(text)

    if args.json:
        print(json.dumps({"header": header, "digest": digest,
                          "out": str(out), "warnings": warnings}, indent=2))
    else:
        for line in _summary_lines(header, digest, out, warnings):
            print(line)
    return 0
