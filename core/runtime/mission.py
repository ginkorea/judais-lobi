# core/runtime/mission.py — the loop where the model chooses the tool

"""A plan/act loop seeded with ``tools/list``.

Everywhere else in this package the *operator* chooses the tool: you
type ``--shell`` and a shell tool runs, ``--search`` and a search tool
runs.  That works because the tool set is fixed and the person typing
knows it.

It cannot work for an agent talking to a server it discovers at runtime.
Nobody can add a flag for a tool that did not exist when the CLI was
written.  So the mission flow inverts it: the catalogue is put in front
of the model, and the model names the tool.

The loop is deliberately small and its refusals are deliberately loud:

* every call goes through ``ToolBus.dispatch``, so capability gating,
  the panic switch and the audit log all still apply.  The runner never
  touches a store, a path or a compute plane itself, and holds no HTTP
  client of its own;
* the model replies with **one** JSON object and nothing else.  A reply
  that does not parse is handed back to the model as a parse error
  rather than guessed at;
* a tool the model invented is a refused step with the real catalogue
  repeated, not a crash;
* the budgets are hard stops.  Steps, and — when a caller supplies a
  :class:`~core.budgets.Deadline` — wall-clock seconds.  Running out of
  either is a recorded outcome (``budget_exhausted``) that **names which
  one**, and not a silent truncation;
* a caller may ask a running mission to wind up, with a
  :class:`~core.budgets.Cancellation` checked at the same points the
  deadline is.  A cancelled run ends ``incomplete`` with ``reason``, and
  it ends by *finishing*: the transcript is intact and the stream gets
  its own ``mission_finished`` rather than stopping mid-record;
* a tool result is **bounded** before it enters the transcript, and the
  whole of it stays in a per-mission store the model can read one field
  of.  See :mod:`core.runtime.results` for why an unbounded paste is a
  correctness problem and not a tidiness one;
* the **conversation** is bounded too, when the caller supplies a
  window: bounding each result says nothing about the sum of them, and
  the sum is what meets ``max_model_len``.  Oldest round trips go first,
  the persona, catalogue, seeded turns, objective and newest result stay,
  and the drop is a record on the stream rather than a shorter prompt
  nobody mentioned.  See :class:`~core.runtime.context_window.MissionWindow`;
* an answer is **checked against the run's own tool output** when the
  skill supplied a grammar for it.  See :mod:`core.runtime.grounding`.

Two of those are configured by content the harness does not own: the
tool subset and the prompt come from a skill manifest
(:mod:`core.runtime.skills`), and so does the identifier grammar.  The
loop supplies the mechanism and nothing else.
"""

from __future__ import annotations

import inspect
import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from core.bounding import MAX_RESULT_BYTES, bound_result
from core.durable import RunStore
from core.budgets import BudgetExhausted, Deadline, cancelled
from core.redact import scrub_record
from core.runtime.approvals import ApprovalStore, ApprovalTicket
from core.runtime.context_window import (
    Compaction, MissionWindow, default_compaction_note,
)
from core.runtime.contract import SCHEMA_VERSION
from core.runtime.grounding import GroundingReport, GroundingValidator
from core.runtime.mission_stream import (
    ANSWER, GATE_REQUESTED, GROUNDING, MISSION_FINISHED, MISSION_STARTED,
    REPLY_REJECTED, STEP_STARTED, TOOL_CALL, TOOL_RESULT, Observer,
)
from core.runtime.results import RESULT_TOOL, MissionResultStore
from core.runtime.usage import Ledger, Rate
from core.tools.descriptors import same_tool, summarize_input_schema


def _profile_field(bus: Any) -> Dict[str, Any]:
    """``{"profile": name}`` when the bus knows its capability profile, else
    ``{}``.

    The ``profile`` on ``mission_started`` is the OPTIONAL field that lets a
    watcher see, in the opening frame, which capability profile a run is
    governed by — a deny-by-default ``safe`` mission and a ``god`` one look
    identical on the wire otherwise. Absent (not ``null``) when the bus was
    built from a raw capability engine that never recorded a profile name, so
    "profile" is a fact the stream states only when there is one to state.
    One owner: the swarm's opening frame reads it from here too.
    """
    engine = getattr(bus, "capability_engine", None)
    name = getattr(engine, "current_profile", None) if engine is not None else None
    return {"profile": name} if name else {}


def _run_field(run_id: str) -> Dict[str, Any]:
    """``{"run_id": id}`` when this run is being recorded, else ``{}``.

    The OPTIONAL field on ``mission_started`` that tells a consumer where
    the durable transcript of this mission is: :class:`core.durable.RunStore`
    keys a directory by it, and a consumer that wants to replay or resume a
    run must not have to guess a directory name from a timestamp.  Absent
    (not ``null``) when nothing is being recorded — ``JUDAIS_LOBI_RUNS=off``,
    or a library caller that passed no store — so "there is a record of this
    run" is a fact the stream states only when it is true.  One owner: the
    swarm's opening frame reads it from here too.
    """
    return {"run_id": run_id} if run_id else {}


def persist_record(store: Optional[RunStore], run_id: str,
                   record: Dict[str, Any]) -> None:
    """Append one emitted record to the run's durable log.  Never raises.

    The same promise ``_emit`` makes about an observer, for the same
    reason and one layer down: a mission must not fail because the disk
    it was being written to filled up, and an 11,000-second submission
    lost to a full ``/var`` is a worse outcome than a transcript with a
    hole in it.  A caller that needs to know whether the record landed
    reads the store.

    One function rather than a copy in each runner's ``_emit``: the
    staged path hand-listing six of ten grounding fields is what a second
    copy of an emitter's decision looks like a month later.
    """
    if store is None or not run_id:
        return
    try:
        store.append(run_id, record)
    except Exception:                           # pragma: no cover - defensive
        pass


#: The whole protocol between the loop and the model.  Kept in one string
#: because a contract split across three f-strings is a contract that
#: drifts from the parser below it.
PROTOCOL = """\
You are working a mission with tools. Reply with exactly one JSON object \
and no other text, no code fence, no commentary.

To use a tool:
  {"tool": "<tool name from the catalogue>", "arguments": {...}}

To finish:
  {"answer": "<your final answer>"}

Use only tool names from the catalogue below, spelled exactly. Call one \
tool per reply. Base every statement on a tool result you actually \
received; if the tools cannot support a statement, say so in the answer \
instead of asserting it.
"""

_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.MULTILINE)

#: Bounds on a seeded conversation history, chosen as a safety net and not
#: a working limit.  The one caller that seeds history today (TAIPAN's
#: Mission Pane) already caps what it sends at 12 turns of ≤4,000
#: characters — ~48 KB worst case — so anything near these numbers is a
#: caller that lost its own cap, and the honest response is a refusal at
#: the door rather than a silent trim.  An oversized history has the same
#: defect as an unbounded tool result (see :mod:`core.bounding`): it can push
#: the catalogue and the protocol out of a small model's window with
#: nothing in the answer saying so.
HISTORY_MAX_TURNS = 100
HISTORY_MAX_CHARS = 262_144


def validate_history(turns: Any) -> List[Dict[str, str]]:
    """*turns* as a clean ``[{"role", "content"}, …]``, or ``ValueError``.

    The one answer to "is this a conversation history this loop will
    seed".  Both callers use it — :class:`MissionRunner` on whatever it
    is constructed with, and the CLI on what ``--history`` read from disk
    — so a history the CLI accepted is a history the runner accepts, and
    the refusal text is identical wherever the bad shape arrives.

    Refusals are loud on purpose.  A malformed history silently dropped
    would reproduce the exact failure this feature exists to fix: an
    agent that looks like it has the conversation and answers as if it
    does not.
    """
    # A tuple is allowed because it is what a Python caller's default
    # argument looks like; anything else — a dict, a string — is a caller
    # holding the wrong shape, and coercing it would validate its pieces
    # rather than the mistake.
    if not isinstance(turns, (list, tuple)):
        raise ValueError(
            f"history must be a JSON array of "
            f'{{"role": "user"|"assistant", "content": "..."}} objects, '
            f"got {type(turns).__name__}"
        )
    if len(turns) > HISTORY_MAX_TURNS:
        raise ValueError(
            f"history has {len(turns)} turns; the cap is "
            f"{HISTORY_MAX_TURNS}. Trim it at the caller — a silent trim "
            f"here would hide which turns the model never saw."
        )
    cleaned: List[Dict[str, str]] = []
    total = 0
    for index, turn in enumerate(turns):
        if not isinstance(turn, dict):
            raise ValueError(
                f"history[{index}] must be an object with 'role' and "
                f"'content', got {type(turn).__name__}"
            )
        role = turn.get("role")
        content = turn.get("content")
        if role not in ("user", "assistant"):
            raise ValueError(
                f"history[{index}].role must be 'user' or 'assistant', "
                f"got {role!r}. System text belongs to the harness, and "
                f"tool turns are this mission's own to make."
            )
        if not isinstance(content, str):
            raise ValueError(
                f"history[{index}].content must be a string, got "
                f"{type(content).__name__}"
            )
        total += len(content)
        cleaned.append({"role": role, "content": content})
    if total > HISTORY_MAX_CHARS:
        raise ValueError(
            f"history totals {total} characters; the cap is "
            f"{HISTORY_MAX_CHARS}. Trim it at the caller."
        )
    return cleaned


def sandbox_of(bus: Any) -> str:
    """The word the bus's sandbox answers to — ``"bwrap"`` or ``"none"``.

    Read off the bus (``ToolBus.sandbox_name`` derives it from the installed
    runner, so it cannot drift from what actually isolates a subprocess), and
    through ``getattr`` for the same reason :func:`audit_ref_of` is: a fake
    bus in somebody's test suite owes the runner ``dispatch`` and
    ``describe_tool`` and nothing else.  A bus that has no such word is
    reported as ``"none"`` — the honest reading of a bus that has no sandbox
    to name.  One owner: the swarm's opening frame reads it from here too.
    """
    return str(getattr(bus, "sandbox_name", None) or "none")


def audit_ref_of(bus: Any) -> Optional[str]:
    """The audit file *bus* is recording this run's dispatches in, or ``None``.

    One function rather than a line in each runner, and it reads the value
    off the **bus** rather than resolving a path of its own.  Both matter.
    A second resolver would be a second owner of "where the audit log is",
    and the day the two disagree the stream names a file nothing wrote to —
    which is worse than no ``audit_ref`` at all, because a consumer would
    believe it.  A second copy of even this one expression is the same
    hazard in miniature: the swarm hand-listed six grounding fields where
    the direct path emitted ten, and that is exactly how.

    ``getattr`` and not an attribute access: a caller may hand either
    runner any object with ``dispatch`` and ``describe_tool`` on it, and a
    fake bus in somebody's test suite is not obliged to know what an audit
    is.  Nothing here is a reason for a mission to fail to start.
    """
    ref = getattr(bus, "audit_ref", None)
    return str(ref) if ref else None


def _takes_deadline(bus: Any) -> bool:
    """Whether *bus*'s ``dispatch`` accepts a ``deadline_s`` ceiling.

    Asked of the signature rather than assumed, and rather than answered by
    a flag somebody has to set.  ``ToolBus.dispatch`` forwards every keyword
    it does not name straight to the tool's executor — which for an MCP tool
    means straight to a remote server as a **tool argument**.  So a mission
    that simply passed ``timeout=`` down would be inventing an argument for
    somebody else's schema, and on a server that happened to declare a
    ``timeout`` of its own (in milliseconds, say, for a query) it would be
    inventing a *wrong* one.  The named parameter is the bus's own, it is
    consumed there, and a bus that does not have it is a bus this loop does
    not hand seconds to.

    ``getattr`` and a swallowed failure for the same reason
    :func:`audit_ref_of` uses one: a caller may hand this runner any object
    with ``dispatch`` and ``describe_tool``, and a fake bus whose signature
    cannot be read is not a reason for a mission to fail to start.
    """
    dispatch = getattr(bus, "dispatch", None)
    if dispatch is None:
        return False
    try:
        return "deadline_s" in inspect.signature(dispatch).parameters
    except (TypeError, ValueError):             # pragma: no cover - defensive
        return False


def _grounding_record(report: "GroundingReport", *, repairs: int = 0,
                      repairing: bool = False, caveat: str = "") -> Dict[str, Any]:
    """A :class:`GroundingReport` as the observer's ``grounding`` fields.

    Read off the report with ``getattr`` defaults rather than by unpacking a
    known shape: this module's job is to say what the validator said, and a
    check the validator grows next month should reach a watcher as a row in
    ``checks`` rather than as an ``AttributeError`` inside a mission.
    """
    return {
        "ran": bool(getattr(report, "ran", False)),
        "grounded": bool(getattr(report, "grounded", False)),
        # Grounded AND something was actually checked. Carried beside
        # `grounded` rather than instead of it because they are different
        # facts and a watcher that cannot tell them apart is the watcher six
        # missions looked clean to on 10 August.
        "verified": bool(getattr(report, "verified", False)),
        "repairs": repairs,
        "repairing": repairing,
        "caveat": caveat or (getattr(report, "caveat", "") or ""),
        # The tokens themselves, not a count of them. "3 figures were not in
        # any tool output" sends a reader looking; "0.181 was not" tells them
        # where, and 0.181 is the exact figure this check was written after.
        "unsupported": list(getattr(report, "unsupported", ()) or ()),
        # Which checks found nothing in the answer at all, and which of those
        # the skill had required to find something.
        "silent": list(getattr(report, "silent", ()) or ()),
        "uncited": list(getattr(report, "uncited", ()) or ()),
        "checks": [
            {"check": getattr(row, "check", ""),
             "configured": bool(getattr(row, "configured", False)),
             "grounded": bool(getattr(row, "grounded", False)),
             "verdict": getattr(row, "verdict", ""),
             "considered": len(getattr(row, "considered", ()) or ()),
             "minimum": int(getattr(row, "minimum", 0) or 0),
             "unsupported": list(getattr(row, "unsupported", ()) or ()),
             "detail": getattr(row, "detail", "")}
            for row in (getattr(report, "results", ()) or ())
        ],
    }


#: The word ``mission_finished.reason`` carries when a run was asked to stop.
#:
#: Cancellation is deliberately **not** a new ``outcome``.  A cancelled run
#: stopped without an answer, which is exactly what ``incomplete`` has always
#: meant; what ``incomplete`` was missing is *why*, and a consumer reading it
#: was told to go and look at stderr.  So the fact arrives as an OPTIONAL field
#: beside the outcome a consumer already has a sentence for, rather than as a
#: sixth word every consumer's closed set has to grow to know.
CANCELLED = "cancelled"


def _finished_record(*, outcome: str, steps: int, max_steps: int,
                     budget: Optional[BudgetExhausted] = None,
                     reason: str = "",
                     usage: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The ``mission_finished`` fields, for **both** paths that emit them.

    One function because there are two emitters — the direct loop's
    ``finally`` and the staged path's — and a hand-listed second copy of a
    record is not a hypothetical failure here: the swarm shipped six of
    ``grounding``'s ten fields that way.  A consumer switching on ``event``
    gets one shape per event or it does not have a vocabulary.

    ``max_steps`` travels beside ``steps`` because the two are only
    meaningful against each other.  ``budget`` is present **exactly when**
    the outcome is ``budget_exhausted``, which is the promise
    :data:`core.runtime.contract.OPTIONAL` makes: a consumer may branch on
    the outcome and index the field, and a consumer that sees the field
    knows the run ran out rather than inferring it from a step count that
    happens to equal its cap.  ``reason`` is present only when there is one
    — today, only for a cancelled run.
    """
    record: Dict[str, Any] = {
        "outcome": outcome, "steps": steps, "max_steps": max_steps,
    }
    if outcome == "budget_exhausted" and budget is not None:
        record["budget"] = budget.as_record()
    if reason:
        record["reason"] = reason
    # `usage` is the run's totals and is ABSENT when no provider reported
    # anything — not three zeros; see the ledger.
    if usage is not None:
        record["usage"] = usage
    return record


@dataclass
class MissionStep:
    """One turn: what the model said, and what came back."""

    index: int
    raw_reply: str
    tool: Optional[str] = None
    arguments: Dict[str, Any] = field(default_factory=dict)
    exit_code: Optional[int] = None
    output: str = ""
    error: str = ""
    #: Handle of the full result in the mission's store, when there is one.
    handle: str = ""
    #: Whether what the model was shown was cut down from :attr:`output`.
    truncated: bool = False

    @property
    def refused(self) -> bool:
        return self.exit_code is not None and self.exit_code != 0


#: Terminal outcome for a mission that named a tool this deployment offers and
#: **gates**. The call was not made.  It is not "refused" and it is not
#: "answered": the mission stopped because it reached something a person has to
#: say yes to, and the harness has no way to be that person.
#:
#: Written as its own outcome rather than folded into ``incomplete`` because a
#: caller resuming a gated mission has to be able to tell "nobody has decided
#: yet" from "the model gave up", and those are the same string otherwise.
AWAITING_APPROVAL = "awaiting_approval"


@dataclass
class MissionTranscript:
    """The whole run, in the order it happened."""

    objective: str
    catalogue: List[str] = field(default_factory=list)
    steps: List[MissionStep] = field(default_factory=list)
    answer: Optional[str] = None
    outcome: str = "incomplete"
    #: What the grounding validator said, when one was configured.
    grounding: Optional[GroundingReport] = None
    #: The gated call this mission stopped at, as ``{tool, arguments}``, when
    #: :attr:`outcome` is :data:`AWAITING_APPROVAL`.
    awaiting: Optional[Dict[str, Any]] = None
    #: What the providers said this run cost, accumulated across every
    #: model call.  Empty — ``calls == 0`` — when nothing reported, which
    #: is a different fact from a run that cost zero tokens and is kept
    #: different all the way to the wire.
    usage: Ledger = field(default_factory=Ledger)
    #: **Which** budget ran out, when :attr:`outcome` is
    #: ``"budget_exhausted"``.  ``None`` otherwise, and never ``None`` when
    #: the outcome is that word: a run that says it ran out of budget and
    #: cannot say of what leaves a consumer guessing between a step cap and
    #: a wall clock, which are different problems with different fixes.
    budget: Optional[BudgetExhausted] = None
    #: Why the run ended, when the outcome word does not say.  Today that is
    #: :data:`CANCELLED` and nothing else; ``""`` means the word was enough.
    reason: str = ""

    @property
    def completed(self) -> bool:
        """Whether the mission produced an answer.

        ``answered_with_caveat`` counts: the answer exists and was
        returned. What it could not support is on the answer itself, in
        words, which is the point of appending a caveat rather than
        discarding the run.
        """
        return self.outcome in ("answered", "answered_with_caveat")


class MissionRunner:
    """Seed the plan with a tool catalogue, then let the model drive.

    Parameters
    ----------
    chat_fn:
        ``messages -> str``.  Injected rather than an ``Agent`` so the
        loop is testable without a backend and so it cannot reach past
        the client it was given.
    bus:
        A :class:`~core.tools.bus.ToolBus`.  The only way out of here.
    tool_names:
        Which registered tools this mission may use.  A subset, not the
        whole bus: a mission agent is given the mission's tools, and
        handing it ``run_shell_command`` because it happened to be
        registered is how a governed run stops being governed.  A skill
        manifest supplies this set; see
        :meth:`core.runtime.skills.SkillManifest.resolve`.
    system_message:
        Persona and skill prompt, already joined by the caller.
    validator:
        A :class:`~core.runtime.grounding.GroundingValidator`, or
        ``None`` for a mission nobody configured a grammar for.  ``None``
        runs exactly as this loop ran before one existed, and the
        transcript's ``grounding`` stays ``None`` rather than claiming a
        clean check.
    store_tool:
        Name to register the per-mission result store under, or ``""``
        to run without one.  Without it, a bounded result is a result
        with a hole in it and nothing to fill the hole from.

    gated:
        Tool names that are **offered and not dispatched**.  The model
        sees them in the catalogue, marked; naming one ends the mission
        at :data:`AWAITING_APPROVAL` with the proposed arguments intact
        and nothing called.

        Offered rather than withheld, on purpose.  A tool simply left
        out of the set produces "there is no tool named X", which is
        false — it exists, this deployment serves it, and the true
        sentence is *somebody has to say yes first*.  A model told the
        false version reroutes around it and reports the capability as
        absent; a model told the true one asks.  And a gate is only
        worth having if what a person approves is the bytes that would
        run, which means the call has to be *proposed* before it is
        stopped.

        The harness supplies the mechanism and never the decision.  There
        is deliberately no parameter here by which a caller could
        pre-answer one — ``approval`` below is not that parameter: it
        takes a *ticket*, which only
        :func:`~core.runtime.approvals.resolve` can build and only out of
        a record somebody already decided, on disk, from outside this
        process.  A boolean would have been that parameter, which is why
        there is not one.
    approvals:
        A :class:`~core.runtime.approvals.ApprovalStore`, or ``None`` for
        the behaviour this loop had before one existed.  With a store, a
        mission that stops at a gate **writes the request down** before it
        returns: a file with the tool, the arguments verbatim, the
        objective and this run's id, addressed by an id that also rides
        ``gate_requested.approval_id``.  Without one, the gate still
        stops the mission and the request lives only in whatever the
        caller kept — which was the whole defect: an approval that dies
        with a socket gets re-asked, or worse, defaulted.

        Injected rather than reached for, so a library caller and a test
        each get exactly the store they passed and no directory appears
        under anybody's working copy uninvited.
    approval:
        An :class:`~core.runtime.approvals.ApprovalTicket` — a decision
        somebody already made, resolved at the door by
        :func:`~core.runtime.approvals.resolve` — or ``None``.

        A ticket does **one** thing: its tool leaves :attr:`gated` for
        this run.  Not for the deployment, not for the caller, not until
        somebody revokes it: for this run, and the spending happens at the
        moment the tool is actually dispatched, so a run that never
        reaches it has not used anybody's yes.  A ticket cannot be
        constructed from a record that is not approved, which is why this
        parameter is an object and not an id — there is no code path in
        this module that reads a state and decides what it means.
    run_id:
        See ``run_store, run_id`` below — one id serves both the durable
        transcript and the approval request that names the run that asked,
        so a restart can tell a request whose run is gone from one whose run
        is still working.  ``""`` records nothing, and
        :meth:`~core.runtime.approvals.ApprovalStore.reconcile` leaves such
        a record alone rather than abandoning it.
    history:
        Prior conversation turns, oldest first, as
        ``[{"role": "user"|"assistant", "content": …}, …]`` — the
        analyst's questions and the agent's final answers, never the
        tool-call plumbing of earlier missions.  Seeded into the message
        list **as messages**, between the system prompt and the current
        objective.

        As messages and not as text folded into the objective, because
        that difference was measured: a chat-tuned model attends to
        role-tagged turns in its own chat template and skates over the
        same turns pasted into one user string.  On 12 August 2026 a
        served gpt-oss-20b, given the prior turns as an "Earlier in this
        conversation:" preamble inside the objective, answered "tell me
        more about headline #2" by web-searching the literal string
        "headline #2" — the headlines were in the prompt and the model
        never looked.  The default ``()`` is a mission that starts cold,
        exactly as every mission started before this parameter existed.
    usage_fn:
        ``() -> Usage | None``, read after every ``chat_fn`` call: what
        the provider said *that* call cost.  ``None`` — the default — is
        a loop that accumulates nothing and emits no ``usage`` field
        anywhere, which is exactly how this loop behaved before there
        was a ledger.

        A nullary callable rather than a client, and rather than a
        second return value from ``chat_fn``.  ``chat_fn`` returns the
        reply and half a dozen callers depend on that; handing the
        runner the whole client instead would give a loop that is
        deliberately confined to one injected function a model client it
        could ask anything.  The CLI passes
        ``lambda: elf.client.last_usage`` and the seam stays one
        function wide.
    rate:
        A :class:`~core.runtime.usage.Rate` for the provider and model
        that will run, or ``None``.  Only used to put ``cost`` beside the
        totals on ``mission_finished``; resolved by the caller, because
        the loop does not know which provider it is talking to and must
        not learn.
    ledger:
        An existing :class:`~core.runtime.usage.Ledger` to accumulate
        into, instead of one per run.  This is how a staged ``--swarm``
        turn keeps ONE ledger: the swarm's own router and planner calls
        and every sub-mission's steps fold into the same object, so the
        total is the turn's rather than the last sub-mission's.  A
        caller passing one owns it, including when it is reset.
    observer:
        ``dict -> None``, called with one record per thing that happens.
        See :mod:`core.runtime.mission_stream` for the vocabulary; it is
        a published contract rather than these dataclasses' field names.
        ``None`` runs exactly as this loop ran before one existed.

        A mission on a local model is minutes long, and a caller holding
        only :meth:`run` has nothing to show for any of them.
    window:
        A :class:`~core.runtime.context_window.MissionWindow`, or ``None``
        for a loop that sends whatever it has accumulated.

        ``None`` is what this loop did until now, and what it did was
        grow one message list across every step of the budget and hand
        the whole of it to the backend each time.  Each result is
        bounded (``MAX_RESULT_BYTES``) and each is at most one step's
        worth, so nothing here is individually large; the sum is.  Eight
        steps of bounded results is a quarter of a megabyte of prompt,
        and against a served model with a real ``max_model_len`` the end
        of that is a 400 from the server or a silent eviction inside it
        — the second being the dangerous one, because the model then
        answers from a conversation it can no longer fully see and
        nothing in the answer says which half went.

        With a window, the compactable middle is dropped oldest-first
        before each step, the persona/catalogue/history/objective prefix
        and the newest round trip survive, and the drop is announced on
        the stream as ``step_started.compacted``.  Nothing is lost to the
        *run*: the whole of every result stays in :attr:`store`, which is
        what the grounding validator reads and what the model can still
        address by handle.
    run_store, run_id:
        A :class:`core.durable.RunStore` and the id of the run inside it
        to append every emitted record to, before that record reaches
        *observer*.  ``None`` (or an empty id) keeps no transcript, which
        is what a library caller and every test that does not ask for one
        get.

        Named ``run_store`` and not ``store`` because :attr:`store` on
        this class is already taken by the mission's *result* store, and
        two different things called the same word one line apart is how a
        caller passes the wrong one.

        The pair is the durable half of the streaming contract: the
        observer is a subscriber that may go away — a browser closing, a
        pipe breaking — and the run directory is what is still there
        afterwards.  ``mission_finished`` in the log is the record of a
        run that closed; a log without one is an orphan, and that is a
        fact about the disk rather than about whoever was watching.

    deadline:
        A :class:`~core.budgets.Deadline`, or ``None`` for a mission
        nobody put a wall clock on — which is the default, and which is
        how every mission ran before this parameter existed.

        Unbounded by default on purpose.  ``max_steps`` bounds the work;
        seconds bound the *waiting*, and the two are not the same bound
        — a 20B at 59 tok/s can spend eight honest steps over several
        minutes, and a framework that killed it at some number nobody
        chose would be a regression for every operator running a slow
        local model.  The reference deployment bounds a turn at its own
        layer today.  A deadline is a thing an operator asks for.

        Checked **between steps and before each model call**, which in
        this loop is the same point, and again before a tool is
        dispatched.  A model call already in flight is not interrupted:
        the bound this gives is "the deadline plus at most one round
        trip", and the honest way to tighten it is a timeout on the
        client, not a thread that abandons a request the server is still
        serving.  A tool call is bounded further where the bus takes a
        ceiling — see :meth:`_deadline_ceiling`.

        Started, not constructed: :meth:`run` calls
        :meth:`~core.budgets.Deadline.start`, and the first start wins.
        That is what lets a staged mission hand one clock to triage, the
        planner and every sub-mission without five sub-missions of a
        minute each fitting inside a one-minute budget.
    cancel:
        A :class:`~core.budgets.Cancellation` — or any object with
        ``is_set()``, so a bare :class:`threading.Event` works — that a
        caller may throw to ask a running mission to wind up.  ``None``
        is a mission nobody can stop, which is what this loop was.

        Cooperative, and that is the point.  A run that is killed
        between records leaves a consumer holding a stream that opened
        and never closed, which is the spinner-forever state
        ``mission_finished`` exists to prevent.  A run that is *asked*
        stops at its next check, keeps its transcript, and emits its own
        ``mission_finished`` saying ``incomplete`` with ``reason:
        "cancelled"``.

    The store tool is offered **in addition to** ``tool_names``, and
    that is not a hole in a closed set: it reaches nothing outside the
    mission.  Every byte it can return already arrived through a gated,
    audited ``dispatch`` of a tool the set allowed, and was shown to
    this same model a moment earlier in truncated form.
    """

    def __init__(
        self,
        chat_fn: Callable[[List[Dict[str, str]]], Any],
        bus: Any,
        tool_names: Sequence[str],
        *,
        system_message: str = "",
        max_steps: int = 8,
        validator: Optional[GroundingValidator] = None,
        max_result_bytes: int = MAX_RESULT_BYTES,
        store_tool: str = RESULT_TOOL,
        gated: Sequence[str] = (),
        approvals: Optional[ApprovalStore] = None,
        approval: Optional[ApprovalTicket] = None,
        history: Sequence[Dict[str, str]] = (),
        observer: Optional[Observer] = None,
        window: Optional[MissionWindow] = None,
        run_store: Optional[RunStore] = None,
        run_id: str = "",
        usage_fn: Optional[Callable[[], Any]] = None,
        rate: Optional[Rate] = None,
        ledger: Optional[Ledger] = None,
        deadline: Optional[Deadline] = None,
        cancel: Any = None,
    ):
        self._chat = chat_fn
        self._bus = bus
        self._tool_names = list(tool_names)
        self._system_message = system_message
        self._max_steps = max_steps
        self._validator = validator
        self._max_result_bytes = max(0, int(max_result_bytes))
        self._store_tool = (store_tool or "").strip()
        self._store = MissionResultStore()
        self._gated = frozenset(str(name) for name in gated if name)
        self._approvals = approvals
        self._approval = approval
        if approval is not None:
            # The whole of what a decision does. One tool, out of the set
            # this run gates, through the ticket's own subtraction so that
            # the direct path, the staged path and the opening frame cannot
            # disagree about which tools are gated. Everything else about
            # the run is unchanged, and nothing anywhere records that this
            # tool is now generally allowed.
            self._gated = frozenset(approval.widen(self._gated))
        # Validated here as well as at the CLI, because the CLI is one
        # caller of several and a runner seeded with a system turn or a
        # non-string content would fail somewhere much less legible than
        # this line.
        self._history = validate_history(history)
        self._observer = observer
        self._window = window
        # The durable half of the observer. `None` — or a store with no run
        # id — is a loop that keeps no transcript, which is what a library
        # caller and every test that does not ask for one get.
        self._run_store = run_store
        self._run_id = str(run_id or "")
        self._usage_fn = usage_fn
        self._rate = rate
        # Kept as "the caller's, or none": `run` makes a fresh one per run
        # when it is none, and leaves a shared one alone. A run that reset
        # a ledger it did not own would silently discard the swarm's
        # router and planner calls on the first sub-mission.
        self._shared_ledger = ledger

        self._deadline = deadline
        self._cancel = cancel
        # Asked once, of this bus, at construction — not per dispatch, and
        # not by declaring a flag a caller has to remember to set. See
        # `_deadline_ceiling` for why a mission may not simply pass one.
        self._bus_takes_deadline = _takes_deadline(bus)

    @property
    def run_id(self) -> str:
        """The run this loop's records are being recorded under, or ``""``.

        Readable because the id is the only handle a caller has on the
        transcript afterwards, and the store — not the runner and not the
        CLI — is the one that hands it out.
        """
        return self._run_id

    @property
    def store(self) -> MissionResultStore:
        """The mission's result store.  One per runner, cleared per run."""
        return self._store

    @property
    def offered(self) -> List[str]:
        """Every tool name the model may name: the set, plus the store."""
        if self._store_tool:
            return [*self._tool_names, self._store_tool]
        return list(self._tool_names)

    @property
    def gated(self) -> List[str]:
        """Offered tools that need a person, in catalogue order."""
        return [name for name in self.offered if name in self._gated]

    # ── telling a watcher ───────────────────────────────────────────────

    def _emit(self, event: str, **fields: Any) -> None:
        """One record to the observer, or nothing.  Never raises.

        A mission must not fail because somebody was watching it, so an
        observer that throws is dropped rather than propagated — the
        alternative is a browser tab closing and taking an 11,000 s
        submission with it.

        **And it is the choke point for redaction.**  Every record leaves
        through here, so :func:`core.redact.scrub_record` is applied here and
        no emitter below can forget it: an exception rendered into ``error``
        or ``problem`` stops naming this host's home directory, this host, or
        a credential in this process's environment before a watcher ever sees
        it.  ``output`` and ``arguments`` are deliberately untouched — see
        :data:`core.redact.WHY_VERBATIM`, and in particular that the grounding
        validator checks an answer against the store's copy of a result, which
        a rewritten stream copy would no longer match.
        """
        if self._observer is None and self._run_store is None:
            return
        record = scrub_record({"event": event, **fields})
        # The store first, then the watcher: the sink is a CLIENT of the
        # durable log and not a second truth beside it, so a record a
        # consumer saw is a record the transcript has. The scrubbed copy
        # goes to both — a credential that must not reach a pane must not
        # reach a file on disk either.
        persist_record(self._run_store, self._run_id, record)
        if self._observer is None:
            return
        try:
            self._observer(record)
        except Exception:                       # pragma: no cover - defensive
            pass

    # ── what the last call cost ─────────────────────────────────────────

    def _spent(self, transcript: MissionTranscript) -> Dict[str, Any]:
        """Fold the last model call into the ledger; render its own field.

        Called once per step, immediately after ``chat_fn`` returns, and
        the ``{"usage": …}`` it hands back is spread into whichever record
        that step goes on to emit — ``tool_call``, ``answer`` or
        ``reply_rejected``, the three records that follow a model call.

        ``{}`` when the provider reported nothing, so the field is
        **absent** rather than zero.  Never raises: a usage source that
        throws must not be able to end a mission, for the same reason an
        observer that throws cannot.
        """
        try:
            usage = self._usage_fn() if self._usage_fn is not None else None
        except Exception:                       # pragma: no cover - defensive
            usage = None
        recorded = transcript.usage.add(usage)
        return {"usage": recorded.as_record()} if recorded is not None else {}

    # ── the catalogue ───────────────────────────────────────────────────

    def catalogue(self) -> str:
        """Render the bus's own descriptions; do not restate them.

        ``describe_tool`` is what ``tools/list`` became once it crossed
        the bridge.  Rewriting it here would be a second copy of a tool's
        contract, and the two would disagree the first time a server
        changed a description.

        Arguments are rendered from the tool's own JSON Schema and not
        from a list of names.  ``limit (integer)`` and ``type (string:
        dataset|model)`` are the difference between a first call that
        works and three refused ones spent discovering that ``type``
        is not free text — and on a 59 tok/s local model, three refused
        calls is most of a mission's budget.
        """
        lines = []
        for name in self.offered:
            info = self._bus.describe_tool(name)
            if "error" in info:
                continue
            desc = info.get("description") or ""
            # Marked in the catalogue rather than withheld from it. See the
            # `gated` parameter: "there is no tool named X" is false and a
            # model told it reroutes around a capability it actually has.
            mark = (" [NEEDS APPROVAL — propose it and a person decides; the "
                    "call is not made until they do]"
                    if name in self._gated else "")
            lines.append(f"- {name}: {desc}{mark}".rstrip())
            arguments = info.get("arguments") or summarize_input_schema(
                info.get("input_schema")
            )
            if arguments:
                lines.append(f"    arguments: {arguments}")
        return "\n".join(lines) if lines else "(no tools available)"

    def seed(self, objective: str) -> List[Dict[str, str]]:
        """The PLAN-phase messages: persona, protocol, catalogue, history, objective.

        The prior turns sit between the system prompt and the current
        question, so what the model receives is a genuine multi-turn
        conversation whose newest user message is the objective.  The
        objective must arrive **without** the history also folded into it
        as text — a caller that does both injects every prior turn twice,
        once where the model attends to it and once where it does not.

        Fresh dicts each call: the loop appends to the list this returns,
        and a runner run twice must not find its history aliased to a
        previous run's messages.
        """
        system = "\n\n".join(
            part for part in (
                self._system_message.strip(),
                PROTOCOL.strip(),
                "Tool catalogue:\n" + self.catalogue(),
            ) if part
        )
        return [
            {"role": "system", "content": system},
            *(dict(turn) for turn in self._history),
            {"role": "user", "content": objective},
        ]

    # ── keeping the conversation inside the window ──────────────────────

    @property
    def pinned(self) -> int:
        """How many leading messages a compaction may never drop.

        Exactly what :meth:`seed` returns — the system turn, every seeded
        history turn, and the objective — counted the same way it builds
        them, because the two must move together: a prefix that grew a
        message and a count that did not is a compaction that eats the
        objective and an agent that answers a question nobody asked.
        """
        return 2 + len(self._history)

    def _compaction_note(self, dropped_turns: int, freed_chars: int) -> str:
        """The default notice, plus where the dropped bytes still are.

        The generic sentence says the work was done and the paste was
        removed.  Only the runner knows the store's name, and naming it
        here is the same teaching move as
        :meth:`_say_it_is_unchanged`: the moment the model loses a result
        from the transcript is the moment to tell it that the result is
        still addressable, because a rule stated 2,000 tokens upstream in
        a persona does not survive to the turn it binds.
        """
        note = default_compaction_note(dropped_turns, freed_chars)
        if not self._store_tool:
            return note
        return (
            f"{note} Every result of this mission is still readable: call "
            f'{self._store_tool}(handle="…", path="…") with the handle you '
            f"were given when it arrived."
        )

    def _fit(
        self, messages: List[Dict[str, str]],
    ) -> Tuple[List[Dict[str, str]], Optional[Compaction]]:
        """``(messages to send, what was dropped or None)``.

        No window is the loop as it ran before there was one: the list
        goes out whole.
        """
        if self._window is None:
            return messages, None
        return self._window.fit(
            messages, pinned=self.pinned, note=self._compaction_note,
        )

    # ── the loop ────────────────────────────────────────────────────────

    def run(self, objective: str,
            resumption: Optional[Any] = None) -> MissionTranscript:
        """Run the mission, or carry a recorded one on from where it stopped.

        *resumption* is a :class:`core.runtime.resume.Resumption` — the
        recorded stream read back into this loop's own state — and ``None``
        is every run that starts cold, which is the shape this method had
        before resuming existed.  Duck-typed rather than imported, because
        :mod:`core.runtime.resume` imports *this* module for
        :class:`MissionStep` and a type annotation is not worth a cycle.

        **A resumed run does not emit a second ``mission_started``.**  It is
        the same mission: one objective, one catalogue, one id, one log.  A
        consumer reading the whole log of a run that was resumed twice would
        otherwise find three openings for one mission and render three, and
        a follower holding a cursor sees only the new records anyway, so the
        opening would be a frame it never receives.  What it does receive is
        the next ``step_started``, and that is where the resumption is
        stated — see :meth:`Resumption.as_record
        <core.runtime.resume.Resumption.as_record>`.
        """
        # The first start wins, so a sub-mission of a staged run does not
        # rewind the clock its parent already wound. See `Deadline.start`.
        if self._deadline is not None:
            self._deadline.start()
        offered = self.offered
        transcript = MissionTranscript(
            objective=objective, catalogue=list(offered),
            # A ledger the caller handed in is shared and must not be
            # reset here; without one, a fresh ledger per run, so a second
            # `run` on the same runner does not report the first one's
            # tokens.
            usage=self._shared_ledger if self._shared_ledger is not None
            else Ledger(),
        )
        if resumption is None:
            self._store.clear()
        else:
            # Adopted, not copied into: the handles the model was given
            # earlier in this run (`r1`, `r2`) have to keep addressing the
            # same results, and a store rebuilt beside the runner's own
            # would mean `mission_result` reads one and the grounding
            # validator reads the other.
            self._store = resumption.store
            transcript.steps.extend(resumption.steps)
        registered = self._register_store()
        # `history` is a count, not the turns: a watcher needs to tell a
        # seeded conversation from a cold start, and the turns themselves
        # already travelled once — TAIPAN holds the thread it sent.
        # `schema_version` first and on the FIRST record, so a consumer that
        # is going to refuse this stream refuses it before it has rendered
        # anything from it. See `core.runtime.contract`.
        # `sandbox` is the word the bus's actual runner answers to — `bwrap`
        # or `none` — so a consumer learns from the opening frame whether the
        # tool subprocesses this mission runs are isolated, without inferring
        # it from the host. One owner: the bus derives it from the installed
        # sandbox, and the staged path reads the same property.
        # `audit_ref` names the file every dispatch below is being written
        # to, and `None` says there is no such file because somebody turned
        # auditing off in as many words. A consumer that finds no audit log
        # and no field cannot tell that from a harness that failed to open
        # one.
        if resumption is None:
            self._emit(MISSION_STARTED, schema_version=SCHEMA_VERSION,
                       objective=objective, catalogue=list(offered),
                       gated=self.gated, max_steps=self._max_steps,
                       history=len(self._history),
                       sandbox=sandbox_of(self._bus),
                       audit_ref=audit_ref_of(self._bus),
                       **_run_field(self._run_id),
                       **_profile_field(self._bus))
        try:
            return self._loop(objective, offered, transcript, resumption)
        finally:
            if registered:
                self._bus.unregister(registered)
            # Withdrawn for the same reason the store descriptor is: the bus
            # outlives this run, and a `step` left behind would stamp the
            # next chat turn's audit entry with the last mission's index —
            # a column that is wrong rather than absent, which is worse.
            context = getattr(self._bus, "audit_context", None)
            if isinstance(context, dict):
                context.pop("step", None)
            # In `finally` so that a mission killed by an exception still tells
            # the watcher the mission is over. A stream that just stops is
            # indistinguishable from an agent that is thinking, and a pane
            # showing a spinner forever is the state an analyst cannot leave.
            # Through `_finished_record` and not by hand, because the staged
            # path emits this record too and a second hand-listing is how the
            # swarm's `grounding` came to carry six of ten fields.
            # `usage` is the run's totals and is ABSENT when no provider
            # reported anything — not three zeros.
            self._emit(MISSION_FINISHED, **_finished_record(
                outcome=transcript.outcome,
                steps=len(transcript.steps),
                max_steps=self._max_steps,
                budget=transcript.budget,
                reason=transcript.reason,
                usage=transcript.usage.as_record(self._rate)))

    def _register_store(self) -> str:
        """Put the result store on the bus for the length of this run.

        Registered and withdrawn rather than left there: the store holds
        one mission's results, and a descriptor that outlived the run
        would offer the next one a handle into the previous one's
        governed material.  It goes through the bus like everything else
        so the audit log records a read of it.
        """
        if not self._store_tool:
            return ""
        return self._store.register_on(self._bus, self._store_tool)

    def _loop(
        self, objective: str, offered: Sequence[str], transcript: MissionTranscript,
        resumption: Optional[Any] = None,
    ) -> MissionTranscript:
        messages = self.seed(objective)
        repairs = 0
        start = 0
        # Carried on the FIRST `step_started` of the resumed stretch and no
        # other, exactly as the swarm's `plan` is: a field an event declares
        # is a field a consumer has a sentence for, and one that arrived on
        # every step would be a fact restated rather than a resumption
        # announced.
        opening: Dict[str, Any] = {}

        if resumption is not None:
            # The seed is rebuilt rather than replayed — persona, catalogue
            # and history belong to the resuming process, and a run resumed
            # against a server that has since grown a tool must be told
            # about the tool. Everything the loop itself appended is the
            # tail, and that is the half the log can give back.
            messages.extend(dict(turn) for turn in resumption.tail)
            repairs = resumption.repairs
            start = resumption.next_index
            opening = {"resumed": resumption.as_record()}

        # `self._max_steps` is the TOTAL for the run and not an allowance
        # for this process — see `Recorded.total_steps`, which is where the
        # caller works out what that total is. A resumed run whose recorded
        # steps already met it runs no steps and ends `budget_exhausted`,
        # which is the truth about it.
        for index in range(start, self._max_steps):
            # Between steps AND before the model call, which in this loop
            # is one point: every path that continues — a parse error, a
            # refused tool, a grounding repair — comes back through here,
            # so a run cannot spend a repair turn past its deadline.
            stop = self._stop()
            if stop is not None:
                return self._stopped(transcript, stop)
            # Before the ask, not after the reply: what is compacted is
            # what this step is about to send, and a watcher told about it
            # afterwards has already rendered the turn it applied to.
            messages, compacted = self._fit(messages)
            self._emit(STEP_STARTED, index=index, **opening,
                       **({"compacted": compacted.as_record()}
                          if compacted is not None else {}))
            opening = {}
            reply = str(self._chat(messages) or "")
            # Read here and used below: whichever record this step emits
            # carries the cost of the call that produced it. One read per
            # call, because `last_usage` is a side channel that the NEXT
            # call clears.
            spent = self._spent(transcript)
            step = MissionStep(index=index, raw_reply=reply)
            messages.append({"role": "assistant", "content": reply})

            decision, problem = self._parse(reply)
            if problem:
                step.error = problem
                transcript.steps.append(step)
                self._emit(REPLY_REJECTED, index=index, problem=problem,
                           **spent)
                messages.append({"role": "user", "content": problem})
                continue

            if "answer" in decision:
                answer = str(decision["answer"])
                report = self._ground(answer, repairs)
                transcript.grounding = report

                if report is not None and report.ran and not report.grounded:
                    if repairs < self._validator.max_repairs:
                        repairs += 1
                        problem = self._validator.repair_prompt(report)
                        step.error = problem
                        transcript.steps.append(step)
                        # A repair turn is a whole extra round-trip to the
                        # model and, from outside, looks exactly like a stall.
                        # Said out loud so a watcher can show WHY the answer
                        # is taking longer — the check caught something.
                        self._emit(GROUNDING, **_grounding_record(
                            report, repairs=repairs, repairing=True))
                        messages.append({"role": "user", "content": problem})
                        continue
                    # One repair turn was spent and the claim is still
                    # unsupported. The answer is kept — deleting it would
                    # hide a finding — and says so about itself.
                    caveat = self._validator.caveat(report)
                    marked = GroundingReport(
                        results=report.results, repairs=repairs, caveat=caveat,
                    )
                    transcript.grounding = marked
                    transcript.answer = answer + caveat
                    transcript.outcome = "answered_with_caveat"
                    transcript.steps.append(step)
                    # The verdict BEFORE the answer, so a consumer building a
                    # frame around the prose already knows what to mark it
                    # with. A caveat that arrives after the text it qualifies
                    # is a caveat that can be rendered separately from it.
                    self._emit(GROUNDING, **_grounding_record(
                        marked, repairs=repairs, caveat=caveat))
                    self._emit(ANSWER, text=transcript.answer,
                               outcome=transcript.outcome, **spent)
                    return transcript

                if report is not None:
                    transcript.grounding = GroundingReport(
                        results=report.results, repairs=repairs,
                    )
                    self._emit(GROUNDING, **_grounding_record(
                        transcript.grounding, repairs=repairs))
                transcript.answer = answer
                transcript.outcome = "answered"
                transcript.steps.append(step)
                self._emit(ANSWER, text=answer, outcome=transcript.outcome,
                           **spent)
                return transcript

            name = str(decision.get("tool") or "")
            arguments = decision.get("arguments") or {}
            if not isinstance(arguments, dict):
                problem = (
                    f'"arguments" must be a JSON object, got '
                    f"{type(arguments).__name__}. Retry with one JSON object."
                )
                step.tool, step.error = name, problem
                transcript.steps.append(step)
                self._emit(REPLY_REJECTED, index=index, tool=name,
                           problem=problem, **spent)
                messages.append({"role": "user", "content": problem})
                continue

            step.tool, step.arguments = name, dict(arguments)

            if name not in offered:
                problem = self._no_such_tool(name, offered)
                step.error = problem
                transcript.steps.append(step)
                self._emit(REPLY_REJECTED, index=index, tool=name,
                           problem=problem, **spent)
                messages.append({"role": "user", "content": problem})
                continue

            if name in self._gated:
                # STOP. Not dispatched, not retried, and not handed back to
                # the model to work around — the mission ends here holding the
                # exact call it proposed, and somebody who is not this process
                # decides what happens to it.
                reason = (
                    f"{name} needs a person's approval on this deployment. It "
                    f"has been proposed exactly as written and NOT called. "
                    f"Nothing further happens on this mission until somebody "
                    f"decides.")
                # Written down BEFORE the record goes out, so the id a
                # watcher is handed is an id something can already be
                # decided against. This process is about to exit; a request
                # that lived only in the consumer's memory is the defect the
                # store exists to fix.
                approval_id, trouble = self._request_approval(
                    objective, name, arguments, reason)
                if trouble:
                    reason = f"{reason} {trouble}"
                carried = {"approval_id": approval_id} if approval_id else {}
                step.error = reason
                transcript.steps.append(step)
                transcript.outcome = AWAITING_APPROVAL
                transcript.awaiting = {"tool": name,
                                       "arguments": dict(arguments),
                                       **carried}
                self._emit(GATE_REQUESTED, index=index, tool=name,
                           arguments=dict(arguments), reason=reason,
                           **carried)
                return transcript

            # Checked again here, after the model call this step spent: the
            # clock may have run out while the endpoint was answering, and
            # `tool_call` is emitted BEFORE the dispatch, so a watcher told
            # a call was about to happen must not then be told the mission
            # ended without it. The proposal is recorded as a step that did
            # not run, in the model's own words about what it wanted.
            stop = self._stop()
            if stop is not None:
                step.error = self._no_time_to_call(name, stop)
                transcript.steps.append(step)
                return self._stopped(transcript, stop)

            self._emit(TOOL_CALL, index=index, tool=name,
                       arguments=dict(arguments), **spent)
            # The bus has no idea what a step is and should not learn: it
            # serves chat turns, kernel roles and missions alike. So the
            # mission leaves its index where the audit entry is built,
            # rather than the bus growing a mission-shaped parameter.
            # Guarded by `isinstance`, because a caller's fake bus has no
            # such dict and a missing audit column is not worth a crash.
            context = getattr(self._bus, "audit_context", None)
            if isinstance(context, dict):
                context["step"] = index
            if self._approval is not None and name == self._approval.tool:
                # HERE and not at the door: a resumed run that answers
                # without calling anything, or runs out of steps, has not
                # used anybody's yes, and burning one on a run where nothing
                # happened teaches an operator to approve the same act twice.
                # Before the dispatch, so a store that refuses to spend —
                # somebody else already did, the record moved underneath us —
                # stops the call rather than following it. That refusal is
                # allowed to end the mission: failing closed is the only
                # direction this may fail in.
                self._approval.spend()
            # The remaining wall clock rides down as a ceiling on the call,
            # where the bus takes one, so a tool cannot run past the
            # deadline by more than its own bounded slack.
            call = dict(arguments)
            call.update(self._deadline_ceiling())
            result = self._bus.dispatch(name, **call)
            step.exit_code = result.exit_code
            step.output = result.stdout
            step.error = result.stderr
            stored = self._store.record(
                name, arguments,
                text=result.stdout,
                evidence=getattr(result, "evidence", "") or "",
                exit_code=result.exit_code,
            )
            step.handle = stored.handle
            rendered, step.truncated = self._render_result(
                name, result, stored.handle,
                already=self._store.first_identical(stored),
            )
            transcript.steps.append(step)
            # The WHOLE result, not the bounded rendering. The bound exists
            # because a model's context is finite; a watcher's is not, and a
            # pane showing an analyst 60% of a governed listing because the
            # model could only be shown that much would be inventing a limit
            # nobody imposed.
            self._emit(TOOL_RESULT, index=index, tool=name,
                       arguments=dict(arguments),
                       ok=result.exit_code == 0, exit_code=result.exit_code,
                       output=result.stdout or "", error=result.stderr or "",
                       handle=stored.handle, truncated=step.truncated)
            messages.append({"role": "user", "content": rendered})

        transcript.outcome = "budget_exhausted"
        # Which budget, with the numbers. `steps` and not `seconds`: the
        # `for` ran to its end, so the clock — if there was one — still had
        # room, and a consumer told "budget_exhausted" and nothing else
        # cannot tell a mission that needed more turns from one that needed
        # a faster endpoint.
        transcript.budget = BudgetExhausted(
            "steps", self._max_steps, len(transcript.steps))
        return transcript

    def _request_approval(
        self, objective: str, tool: str, arguments: Dict[str, Any],
        reason: str,
    ) -> Tuple[str, str]:
        """``(approval_id, trouble)`` — the durable record for one gate.

        ``("", "")`` when no store was injected: the loop as it ran before
        approvals were durable, which is what a test and a library caller
        holding their own gate machinery still want.

        A store that cannot write is **said out loud** rather than swallowed.
        The gate has already done its job — nothing is dispatched either way
        — but a request with no record is a request nobody can ever answer,
        and an operator who is never told that is waiting on a decision that
        cannot be made.  Same lesson as the audit log's failed write: a bare
        ``pass`` around a record that did not get written is how a run comes
        to look complete and be unaccountable.

        It writes and returns; there is nothing here that reads a state, and
        nothing here that could produce an approved one.
        """
        if self._approvals is None:
            return "", ""
        try:
            return self._approvals.request(
                tool=tool, arguments=dict(arguments), objective=objective,
                run_id=self._run_id, reason=reason), ""
        except OSError as exc:
            return "", (
                f"NO DURABLE RECORD of this request could be written "
                f"({exc}), so there is nothing for anybody to decide "
                f"against — the call is still not made, and asking again "
                f"will not help until the approvals directory is writable.")

    # ── being asked to stop, and running out of clock ───────────────────

    def _stop(self) -> Optional[Tuple[str, Optional[BudgetExhausted], str]]:
        """``(outcome, budget, reason)`` when the run must stop, else ``None``.

        Returned rather than raised.  The loop wants to *end* — recorded
        outcome, intact transcript, its own ``mission_finished`` — and a
        loop that unwinds through an exception to do that is one stray
        ``except`` away from ending on somebody else's.

        Cancellation is asked about first, and that is a decision.  When a
        clock and a person both say stop at the same moment, the person is
        the one who is going to be shown a sentence about it, and
        "somebody stopped this" is the truer thing to show them than
        "it ran out of seconds" — which would also be true, and useless.
        """
        if cancelled(self._cancel):
            return "incomplete", None, CANCELLED
        exhausted = (self._deadline.exhausted()
                     if self._deadline is not None else None)
        if exhausted is not None:
            return "budget_exhausted", exhausted, ""
        return None

    @staticmethod
    def _stopped(transcript: MissionTranscript,
                 stop: Tuple[str, Optional[BudgetExhausted], str],
                 ) -> MissionTranscript:
        """Write a :meth:`_stop` verdict onto the transcript and hand it back."""
        transcript.outcome, transcript.budget, transcript.reason = stop
        return transcript

    @staticmethod
    def _no_time_to_call(
            name: str, stop: Tuple[str, Optional[BudgetExhausted], str]) -> str:
        """What a step that proposed a tool and never ran it says about itself.

        On the step rather than only in the outcome, because the step is
        what a transcript prints and what an operator reads: a proposal
        with no result beside it looks like a tool that failed silently,
        and this is the sentence that says it was never called at all.
        """
        why = (f"the mission was cancelled" if stop[2] == CANCELLED else
               f"the mission's {stop[1].which} budget ran out")
        return (f"{name} was proposed and NOT called: {why} before the "
                f"call could be dispatched.")

    def _deadline_ceiling(self) -> Dict[str, Any]:
        """``{"deadline_s": …}`` when there is a clock and the bus takes one.

        Empty otherwise, and empty is the ordinary case: a mission with no
        wall clock passes nothing, so a run that behaved one way before
        this parameter existed behaves that way still — including a
        caller's fake bus, which never sees a keyword it did not expect
        unless that caller asked for a deadline.

        The floor is zero and not the true remaining figure: a negative
        ceiling is a caller telling a subprocess layer to run for minus
        two seconds, and what that means is the subprocess layer's guess.
        This loop's own check has already refused to get here with nothing
        left; zero is the honest way to say "and not a second more".
        """
        if self._deadline is None or not self._bus_takes_deadline:
            return {}
        remaining = self._deadline.remaining()
        if remaining is None:
            return {}
        return {"deadline_s": max(0.0, remaining)}

    def _ground(self, answer: str, repairs: int) -> Optional[GroundingReport]:
        """Validate the answer, or ``None`` when nothing is configured."""
        if self._validator is None:
            return None
        report = self._validator.validate(answer, self._store.evidence_texts())
        if not report.ran:
            # Every check said it could not run. That is a report with no
            # opinion, and it must not be read as a pass — it is kept on
            # the transcript for exactly that reason.
            return GroundingReport(results=report.results, repairs=repairs)
        return report

    # ── parsing ─────────────────────────────────────────────────────────

    @staticmethod
    def _parse(reply: str):
        """Return ``(decision, problem)``; exactly one is truthy.

        A model that wrapped its JSON in a fence gets the fence stripped
        — that is a formatting slip, not a different decision.  A model
        that said something else entirely gets told what was expected,
        because guessing an intent out of prose is how a loop calls a
        tool nobody asked for.
        """
        text = _FENCE.sub("", (reply or "").strip()).strip()
        if not text:
            return None, "Empty reply. Reply with one JSON object."
        try:
            decision = json.loads(text)
        except json.JSONDecodeError as exc:
            return None, (
                f"That was not valid JSON ({exc.msg}). Reply with exactly one "
                f'JSON object: {{"tool": ..., "arguments": {{...}}}} or '
                f'{{"answer": ...}}.'
            )
        if not isinstance(decision, dict):
            return None, (
                f"Expected a JSON object, got a {type(decision).__name__}. "
                f"Reply with one JSON object."
            )
        if "answer" not in decision and "tool" not in decision:
            return None, (
                'The object needs either a "tool" key or an "answer" key. '
                "Reply with one JSON object."
            )
        return decision, None

    def _render_result(self, name: str, result: Any, handle: str = "",
                       already: Any = None):
        """``(what the model is shown, whether it was cut down)``.

        *already* is an earlier result of this exact call with these exact
        bytes, when there is one.  See
        :meth:`~core.runtime.results.MissionResultStore.first_identical`:
        the call is made and recorded either way, and only the paste into
        the transcript is collapsed, so a poll that returned something new
        is still shown in full while a re-fetch of an unchanged view costs
        one line instead of thirty-three thousand characters.
        """
        if result.exit_code == 0:
            if already is not None:
                return self._say_it_is_unchanged(name, already), False
            body, truncated = self._bound(result.stdout or "(no output)", handle)
            return f"Result of {name} (ok):\n{body}", truncated
        body, truncated = self._bound(
            result.stderr or result.stdout or "(no detail)", handle,
        )
        return (
            f"Result of {name} (refused, exit {result.exit_code}):\n{body}\n"
            f"Do not retry the same call unchanged."
        ), truncated

    @staticmethod
    def _near_miss(name: str, offered: Sequence[str]) -> str:
        """The offered tool *name* was probably trying to be, or ``""``.

        Not fuzzy matching.  The recorded failures are all one shape — the
        right tool under a different **namespace convention** — and a
        deliberately narrow rule catches them without ever proposing a
        genuinely different tool, which is the way a helpful suggestion
        becomes a wrong call the model makes confidently.

        Measured 10 August 2026: one prompt carried three spellings of one
        tool.  ``mcp.catalog_search_assets`` is the dispatch name, the
        catalogue prose says ``catalog.search_assets``, and the skill prose
        says bare ``catalog_search_assets``.  A mission emitted the bare
        form, spent a turn on ``reply_rejected``, and spent a second turn
        on a repair that guessed wrong — because the refusal listed the
        whole catalogue and never said *which* entry the model had nearly
        typed.

        The comparison is :func:`~core.tools.descriptors.tool_key` — the
        harness's one answer to *"are these the same tool"*, shared with
        ``SkillManifest.resolve`` and with the grounding checks' ignore
        rule, because three private copies of that question is the
        three-spellings defect one level up.  So
        ``catalog_search_assets``, ``catalog.search_assets`` and
        ``mcp.catalog_search_assets`` all reduce together, and a suffix
        match catches an unqualified name against its namespaced form.  A
        name that reduces to two offered tools proposes neither: an
        ambiguous suggestion is a coin flip the model cannot see it is
        taking.
        """
        matches = [c for c in offered if same_tool(c, name)]
        return matches[0] if len(matches) == 1 else ""

    def _no_such_tool(self, name: str, offered: Sequence[str]) -> str:
        """The refusal for a tool this mission does not offer.

        Leads with the near miss when there is one.  The catalogue still
        follows it, because a model that meant a different tool entirely
        needs to see the set — but a refusal whose first line is the
        answer is the one that costs a single turn instead of three.
        """
        listed = ", ".join(offered) or "(none)"
        near = self._near_miss(name, offered)
        if near:
            return (
                f"There is no tool named {name!r} in this mission. You almost "
                f"certainly mean {near!r} — that is the same tool under the "
                f"name this deployment dispatches it by. Spell it exactly as "
                f"{near!r}. The full set is: {listed}."
            )
        return (
            f"There is no tool named {name!r} in this mission. "
            f"Choose one of: {listed}."
        )

    def _say_it_is_unchanged(self, name: str, already: Any) -> str:
        """The one line an unchanged re-fetch is worth, and what to do next.

        Written as a teaching refusal rather than a bare notice.  The
        measured lesson of 10 August is that the platform's own refusal
        text taught a 20B model a rule verbatim at the turn it bound,
        while the same rule 2,000 tokens upstream in a persona did
        nothing.  A model that re-fetched a view has not understood that
        the whole of it is already addressable, so this is the moment to
        say so — with the handle, and with the call spelled out.
        """
        where = (
            f' Call {self._store_tool}(handle="{already.handle}", path="...") '
            f"to read any field of it — the whole result is there, including "
            f"the parts the transcript truncated."
            if self._store_tool else
            " Re-read it in the transcript above."
        )
        return (
            f"Result of {name} (ok): byte-for-byte identical to "
            f"{already.handle}, which you already received in this mission. "
            f"It is not shown again.{where} Calling {name} with the same "
            f"arguments will keep returning this."
        )

    def _bound(self, body: str, handle: str = ""):
        """Head and tail of *body*, with a marker naming the store.

        The cut itself belongs to :func:`core.bounding.bound_result`,
        which every path that bounds a tool result now shares.  What is
        the mission's own is the clause the marker ends with: when this
        run has a store, a truncated result is not a loss but a
        redirection, and the sentence that says so spells out the call —
        the recorded lesson is that a refusal at the turn it binds
        teaches a small model a rule that the same rule 2,000 tokens
        upstream in a persona does not.
        """
        where = (
            f" The whole result is stored as {handle}: call "
            f'{self._store_tool}(handle="{handle}", path="...") for one field.'
            if handle and self._store_tool else
            " The rest is not retrievable in this mission."
        )
        return bound_result(body, self._max_result_bytes, where=where)
