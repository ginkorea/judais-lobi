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
* …unless the caller asked for the **native protocol**
  (:data:`NATIVE_PROTOCOL`), in which case the reply is not text at all
  but a function call the decoder was constrained to produce, and the two
  mistakes that class of failure is made of — invalid JSON, and a tool
  name nobody offers — are unrepresentable rather than caught.  It is
  off by default and measured before it is anybody's default; see the
  ``protocol`` parameter;
* the arguments of a call are checked against the tool's **own published
  schema** before it is dispatched, in either protocol.  See
  :mod:`core.runtime.schema_check`, and in particular what that check
  cannot catch;
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
* and a caller may **steer** one, with a
  :class:`~core.runtime.control.ControlChannel`.  Commands coming in where
  the observer is records going out: a user instruction delivered between
  steps, a cancellation, an abandonment of the rest of the current step,
  and a decision on a gate the run is still standing at.  Every one of
  them is drained at a point this loop chose, and none of them decides
  anything the harness was not already told;
* a tool result is **bounded** before it enters the transcript, and the
  whole of it stays in a per-mission store the model can read one field
  of.  See :mod:`core.runtime.results` for why an unbounded paste is a
  correctness problem and not a tidiness one;
* the **conversation** is bounded too, when the caller supplies a
  window: bounding each result says nothing about the sum of them, and
  the sum is what meets ``max_model_len``.  **Tool round trips go before
  turns somebody said** — the output is still in the result store and the
  said turn is what a follow-up refers to — the persona, catalogue,
  seeded turns, objective and newest round trip stay, and the drop is a
  record on the stream rather than a shorter prompt nobody mentioned.
  See :class:`~core.runtime.context_window.MissionWindow`;
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
import time
from dataclasses import dataclass, field
from typing import (
    Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple,
)

from core.bounding import MAX_RESULT_BYTES, bound_result
from core.durable import RunStore
from core.budgets import BudgetExhausted, Deadline, cancelled
from core.redact import scrub_record
from core.runtime.answer_stream import drain as drain_answer
from core.runtime.approvals import ApprovalError, ApprovalStore, ApprovalTicket
from core.runtime.context_window import (
    Compaction, MissionWindow, default_compaction_note,
)
from core.runtime.contract import SCHEMA_VERSION
from core.runtime.control import (
    CANCEL_STEP, GATE_DECISION, GATE_WAIT_S, INJECT,
)
from core.runtime.grounding import GroundingReport, GroundingValidator
from core.runtime.mission_stream import (
    ANSWER, ANSWER_DELTA, GATE_REQUESTED, GROUNDING, MISSION_FINISHED,
    MISSION_STARTED, REPLY_REJECTED, STEP_STARTED, TOOL_CALL, TOOL_RESULT,
    Observer,
)
from core.runtime.results import RESULT_TOOL, MissionResultStore
from core.runtime.schema_check import check as check_arguments
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


def _protocol_field(protocol: str) -> Dict[str, Any]:
    """``{"protocol": word}`` for a run that is not speaking the default.

    Absent — not ``"json"`` — on an ordinary run, which is the whole reason
    the field can be added at all without bumping ``SCHEMA_VERSION``: every
    stream a consumer has ever read stays byte-identical, and the field
    appears exactly when something about the run it describes is different.
    A consumer reads it with a default of :data:`JSON_PROTOCOL`, like every
    OPTIONAL field.

    It matters on the wire and not only as trivia: a resumed run has to be
    rebuilt in the message shape it was recorded in — native turns carry
    ``tool_calls`` and are answered by ``tool`` messages — and this is where
    :func:`core.runtime.resume.rebuild` learns which.  One owner: the
    swarm's opening frame reads it from here too.
    """
    return {"protocol": protocol} if protocol != JSON_PROTOCOL else {}


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

def stacked(*parts: str) -> str:
    """The ONE way this harness stacks prompt sections into a system turn.

    Blank line between sections, empty sections dropped, every section
    stripped.  Trivial, and it has one owner for a reason that is not
    tidiness: a served endpoint's prefix cache is keyed on **bytes**, so
    two assembly sites that disagree about a trailing newline produce two
    prefixes where the deployment was paying for one.  ``seed`` below and
    the swarm's four role prompts all come through here, so the persona a
    turn opens with is byte-identical whichever role is speaking.

    Sections are ordered most-constant-first everywhere it is used — see
    :meth:`MissionRunner.seed` for what that order is and why the
    catalogue is last of the three.
    """
    return "\n\n".join(part.strip() for part in parts if part and part.strip())


#: The protocol this loop has always spoken: one JSON object per reply,
#: parsed out of the text.  The default, and it stays the default until an
#: eval harness says the other one is better — see ``ROADMAP.md`` §2.5.
JSON_PROTOCOL = "json"

#: The other one: the model does not write a decision, it **calls a
#: function**, and the server's decoder is constrained to the namespace the
#: request declared.
#:
#: The failure class this closes was measured rather than imagined.  On the
#: reference deployment's 10 August suite a mission spent two turns of eight
#: on a malformed tool name and two more on invalid JSON — a quarter of the
#: budget on protocol rather than on the question — and on the 20B a
#: four-turn mission spent two of them on argument shape.  Under
#: ``tool_choice="required"`` neither mistake is representable: the decoder
#: cannot emit a name outside the declared namespace, nor arguments that do
#: not parse.  What is left is arguments that parse and are wrong, which is
#: what :mod:`core.runtime.schema_check` is for.
#:
#: It is **not** the default, and that is the discipline rather than
#: timidity: this and the grounding control were probed the same day, and a
#: change turned on before the harness that scores it produces a delta
#: nobody can attribute.
NATIVE_PROTOCOL = "native"

#: The closed set, so a caller can be refused by name rather than by
#: discovering later that its word did nothing.
PROTOCOLS = (JSON_PROTOCOL, NATIVE_PROTOCOL)

#: The synthetic function a native-protocol mission finishes by calling.
#:
#: A function and not a sentinel string, because under
#: ``tool_choice="required"`` the model has no other way to stop: every
#: reply must be a call, so "I am done" has to be one too.  It is
#: registered on **nothing** — the bus never sees it, no capability governs
#: it, and dispatching it is not a thing this loop can do; it is read out of
#: the call list and turned into the answer the JSON protocol would have
#: produced from ``{"answer": …}``.
#:
#: ``mission_`` prefixed for the reason :data:`~core.runtime.results
#: .RESULT_TOOL` is: it shares a namespace with whatever a server
#: advertises, and a collision would mean the model's way of finishing was
#: also somebody's tool.  A collision is refused at construction rather
#: than resolved by renaming one of them, because both names would then be
#: right somewhere and wrong here.
ANSWER_TOOL = "mission_answer"

#: The declaration of :data:`ANSWER_TOOL`, in the shape a request carries.
#:
#: Here rather than in the CLI because it is half of the protocol: the loop
#: reads a call to this function and the caller declares it, and two copies
#: of one function's schema is the arrangement that had six of ten grounding
#: fields hand-listed in a second emitter.
ANSWER_FUNCTION: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": ANSWER_TOOL,
        "description": (
            "Finish the mission. Call this — and nothing else in the same "
            "reply — with your final answer for the person who asked. "
            "Base every statement on a tool result you actually received."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string",
                         "description": "The final answer, in prose."},
            },
            "required": ["text"],
        },
    },
}

#: The protocol text for a native run.  Same job as :data:`PROTOCOL` and
#: the same reason it is one string: the instruction and the branch that
#: reads the reply have to say the same thing.
NATIVE_PROTOCOL_TEXT = f"""\
You are working a mission with tools. The tools below are declared to you \
as functions and every reply must be one or more CALLS to them — not prose, \
not JSON in a message.

To use a tool: call it by name, with its arguments.
To finish: call {ANSWER_TOOL}(text="<your final answer>").

You may make several tool calls in one reply; they are dispatched in the \
order you give them and you are shown every result. {ANSWER_TOOL} counts \
only when it is ALONE: called alongside tool calls it is ignored, the tools \
run, and you are asked again. Base every statement on a tool result you \
actually received; if the tools cannot support a statement, say so in \
{ANSWER_TOOL} instead of asserting it.
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
                      repairing: bool = False, caveat: str = "",
                      opinions: Sequence[Mapping[str, Any]] = ()) -> Dict[str, Any]:
    """A :class:`GroundingReport` as the observer's ``grounding`` fields.

    Read off the report with ``getattr`` defaults rather than by unpacking a
    known shape: this module's job is to say what the validator said, and a
    check the validator grows next month should reach a watcher as a row in
    ``checks`` rather than as an ``AttributeError`` inside a mission.

    *opinions* are rows a **second opinion** contributed — today the critic's,
    from :meth:`core.critic.mission.CriticOpinion.as_check`.  They are
    appended to ``checks`` and they are appended LAST, after every mechanical
    row, and they are **not** in ``report.results``: ``grounded``,
    ``verified``, ``unsupported``, ``silent`` and ``uncited`` are all computed
    from the report alone, so a model's opinion cannot move a mechanical fact.
    Each such row carries ``advisory: true`` and says so for itself.
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
             "detail": getattr(row, "detail", ""),
             # False on every mechanical row and true on a second opinion,
             # stated on both so a consumer never has to infer it from a
             # check's name. See `opinions` above.
             "advisory": False}
            for row in (getattr(report, "results", ()) or ())
        ] + [dict(row) for row in opinions],
    }


def second_opinion(critic: Any, objective: str, answer: str,
                   evidence: Sequence[str], *,
                   unsupported: Sequence[str] = (),
                   answered_with_caveat: bool) -> List[Dict[str, Any]]:
    """The critic's row for a grounding record, or no rows at all.

    **One owner, and there are two callers**: the direct loop's
    :meth:`MissionRunner._second_opinion` and the staged path's
    :meth:`~core.runtime.swarm.SwarmRunner._synthesize`.  A second copy of
    these six keys is precisely the arrangement that had the swarm emitting
    six of ``grounding``'s ten fields — and this row is worse than a field
    to get wrong, because ``advisory`` is what stops a model's opinion being
    read as a mechanical verdict.

    Beside the mechanical verdict and never inside it — see
    :func:`_grounding_record` and :mod:`core.critic.mission`.  The report the
    caller holds is already final; nothing this returns is allowed to change
    it, which is why it comes back as rows for the record rather than as a
    report the caller merges.

    ``None`` for *critic* is every run that never asked for one, and the
    answer is no rows: a mission with no critic emits exactly the stream it
    emitted before one existed.

    Every failure is swallowed into a row rather than raised.  A second
    opinion that took the mission down with it would be a control strictly
    worse than not having one: the draft exists, the mechanical verdict is
    computed, and the only thing missing is an opinion nobody is entitled to.
    """
    if critic is None:
        return []
    try:
        opinion = critic.review(
            answer, list(evidence),
            objective=objective,
            unsupported=list(unsupported),
            answered_with_caveat=answered_with_caveat,
        )
    except Exception as exc:                    # pragma: no cover - defensive
        return [{"check": "critic", "advisory": True, "configured": False,
                 "grounded": True, "verdict": "skipped", "considered": 0,
                 "minimum": 0, "unsupported": [],
                 "detail": f"the critic could not be reached: "
                           f"{type(exc).__name__}: {exc}"}]
    return [opinion.as_check()] if opinion is not None else []


#: What the model is told when the tool plane changed under it mid-run.
#:
#: Said to the model and not only announced on the wire, because the model is
#: about to be asked again with a **different catalogue** in its system turn,
#: and a prompt that quietly grew a tool between two steps is the same defect
#: as a conversation that quietly lost one: from inside the transcript it
#: reads as the harness having lied earlier.  One sentence, naming what
#: joined and what went, in the order the bus reports them.
PLANE_CHANGED = (
    "The tool plane changed: {changes}. The catalogue above has been "
    "re-rendered and this is the set you may name from the next reply on; "
    "nothing you were told earlier about the other tools has changed."
)


#: The word ``mission_finished.reason`` carries when a run was asked to stop.
#:
#: Cancellation is deliberately **not** a new ``outcome``.  A cancelled run
#: stopped without an answer, which is exactly what ``incomplete`` has always
#: meant; what ``incomplete`` was missing is *why*, and a consumer reading it
#: was told to go and look at stderr.  So the fact arrives as an OPTIONAL field
#: beside the outcome a consumer already has a sentence for, rather than as a
#: sixth word every consumer's closed set has to grow to know.
CANCELLED = "cancelled"


#: What the model is told about a call the operator cancelled before it ran.
#:
#: Said to the model rather than only recorded, because the model is about
#: to be asked again and a turn whose calls silently produced no results
#: reads, from inside the conversation, exactly like a tool plane that
#: broke.  Under the native protocol it goes back as the ``tool`` message
#: for each skipped call — every declared call has to be answered or the
#: next request is a 400 — and under the JSON protocol as the ``user`` turn
#: every other refusal takes.  See
#: :data:`core.runtime.control.WHY_NOT_MID_FLIGHT` for the call this does
#: **not** reach: one already dispatched.
CANCEL_STEP_NOTE = (
    "The operator cancelled the rest of this step. This call was NOT "
    "dispatched and nothing it would have done has happened. Decide what to "
    "do next from what you already have."
)

#: The same command, arriving too late to skip anything.
#:
#: A no-op, and said out loud anyway.  The operator asked for something and
#: the answer is that it had already happened — a fact the model is entitled
#: to, because the next turn is the one where the operator's intent still
#: applies and an unexplained silence would leave the model repeating the
#: work somebody just tried to stop.
CANCEL_STEP_LATE = (
    "The operator asked to cancel the rest of the previous step, which had "
    "already been dispatched — so nothing was skipped, and its results "
    "above stand. Take the ask as guidance for what to do next."
)


def _finished_record(*, outcome: str, steps: int, max_steps: int,
                     budget: Optional[BudgetExhausted] = None,
                     reason: str = "",
                     usage: Optional[Dict[str, Any]] = None,
                     started_at: Optional[float] = None) -> Dict[str, Any]:
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
    # `elapsed_s` — wall time from the run's first record to this one, on
    # the harness's own monotonic clock (the same one `--mission-seconds`
    # runs against). Present whenever the run knew when it started, which is
    # every run this module or the swarm starts; NOT inside `usage`, whose
    # absence means "the provider reported nothing" and must stay a statement.
    if started_at is not None:
        record["elapsed_s"] = round(max(0.0, time.monotonic() - started_at), 3)
    return record


@dataclass
class MissionCall:
    """One dispatched call inside a turn, for the turns that have several.

    Only the native protocol produces these: under the JSON protocol a
    reply is one decision, so the turn *is* the call and
    :class:`MissionStep`'s own fields say everything there is to say.  A
    model that can emit two calls in one reply cannot be described that
    way, and the honest shape is a list.

    The field names are :class:`MissionStep`'s deliberately.  The console
    prints a step's calls and a step with none through the same loop, and
    a second vocabulary for "what was called and what came back" would be
    a second thing to keep in step with the renderer.
    """

    tool: str
    arguments: Dict[str, Any] = field(default_factory=dict)
    #: The id the provider gave this call, which the result message quotes
    #: back.  Synthesized when the provider gave none — the shape requires
    #: one, and a missing id is not a reason to lose a result.
    call_id: str = ""
    #: 0-based position among the turn's **real** calls, in the order the
    #: provider returned them.  It is what rides ``tool_call.call`` and
    #: ``tool_result.call``, and a call refused before dispatch still holds
    #: its place: the ordinal describes what the model emitted, not what
    #: this loop got round to running.
    ordinal: int = 0
    exit_code: Optional[int] = None
    output: str = ""
    error: str = ""
    handle: str = ""
    truncated: bool = False

    @property
    def refused(self) -> bool:
        return self.exit_code is not None and self.exit_code != 0


@dataclass
class MissionStep:
    """One turn: what the model said, and what came back.

    **A step is a model turn**, in both protocols, and that is what
    ``--mission-steps`` counts.  It was already true of the JSON protocol
    because a turn could only be one decision; it is stated here because
    the native protocol makes it a choice, and the other choice — a step
    per dispatched call — would have made ``max_steps`` mean "tool calls"
    on one path and "round trips" on the other, silently widened a budget
    an operator set, and put two ``step_started`` records under one index.
    """

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
    #: Every call this turn made, when the turn was a native one.
    #:
    #: **Empty under the JSON protocol**, where the fields above are the
    #: whole truth and nothing about a transcript changes.  Non-empty under
    #: the native one, where those fields are left unset instead of being
    #: filled from the first call: a mirror would be a second owner of
    #: "what was called", and the day a turn's second call is the
    #: interesting one, a reader of the mirror would be reading the first.
    calls: List[MissionCall] = field(default_factory=list)

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
        and nothing called — unless a ``control`` channel is open and
        somebody answers the request while the run stands at it, which
        dispatches that one call in that one step and is still not a
        decision this harness made.

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
    protocol:
        :data:`JSON_PROTOCOL` — the default, and byte for byte the loop
        that has always run — or :data:`NATIVE_PROTOCOL`.

        Under ``native`` the loop stops reading text.  The caller's
        ``chat_fn`` is expected to have declared the offered tools plus
        :data:`ANSWER_FUNCTION` and asked for ``tool_choice="required"``
        with ``parallel_tool_calls=True``; what comes back is read from
        *tool_calls_fn* rather than parsed out of the reply.  The loop
        does not send the request and cannot check that the caller did
        this — the seam is one function wide on purpose — so the CLI
        refuses the flag at the door on a backend whose capabilities do
        not declare both, and a library caller wiring this up itself owns
        the same check.

        The rules, stated once because a protocol split across a docstring
        and a branch is a protocol that drifts:

        * exactly one :data:`ANSWER_TOOL` call and nothing else — that is
          the answer, and everything downstream (grounding, the repair
          turn, the ``answer`` record) is the JSON protocol's;
        * one or more real tool calls — each is dispatched **in the order
          the provider returned them**, each emits its own ``tool_call``
          and ``tool_result``, and the second and later ones carry a
          ``call`` ordinal beside the step's ``index``;
        * :data:`ANSWER_TOOL` *alongside* tool calls — the tools run and
          the answer is **ignored**, with a sentence saying so appended
          for the model.  Honoured only when alone, because the other
          reading (answer now, drop the calls) throws away work the model
          asked for and produces an answer written before its own
          evidence arrived;
        * a gated tool ends the turn at :data:`AWAITING_APPROVAL` on
          **that** call: the calls before it have already run and are on
          the record, the calls after it are not dispatched, and the
          ``reason`` says how many;
        * no calls at all — some servers answer in ``content`` despite
          ``required`` — is read as an answer when there is text, and
          refused as ``reply_rejected`` when there is not.
    tool_calls_fn:
        ``() -> [{"id", "name", "arguments", ["arguments_raw"]}, …]``,
        read after every ``chat_fn`` call under the native protocol: every
        call the provider returned, in provider order, cleared per call.

        A nullary callable for the reason ``usage_fn`` is one — ``chat_fn``
        returns the reply and half a dozen callers depend on that shape,
        and handing this loop the whole client to ask instead would give a
        deliberately confined loop something it could ask anything.  The
        CLI passes ``lambda: list(getattr(elf.client, "last_tool_calls",
        []) or [])`` and the seam stays one function wide.  ``None`` under
        the native protocol is a run whose every turn looks like a reply
        with no calls in it, which is a caller that wired half of this up
        and will be told so on the first turn rather than silently
        answered from prose.
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
    admits, plane_changed:
        **How a mission learns that its tool plane changed underneath it.**
        A discovered server may register a tool and notify mid-run; the
        bridge picks it up and the bus registers it, and until 0.14 the
        mission's offered set was fixed at ``__init__`` — so the model that
        named the new tool was told there is no such tool, which is the
        finding the eval harness's ``the_plane_grew_mid_run`` mission was
        written to measure.

        ``admits(grew, offered)`` answers *may these join*, and it is the
        caller's because the closed set is the manifest's: ``None`` admits
        whatever the bus grew, which is the honest default for a run that
        had no manifest and was therefore offered the whole bridge already.
        ``plane_changed(offered)`` is told the new whole list, which is how
        a native run's declared function schemas stay in step with the
        catalogue.  Neither is consulted about a tool that was on the bus
        when the run started: a closed set that left ``run_shell_command``
        out did not leave it out provisionally.

        See :meth:`_relearn_the_plane` for when it is asked, and
        :meth:`system_turn` for why the changed catalogue is a legitimately
        different prefix.
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
    control:
        A :class:`~core.runtime.control.ControlChannel` — commands coming
        *in*, where ``observer`` is records going out — or ``None``, which
        is a run nobody can steer and is what this loop was.

        Four things it can do, and each one is drained at a point this loop
        chose rather than delivered whenever it arrives.  ``inject`` puts a
        user turn in front of the next model call, and that step's
        ``step_started`` carries the text as ``injected``.  ``cancel``
        throws :attr:`cancel` from the channel's own thread, so it behaves
        exactly as the first ``SIGTERM`` does.  ``cancel_step`` skips the
        calls of the current step that have not been dispatched yet — see
        :data:`CANCEL_STEP_NOTE`, and
        :data:`core.runtime.control.WHY_NOT_MID_FLIGHT` for what it
        deliberately cannot reach.  ``gate_decision`` answers a gate **while
        the run is still standing at it**: see :meth:`_gate`.

        The channel is a transport and never a decision.  A gate answered
        through it is recorded in the same :class:`ApprovalStore` the
        ``--approval`` path reads, signed by the name the platform sent,
        and spent on the dispatch it authorised — there is still no code
        path in this module that reads a state and concludes a yes.
    gate_wait_s:
        How long a gated call waits for a ``gate_decision`` before the
        mission ends at :data:`AWAITING_APPROVAL` as it always has.
        Defaults to :data:`~core.runtime.control.GATE_WAIT_S`, and the real
        bound is that or whatever is left of ``deadline``, whichever is
        less.  A runner keyword and deliberately not a flag: it is a
        property of the *platform* holding the other end of the channel,
        which is the caller constructing this object, and a mission with no
        channel is unaffected by it either way.

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
        critic: Any = None,
        admits: Optional[Callable[[Sequence[str], Sequence[str]],
                                  Sequence[str]]] = None,
        plane_changed: Optional[Callable[[List[str]], None]] = None,
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
        tool_calls_fn: Optional[Callable[[], Any]] = None,
        protocol: str = JSON_PROTOCOL,
        rate: Optional[Rate] = None,
        ledger: Optional[Ledger] = None,
        deadline: Optional[Deadline] = None,
        cancel: Any = None,
        control: Any = None,
        gate_wait_s: float = GATE_WAIT_S,
        started_at: Optional[float] = None,
    ):
        self._chat = chat_fn
        self._bus = bus
        self._tool_names = list(tool_names)
        self._system_message = system_message
        self._max_steps = max_steps
        self._validator = validator
        #: A :class:`~core.critic.mission.MissionCritic`, or ``None``.
        #:
        #: ``None`` is the default and the whole behaviour: a mission with
        #: no critic emits exactly the stream it emitted before one existed.
        #: **Whether a run gets one is the manifest's decision** —
        #: ``grounding: critic: true`` — and it is read by the caller that
        #: already reads the manifest, so this object never learns what a
        #: skill is. Duck-typed rather than imported: `core.critic` pulls in
        #: pydantic and a transport, and a mission that is not using a
        #: critic must not pay for either.
        self._critic = critic
        #: Which names the bus grew **mid-run** this mission may add to its
        #: offered set: ``admits(grew, offered) -> names to join``.
        #:
        #: The runner asks; it never decides. A mission's closed set is the
        #: manifest's business (:meth:`core.runtime.skills.SkillManifest
        #: .admits`, which is what the CLI passes here) and this module has
        #: never known what a skill is. ``None`` is "whatever the bus grew is
        #: offered", which is the honest reading of a run with no manifest —
        #: it was already offered every tool the bridge discovered.
        #:
        #: What it can NEVER do is widen the run to something that was on the
        #: bus all along: only names absent at `run` and present now are ever
        #: put to it. See :meth:`_relearn_the_plane`.
        self._admits = admits
        #: Told when :attr:`offered` changes, with the new whole list.
        #:
        #: The seam for the native protocol, and the reason it is a callback
        #: rather than a list this object writes into: the runner owns "what
        #: is offered now" and the caller owns how a tool is *declared* to a
        #: server. The CLI re-renders its function schemas here, so a run
        #: whose plane grew declares the tool it is about to let the model
        #: name. Nothing else is entitled to fire on this.
        self._plane_changed = plane_changed
        #: What the bus had registered when this run started, or ``None``
        #: before one has. The baseline for "the plane GREW", so a tool that
        #: was on the bus and deliberately left out of the closed set can
        #: never wander into it later.
        self._plane: Optional[set] = None
        #: What changed since the last step boundary, rendered (``+mcp.x``,
        #: ``-mcp.y``) and waiting to be told to the model. Drained by
        #: :meth:`_plane_news`, which is the one place a step decides whether
        #: its system turn is the same bytes as the last one's.
        self._plane_pending: List[str] = []
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
        self._tool_calls_fn = tool_calls_fn
        if protocol not in PROTOCOLS:
            raise ValueError(
                f"protocol must be one of {', '.join(PROTOCOLS)}, got "
                f"{protocol!r}")
        self._protocol = protocol
        self._native = protocol == NATIVE_PROTOCOL
        if self._native and ANSWER_TOOL in self.offered:
            # Refused at construction, and refused rather than worked
            # around. Under `tool_choice="required"` the model's only way
            # to finish is a call to `mission_answer`, so a bus tool of
            # that name would make finishing and calling that tool the
            # same act — and renaming either one here would leave a name
            # that is right on the wire and wrong in the catalogue.
            raise ValueError(
                f"the {NATIVE_PROTOCOL} protocol finishes by calling "
                f"{ANSWER_TOOL!r}, and this mission offers a tool of that "
                f"name. Rename the tool, drop it from the mission's set, "
                f"or run with --protocol {JSON_PROTOCOL}.")
        self._rate = rate
        # Kept as "the caller's, or none": `run` makes a fresh one per run
        # when it is none, and leaves a shared one alone. A run that reset
        # a ledger it did not own would silently discard the swarm's
        # router and planner calls on the first sub-mission.
        self._shared_ledger = ledger

        self._deadline = deadline
        self._cancel = cancel
        # Commands coming IN. Drained at three points and nowhere else: the
        # step boundary, a call boundary inside a step, and a gate that is
        # waiting for somebody. A channel read anywhere the loop happened to
        # look would be an operator's instruction landing in the middle of a
        # decision the model had already made.
        self._control = control
        self._gate_wait_s = max(0.0, float(gate_wait_s))
        # The instant the MISSION began, on `time.monotonic`. A staged run
        # hands its own down so a sub-mission's `mission_finished` counts
        # from triage, not from the sub-mission; `None` means "this run's
        # own start", set in `run`.
        self._started_at = started_at
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
    def protocol(self) -> str:
        """Which protocol this loop is speaking, :data:`JSON_PROTOCOL` or
        :data:`NATIVE_PROTOCOL`.

        Readable because the caller that built the ``chat_fn`` has to
        declare the matching request, and a resume has to rebuild the
        matching messages — two decisions made outside this object about
        a fact it holds.
        """
        return self._protocol

    @property
    def store(self) -> MissionResultStore:
        """The mission's result store.  One per runner, cleared per run."""
        return self._store

    @property
    def offered(self) -> List[str]:
        """Every tool name the model may name **now**: the set, plus the store.

        ``now`` is the whole of what this property grew into.  A mission's
        set used to be fixed at construction, and a plane that changed under
        a running mission — an MCP server registering a tool and notifying,
        which the bridge picks up and the bus registers — was invisible to
        it: the model named the new tool and was told there is no such tool.
        See :meth:`_relearn_the_plane`.

        Everything that has to agree about what is offered reads THIS: the
        catalogue in the system turn, the membership check that refuses a
        name, the opening frame's ``catalogue``, and — through
        ``plane_changed`` — the function schemas a native request declares.
        """
        if self._store_tool:
            return [*self._tool_names, self._store_tool]
        return list(self._tool_names)

    # ── the plane, when it changes underneath a running mission ─────────

    def _bus_names(self) -> Optional[List[str]]:
        """What the bus has registered, or ``None`` when it cannot say.

        ``getattr`` for the reason :func:`audit_ref_of` uses one: a caller
        may hand this runner any object with ``dispatch`` and
        ``describe_tool``, and a fake bus in somebody's test suite is not
        obliged to know how to list itself.  A bus that cannot answer is a
        run whose offered set never changes, which is what every run did
        before this existed.
        """
        lister = getattr(self._bus, "list_tools", None)
        if lister is None:
            return None
        try:
            return [str(name) for name in lister()]
        except Exception:                       # pragma: no cover - defensive
            return None

    def _relearn_the_plane(self) -> List[str]:
        """Reconcile :attr:`offered` against the bus.  Returns what changed.

        Called at the three moments it can matter, and the second two are
        there because of a thread this loop does not own.  **After a
        dispatch** is when a tool like ``add_a_tool`` has just told a server
        to register something.  **At the step boundary** is where the model
        can still be TOLD, and it is a second look because the bridge
        re-lists on its own thread and the registration can land after the
        call that caused it returned.  **Before refusing a name the model
        wrote** is where the same race would otherwise cost a turn: a
        mission that looked once and never again would say "no such tool"
        about a tool that arrived while the reply was being written.

        Two directions, and they are not symmetrical:

        * a name the bus GREW joins only if ``admits`` says so, and only if
          it was not registered when this run started.  Both halves matter.
          The manifest's closed set is the whole governance story of a
          mission, and a run that widened itself by whatever a server
          decided to advertise would have no closed set at all; and the
          baseline is what stops a *local* tool the closed set deliberately
          left out — ``run_shell_command``, sitting on the bus for every
          other caller — from being read as an arrival.
        * a name the bus LOST goes, and needs nobody's permission.  There is
          no governance question in withdrawing a tool: the call would fail
          at the far end anyway, and leaving it in the catalogue spends a
          step teaching the model that.  Only names that were registered at
          the start are dropped, so a caller offering a name its bus never
          held keeps whatever it was doing.

        The ``plane_changed`` callback fires here and only here, with the
        new whole list, so the one owner of *what is offered now* is the one
        that tells everybody else.
        """
        if self._plane is None:
            return []
        registered = self._bus_names()
        if registered is None:
            return []
        now = set(registered)
        offered = set(self._tool_names)
        grew = [name for name in registered
                if name not in self._plane and name not in offered
                and name != self._store_tool]
        joined = list(grew)
        if self._admits is not None and grew:
            allowed = set(str(name) for name in
                          self._admits(grew, self.offered))
            joined = [name for name in grew if name in allowed]
        gone = [name for name in self._tool_names
                if name in self._plane and name not in now]
        self._plane = now
        if not joined and not gone:
            return []
        self._tool_names = [name for name in self._tool_names
                            if name not in gone] + joined
        changes = [f"+{name}" for name in joined] + [f"-{name}" for name in gone]
        self._plane_pending.extend(changes)
        if self._plane_changed is not None:
            try:
                self._plane_changed(self.offered)
            except Exception:                   # pragma: no cover - defensive
                # A caller's hook is not allowed to end a mission, for the
                # reason an observer is not: the run has a catalogue that is
                # right and, at worst, a declared namespace that is one tool
                # behind — a tool the model cannot call, not a wrong answer.
                pass
        return changes

    def _offers(self, name: str) -> bool:
        """Whether the model may call *name* — asked of the plane, not a list.

        The last look before a refusal.  ONE owner for the question, so the
        JSON branch and the native one cannot disagree about which names are
        real, and so that "no such tool" stays a statement about the bus
        rather than about a snapshot of it taken some steps ago.
        """
        if name in self.offered:
            return True
        self._relearn_the_plane()
        return name in self.offered

    def _plane_news(self) -> List[str]:
        """What changed since the last step boundary, and clear it."""
        news, self._plane_pending = list(self._plane_pending), []
        return news

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

    # ── asking the model ────────────────────────────────────────────────

    def _model_reply(self, messages: List[Dict[str, Any]], index: int) -> str:
        """The model's reply, whether it arrives whole or in pieces.

        ``chat_fn`` may return a ``str`` — every test in this repo, every
        library caller, and any deployment that turned streaming off —
        and the loop below is byte for byte the loop that has always run
        for those.  It may instead return an **iterator of delta frames**,
        which is the other shape
        :meth:`core.runtime.backends.base.Backend.chat` has always had,
        and then the frames are drained here: the answer's own fragments
        go out as ``answer_delta`` records as they decode, and what comes
        back is the same complete reply string the non-streamed call
        would have returned.

        Everything after this line is therefore unchanged.  ``_parse``
        reads the same object, the native branch reads the same side
        channel — ``tool_calls_fn`` is filled by the backend when the
        iterator is exhausted, which is before this returns — and the
        ``answer`` record still carries the WHOLE text and is still
        emitted, always, even when the deltas already added up to it.

        ``part`` restarts at 0 for every model call.  A step is one call,
        so a grounding repair turn — a further step, with its own
        ``index`` — streams again from part 0, and the consumer's rule of
        replacing provisional text when an ``answer`` arrives makes that
        right without anything here having to remember the last one.
        """
        got = self._chat(messages)
        if isinstance(got, str):
            return got
        if got is None or not hasattr(got, "__iter__"):
            return str(got or "")

        part = 0

        def on_delta(text: str) -> None:
            nonlocal part
            self._emit(ANSWER_DELTA, index=index, part=part, text=text)
            part += 1

        return drain_answer(got, on_delta, native=self._native,
                            answer_tool=ANSWER_TOOL)

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

        **THE ORDER IS THE POINT, AND IT IS MOST-CONSTANT-FIRST.**  A
        served endpoint (vLLM, TRT-LLM) caches the KV of a prompt's
        *prefix* and reuses it for the next request that begins with the
        same bytes.  This harness re-sends the whole system turn on every
        step of every mission, so the longest byte-stable prefix is the
        cheapest thing available and it costs nothing but discipline:

        1. the **persona**, and behind it the skill's operational prose —
           one deployment, one string, the same for every mission it ever
           runs, and the same for every sub-mission of a staged one (the
           executor's extra paragraph is appended, not prepended, by
           :meth:`~core.runtime.swarm.SwarmRunner._execute_step`);
        2. the **protocol** — a module constant, the same for every run of
           every version of this package;
        3. the **catalogue** — the same for every step of one mission, and
           different the moment a mission is offered a different tool set,
           which is why it is last of the three.  It also has to follow the
           protocol, whose text says "the catalogue below";
        4. the seeded ``--history`` turns, then the objective, which is
           where this turn stops being like the last one.

        Everything the step produces goes strictly **after** the objective:
        the loop appends, and :meth:`_fit`'s compaction notice is inserted
        after the pinned prefix that this method defines.  A notice, a
        resumption sentence or a timestamp placed above the objective would
        move the bytes under the cache on every single step, which is the
        one way to make the whole arrangement worth nothing.

        Nothing here is run-specific and nothing here is a clock: no run
        id, no ``audit_ref``, no sandbox name, no date.  Two runs of the
        same mission against the same bus produce byte-identical messages
        up to and including the objective, and there is a test that says so.
        """
        return [
            self.system_turn(),
            *(dict(turn) for turn in self._history),
            {"role": "user", "content": objective},
        ]

    def system_turn(self) -> Dict[str, str]:
        """The system message, rendered from what is offered NOW.

        One owner, and it has two callers for a reason that is the whole of
        the byte-stability argument above: :meth:`seed` builds it once at the
        start of a run, and :meth:`_loop` builds it AGAIN — replacing
        ``messages[0]`` in place — on the one kind of step whose prefix is
        legitimately different from the last one's, the step after the tool
        plane changed.

        **A changed catalogue is a different prefix, and that is correct.**
        The rule was never "the bytes never move"; it is "the bytes never
        move for a reason nobody can point at".  A prefix that shifted
        because a server registered a tool costs one cache miss and buys a
        model that can name the tool; a prefix that shifted because a
        timestamp was rendered into it costs a cache miss per step and buys
        nothing.  Every other step re-renders to the same bytes, because
        every input to this method is the same as it was.
        """
        return {"role": "system", "content": stacked(
            self._system_message,
            self._protocol_text(),
            "Tool catalogue:\n" + self.catalogue(),
        )}

    def _protocol_text(self) -> str:
        """The instruction half of whichever protocol is running.

        One function so the branch that reads a reply and the sentence
        that asked for it cannot disagree: a native run told to answer in
        JSON would spend its budget writing objects nothing parses, and a
        JSON run told to call ``mission_answer`` would name a tool the
        catalogue does not list.
        """
        return (NATIVE_PROTOCOL_TEXT.strip() if self._native
                else PROTOCOL.strip())

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

    def _compaction_note(self, dropped_turns: int, freed_chars: int,
                         dropped_results: int = 0) -> str:
        """The default notice, plus where the dropped bytes still are.

        The generic sentence says the work was done and the paste was
        removed.  Only the runner knows the store's name, and naming it
        here is the same teaching move as
        :meth:`_say_it_is_unchanged`: the moment the model loses a result
        from the transcript is the moment to tell it that the result is
        still addressable, because a rule stated 2,000 tokens upstream in
        a persona does not survive to the turn it binds.

        *dropped_results* is how many of the dropped turns were tool round
        trips, which is the window's count and the reason the policy
        prefers them: they are the only kind of message in this
        conversation that is **also somewhere else**.  The pointer is the
        store's own index rather than a handle range, and that is
        deliberate.  Numbering the handles from the outside would mean
        counting round trips and assuming each one stored a result — and a
        refused reply is a round trip that stored nothing, so the first
        rejected tool name would slide every later handle by one and hand
        the model a confident, wrong ``r5``.  ``{tool}()`` with no handle
        lists exactly what the store holds, which cannot be wrong.
        """
        note = default_compaction_note(dropped_turns, freed_chars,
                                       dropped_results)
        if not self._store_tool:
            return note
        gone = (f" The results whose text was removed here are still in that "
                f"store: call {self._store_tool}() with no handle for the "
                f"list of everything this mission has stored."
                if dropped_results else "")
        return (
            f"{note} Every result of this mission is still readable: call "
            f'{self._store_tool}(handle="…", path="…") with the handle you '
            f"were given when it arrived.{gone}"
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
        kept, compaction = self._window.fit(
            messages, pinned=self.pinned, note=self._compaction_note,
        )
        if compaction is None:
            return kept, compaction
        return self._heal_native(kept), compaction

    @staticmethod
    def _heal_native(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Drop ``tool`` messages whose call is no longer in the list.

        A compaction drops oldest-first and the window already refuses to
        leave a tail starting with anything but the model's own turn, so
        this is the last edge of that rule rather than a second copy of
        it: when the tail has been cut to its floor, a result message can
        survive the call it answers.  Under the JSON protocol that is a
        stray user turn and reads oddly; under the native one it is a
        **400** — an OpenAI-shaped request may not carry a ``tool``
        message that answers no ``tool_calls`` — and a mission that dies
        of its own compaction is a worse failure than a shorter prompt.

        Here and not in :class:`~core.runtime.context_window.MissionWindow`
        because the window bounds a conversation and knows nothing about
        which protocol shaped it; what a valid request looks like belongs
        to the loop that builds one.  A list with nothing to heal comes
        back unchanged, which is every JSON-protocol run.
        """
        healed: List[Dict[str, Any]] = []
        answerable: set = set()
        for message in messages:
            role = message.get("role")
            if role == "assistant":
                answerable = {
                    str(call.get("id") or "")
                    for call in (message.get("tool_calls") or [])
                }
            elif role == "tool":
                if str(message.get("tool_call_id") or "") not in answerable:
                    continue
            elif role in ("user", "system"):
                answerable = set()
            healed.append(message)
        return healed

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
        if self._started_at is None:
            self._started_at = time.monotonic()
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
        # The baseline for "the plane grew", taken AFTER the store tool is on
        # the bus so the mission's own descriptor is never read as an
        # arrival. Everything registered at this instant — every local tool
        # the closed set left out included — is what this run was offered a
        # subset of, and only what appears later is ever put to `admits`.
        self._plane = set(self._bus_names() or ())
        self._plane_pending = []
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
                       **_protocol_field(self._protocol),
                       **_profile_field(self._bus))
        try:
            return self._loop(objective, transcript, resumption)
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
                usage=transcript.usage.as_record(self._rate),
                started_at=self._started_at))

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
        self, objective: str, transcript: MissionTranscript,
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
            # Looked at again here, and not only after the dispatch that
            # caused it: the bridge re-lists on ITS OWN THREAD when a server
            # notifies, so the registration can land a few milliseconds
            # after the call that triggered it returned. Asking once more at
            # the boundary is what makes the model TOLD about a new tool
            # rather than left to name it and find out — measured on the
            # stub plane, where `add_a_tool` can and does return before the
            # re-list has completed. Which boundary catches it is the
            # bridge's timing; that one of them does is this loop's job.
            self._relearn_the_plane()
            # The step boundary is where a changed plane is ANNOUNCED — the
            # change itself was noticed at the dispatch that caused it. Here
            # rather than there because both halves of the announcement are
            # about the next model call: the system turn is re-rendered from
            # the new catalogue, and the note goes at the END of the
            # conversation, after every tool message the last turn produced.
            # Under the native protocol a `user` turn dropped between two
            # `tool` messages is a 400, and one after all of them is not.
            changed = self._plane_news()
            if changed:
                messages[0] = self.system_turn()
                self._say(messages,
                          PLANE_CHANGED.format(changes=", ".join(changed)))
            # Immediately before the ask and after the stop check, which is
            # the one moment an operator's instruction can reach the model
            # without arriving in the middle of a decision it had already
            # made. A cancellation sent on the same channel was applied by
            # the channel's own thread and was caught by `_stop` above.
            injected = self._steer(messages)
            # Before the ask, not after the reply: what is compacted is
            # what this step is about to send, and a watcher told about it
            # afterwards has already rendered the turn it applied to.
            messages, compacted = self._fit(messages)
            # `catalogue` on the steps where it CHANGED and no other, so a
            # watcher that has never heard of the field reads the stream it
            # always read, and one that has can tell the plane it is looking
            # at from the one the opening frame named. The whole new list,
            # not a delta: a consumer holding a set should be able to
            # replace it rather than apply arithmetic to it.
            self._emit(STEP_STARTED, index=index, **opening,
                       **({"catalogue": self.offered} if changed else {}),
                       **({"injected": injected} if injected else {}),
                       **({"compacted": compacted.as_record()}
                          if compacted is not None else {}))
            opening = {}
            reply = self._model_reply(messages, index)
            # Read here and used below: whichever record this step emits
            # carries the cost of the call that produced it. One read per
            # call, because `last_usage` is a side channel that the NEXT
            # call clears.
            spent = self._spent(transcript)
            step = MissionStep(index=index, raw_reply=reply)

            if self._native:
                # The whole of the other protocol, in one branch and one
                # method. Everything it decides — an answer, a gate, a stop
                # — is decided by the same helpers the lines below use, so
                # there is one owner for what a dispatch emits and one for
                # what an answer is worth.
                done, repairs = self._native_turn(
                    objective, index, reply, spent, step,
                    messages, transcript, repairs)
                if done is not None:
                    return done
                continue

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
                done, repairs = self._answered(
                    str(decision["answer"]), index, step, spent, messages,
                    transcript, repairs)
                if done is not None:
                    return done
                continue

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

            # `_offers` and not `name in offered`: the bus is the authority
            # on what exists, and it is asked again before a refusal.
            if not self._offers(name):
                problem = self._no_such_tool(name, self.offered)
                step.error = problem
                transcript.steps.append(step)
                self._emit(REPLY_REJECTED, index=index, tool=name,
                           problem=problem, **spent)
                messages.append({"role": "user", "content": problem})
                continue

            if name in self._gated:
                # `None` back means the gate was ANSWERED on the control
                # channel while the run stood at it — the call was
                # dispatched, or it was refused and said so — and this turn
                # carries on with the step that already happened.
                stopped = self._gate(objective, index, name, arguments, step,
                                     transcript, messages=messages,
                                     spent=spent)
                if stopped is not None:
                    return stopped
                transcript.steps.append(step)
                continue

            # The tool's own schema, on the way out. AFTER the gate, so a
            # gated call is still proposed exactly as written — what a
            # person approves has to be the bytes the model wrote, whatever
            # this would have said about them — and before the dispatch,
            # because the point is not to make the call.
            problem = self._schema_violation(name, arguments)
            if problem:
                step.error = problem
                transcript.steps.append(step)
                self._emit(REPLY_REJECTED, index=index, tool=name,
                           problem=problem, **spent)
                messages.append({"role": "user", "content": problem})
                continue

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

            # The last boundary before the call is made, and the only place
            # `cancel_step` can act under this protocol: a turn is one
            # decision here, so "the rest of this step" is exactly this
            # dispatch. After it, the tool is the bus's and not this loop's.
            if self._cancel_step_asked():
                step.error = CANCEL_STEP_NOTE
                self._say(messages, CANCEL_STEP_NOTE)
                transcript.steps.append(step)
                continue

            self._dispatch(step, index, spent, messages)
            transcript.steps.append(step)

        transcript.outcome = "budget_exhausted"
        # Which budget, with the numbers. `steps` and not `seconds`: the
        # `for` ran to its end, so the clock — if there was one — still had
        # room, and a consumer told "budget_exhausted" and nothing else
        # cannot tell a mission that needed more turns from one that needed
        # a faster endpoint.
        transcript.budget = BudgetExhausted(
            "steps", self._max_steps, len(transcript.steps))
        return transcript

    # ── the pieces both protocols are made of ───────────────────────────

    def _say(self, messages: List[Dict[str, Any]], text: str,
             call_id: str = "") -> None:
        """Append what the loop is telling the model, in this protocol's shape.

        A ``user`` turn under the JSON protocol, which is what every one of
        these was until now and is byte for byte what it still is.  A
        ``tool`` message quoting the call it answers under the native one,
        because that is not a preference: an assistant turn that declared
        ``tool_calls`` and is followed by a ``user`` message is a **400**
        from an OpenAI-shaped server, and every declared call has to be
        answered — including the ones this loop refused, which is why the
        refusals go through here too rather than being written inline.
        """
        if self._native and call_id:
            messages.append({"role": "tool", "tool_call_id": call_id,
                             "content": text})
            return
        messages.append({"role": "user", "content": text})

    def _schema_violation(self, name: str, arguments: Dict[str, Any]) -> str:
        """What is wrong with *arguments* against the tool's own schema, or ``""``.

        The schema comes off :meth:`~core.tools.bus.ToolBus.describe_tool`
        — the same place the catalogue's argument summary comes from and
        the same place a native request's ``parameters`` come from — so the
        prompt, the wire and this check cannot describe one tool three
        ways.  A bus that cannot describe the tool checks nothing: the
        dispatch below is about to fail on its own, and inventing a refusal
        here would hide why.

        Read :mod:`core.runtime.schema_check` for what this does and does
        not catch.  It is worth stating in one line at the call site: it
        catches a *shape* the tool declared, and it does not catch a
        well-typed argument meant for a different tool.
        """
        try:
            info = self._bus.describe_tool(name)
        except Exception:                       # pragma: no cover - defensive
            return ""
        if not isinstance(info, dict) or "error" in info:
            return ""
        return check_arguments(name, info.get("input_schema"), arguments)

    def _dispatch(self, slot: Any, index: int, spent: Dict[str, Any],
                  messages: List[Dict[str, Any]]) -> None:
        """Call one tool and tell everyone what happened.

        *slot* is whatever carries this call: the :class:`MissionStep`
        itself under the JSON protocol, where a turn is a call, and a
        :class:`MissionCall` under the native one, where it is one of
        several.  The two share their field names precisely so this method
        can be the single owner of "what a dispatch does" — the alternative
        is a second copy of ten lines that emit records, and the swarm's
        six-of-ten grounding fields are what a second copy looks like a
        month later.
        """
        name = str(slot.tool or "")
        arguments = dict(slot.arguments)
        # The ordinal is ABSENT on the first call of a turn and on every
        # call of a JSON-protocol run, so a consumer that has never heard
        # of it reads exactly the stream it read before.
        ordinal = {"call": slot.ordinal} if getattr(slot, "ordinal", 0) else {}
        self._emit(TOOL_CALL, index=index, tool=name,
                   arguments=dict(arguments), **ordinal, **spent)
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
        slot.exit_code = result.exit_code
        slot.output = result.stdout
        slot.error = result.stderr
        stored = self._store.record(
            name, arguments,
            text=result.stdout,
            evidence=getattr(result, "evidence", "") or "",
            exit_code=result.exit_code,
        )
        slot.handle = stored.handle
        rendered, slot.truncated = self._render_result(
            name, result, stored.handle,
            already=self._store.first_identical(stored),
        )
        # The WHOLE result, not the bounded rendering. The bound exists
        # because a model's context is finite; a watcher's is not, and a
        # pane showing an analyst 60% of a governed listing because the
        # model could only be shown that much would be inventing a limit
        # nobody imposed.
        self._emit(TOOL_RESULT, index=index, tool=name,
                   arguments=dict(arguments),
                   ok=result.exit_code == 0, exit_code=result.exit_code,
                   output=result.stdout or "", error=result.stderr or "",
                   handle=stored.handle, truncated=slot.truncated, **ordinal)
        self._say(messages, rendered, getattr(slot, "call_id", ""))
        # The moment a plane can have changed: a dispatch is the only thing
        # this loop does that a server can watch, and `add_a_tool`-shaped
        # tools exist. Noticed here, announced at the next step boundary —
        # see `_relearn_the_plane` and the `_plane_news` block in `_loop`.
        self._relearn_the_plane()

    def _answered(self, answer: str, index: int, step: MissionStep,
                  spent: Dict[str, Any], messages: List[Dict[str, Any]],
                  transcript: MissionTranscript, repairs: int,
                  call_id: str = "") -> Tuple[Optional[MissionTranscript], int]:
        """The answer path, for whichever protocol produced the text.

        ``(transcript to return, repairs)`` — the first is ``None`` when
        the loop should carry on, which is the grounding repair turn and
        nothing else.

        One method rather than one per protocol.  What an answer is worth
        — whether it is grounded, whether a repair turn is spent, what
        ``grounding`` and ``answer`` carry and in which order — is a
        property of the mission and not of how the text arrived, and a
        native run whose caveat path drifted from the JSON one would be
        two agents wearing one name.
        """
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
                self._say(messages, problem, call_id)
                return None, repairs
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
                marked, repairs=repairs, caveat=caveat,
                opinions=self._second_opinion(
                    transcript.objective, answer, marked,
                    answered_with_caveat=True)))
            self._emit(ANSWER, text=transcript.answer,
                       outcome=transcript.outcome, **spent)
            return transcript, repairs

        if report is not None:
            transcript.grounding = GroundingReport(
                results=report.results, repairs=repairs,
            )
            self._emit(GROUNDING, **_grounding_record(
                transcript.grounding, repairs=repairs,
                # Asked here too, and on this path it declines: no rule in
                # `core.critic.triggers` fires on a clean answer, and the
                # call is made anyway so that the decision has ONE owner.
                # A branch that skipped asking would be a second copy of
                # the trigger policy, written in `if`s.
                opinions=self._second_opinion(
                    transcript.objective, answer, transcript.grounding,
                    answered_with_caveat=False)))
        transcript.answer = answer
        transcript.outcome = "answered"
        transcript.steps.append(step)
        self._emit(ANSWER, text=answer, outcome=transcript.outcome, **spent)
        return transcript, repairs

    def _second_opinion(self, objective: str, answer: str,
                        report: GroundingReport, *,
                        answered_with_caveat: bool,
                        ) -> List[Dict[str, Any]]:
        """This run's evidence, put to :func:`second_opinion`.

        A thin call and deliberately thin: what a critic row looks like is
        the module function's, shared with the staged path, and what THIS
        object contributes is the only thing the staged path cannot — the
        evidence its own result store holds.

        It runs **before** the ``answer`` record, like the grounding verdict
        it sits beside, so a consumer framing the prose has the whole
        verdict before the prose arrives.  Under streaming the text has
        already gone out as ``answer_delta`` fragments, so what this delays
        is the authoritative record and not the reader's first sight of the
        answer.
        """
        return second_opinion(
            self._critic, objective, answer, self._store.evidence_texts(),
            unsupported=report.unsupported,
            answered_with_caveat=answered_with_caveat)

    def _gate(self, objective: str, index: int, name: str,
              arguments: Dict[str, Any], step: MissionStep,
              transcript: MissionTranscript, *, skipped: int = 0,
              call: Optional[MissionCall] = None,
              messages: Optional[List[Dict[str, Any]]] = None,
              spent: Optional[Dict[str, Any]] = None,
              ) -> Optional[MissionTranscript]:
        """STOP, write the proposal down — and, if anybody is listening, wait.

        ``None`` back means the gate was **answered in this turn** and the
        loop should carry on: a yes was recorded and the one call it
        authorised has been dispatched, or a no was recorded and the model
        has been told.  A transcript back is the behaviour this method has
        always had — the mission ends here holding the exact call it
        proposed, and somebody who is not this process decides later.

        **Waiting is what a control channel buys**, and it buys nothing
        else here.  Without one — the default, and every run before this
        parameter existed — the call is not dispatched, not retried and not
        handed back to the model to work around.  With one, the ask is
        still written down first, the ``gate_requested`` record still goes
        out first, and only then does the runner wait: what arrives is a
        decision somebody *sent*, recorded through the same
        :class:`ApprovalStore` the ``--approval`` path reads and signed
        with the name that platform put on it.  Nothing here reads a state
        and concludes a yes; nothing here times out into one either — the
        wait running out is exactly the :data:`AWAITING_APPROVAL` a run
        without a channel would have reached, with the record left
        ``pending`` for ``--approval`` on a later turn.

        *skipped* is how many further calls the same reply asked for and
        did **not** get: only the native protocol can produce more than
        one, and a person reading "the mission stopped here" is entitled
        to know that two other calls the model wanted were dropped with
        it rather than run behind the gate's back.  Zero adds no words, so
        a JSON-protocol gate says exactly what it always said — and where
        a decision may arrive in-turn the sentence says *held* rather than
        *not dispatched*, because on a yes those later calls do run.
        """
        waiting = self._can_wait_for_a_decision()
        reason = (
            f"{name} needs a person's approval on this deployment. It "
            f"has been proposed exactly as written and NOT called. "
            f"Nothing further happens on this mission until somebody "
            f"decides.")
        if skipped:
            plural = "" if skipped == 1 else "s"
            reason = (
                f"{reason} The {skipped} later call{plural} in the same "
                f"reply {'is' if skipped == 1 else 'are'} HELD: "
                f"{'it runs' if skipped == 1 else 'they run'} only if this "
                f"is approved and the mission carries on."
                if waiting else
                f"{reason} The {skipped} later call{plural} in the same "
                f"reply {'was' if skipped == 1 else 'were'} NOT dispatched "
                f"either.")
        if waiting:
            reason = (
                f"{reason} A decision sent on this run's control channel is "
                f"honoured while the run stands here.")
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
        # BEFORE the wait, and that is the whole ordering: the platform
        # cannot answer a request it has not been shown, and this record is
        # what shows it — carrying the `approval_id` the decision has to
        # quote back.
        self._emit(GATE_REQUESTED, index=index, tool=name,
                   arguments=dict(arguments), reason=reason, **carried)

        if waiting and approval_id:
            decision = self._control.wait_for(
                lambda command: (
                    command.get("control") == GATE_DECISION
                    and command.get("approval_id") == approval_id),
                self._gate_window())
            if decision is not None:
                approved, trouble = self._record_decision(
                    approval_id, decision)
                if not trouble:
                    return self._answered_gate(
                        approved, decision, index, name, step, call,
                        messages if messages is not None else [],
                        dict(spent or {}))
                # Fail closed and say so. A decision that could not be
                # recorded is not a decision: the call is not made, and the
                # mission stops where it would have stopped anyway.
                reason = f"{reason} {trouble}"

        # On the CALL when there is one, and on the step otherwise. A
        # native turn's problems belong to the call that had them — the
        # step is the turn, and a turn with three calls has no single
        # error — while a JSON turn is its call and keeps the field a
        # transcript reader has always read.
        if call is not None:
            call.error = reason
        else:
            step.error = reason
        transcript.steps.append(step)
        transcript.outcome = AWAITING_APPROVAL
        transcript.awaiting = {"tool": name,
                               "arguments": dict(arguments),
                               **carried}
        return transcript

    # ── a gate somebody answers while the run is still standing at it ───

    def _can_wait_for_a_decision(self) -> bool:
        """Whether this gate has anybody to wait for.

        All three have to be true.  A channel, or there is nowhere for a
        decision to arrive from; a **store**, or there is nothing to record
        it in and no id to address it to — and an unrecorded yes is the
        standing permission :mod:`core.runtime.approvals` exists not to
        have; and a window greater than zero, which is how a caller turns
        the whole behaviour off without taking the channel away.
        """
        return (self._control is not None and self._approvals is not None
                and self._gate_wait_s > 0)

    def _gate_window(self) -> float:
        """``min(what the caller allows, what is left of the clock)``.

        The deadline wins where it is shorter, because a run that waited
        five minutes for a person and then reported that it had run out of
        seconds would have spent the operator's whole budget standing
        still.  Negative remaining floors at zero — :meth:`wait_for
        <core.runtime.control.ControlChannel.wait_for>` returns at once,
        which is the honest reading of a clock that is already past.
        """
        window = self._gate_wait_s
        remaining = (self._deadline.remaining()
                     if self._deadline is not None else None)
        if remaining is not None:
            window = min(window, max(0.0, remaining))
        return window

    def _record_decision(self, approval_id: str,
                         decision: Dict[str, Any]) -> Tuple[bool, str]:
        """``(approved, trouble)`` — write somebody's answer down.

        Through :meth:`ApprovalStore.decide
        <core.runtime.approvals.ApprovalStore.decide>` and then
        :meth:`consume <core.runtime.approvals.ApprovalStore.consume>`, the
        same two calls the ``--approval`` path makes one process later, so
        a gate answered in-turn and a gate answered tomorrow leave the same
        record: ``spent``, by the named decider, at a recorded time.  The
        decision is the *platform's*; this is the bookkeeping.

        Any refusal from the store — the record was already answered out of
        band, the directory went read-only — is **trouble**, never a
        dispatch.  Failing closed is the only direction a gate may fail in,
        and the sentence names the store's own complaint so an operator is
        not left guessing which of the two halves refused.
        """
        approve = bool(decision.get("approve"))
        try:
            self._approvals.decide(
                approval_id, approve=approve,
                decided_by=str(decision.get("decided_by") or ""),
                note=str(decision.get("note") or ""))
        except (ApprovalError, OSError) as exc:
            return False, (
                f"A decision arrived on the control channel and could NOT "
                f"be recorded ({exc}) — so it is not a decision, and the "
                f"call was not made.")
        if not approve:
            return False, ""
        try:
            self._approvals.consume(approval_id)
        except (ApprovalError, OSError) as exc:
            return False, (
                f"The approval was recorded and could NOT be spent ({exc}), "
                f"so the call was NOT made. Nothing here proceeds on a "
                f"decision it cannot account for.")
        return True, ""

    def _answered_gate(self, approved: bool, decision: Dict[str, Any],
                       index: int, name: str, step: MissionStep,
                       call: Optional[MissionCall],
                       messages: List[Dict[str, Any]],
                       spent: Dict[str, Any]) -> None:
        """Carry out a decision that arrived in time.  Always ``None``.

        ``None`` is the caller's signal to carry on, and both outcomes are
        that: an approved call is dispatched **now**, in this step, under
        this ``index``, so a consumer sees the ``tool_call`` it asked about
        following the ``gate_requested`` that asked; a refused one tells the
        model, in the shape its protocol requires, and the loop asks again.

        The approved call is dispatched **exactly as proposed** and is not
        put through :meth:`_schema_violation` on the way.  What a person
        approves has to be the bytes that run — a harness that refused a
        call somebody had just said yes to would be answering a gate it did
        not open, and the tool's own refusal is the honest place for a
        malformed argument to land.
        """
        who = str(decision.get("decided_by") or "")
        slot = call if call is not None else step
        if approved:
            self._dispatch(slot, index, spent, messages)
            return None
        note = str(decision.get("note") or "").strip()
        refusal = (
            f"{name} was REFUSED by {who}"
            + (f": {note}" if note else ".")
            + f" The call was not made and will not be. Do not propose it "
              f"again; answer with what you have, or find another way.")
        slot.error = refusal
        self._say(messages, refusal, getattr(slot, "call_id", ""))
        return None

    # ── the native protocol ─────────────────────────────────────────────

    def _read_tool_calls(self, index: int) -> List[Dict[str, Any]]:
        """This turn's calls off the side channel, normalized.

        Never raises, for the reason :meth:`_spent` does not: a side
        channel that throws must not be able to end a mission, and a turn
        with no readable calls is handled below as a turn with no calls —
        which is a case the protocol has to have anyway, because a server
        may answer in ``content`` despite ``tool_choice="required"``.

        Every id is filled in here, once, so that the assistant turn and
        the result messages that quote it cannot disagree: a provider that
        gave no id gets one made of the step and the position, which is
        unique inside a conversation and stable across a re-render.
        """
        try:
            raw = (self._tool_calls_fn()
                   if self._tool_calls_fn is not None else None)
        except Exception:                       # pragma: no cover - defensive
            raw = None
        calls: List[Dict[str, Any]] = []
        for position, entry in enumerate(list(raw or ())):
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name") or "").strip()
            if not name:
                continue
            arguments = entry.get("arguments")
            calls.append({
                "id": str(entry.get("id") or "") or f"call_{index}_{position}",
                "name": name,
                "arguments": dict(arguments) if isinstance(arguments, dict)
                else {},
                # Kept verbatim when the backend has it: what goes back to
                # the model as its own turn should be what the model
                # emitted, down to the key order, and a re-serialization is
                # a paraphrase of the model to itself.
                "raw": entry.get("arguments_raw"),
                "shaped": isinstance(arguments, dict) or arguments is None,
            })
        return calls

    @staticmethod
    def _assistant_turn(reply: str,
                        calls: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        """The model's own turn, in the shape a server will take back.

        ``content`` and ``tool_calls`` together, because a harmony model
        emits both — the reasoning-flavoured preamble and the call — and a
        turn that dropped the text would hand the model back a version of
        itself that never explained anything.  No ``tool_calls`` key at all
        when there were none: an empty list is a different thing to some
        servers, and this is the shape a reply with no calls in it takes.
        """
        message: Dict[str, Any] = {"role": "assistant", "content": reply}
        if calls:
            message["tool_calls"] = [
                {"id": call["id"], "type": "function",
                 "function": {
                     "name": call["name"],
                     "arguments": (call["raw"]
                                   if isinstance(call["raw"], str)
                                   else json.dumps(call["arguments"],
                                                   ensure_ascii=False)),
                 }}
                for call in calls
            ]
        return message

    def _native_turn(
        self, objective: str, index: int, reply: str,
        spent: Dict[str, Any], step: MissionStep,
        messages: List[Dict[str, Any]], transcript: MissionTranscript,
        repairs: int,
    ) -> Tuple[Optional[MissionTranscript], int]:
        """One native turn: read the calls, run them, or answer.

        ``(transcript to return, repairs)``, with ``None`` meaning carry
        on — the same shape :meth:`_answered` returns and for the same
        reason.

        The rules are the class docstring's ``protocol`` paragraph, and
        this is the only place they are implemented.
        """
        calls = self._read_tool_calls(index)
        messages.append(self._assistant_turn(reply, calls))
        answers = [call for call in calls if call["name"] == ANSWER_TOOL]
        wanted = [call for call in calls if call["name"] != ANSWER_TOOL]

        # `usage` rides the FIRST record this turn emits and no other.
        # It is the cost of one model call, and a turn that made three
        # dispatches did not pay for the call three times — a consumer
        # summing the per-record field would report a run at triple what
        # it cost.
        pending = dict(spent)

        def cost() -> Dict[str, Any]:
            taken = dict(pending)
            pending.clear()
            return taken

        def reject(problem: str, call_id: str = "", tool: str = "") -> None:
            self._emit(REPLY_REJECTED, index=index, problem=problem,
                       **({"tool": tool} if tool else {}), **cost())
            self._say(messages, problem, call_id)

        if not calls:
            # Some servers answer in prose despite `tool_choice="required"`,
            # and prose that says something is an answer: refusing it would
            # spend a turn asking again for text already written. Prose that
            # says nothing is the one case with nothing to salvage.
            text = reply.strip()
            if text:
                return self._answered(text, index, step, cost(), messages,
                                      transcript, repairs)
            problem = (
                f"That reply carried no function call and no text. Every "
                f"reply must call one of the declared functions; call "
                f"{ANSWER_TOOL}(text=\"…\") when you are ready to finish.")
            step.error = problem
            transcript.steps.append(step)
            reject(problem)
            return None, repairs

        if answers and not wanted:
            if len(answers) > 1:
                problem = (
                    f"You called {ANSWER_TOOL} {len(answers)} times in one "
                    f"reply. An answer is one thing: call it once, alone, "
                    f"with the whole of what you want to say.")
                step.error = problem
                transcript.steps.append(step)
                for call in answers:
                    reject(problem, call["id"], ANSWER_TOOL)
                return None, repairs
            call = answers[0]
            problem = (
                "" if call["shaped"] else
                f"{ANSWER_TOOL} was called with arguments that are not a "
                f"JSON object.")
            problem = problem or check_arguments(
                ANSWER_TOOL, ANSWER_FUNCTION["function"]["parameters"],
                call["arguments"])
            if problem:
                step.error = problem
                transcript.steps.append(step)
                reject(problem, call["id"], ANSWER_TOOL)
                return None, repairs
            return self._answered(
                str(call["arguments"]["text"]), index, step, cost(), messages,
                transcript, repairs, call_id=call["id"])

        # Set the moment the operator asks, and never cleared inside this
        # turn: "cancel the rest of this step" means the rest of it, not
        # the next call only. It dies with the turn, because the next step
        # is a decision the model has not made yet.
        cancel_step = False

        for ordinal, entry in enumerate(wanted):
            name = entry["name"]
            arguments = entry["arguments"]
            # The call boundary this protocol has and the JSON one does
            # not: a turn may carry several calls, and the operator gets to
            # stop the ones that have not gone out. Asked before anything
            # else about this call, so a `cancel_step` sent while the
            # previous call was in flight catches this one.
            if cancel_step or self._cancel_step_asked():
                cancel_step = True
                step.calls.append(MissionCall(
                    tool=name, arguments=dict(arguments),
                    call_id=entry["id"], ordinal=ordinal,
                    error=CANCEL_STEP_NOTE))
                # Every declared call has to be answered or the next
                # request is a 400 — including the ones nobody ran.
                self._say(messages, CANCEL_STEP_NOTE, entry["id"])
                continue
            if not entry["shaped"]:
                problem = (
                    f"{name} was called with arguments that are not a JSON "
                    f"object. Call it again with an object of the arguments "
                    f"it declares.")
                step.calls.append(MissionCall(
                    tool=name, arguments=dict(arguments),
                    call_id=entry["id"], ordinal=ordinal, error=problem))
                reject(problem, entry["id"], name)
                continue
            if not self._offers(name):
                # Unreachable through a decoder constrained to the declared
                # namespace, which is the point of the protocol — and kept
                # anyway, because the constraint is the SERVER's promise and
                # a mission must not crash on a server that broke it. It is
                # also where a plane that grew a moment ago is picked up:
                # `_offers` asks the bus before it refuses, so a tool the
                # bridge registered while the model was writing is dispatched
                # rather than denied.
                problem = self._no_such_tool(name, self.offered)
                step.calls.append(MissionCall(
                    tool=name, arguments=dict(arguments),
                    call_id=entry["id"], ordinal=ordinal, error=problem))
                reject(problem, entry["id"], name)
                continue
            call = MissionCall(tool=name, arguments=dict(arguments),
                               call_id=entry["id"], ordinal=ordinal)
            step.calls.append(call)
            if name in self._gated:
                # The turn ends HERE, on this call — unless somebody
                # answers the gate on the control channel while it stands,
                # in which case `_gate` dispatches (or refuses) this one
                # call and hands back `None`, and the calls after it run in
                # their turn. The ones before it have already run and are
                # on the record; the ones after it are not dispatched if
                # the mission stops, and the reason says how many.
                stopped = self._gate(
                    objective, index, name, arguments, step, transcript,
                    skipped=len(wanted) - ordinal - 1, call=call,
                    messages=messages, spent=cost())
                if stopped is not None:
                    return stopped, repairs
                continue
            problem = self._schema_violation(name, arguments)
            if problem:
                call.error = problem
                reject(problem, entry["id"], name)
                continue
            stop = self._stop()
            if stop is not None:
                call.error = self._no_time_to_call(name, stop)
                transcript.steps.append(step)
                return self._stopped(transcript, stop), repairs
            self._dispatch(call, index, cost(), messages)

        # Last, so the model reads its results before it reads the note,
        # and only ever as a note: the tools ran, so the reply was not
        # wasted, and the answer it wrote before seeing them is exactly the
        # answer that should not stand.
        for entry in answers:
            self._say(messages,
                      f"{ANSWER_TOOL} was IGNORED: you called it alongside "
                      f"tool calls, so the tools ran and the answer did not. "
                      f"Answer when you have the results — call "
                      f"{ANSWER_TOOL} alone.",
                      entry["id"])
        transcript.steps.append(step)
        return None, repairs

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

    # ── being steered from outside ──────────────────────────────────────

    def _steer(self, messages: List[Dict[str, Any]]) -> List[str]:
        """Take the step boundary's commands off the channel.  Returns the
        injected texts, in the order they were sent.

        The **only** place an ``inject`` is applied, and the reason is the
        one thing that makes injection safe: here, the model has just
        finished a turn and has not begun the next one, so an operator's
        instruction is a message in a conversation rather than an edit to a
        decision already taken.  A channel read after the reply and before
        the dispatch would put "look at the second corpus" between the
        model choosing the first and the tool fetching it.

        The texts come back rather than being emitted from inside, because
        they ride ``step_started`` — one record, one emitter, and a field
        added by a second one is how six of ten grounding fields came to be
        hand-listed.

        A ``cancel_step`` that arrives here missed its step: the call it
        meant to stop has already been dispatched, so there is nothing to
        skip and the ask becomes a sentence for the model (see
        :data:`CANCEL_STEP_LATE`).  Anything else waiting — a decision for
        a gate that closed while it was in flight — is dropped with one
        line on stderr, because a decision nobody can apply must not look
        like one that was applied.
        """
        if self._control is None:
            return []
        injected: List[str] = []
        # Arrival order, not kind order: two injections and a late
        # cancel_step reach the model in the order the operator sent them,
        # which is the only order they mean anything in.
        for command in self._control.poll():
            word = command.get("control")
            if word == INJECT:
                text = str(command.get("text") or "")
                # A plain user turn in BOTH protocols. A native turn's
                # `tool` messages answer calls; this answers nothing — it
                # is somebody talking, and `user` is the role for that.
                messages.append({"role": "user", "content": text})
                injected.append(text)
            elif word == CANCEL_STEP:
                messages.append({"role": "user",
                                 "content": CANCEL_STEP_LATE})
            else:
                self._control.warn(
                    f"control: dropped a {word} for "
                    f"{command.get('approval_id', '?')} — this run is not "
                    f"waiting on it any more")
        return injected

    def _cancel_step_asked(self) -> bool:
        """Whether the operator has asked to drop the rest of this step.

        Takes **only** ``cancel_step`` off the channel and leaves everything
        else where it was: an injection swallowed at a call boundary would
        be an instruction the model was never shown, delivered to nobody,
        with nothing saying so.  Several asks are one answer — an operator
        clicking twice wanted the step stopped, not two steps.
        """
        if self._control is None:
            return False
        return bool(self._control.poll(only=(CANCEL_STEP,)))

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
        report = self._validator.validate(
            answer, self._store.evidence_texts(),
            # Which tools this run dispatched, from the store that recorded
            # them — the plane-claim check's evidence, and the one place
            # that fact lives. See `MissionResultStore.called_tools`.
            called=self._store.called_tools())
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
