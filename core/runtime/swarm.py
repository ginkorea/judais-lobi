# core/runtime/swarm.py — staged decomposition over one mission backend

"""A mission turn as a swarm of small missions, when — and only when — the
question needs one.

The problem this solves is measured, not theoretical: a 20B model at 59
tok/s drowns in one long transcript.  By step six of a single-runner
mission, the catalogue lookups that told it what its numbers mean have
been pushed out of attention by three governed views, and the answer is
written from the part it can still see.  The fix is not a longer prompt;
it is *shorter ones* — each stage of the work sees only what that stage
needs.

Five roles, one backend, no second model:

* **TRIAGE** — one cheap call: does this need staging at all?  Most turns
  do not, and a swarm that makes "what's trending" slower is a
  regression, so the router is biased to DIRECT and every failure of the
  router falls back to DIRECT.
* **PLAN** — decompose into at most a handful of steps, each one action
  with a checkable result, each tagged with its rung: a registered tool,
  code via a code-execution tool, or code that composes platform data
  with computation (the SDK inside the code).
* **EXECUTE** — one step, one small :class:`MissionRunner` with a tight
  step budget.  The sub-mission's transcript holds only its own step's
  tool results; earlier steps arrive as short summaries, never as their
  raw output.
* **GATE** — did the step produce what the plan needed.  Mechanical
  first (the runner answered; a tool call succeeded), because a check
  the runtime can evaluate cannot be talked out of its verdict.  An LLM
  gate runs only where mechanics cannot decide — the step stated a
  "done" condition — and it is asked a binary question.
* **SYNTHESIZE** — the final answer, written from the accumulated step
  results and nothing else, then held to the same grounding validator
  the direct path uses.

Failure is contained, never silent: a failed step retries once with the
error in context, then the plan is redrawn once around what already
succeeded, and if that still fails the answer says plainly which step
failed and why.  There is no path that stalls and no path that reports
success it did not have.

Everything a sub-mission does still goes through the one
:class:`~core.tools.bus.ToolBus`; the closed tool set, the gating and
the audit are exactly the direct path's.  The observer vocabulary is
:mod:`core.runtime.mission_stream`, unchanged — a watcher sees one
mission with more steps, and a sub-mission proposing a gated tool ends
the whole turn at ``awaiting_approval`` holding the proposed call, the
same as it always did.

Approvals are the direct path's, entirely.  A sub-runner *is* a
:class:`~core.runtime.mission.MissionRunner`, so it writes the durable
request itself and the ``approval_id`` reaches a watcher on the
``gate_requested`` this class re-emits — which passes gate records
through with their fields untouched, so there is no second copy of the
id to drift.  A resumed turn carries one
:class:`~core.runtime.approvals.ApprovalTicket` into every sub-runner it
builds; the ticket spends itself once, on the dispatch that uses it, so
a plan of five steps that calls the approved tool in the third has spent
exactly one decision.

The stream opens before triage.  Triage is a call to the model like any
other, and the contract's silence clause promises ``mission_started``
ahead of the first one; a turn that announced itself after the router
and the planner spent two round-trips saying nothing, which a consumer
is told to read as a harness that never started.  The plan therefore
cannot ride that record — it does not exist yet, and may never — so it
rides the first ``step_started`` it produces.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import (
    Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple,
)

from core.durable import RunStore
from core.runtime.control import GATE_WAIT_S
from core.budgets import BudgetExhausted, Deadline, cancelled
from core.redact import scrub_record
from core.runtime.approvals import ApprovalStore, ApprovalTicket
from core.runtime.context_window import MissionWindow
from core.runtime.contract import SCHEMA_VERSION
from core.runtime.grounding import GroundingReport, GroundingValidator
from core.runtime.mission import (
    AWAITING_APPROVAL, CANCELLED, JSON_PROTOCOL, MissionRunner,
    MissionTranscript, _finished_record, _grounding_record, _profile_field,
    _protocol_field, _run_field, audit_ref_of, persist_record, sandbox_of,
    second_opinion, stacked, validate_history,
)
from core.runtime.mission_stream import (
    ANSWER, GATE_REQUESTED, GROUNDING, MISSION_FINISHED, MISSION_STARTED,
    Observer, REPLY_REJECTED, STEP_STARTED, TOOL_CALL, TOOL_RESULT,
)
from core.runtime.results import RESULT_TOOL
from core.runtime.usage import Ledger, Rate

__all__ = ["SwarmRunner", "PlanStep", "RUNGS", "RUNGS_WITHOUT_SDK", "SDK_RUNG"]

_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.MULTILINE)

#: Every rung this runner knows how to describe.  The vocabulary is the
#: planner's whole knowledge of the platform's rungs; everything
#: tool-specific stays in the bus's own catalogue, so these never name a
#: tool and never go stale.
#:
#: Not every rung is *offered* on every run — see :data:`SDK_RUNG`.
RUNGS = ("tool", "code", "code+sdk")

#: The one rung that cannot be described without knowing the platform.
SDK_RUNG = "code+sdk"

#: The rungs offered when nothing names an SDK.  Withholding
#: :data:`SDK_RUNG` rather than describing it vaguely is the point: a
#: sentence telling a model to "import the platform SDK" without naming
#: one is an invitation to invent a module, and a 20B accepts it.
RUNGS_WITHOUT_SDK = tuple(rung for rung in RUNGS if rung != SDK_RUNG)

#: What each rung means, said to the executor at the moment it acts — the
#: one place a short instruction has been measured to bind on a 20B, per
#: the 10 August finding that a refusal taught a rule verbatim where the
#: same rule 2,000 tokens upstream in a persona did nothing.
#:
#: These two are true of every platform.  The third is composed per run by
#: :func:`sdk_rung_sentence` from a name only the skill manifest knows.
#: It used to be a constant here reading ``import taipan`` — one
#: deployment's module name frozen into the framework meant to drive any
#: of them, twenty lines under a comment promising that a role never names
#: a platform's particulars.
_RUNG_SENTENCES = {
    "tool": (
        "a registered platform tool. Pick the one whose catalogue "
        "description matches this step and call it."
    ),
    "code": (
        "writing code and running it through a code-execution tool. "
        "Have the code print the values that prove it worked."
    ),
}

#: How each rung is offered to the *planner*: shorter than the executor's
#: sentence, because the planner is choosing between rungs rather than
#: acting on one.  Only the offered rungs are ever listed, so a planner is
#: never told about a route it would then be refused for taking.
_RUNG_PLAN_LINES = {
    "tool": ('- "tool": a platform tool from the list below does exactly '
             'this (search, fetch, submit, poll, read a run).'),
    "code": ('- "code": computation, transformation or visualization — '
             'code written and run through a code-execution tool. Only if '
             'one of the tools listed below runs code; if none does, the '
             'step is a "tool" step or it is not a step.'),
}


def sdk_rung_sentence(sdk_import: str) -> str:
    """The ``code+sdk`` executor sentence, naming one declared SDK."""
    return (
        "code that itself reads platform data and computes over it in "
        f"one run — `import {sdk_import}`, connect (the credential is "
        "already in the execution environment), fetch what the step "
        "names, then compute. Run it through a code-execution tool and "
        "have it print the values that prove it worked."
    )


def sdk_rung_plan_line(sdk_import: str) -> str:
    """The ``code+sdk`` planner line, naming one declared SDK."""
    return (f'- "code+sdk": code that also fetches platform data itself '
            f'with `import {sdk_import}`, because the step composes '
            f'governed data with computation.')

# ── the role prompts ─────────────────────────────────────────────────────
# Short on purpose, and general on purpose.  Each one describes a KIND of
# work, never a platform's particulars — the particulars arrive from the
# skill manifest and the tool catalogue, which are content, not code.

TRIAGE_PROMPT = """\
You are a router deciding how much machinery one request needs.
DIRECT: it can be answered with a couple of tool calls or from the \
conversation — a lookup, a search, a status check, a follow-up on an \
earlier answer.
STAGED: it needs several dependent actions — run something then read the \
result then transform or visualize it; research a thing then compute over \
what was found; compare across several sources.
Most requests are DIRECT. When unsure, say DIRECT.
Reply with exactly one JSON object and nothing else:
{"route": "direct"} or {"route": "staged"}
"""

PLAN_PROMPT = """\
You are a planner. Break the objective into the fewest small steps that \
answer it — {max_steps} at most, usually 2 or 3. Each step is ONE action \
with a checkable result. Tag each step with how it gets done:
{rungs}
Steps run in order. "needs" names earlier steps whose results this step \
uses. "done" states the evidence of success in one clause: a value \
printed, an artifact produced, a handle returned, an id found.
Reply with exactly one JSON object and nothing else:
{{"steps": [{{"id": "s1", "goal": "...", "rung": "tool", "needs": [], \
"done": "..."}}]}}
"""

EXECUTE_PROMPT = """\
You are executing ONE step of a larger plan. Do only this step.
Use the fewest tool calls that produce the step's result — usually one.
When the step is done, answer with only the facts it produced: values, \
identifiers, handles, filenames — with nothing invented and nothing \
about the wider objective.
If the step cannot be done with the tools offered, answer saying exactly \
what is missing, and stop.
"""

GATE_PROMPT = """\
You are checking one step's reported result against what the plan needed.
Judge only what is reported below — not what you believe is likely.
Reply with exactly one JSON object and nothing else:
{"pass": true} or {"pass": false, "why": "<one sentence>"}
"""

SYNTHESIZE_PROMPT = """\
You are writing the final answer to the objective from two things below: \
the step results, and the tool output this mission received.
The tool output is what the plane actually returned. Read the answer out \
of it and carry every identifier and figure across exactly as it appears \
there. Quote when the objective asks you to quote.
The step results say which steps met their success condition. If one \
FAILED, say plainly which and why, and never claim a step succeeded that \
did not — but a fact is available if it is in the tool output, whatever \
became of the step that read it.
Answer every part of the objective the tool output supports.
"""


@dataclass
class PlanStep:
    """One step of a staged plan, as the planner stated it."""

    id: str
    goal: str
    rung: str = "tool"
    needs: List[str] = field(default_factory=list)
    done: str = ""

    def as_state(self) -> Dict[str, Any]:
        """Every field of this step, for the run's checkpoint.

        All five, not the three a watcher is shown: ``needs`` decides which
        earlier summaries the executor of this step is given and ``done`` is
        the condition the gate asks the model about, so a restart that read
        back only the watcher's three would continue a *different* plan
        under the same run id — the failure the staged resume exists to
        avoid, reintroduced by the record it reads.
        """
        return {"id": self.id, "goal": self.goal, "rung": self.rung,
                "needs": list(self.needs), "done": self.done}

    @classmethod
    def from_state(cls, state: Mapping[str, Any]) -> "PlanStep":
        """One checkpointed step, back.  ``.get`` throughout on purpose.

        A run checkpointed by a harness that wrote only ``{id, goal, rung}``
        — every staged run recorded before :meth:`as_state` existed — comes
        back as a step with no ``needs`` and no ``done``, which is a plan
        this runner can execute rather than a resume it has to refuse.
        """
        needs = state.get("needs")
        return cls(
            id=str(state.get("id") or ""),
            goal=str(state.get("goal") or ""),
            rung=str(state.get("rung") or "tool"),
            needs=[str(n) for n in needs] if isinstance(needs, list) else [],
            done=str(state.get("done") or ""),
        )


@dataclass
class _StepOutcome:
    """What one executed step left behind — what it said, and what it read.

    ``summary`` is the executor's own sentence about the step; ``evidence``
    is what that step's tools actually returned, whole, straight out of the
    sub-mission's :class:`~core.runtime.results.MissionResultStore`.

    Both, because the synthesizer needs the second one.  A step that fetched
    a 34,000-character governed view and reported "read the view for run
    r-7" has the actor list in ``evidence`` and nowhere else; an answer
    asked to name the actor at the top of it, given only ``summary``, said
    "the actor list was not reported in the step results" — which was true
    of what it had been shown and false of what the mission had read.
    """

    step: PlanStep
    ok: bool
    summary: str = ""
    why: str = ""
    #: Every successful tool result of every attempt at this step, whole.
    evidence: List[str] = field(default_factory=list)


#: The keys of a plan step a *watcher* is shown, which is deliberately
#: fewer than the keys a *restart* needs.  See :meth:`PlanStep.as_state`.
_PLAN_FIELDS = ("id", "goal", "rung")


def _plan_state(plan: Sequence[PlanStep]) -> List[Dict[str, Any]]:
    """A plan as the run's checkpoint holds it — every field of every step.

    The checkpoint's shape and the stream's are two renderings of one fact,
    so the stream's is a *projection* of this one rather than a second
    hand-listing beside it.
    """
    return [step.as_state() for step in plan]


def _plan_record(plan: Sequence[PlanStep]) -> List[Dict[str, str]]:
    """A plan as the observer's ``plan`` field.

    One owner for the shape, because it is now stated from two places — the
    plan as drawn and the plan as redrawn — and a second hand-listing is how
    the ``grounding`` record came to carry six of the ten fields its own
    contract required.
    """
    return [{key: state[key] for key in _PLAN_FIELDS}
            for state in _plan_state(plan)]


#: The two checkpointed outcomes that mean a step is FINISHED with.
#:
#: ``awaiting_approval`` is deliberately not one of them.  Nothing was
#: called, nothing was produced, and the next move belongs to a person —
#: which is why :data:`core.runtime.resume.RESUMABLE_OUTCOMES` admits that
#: word at the door in the first place.  A resume carrying the decision is
#: precisely the run that has to reach that call again, so the step goes
#: back on the queue rather than into the results.
_SETTLED = ("ok", "failed")


def _steps_done(resumption: Optional[Any]) -> List[Dict[str, str]]:
    """The checkpointed steps a resumed turn is NOT going to run again."""
    if resumption is None:
        return []
    return [dict(entry) for entry in resumption.steps_done
            if isinstance(entry, Mapping)
            and str(entry.get("outcome") or "") in _SETTLED
            and entry.get("id")]


def _resumed_outcome(entry: Mapping[str, Any],
                     plan: Sequence[PlanStep]) -> "_StepOutcome":
    """One checkpointed step, back as the outcome this loop carries.

    The inverse of :meth:`SwarmRunner._step_done`, and next to nothing else
    on purpose: those two are the whole of what a staged run persists about
    a step, and a reader written anywhere but beside the writer is the
    second owner that drifts.  ``summary`` and ``why`` are the same slot —
    the field answers *what came of this step* — so which of the two it
    lands in here is decided by the word, exactly as the word decided which
    of them was written.

    The :class:`PlanStep` is looked up in the plan where the plan still has
    it, and reconstructed from the id where it does not: a step completed
    under a plan that was then redrawn around it is a real thing to have
    happened, and its summary is still what the synthesizer is owed.
    """
    sid = str(entry.get("id") or "")
    step = next((s for s in plan if s.id == sid), None) or PlanStep(
        id=sid, goal=str(entry.get("goal") or sid))
    ok = str(entry.get("outcome") or "") == "ok"
    text = str(entry.get("summary") or "")
    return _StepOutcome(step=step, ok=ok,
                        summary=text if ok else "",
                        why="" if ok else text)


def _dispatched(step: Any) -> Sequence[Any]:
    """What one turn called, whichever protocol it called it under.

    A JSON turn is one decision and keeps it in :class:`MissionStep`'s own
    ``tool``/``exit_code``; a native turn may make several and keeps them
    in :attr:`~core.runtime.mission.MissionStep.calls`, leaving the step's
    own fields unset rather than mirroring the first call into them.  The
    field *names* are the same on both classes on purpose (see
    :class:`~core.runtime.mission.MissionCall`), so one expression reads
    either.

    Written down because the mechanical gate got this wrong for as long as
    the native protocol existed: it asked ``step.tool`` and nothing else,
    so **every** native sub-mission "made no successful tool call", failed
    its gate, retried, and had its plan redrawn around a step that had in
    fact worked.  Nothing failed loudly — the turn just did three times the
    work and then said so in a caveat.
    """
    if step.calls:
        return list(step.calls)
    return [step] if step.tool else []


class _OpenedAlready:
    """A sub-mission's observer with the sub-mission's opening removed.

    :meth:`SwarmRunner.run` announces the mission before triage, which is the
    only way the contract's silence clause can hold across a router that is
    itself a call to the model.  The direct path underneath is a whole
    :class:`MissionRunner` and would announce it a second time: one turn, two
    ``mission_started`` records, and a pane that renders two missions.

    Everything else passes through untouched — ``mission_finished``
    emphatically included.  That record comes out of the sub-runner's own
    ``finally`` holding the step count this object does not have, and dropping
    it here would trade a doubled opening for a stream that never closes.

    Untouched, and through :meth:`SwarmRunner._emit` rather than straight to
    the observer, exactly as :class:`_StageObserver` does.  There is one
    choke point per runner and it is where the durable transcript is written;
    a direct path that handed its records to the observer around it would put
    a run's own answer on a pane and not in its log.  Re-scrubbing what a
    sub-runner already scrubbed costs a pass and changes nothing —
    :func:`~core.redact.scrub_record` is idempotent.
    """

    def __init__(self, emit: Callable[..., None]):
        self._emit = emit

    def __call__(self, record: Dict[str, Any]) -> None:
        if record.get("event") == MISSION_STARTED:
            return
        fields = dict(record)
        event = fields.pop("event", "")
        self._emit(event, **fields)


class _StageObserver:
    """One watcher for many sub-missions, speaking as a single mission.

    Sub-runners each emit ``mission_started`` … ``mission_finished`` around
    their own little run; a pane fed those raw would render five missions
    for one turn.  This filter drops the sub-mission bookkeeping, renumbers
    ``index`` into one global sequence, and passes everything else through
    untouched — so the events a watcher sees are indistinguishable in
    vocabulary from a single longer mission.

    It also carries the plan.  The plan cannot ride ``mission_started`` any
    more — that record is emitted before triage, and at that moment there is
    no plan and may never be one — so it rides the first ``step_started`` the
    plan produces, which is the next thing a watcher hears and the moment the
    plan starts being true.  See :data:`core.runtime.contract.OPTIONAL`.

    *start_index* is where the global numbering begins, and it is ``0``
    everywhere except a resumed staged turn: those records go into the log
    the earlier stretch wrote, and an index that started again would put two
    records with the same ``index`` in one run.  *resumed* rides the first
    ``step_started`` of the new stretch beside the plan, for the reason the
    plan does — one record announcing what a watcher is about to see, and
    not a fact restated on every step.
    """

    _PASS = frozenset({
        STEP_STARTED, REPLY_REJECTED, TOOL_CALL, TOOL_RESULT, GATE_REQUESTED,
    })

    def __init__(self, emit: Callable[..., None], *, start_index: int = 0,
                 resumed: Optional[Dict[str, Any]] = None):
        self._emit = emit
        self._next_index = max(0, int(start_index))
        self._offset = self._next_index
        self._seen_high = -1
        self._pending_plan: Optional[List[Dict[str, str]]] = None
        self._pending_resumed = dict(resumed) if resumed else None

    def begin_stage(self) -> None:
        """A new sub-mission is starting; its indexes begin at zero."""
        self._offset = self._next_index
        self._seen_high = -1

    def announce(self, plan: Sequence[PlanStep]) -> None:
        """Carry this plan on the next ``step_started`` to come through.

        Called once for the plan as drawn and again for a redraw, so what a
        watcher holds is the plan the steps it is now seeing belong to rather
        than the one that was abandoned.
        """
        self._pending_plan = _plan_record(plan)

    def __call__(self, record: Dict[str, Any]) -> None:
        event = record.get("event")
        if event not in self._PASS:
            return
        fields = dict(record)
        fields.pop("event", None)
        if "index" in fields:
            local = int(fields["index"])
            self._seen_high = max(self._seen_high, local)
            fields["index"] = self._offset + local
            self._next_index = max(self._next_index,
                                   self._offset + self._seen_high + 1)
        if event == STEP_STARTED:
            # On ``step_started`` and nowhere else: ``plan`` and ``resumed``
            # are declared optional on that event alone, and a field an event
            # does not declare is a field a consumer meets with no sentence
            # for it.
            if self._pending_plan is not None:
                fields["plan"] = self._pending_plan
                self._pending_plan = None
            if self._pending_resumed is not None:
                fields["resumed"] = self._pending_resumed
                self._pending_resumed = None
        self._emit(event, **fields)


class SwarmRunner:
    """Triage, then either one mission or a staged handful of small ones.

    Constructed exactly like a :class:`MissionRunner` plus the staging
    knobs, so the CLI can build either from the same material.  The same
    ``chat_fn`` drives every role — one leased endpoint, no second model.

    Parameters beyond the runner's:

    plain_chat_fn:
        ``messages -> str`` with **no tool schemas declared**, for the
        roles that must answer in prose or bare JSON (triage, plan, gate,
        synthesis).  A harmony model with tools declared will answer a
        yes/no question with a tool call; without them it answers the
        question.  Defaults to ``chat_fn``.

        When ``json_mode`` is set it is additionally called as
        ``plain_chat_fn(messages, response_format=…)`` for the three roles
        that must return an object, so it has to accept keyword extras;
        the CLI's does.  Never for the synthesizer, which writes prose.
    json_mode:
        Whether this backend can be told to emit syntactically valid JSON
        — ``BackendCapabilities.supports_json_mode``, read by the CALLER
        off the client it built, because the swarm holds a function and
        not a client.  ``False`` is every backend that cannot, and is the
        behaviour this class had before the flag existed.
    max_plan_steps:
        Hard cap on plan length.  ``None`` — the default — derives it from
        the mission's own budget: ``max(2, max_steps // 2)``, which is the
        longest plan whose every step can still afford a call and an
        answer.  It was a flat five, and five was a stand-in for the
        thing that actually bounds a plan: a plan cannot have more steps
        than the mission has tool turns to spend on them.  A caller who
        wants a shorter plan than the budget allows still says so.
    step_budget:
        Tool-turns per sub-mission.  ``None`` — the default — is *what the
        mission has left*: a step may spend the whole remaining budget.
        It was four, and four is what starved the live run of 16 August: a
        planner-written step reading two governed runs needs two views and
        two ``mission_result`` reads, which is four turns before it can
        say a word, so it exhausted its slice, failed its gate on
        ``budget_exhausted``, retried, and had the plan redrawn around the
        work that had happened to fit.  ``max_steps`` already bounds the
        turn; a second, smaller number inside it was bounding the wrong
        thing.  Portioning is kept as a knob for a caller who wants a
        slice — with the trade stated: one greedy step can now spend the
        whole mission, and the mission stops when it does, which is the
        same stop it always had.
    retries_per_step:
        Bounded retries before the plan is redrawn.  Stays a small fixed
        number, and it is not a stand-in for a context bound: it counts
        *attempts at the same failure*, and the second attempt of a step
        that failed for a reason retrying cannot fix is spent, not saved.
    sdk_import:
        What the platform's SDK is called to ``import``, from the skill
        manifest's ``sdk_import`` field.  Naming it offers the planner the
        ``code+sdk`` rung and composes the sentence the executor is given;
        leaving it empty withholds that rung entirely, and the planner's
        prose then lists only the rungs it may actually use.  The harness
        does not know this name and must not guess it: it drives whatever
        platform it is pointed at, and a manifest is where a platform
        describes itself.
    window:
        **The one window for the whole turn.**  Passed straight through to
        every :class:`MissionRunner` this builds — see that class's
        ``window`` parameter — and, since the live run of 16 August, used
        on this runner's *own* four roles as well: the router, the
        planner, every gate and the synthesizer go out through
        :meth:`_fit`.

        Those four were unbounded on the argument that each builds "one
        short list and sends it once".  Two of them are not short.  The
        planner carries the tool catalogue, and the synthesizer carries
        every settled step's whole result — which is the point of it — so
        the only honest bound on either is the same
        :class:`~core.runtime.context_window.MissionWindow` the steps are
        held to, resolved once from the backend's real
        ``max_context_tokens``.  Nothing in this class shrinks it: there
        is one object, one profile, one number, and a staged turn on a
        million-token endpoint uses a million-token endpoint.

        ``None`` is a swarm with no bound at all, which is what a caller
        who passes no window is asking for.
    run_store, run_id:
        The durable transcript, exactly as
        :class:`~core.runtime.mission.MissionRunner` takes it — and
        **not** passed through to the sub-missions this builds.  Their
        records already arrive here to be renumbered and filtered; a
        sub-runner writing to the same run as well would put every step
        in the log twice, once under its own index and once under the
        global one.  One turn is one run.
    usage_fn, rate:
        As :class:`MissionRunner`'s, and handed down to every runner this
        builds.  The staged path makes model calls of its own — the
        router, the planner, each gate, the synthesizer and its repair
        turns — *outside* any :class:`MissionRunner`, so those are folded
        in here; everything a sub-mission spends is folded into the SAME
        :class:`~core.runtime.usage.Ledger` by handing it down rather
        than by adding sub-totals up afterwards.  One ledger per turn,
        one place the arithmetic happens: a second accumulator is how the
        opening frame once carried six of ten grounding fields, and
        numbers are the half nobody notices is wrong.
    protocol, tool_calls_fn:
        As :class:`MissionRunner`'s, and handed down to every sub-mission
        this builds: a rung's execution is an ordinary mission loop, and a
        staged turn that spoke one protocol at the top and another
        underneath would be a turn whose opening frame is false of most of
        its records.

        This runner's **own** calls do not use them.  The router, the
        planner, each gate and the synthesizer go through
        ``plain_chat_fn``, which deliberately declares no tools at all —
        a harmony model handed a function namespace answers a yes/no
        question with a tool call, which is the failure that function
        exists to prevent, and ``tool_choice="required"`` would make it
        compulsory.
    deadline:
        The **mission's** wall clock, one
        :class:`~core.budgets.Deadline` shared by triage, the planner,
        every sub-mission, every gate and the synthesizer.  ``None`` is
        an unbounded run, which is the default.

        Shared and not divided, because a staged turn is one question:
        an operator who allows a mission ninety seconds has allowed the
        *mission* ninety seconds, and a clock handed out per stage would
        give a five-step plan five times what was asked for.  This is the
        opposite of how ``max_steps`` travels — the step budget is
        deliberately *portioned*, a slice per sub-mission, because steps
        are the thing staging exists to spend in small amounts.  Two
        budgets, two behaviours, on purpose.
    cancel:
        The mission's stop switch, shared the same way and checked at the
        same points: before triage, before a redraw, before the
        synthesizer, and inside every sub-mission the runners below build.
    control:
        The turn's :class:`~core.runtime.control.ControlChannel`, shared
        exactly as the clock and the switch are: **one channel per turn**,
        handed to every :class:`MissionRunner` this builds.  ``None`` is a
        turn nobody can steer, which is the default.

        One and not one apiece, for the reason the clock is one: an
        operator steering "this mission" is steering the turn, and a
        channel opened per sub-mission would deliver an injection to
        whichever of five stages happened to be reading.  Shared, it
        reaches **the sub-mission that is running** — that runner drains
        it between its own steps — which is the only stage in a staged
        turn that is a conversation.

        This runner's **own** roles ignore it, and that is not an omission.
        The router, the planner, each gate and the synthesizer are single
        questions asked and answered in one round trip through
        ``plain_chat_fn``; there is no "between steps" to inject into, and
        an instruction folded into a yes/no prompt would corrupt the answer
        that prompt exists to get.  A ``cancel`` still reaches them,
        because the channel throws the switch from its own thread and
        :meth:`_stop` is asked before each of those round trips.
    """

    def __init__(
        self,
        chat_fn: Callable[[List[Dict[str, str]]], Any],
        bus: Any,
        tool_names: Sequence[str],
        *,
        system_message: str = "",
        max_steps: int = 24,
        validator: Optional[GroundingValidator] = None,
        critic: Any = None,
        admits: Optional[Callable[[Sequence[str], Sequence[str]],
                                  Sequence[str]]] = None,
        plane_changed: Optional[Callable[[List[str]], None]] = None,
        gated: Sequence[str] = (),
        approvals: Optional[ApprovalStore] = None,
        approval: Optional[ApprovalTicket] = None,
        history: Sequence[Dict[str, str]] = (),
        observer: Optional[Observer] = None,
        plain_chat_fn: Optional[Callable[..., Any]] = None,
        json_mode: bool = False,
        max_plan_steps: Optional[int] = None,
        step_budget: Optional[int] = None,
        retries_per_step: int = 1,
        summary_chars: Optional[int] = None,
        sdk_import: str = "",
        window: Optional[MissionWindow] = None,
        run_store: Optional[RunStore] = None,
        run_id: str = "",
        usage_fn: Optional[Callable[[], Any]] = None,
        tool_calls_fn: Optional[Callable[[], Any]] = None,
        protocol: str = JSON_PROTOCOL,
        rate: Optional[Rate] = None,
        deadline: Optional[Deadline] = None,
        cancel: Any = None,
        control: Any = None,
        gate_wait_s: float = GATE_WAIT_S,
    ):
        self._chat = chat_fn
        self._plain_chat = plain_chat_fn or chat_fn
        # Only ever consulted by `_json_reply`, and only ever set by a
        # caller that also handed in a `plain_chat_fn` able to take the
        # keyword: a runner given a bare `chat_fn` keeps the old call shape.
        self._json_mode = bool(json_mode) and plain_chat_fn is not None
        self._bus = bus
        self._tool_names = list(tool_names)
        self._system_message = system_message
        self._max_steps = max(1, int(max_steps))
        self._validator = validator
        #: A :class:`~core.critic.mission.MissionCritic`, or ``None``, and
        #: it belongs to the SYNTHESIZER.
        #:
        #: A staged turn's answer is written once, at the end, over every
        #: step's evidence — so the second opinion is asked there, exactly
        #: where the direct path asks it of its own answer, and not once per
        #: sub-mission. The sub-runners have no validator either, for the
        #: same reason: a step's summary is not an answer to the objective.
        #:
        #: `_direct` DOES hand it on, because that path's MissionRunner is
        #: writing the turn's answer itself. Duck-typed rather than
        #: imported, as in `MissionRunner`: `core.critic` pulls in pydantic
        #: and a transport, and a turn that is not using a critic must not
        #: pay for either.
        self._critic = critic
        #: Handed to every MissionRunner this builds and used by nothing
        #: here — the two halves of "the plane may change under a run"
        #: (see `MissionRunner`'s own parameter documentation).
        #:
        #: Threaded rather than dropped because a sub-mission with no
        #: `admits` takes whatever the bus grows, and a staged turn that
        #: widened itself where the direct one would not would make
        #: `--swarm` the looser of the two governance paths. This runner's
        #: OWN view of the plane — `_offered`, the opening frame, the
        #: planner's short catalogue — is the set the turn started with;
        #: Phase 11's one runtime is where that stops being two views.
        self._admits = admits
        self._plane_changed = plane_changed
        self._gated = list(gated)
        self._approvals = approvals
        self._approval = approval
        if approval is not None:
            # Narrowed HERE as well as in every MissionRunner this builds,
            # because `_opening` renders the gated names for the whole turn
            # from this list and a consumer must not be able to tell from the
            # opening frame which route ran. One owner for the subtraction
            # itself: `ApprovalTicket.widen`.
            self._gated = approval.widen(self._gated)
        self._history = validate_history(history)
        self._observer = observer
        # The durable transcript, and it stays HERE. Every record a
        # sub-mission emits reaches this runner's `_emit` — through
        # `_StageObserver` on the staged path and `_OpenedAlready` on the
        # direct one — so a sub-runner given a store of its own would append
        # the same record twice, once under its own index and once under the
        # renumbered one. One run, one log, one writer.
        self._run_store = run_store
        self._run_id = str(run_id or "")
        # ONE window, handed to every MissionRunner this builds AND used
        # by `_fit` on this runner's own four roles. A rung's execution is
        # an ordinary mission loop and grows the same unbounded message
        # list; the planner and the synthesizer build lists of their own
        # that are not short either, and a character cap standing in for a
        # context bound is what starved the 16 August run.
        self._window = window
        self._usage_fn = usage_fn
        # Handed down to every MissionRunner this builds and used by
        # nothing here. A rung's execution is an ordinary mission loop and
        # speaks whichever protocol the turn was started with; this
        # runner's OWN calls — the router, the planner, each gate, the
        # synthesizer — go through `plain_chat_fn`, which declares no
        # tools at all, because a yes/no question answered with a tool
        # call is the failure that function exists to prevent.
        self._tool_calls_fn = tool_calls_fn
        self._protocol = protocol
        self._rate = rate
        # Replaced at the top of every `run`, so a runner used twice does
        # not report the first turn's tokens on the second.
        self._ledger = Ledger()
        #: The per-call field of the most recent call THIS object made,
        #: so the synthesized answer can carry the cost of the call that
        #: actually wrote it — which is the repair turn when there was
        #: one, not the draft it replaced.
        self._last_spent: Dict[str, Any] = {}
        #: Every tool this staged turn dispatched, across every sub-mission,
        #: once each.  Accumulated here rather than threaded back through
        #: `_execute_step` beside `evidence` because it comes from the same
        #: place `evidence` does — the sub-runner's own store — and the
        #: plane-claim check needs the union over the whole turn, not one
        #: step's.  See `MissionResultStore.called_tools`.
        self._called: List[str] = []
        # One clock and one switch for the whole turn, handed to every
        # runner `_runner` and `_direct` build. See the class docstring for
        # why seconds are shared where steps are portioned.
        self._deadline = deadline
        self._cancel = cancel
        # One channel for the whole turn, like the clock and the switch,
        # and handed to the sub-missions for the same reason: an operator
        # steering this turn is steering the mission, not whichever stage
        # happened to be listening.
        self._control = control
        self._gate_wait_s = max(0.0, float(gate_wait_s))
        self._started_at: Optional[float] = None
        # All three default to "ask the thing that actually bounds this"
        # rather than to a number. See the class docstring for what each
        # one used to be and what it cost.
        self._max_plan_steps = (max(1, int(max_plan_steps))
                                if max_plan_steps is not None
                                else max(2, self._max_steps // 2))
        self._step_budget = (max(1, int(step_budget))
                             if step_budget is not None else None)
        self._retries = max(0, int(retries_per_step))
        #: ``None`` is "the window decides": a step's result travels whole
        #: and `_fit` bounds the prompt it lands in. An int is a caller
        #: asking for a cut in characters, which is what this was.
        self._summary_chars = (max(200, int(summary_chars))
                               if summary_chars is not None else None)

        # The rungs THIS run offers, and what each one says.  Resolved once
        # here rather than at each use, so the planner's prose, the plan
        # validator and the executor's instruction cannot disagree about
        # which routes exist — a planner offered a rung the validator then
        # rejects burns a re-plan on the harness's own inconsistency.
        self._sdk_import = str(sdk_import or "").strip()
        self._rungs = RUNGS if self._sdk_import else RUNGS_WITHOUT_SDK
        self._rung_sentences = dict(_RUNG_SENTENCES)
        self._rung_plan_lines = dict(_RUNG_PLAN_LINES)
        if self._sdk_import:
            self._rung_sentences[SDK_RUNG] = sdk_rung_sentence(self._sdk_import)
            self._rung_plan_lines[SDK_RUNG] = sdk_rung_plan_line(self._sdk_import)

    # ── the one window, applied to this runner's own roles ──────────────

    def _role_messages(self, system: str, user: str) -> List[Dict[str, str]]:
        """One role's message list: its system turn, this turn's history,
        its question.

        The history is the WHOLE history and not a fixed tail of it.  Three
        roles took ``self._history[-2:]`` — a count standing in for a
        context bound, chosen when nothing in this class knew how big the
        window was.  The window knows.  :meth:`_fit` is where the bound is
        applied now, so a turn with a large window carries the conversation
        it actually had, and a turn with a small one has its oldest turns
        evicted by the same policy every mission step is bounded by.
        """
        return [{"role": "system", "content": system},
                *[dict(turn) for turn in self._history],
                {"role": "user", "content": user}]

    def _fit(self, messages: Sequence[Dict[str, str]]) -> List[Dict[str, str]]:
        """*messages*, inside the one window this turn was given.

        ``pinned=1`` is the role's system turn and nothing else: the
        instruction — and, for the planner, the tool catalogue — is what a
        role cannot be without.  Everything after it is evicted
        oldest-first by :meth:`~core.runtime.context_window.MissionWindow
        .fit`, which never drops the newest round trip, so the question
        itself always survives.

        No window is this class as it ran before there was one: the list
        goes out whole.  The compaction is not announced on the stream —
        these four calls are not mission steps and have no ``step_started``
        to ride, and inventing a record for them would be a contract
        change for a fact the ``usage`` totals already imply.
        """
        if self._window is None:
            return [dict(message) for message in messages]
        kept, _compaction = self._window.fit(
            [dict(message) for message in messages], pinned=1)
        return kept

    # ── telling a watcher ───────────────────────────────────────────────

    def _emit(self, event: str, **fields: Any) -> None:
        """The staged path's choke point, redaction included.

        Same contract as :meth:`MissionRunner._emit`, and scrubbing here for
        the same reason: the records this runner writes itself — the opening,
        the synthesized answer, the swarm's own grounding verdict — never pass
        through a :class:`MissionRunner`, so a redactor installed only there
        would cover the sub-missions and miss the swarm.  Scrubbing is
        idempotent, so a sub-mission's record that arrives here already
        scrubbed is unharmed by being scrubbed again.
        """
        if not self._recording:
            return
        record = scrub_record({"event": event, **fields})
        # The store first, then the watcher, for the reason
        # :meth:`MissionRunner._emit` gives: the sink is a client of the
        # durable log rather than a second truth beside it.
        persist_record(self._run_store, self._run_id, record)
        if self._observer is None:
            return
        try:
            self._observer(record)
        except Exception:                       # pragma: no cover - defensive
            pass

    @property
    def _recording(self) -> bool:
        """Whether anything at all is listening — a watcher or a disk.

        Asked before a record is built rather than only before it is sent,
        because a swarm with neither must run exactly as it ran before
        either existed.
        """
        return self._observer is not None or self._run_store is not None

    @property
    def run_id(self) -> str:
        """The run this swarm's records are recorded under, or ``""``."""
        return self._run_id
    # ── what the last call cost ─────────────────────────────────────────

    def _spent(self) -> Dict[str, Any]:
        """Fold this object's own model call in; render its per-call field.

        The sub-missions do not come through here — they are handed
        ``ledger=self._ledger`` and fold themselves in through
        :meth:`MissionRunner._spent`, which is the same
        :meth:`~core.runtime.usage.Ledger.add`.  What is left for this
        method is the four roles that are this class's own calls: triage,
        the planner, each gate and the synthesizer.

        ``{}`` when the provider reported nothing, so a record carries no
        ``usage`` key rather than a zeroed one.  Never raises.
        """
        try:
            usage = self._usage_fn() if self._usage_fn is not None else None
        except Exception:                       # pragma: no cover - defensive
            usage = None
        recorded = self._ledger.add(usage)
        self._last_spent = ({"usage": recorded.as_record()}
                            if recorded is not None else {})
        return self._last_spent

    def _usage_kw(self) -> Dict[str, Any]:
        """``{"usage": totals}`` for :func:`_finished_record`, or ``{}``."""
        spent = self._ledger.as_record(self._rate)
        return {"usage": spent} if spent is not None else {}

    def _totals(self) -> Dict[str, Any]:
        """``{"usage": …}`` for ``mission_finished``, or ``{}``.

        Through :meth:`~core.runtime.usage.Ledger.as_record`, which is the
        direct path's renderer too — this record is emitted from three
        places in this file and a hand-listed copy in any of them is the
        drift the grounding renderer already paid for once.
        """
        spent = self._ledger.as_record(self._rate)
        return {"usage": spent} if spent is not None else {}

    # ── the one entry point ─────────────────────────────────────────────

    def run(self, objective: str,
            resumption: Optional[Any] = None) -> MissionTranscript:
        """Announce, triage, then one path or the other.

        The announcement is FIRST, before triage — because triage is itself
        a call to the model, and the contract's silence clause says
        ``mission_started`` is emitted *before the model is asked*.  It used
        to come after the router and, on a staged turn, after the planner
        too: two round-trips of nothing on the wire, which on a cold endpoint
        is minutes of a stream a consumer is entitled to read as a harness
        that never started.  A swarm that died in there emitted no events at
        all and was reported as never having run, while it had in fact run
        and asked.

        *resumption* is a
        :class:`core.runtime.resume.StagedResumption` — a staged run's
        checkpointed plan and completed steps, read back — and ``None`` is
        every turn that starts cold, which is the shape this method had
        before staged resuming existed.  Duck-typed rather than imported,
        for the reason :meth:`core.runtime.mission.MissionRunner.run`
        duck-types its own.

        **A resumed staged turn announces nothing and decides nothing.**
        There is no second ``mission_started`` — it is the same mission,
        one objective, one id, one log — and the router and the planner
        are not asked again: the plan is on the record, and re-deciding it
        would be a different mission continuing under the run id of this
        one.  What the resumed stretch does is run the steps the plan has
        left, and say so on its first ``step_started``.
        """
        # One ledger for the whole turn, made here: the router's call is
        # already part of what this turn spent, and every runner below is
        # handed this same object.
        self._ledger = Ledger()
        # The first start wins, so this is where the mission's clock begins
        # — before triage, which is a model call and part of the turn — and
        # the sub-missions below inherit the same started clock rather than
        # rewinding it.
        if self._deadline is not None:
            self._deadline.start()
        self._started_at = time.monotonic()
        if resumption is not None:
            plan = [PlanStep.from_state(state) for state in resumption.plan]
            # Every tool the recorded stretch dispatched, so the answer's
            # plane-claim check sees the whole turn and not the half of it
            # this process ran. Same owner as the live path's: the result
            # store, here rebuilt from the log rather than from a dispatch.
            self._called = list(resumption.called)
            return self._staged(objective, plan, resumption=resumption)
        self._emit(MISSION_STARTED, **self._opening(objective))
        stop = self._stop()
        if stop is not None:
            # Already over before the router was asked. It happens on a
            # resumed switch and on a deadline of zero, and the honest run
            # is one that opens, says why it is stopping, and closes.
            return self._finish_early(objective, stop)
        try:
            plan = (self._plan(objective)
                    if self._route(objective) == "staged" else None)
        except BaseException:
            # Neither path below has been reached, so neither path's
            # ``finally`` will close what was just opened — and a stream that
            # opens and then stops is the spinner-forever state the
            # ``finished`` clause exists to prevent.  Announcing early would
            # otherwise have manufactured that state where there was honest
            # silence before.
            # Zero steps and possibly two model calls: triage and the
            # planner both ran before this. What they cost is on the
            # record even though nothing was accomplished with it.
            self._emit(MISSION_FINISHED, **_finished_record(
                started_at=self._started_at,
                outcome="incomplete", steps=0, max_steps=self._max_steps,
                **self._usage_kw()))
            raise
        # Not asked again here, deliberately. Triage and planning are two
        # model round trips and a small budget can be gone by now — but
        # every route below opens a MissionRunner holding the same clock
        # and the same switch, and that runner asks before its first step.
        # A second check here would be a branch no test can make fail,
        # which is the kind of code that rots into a wrong answer.
        if plan is None or len(plan) == 1:
            # A plan the planner could not state, or a plan of one step, IS
            # the direct path.  Falling back is the honest move: the direct
            # runner is a complete agent, and a swarm that refuses to answer
            # because its planner misfired would be machinery failing the
            # question the machinery exists to serve.
            return self._direct(objective)
        return self._staged(objective, plan)

    # ── the clock and the switch, shared by every stage ─────────────────

    def _stop(self) -> Optional[Tuple[str, Optional[BudgetExhausted], str]]:
        """``(outcome, budget, reason)`` when this turn must stop, else ``None``.

        The same question :meth:`MissionRunner._stop` asks, asked at the
        three junctions a sub-mission's own check cannot see: before
        triage, before a redraw, and before the synthesizer.  Each of
        those is a model round trip this class makes itself.  Everywhere
        else — between plan steps, inside a step's retries — the next
        thing to happen is a runner holding this same clock, and asking
        here as well would be a branch no test could make fail.

        Same order and same words as the direct path's: a cancellation
        outranks a clock, because the person who threw the switch is the
        one who will read the sentence.
        """
        if cancelled(self._cancel):
            return "incomplete", None, CANCELLED
        exhausted = (self._deadline.exhausted()
                     if self._deadline is not None else None)
        if exhausted is not None:
            return "budget_exhausted", exhausted, ""
        return None

    def _finish_early(self, objective: str,
                      stop: Tuple[str, Optional[BudgetExhausted], str],
                      ) -> MissionTranscript:
        """Close a turn that stopped before it had any steps to report.

        Through the same renderer both other finishes use.  A turn that
        opened its stream owes it a ``mission_finished``, and one that never
        reached a sub-mission has nobody else to write it.
        """
        transcript = MissionTranscript(objective=objective,
                                       catalogue=list(self._offered))
        transcript.outcome, transcript.budget, transcript.reason = stop
        self._emit(MISSION_FINISHED, **_finished_record(
            started_at=self._started_at,
            outcome=transcript.outcome, steps=0, max_steps=self._max_steps,
            budget=transcript.budget, reason=transcript.reason))
        return transcript

    @property
    def _offered(self) -> List[str]:
        """Every tool name a sub-mission may call: the set, plus the store."""
        return [*self._tool_names, RESULT_TOOL]

    def _opening(self, objective: str) -> Dict[str, Any]:
        """The ``mission_started`` fields, whichever way this turn goes.

        Built once for both routes, and built to be the record the direct
        path's own :class:`MissionRunner` would have emitted: same catalogue,
        same gated names in catalogue order.  A consumer that could tell from
        the opening frame which way the router went would be reading an
        internal decision of this harness off a contract that promises it one
        vocabulary.
        """
        offered = self._offered
        return {
            "schema_version": SCHEMA_VERSION,
            "objective": objective,
            "catalogue": offered,
            "gated": [name for name in offered if name in self._gated],
            "max_steps": self._max_steps,
            "history": len(self._history),
            # The bus is the one owner of the string; the direct runner reads
            # the same property, so the two paths cannot disagree about
            # whether this mission's tool subprocesses were isolated.
            "sandbox": sandbox_of(self._bus),
            # Same OPTIONAL `run_id` field, from the same owner, for the
            # same reason as `profile` below it: the route this turn took
            # must not be readable off the opening frame.
            **_run_field(self._run_id),
            # Same OPTIONAL `protocol` field, from the same owner: absent
            # on an ordinary run, `native` on one that declared its tools as
            # functions. A staged turn's sub-missions speak whatever this
            # says, so the opening frame is true of every step under it.
            **_protocol_field(self._protocol),
            # Same OPTIONAL `profile` field the direct path's MissionRunner
            # emits, from the same owner — a consumer must not be able to tell
            # which route ran from the opening frame.
            **_profile_field(self._bus),
            # Through the direct path's own helper, not a second reading of
            # the same bus. This dict is a hand-written copy of a record
            # another module emits, which is precisely the arrangement that
            # let the swarm ship six grounding fields where the direct path
            # emitted ten.
            "audit_ref": audit_ref_of(self._bus),
        }

    # ── DIRECT: the path that already worked, untouched ─────────────────

    def _runner(self, *, system_message: str, max_steps: int,
                history: Sequence[Dict[str, str]] = (),
                observer: Optional[Observer] = None) -> MissionRunner:
        return MissionRunner(
            self._chat, self._bus, self._tool_names,
            system_message=system_message,
            max_steps=max_steps,
            validator=None,
            admits=self._admits,
            plane_changed=self._plane_changed,
            gated=self._gated,
            approvals=self._approvals,
            approval=self._approval,
            run_id=self._run_id,
            history=history,
            observer=observer,
            window=self._window,
            usage_fn=self._usage_fn,
            tool_calls_fn=self._tool_calls_fn,
            protocol=self._protocol,
            rate=self._rate,
            ledger=self._ledger,
            # The mission's clock and the mission's switch, not a fresh
            # one per stage: five sub-missions of a minute each must not
            # fit inside a one-minute budget.
            deadline=self._deadline,
            cancel=self._cancel,
            control=self._control,
            gate_wait_s=self._gate_wait_s,
            started_at=self._started_at,
        )

    def _direct(self, objective: str) -> MissionTranscript:
        runner = MissionRunner(
            self._chat, self._bus, self._tool_names,
            system_message=self._system_message,
            max_steps=self._max_steps,
            validator=self._validator,
            critic=self._critic,
            admits=self._admits,
            plane_changed=self._plane_changed,
            gated=self._gated,
            approvals=self._approvals,
            approval=self._approval,
            run_id=self._run_id,
            history=self._history,
            observer=(_OpenedAlready(self._emit)
                      if self._recording else None),
            window=self._window,
            usage_fn=self._usage_fn,
            tool_calls_fn=self._tool_calls_fn,
            protocol=self._protocol,
            rate=self._rate,
            # THE SAME ledger, not a fresh one. The direct path's runner
            # emits this turn's `mission_finished` itself, and the router
            # call that chose this path was already made — a runner with
            # its own ledger would report a turn that cost one call less
            # than it did.
            ledger=self._ledger,
            deadline=self._deadline,
            cancel=self._cancel,
            control=self._control,
            gate_wait_s=self._gate_wait_s,
            started_at=self._started_at,
        )
        return runner.run(objective)

    # ── TRIAGE ──────────────────────────────────────────────────────────

    def _route(self, objective: str) -> str:
        """``"direct"`` or ``"staged"``, and every failure is ``"direct"``.

        Fail-open to the cheap path on purpose: a router that cannot answer
        must cost the turn nothing, and the direct runner can still handle a
        complex question the slow way — the reverse mistake (ceremony around
        a small question) has no such recovery.
        """
        tools = ", ".join(self._tool_names) or "(none)"
        # Constant first, this run's tool set after it, the objective last —
        # `MissionRunner.seed`'s ordering discipline applied to a role that
        # is called once per turn rather than once per step.  Through
        # `stacked` so that every system turn this package builds is
        # assembled the same way, down to the whitespace.
        messages = self._role_messages(
            stacked(TRIAGE_PROMPT, f"Tools that exist here: {tools}"),
            objective)
        decision = self._json_reply(messages)
        route = str((decision or {}).get("route", "")).strip().lower()
        return route if route == "staged" else "direct"

    # ── PLAN ────────────────────────────────────────────────────────────

    def _short_catalogue(self) -> str:
        """Tool names with first-sentence descriptions — the planner's view.

        The full catalogue (schemas, argument grammars) belongs to the
        executor that will actually call the tool; the planner only decides
        *that* a tool step exists.

        This one **stays** a cut, and it is not a context bound wearing a
        character cap.  It is a *relevance* filter: an argument grammar is
        the answer to "how do I call this", which is the executor's
        question and not the planner's, and a planner shown fifty JSON
        schemas plans worse than one shown fifty sentences — on a window of
        any size.  What the window now decides is whether the sentences
        themselves fit, which is :meth:`_fit`'s business one level up.
        """
        lines = []
        for name in self._tool_names:
            info = self._bus.describe_tool(name)
            if "error" in info:
                continue
            desc = str(info.get("description") or "").strip()
            first = desc.split(". ")[0].strip()
            lines.append(f"- {name}: {first}" if first else f"- {name}")
        return "\n".join(lines) if lines else "(no tools available)"

    def _plan_rung_lines(self) -> str:
        """The offered rungs, described, in :data:`RUNGS` order."""
        return "\n".join(self._rung_plan_lines[rung] for rung in self._rungs)

    def _plan(self, objective: str,
              carried: Optional[Dict[str, str]] = None,
              failure: str = "") -> Optional[List[PlanStep]]:
        """A validated plan, retrying the parse once, or ``None``.

        ``carried`` and ``failure`` are the re-plan case: what already
        succeeded travels as summaries so the new plan builds on it instead
        of repeating it, and the failure is stated so the new plan routes
        around what did not work.
        """
        # Persona, then the role's constant instruction, then this run's
        # catalogue: the same most-constant-first order `MissionRunner.seed`
        # documents, so a redraw re-sends a prefix the endpoint has already
        # cached.  Everything that differs between the first plan and a
        # redraw — what succeeded, what failed — is in the user turn below.
        system = stacked(
            self._system_message,
            PLAN_PROMPT.format(max_steps=self._max_plan_steps,
                               rungs=self._plan_rung_lines()),
            "Tools that exist here:\n" + self._short_catalogue(),
        )
        user_parts = [objective]
        if carried:
            done = "\n".join(f"- {sid}: {summary}"
                             for sid, summary in carried.items())
            user_parts.append(
                "Already completed — build on these, do not repeat them:\n"
                + done)
        if failure:
            user_parts.append(
                f"The previous plan failed: {failure}\n"
                f"Plan a different route around that failure.")
        messages = self._role_messages(system, "\n\n".join(user_parts))

        for _attempt in range(2):
            decision = self._json_reply(messages)
            steps, problem = self._read_plan(decision)
            if steps is not None:
                return steps
            messages.append({"role": "assistant",
                             "content": json.dumps(decision or {})})
            messages.append({"role": "user", "content": problem})
        return None

    def _read_plan(self, decision: Optional[Dict[str, Any]]):
        """``(steps, "")`` or ``(None, problem)`` — mechanical, no judgement."""
        if not isinstance(decision, dict):
            return None, ('Reply with one JSON object: {"steps": [...]}')
        raw = decision.get("steps")
        if not isinstance(raw, list) or not raw:
            return None, ('The object needs a non-empty "steps" array.')
        if len(raw) > self._max_plan_steps:
            return None, (
                f"{len(raw)} steps is too many; the cap is "
                f"{self._max_plan_steps}. Merge or drop steps."
            )
        steps: List[PlanStep] = []
        seen: set = set()
        for position, entry in enumerate(raw):
            if not isinstance(entry, dict):
                return None, f"steps[{position}] must be an object."
            sid = str(entry.get("id") or f"s{position + 1}").strip()
            goal = str(entry.get("goal") or "").strip()
            rung = str(entry.get("rung") or "tool").strip().lower()
            needs = entry.get("needs") or []
            done = str(entry.get("done") or "").strip()
            if not goal:
                return None, f"steps[{position}] has no goal."
            if rung not in self._rungs:
                # Against the OFFERED rungs, not every rung that exists.
                # A plan tagged `code+sdk` where no SDK was declared is
                # rejected naming what is actually available, which is the
                # repair the planner can act on.
                return None, (
                    f'steps[{position}].rung is {rung!r}; it is one of '
                    f'{", ".join(self._rungs)}.'
                )
            if sid in seen:
                return None, f"step id {sid!r} appears twice."
            if not isinstance(needs, list) or any(
                    str(n) not in seen for n in needs):
                return None, (
                    f'steps[{position}].needs must name only EARLIER step '
                    f'ids; steps run in order.'
                )
            seen.add(sid)
            steps.append(PlanStep(id=sid, goal=goal, rung=rung,
                                  needs=[str(n) for n in needs], done=done))
        return steps, ""

    # ── STAGED: execute, gate, iterate, synthesize ──────────────────────

    # ── the checkpoint ──────────────────────────────────────────────────

    def _checkpoint(self, **facts: Any) -> None:
        """Write the staged run's progress into the run's metadata.

        Through :meth:`~core.durable.RunStore.update_meta` and never
        :meth:`~core.durable.RunStore.save`: this runner holds no
        :class:`~core.durable.Run` and must not start, because saving a
        record read before a step would stamp a ``last_seq`` that the
        step's own records have moved on — which is the reused-sequence bug
        :mod:`core.durable` was written around, reproduced by the one
        caller most likely to reproduce it.

        Into the *metadata* and not onto the stream, because a checkpoint
        is not an event.  The plan already reaches a watcher on the first
        ``step_started`` it produces, and each step's outcome reaches one
        as the records of the sub-mission that produced it.  What the
        metadata adds is an index a *restart* can read without replaying
        the log: which steps are done, and what they found.

        Never raises, for the reason :func:`~core.runtime.mission
        .persist_record` does not: a staged mission must not die because
        the disk it was being indexed on filled up.
        """
        if self._run_store is None or not self._run_id:
            return
        try:
            self._run_store.update_meta(self._run_id, **facts)
        except Exception:                       # pragma: no cover - defensive
            pass

    @staticmethod
    def _step_done(outcome: "_StepOutcome") -> Dict[str, str]:
        """One executed step as the metadata's ``steps_done`` entry.

        ``{id, goal, outcome, summary}`` — the word first and the prose
        second, so a restart can branch on the word without parsing the
        prose.  A failure's ``why`` goes in the same slot its success's
        ``summary`` would: the field answers "what came of this step", and
        two fields only one of which is ever populated is two fields to
        read wrong.

        ``goal`` is here because after a redraw this record is the ONLY
        place it lives.  The plan on the checkpoint is the plan as redrawn;
        a step that settled under the plan it replaced is not in it, so a
        resumed synthesis rebuilding that step from its id alone rendered
        it as ``s1 (s1)`` — the step's own account of itself, lost to the
        redraw that kept its result.  Read with ``.get`` on the way back
        in, so a run checkpointed before this field existed still resumes.

        :func:`_resumed_outcome` is the reader, and the two are written to
        be read together: this method decides which of ``summary`` and
        ``why`` the one slot holds, and that one decides which of them it
        comes back out as.
        """
        return {"id": outcome.step.id,
                "goal": outcome.step.goal,
                "outcome": "ok" if outcome.ok else "failed",
                "summary": outcome.summary if outcome.ok else outcome.why}

    def _staged(self, objective: str, plan: List[PlanStep],
                resumption: Optional[Any] = None) -> MissionTranscript:
        transcript = MissionTranscript(objective=objective,
                                       catalogue=list(self._offered),
                                       usage=self._ledger)
        # `run` opened the stream before triage; the plan did not exist then.
        # It travels on the first `step_started` instead. On a resumed turn
        # the numbering continues the log this stretch is being appended to,
        # and the first new `step_started` says that it does.
        stage = _StageObserver(
            self._emit,
            start_index=resumption.next_index if resumption else 0,
            resumed=resumption.as_record() if resumption else None)
        stage.announce(plan)
        # The plan, before the first step of it runs. A checkpoint written
        # after the work is a checkpoint that is missing exactly when the
        # work was what died.
        #
        # `steps_done` is restated rather than left alone, because the whole
        # list is what every later checkpoint writes: a resumed turn that
        # wrote `[]` here would erase the steps it is resuming past, and one
        # that wrote nothing would leave the plan and the progress written by
        # two different runs of two different lengths.
        self._checkpoint(plan=_plan_state(plan),
                         steps_done=list(_steps_done(resumption)),
                         replanned=bool(resumption.replanned)
                         if resumption else False)
        try:
            outcome = self._work_through(objective, plan, transcript, stage,
                                         resumption=resumption)
        finally:
            # The direct path's own renderer, not a second hand-listing of
            # the same record.
            self._emit(MISSION_FINISHED, **_finished_record(
                started_at=self._started_at,
                outcome=transcript.outcome,
                steps=len(transcript.steps),
                max_steps=self._max_steps,
                budget=transcript.budget,
                reason=transcript.reason,
                **self._usage_kw()))
        return outcome

    def _work_through(self, objective: str, plan: List[PlanStep],
                      transcript: MissionTranscript,
                      stage: _StageObserver,
                      resumption: Optional[Any] = None) -> MissionTranscript:
        budget = self._max_steps
        evidence: List[str] = []
        results: Dict[str, _StepOutcome] = {}
        replanned = False
        queue = list(plan)
        done: List[Dict[str, str]] = []

        if resumption is not None:
            # Everything the recorded stretch left behind, put back where
            # this loop keeps it — and nothing else. There is no message
            # tail to replay: a staged step's conversation belongs to the
            # sub-mission that had it and is thrown away when the step ends,
            # so what carries forward here is exactly what carried forward
            # the first time, the step's summary.
            done = list(_steps_done(resumption))
            results = {entry["id"]: _resumed_outcome(entry, plan)
                       for entry in done}
            evidence = list(resumption.evidence)
            replanned = bool(resumption.replanned)
            # `max_steps` bounds a MISSION and not a process, exactly as it
            # does across a direct resume: the tool turns the recorded
            # stretch spent count against it, so a plan that spent 5 of 8
            # has 3 left. See `Recorded.total_steps`, which is where the
            # caller works the total out.
            budget = max(0, self._max_steps - int(resumption.steps_spent))
            # A step the plan already has an outcome for is not run again.
            # One stopped at a gate is NOT such a step: nothing was called,
            # the decision belongs to a person, and a resume carrying their
            # approval is precisely the run that has to reach that call
            # again — so it is left on the queue. See `_steps_done`.
            queue = [step for step in plan if step.id not in results]

        # No check at the top of this loop either, for the reason `run` does
        # not repeat one after planning: the next thing that happens is a
        # sub-mission holding this clock, and it asks before its first step.
        # The two junctions the sub-missions genuinely cannot cover are the
        # replan and the synthesis — both model round trips this method makes
        # itself — and those are where the checks are.
        while queue:
            step = queue.pop(0)
            outcome, attempts, gathered, spent = self._execute_step(
                objective, step, results, stage, budget)
            budget -= spent
            # Every attempt is folded in, not only the one that stuck: the
            # transcript is the record of what ran, and a failed attempt's
            # tool output is still real evidence the grounding check may
            # need to support the answer with.
            sub = attempts[-1] if attempts else None
            for attempt in attempts:
                self._fold_in(transcript, attempt)
            evidence.extend(gathered)

            if sub is not None and sub.outcome == AWAITING_APPROVAL:
                # A person has to decide. The whole turn stops holding the
                # proposed call — staging changes nothing about who answers
                # for a gated act.
                transcript.outcome = AWAITING_APPROVAL
                transcript.awaiting = sub.awaiting
                # Checkpointed on the way out, like every other step: a
                # turn stopped for a person is the one a restart is most
                # likely to be looking at.
                done.append({"id": step.id, "outcome": AWAITING_APPROVAL,
                             "summary": "awaiting a person's decision"})
                self._checkpoint(steps_done=list(done))
                return transcript

            results[step.id] = outcome
            # Per step, not per plan: a checkpoint written when the plan
            # finishes is a checkpoint that never exists for the run that
            # needed it.
            done.append(self._step_done(outcome))
            self._checkpoint(steps_done=list(done))
            if outcome.ok:
                continue

            # A redraw is one or two more model round trips, and the step
            # that just failed may have failed BECAUSE the clock ran out
            # inside it — in which case replanning is the harness spending
            # the budget it has already exceeded on planning work it cannot
            # then do.
            stop = self._stop()
            if stop is not None:
                return self._stopped(transcript, stop)

            if not replanned and budget > 0:
                # One redraw around the failure, carrying what succeeded.
                replanned = True
                carried = {sid: r.summary for sid, r in results.items()
                           if r.ok}
                fresh = self._plan(objective, carried=carried,
                                   failure=f"step {step.id} "
                                           f"({step.goal}): {outcome.why}")
                if fresh:
                    # A COPY into the queue: `plan` below and `queue` here
                    # would otherwise be one list, and `queue.pop(0)` empties
                    # the plan the answer is then written from — which is a
                    # plan of nothing by the time the last step has run.
                    queue = list(fresh)
                    # The plan the answer is written from is the plan the
                    # steps belong to. This method used to keep the plan as
                    # DRAWN in `plan` and hand that to `_synthesize`, while
                    # a resume handed it the plan as CHECKPOINTED — two
                    # owners of one fact, each dropping the other's step
                    # results out of the synthesis. `_settled_order` takes
                    # the union of this plan and everything else that
                    # settled, so nothing that ran is lost either way.
                    plan = fresh
                    stage.announce(fresh)
                    # The plan as REDRAWN replaces the plan as drawn, for
                    # the reason `_StageObserver.announce` is called again:
                    # what is checkpointed has to be the plan the steps
                    # arriving next belong to.
                    self._checkpoint(plan=_plan_state(fresh),
                                     replanned=True)
                    continue
            # Out of moves for this step: the failure is now part of the
            # answer.  The steps still queued are dropped rather than run
            # against a hole — their `needs` may name the failed step.
            break

        # Synthesis is one more round trip, and the last one. A turn whose
        # clock ran out on the final step must not spend a further model
        # call writing prose about it: the outcome IS the answer here, and
        # the steps that did run are on the transcript either way.
        stop = self._stop()
        if stop is not None:
            return self._stopped(transcript, stop)
        return self._synthesize(objective, plan, results, evidence,
                                transcript)

    @staticmethod
    def _stopped(transcript: MissionTranscript,
                 stop: Tuple[str, Optional[BudgetExhausted], str],
                 ) -> MissionTranscript:
        """Write a :meth:`_stop` verdict onto the transcript and hand it back.

        No ``answer`` record follows, and that is the direct path's
        behaviour too: a run that stopped did not answer, and emitting the
        step summaries as one would be the harness writing the conclusion
        it was stopped before reaching.
        """
        transcript.outcome, transcript.budget, transcript.reason = stop
        return transcript

    def _execute_step(self, objective: str, step: PlanStep,
                      results: Dict[str, _StepOutcome],
                      stage: _StageObserver, budget: int):
        """Run one step with bounded retries.

        Returns ``(outcome, attempts, evidence, tool_turns_spent)`` —
        every attempt's transcript oldest first, and every attempt's tool
        evidence, so nothing that ran goes unrecorded.
        """
        if budget <= 0:
            return _StepOutcome(
                step=step, ok=False,
                why="the mission's step budget was exhausted before this "
                    "step could run",
            ), [], [], 0

        spent = 0
        failure = ""
        attempts: List[MissionTranscript] = []
        evidence: List[str] = []
        for attempt in range(1 + self._retries):
            # What the MISSION has left, unless a caller portioned it.
            # `budget` is already `max_steps` minus everything spent, so
            # the default lets a step that needs five tool turns take five
            # — and the turn still stops at `max_steps`, which is the bound
            # an operator actually set.
            allowance = (budget - spent if self._step_budget is None
                         else min(self._step_budget, budget - spent))
            if allowance <= 0:
                break
            stage.begin_stage()
            runner = self._runner(
                # The persona LEADS and the executor's paragraph follows it,
                # so every sub-mission of every staged turn opens with the
                # same bytes the direct path opens with.
                system_message=stacked(self._system_message, EXECUTE_PROMPT),
                max_steps=allowance,
                observer=stage,
            )
            sub = runner.run(
                self._step_objective(objective, step, results, failure))
            attempts.append(sub)
            evidence.extend(runner.store.evidence_texts())
            self._note_calls(runner)
            spent += len(sub.steps)
            if sub.outcome == AWAITING_APPROVAL:
                return (_StepOutcome(step=step, ok=False,
                                     why="awaiting approval"),
                        attempts, evidence, spent)

            ok, why = self._gate(step, sub)
            if ok:
                summary = self._bound_summary(sub.answer or "")
                # `evidence` and not `runner.store.evidence_texts()`: every
                # attempt at this step read something real, and the answer
                # is written over what the mission read rather than over
                # what its last attempt read.
                return (_StepOutcome(step=step, ok=True, summary=summary,
                                     evidence=list(evidence)),
                        attempts, evidence, spent)
            failure = why
        return (_StepOutcome(step=step, ok=False, why=failure or
                             "the step produced no checkable result",
                             evidence=list(evidence)),
                attempts, evidence, spent)

    def _step_objective(self, objective: str, step: PlanStep,
                        results: Dict[str, _StepOutcome],
                        failure: str = "") -> str:
        """The whole of what an executor sees about the mission.

        The mission's objective for context, the step, its rung, its
        success shape, and the summaries of exactly the earlier steps it
        declared it needs — never the raw output of any of them, and never
        the rest of the plan.  The executor's context still does not grow
        with the mission: everything here is a fixed handful of sentences
        whatever the plan's length.

        **The objective is here now, and it was not.**  It was withheld on
        the rule that an executor doing one step must not be told about the
        wider question, and what that bought was a step doing *less* than
        the question needed.  Live, 16 August: the objective asked for "the
        actor at the top of each run's actor list"; the planner wrote the
        step as "Retrieve details for run r-7"; the executor, reading only
        the step, called the view asking for ``totals`` and got no actor
        list at all — twice in three runs, on a different run each time.
        Nothing had gone wrong that any gate could see: the step said
        *details* and details came back.

        Marked as context and not as the task, because the failure it
        guards against is real too — an executor handed a whole objective
        answers the whole objective and the plan stops meaning anything.
        The paragraph above it (``EXECUTE_PROMPT``) says *do only this
        step*, and the line here says the same word again.
        """
        # `.get` with the plain-code fallback, and not a KeyError: a rung
        # this run does not offer cannot reach here through `_read_plan`,
        # and if a caller builds a `PlanStep` by hand, code without the
        # SDK is the honest degradation of code with it.
        sentence = self._rung_sentences.get(step.rung,
                                            self._rung_sentences["code"])
        parts = [f"The mission's objective, for context only — you are "
                 f"doing ONE step of a plan that answers it, and not the "
                 f"objective itself:\n{objective}",
                 f"Step {step.id} of a plan: {step.goal}",
                 f"Do it via: {sentence}"]
        if step.done:
            parts.append(f"Success looks like: {step.done}")
        needed = [(sid, results[sid].summary) for sid in step.needs
                  if sid in results and results[sid].ok]
        if needed:
            lines = "\n".join(f"- {sid}: {summary}"
                              for sid, summary in needed)
            parts.append(f"Results from earlier steps you need:\n{lines}")
        if failure:
            parts.append(
                f"Your previous attempt at this step failed: {failure}\n"
                f"Do not repeat the same call unchanged.")
        return "\n\n".join(parts)

    # ── GATE ────────────────────────────────────────────────────────────

    def _gate(self, step: PlanStep, sub: MissionTranscript):
        """``(ok, why)`` — mechanical verdicts first, the model last.

        The runtime decides everything it can decide: an executor that
        never answered, or answered without one successful tool call,
        failed no matter how fluent its text was.  Only when those pass
        and the step stated a ``done`` condition is the model asked — one
        binary question about the reported result, not about the world.
        """
        if not sub.completed:
            return False, (
                f"the step ended without a result ({sub.outcome})"
                + (f": {sub.steps[-1].error}" if sub.steps
                   and sub.steps[-1].error else "")
            )
        acted = any(call.tool and not call.refused
                    and call.tool != RESULT_TOOL
                    for step in sub.steps for call in _dispatched(step))
        if not acted:
            return False, (
                "the step made no successful tool call, so its result is "
                "unsupported by anything that actually ran"
            )
        if not step.done:
            return True, ""

        messages = [
            {"role": "system", "content": GATE_PROMPT},
            {"role": "user", "content": (
                f"Step goal: {step.goal}\n"
                f"Success looks like: {step.done}\n"
                f"The step reported: {self._bound_summary(sub.answer or '')}"
            )},
        ]
        decision = self._json_reply(messages)
        if decision is None or "pass" not in decision:
            # A gate that cannot say no has not said yes — but a gate that
            # cannot PARSE must not fail work that mechanically succeeded.
            # The mechanical checks above already held; the LLM layer is
            # advisory refinement on top of them.
            return True, ""
        if bool(decision.get("pass")):
            return True, ""
        return False, str(decision.get("why") or
                          "the result did not match the step's own "
                          "success condition")

    # ── SYNTHESIZE ──────────────────────────────────────────────────────

    #: The heading the whole tool output goes under in the synthesizer's
    #: user turn.  Named rather than inlined because a test reads it and a
    #: second spelling of it would be a test that passes against nothing.
    EVIDENCE_HEADER = ("What the tools actually returned, oldest first — "
                       "quote identifiers and figures from here:")

    def _settled_order(self, plan: Sequence[PlanStep],
                       results: Dict[str, _StepOutcome]) -> List[str]:
        """Which steps the answer is written from: plan order, then arrival.

        The current plan's ids first, in the plan's own order, then every
        other settled id in the order its step finished.  A step that ran
        and settled is evidence whether or not the plan it belonged to is
        still the current one — which is exactly the case a redraw makes,
        live and resumed alike.
        """
        order = [step.id for step in plan]
        order.extend(sid for sid in results if sid not in order)
        return order

    def _result_lines(self, order: Sequence[str], plan: Sequence[PlanStep],
                      results: Dict[str, _StepOutcome]) -> List[str]:
        """One line per step: what it was for, and what came of it."""
        goals = {step.id: step.goal for step in plan}
        lines = []
        for sid in order:
            outcome = results.get(sid)
            goal = goals.get(sid) or (outcome.step.goal if outcome else sid)
            if outcome is None:
                lines.append(f"- {sid} ({goal}): NOT RUN — an "
                             f"earlier step failed first")
            elif outcome.ok:
                lines.append(f"- {sid} ({goal}): {outcome.summary}")
            else:
                lines.append(f"- {sid} ({goal}): FAILED — {outcome.why}")
        return lines

    @staticmethod
    def _evidence_blocks(order: Sequence[str],
                         results: Dict[str, _StepOutcome],
                         evidence: Sequence[str]) -> List[tuple]:
        """``(label, text)`` for everything this turn's tools returned.

        Attributed to the step that read it where a step claims it, and
        labelled ``earlier`` where nothing does — which on a resumed turn
        is the whole of the recorded stretch, read back off the log rather
        than out of a store this process ever held.  Unattributed first,
        because that is the order it happened in and the order
        :meth:`_synthesis_messages` drops it in.

        Deduplicated on the text, once across the turn: two steps that read
        the same view are one thing to quote, and a window spent twice on
        it is a window spent on nothing.
        """
        claimed: set = set()
        blocks: List[tuple] = []
        for sid in order:
            outcome = results.get(sid)
            if outcome is None:
                continue
            for text in outcome.evidence:
                if text and text not in claimed:
                    claimed.add(text)
                    blocks.append((sid, text))
        earlier: List[tuple] = []
        for text in evidence:
            if text and text not in claimed:
                claimed.add(text)
                earlier.append(("earlier", text))
        return earlier + blocks

    def _synthesis_user(self, objective: str, lines: Sequence[str],
                        blocks: Sequence[tuple], dropped: int) -> str:
        """The synthesizer's user turn: the step lines, then the results.

        The note about what was left out is written whether or not anything
        survived it — a window small enough to drop *every* result is
        exactly the run whose answer must not read as though there were
        none.
        """
        parts = [f"Objective: {objective}\n\nStep results:\n"
                 + "\n".join(lines)]
        if dropped:
            parts.append(f"({dropped} tool result(s) left out to fit the "
                         f"context window; the whole of each is in the "
                         f"mission's result store.)")
        if blocks:
            parts.append(self.EVIDENCE_HEADER + "\n" + "\n\n".join(
                f"[{label}] {body}" for label, body in blocks))
        return "\n\n".join(parts)

    def _synthesis_messages(self, objective: str, plan: Sequence[PlanStep],
                            results: Dict[str, _StepOutcome],
                            evidence: Sequence[str]):
        """``(messages, step lines)`` — as much of the truth as fits.

        **The whole of every settled step's tool output goes in here**, and
        that is a reversal of what this class used to promise.  Raw tool
        output was kept out of the synthesizer on the argument that a step's
        summary is what travels; the live run of 16 August is what that cost.
        Two governed views of 34 KB each were read, summarised into 1.2 KB
        of prose apiece, and the answer to "name the actor at the top of its
        actor list" was *"the actor list for run r-7 was not reported in the
        step results"*.  It had been read.  Nothing downstream of the step
        that read it was allowed to see it.

        What bounds it now is the window and not a number: everything goes
        in, and if the assembled prompt does not fit, whole results are
        dropped **oldest first** — :data:`~core.runtime.context_window
        .EVICTION_ORDER`'s policy (tool output before conversation, oldest
        before newest) applied where the content actually is, rather than
        left to :meth:`MissionWindow.fit`, which can only drop whole
        messages and would take the step lines with them.  :meth:`_fit`
        still has the last word on the list it is handed.

        On a small window this degrades to what it always did — the step
        summaries alone — and says so in the prompt.
        """
        order = self._settled_order(plan, results)
        lines = self._result_lines(order, plan, results)
        blocks = self._evidence_blocks(order, results, evidence)
        system = stacked(self._system_message, SYNTHESIZE_PROMPT)
        kept = list(blocks)
        while True:
            messages = self._fit(self._role_messages(
                system, self._synthesis_user(objective, lines, kept,
                                             len(blocks) - len(kept))))
            if not kept or self._window is None:
                return messages, lines
            if self._window.estimate(messages) <= self._window.limit_tokens:
                return messages, lines
            kept.pop(0)

    def _synthesize(self, objective: str, plan: List[PlanStep],
                    results: Dict[str, _StepOutcome],
                    evidence: List[str],
                    transcript: MissionTranscript) -> MissionTranscript:
        messages, lines = self._synthesis_messages(
            objective, plan, results, evidence)
        answer = str(self._plain_chat(messages) or "").strip()
        self._spent()
        if not answer:
            # The synthesizer said nothing.  The step results themselves are
            # the honest fallback — facts the gates passed, not prose.
            answer = ("The mission's steps completed as follows and no "
                      "synthesis could be produced:\n" + "\n".join(lines))

        answer, report = self._ground(answer, messages, evidence)
        transcript.answer = answer
        transcript.grounding = report
        # A plan step with no outcome at all, not a count: `results` may
        # now hold ids the current plan does not (a redraw settled them),
        # so `len(results) < len(plan)` could be false of a plan step that
        # never ran.
        failed = (any(not r.ok for r in results.values())
                  or any(step.id not in results for step in plan))
        if report is not None and report.caveat:
            transcript.outcome = "answered_with_caveat"
        else:
            transcript.outcome = "answered_with_caveat" if failed else "answered"
        if report is not None:
            # Through the SAME renderer the direct path uses. Hand-listing the
            # fields here is how this record came to be six of the ten the
            # contract requires: a consumer switching on `event` gets one shape
            # per event or it is not a vocabulary.
            #
            # And the second opinion through the SAME function, for the
            # same reason one level down: `advisory: true` is what stops a
            # model's verdict being read as a mechanical one, and a
            # hand-built row here is a row that will one day be missing it.
            # Asked on the clean path too — no rule in `core.critic
            # .triggers` fires on a grounded answer — so the decision has
            # one owner rather than a copy of the trigger policy in `if`s.
            caveat = report.caveat or ""
            drafted = (transcript.answer[:-len(caveat)]
                       if caveat and transcript.answer.endswith(caveat)
                       else transcript.answer)
            self._emit(GROUNDING, **_grounding_record(
                report, repairs=report.repairs, caveat=caveat,
                # The DRAFT, not the caveated text: the critic is asked
                # about what the model wrote, and the caveat is this
                # harness's own sentence about it — a critic shown its own
                # harness's caveat is being asked to review the grader.
                opinions=second_opinion(
                    self._critic, objective, drafted, evidence,
                    unsupported=report.unsupported,
                    answered_with_caveat=bool(caveat))))
        # `_last_spent` and not the synthesizer's own call, because
        # `_ground` above may have spent a repair turn — and then the text
        # on this record is the repair's, not the draft's. The per-call
        # field is the cost of the call that produced the text beside it;
        # the run's total is on `mission_finished`.
        self._emit(ANSWER, text=transcript.answer, outcome=transcript.outcome,
                   **self._last_spent)
        return transcript

    def _note_calls(self, runner) -> None:
        """Fold one sub-mission's dispatched tools into the turn's set.

        A direct mission's plane-claim check reads one store; a staged
        turn's answer is synthesized over several, and a claim to have used
        the SDK is true if *any* step used it.  One owner still — each
        store's own record of what it dispatched — merged, not re-derived.
        """
        for name in runner.store.called_tools():
            if name not in self._called:
                self._called.append(name)

    def _ground(self, answer: str, messages: List[Dict[str, str]],
                evidence: List[str]):
        """The same discipline the direct path applies to its answer.

        The validator checks the synthesized answer against the evidence
        every sub-mission's tools actually returned; one repair turn, then
        the caveat.  Skipped entirely when no validator was configured,
        exactly like the direct path.
        """
        if self._validator is None:
            return answer, None
        report = self._validator.validate(answer, evidence,
                                          called=self._called)
        if not report.ran:
            return answer, GroundingReport(results=report.results)
        repairs = 0
        while not report.grounded and repairs < self._validator.max_repairs:
            repairs += 1
            # The interim report, through the same renderer the direct path
            # uses.  A repair turn is a whole extra round-trip to the model
            # and from outside looks exactly like a stall; the staged path
            # spent them silently and a watcher saw only the verdict, minutes
            # later, with no way to tell the wait from a hang.  `repairing`
            # marks it as work in progress — the record that follows is the
            # verdict.
            self._emit(GROUNDING, **_grounding_record(
                report, repairs=repairs, repairing=True))
            messages.append({"role": "assistant", "content": answer})
            messages.append({"role": "user",
                             "content": self._validator.repair_prompt(report)})
            answer = str(
                self._plain_chat(self._fit(messages)) or "").strip() or answer
            self._spent()
            report = self._validator.validate(answer, evidence,
                                              called=self._called)
        if not report.grounded:
            caveat = self._validator.caveat(report)
            return answer + caveat, GroundingReport(
                results=report.results, repairs=repairs, caveat=caveat)
        return answer, GroundingReport(results=report.results,
                                       repairs=repairs)

    # ── plumbing ────────────────────────────────────────────────────────

    def _fold_in(self, transcript: MissionTranscript,
                 sub: Optional[MissionTranscript]) -> None:
        """A sub-mission's steps onto the one transcript, renumbered."""
        if sub is None:
            return
        for step in sub.steps:
            step.index = len(transcript.steps)
            transcript.steps.append(step)

    def _bound_summary(self, text: str) -> str:
        """A step's reported result, whole unless a caller asked for a cut.

        ``summary_chars=None`` — the default — returns the executor's own
        sentence entire, whitespace collapsed, because the thing that
        bounds it is the window of the prompt it lands in and not a number
        chosen here.  It was 1,200 characters by default, and 1,200
        characters is what reached the synthesizer of the 16 August run:
        a 34,000-character governed view arrived as 1.2 KB of prose about
        it, and the answer said the actor list "was not reported".

        An int is a caller who wants the cut, and gets exactly the cut
        this always made, marker included.
        """
        text = " ".join(str(text).split())
        if self._summary_chars is None or len(text) <= self._summary_chars:
            return text
        return (text[:self._summary_chars]
                + f" … [cut at {self._summary_chars} characters]")

    def _json_reply(self, messages: List[Dict[str, str]]) -> Optional[Dict[str, Any]]:
        """One JSON object from the plain backend, or ``None``.  Never raises.

        The router, the planner and every gate come through here, and all
        three are asked for an object in prose: *"Reply with exactly one
        JSON object and nothing else"*.  A 20B obeys that most of the
        time, which is the problem — the times it wraps the object in a
        sentence, ``json.loads`` fails and the caller falls open (the
        router to DIRECT, the gate to pass).  The fall-open is correct
        behaviour and it is also **a second explanation for every bad
        decision this path makes**.

        So where the backend has the grammar constraint —
        ``BackendCapabilities.supports_json_mode``, true on openai, local
        and mistral, and probed working on the reference deployment's vLLM
        0.14.1 — the request carries ``response_format={"type":
        "json_object"}`` and the decoder cannot emit anything but a valid
        object.  Free: no extra tokens, no extra call.

        **This does not improve anybody's judgement and is not expected
        to.**  The A/B in ``ROADMAP.md`` §2.5 has the router staging a
        ``[quick web]`` request; a router that stages a quick lookup while
        emitting perfectly-formed JSON stages it just the same.  What this
        removes is the confound: a staged quick lookup after this is a
        routing decision that was actually made, not a reply nobody could
        parse.  Routing heuristics are untouched here on purpose.

        The synthesizer does NOT come through here — it writes prose, and
        a grammar that forbids prose would forbid the answer.
        """
        extra = ({"response_format": {"type": "json_object"}}
                 if self._json_mode else {})
        try:
            reply = str(self._plain_chat(self._fit(messages), **extra) or "")
        except Exception:
            # Nothing to fold: `last_usage` is cleared at the start of
            # every call, so a call that raised reports nothing and adding
            # it would be adding None.
            return None
        # Folded even when the reply turns out to be unparseable below — a
        # call that produced garbage was still billed.
        self._spent()
        text = _FENCE.sub("", reply.strip()).strip()
        if not text:
            return None
        try:
            decision = json.loads(text)
        except json.JSONDecodeError:
            return None
        return decision if isinstance(decision, dict) else None
