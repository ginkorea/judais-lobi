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
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

from core.redact import scrub_record
from core.runtime.approvals import ApprovalStore, ApprovalTicket
from core.runtime.context_window import MissionWindow
from core.runtime.contract import SCHEMA_VERSION
from core.runtime.grounding import GroundingReport, GroundingValidator
from core.runtime.mission import (
    AWAITING_APPROVAL, MissionRunner, MissionTranscript, _grounding_record,
    _profile_field, audit_ref_of, sandbox_of, validate_history,
)
from core.runtime.mission_stream import (
    ANSWER, GATE_REQUESTED, GROUNDING, MISSION_FINISHED, MISSION_STARTED,
    Observer, REPLY_REJECTED, STEP_STARTED, TOOL_CALL, TOOL_RESULT,
)
from core.runtime.results import RESULT_TOOL

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
             'code written and run through a code-execution tool.'),
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
You are writing the final answer to the objective from the step results \
below. Use only what the steps reported, and carry their identifiers and \
figures into the answer exactly as reported. If a step FAILED, say \
plainly which one and why, and answer with what the completed steps \
support. Never present a failed or missing step's result as obtained.
"""


@dataclass
class PlanStep:
    """One step of a staged plan, as the planner stated it."""

    id: str
    goal: str
    rung: str = "tool"
    needs: List[str] = field(default_factory=list)
    done: str = ""


@dataclass
class _StepOutcome:
    """What one executed step left behind."""

    step: PlanStep
    ok: bool
    summary: str = ""
    why: str = ""


def _plan_record(plan: Sequence[PlanStep]) -> List[Dict[str, str]]:
    """A plan as the observer's ``plan`` field.

    One owner for the shape, because it is now stated from two places — the
    plan as drawn and the plan as redrawn — and a second hand-listing is how
    the ``grounding`` record came to carry six of the ten fields its own
    contract required.
    """
    return [{"id": step.id, "goal": step.goal, "rung": step.rung}
            for step in plan]


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
    """

    def __init__(self, observer: Observer):
        self._observer = observer

    def __call__(self, record: Dict[str, Any]) -> None:
        if record.get("event") == MISSION_STARTED:
            return
        self._observer(record)


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
    """

    _PASS = frozenset({
        STEP_STARTED, REPLY_REJECTED, TOOL_CALL, TOOL_RESULT, GATE_REQUESTED,
    })

    def __init__(self, emit: Callable[..., None]):
        self._emit = emit
        self._next_index = 0
        self._offset = 0
        self._seen_high = -1
        self._pending_plan: Optional[List[Dict[str, str]]] = None

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
        if self._pending_plan is not None and event == STEP_STARTED:
            # On ``step_started`` and nowhere else: ``plan`` is declared
            # optional on that event alone, and a field an event does not
            # declare is a field a consumer meets with no sentence for it.
            fields["plan"] = self._pending_plan
            self._pending_plan = None
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
    max_plan_steps:
        Hard cap on plan length.  Five, because the endpoint is serial at
        59 tok/s and a 20-step plan is a hang wearing a plan's clothes.
    step_budget:
        Tool-turns per sub-mission.  Small on purpose: a step that needs
        eight turns was two steps.
    retries_per_step:
        Bounded retries before the plan is redrawn.
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
        Passed straight through to every :class:`MissionRunner` this
        builds; see that class's ``window`` parameter.  A staged mission
        runs more steps than a direct one, not fewer, so it is the path
        that needs bounding most.
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
        gated: Sequence[str] = (),
        approvals: Optional[ApprovalStore] = None,
        approval: Optional[ApprovalTicket] = None,
        run_id: str = "",
        history: Sequence[Dict[str, str]] = (),
        observer: Optional[Observer] = None,
        plain_chat_fn: Optional[Callable[[List[Dict[str, str]]], Any]] = None,
        max_plan_steps: int = 5,
        step_budget: int = 4,
        retries_per_step: int = 1,
        summary_chars: int = 1_200,
        sdk_import: str = "",
        window: Optional[MissionWindow] = None,
    ):
        self._chat = chat_fn
        self._plain_chat = plain_chat_fn or chat_fn
        self._bus = bus
        self._tool_names = list(tool_names)
        self._system_message = system_message
        self._max_steps = max(1, int(max_steps))
        self._validator = validator
        self._gated = list(gated)
        self._approvals = approvals
        self._approval = approval
        self._run_id = str(run_id or "")
        if approval is not None:
            # Narrowed HERE as well as in every MissionRunner this builds,
            # because `_opening` renders the gated names for the whole turn
            # from this list and a consumer must not be able to tell from the
            # opening frame which route ran. One owner for the subtraction
            # itself: `ApprovalTicket.widen`.
            self._gated = approval.widen(self._gated)
        self._history = validate_history(history)
        self._observer = observer
        # Handed to every MissionRunner this builds and to nothing else.
        # A rung's execution is an ordinary mission loop and grows the same
        # unbounded message list; the router, planner, gate and synthesizer
        # each build one short list of their own and send it once, so there
        # is nothing there for a window to bound.
        self._window = window
        self._max_plan_steps = max(1, int(max_plan_steps))
        self._step_budget = max(1, int(step_budget))
        self._retries = max(0, int(retries_per_step))
        self._summary_chars = max(200, int(summary_chars))

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
        if self._observer is None:
            return
        try:
            self._observer(scrub_record({"event": event, **fields}))
        except Exception:                       # pragma: no cover - defensive
            pass

    # ── the one entry point ─────────────────────────────────────────────

    def run(self, objective: str) -> MissionTranscript:
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
        """
        self._emit(MISSION_STARTED, **self._opening(objective))
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
            self._emit(MISSION_FINISHED, outcome="incomplete", steps=0,
                       max_steps=self._max_steps)
            raise
        if plan is None or len(plan) == 1:
            # A plan the planner could not state, or a plan of one step, IS
            # the direct path.  Falling back is the honest move: the direct
            # runner is a complete agent, and a swarm that refuses to answer
            # because its planner misfired would be machinery failing the
            # question the machinery exists to serve.
            return self._direct(objective)
        return self._staged(objective, plan)

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
            gated=self._gated,
            approvals=self._approvals,
            approval=self._approval,
            run_id=self._run_id,
            history=history,
            observer=observer,
            window=self._window,
        )

    def _direct(self, objective: str) -> MissionTranscript:
        runner = MissionRunner(
            self._chat, self._bus, self._tool_names,
            system_message=self._system_message,
            max_steps=self._max_steps,
            validator=self._validator,
            gated=self._gated,
            approvals=self._approvals,
            approval=self._approval,
            run_id=self._run_id,
            history=self._history,
            observer=(_OpenedAlready(self._observer)
                      if self._observer is not None else None),
            window=self._window,
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
        messages: List[Dict[str, str]] = [
            {"role": "system",
             "content": TRIAGE_PROMPT + f"\nTools that exist here: {tools}"},
            *[dict(turn) for turn in self._history[-2:]],
            {"role": "user", "content": objective},
        ]
        decision = self._json_reply(messages)
        route = str((decision or {}).get("route", "")).strip().lower()
        return route if route == "staged" else "direct"

    # ── PLAN ────────────────────────────────────────────────────────────

    def _short_catalogue(self) -> str:
        """Tool names with first-sentence descriptions — the planner's view.

        The full catalogue (schemas, argument grammars) belongs to the
        executor that will actually call the tool; the planner only decides
        *that* a tool step exists, and feeding it the schemas would spend
        the context the whole design exists to save.
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
        system = "\n\n".join(part for part in (
            self._system_message.strip(),
            PLAN_PROMPT.format(max_steps=self._max_plan_steps,
                               rungs=self._plan_rung_lines()),
            "Tools that exist here:\n" + self._short_catalogue(),
        ) if part)
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
        messages: List[Dict[str, str]] = [
            {"role": "system", "content": system},
            *[dict(turn) for turn in self._history[-2:]],
            {"role": "user", "content": "\n\n".join(user_parts)},
        ]

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

    def _staged(self, objective: str, plan: List[PlanStep]) -> MissionTranscript:
        transcript = MissionTranscript(objective=objective,
                                       catalogue=list(self._offered))
        # `run` opened the stream before triage; the plan did not exist then.
        # It travels on the first `step_started` instead.
        stage = _StageObserver(self._emit)
        stage.announce(plan)
        try:
            outcome = self._work_through(objective, plan, transcript, stage)
        finally:
            self._emit(MISSION_FINISHED, outcome=transcript.outcome,
                       steps=len(transcript.steps),
                       max_steps=self._max_steps)
        return outcome

    def _work_through(self, objective: str, plan: List[PlanStep],
                      transcript: MissionTranscript,
                      stage: _StageObserver) -> MissionTranscript:
        budget = self._max_steps
        evidence: List[str] = []
        results: Dict[str, _StepOutcome] = {}
        replanned = False
        queue = list(plan)

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
                return transcript

            results[step.id] = outcome
            if outcome.ok:
                continue

            if not replanned and budget > 0:
                # One redraw around the failure, carrying what succeeded.
                replanned = True
                carried = {sid: r.summary for sid, r in results.items()
                           if r.ok}
                fresh = self._plan(objective, carried=carried,
                                   failure=f"step {step.id} "
                                           f"({step.goal}): {outcome.why}")
                if fresh:
                    queue = fresh
                    stage.announce(fresh)
                    continue
            # Out of moves for this step: the failure is now part of the
            # answer.  The steps still queued are dropped rather than run
            # against a hole — their `needs` may name the failed step.
            break

        return self._synthesize(objective, plan, results, evidence,
                                transcript)

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
            allowance = min(self._step_budget, budget - spent)
            if allowance <= 0:
                break
            stage.begin_stage()
            runner = self._runner(
                system_message="\n\n".join(part for part in (
                    self._system_message.strip(), EXECUTE_PROMPT.strip(),
                ) if part),
                max_steps=allowance,
                observer=stage,
            )
            sub = runner.run(self._step_objective(step, results, failure))
            attempts.append(sub)
            evidence.extend(runner.store.evidence_texts())
            spent += len(sub.steps)
            if sub.outcome == AWAITING_APPROVAL:
                return (_StepOutcome(step=step, ok=False,
                                     why="awaiting approval"),
                        attempts, evidence, spent)

            ok, why = self._gate(step, sub)
            if ok:
                summary = self._bound_summary(sub.answer or "")
                return (_StepOutcome(step=step, ok=True, summary=summary),
                        attempts, evidence, spent)
            failure = why
        return (_StepOutcome(step=step, ok=False, why=failure or
                             "the step produced no checkable result"),
                attempts, evidence, spent)

    def _step_objective(self, step: PlanStep,
                        results: Dict[str, _StepOutcome],
                        failure: str = "") -> str:
        """The whole of what an executor sees about the mission.

        The step, its rung, its success shape, and the summaries of exactly
        the earlier steps it declared it needs — never the raw output of
        any of them, and never the rest of the plan.  This bound is the
        design: the executor's context must not grow with the mission.
        """
        # `.get` with the plain-code fallback, and not a KeyError: a rung
        # this run does not offer cannot reach here through `_read_plan`,
        # and if a caller builds a `PlanStep` by hand, code without the
        # SDK is the honest degradation of code with it.
        sentence = self._rung_sentences.get(step.rung,
                                            self._rung_sentences["code"])
        parts = [f"Step {step.id} of a plan: {step.goal}",
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
        acted = any(s.tool and not s.refused and s.tool != RESULT_TOOL
                    for s in sub.steps)
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

    def _synthesize(self, objective: str, plan: List[PlanStep],
                    results: Dict[str, _StepOutcome],
                    evidence: List[str],
                    transcript: MissionTranscript) -> MissionTranscript:
        lines = []
        for step in plan:
            outcome = results.get(step.id)
            if outcome is None:
                lines.append(f"- {step.id} ({step.goal}): NOT RUN — an "
                             f"earlier step failed first")
            elif outcome.ok:
                lines.append(f"- {step.id} ({step.goal}): {outcome.summary}")
            else:
                lines.append(f"- {step.id} ({step.goal}): FAILED — "
                             f"{outcome.why}")
        messages: List[Dict[str, str]] = [
            {"role": "system", "content": "\n\n".join(part for part in (
                self._system_message.strip(), SYNTHESIZE_PROMPT.strip(),
            ) if part)},
            *[dict(turn) for turn in self._history[-2:]],
            {"role": "user",
             "content": f"Objective: {objective}\n\nStep results:\n"
                        + "\n".join(lines)},
        ]
        answer = str(self._plain_chat(messages) or "").strip()
        if not answer:
            # The synthesizer said nothing.  The step results themselves are
            # the honest fallback — facts the gates passed, not prose.
            answer = ("The mission's steps completed as follows and no "
                      "synthesis could be produced:\n" + "\n".join(lines))

        answer, report = self._ground(answer, messages, evidence)
        transcript.answer = answer
        transcript.grounding = report
        failed = any(not r.ok for r in results.values()) or (
            len(results) < len(plan))
        if report is not None and report.caveat:
            transcript.outcome = "answered_with_caveat"
        else:
            transcript.outcome = "answered_with_caveat" if failed else "answered"
        if report is not None:
            # Through the SAME renderer the direct path uses. Hand-listing the
            # fields here is how this record came to be six of the ten the
            # contract requires: a consumer switching on `event` gets one shape
            # per event or it is not a vocabulary.
            self._emit(GROUNDING, **_grounding_record(
                report, repairs=report.repairs, caveat=report.caveat or ""))
        self._emit(ANSWER, text=transcript.answer, outcome=transcript.outcome)
        return transcript

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
        report = self._validator.validate(answer, evidence)
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
            answer = str(self._plain_chat(messages) or "").strip() or answer
            report = self._validator.validate(answer, evidence)
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
        text = " ".join(str(text).split())
        if len(text) <= self._summary_chars:
            return text
        return (text[:self._summary_chars]
                + f" … [cut at {self._summary_chars} characters]")

    def _json_reply(self, messages: List[Dict[str, str]]) -> Optional[Dict[str, Any]]:
        """One JSON object from the plain backend, or ``None``.  Never raises."""
        try:
            reply = str(self._plain_chat(messages) or "")
        except Exception:
            return None
        text = _FENCE.sub("", reply.strip()).strip()
        if not text:
            return None
        try:
            decision = json.loads(text)
        except json.JSONDecodeError:
            return None
        return decision if isinstance(decision, dict) else None
