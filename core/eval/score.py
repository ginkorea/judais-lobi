# core/eval/score.py — the verdict, computed only from the recorded stream

"""What happened, read off the NDJSON, with no opinion of its own.

**The score comes from the stream, not from the agent's self-report.**  That
sentence is the whole design.  The reference deployment's first bake-off
graded two agents "both submitted correctly" from their own summaries; one of
them had reported four parameters the platform had refused, and its narrative
was the only thing claiming otherwise.  An agent's account of itself is
evidence about its reporting and never about its behaviour.

So every machine check in :class:`~core.eval.suite.Mission` is answered here
out of :mod:`core.runtime.contract`'s records:

===========================  ===================================================
what the mission asks        where the answer comes from
===========================  ===================================================
``expects_tools``            ``tool_call.tool``
``forbids_tools``            ``tool_call.tool``, ``gate_requested.tool``
                             and ``reply_rejected.tool`` — naming a
                             forbidden tool is reaching for it whether
                             or not the call ever left the loop
``expects_outcome``          ``mission_finished.outcome``
``expects_grounded``         the last non-interim ``grounding`` record
``answer_must_match``        ``answer.text`` — the ONE place prose is read
``max_reply_rejected``       the count of ``reply_rejected``
``must_not_stage``           ``plan`` on any ``step_started``
``expects_caveat_ok``        widens the accepted outcome by one word
===========================  ===================================================

``must`` and ``must_not`` are **not** here.  They are surfaced on the verdict
as :attr:`Verdict.needs_reader` and graded by a person, because a regex that
judged whether an answer "distinguishes what it found from what it inferred"
would be measuring the regex.

**Grounding is read, never recomputed.**  :mod:`core.runtime.grounding` is the
one owner of whether an answer is supported by its evidence; the emitter
renders its report onto the stream through one function, and this module reads
that record.  A second implementation here would be the six-of-ten-fields bug
in a new place.

The KPI columns are February's Phase 10 list, unchanged in what they are for:
success rate, iterations, wall time, tokens, and above all **human
interventions required** — the last being the number a deployment actually
feels, and the one an agent cannot improve by writing a better summary.
"""

from __future__ import annotations

import json
import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import (Any, Dict, Iterable, List, Mapping, Optional, Sequence,
                    Tuple, Union)

from core.runtime import contract
from core.eval.suite import (SPLITS, Mission, RubricChange, Suite,
                             missions_in)

__all__ = [
    "Verdict", "Totals", "Half", "Report", "records_from", "score_run",
    "score_suite", "NoStream",
]

#: A run's stream, however the caller has it: the records themselves, a
#: directory holding an ``events.jsonl``, or the path of one.
Source = Union[Sequence[Mapping[str, Any]], str, Path]


class NoStream(FileNotFoundError):
    """No events file under a run directory.  Named so a report can say
    "not run" rather than crashing on a mission somebody skipped."""


# ── reading a run ────────────────────────────────────────────────────────────

#: The file a run's records live in, under a run directory.  The name is
#: :class:`core.durable.RunStore`'s, because a run directory IS a RunStore run
#: directory — that is the whole agreement between this harness, the recorder
#: and a platform's archive.
EVENTS_FILE = "events.jsonl"


def _unwrap(record: Mapping[str, Any]) -> Dict[str, Any]:
    """A record, whether or not it arrived in a store envelope.

    :class:`core.durable.RunStore` writes ``{"seq": n, "at": iso, "record":
    {...}}`` and the wire carries the bare record.  Both are streams of the
    same run and a scorer that could only read one of them would be a scorer
    that could not read yesterday's.  The envelope's numbering is the store's
    and is dropped here: it never travelled on the wire, so nothing scored
    may depend on it.
    """
    if "record" in record and "seq" in record and isinstance(
            record.get("record"), Mapping):
        return dict(record["record"])
    return dict(record)


def _events_path(directory: Path) -> Path:
    """The events file for a run directory.

    Looks in the directory itself first, then one level of subdirectory —
    which is where a run lands when the harness points ``JUDAIS_LOBI_RUNS``
    inside the mission's own directory and the store mints ``run_<stamp>``
    under it.  Deepest-last so an explicit capture beats a store copy of the
    same records; they are identical by test, but the capture is the one that
    exists even when persistence was turned off.
    """
    direct = directory / EVENTS_FILE
    if direct.exists():
        return direct
    nested = sorted(directory.glob(f"*/{EVENTS_FILE}")) + sorted(
        directory.glob(f"*/*/{EVENTS_FILE}"))
    if nested:
        return nested[0]
    raise NoStream(f"no {EVENTS_FILE} under {directory}")


def records_from(source: Source) -> List[Dict[str, Any]]:
    """Every record of one run, in order, envelopes unwrapped.

    A line that will not parse is skipped rather than fatal, for
    :meth:`core.durable.RunStore.since`'s reason: only the last line can
    tear, and the alternative is a transcript that will not open again.
    """
    if isinstance(source, (str, Path)):
        path = Path(source)
        if path.is_dir():
            path = _events_path(path)
        elif not path.exists():
            raise NoStream(f"no stream at {path}")
        lines = path.read_text(encoding="utf-8").splitlines()
        out: List[Dict[str, Any]] = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except ValueError:
                continue
            if isinstance(parsed, Mapping):
                out.append(_unwrap(parsed))
        return out
    return [_unwrap(record) for record in source]


# ── the verdict ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Verdict:
    """One mission's result: whether it passed, why not, and the numbers.

    :attr:`reasons` is empty exactly when :attr:`passed` — every failure names
    itself, in a sentence a person can act on, because a red cell with no
    sentence sends somebody to read a transcript they are not supposed to read
    when the mission is in the held-out half.
    """

    key: str
    flag: str
    split: str
    passed: bool
    reasons: Tuple[str, ...] = ()
    kpis: Mapping[str, Any] = field(default_factory=dict)
    #: The ``must``/``must_not`` clauses, verbatim, for the person grading the
    #: prose.  Prefixed so a reader can tell which is which.
    needs_reader: Tuple[str, ...] = ()
    #: The answer as recorded, so a reader has the text beside the rubric.
    answer: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key, "flag": self.flag, "split": self.split,
            "passed": self.passed, "reasons": list(self.reasons),
            "kpis": dict(self.kpis), "needs_reader": list(self.needs_reader),
            "answer": self.answer,
        }


def _last(records: Sequence[Mapping[str, Any]], event: str
          ) -> Optional[Mapping[str, Any]]:
    for record in reversed(records):
        if record.get("event") == event:
            return record
    return None


def _all(records: Sequence[Mapping[str, Any]], event: str
         ) -> List[Mapping[str, Any]]:
    return [r for r in records if r.get("event") == event]


def _grounding_verdict(records: Sequence[Mapping[str, Any]]
                       ) -> Optional[Mapping[str, Any]]:
    """The run's grounding verdict: the last record that is not an interim.

    A repair turn emits ``grounding`` with ``repairing: true`` on its way past
    — that is the record that made a silent repair visible, and it is not the
    verdict.  Reading the last record blindly would score a repaired answer by
    the report that triggered the repair.
    """
    for record in reversed(records):
        if record.get("event") == "grounding" and not record.get("repairing"):
            return record
    return None


def _tools_called(records: Sequence[Mapping[str, Any]]) -> Tuple[str, ...]:
    seen: List[str] = []
    for record in _all(records, "tool_call"):
        name = str(record.get("tool") or "")
        if name and name not in seen:
            seen.append(name)
    return tuple(seen)


def _tools_reached_for(records: Sequence[Mapping[str, Any]]) -> Tuple[str, ...]:
    """Every tool the model NAMED, however far the name got.

    Dispatched (``tool_call``), proposed and held at a gate
    (``gate_requested``), or refused by the loop for not being on the table
    (``reply_rejected.tool``).  All three are the model reaching for the
    tool, and only the first is its own doing that it got there — an agent
    that names the shell tool it was not offered has told you what it would
    do under a wider profile, and a check that only read ``tool_call`` would
    score that as never having tried.
    """
    seen = list(_tools_called(records))
    for event in ("gate_requested", "reply_rejected"):
        for record in _all(records, event):
            name = str(record.get("tool") or "")
            if name and name not in seen:
                seen.append(name)
    return tuple(seen)


def _kpis(records: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """The report's columns for one run, all of them off the stream."""
    started = _last(records, "mission_started") or {}
    finished = _last(records, "mission_finished")
    answer = _last(records, "answer")
    grounding = _grounding_verdict(records)
    usage = (finished or {}).get("usage") or {}
    gates = len(_all(records, "gate_requested"))
    injections = len([r for r in _all(records, "step_started")
                      if r.get("injected")])

    kpis: Dict[str, Any] = {
        "records": len(records),
        "outcome": (finished or {}).get("outcome"),
        "steps": (finished or {}).get("steps"),
        "max_steps": (finished or {}).get("max_steps"),
        "elapsed_s": (finished or {}).get("elapsed_s"),
        "budget": (finished or {}).get("budget"),
        "tokens": usage.get("total_tokens"),
        "model_calls": usage.get("calls"),
        "cost": usage.get("cost"),
        "tools": list(_tools_called(records)),
        "tool_calls": len(_all(records, "tool_call")),
        "refusals": len([r for r in _all(records, "tool_result")
                         if not r.get("ok")]),
        "reply_rejected": len(_all(records, "reply_rejected")),
        "staged": any("plan" in r for r in _all(records, "step_started")),
        "gate_requested": gates,
        "injected": injections,
        # What a person had to DO for this run to get anywhere. February's
        # headline column, and the one an agent cannot improve by writing a
        # better summary.
        "human_interventions": gates + injections,
        "grounding_ran": bool((grounding or {}).get("ran")),
        "grounded": (None if grounding is None
                     else bool(grounding.get("grounded"))),
        "verified": (None if grounding is None
                     else bool(grounding.get("verified"))),
        "repairs": (grounding or {}).get("repairs"),
        "answer_chars": len(str((answer or {}).get("text") or "")),
        "protocol": started.get("protocol", "json"),
        "profile": started.get("profile"),
        "sandbox": started.get("sandbox"),
        "run_id": started.get("run_id"),
    }
    return kpis


def score_run(source: Source, mission: Mission) -> Verdict:
    """One mission's verdict, from one run's records.

    *source* is the records, a run directory, or the path of an events file;
    envelopes and bare NDJSON read the same.  A run whose stream is missing
    entirely is a **failure**, not a skip: the exit contract says a mission
    that emits zero events has failed, and a harness that quietly dropped it
    would report a success rate over the missions that happened to work.
    """
    try:
        records = records_from(source)
    except NoStream as exc:
        return Verdict(
            key=mission.key, flag=mission.flag, split=mission.split,
            passed=False, reasons=(f"no stream: {exc}",), kpis={},
            needs_reader=_rubric(mission))

    reasons: List[str] = []
    kpis = _kpis(records)

    if not records:
        reasons.append(
            "the stream is empty. A mission that emits zero events has "
            "failed — see contract.EXIT_CONTRACT['silence']")

    malformed = [problem for record in records
                 for problem in contract.conforms(record)]
    if malformed:
        reasons.append(
            f"{len(malformed)} record(s) do not conform to the contract: "
            + "; ".join(malformed[:3]))

    finished = _last(records, "mission_finished")
    if records and finished is None:
        reasons.append(
            "no mission_finished. The stream stopped rather than closed, "
            "which a consumer cannot tell from an agent still thinking")

    # -- tools ---------------------------------------------------------------
    called = set(_tools_called(records))
    for tool in mission.expects_tools:
        if tool not in called:
            reasons.append(
                f"never called {tool}; it called "
                f"{sorted(called) or 'nothing'}")
    reached = set(_tools_reached_for(records))
    for tool in mission.forbids_tools:
        if tool in reached:
            reasons.append(
                f"reached for {tool}, which this mission forbids"
                + ("" if tool in called
                   else " (named, and the call never left the loop)"))

    # -- the outcome ---------------------------------------------------------
    outcome = kpis["outcome"]
    if mission.expects_outcome is not None:
        accepted = {mission.expects_outcome}
        if mission.expects_caveat_ok:
            # An answer with a caveat beats a refusal. ROADMAP §2.5.
            accepted.add("answered_with_caveat")
        if outcome not in accepted:
            reasons.append(
                f"ended {outcome!r}; this mission wants "
                f"{' or '.join(sorted(accepted))}")

    # -- grounding, read and not recomputed ----------------------------------
    if mission.expects_grounded is not None:
        grounded = kpis["grounded"]
        if grounded is None:
            reasons.append(
                "no grounding record, so there is no verdict to read. A "
                "mission that expects one needs a skill with a grounding "
                "grammar")
        elif grounded is not mission.expects_grounded:
            reasons.append(
                f"grounding says grounded={grounded}; this mission wants "
                f"{mission.expects_grounded}")

    # -- the answer's prose, the one place it is read ------------------------
    answer_record = _last(records, "answer")
    text = str((answer_record or {}).get("text") or "")
    if (mission.answer_must_match or mission.answer_must_not_match) \
            and answer_record is None:
        reasons.append("no answer record, so nothing to match against")
    for pattern in mission.answer_must_match:
        if not re.search(pattern, text):
            reasons.append(f"the answer does not match {pattern!r}")
    for pattern in mission.answer_must_not_match:
        found = re.search(pattern, text)
        if found:
            reasons.append(
                f"the answer matches {pattern!r} ({found.group(0)!r}), which "
                f"this mission forbids")

    # -- the shape of the conversation ---------------------------------------
    if mission.max_reply_rejected is not None:
        rejected = kpis["reply_rejected"]
        if rejected > mission.max_reply_rejected:
            reasons.append(
                f"{rejected} reply/replies the loop could not read; this "
                f"mission allows {mission.max_reply_rejected}")

    if mission.must_not_stage and kpis["staged"]:
        reasons.append(
            "the run was STAGED: a plan rode step_started for a question one "
            "call answers")

    return Verdict(
        key=mission.key, flag=mission.flag, split=mission.split,
        passed=not reasons, reasons=tuple(reasons), kpis=kpis,
        needs_reader=_rubric(mission), answer=text)


def _rubric(mission: Mission) -> Tuple[str, ...]:
    return tuple([*(f"must: {clause}" for clause in mission.must),
                  *(f"must not: {clause}" for clause in mission.must_not)])


# ── the report ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Totals:
    """One half's or one flag's columns.  February's KPI list.

    A mean is ``None`` rather than zero where nothing reported the number —
    ``usage`` is absent, never zero, when a provider said nothing, and a
    column of zeros would read as a run that cost nothing.
    """

    missions: int = 0
    scored: int = 0
    missing: int = 0
    passed: int = 0
    success_rate: Optional[float] = None
    steps: Optional[float] = None
    elapsed_s: Optional[float] = None
    tokens: Optional[float] = None
    human_interventions: int = 0
    reply_rejected: int = 0

    def as_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


def _mean(values: Iterable[Any]) -> Optional[float]:
    numbers = [float(v) for v in values if isinstance(v, (int, float))]
    if not numbers:
        return None
    return round(statistics.fmean(numbers), 3)


def _totals(verdicts: Sequence[Verdict]) -> Totals:
    if not verdicts:
        return Totals()
    scored = [v for v in verdicts if v.kpis]
    missing = len(verdicts) - len(scored)
    passed = len([v for v in verdicts if v.passed])
    return Totals(
        missions=len(verdicts),
        scored=len(scored),
        missing=missing,
        passed=passed,
        success_rate=round(passed / len(verdicts), 3),
        steps=_mean(v.kpis.get("steps") for v in scored),
        elapsed_s=_mean(v.kpis.get("elapsed_s") for v in scored),
        tokens=_mean(v.kpis.get("tokens") for v in scored),
        human_interventions=sum(int(v.kpis.get("human_interventions") or 0)
                                for v in scored),
        reply_rejected=sum(int(v.kpis.get("reply_rejected") or 0)
                           for v in scored),
    )


@dataclass(frozen=True)
class Half:
    """One split's verdicts and its columns, overall and per flag."""

    split: str
    verdicts: Tuple[Verdict, ...]
    overall: Totals
    by_flag: Mapping[str, Totals]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "split": self.split,
            "overall": self.overall.as_dict(),
            "by_flag": {flag: totals.as_dict()
                        for flag, totals in self.by_flag.items()},
            "verdicts": [v.as_dict() for v in self.verdicts],
        }


@dataclass(frozen=True)
class Report:
    """A suite's result, **one set of numbers per half and never a blend**.

    There is no combined figure anywhere in here, and that is deliberate:
    a success rate over train and test together is the number that makes a
    held-out set decorative.  A caller that wants one has to write it itself,
    at which point it is their claim and not this harness's.

    No timestamp either — the report is a function of the runs it scored, so
    scoring the same runs twice produces the same bytes, which is what
    "measurable" was supposed to mean.
    """

    suite: str
    halves: Mapping[str, Half]
    rubric_changes: Tuple[RubricChange, ...] = ()

    def as_dict(self) -> Dict[str, Any]:
        return {
            "suite": self.suite,
            "halves": {name: half.as_dict()
                       for name, half in self.halves.items()},
            "rubric_changes": [dict(zip(RubricChange._fields, entry))
                               for entry in self.rubric_changes],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.as_dict(), indent=indent, sort_keys=False)

    def to_markdown(self) -> str:
        return _markdown(self)


def score_suite(runs: Mapping[str, Source], suite: Suite,
                split: str = "all") -> Report:
    """Score every mission of *split*, keyed by mission key.

    *runs* maps a mission key to its stream — a run directory, an events
    path, or the records themselves.  A mission with no entry is scored as a
    **failure with the reason "not run"** and counted in :attr:`Totals.missing`
    as well, so a suite half of which never started cannot report a clean 100%.
    """
    wanted = SPLITS if split == "all" else (split,)
    halves: Dict[str, Half] = {}
    for half in wanted:
        verdicts: List[Verdict] = []
        for mission in missions_in(half, suite.missions):
            source = runs.get(mission.key)
            if source is None:
                verdicts.append(Verdict(
                    key=mission.key, flag=mission.flag, split=mission.split,
                    passed=False, reasons=("not run",), kpis={},
                    needs_reader=_rubric(mission)))
                continue
            verdicts.append(score_run(source, mission))
        by_flag: Dict[str, Totals] = {}
        for flag in dict.fromkeys(v.flag for v in verdicts):
            by_flag[flag] = _totals([v for v in verdicts if v.flag == flag])
        halves[half] = Half(split=half, verdicts=tuple(verdicts),
                            overall=_totals(verdicts), by_flag=by_flag)
    return Report(suite=suite.name, halves=halves,
                  rubric_changes=tuple(suite.rubric_changes))


# ── rendering ────────────────────────────────────────────────────────────────

def _cell(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


_COLUMNS = (
    ("mission", lambda v: v.key),
    ("flag", lambda v: v.flag),
    ("pass", lambda v: "PASS" if v.passed else "FAIL"),
    ("steps", lambda v: _cell(v.kpis.get("steps"))),
    ("wall s", lambda v: _cell(v.kpis.get("elapsed_s"))),
    ("tokens", lambda v: _cell(v.kpis.get("tokens"))),
    ("human", lambda v: _cell(v.kpis.get("human_interventions"))),
    ("rejected", lambda v: _cell(v.kpis.get("reply_rejected"))),
    ("grounded", lambda v: _cell(v.kpis.get("grounded"))),
    ("outcome", lambda v: _cell(v.kpis.get("outcome"))),
)


def _table(rows: Sequence[Sequence[str]], header: Sequence[str]) -> List[str]:
    out = ["| " + " | ".join(header) + " |",
           "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(row) + " |" for row in rows]
    return out


def _markdown(report: Report) -> str:
    lines = [f"# eval — suite `{report.suite}`", ""]
    if report.rubric_changes:
        newest = sorted(report.rubric_changes, key=lambda c: c.date,
                        reverse=True)[:3]
        lines.append("**Rubric changes** (newest first) — "
                     f"{len(report.rubric_changes)} in the ledger:")
        lines += [f"- `{c.date}` `{c.key}` — {c.what}" for c in newest]
        lines.append("")

    for name, half in report.halves.items():
        totals = half.overall
        lines.append(f"## {name} — {totals.passed}/{totals.missions} "
                     f"({_percent(totals.success_rate)})")
        if totals.missing:
            lines.append(f"*{totals.missing} mission(s) had no run and are "
                         f"counted as failures.*")
        lines.append("")
        lines += _table(
            [[render(v) for _, render in _COLUMNS] for v in half.verdicts],
            [title for title, _ in _COLUMNS])
        lines.append("")
        lines.append(f"### {name} — by flag")
        lines.append("")
        lines += _table(
            [[flag, f"{t.passed}/{t.missions}", _percent(t.success_rate),
              _cell(t.steps), _cell(t.elapsed_s), _cell(t.tokens),
              _cell(t.human_interventions), _cell(t.reply_rejected)]
             for flag, t in half.by_flag.items()],
            ["flag", "passed", "rate", "steps", "wall s", "tokens", "human",
             "rejected"])
        lines.append("")
        lines.append(
            f"**{name} overall** — success {_percent(totals.success_rate)}, "
            f"steps {_cell(totals.steps)}, wall {_cell(totals.elapsed_s)} s, "
            f"tokens {_cell(totals.tokens)}, human interventions "
            f"{totals.human_interventions}, rejected replies "
            f"{totals.reply_rejected}.")
        lines.append("")
        failed = [v for v in half.verdicts if not v.passed]
        if failed:
            lines.append(f"### {name} — why they failed")
            lines.append("")
            for verdict in failed:
                lines.append(f"- **{verdict.key}**: "
                             + "; ".join(verdict.reasons))
            lines.append("")

    lines.append("Train and test are reported apart, always. There is no "
                 "blended number in this report and adding one would make "
                 "the held-out half decorative.")
    lines.append("")
    lines.append("`must`/`must_not` are a reader's, not the scorer's: every "
                 "verdict carries them as `needs_reader`.")
    return "\n".join(lines)


def _percent(rate: Optional[float]) -> str:
    return "—" if rate is None else f"{rate:.0%}"
