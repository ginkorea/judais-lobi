# core/eval/linker.py — does the deterministic linker link ONLY what was declared?

"""``python -m core.eval linker`` — the false-link rate, off a probe corpus.

The subject spine (ROADMAP §2.9's W1/W4) joins receipts to subjects
**deterministically**: a link is made only where a platform declared a key
an identity and the receipt carried one value under that key.  The design's
own sentence for why the bar is that high: *a wrong link manufactures
contradictions* — two receipts that never disagreed, joined to one subject,
become a CONTESTED the model is then shown — so the linker's number is the
**false-link rate and the target is ~0**, and this module is the instrument
that measures it (``EVAL.md`` §20).

**Why a subcommand of its own and not a probe kind in ``extraction``.**
The extraction corpus (§13) measures a MODEL: every probe there costs an
endpoint a call, its rates carry Wilson intervals because a model is dice,
and its identity block names a provider and a temperature.  The linker has
no model in it anywhere — the whole path is
:func:`core.runtime.cognition.identities_of`, the cross-kind guard in
:meth:`~core.runtime.cognition.ShadowCognition._identify` and the kernel's
own :meth:`~core.cognition.state.CognitiveState.link` — so a run of this
corpus is exact, free and reproducible byte for byte.  Folding the two into
one probe file would have made every deterministic probe carry a dead
``question`` field and every reader of the report wonder which numbers are
dice.  Different instruments for different subjects, sharing the package's
seams: the corpus idiom (JSONL, ``--probes``, the module names no probe),
the identity rule (§12: a number without its interpreter is not evidence —
the interpreter HERE is the commit and the kernel version, because the
code is the thing being measured), and the report shapes.

**The path under test is the production path.**  Each probe's receipt goes
through a real :class:`~core.runtime.cognition.ShadowCognition` —
:meth:`~core.runtime.cognition.ShadowCognition.receipt` then
:meth:`~core.runtime.cognition.ShadowCognition.close_step`, against a real
kernel store and a real log in a temporary directory — and the verdict is
read back off :meth:`~core.cognition.state.CognitiveState.links` and
:meth:`~core.cognition.state.CognitiveState.query`.  A reimplementation of
the harvest here would measure the reimplementation; the one liberty taken
is the declarations object, a four-line stand-in for
:class:`core.runtime.declarations.PlaneDeclarations` that answers
``identifiers_for`` with the probe's own mapping — because resolution
(wire-beats-manifest, discrepancy notes) is ``test_declarations.py``'s
subject and the linker consumes only the resolved mapping.

**Ground truth is total.**  A probe states every link its receipt should
produce (``expect_links``), so a link not on that list is a **false link**
— there is no "extra but harmless" here, by the design's own argument —
and an expected link not made is a **missed link**, reported apart because
the two failures have opposite costs: a false link manufactures a
contradiction, a missed link only forgoes a join.  Beside the links, a
probe may pin the projected consequences, which is where the cross-kind
guard's disease would show: ``forbid_subject_fields`` names claims a
subject must never hold (a job's id projected onto an asset), and
``expect_subject_fields`` names the projections the join exists to make.
The counters (``ambiguous``, ``unlinked``, ``refused``) are assertable too,
so the adversarial classes — same value under a non-identifier key, two
values under one key, colliding values across kinds, a value that cannot
spell a subject — each pin the exact behaviour the design wrote down.

**An instrument, never a gate.**  Nothing in the mission path reads this
number; the subcommand's exit code follows the package's convention
(non-zero on a red probe unless ``--allow-failures``) so a CI lane MAY
choose to watch it, which is that lane's choice and not this module's.

The probe corpus is data and lives in ``tests/fixtures/cognition``; this
module names no probe, no tool and no deployment.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from core.cognition import EVENT_SCHEMA_VERSION, KERNEL_VERSION
from core.durable import atomic_write_text
from core.eval.measure import _table, commit_of, report_paths
from core.runtime.cognition import ShadowCognition

__all__ = [
    "ProbeMisdeclared", "LinkProbe", "ProbeVerdict", "LinkerReport",
    "load_probes", "run_probe", "run_probes", "add_parser", "from_args",
]


class ProbeMisdeclared(ValueError):
    """This probe cannot mean what it says, and the reason is the news."""


#: The keys a probe may carry.  A closed set, refused loudly on anything
#: else: a misspelled ``expect_linsk`` that was silently ignored would be a
#: probe that can never fail, wearing the name of one that can.
_PROBE_KEYS = frozenset({
    "id", "why", "tool", "identifiers", "receipt", "receipt_text",
    "expect_links", "forbid_subject_fields", "expect_subject_fields",
    "expect_ambiguous", "expect_unlinked", "expect_refused",
})


@dataclass(frozen=True)
class LinkProbe:
    """One receipt with its subject identity fully known."""

    id: str
    #: What this probe exists to prove — printed beside a failure.
    why: str
    #: The tool the receipt pretends to come from; part of the entity name.
    tool: str
    #: ``{declared key path: kind}`` — the RESOLVED mapping, exactly what
    #: :meth:`~core.runtime.declarations.PlaneDeclarations.identifiers_for`
    #: answers for the tool.
    identifiers: Mapping[str, str]
    #: The receipt's payload, as the text the plane wrote.  One of the two
    #: source keys: ``receipt`` (an object, serialised canonically here) or
    #: ``receipt_text`` (raw text, for multi-block and adversarial shapes).
    text: str
    #: Every subject this receipt must link — total, so any other link made
    #: is a false one.
    expect_links: Tuple[str, ...] = ()
    #: ``{subject: (field, …)}`` the store must NOT claim on that subject —
    #: the cross-kind guard's disease, pinned.
    forbid_subject_fields: Mapping[str, Tuple[str, ...]] = \
        field(default_factory=dict)
    #: ``{subject: (field, …)}`` the store MUST claim there — the positive
    #: control, so a linker that links nothing cannot pass by silence.
    expect_subject_fields: Mapping[str, Tuple[str, ...]] = \
        field(default_factory=dict)
    #: The counters, where the probe pins them; ``None`` is unchecked.
    expect_ambiguous: Optional[int] = None
    expect_unlinked: Optional[int] = None
    expect_refused: Optional[int] = None


def load_probes(path: Path) -> Tuple[LinkProbe, ...]:
    """The corpus at *path*, refused whole on the first malformed line.

    Whole, not partially: a corpus with one bad probe silently dropped
    would report a rate over a denominator nobody chose.
    """
    out: List[LinkProbe] = []
    seen: set = set()
    for number, line in enumerate(
            Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        where = f"{path}:{number}"
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ProbeMisdeclared(f"{where}: not JSON ({exc})") from exc
        if not isinstance(raw, Mapping):
            raise ProbeMisdeclared(f"{where}: a probe is an object")
        unknown = sorted(set(raw) - _PROBE_KEYS)
        if unknown:
            raise ProbeMisdeclared(
                f"{where}: unknown key(s) {unknown} — a key this runner "
                f"ignores is an assertion that can never fail")
        probe = _probe_from(raw, where)
        if probe.id in seen:
            raise ProbeMisdeclared(f"{where}: duplicate id {probe.id!r}")
        seen.add(probe.id)
        out.append(probe)
    if not out:
        raise ProbeMisdeclared(f"{path}: no probes at all")
    return tuple(out)


def _fields_map(raw: Any, where: str, key: str
                ) -> Dict[str, Tuple[str, ...]]:
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise ProbeMisdeclared(f"{where}: {key} is an object of "
                               f"subject → [field, …]")
    out: Dict[str, Tuple[str, ...]] = {}
    for subject, names in raw.items():
        if not isinstance(names, Sequence) or isinstance(names, str):
            raise ProbeMisdeclared(f"{where}: {key}[{subject!r}] is a list")
        out[str(subject)] = tuple(str(name) for name in names)
    return out


def _count(raw: Any, where: str, key: str) -> Optional[int]:
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
        raise ProbeMisdeclared(f"{where}: {key} is a count")
    return raw


def _probe_from(raw: Mapping[str, Any], where: str) -> LinkProbe:
    for wanted in ("id", "why", "tool", "identifiers"):
        if not raw.get(wanted):
            raise ProbeMisdeclared(f"{where}: {wanted!r} is required")
    identifiers = raw["identifiers"]
    if not isinstance(identifiers, Mapping) or not all(
            isinstance(k, str) and isinstance(v, str)
            for k, v in identifiers.items()):
        raise ProbeMisdeclared(
            f"{where}: identifiers is {{key path: kind}}, both strings")
    has_object = "receipt" in raw
    has_text = "receipt_text" in raw
    if has_object == has_text:
        raise ProbeMisdeclared(
            f"{where}: exactly one of receipt / receipt_text — a probe "
            f"with both would be two receipts wearing one id")
    if has_object:
        # Canonical JSON, because that is what a wire payload is: the
        # production path reads receipts as text and a probe stored as an
        # object is serialised HERE, once, rather than by every reader.
        text = json.dumps(raw["receipt"], ensure_ascii=False, sort_keys=True)
    else:
        text = str(raw["receipt_text"])
    links = raw.get("expect_links")
    if links is None or isinstance(links, str) or \
            not isinstance(links, Sequence):
        raise ProbeMisdeclared(
            f"{where}: expect_links is required and is a list — TOTAL "
            f"ground truth is the point, and an absent list would read "
            f"as 'no opinion', which no probe here is allowed to have")
    return LinkProbe(
        id=str(raw["id"]), why=str(raw["why"]), tool=str(raw["tool"]),
        identifiers={str(k): str(v) for k, v in identifiers.items()},
        text=text,
        expect_links=tuple(str(name) for name in links),
        forbid_subject_fields=_fields_map(
            raw.get("forbid_subject_fields"), where, "forbid_subject_fields"),
        expect_subject_fields=_fields_map(
            raw.get("expect_subject_fields"), where, "expect_subject_fields"),
        expect_ambiguous=_count(raw.get("expect_ambiguous"), where,
                                "expect_ambiguous"),
        expect_unlinked=_count(raw.get("expect_unlinked"), where,
                               "expect_unlinked"),
        expect_refused=_count(raw.get("expect_refused"), where,
                              "expect_refused"),
    )


# ── running one probe ────────────────────────────────────────────────────────

class _Plane:
    """The resolved declarations, and nothing else — see the module doc.

    Duck-typed to the two calls the shadow makes on a declarations object
    at receipt time: :meth:`identifiers_for` (the mapping under test) and
    :meth:`for_tool` (the link's declaration ref; ``None`` renders an
    unlocated declaration, which the evidence path accepts).  Resolution
    itself — which door won, discrepancy notes — is
    ``PlaneDeclarations``'s subject and has its own tests.
    """

    def __init__(self, identifiers: Mapping[str, str]) -> None:
        self._identifiers = dict(identifiers)

    def identifiers_for(self, tool: Any) -> Mapping[str, str]:
        return dict(self._identifiers)

    def for_tool(self, tool: Any) -> Any:
        return None


@dataclass(frozen=True)
class ProbeVerdict:
    """One probe's outcome: what linked, what should have."""

    id: str
    why: str
    #: Every subject actually linked, sorted.
    linked: Tuple[str, ...]
    #: Links made that the ground truth does not hold — THE number.
    false_links: Tuple[str, ...]
    #: Links owed and not made.
    missed_links: Tuple[str, ...]
    #: Every other broken pin, as sentences.
    problems: Tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not (self.false_links or self.missed_links or self.problems)

    def as_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "why": self.why, "passed": self.passed,
                "linked": list(self.linked),
                "false_links": list(self.false_links),
                "missed_links": list(self.missed_links),
                "problems": list(self.problems)}


def run_probe(probe: LinkProbe) -> ProbeVerdict:
    """One receipt through the production attachment, and the reckoning.

    A fresh shadow per probe, in a directory that exists only for the
    call: probes must not be able to contaminate each other, or the
    corpus's order would become part of its meaning.
    """
    problems: List[str] = []
    with tempfile.TemporaryDirectory(prefix="linker-") as scratch:
        shadow = ShadowCognition(Path(scratch) / "reasoning.jsonl",
                                 run_id=f"probe-{probe.id}")
        shadow.declarations = _Plane(probe.identifiers)
        shadow.receipt(probe.tool, 1, probe.text)
        shadow.close_step()

        # A probe that crashed cognition is RED, never a silent pass over
        # an empty store: the instrument must not bless a crash as caution.
        if not shadow.on or shadow.failures:
            problems.append(
                "cognition STOPPED on this receipt — the attachment "
                "raised, which no receipt may make it do")

        state = shadow.state
        linked = sorted({link.subject for link in state.links()})
        expected = set(probe.expect_links)
        false_links = sorted(set(linked) - expected)
        missed_links = sorted(expected - set(linked))

        for subject, names in probe.forbid_subject_fields.items():
            held = {prop.triple[1] for prop in state.query(
                (subject, "?field", "?value"))}
            for name in names:
                if name in held:
                    problems.append(
                        f"subject {subject!r} holds forbidden field "
                        f"{name!r} — a manufactured cross-kind claim")
        for subject, names in probe.expect_subject_fields.items():
            held = {prop.triple[1] for prop in state.query(
                (subject, "?field", "?value"))}
            for name in names:
                if name not in held:
                    problems.append(
                        f"subject {subject!r} does not hold expected "
                        f"field {name!r} — the join this link exists "
                        f"for did not happen")

        for wanted, counter in (
                (probe.expect_ambiguous, "ambiguous"),
                (probe.expect_unlinked, "unlinked"),
                (probe.expect_refused, "refused")):
            if wanted is None:
                continue
            got = getattr(shadow, counter)
            if got != wanted:
                problems.append(
                    f"{counter} is {got}, probe expects {wanted}")

    return ProbeVerdict(
        id=probe.id, why=probe.why, linked=tuple(linked),
        false_links=tuple(false_links), missed_links=tuple(missed_links),
        problems=tuple(problems))


# ── the report ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class LinkerReport:
    """Every probe's verdict, and the interpreter that produced them."""

    verdicts: Tuple[ProbeVerdict, ...]
    meta: Mapping[str, Any] = field(default_factory=dict)

    @property
    def links_made(self) -> int:
        return sum(len(verdict.linked) for verdict in self.verdicts)

    @property
    def false_links(self) -> int:
        return sum(len(verdict.false_links) for verdict in self.verdicts)

    @property
    def missed_links(self) -> int:
        return sum(len(verdict.missed_links) for verdict in self.verdicts)

    @property
    def passed(self) -> int:
        return len([verdict for verdict in self.verdicts if verdict.passed])

    def as_dict(self) -> Dict[str, Any]:
        return {
            "meta": dict(self.meta),
            "probes": len(self.verdicts),
            "passed": self.passed,
            "links_made": self.links_made,
            "false_links": self.false_links,
            "missed_links": self.missed_links,
            "verdicts": [verdict.as_dict() for verdict in self.verdicts],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.as_dict(), indent=indent)

    def to_markdown(self) -> str:
        return _markdown(self)


def run_probes(probes: Sequence[LinkProbe], *,
               only: Sequence[str] = ()) -> LinkerReport:
    """The corpus, run.  Deterministic: same corpus, same report."""
    wanted = [str(name) for name in only]
    unknown = [name for name in wanted
               if name not in {probe.id for probe in probes}]
    if unknown:
        raise ProbeMisdeclared(
            f"--only names {unknown}; the corpus holds "
            f"{sorted(probe.id for probe in probes)}")
    chosen = [probe for probe in probes
              if not wanted or probe.id in wanted]
    return LinkerReport(
        verdicts=tuple(run_probe(probe) for probe in chosen),
        # The interpreter is the CODE: no provider, no temperature, no
        # prompt — the commit and the kernel say which linker ran, and
        # rerunning at the same pair reproduces the bytes.
        meta={"commit": commit_of(),
              "kernel": KERNEL_VERSION,
              "event_schema": EVENT_SCHEMA_VERSION,
              "deterministic": True})


def _markdown(report: LinkerReport) -> str:
    meta = report.meta
    lines = [
        "# linker — the false-link rate", "",
        f"- **commit** `{meta.get('commit', 'unknown')}` — the "
        f"interpreter: this instrument has no model in it, so the code IS "
        f"the thing measured and a rerun at this commit reproduces these "
        f"bytes exactly",
        f"- **kernel** `{meta.get('kernel')}`, event schema "
        f"`{meta.get('event_schema')}`",
        f"- **probes** {len(report.verdicts)}, passed {report.passed}",
        f"- **false links** {report.false_links} of {report.links_made} "
        f"made — the target is ~0, because a wrong link manufactures "
        f"contradictions",
        f"- **missed links** {report.missed_links} — reported apart: a "
        f"missed join forgoes a fact, a false one invents a dispute",
        "",
    ]
    rows = [[f"`{verdict.id}`",
             "PASS" if verdict.passed else "FAIL",
             str(len(verdict.linked)),
             ", ".join(f"`{name}`" for name in verdict.false_links) or "—",
             ", ".join(f"`{name}`" for name in verdict.missed_links) or "—",
             "; ".join(verdict.problems) or "—"]
            for verdict in report.verdicts]
    lines += _table(rows, ["probe", "verdict", "links", "false", "missed",
                           "problems"])
    lines.append("")
    for verdict in report.verdicts:
        if not verdict.passed:
            lines.append(f"- **`{verdict.id}`**: {verdict.why}")
    return "\n".join(lines).rstrip() + "\n"


# ── the command line ─────────────────────────────────────────────────────────

def add_parser(subs) -> argparse.ArgumentParser:
    """Register ``linker`` on :func:`core.eval.run._parser`'s subparsers.

    From here, the way every other subcommand registers itself.  Without
    ``common``: a link probe is not a mission — no suite, no half, nothing
    to spawn, and **no model**.
    """
    parser = subs.add_parser(
        "linker",
        help="run the false-link probe corpus through the production "
             "attachment and report the false-link rate (target ~0)")
    parser.add_argument("--probes", required=True, type=Path, metavar="PATH",
                        help="the JSONL probe corpus; the one this "
                             "repository ships is "
                             "tests/fixtures/cognition/link_probes.jsonl")
    parser.add_argument("--only", action="append", default=[], metavar="ID",
                        help="run only this probe; repeatable")
    parser.add_argument("--json", action="store_true",
                        help="print JSON instead of the Markdown table")
    parser.add_argument("--report", type=Path, metavar="PATH",
                        help="write the table here as Markdown, and the "
                             "same report as JSON beside it")
    parser.add_argument("--allow-failures", action="store_true",
                        help="exit 0 even when probes failed")
    return parser


def from_args(args: argparse.Namespace) -> int:
    """``linker`` as :func:`core.eval.run.main` reaches it."""
    try:
        probes = load_probes(args.probes)
        report = run_probes(probes, only=args.only)
    except (ProbeMisdeclared, OSError) as exc:
        print(f"linker: {exc}", file=sys.stderr)
        return 2
    print(report.to_json() if args.json else report.to_markdown())
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        markdown, beside = report_paths(args.report)
        atomic_write_text(markdown, report.to_markdown())
        atomic_write_text(beside, report.to_json())
    failed = len(report.verdicts) - report.passed
    return 0 if args.allow_failures or not failed else 1
