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
* **EXECUTE** — one step, one small child :class:`~core.runtime.run.Run`
  of the turn's, under the same supervisor and the same operator ceiling
  as the whole turn — the same objects, by identity.  There
  is no per-step slice of a budget any more: a step takes the turns it
  needs, and the turn stops where an operator said it stops or where the
  supervisor says it is going round.  The sub-mission's transcript holds
  only its own step's tool results; earlier steps arrive as short
  summaries, never as their raw output.
* **GATE** — did the step produce what the plan needed.  Mechanical
  first (the runner answered; a tool call succeeded), because a check
  the runtime can evaluate cannot be talked out of its verdict.  An LLM
  gate runs only where mechanics cannot decide — the step stated a
  "done" condition — and it is asked a binary question.
* **SYNTHESIZE** — the final answer, written from the accumulated step
  results and nothing else, then held to the same grounding validator
  the direct path uses.

Failure is contained, never silent, and **who decides is the supervisor**
(:mod:`core.runtime.supervisor`).  A step whose gate says no is not
retried a fixed number of times: the failed gate is a signal, the
reviewing model is shown the step and the gate's sentence, and it says
``nudge`` (try again with this note), ``replan`` (the plan is what is
wrong — redraw it around what already succeeded), ``progressing`` (the
gate is wrong and the step stands) or ``stuck`` (this step has failed;
the plan carries on past it and the answer says so).  Review turns are
capped for the whole turn, so retries and redraws are bounded by the
same arithmetic rather than by two counters nobody can relate to each
other.  There is no path that stalls and no path that reports success it
did not have.

Everything a sub-mission does still goes through the one
:class:`~core.tools.bus.ToolBus`; the closed tool set, the gating and
the audit are exactly the direct path's.  The observer vocabulary is
:mod:`core.runtime.mission_stream`, unchanged — a watcher sees one
mission with more steps, and a sub-mission proposing a gated tool ends
the whole turn at ``awaiting_approval`` holding the proposed call, the
same as it always did.

Approvals are the direct path's, entirely.  A sub-mission *is* a whole
:class:`~core.runtime.run.Run`, sharing this turn's
:class:`~core.runtime.run.Store`, so it writes the durable request itself
and the ``approval_id`` reaches a watcher on the ``gate_requested`` its
branch passes through with the fields untouched — there is no second copy
of the id to drift.  The one
:class:`~core.runtime.approvals.ApprovalTicket` is on that shared store
too; it spends itself once, on the dispatch that uses it, so a plan of
five steps that calls the approved tool in the third has spent exactly
one decision.

**This class is a composition over one** :class:`~core.runtime.run.Run`.
Its constructor is that class's adapter with the staging knobs beside it —
thirty parameters in, six objects out — and every stage of a turn is a
child of the one run those six make: one plane, one durable log, one
observer, one model and therefore one ledger, one clock, one supervisor.
What used to be here instead was a second copy of ten of them, which is
what ``ROADMAP.md`` §2.6.1's table is a list of.

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
from dataclasses import dataclass, field, replace
from typing import (
    Any, Callable, Dict, List, Mapping, Optional, Sequence,
)

from core.bounding import bound_result
from core.durable import RunStore
from core.runtime.control import GATE_WAIT_S
from core.budgets import Deadline
from core.runtime.approvals import ApprovalStore, ApprovalTicket
from core.runtime.context_window import MissionWindow
from core.runtime.grounding import GroundingValidator
from core.runtime.mission import (
    AWAITING_APPROVAL, JSON_PROTOCOL, MissionTranscript, _finished_record,
    stacked,
)
from core.runtime.mission_stream import (
    ANSWER, MISSION_FINISHED, MISSION_STARTED, Observer,
)
from core.runtime.results import RESULT_TOOL
from core.runtime.run import (
    Bounds, Model, Observer as RunObserver, Personality, Run, Store, ToolPlane,
)
from core.runtime.supervisor import NUDGE, PROGRESSING, REPLAN
from core.runtime.usage import Ledger, Rate

__all__ = ["SwarmRunner", "PlanStep", "RUNGS", "RUNGS_WITHOUT_SDK",
           "SDK_RUNG", "MAX_PLAN_STEPS"]

#: How long a plan may be when nothing else bounds it.
#:
#: A cap on a **list the planner writes in one reply**, not on work: every
#: step of a plan of eight may take as many turns as it needs.  It exists
#: because a planner that answers a two-part question with a plan of
#: nineteen steps has misread the question, and the cheapest place to say
#: so is in the prompt that asks for the plan and in the refusal that reads
#: it back (:meth:`SwarmRunner._read_plan`).
#:
#: It used to be derived from the mission's step budget — the longest plan
#: whose every step could still afford a call and an answer — and there is
#: no such budget to derive it from now.  Where an operator DID set a
#: ceiling that derivation still applies, because it is still true.
MAX_PLAN_STEPS = 8

_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.MULTILINE)

#: What a child run's records are called, for the observer.  Neither name
#: reaches the wire — an OPTIONAL ``branch`` field is the parallel-children
#: lane's (``ROADMAP.md`` §2.6.2, item 5) — and they exist so that the two
#: kinds of child are named where they are made: the direct route is the
#: mission continued, a plan step is one stage of it.  A step's branch is
#: named for the step, so the day the field does reach the wire a consumer
#: can demultiplex by plan id without this file changing.
_DIRECT = "direct"

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
    #: Whether the supervisor said the PLAN is what is wrong, rather than
    #: this step.  The one thing that redraws a plan now — see
    #: :meth:`SwarmRunner._work_through`, which used to redraw on any
    #: failure, once, from a counter.
    replan: bool = False


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


class SwarmRunner:
    """Triage, then either one mission or a staged handful of small ones.

    Constructed exactly like a :class:`~core.runtime.mission.MissionRunner`
    plus the staging knobs, so the CLI can build either from the same
    material — and, like that class, the constructor is an **adapter**:
    the parameters below find the six objects of
    :mod:`core.runtime.run` and what this class holds is one
    :class:`~core.runtime.run.Run` built from them.  The same ``chat_fn``
    drives every role — one leased endpoint, no second model.

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
    max_steps:
        An operator's ceiling on model turns for the WHOLE turn — every
        sub-mission's steps summed — or ``0``, the default, for no ceiling.
        Exactly :class:`~core.runtime.mission.MissionRunner`'s parameter,
        with the same meaning and the same default — it is one field of
        the one :class:`~core.runtime.run.Bounds` — because a staged turn
        is a mission and an operator who typed ``--mission-steps 20``
        typed it once.
    supervisor:
        The turn's :class:`~core.runtime.supervisor.Supervisor`, or
        ``None``.  **One per turn**, shared exactly as the clock and the
        switch are — one :class:`~core.runtime.run.Bounds`, inherited by
        every child — so a plan that loops *across* its steps — step two reading
        what step one read, step three reading it again — is a pattern
        something can see, and so the review budget is the turn's rather
        than five copies of it.

        It is also what this class asks about a **failed gate**, which is
        the one signal reported to it rather than noticed by it: only the
        plan knows what a step promised.  ``None`` is a staged turn with
        no retries and no redraw at all — a gate that says no settles the
        step as failed and the plan carries on — which is the honest
        reading of a turn nobody is watching, and is why the CLI always
        builds one.
    max_plan_steps:
        Hard cap on plan **length**, which is a different kind of number
        from the ones that were deleted around it: it bounds a list the
        planner writes in one reply, it is stated in the planner's own
        prompt, and a longer plan is refused at :meth:`_read_plan` with a
        sentence telling it to merge steps.  Nothing about it bounds how
        much work a step may do.

        ``None`` — the default — is :data:`MAX_PLAN_STEPS`, and no more
        than what an operator's ceiling could pay for when there is one
        (``max(2, max_steps // 2)``, the longest plan whose every step can
        still afford a call and an answer).
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
        **The one window for the whole turn.**  It lives on the one
        :class:`~core.runtime.run.Model` every stage shares — see
        :class:`~core.runtime.mission.MissionRunner`'s ``window``
        parameter — and, since the live run of 16 August, it is applied to
        this runner's *own* four roles as well: the router, the
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
        :class:`~core.runtime.mission.MissionRunner` takes it, and one
        :class:`~core.runtime.run.Store` shared with every sub-mission.

        **One writer**, still, and it is the turn's
        :class:`~core.runtime.run.Observer`: a stage emits into a *branch*
        of it, and a branch is a caller of the parent's ``emit`` rather
        than a second one beside it, so a record is scrubbed once and
        appended once whichever child spoke.  It used to be stated by
        withholding the log from the sub-runner — it was handed the id and
        not the store — which was half an object where the property wanted
        one.
    usage_fn, rate:
        As :class:`~core.runtime.mission.MissionRunner`'s, and they live on
        the one :class:`~core.runtime.run.Model` every stage shares.  The
        staged path makes model calls of its own — the router, the
        planner, each gate, the synthesizer and its repair turns — outside
        any sub-mission, and every one of them folds through
        :meth:`~core.runtime.run.Model.spend` into the same
        :class:`~core.runtime.usage.Ledger` a sub-mission's steps fold
        into.  One ledger per turn, ONE place the arithmetic happens: this
        class used to hold its own copy of those four lines, and a second
        accumulator is how the opening frame once carried six of ten
        grounding fields.  Numbers are the half nobody notices is wrong.
    protocol, tool_calls_fn:
        As :class:`~core.runtime.mission.MissionRunner`'s, on the one
        :class:`~core.runtime.run.Model` every stage shares: a rung's
        execution is an ordinary mission loop, and a
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
        give a five-step plan five times what was asked for.  ``max_steps``
        travels the same way now and used to travel the other: it was
        *portioned*, a slice per sub-mission, and the slice is what starved
        the live run of 16 August — a step needing two governed views and
        two store reads had four turns, exhausted them, failed its gate on
        ``budget_exhausted`` and had the plan redrawn around whatever had
        fitted.  One turn, one ceiling, one clock, one supervisor.
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
        :meth:`~core.runtime.run.Bounds.stop` is asked before each of
        those round trips.
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
        gated: Sequence[str] = (),
        approvals: Optional[ApprovalStore] = None,
        approval: Optional[ApprovalTicket] = None,
        history: Sequence[Dict[str, str]] = (),
        observer: Optional[Observer] = None,
        plain_chat_fn: Optional[Callable[..., Any]] = None,
        json_mode: bool = False,
        max_plan_steps: Optional[int] = None,
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
        memory: Any = None,
    ):
        # THE ADAPTER, and it is `MissionRunner.__init__`'s adapter with
        # the staging knobs beside it: the same thirty parameters find the
        # same six objects, and what is built out of them is ONE `Run` that
        # every stage of this turn is a child of. Nothing here decides
        # anything — every line is a parameter finding the object that owns
        # it — and the constructor's surface is unchanged because `core/cli
        # .py` and this class's conformance suite hold it.
        store = Store(runs=run_store, run_id=run_id, approvals=approvals,
                      ticket=approval)
        # ONE plane for the whole turn, shared by every sub-mission. Each
        # used to build its own from the manifest's list, so a tool the bus
        # grew mid-turn was offered to the step that learned of it and to
        # no later one — two views of what may be called, which is the
        # thing a closed set exists to be one of. The ticket's subtraction
        # happens once, inside `Run`, so the opening frame and every stage
        # read the same gated set.
        plane = ToolPlane(bus=bus, offered=tool_names, store_tool=RESULT_TOOL,
                          gated=gated, admits=admits,
                          plane_changed=plane_changed)
        # `memory` is the TURN's, exactly as `grounding` and `critic` are:
        # the direct route inherits it whole because that route is a whole
        # agent answering the whole question, and `_execute_step` strikes
        # it out of a plan step's personality for the same reason it
        # strikes out the validator — see the comment there.
        personality = Personality(system_message=system_message,
                                  history=history, grounding=validator,
                                  critic=critic, sdk_import=sdk_import,
                                  memory=memory)
        # ONE model, therefore ONE ledger: `run` puts a fresh one on it and
        # every child shares the object, so the router's call, the
        # planner's, every sub-mission's step and the synthesizer's repair
        # all fold into the same totals. `plain` is never `None` here — a
        # caller that handed no plain function is asking for the roles to
        # go through the same one the steps do.
        model = Model(ask=chat_fn, plain=plain_chat_fn or chat_fn,
                      protocol=protocol, window=window,
                      # Only ever consulted by `_json_reply`, and only ever
                      # true for a caller that also handed in a
                      # `plain_chat_fn` able to take the keyword: a runner
                      # given a bare `chat_fn` keeps the old call shape.
                      json_mode=bool(json_mode) and plain_chat_fn is not None,
                      usage_fn=usage_fn, tool_calls_fn=tool_calls_fn,
                      rate=rate)
        # ONE bounds: one clock, one switch, one channel and ONE supervisor
        # for the whole turn — handed to every child by identity, so a plan
        # that loops ACROSS its steps is a pattern something can see and the
        # review budget is the turn's rather than five copies of it. Zero
        # steps is NO CEILING and is the default.
        bounds = Bounds(deadline=deadline, cancel=cancel, control=control,
                        gate_wait_s=gate_wait_s, max_steps=max(0, int(max_steps)),
                        supervisor=supervisor)
        #: ONE observer for the whole turn, and the one place a record is
        #: scrubbed and the durable log is written. Every stage emits into
        #: a BRANCH of this — see `Observer.branch` — so a sub-runner
        #: cannot reach a sink without passing through here.
        self._observer = RunObserver(observer, store=store)
        #: The turn, as one loop object. This class is a composition over
        #: it: the six objects above are read back off it below, so there
        #: is one copy of each fact rather than one here and one there.
        self._run = Run(personality, plane, bounds, store, self._observer,
                        model)

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
        #: place `evidence` does — the sub-mission's own store — and the
        #: plane-claim check needs the union over the whole turn, not one
        #: step's.  See `MissionResultStore.called_tools`.
        self._called: List[str] = []
        self._started_at: Optional[float] = None
        #: Where this turn's global step numbering begins: `0` cold, and a
        #: resumed stretch's `next_index` when there is a log to continue.
        #: Handed to each stage's branch, which is what allocates.
        self._start_index = 0
        # A cap on the LENGTH of a list the planner writes, and no longer
        # than an operator's ceiling could pay for when there is one. See
        # the class docstring for why this is not one of the numbers that
        # was deleted around it.
        ceiling = self._run.bounds.max_steps
        self._max_plan_steps = (
            max(1, int(max_plan_steps)) if max_plan_steps is not None
            else (min(MAX_PLAN_STEPS, max(2, ceiling // 2))
                  if ceiling else MAX_PLAN_STEPS))
        #: ``None`` is "the window decides": a step's result travels whole
        #: and `_fit` bounds the prompt it lands in. An int is a caller
        #: asking for a cut, in bytes, through `core.bounding.bound_result`.
        self._summary_chars = (max(200, int(summary_chars))
                               if summary_chars is not None else None)

        # The rungs THIS run offers, and what each one says.  Resolved once
        # here rather than at each use, so the planner's prose, the plan
        # validator and the executor's instruction cannot disagree about
        # which routes exist — a planner offered a rung the validator then
        # rejects burns a re-plan on the harness's own inconsistency.
        sdk = self._run.personality.sdk_import
        self._rungs = RUNGS if sdk else RUNGS_WITHOUT_SDK
        self._rung_sentences = dict(_RUNG_SENTENCES)
        self._rung_plan_lines = dict(_RUNG_PLAN_LINES)
        if sdk:
            self._rung_sentences[SDK_RUNG] = sdk_rung_sentence(sdk)
            self._rung_plan_lines[SDK_RUNG] = sdk_rung_plan_line(sdk)

    # ── the six objects, read off the one that holds them ───────────────
    #
    # Not copied into fields of this class.  A second copy of "what the
    # ceiling is" or "which tools are gated" is exactly the arrangement
    # this phase is deleting: the `Run` holds each fact once and these
    # read it, so a child and its parent cannot disagree about any of them.

    @property
    def _model(self) -> Model:
        """What this turn asks, how it reads the reply, what the call cost."""
        return self._run.model

    @property
    def _bounds(self) -> Bounds:
        """Everything that can stop this turn — one clock, one supervisor."""
        return self._run.bounds

    @property
    def _plane(self) -> ToolPlane:
        """The only way out, and the live set of what may be called now."""
        return self._run.plane

    @property
    def _persona(self) -> str:
        """The bytes every role and every sub-mission of this turn opens
        with.  One string, so the prefix a served endpoint has cached is
        the same one whichever stage is speaking."""
        return self._run.personality.system_message

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

        The turns come off the :class:`~core.runtime.run.Personality`,
        which validated them once at construction: a role seeded from a
        second copy of the history is a role that can be seeded from a
        malformed one.
        """
        return [{"role": "system", "content": system},
                *[dict(turn) for turn in self._run.personality.history],
                {"role": "user", "content": user}]

    def _fit(self, messages: Sequence[Dict[str, str]]) -> List[Dict[str, str]]:
        """*messages*, inside the one window this turn was given.

        ``pinned=1`` is the role's system turn and nothing else: the
        instruction — and, for the planner, the tool catalogue — is what a
        role cannot be without.  Everything after it is evicted
        oldest-first by :meth:`~core.runtime.context_window.MissionWindow
        .fit`, which never drops the newest round trip, so the question
        itself always survives.

        **Not** :meth:`core.runtime.run.Run._fit`, and the difference is
        the reason there are two: that one bounds a *conversation* — it
        pins the whole seeded prefix, announces the compaction on the
        stream and heals a native request whose tool messages lost their
        call — and these four calls are none of those things.  They are
        single round trips with no ``step_started`` to ride and no tool
        namespace declared.  One window (``Model.window``, the object both
        read); two ways of fitting into it, because a role and a loop are
        two shapes of request.

        No window is this class as it ran before there was one: the list
        goes out whole.
        """
        window = self._model.window
        if window is None:
            return [dict(message) for message in messages]
        kept, _compaction = window.fit(
            [dict(message) for message in messages], pinned=1)
        return kept

    @property
    def run_id(self) -> str:
        """The run this swarm's records are recorded under, or ``""``."""
        return self._run.run_id

    # ── what the last call cost ─────────────────────────────────────────

    def _asked(self) -> Dict[str, Any]:
        """Fold the call this object just made into the turn's ledger.

        The **fold** is :meth:`core.runtime.run.Model.spend`'s and is not
        written here: the same four lines used to stand in this file and
        in the loop's, which is two owners of arithmetic and the half of a
        record nobody notices is wrong.  Every sub-mission's step folds
        through the same method into the same :class:`~core.runtime.usage
        .Ledger`, because there is one :class:`~core.runtime.run.Model` and
        it is shared by identity.

        What is left here is the one fact this class contributes: *which*
        call wrote the text a record is about.  ``{}`` when the provider
        reported nothing, so a record carries no ``usage`` key rather than
        a zeroed one.
        """
        self._last_spent = self._model.spend(self._ledger)
        return self._last_spent

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

        The record itself is :meth:`core.runtime.run.Run.opening`'s — the
        loop's own builder, called early rather than copied — so a consumer
        cannot read which route the router took off the frame that promises
        it one vocabulary.

        *resumption* is a
        :class:`core.runtime.resume.StagedResumption` — a staged run's
        checkpointed plan and completed steps, read back — and ``None`` is
        every turn that starts cold, which is the shape this method had
        before staged resuming existed.  Duck-typed rather than imported,
        for the reason :meth:`core.runtime.run.Run.run` duck-types its own.

        **A resumed staged turn announces nothing and decides nothing.**
        There is no second ``mission_started`` — it is the same mission,
        one objective, one id, one log — and the router and the planner
        are not asked again: the plan is on the record, and re-deciding it
        would be a different mission continuing under the run id of this
        one.  What the resumed stretch does is run the steps the plan has
        left, and say so on its first ``step_started``.
        """
        # One ledger for the whole turn, put on the one Model every child
        # of this run shares: the router's call is already part of what
        # this turn spent, and a stage folding into a ledger of its own
        # would report a turn that cost less than it did.
        self._ledger = Ledger()
        self._model.ledger = self._ledger
        # `Bounds.begin` is the one owner of "a run's clock starts here",
        # and it starts HERE — before triage, which is a model call and
        # part of the turn. First start wins, so the sub-missions below
        # inherit the same started clock rather than rewinding it.
        self._started_at = self._bounds.begin()
        plan: Optional[List[PlanStep]] = None
        if resumption is not None:
            plan = [PlanStep.from_state(state) for state in resumption.plan]
            # Every tool the recorded stretch dispatched, so the answer's
            # plane-claim check sees the whole turn and not the half of it
            # this process ran. Same owner as the live path's: the result
            # store, here rebuilt from the log rather than from a dispatch.
            self._called = list(resumption.called)
        else:
            self._observer.emit(MISSION_STARTED,
                                **self._run.opening(objective))
        # ONE transcript for the turn, whichever way it ends, so the record
        # below is written from state rather than from three hand-listings
        # of what each ending happens to know.
        transcript = MissionTranscript(objective=objective,
                                       catalogue=list(self._run.offered),
                                       usage=self._ledger)
        # Whether THIS object owes the stream its closing record. It does,
        # on every path but one: the direct route hands the whole ending to
        # the child, whose own `finally` emits it holding the step count
        # this object does not have.
        mine = True
        try:
            if resumption is not None:
                return self._staged(objective, plan, transcript,
                                    resumption=resumption)
            stop = self._bounds.stop()
            if stop is not None:
                # Already over before the router was asked. It happens on a
                # resumed switch and on a deadline of zero, and the honest
                # run is one that opens, says why it is stopping, and closes.
                return Run._stopped(transcript, stop)
            plan = (self._plan(objective)
                    if self._route(objective) == "staged" else None)
            # Not asked again here, deliberately. Triage and planning are
            # two model round trips and a small budget can be gone by now —
            # but every route below opens a run holding the same clock and
            # the same switch, and that run asks before its first step. A
            # second check here would be a branch no test can make fail,
            # which is the kind of code that rots into a wrong answer.
            if plan is None or len(plan) == 1:
                # A plan the planner could not state, or a plan of one step,
                # IS the direct path.  Falling back is the honest move: the
                # direct runner is a complete agent, and a swarm that
                # refused to answer because its planner misfired would be
                # machinery failing the question the machinery exists to
                # serve.
                mine = False
                return self._direct(objective)
            return self._staged(objective, plan, transcript)
        finally:
            # ONE call site, in a `finally`, and that is the whole of this
            # record in this file. There were three — the exception out of
            # triage, the stop before the router, and the staged path's own
            # — each passing a slightly different subset of what
            # `_finished_record` takes, and the one that predated `usage`
            # never grew it. A stream that opens and then stops is the
            # spinner-forever state the `finished` clause exists to
            # prevent, so a turn that opened owes this record however it
            # ended, including by raising.
            if mine:
                self._observer.emit(MISSION_FINISHED, **_finished_record(
                    started_at=self._started_at,
                    outcome=transcript.outcome,
                    steps=len(transcript.steps),
                    max_steps=self._bounds.max_steps,
                    budget=transcript.budget,
                    reason=transcript.reason,
                    # The run's totals, ABSENT when no provider reported
                    # anything — not three zeros. Off the one ledger every
                    # call of this turn folded into.
                    usage=self._ledger.as_record(self._model.rate)))

    # ── the clock and the switch, shared by every stage ─────────────────
    #
    # `Bounds.stop` is the question, asked at the three junctions a
    # sub-mission's own check cannot see: before triage, before a redraw,
    # and before the synthesizer.  Each of those is a model round trip this
    # class makes itself.  Everywhere else — between plan steps, inside a
    # step's retries — the next thing to happen is a child holding this
    # same `Bounds`, and asking here as well would be a branch no test
    # could make fail.  This file used to carry its own copy of that
    # question and its own copy of writing the verdict down, line for line
    # the loop's; both are the loop's now.

    def _child_bounds(self, max_steps: Optional[int] = None) -> Bounds:
        """This turn's bounds, for one child of it.

        One clock, one switch, one channel and ONE supervisor — shared by
        **identity**, which is what makes five sub-missions of a minute
        each not fit inside a one-minute budget and what makes a plan that
        loops across its steps a pattern something can see.

        Two things differ from the turn's own, and both are facts about a
        child rather than about the bounds.  ``started_at`` is the instant
        the TURN began, so a sub-mission's ``elapsed_s`` counts from triage
        and not from itself.  ``max_steps``, when a caller names one, is
        what an operator's ceiling has LEFT for the whole turn — not a
        slice of it for this step: a step takes the turns its work takes,
        and the four-turn slice this replaced is what starved the live run
        of 16 August.
        """
        return replace(
            self._bounds, started_at=self._started_at,
            **({} if max_steps is None else {"max_steps": max_steps}))

    # ── DIRECT: the path that already worked, untouched ─────────────────

    def _direct(self, objective: str) -> MissionTranscript:
        """One whole mission, inside this turn's stream.

        A child with **nothing overridden but the branch**, and that is the
        statement: the direct route's persona, history, validator and
        critic ARE the turn's, and the only way it differs from a mission
        run without ``--swarm`` is that its opening frame has already gone
        out — which is what a non-staged branch drops.  Its ``answer``, its
        ``grounding`` and its ``mission_finished`` are the turn's own,
        written where the run ends, which here is inside the child.

        It shares the ledger by sharing the model, and that is not an
        optimisation: the router call that chose this path was already
        made, and a child with a ledger of its own would report a turn that
        cost one call less than it did.
        """
        return self._run.child(branch=_DIRECT,
                               bounds=self._child_bounds()).run(objective)

    # ── TRIAGE ──────────────────────────────────────────────────────────

    def _route(self, objective: str) -> str:
        """``"direct"`` or ``"staged"``, and every failure is ``"direct"``.

        Fail-open to the cheap path on purpose: a router that cannot answer
        must cost the turn nothing, and the direct runner can still handle a
        complex question the slow way — the reverse mistake (ceremony around
        a small question) has no such recovery.
        """
        tools = ", ".join(self._plane.offered) or "(none)"
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

        Over the **plane's** list and not a second copy of it, and without
        the mission result store on it: the store tool is this harness's
        own descriptor and the planner is choosing platform actions.
        :attr:`~core.runtime.run.ToolPlane.offered` is live, so a redraw
        after a server registered something plans against what is
        registered now — which is the whole point of there being one plane
        for the turn.
        """
        lines = []
        for name in self._plane.offered:
            info = self._plane.bus.describe_tool(name)
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
            self._persona,
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
        store = self._run.store
        if store.runs is None or not store.run_id:
            return
        try:
            store.runs.update_meta(store.run_id, **facts)
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
                transcript: MissionTranscript,
                resumption: Optional[Any] = None) -> MissionTranscript:
        # `run` opened the stream before triage; the plan did not exist then.
        # It travels on the first `step_started` instead — carried by the
        # observer, which is what every stage's branch drains. On a resumed
        # turn the numbering continues the log this stretch is being
        # appended to, and the first new `step_started` says that it does.
        self._start_index = resumption.next_index if resumption else 0
        self._observer.carry(plan=_plan_record(plan))
        if resumption is not None:
            self._observer.carry(resumed=resumption.as_record())
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
        # No `finally` writing `mission_finished` here: `run` owns that
        # record on every path this turn can take, which is what makes it
        # one call site rather than three.
        return self._work_through(objective, plan, transcript,
                                  resumption=resumption)

    def _work_through(self, objective: str, plan: List[PlanStep],
                      transcript: MissionTranscript,
                      resumption: Optional[Any] = None) -> MissionTranscript:
        # `None` is no ceiling — the default — and an int is what an
        # operator's ceiling has left for the whole turn. There is no
        # per-step slice of it any more: see `_execute_step`.
        left: Optional[int] = self._bounds.max_steps or None
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
            if left is not None:
                left = max(0, left - int(resumption.steps_spent))
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
                objective, step, results, left)
            if left is not None:
                left = max(0, left - spent)
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
            # a bound it has already exceeded on planning work it cannot
            # then do.
            stop = self._bounds.stop()
            if stop is not None:
                return Run._stopped(transcript, stop)

            # The supervisor's verdict and not a counter. A redraw used to
            # be "once per turn, on any failure", which meant a plan that
            # was right and a step that was unlucky bought the same redraw
            # as a plan that could never have worked — and meant the second
            # genuinely wrong plan of a turn could not be fixed. Now the
            # step's own review says which of those this is, and the review
            # budget bounds how many times it may say so.
            if outcome.replan and (left is None or left > 0):
                # A redraw around the failure, carrying what succeeded.
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
                    # The plan as REDRAWN replaces the plan as drawn, on the
                    # stream and on the checkpoint alike: what a watcher
                    # holds, and what a restart reads, has to be the plan
                    # the steps arriving next belong to rather than the one
                    # that was abandoned. `carry` replaces for that reason.
                    self._observer.carry(plan=_plan_record(fresh))
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
        stop = self._bounds.stop()
        if stop is not None:
            return Run._stopped(transcript, stop)
        return self._synthesize(objective, plan, results, evidence,
                                transcript)

    def _execute_step(self, objective: str, step: PlanStep,
                      results: Dict[str, _StepOutcome],
                      left: Optional[int]):
        """Run one step, and let the supervisor say what a failed gate means.

        Returns ``(outcome, attempts, evidence, tool_turns_spent)`` —
        every attempt's transcript oldest first, and every attempt's tool
        evidence, so nothing that ran goes unrecorded.

        *left* is what an operator's ceiling has left for the whole turn,
        or ``None`` when there is no ceiling.  **There is no slice of it
        for this step.**  A step takes the turns its work takes; the turn
        stops where the operator said it stops.  The four-turn slice this
        parameter replaced is what starved the live run of 16 August, and
        the general lesson is the one this whole change is about: a
        number that bounds *work* is a guess about how much a question is
        worth.

        The retry loop is gone too, and what is here instead is not a
        smaller version of it: a failed gate is put to the supervisor, and
        the step is attempted again ONLY on a ``nudge``, carrying the
        reviewer's note. ``replan`` and ``stuck`` settle the step —
        differently, and :attr:`_StepOutcome.replan` is which — and
        ``progressing`` is the reviewer overruling the gate, which is a
        thing a gate needs: its mechanical half can be wrong about a step
        that did the work under a name the plan did not use.
        """
        if left is not None and left <= 0:
            return _StepOutcome(
                step=step, ok=False,
                why="the operator's step ceiling was reached before this "
                    "step could run",
            ), [], [], 0

        spent = 0
        failure = ""
        attempts: List[MissionTranscript] = []
        evidence: List[str] = []
        while True:
            allowance = 0 if left is None else left - spent
            if left is not None and allowance <= 0:
                break
            # ONE `Run.child` where there were two constructors, each
            # threading twenty collaborators by hand. What differs between
            # a stage and the turn is exactly what is named here: the
            # prompt it is given, what an operator's ceiling has left, and
            # that its records are one stage's rather than the mission's.
            # Everything else — the plane, the store, the observer, the
            # model and therefore the ledger, the clock, the switch, the
            # channel and the supervisor — is the parent's, by identity.
            child = self._run.child(
                personality=replace(
                    self._run.personality,
                    # The persona LEADS and the executor's paragraph
                    # follows it, so every sub-mission of every staged turn
                    # opens with the same bytes the direct path opens with.
                    system_message=stacked(self._persona, EXECUTE_PROMPT),
                    # A step is not a conversation and is not the answer.
                    # The history belongs to the turn, and the validator
                    # and the critic to the synthesizer: a step's summary
                    # is not an answer to the objective, so holding it to
                    # the objective's grammar would fail it for not being
                    # one.
                    #
                    # `memory` goes with them, and for the same sentence: a
                    # step's summary is not an answer, so a reflection over
                    # it would distil "what a stage concluded" into a bank
                    # that is supposed to hold what a MISSION learned —
                    # three notes per plan step, none of them about the
                    # question. The direct route (`_direct`) overrides
                    # nothing and keeps the bank, because that route is a
                    # whole agent answering the whole question.
                    history=(), grounding=None, critic=None, memory=None),
                bounds=self._child_bounds(allowance),
                branch=step.id, stage=True, start_index=self._start_index)
            sub = child.run(
                self._step_objective(objective, step, results, failure))
            attempts.append(sub)
            evidence.extend(child.results.evidence_texts())
            self._note_calls(child)
            spent += len(sub.steps)
            if sub.outcome == AWAITING_APPROVAL:
                return (_StepOutcome(step=step, ok=False,
                                     why="awaiting approval"),
                        attempts, evidence, spent)

            ok, why = self._gate(step, sub)
            if ok:
                summary = self._summary(sub.answer or "")
                # `evidence` and not `runner.store.evidence_texts()`: every
                # attempt at this step read something real, and the answer
                # is written over what the mission read rather than over
                # what its last attempt read.
                return (_StepOutcome(step=step, ok=True, summary=summary,
                                     evidence=list(evidence)),
                        attempts, evidence, spent)
            failure = why
            if self._bounds.supervisor is None:
                # Nobody is watching, so nothing decides to try again. A
                # turn with no supervisor settles a failed gate as a failed
                # step and carries on, which is the honest behaviour of a
                # harness with no judgement available to it.
                break
            review = self._bounds.supervisor.review_gate(
                objective, goal=step.goal, why=why,
                ledger=self._ledger)
            if review is not None:
                # It rides the NEXT `step_started`, which is what `review`
                # means on the direct path too: the step that follows a
                # review turn. This one happened BETWEEN sub-missions — a
                # gate said no and the supervisor was asked what that means
                # — so it has no step of its own. A review with no step
                # after it (the last step of a plan, settled `stuck`) is
                # not announced, and `mission_finished` is what says how
                # the turn ended.
                self._observer.carry(review=review.as_record())
            if review.verdict == PROGRESSING:
                # The gate is overruled. What the step reported stands, and
                # it stands as the step's own summary — the same text a
                # passed gate would have carried forward.
                return (_StepOutcome(step=step, ok=True,
                                     summary=self._summary(
                                         sub.answer or ""),
                                     evidence=list(evidence)),
                        attempts, evidence, spent)
            if review.verdict == NUDGE:
                # Round again, with the reviewer's note in the executor's
                # own instructions — where the gate's sentence already goes,
                # because to the executor they are the same kind of fact:
                # this is what was wrong last time.
                if review.note:
                    failure = f"{why}\n{review.note}"
                continue
            return (_StepOutcome(step=step, ok=False, why=failure,
                                 evidence=list(evidence),
                                 replan=review.verdict == REPLAN),
                    attempts, evidence, spent)
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
                f"The step reported: {self._summary(sub.answer or '')}"
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
        system = stacked(self._persona, SYNTHESIZE_PROMPT)
        window = self._model.window
        kept = list(blocks)
        while True:
            messages = self._fit(self._role_messages(
                system, self._synthesis_user(objective, lines, kept,
                                             len(blocks) - len(kept))))
            if not kept or window is None:
                return messages, lines
            if window.estimate(messages) <= window.limit_tokens:
                return messages, lines
            kept.pop(0)

    def _synthesize(self, objective: str, plan: List[PlanStep],
                    results: Dict[str, _StepOutcome],
                    evidence: List[str],
                    transcript: MissionTranscript) -> MissionTranscript:
        messages, lines = self._synthesis_messages(
            objective, plan, results, evidence)
        answer = str(self._model.plain(messages) or "").strip()
        self._asked()
        if not answer:
            # The synthesizer said nothing.  The step results themselves are
            # the honest fallback — facts the gates passed, not prose.
            answer = ("The mission's steps completed as follows and no "
                      "synthesis could be produced:\n" + "\n".join(lines))

        # ── the same discipline the direct path applies to its answer ──
        #
        # Through the loop's own four owners and not a second copy of them.
        # What this path contributes is the two things the loop cannot
        # know: the evidence is the UNION of every sub-mission's store
        # (plus a resumed stretch's, read back off the log), and the repair
        # is one more call to a model with no tools rather than another
        # turn of a loop.  Everything decided ABOUT the answer — what a
        # check that could not run means, when a repair is announced, what
        # the caveated report says, what the `grounding` record carries and
        # in which order it and the `answer` go out — is `Run`'s.
        #
        # This file used to hold all of it, and the drift was measured: the
        # record it built by hand carried six of the ten fields the
        # contract requires.
        validator = self._run.personality.grounding
        repairs = 0
        report = self._run._ground(answer, repairs, evidence=evidence,
                                   called=self._called)
        while (report is not None and report.ran and not report.grounded
               and repairs < validator.max_repairs):
            repairs += 1
            messages.append({"role": "assistant", "content": answer})
            messages.append({
                "role": "user",
                "content": self._run._repairing_turn(report, repairs)})
            answer = str(
                self._model.plain(self._fit(messages)) or "").strip() or answer
            self._asked()
            report = self._run._ground(answer, repairs, evidence=evidence,
                                       called=self._called)
        # The draft is what the model wrote; the caveat is this harness's
        # own sentence about it, and the critic below is shown the first
        # and not the second.
        draft = answer
        if report is not None and report.ran and not report.grounded:
            report = self._run._caveated(report, repairs)
            answer = answer + report.caveat

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
            self._run._verdict(objective, draft, report,
                               repairs=report.repairs, caveat=report.caveat,
                               evidence=evidence)
        # `_last_spent` and not the synthesizer's own call, because the
        # grounding above may have spent a repair turn — and then the text
        # on this record is the repair's, not the draft's. The per-call
        # field is the cost of the call that produced the text beside it;
        # the run's total is on `mission_finished`.
        self._observer.emit(ANSWER, text=transcript.answer,
                            outcome=transcript.outcome, **self._last_spent)
        return transcript

    def _note_calls(self, child: Any) -> None:
        """Fold one sub-mission's dispatched tools into the turn's set.

        A direct mission's plane-claim check reads one store; a staged
        turn's answer is synthesized over several, and a claim to have used
        the SDK is true if *any* step used it.  One owner still — each
        store's own record of what it dispatched — merged, not re-derived.
        """
        for name in child.results.called_tools():
            if name not in self._called:
                self._called.append(name)

    # ── plumbing ────────────────────────────────────────────────────────

    def _fold_in(self, transcript: MissionTranscript,
                 sub: Optional[MissionTranscript]) -> None:
        """A sub-mission's steps onto the one transcript, renumbered."""
        if sub is None:
            return
        for step in sub.steps:
            step.index = len(transcript.steps)
            transcript.steps.append(step)

    def _summary(self, text: str) -> str:
        """A step's reported result, whole unless a caller asked for a cut.

        ``summary_chars=None`` — the default — returns the executor's own
        sentence entire, whitespace collapsed, because the thing that
        bounds it is the window of the prompt it lands in and not a number
        chosen here.  It was 1,200 characters by default, and 1,200
        characters is what reached the synthesizer of the 16 August run:
        a 34,000-character governed view arrived as 1.2 KB of prose about
        it, and the answer said the actor list "was not reported".

        An int is a caller who wants the cut, and the cut is
        :func:`core.bounding.bound_result`'s — the one owner of "how much
        of a result reaches a model, and how it says so".  This method
        used to be a fifth implementation of that rule beside the four
        that module was written to end, and it was the worst of them: a
        head-only cut, which throws away the totals a governed view puts
        at the bottom, under a marker that promises nothing about where
        the rest went.  What a caller gets now is head AND tail inside the
        bound, and a marker that says how much of each and that the middle
        must not be guessed at.

        In bytes, therefore, and not characters — a context budget is
        bytes, and a multi-byte character costs what it costs.
        """
        text = " ".join(str(text).split())
        if self._summary_chars is None:
            return text
        bounded, _cut = bound_result(text, self._summary_chars)
        return bounded

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
                 if self._model.json_mode else {})
        try:
            reply = str(self._model.plain(self._fit(messages), **extra) or "")
        except Exception:
            # Nothing to fold: `last_usage` is cleared at the start of
            # every call, so a call that raised reports nothing and adding
            # it would be adding None.
            return None
        # Folded even when the reply turns out to be unparseable below — a
        # call that produced garbage was still billed.
        self._asked()
        text = _FENCE.sub("", reply.strip()).strip()
        if not text:
            return None
        try:
            decision = json.loads(text)
        except json.JSONDecodeError:
            return None
        return decision if isinstance(decision, dict) else None
