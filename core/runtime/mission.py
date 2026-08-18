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
  the sandbox and the audit log all still apply.  The runner never
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
* **this loop imposes no budget of its own.**  It runs until the model
  answers, until somebody stops it, or until a bound an *operator* asked
  for is reached: ``max_steps`` when one was given, and wall-clock
  seconds when a caller supplied a :class:`~core.budgets.Deadline`.
  Running out of either is a recorded outcome (``budget_exhausted``) that
  **names which one**, and not a silent truncation.  Neither is set by
  default, and that is the whole of the change: the eight-step cap
  this loop used to carry decided how much work a question was worth,
  which is not a thing a framework can know;
* what catches a run that is going nowhere is a
  :class:`~core.runtime.supervisor.Supervisor` and not a counter.  It
  watches for repetition — the same call returning the same bytes, three
  rejected replies running, steps that produce nothing new — asks the
  model what the pattern means, and hands back ``nudge`` (a note this
  loop injects at the next step boundary), ``stuck`` (this loop asks for
  a best answer and ends, ``reason: "stuck"``) or ``progressing``
  (nothing happens).  ``None`` is a run nobody is watching, which is what
  every run of this loop was;
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

**Where the loop is.**  Everything above is still true and none of it
happens here any more: the loop is :class:`core.runtime.run.Run`, six
objects rather than thirty parameters, and
:class:`MissionRunner` is the adapter that builds them.  What stayed is
the *vocabulary* — the transcript shapes, the protocol text both
protocols are stated in, the builders for the records two paths emit
(:func:`_grounding_record`, :func:`_finished_record`, :func:`second_opinion`,
:func:`persist_record`, :func:`_record_decision`), and the three facts a
run reads off its bus (:func:`sandbox_of`, :func:`audit_ref_of`,
:func:`_profile_field`).  Each of those has exactly one owner and this is
where it lives; :mod:`core.runtime.run` imports them, and the staged path
in :mod:`core.runtime.swarm` imports the same ones rather than writing a
second copy — which it once did, and shipped six of ``grounding``'s ten
fields for its trouble.
"""

from __future__ import annotations

import inspect
import re
import time
from dataclasses import dataclass, field
from typing import (
    Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple,
)

from core.bounding import MAX_RESULT_BYTES
from core.durable import RunStore
from core.budgets import BudgetExhausted, Deadline
from core.runtime.approvals import ApprovalError, ApprovalStore, ApprovalTicket
from core.runtime.context_window import MissionWindow
from core.runtime.control import GATE_WAIT_S
from core.runtime.grounding import GroundingReport, GroundingValidator
from core.runtime.mission_stream import Observer
from core.runtime.results import RESULT_TOOL, MissionResultStore
from core.runtime.usage import Ledger, Rate


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
    :meth:`core.runtime.run.Run._second_opinion` and the staged path's
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
    happens to equal its cap.  ``reason`` is present only when there is one,
    and there are two: :data:`CANCELLED` for a run somebody stopped, and
    :data:`~core.runtime.supervisor.STUCK` for one the supervisor wound up.
    The second may sit beside ``answered`` — a wound-up run is asked for its
    best answer and often writes one — which is the point of the field
    being beside the outcome rather than being a word inside it.
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
    #: Why the run ended, when the outcome word does not say: :data:`CANCELLED`
    #: for a run somebody stopped, :data:`~core.runtime.supervisor.STUCK` for
    #: one the supervisor wound up.  ``""`` means the word was enough.
    #:
    #: Written the moment the reason becomes true rather than at the end —
    #: a `stuck` verdict sets it before the wind-up turn is asked — and
    #: overwritten by :meth:`~core.runtime.run.Run._stopped` if a person
    #: or a clock
    #: gets there first, which is the right precedence: somebody threw a
    #: switch, and that is the sentence they are owed.
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


# ── writing a decision down ─────────────────────────────────────────────────


def _record_decision(approvals: ApprovalStore, approval_id: str,
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

    A module function and not a method, for the reason
    :func:`persist_record` is one: it is the ONE call in this package
    that writes a decision down, the loop that carries a decision now
    lives in :mod:`core.runtime.run`, and a second copy of these two
    calls would be a second owner of what a yes means.  It stays in
    this module beside the other things a run writes down.
    """
    approve = bool(decision.get("approve"))
    try:
        approvals.decide(
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
        approvals.consume(approval_id)
    except (ApprovalError, OSError) as exc:
        return False, (
            f"The approval was recorded and could NOT be spent ({exc}), "
            f"so the call was NOT made. Nothing here proceeds on a "
            f"decision it cannot account for.")
    return True, ""


class MissionRunner:
    """Seed the plan with a tool catalogue, then let the model drive.

    **The loop moved and this is the adapter.**  Everything below is still
    true of a run — it is the long-form documentation of what each of these
    parameters means, and there is nowhere better for it — but the loop
    itself is :class:`core.runtime.run.Run`, whose constructor is six
    objects rather than thirty parameters.  ``__init__`` builds those six
    and every method here delegates.

    It stays, and it is not a shim on the way out.  A caller that holds a
    ``MissionRunner`` keeps it — ``core/cli.py``, the staged runner, the
    resume path and this class's conformance suite all do — and the suite
    is the reason the adapter exists: ``tests/test_mission.py`` is several
    hundred assertions about what this loop does, and they go on being made
    through the surface they were written against while the loop underneath
    them changes shape.  What the extraction may not do is change a byte of
    what a run emits, and ``tests/test_run_corpus.py`` is where that is
    checked rather than asserted.

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
    max_steps:
        An operator's **hard ceiling** on model turns, or ``0`` — the
        default — for no ceiling at all.

        Zero and not eight, and that is the whole change stated in one
        parameter.  A cap of eight stopped an endless loop, which is a
        real job, and it also decided that no question was worth a ninth
        turn, which is not a decision this loop can make: a mission that
        needed a fifth governed view spent the cap on the fourth and
        reported what it had.  The endless loop is now caught by
        ``supervisor`` below, which watches for repetition rather than
        for quantity, and this number went back to being what
        ``--mission-seconds`` already was — a thing an operator asks for,
        absent unless they do.

        When it IS given it behaves exactly as it always did: a total for
        the run and not an allowance per process (a resumed run counts
        its recorded steps against it), hit is ``budget_exhausted`` with
        ``budget.which == "steps"``, and it counts model turns including
        the ones spent on a parse error.  ``0`` travels on
        ``mission_started.max_steps`` as ``0``, which is how the wire says
        "no ceiling".
    supervisor:
        A :class:`~core.runtime.supervisor.Supervisor`, or ``None`` for a
        run nobody is watching — which is what every run of this loop was,
        and is what a library caller gets unless it asks.

        It is what replaced the step budget.  At each step boundary it is
        told what the last step did and answers with a
        :class:`~core.runtime.supervisor.Review` or with nothing; three
        verdicts reach this loop and each one is acted on in exactly one
        place (:meth:`_supervise`): ``progressing`` changes nothing,
        ``nudge`` puts the reviewer's note in front of the model as a user
        turn — the same delivery an operator's ``inject`` gets, and it
        rides the same ``injected`` field — and ``stuck`` asks the model
        for its best answer with what it has and ends the run with
        ``reason: "stuck"``.

        **A run with no ceiling and no supervisor can loop forever**, and
        that is stated rather than defended against: a library caller that
        passes neither has asked for a loop with no bound, the CLI always
        builds one, and a bound this loop invented for itself is the thing
        that was removed.
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

        Unbounded by default on purpose, and now for the same reason
        ``max_steps`` is: a framework that killed a run at some number
        nobody chose would be a regression for every operator running a
        slow local model — a 20B at 59 tok/s spends minutes on one honest
        answer.  The reference deployment bounds a turn at its own layer
        today.  A deadline is a thing an operator asks for.

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
        max_steps: int = 0,
        validator: Optional[GroundingValidator] = None,
        critic: Any = None,
        supervisor: Any = None,
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
        # Here and not at module scope, and it is the one import in this
        # package that points that way. `core.runtime.run` reads this
        # module's vocabulary — the transcript shapes, the protocol text,
        # the record builders, the three facts read off a bus — at import
        # time; this is a runtime import so the two can be loaded in
        # either order and neither has to be half-built for the other.
        from core.runtime.run import (
            Bounds, Model, Observer as RunObserver, Personality, Run, Store,
            ToolPlane,
        )

        # THE ADAPTER. Thirty parameters in, six objects out, and the
        # order they are built in is the order this constructor used to
        # refuse things in: a bad history is a `ValueError` before a bad
        # protocol is, and both before a native run that offers a tool
        # called `mission_answer`. Nothing here decides anything — every
        # line is a parameter finding the object that owns it.
        store = Store(runs=run_store, run_id=run_id, approvals=approvals,
                      ticket=approval)
        plane = ToolPlane(bus=bus, offered=tool_names, store_tool=store_tool,
                          gated=gated, admits=admits,
                          plane_changed=plane_changed)
        personality = Personality(system_message=system_message,
                                  history=history, grounding=validator,
                                  critic=critic)
        model = Model(ask=chat_fn, protocol=protocol, window=window,
                      usage_fn=usage_fn, tool_calls_fn=tool_calls_fn,
                      rate=rate, ledger=ledger)
        bounds = Bounds(deadline=deadline, cancel=cancel, control=control,
                        gate_wait_s=gate_wait_s,
                        max_result_bytes=max_result_bytes,
                        started_at=started_at, max_steps=max_steps,
                        supervisor=supervisor)
        #: The loop. Everything below this line is a name kept alive for a
        #: caller that already had it.
        self._run = Run(personality, plane, bounds, store,
                        # The one sink this constructor's caller gets to
                        # pass, and the durable log beside it: emitting is
                        # store-first, so the `Observer` holds both.
                        RunObserver(observer, store=store), model)

    # ── the surface a caller already had ────────────────────────────────
    #
    # Delegates and nothing else. `core/cli.py`, `core/runtime/swarm.py`,
    # `core/runtime/resume.py` and this class's own conformance suite
    # (`tests/test_mission.py`) hold these names, and an extraction that
    # made a caller change a line would be an extraction that changed
    # something. Each one reads the live object: `store` in particular must
    # follow a resumption's adoption, so it is a property and not a field
    # copied at construction.

    @property
    def run_id(self) -> str:
        """The run this loop's records are being recorded under, or ``""``.

        Readable because the id is the only handle a caller has on the
        transcript afterwards, and the store — not the runner and not the
        CLI — is the one that hands it out.
        """
        return self._run.run_id

    @property
    def protocol(self) -> str:
        """Which protocol this loop is speaking, :data:`JSON_PROTOCOL` or
        :data:`NATIVE_PROTOCOL`.

        Readable because the caller that built the ``chat_fn`` has to
        declare the matching request, and a resume has to rebuild the
        matching messages — two decisions made outside this object about
        a fact it holds.
        """
        return self._run.protocol

    @property
    def store(self) -> MissionResultStore:
        """The mission's result store.  One per runner, cleared per run."""
        return self._run.results

    @property
    def offered(self) -> List[str]:
        """Every tool name the model may name **now**: the set, plus the
        store.  See :attr:`core.runtime.run.Run.offered`."""
        return self._run.offered

    @property
    def gated(self) -> List[str]:
        """Offered tools that need a person, in catalogue order."""
        return self._run.gated

    @property
    def pinned(self) -> int:
        """How many leading messages a compaction may never drop."""
        return self._run.pinned

    def catalogue(self) -> str:
        """The bus's own descriptions of what this mission may name."""
        return self._run.catalogue()

    def seed(self, objective: str) -> List[Dict[str, str]]:
        """The PLAN-phase messages: persona, protocol, catalogue, history,
        objective."""
        return self._run.seed(objective)

    def system_turn(self) -> Dict[str, str]:
        """The system message, rendered from what is offered NOW."""
        return self._run.system_turn()

    def run(self, objective: str,
            resumption: Optional[Any] = None) -> MissionTranscript:
        """Run the mission, or carry a recorded one on from where it
        stopped.  See :meth:`core.runtime.run.Run.run`."""
        return self._run.run(objective, resumption)

    # ── names reached past the surface, and kept working ────────────────
    #
    # Three callers reach for a private method of this class, and each has
    # a reason that survives the extraction: `core.runtime.resume.rebuild`
    # renders a recorded tool result through the loop's OWN renderer rather
    # than a second copy of it, and two tests hold the bound and the gate
    # window to what the loop does. They keep working, and they keep
    # pointing at one implementation.

    def _render_result(self, name: str, result: Any, handle: str = "",
                       already: Any = None):
        """``(what the model is shown, whether it was cut down)``."""
        return self._run._render_result(name, result, handle, already=already)

    def _bound(self, body: str, handle: str = ""):
        """Head and tail of *body*, with a marker naming the store."""
        return self._run._bound(body, handle)

    def _gate_window(self) -> float:
        """``min(what the caller allows, what is left of the clock)``."""
        return self._run._gate_window()

    @property
    def _run_store(self) -> Optional[RunStore]:
        """The durable log this runner appends to, or ``None``.

        Kept because the staged path's suite asks a sub-runner whether it
        was handed one — one writer per run is the property, and the
        cheapest way to state it is to look. The log itself lives on
        :class:`core.runtime.run.Store` now, which is where the run id it
        travels with lives too.
        """
        return self._run.store.runs

    @staticmethod
    def _parse(reply: str):
        """Return ``(decision, problem)``; exactly one is truthy.

        A ``staticmethod`` that imports, because it is called off the
        **class** — the reply parser is a pure function of a string and
        two suites ask it directly — and this module cannot import
        :mod:`core.runtime.run` at the top.  See the note in
        :meth:`__init__`.
        """
        from core.runtime.run import Run
        return Run._parse(reply)

    @staticmethod
    def _heal_native(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Drop ``tool`` messages whose call is no longer in the list.

        Called off the class, like :meth:`_parse`, and for the same reason.
        """
        from core.runtime.run import Run
        return Run._heal_native(messages)
