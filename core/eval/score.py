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
``expects_carried``          a literal in a ``tool_result``'s ``output`` or
                             ``error`` — never in the arguments the result
                             echoes back — and then in a LATER
                             ``tool_call.arguments`` of the same emitter
``expects_recovered``        a ``tool_result`` with ``ok: false`` for a name,
                             and a later one with ``ok: true`` for the same,
                             from the same emitter
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

Beside them there is now one column that is not about the agent at all.  A
run that never reached its model measured the **environment**, and scoring it
as a FAIL is a claim about a model that was never asked: the reference
deployment lost thirteen missions to an endpoint blink and read them off the
table as thirteen model failures.  So such a run is classed ``infra``, kept
out of the rate's denominator, and printed with its run ids — see
:func:`infra_reason` for the rule and ``EVAL.md`` §6 for what it is worth.
It is never dropped: a column that silently disappeared would be the same
error told the other way round.
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
    "score_suite", "NoStream", "MODEL_SPOKE", "ERRORED", "infra_reason",
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
    #: The mission's class, when its suite groups missions into any — see
    #: :attr:`core.eval.suite.Mission.mission_class`.  ``""`` for a suite
    #: that does not, which is every suite written before classes existed.
    mission_class: str = ""
    #: Why this run measured the ENVIRONMENT and not the agent, or ``""``.
    #: See :func:`infra_reason`.  Non-empty keeps the verdict out of the
    #: rate's denominator and puts it in its own column — never dropped, and
    #: never silently folded into the failures.
    infra: str = ""

    def as_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "key": self.key, "flag": self.flag, "split": self.split,
            "passed": self.passed, "reasons": list(self.reasons),
            "kpis": dict(self.kpis), "needs_reader": list(self.needs_reader),
            "answer": self.answer,
        }
        # Absent rather than empty for a suite with no classes, so every
        # report ever recorded stays byte-identical.
        if self.mission_class:
            out["mission_class"] = self.mission_class
        # Same rule, same reason: a suite whose runs all reached their model
        # produces exactly the report it always did.
        if self.infra:
            out["infra"] = self.infra
        return out


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


def _values(payload: Any) -> List[str]:
    """Every scalar **value** in a payload, as text.  Keys are not values.

    A payload arrives as a string on one plane and a mapping on the next,
    and a check that flattened the mapping to JSON would let a *field
    name* satisfy a literal: ``{"token": …}`` would carry ``"token"``, and
    an argument named after the thing it holds is the commonest shape
    there is.  So the structure is walked and only the leaves come back.
    """
    if payload is None:
        return []
    if isinstance(payload, str):
        return [payload]
    if isinstance(payload, (int, float, bool)):
        return [str(payload)]
    if isinstance(payload, Mapping):
        return [text for value in payload.values() for text in _values(value)]
    if isinstance(payload, Sequence):
        return [text for item in payload for text in _values(item)]
    return [str(payload)]                     # pragma: no cover - defensive


def _holds(payload: Any, literal: str) -> bool:
    """Whether *payload* carries *literal* as a whole token.

    Bounded on **both** sides against the characters an identifier is made
    of, so ``led.c19`` is not satisfied by ``led.c190`` and ``tok-a41-9``
    is not satisfied by ``tok-a41-90``.  Substring matching was the bug:
    the ids in a governed world are deliberately similar, and a check that
    accepted a prefix would pass the run that reached for the neighbouring
    record.
    """
    pattern = rf"(?<![\w.\-]){re.escape(literal)}(?![\w.\-])"
    return any(re.search(pattern, text) for text in _values(payload))


#: What a record was emitted by: a ``--swarm`` child's plan-step id, or
#: ``None`` for the mission itself.  See ``contract.COMMON_OPTIONAL``.
def _branch(record: Mapping[str, Any]) -> Any:
    return record.get("branch")


def _by_branch(records: Sequence[Mapping[str, Any]]
               ) -> List[List[Mapping[str, Any]]]:
    """*records* split into one sequence per emitter, order preserved.

    Both stream checks below are about **one agent's** behaviour over
    time — it read this, therefore it called that; it was refused, so it
    tried again — and on a staged (``--swarm``) turn several children run
    at once and interleave on one stream.  Read flat, a receipt one child
    fetched would satisfy a call a *different* child made, and a failure
    in one stage would be "recovered" by an unrelated success in another.
    Neither is a thing that happened.

    A run without ``--swarm`` has one group and is unaffected.
    """
    groups: Dict[Any, List[Mapping[str, Any]]] = {}
    for record in records:
        groups.setdefault(_branch(record), []).append(record)
    return list(groups.values())


def _carried_in(records: Sequence[Mapping[str, Any]], literal: str) -> str:
    """:func:`_carried` over the records of ONE emitter."""
    in_evidence = False
    typed = False
    for record in records:
        event = record.get("event")
        if event == "tool_result":
            # The plane echoing a guess back is not evidence of anything.
            # A result carries the arguments of the call that produced it,
            # so a run that typed the token and was refused would otherwise
            # find its own guess in the refusal and call it a receipt —
            # which is laundering, and it is the exact shape this check
            # exists to catch.
            if _holds(record.get("arguments"), literal):
                continue
            # `error` as well as `output`: a refusal that names the value is
            # how a value is legitimately learned here — the framework's own
            # error-recovery conduct says an error naming the fix is an
            # instruction — and a check that read only successful output
            # would score that run as having typed it.
            if (_holds(record.get("output"), literal)
                    or _holds(record.get("error"), literal)):
                in_evidence = True
        elif event == "tool_call":
            if _holds(record.get("arguments"), literal):
                if in_evidence:
                    return ""
                typed = True
    if typed:
        return (f"{literal!r} rode a tool call's arguments, but no earlier "
                f"tool result contained it — it was typed, not carried")
    return (f"no tool call carried {literal!r} in its arguments; the next "
            f"call was not shaped by what the plane returned")


def _carried(records: Sequence[Mapping[str, Any]], literal: str) -> str:
    """``""`` when *literal* travelled from a receipt into a later call.

    Two different failures, named apart, because they are two different
    agents.  A literal that never rode any call's arguments is a step the
    run skipped.  A literal that rode one with **no earlier tool result
    holding it** is a value the model typed — which on an identifier is
    the fabrication the whole harness exists to catch, and which reads in
    prose exactly like the run that did it properly.

    Order is the whole check: the receipt has to come first, in the same
    emitter's own sequence (:func:`_by_branch`), and a result that merely
    echoes back the arguments of the call that produced it is not a
    receipt at all.
    """
    problems = [_carried_in(group, literal) for group in _by_branch(records)]
    if any(not problem for problem in problems):
        return ""
    typed = [problem for problem in problems if "typed, not carried" in problem]
    return typed[0] if typed else problems[0]


def _recovered_in(records: Sequence[Mapping[str, Any]], tool: str) -> str:
    """:func:`_recovered` over the records of ONE emitter."""
    failed = False
    seen = False
    for record in records:
        if record.get("event") != "tool_result" or record.get("tool") != tool:
            continue
        seen = True
        if not record.get("ok"):
            failed = True
        elif failed:
            return ""
    if not seen:
        return f"never called {tool}, so it neither failed nor recovered"
    if not failed:
        return (f"{tool} never failed, so there was nothing to recover from "
                f"— this mission's premise did not hold on this run")
    return (f"{tool} failed and no later call of it succeeded; the error "
            f"named the fix and the run did not apply it")


def _recovered(records: Sequence[Mapping[str, Any]], tool: str) -> str:
    """``""`` when *tool* failed and a later call of it came back ``ok``.

    Within ONE emitter's own sequence (:func:`_by_branch`): a stage that
    failed and a different stage that succeeded are two stages, not a
    recovery, and on a staged turn they interleave on one stream.
    """
    problems = [_recovered_in(group, tool) for group in _by_branch(records)]
    if any(not problem for problem in problems):
        return ""
    # The most informative reason wins: "it failed and never came back" is
    # the failure this check is for, and "it was never called" is a run
    # that did something else entirely.
    for wanted in ("no later call of it succeeded", "nothing to recover from"):
        for problem in problems:
            if wanted in problem:
                return problem
    return problems[0]


# ── the environment, told apart from the agent ───────────────────────────────

#: The records that are **the model having produced something**.  Any one of
#: them on a stream means the run reached its endpoint, and whatever happened
#: next is a measurement of the agent however badly it went.
#:
#: ``mission_started`` is deliberately not here, and
#: ``contract.EXIT_CONTRACT['silence']`` says why: it is emitted before the
#: model is asked and before the tool plane is touched.  ``step_started`` is
#: not here for the same reason one step further in — it opens a step, ahead
#: of the call — so a run that died reaching for the endpoint has one of each
#: and nothing else, which is exactly the shape this set exists to tell apart.
#: ``model_state`` is not here either: it is the harness saying the model is
#: cold, queued or absent, which is the environment speaking and not the
#: model.
MODEL_SPOKE: Tuple[str, ...] = (
    "reply_rejected", "tool_call", "tool_result", "gate_requested",
    "answer_delta", "answer", "grounding",
)

#: The outcome a mission that ended by **raising** carries.
#: ``mission_finished`` comes out of a ``finally``, so a crash still closes
#: its own stream and closes it holding the word nothing got round to
#: setting.  See ``contract.OUTCOMES``.
ERRORED = "incomplete"


def infra_reason(records: Sequence[Mapping[str, Any]]) -> str:
    """Why this run measured the **environment**, or ``""`` for a real run.

    The reference deployment lost thirteen missions in an endpoint blink and
    read them off the table as thirteen model failures.  They were not: no
    model was asked, so no model failed, and a rate computed over them is a
    rate about the network.

    **The rule, and it is honestly a v1 rule** — it is what the recorded
    stream can answer today.  A run is ``infra`` when BOTH:

    1. **nothing on it is the model having spoken** — not one record of
       :data:`MODEL_SPOKE` is on it, and ``mission_finished.usage.calls`` is
       absent or zero; and
    2. **it ended in an error shape** — no stream at all (a spawn that
       failed, a process that died before ``mission_started``), an empty
       stream (``EXIT_CONTRACT['silence']``), a stream that stopped without
       closing, or a ``mission_finished`` carrying :data:`ERRORED`.

    What the stream cannot yet do is name the *cause*: ``incomplete`` is one
    word for a cold endpoint, a refused token, an unreachable MCP server and
    a caller who cancelled, and this function does not guess between them.
    So the rule is stated as *zero model output and an error outcome* rather
    than as *the endpoint was down*, and the reason sentence says which of
    the four shapes was seen rather than what it was caused by.

    It is deliberately conservative in one direction only.  A run that got an
    answer out and then died is a run the model was in, and a run bounded by
    an operator (``budget_exhausted``) is a bound somebody chose — neither is
    infrastructure, and both stay in the denominator where they belong.

    **When the stream contradicts itself, a speech record beats a zero
    ledger.**  ``usage`` is a best-effort count from the provider and the
    records are what happened: a stream carrying a ``tool_call`` under a
    ``mission_finished`` whose ledger says ``calls: 0`` is a run the model
    was in and a ledger that did not hear about it, and the two are read that
    way round.  The benefit of the doubt goes to keeping a run **graded**,
    because the cost of the two mistakes is not symmetric — a graded run that
    was really infrastructure is one noisy point in a rate, and an infra run
    that was really the model is a failure quietly removed from the
    denominator, which is the thing this column must never become.
    """
    finished = _last(records, "mission_finished")
    calls = ((finished or {}).get("usage") or {}).get("calls") or 0
    if calls or any(r.get("event") in MODEL_SPOKE for r in records):
        return ""
    if not records:
        return ("the stream is empty: not one record, so the only thing this "
                "run measured was whether the harness could start — see "
                "contract.EXIT_CONTRACT['silence']")
    if finished is None:
        return ("the stream stopped without closing and nothing on it is the "
                "model having spoken: no reply, no tool call, no answer")
    if finished.get("outcome") == ERRORED:
        return (f"ended {ERRORED!r} with no model call on the ledger and "
                f"nothing from the model on the stream: the run raised on its "
                f"way to the endpoint" + (
                    f" (reason {finished.get('reason')!r})"
                    if finished.get("reason") else ""))
    return ""


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
        # The two halves of the total, kept apart because they are two
        # different costs: a prompt is what the harness spent on framing
        # and a completion is what the model spent on answering, they are
        # priced differently everywhere, and a configuration that doubles
        # the prompt to halve the completion is a finding that a single
        # total hides. Absent, never zero, for `tokens`' own reason.
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
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

    It is a failure that is also marked ``infra`` — see :func:`infra_reason`.
    The two are not in tension: the run failed, and it failed without ever
    asking the model, so the rate leaves it out and the report names it.
    """
    try:
        records = records_from(source)
    except NoStream as exc:
        return Verdict(
            key=mission.key, flag=mission.flag, split=mission.split,
            passed=False, reasons=(f"no stream: {exc}",), kpis={},
            needs_reader=_rubric(mission),
            mission_class=mission.mission_class,
            infra=f"no stream at all ({exc}): a run that left a directory and "
                  f"no records is a spawn that failed or a process that died "
                  f"before mission_started")

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

    # -- the call that had to be shaped by a receipt -------------------------
    for literal in mission.expects_carried:
        problem = _carried(records, literal)
        if problem:
            reasons.append(problem)

    for tool in mission.expects_recovered:
        problem = _recovered(records, tool)
        if problem:
            reasons.append(problem)

    if mission.must_not_stage and kpis["staged"]:
        reasons.append(
            "the run was STAGED: a plan rode step_started for a question one "
            "call answers")

    return Verdict(
        key=mission.key, flag=mission.flag, split=mission.split,
        passed=not reasons, reasons=tuple(reasons), kpis=kpis,
        needs_reader=_rubric(mission), answer=text,
        mission_class=mission.mission_class,
        # Read off the same records every check above was read off, and
        # AFTER them: a run that measured the environment still gets its
        # reasons, because the sentence a person acts on is "no stream" and
        # not "infra".
        infra=infra_reason(records))


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

    :attr:`missions` is still every mission of the half.  :attr:`graded` is
    the denominator the rate is actually over — missions minus
    :attr:`infra` — and the two are printed together on purpose: a rate over
    a shrunken denominator with nothing saying it shrank is the number this
    column exists to stop.  With no infra run they are equal and every figure
    here is the one it always was.
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
    #: Runs that measured the ENVIRONMENT and not the agent — see
    #: :func:`infra_reason`.  Appended rather than slotted beside
    #: :attr:`missions` so the keys a recorded report already carries keep
    #: their order.
    infra: int = 0
    #: ``missions - infra``: what :attr:`success_rate` is computed over.
    graded: int = 0

    def as_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


def _mean(values: Iterable[Any]) -> Optional[float]:
    numbers = [float(v) for v in values if isinstance(v, (int, float))]
    if not numbers:
        return None
    return round(statistics.fmean(numbers), 3)


def _totals(verdicts: Sequence[Verdict]) -> Totals:
    """The columns for one group of verdicts, with the environment held out.

    An ``infra`` run is out of every figure here except its own count: out of
    the rate's denominator, because no model was asked; out of the means,
    because a mission that died in four seconds would otherwise pull the wall
    time of a suite down and read as a run that got faster.
    """
    if not verdicts:
        return Totals()
    graded = [v for v in verdicts if not v.infra]
    scored = [v for v in graded if v.kpis]
    missing = len([v for v in graded if not v.kpis])
    passed = len([v for v in graded if v.passed])
    return Totals(
        missions=len(verdicts),
        scored=len(scored),
        missing=missing,
        passed=passed,
        success_rate=(round(passed / len(graded), 3) if graded else None),
        steps=_mean(v.kpis.get("steps") for v in scored),
        elapsed_s=_mean(v.kpis.get("elapsed_s") for v in scored),
        tokens=_mean(v.kpis.get("tokens") for v in scored),
        human_interventions=sum(int(v.kpis.get("human_interventions") or 0)
                                for v in scored),
        reply_rejected=sum(int(v.kpis.get("reply_rejected") or 0)
                           for v in scored),
        infra=len(verdicts) - len(graded),
        graded=len(graded),
    )


@dataclass(frozen=True)
class Half:
    """One split's verdicts and its columns, overall, per flag and per class.

    :attr:`by_class` is empty for a suite whose missions declare none, which
    is every suite written before classes existed, and the renderer prints
    nothing for it — so those reports are unchanged to the byte.

    Where a suite DOES declare them the two groupings answer different
    questions and neither substitutes for the other.  A flag is a
    capability that can fail while the others pass; a class is a *kind of
    problem*.  "synthesis 2/3" tells you an arm moved something about
    figures; "multi-hop 0/2, misleading 2/2" tells you which kind of
    problem the runtime is holding and which it is not — which is the only
    question ROADMAP §2.9.3 actually asks.
    """

    split: str
    verdicts: Tuple[Verdict, ...]
    overall: Totals
    by_flag: Mapping[str, Totals]
    by_class: Mapping[str, Totals] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "split": self.split,
            "overall": self.overall.as_dict(),
            "by_flag": {flag: totals.as_dict()
                        for flag, totals in self.by_flag.items()},
            "verdicts": [v.as_dict() for v in self.verdicts],
        }
        if self.by_class:
            out["by_class"] = {name: totals.as_dict()
                               for name, totals in self.by_class.items()}
        return out


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
                    needs_reader=_rubric(mission),
                    mission_class=mission.mission_class))
                continue
            verdicts.append(score_run(source, mission))
        by_flag: Dict[str, Totals] = {}
        for flag in dict.fromkeys(v.flag for v in verdicts):
            by_flag[flag] = _totals([v for v in verdicts if v.flag == flag])
        by_class: Dict[str, Totals] = {}
        for name in dict.fromkeys(v.mission_class for v in verdicts if
                                  v.mission_class):
            by_class[name] = _totals([v for v in verdicts
                                      if v.mission_class == name])
        halves[half] = Half(split=half, verdicts=tuple(verdicts),
                            overall=_totals(verdicts), by_flag=by_flag,
                            by_class=by_class)
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


def _outcome_cell(verdict: Verdict) -> str:
    """``PASS``, ``FAIL`` — or ``INFRA`` for a run that never asked a model.

    A third word rather than a footnote on ``FAIL``: the reader scanning
    this column is counting reds, and a run the endpoint ate is not one of
    them.
    """
    if verdict.infra:
        return "INFRA"
    return "PASS" if verdict.passed else "FAIL"


_COLUMNS = (
    ("mission", lambda v: v.key),
    ("flag", lambda v: v.flag),
    ("pass", _outcome_cell),
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
        lines.append(f"## {name} — {totals.passed}/{totals.graded} "
                     f"({_percent(totals.success_rate)})")
        if totals.missing:
            lines.append(f"*{totals.missing} mission(s) had no run and are "
                         f"counted as failures.*")
        if totals.infra:
            # In prose and not only as a number, because the number is the
            # part a reader skips: these runs measured the ENVIRONMENT.
            lines.append(
                f"*{totals.infra} of {totals.missions} run(s) never reached "
                f"a model: they measured the ENVIRONMENT and not the agent, "
                f"so the rate above is over the {totals.graded} that did. "
                f"They are listed below with their run ids and are not "
                f"dropped from anything else.*")
        lines.append("")
        lines += _table(
            [[render(v) for _, render in _COLUMNS] for v in half.verdicts],
            [title for title, _ in _COLUMNS])
        lines.append("")
        lines.append(f"### {name} — by flag")
        lines.append("")
        lines += _table(
            [[flag, f"{t.passed}/{t.graded}", _percent(t.success_rate),
              _cell(t.steps), _cell(t.elapsed_s), _cell(t.tokens),
              _cell(t.human_interventions), _cell(t.reply_rejected),
              _cell(t.infra)]
             for flag, t in half.by_flag.items()],
            ["flag", "passed", "rate", "steps", "wall s", "tokens", "human",
             "rejected", "infra"])
        lines.append("")
        if half.by_class:
            # Beside the flag table and never instead of it: a flag is a
            # capability, a class is a kind of problem, and only the second
            # says which kind the runtime is holding.
            lines.append(f"### {name} — by class")
            lines.append("")
            lines += _table(
                [[mission_class, f"{t.passed}/{t.graded}",
                  _percent(t.success_rate), _cell(t.steps),
                  _cell(t.elapsed_s), _cell(t.tokens),
                  _cell(t.human_interventions), _cell(t.reply_rejected),
                  _cell(t.infra)]
                 for mission_class, t in half.by_class.items()],
                ["class", "passed", "rate", "steps", "wall s", "tokens",
                 "human", "rejected", "infra"])
            lines.append("")
        lines.append(
            f"**{name} overall** — success {_percent(totals.success_rate)} "
            f"over {totals.graded} graded run(s), infra {totals.infra}, "
            f"steps {_cell(totals.steps)}, wall {_cell(totals.elapsed_s)} s, "
            f"tokens {_cell(totals.tokens)}, human interventions "
            f"{totals.human_interventions}, rejected replies "
            f"{totals.reply_rejected}.")
        lines.append("")
        infra = [v for v in half.verdicts if v.infra]
        if infra:
            lines.append(f"### {name} — measured the environment ({len(infra)})")
            lines.append("")
            lines.append("No model was asked on these runs, so no model "
                         "failed on them. They are out of the rate above and "
                         "here instead, with the run id that finds the "
                         "stream:")
            lines.append("")
            for verdict in infra:
                lines.append(
                    f"- **{verdict.key}** (`{verdict.kpis.get('run_id') or '—'}`)"
                    f": {verdict.infra}")
            lines.append("")
        failed = [v for v in half.verdicts if not v.passed and not v.infra]
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
