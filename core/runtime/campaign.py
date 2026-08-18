# core/runtime/campaign.py — a plan of missions, on Run

"""A campaign is a parent that spawns child runs with artifact handoff.

``ROADMAP.md`` §2.6b names three layers.  The **skill** is what the model
is told and held to (a ``SKILL.md``).  The **task** is one objective under
one skill on one plane with bounds — one :class:`~core.runtime.run.Run`,
which is what ``--mission`` already is, shaped by a *task template*.  The
**campaign** is a DAG of tasks with explicit artifact handoff, human
approval and a resume: it stays *above* ``Run`` (§2.6.5) as a parent
spawning children, and what makes it real is what the mission path already
earned — the run store, ``--approval``, the supervisor — plus the wire:
lane D's OPTIONAL ``branch`` says which child a record belongs to, the
campaign plan rides the first ``step_started`` the way the swarm's plan
does, and an OPTIONAL ``artifacts`` field goes beside it.  No new required
field, and ``SCHEMA_VERSION`` does not move.

**This is a subclass of** :class:`~core.runtime.swarm.SwarmRunner`, **and
that is the design.**  Read the swarm's ``_work_through`` and then read
February's ``CampaignOrchestrator.run`` and the overlap is almost total: a
parent over children, waves of independent steps, a per-step gate, a
checkpoint after each one so a restart continues, a synthesis at the end.
The lesson this repo keeps relearning — *one owner per fact* — says that
the second implementation of that loop is the one that drifts, and it had
already started to: the orchestrator dispatched through the coding
kernel's task dispatcher while the swarm dispatched a ``Run``, so a
campaign step and a plan step disagreed about what a step even was.  So
the loop is the swarm's, and what a campaign contributes is exactly five
overrides, each of which is a real difference between a plan somebody
*wrote* and a plan a model *drew*:

* :meth:`CampaignRunner.arun` — no router and no planner.  The steps come
  from a file or from :func:`~core.campaign.planner.draft_campaign_plan`,
  and before any of them runs a **person approves the plan**.
* :meth:`CampaignRunner._execute_step` — artifact handoff.  A step's
  declared inputs are copied out of the steps that produced them before
  it starts, and its declared exports are collected after; a step that
  promised a file and did not write it did not do the step.
* :meth:`CampaignRunner._wave` — least privilege decides who runs
  together, because the engine's scope allowlist is one object.
* :meth:`CampaignRunner._redraw` — never.  A campaign plan is **immutable
  once approved** (``ROADMAP.md`` §5.1, invariant 9): steps may be
  retried, skipped or aborted, and anything else goes back to a person.
* :meth:`CampaignRunner._persona` — a step runs under **its own pack's**
  skill, where a plan step runs under the turn's.

Everything else — the child run, the gate, the supervisor's verdicts, the
checkpoint, the resume, the synthesizer and its grounding, ``branch``, the
numbering, the ledger — is inherited and therefore is the same code the
staged path runs.

**One owner for the plan's own facts, too.**  :mod:`core.campaign` keeps
them and this module imports them: :class:`~core.contracts.campaign
.CampaignPlan` and :class:`~core.contracts.campaign.MissionStep` are the
schema, :func:`~core.campaign.validator.validate_campaign_plan` decides
what is legal, :func:`~core.campaign.handoff.materialize_handoff` moves a
file between two steps, :func:`~core.campaign.scope.effective_scopes` is
the intersection, :func:`~core.campaign.hitl.review_plan` is the ``$EDITOR``
half of the approval and :class:`~core.campaign.session.CampaignSession` is
the directory layout.  What was retired is
``CampaignOrchestrator.run`` — the *dispatch*, and only the dispatch.
"""

from __future__ import annotations

import hashlib
import json
from contextvars import ContextVar
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Set, Tuple

from core.campaign.handoff import materialize_handoff
from core.campaign.hitl import HumanReviewError, review_plan
from core.campaign.scope import effective_scopes
from core.campaign.session import CampaignSession
from core.campaign.validator import toposort, validate_campaign_plan
from core.contracts.campaign import CampaignPlan, MissionStep
from core.runtime.mission import (
    AWAITING_APPROVAL, MissionTranscript, _finished_record,
)
from core.runtime.mission_stream import (
    GATE_REQUESTED, MISSION_FINISHED, MISSION_STARTED,
)
from core.runtime.run import Personality, Run
from core.runtime.swarm import PlanStep, SwarmRunner, _StepOutcome
from core.runtime.usage import Ledger

__all__ = [
    "CampaignRunner", "CampaignRefused", "TaskTemplate", "CAMPAIGN_TOOL",
    "HANDOFF_IN", "HANDOFF_OUT", "load_template", "templates_of",
    "plan_from_file", "plan_digest", "campaign_meta",
]


#: The name a campaign plan's approval record is filed under.
#:
#: A pseudo-tool, and deliberately not a real one: the approval store's
#: :attr:`~core.runtime.approvals.Approval.tool` field answers "what is
#: being decided", and there is exactly one approvals mechanism in this
#: harness rather than one for tool calls and a second for plans.  A
#: consumer sees a ``gate_requested`` naming this, with the whole plan in
#: ``arguments`` — which is the point of a durable record over a prompt: a
#: person deciding an hour later can read what they are approving.
#:
#: :meth:`~core.runtime.approvals.ApprovalTicket.widen` removing this name
#: from the run's gated set is a no-op, because no bus registers it.
CAMPAIGN_TOOL = "campaign_plan"

#: Where a step finds what earlier steps handed it, and where it leaves
#: what it owes.  The two directory names are
#: :class:`~core.campaign.session.CampaignSession`'s and are named here
#: because the *prompt* quotes them: a step is told the paths, and the
#: harness reads the same paths back.
HANDOFF_IN = "handoff_in"
HANDOFF_OUT = "handoff_out"

#: How much of a task template's role shape reaches a step's objective.
#: A template is data a person wrote and may be long; what a step needs is
#: the shape, not the essay.
_SHAPE_CHARS = 480


class CampaignRefused(ValueError):
    """A campaign plan that will not be run, naming every fault.

    Raised at construction and not at dispatch, so an operator whose plan
    has a cycle finds out before a model is asked anything.  A
    :class:`ValueError` for the reason
    :class:`~core.campaign.validator.CampaignValidationError` is one — the
    plan is an argument, and a bad argument is not an exceptional
    condition somebody should catch broadly.
    """


# ── a task template, as much of one as a step needs ─────────────────────────


@dataclass(frozen=True)
class TaskTemplate:
    """One ``templates/<name>.yaml`` out of a mission pack, as data.

    The middle layer of §2.6b: the workflow shape a task runs in — intake,
    plan, act, verify, finalize, with a judge — stated as data rather than
    as a second loop.  A campaign step *names* one, exactly as
    ``ROADMAP.md`` §5.1's invariant 8 requires ("the LLM picks from a menu
    of templates; it never writes the menu"), and what the template
    contributes here is three things and no more: the vocabulary a plan's
    ``target_workflow`` is validated against, a ceiling on the step's
    scopes, and the sentence the step's executor is given.

    It is deliberately not the kernel's :class:`~core.kernel.workflows
    .WorkflowTemplate`.  That class is a phase state machine with a
    transition graph, and the campaign layer on ``Run`` has no phases: a
    step is one child run.  A plan may still name a kernel workflow —
    :class:`CampaignRunner` accepts both vocabularies — and then no
    template narrows it.
    """

    name: str
    #: The pack whose skill a step under this template runs with, or ``""``
    #: for a template that names none.  See :attr:`CampaignRunner._packs`.
    skill: str = ""
    description: str = ""
    #: The scopes this template permits, or ``None`` for a template with no
    #: opinion.  ``None`` and the empty tuple are different: no opinion
    #: narrows nothing, and an explicit empty list permits nothing.
    scopes: Optional[Tuple[str, ...]] = None
    #: ``("intake — list the working directory …", …)``, one line per role.
    shape: Tuple[str, ...] = ()

    def sentence(self) -> str:
        """What a step under this template is told to do it *via*.

        Rendered into the executor's own instruction through the swarm's
        rung machinery — see :meth:`CampaignRunner._adopt_templates` — so a
        campaign step's prompt is composed by the same function a plan
        step's is, and the two cannot drift into two prompts.
        """
        parts = [f"the '{self.name}' task template"]
        if self.description:
            parts.append(self.description.strip())
        if self.shape:
            shape = "; ".join(self.shape)
            parts.append(f"Work in this shape: {shape[:_SHAPE_CHARS]}")
        return ". ".join(parts)


def load_template(path: Any) -> TaskTemplate:
    """One template file, parsed.  ``pyyaml`` is imported where it is used.

    Tolerant on purpose about everything except the name: a template is
    content a pack author wrote, and a missing ``description`` is not a
    reason to refuse a campaign.  A file with no ``name`` takes the file's
    own stem, which is what a reader would assume anyway.
    """
    import yaml

    path = Path(path)
    data = yaml.safe_load(path.read_text()) or {}
    if not isinstance(data, Mapping):
        data = {}
    scopes = data.get("scopes")
    shape = []
    for role in data.get("workflow") or ():
        if not isinstance(role, Mapping):
            continue
        name = str(role.get("role") or "").strip()
        does = " ".join(str(role.get("does") or "").split())
        if name:
            shape.append(f"{name} — {does}" if does else name)
    return TaskTemplate(
        name=str(data.get("name") or path.stem),
        skill=str(data.get("skill") or ""),
        description=" ".join(str(data.get("description") or "").split()),
        scopes=None if scopes is None else tuple(str(s) for s in scopes),
        shape=tuple(shape),
    )


def templates_of(*packs: Any) -> Dict[str, TaskTemplate]:
    """Every ``templates/*.yaml`` of these packs, by name.

    *packs* are :class:`~core.skills.library.Pack` objects — the loader is
    that module's and is not repeated here, for the reason it says about
    itself: a second reader of a pack's layout is how a closed set comes to
    mean one thing to ``--skill`` and another to everything else.  A
    template whose ``skill:`` names nothing inherits its pack's name, so a
    plan naming that template gets the pack's persona without a pack author
    having to say the name twice.

    A template that will not parse is skipped rather than fatal: one bad
    file in a pack must not make the other templates unnameable.
    """
    found: Dict[str, TaskTemplate] = {}
    for pack in packs:
        for path in getattr(pack, "templates", ()) or ():
            try:
                template = load_template(path)
            except Exception:                   # pragma: no cover - defensive
                continue
            if not template.skill:
                template = replace(template, skill=str(getattr(pack, "name",
                                                               "")))
            found[template.name] = template
    return found


# ── the plan: read it, name it, remember it ─────────────────────────────────


def plan_from_file(path: Any) -> CampaignPlan:
    """A ``CampaignPlan`` off disk, JSON or YAML by suffix.

    The one reader, because there were two — ``core/cli.py`` inlined the
    suffix test and :func:`~core.campaign.hitl.review_plan` has its own for
    the file it just wrote — and two readers of one format is how a plan an
    operator edited comes back parsed by rules the harness did not use to
    write it.
    """
    path = Path(path)
    raw = path.read_text()
    if path.suffix in {".yml", ".yaml"}:
        import yaml
        return CampaignPlan.model_validate(yaml.safe_load(raw) or {})
    return CampaignPlan.model_validate_json(raw)


def plan_digest(plan: CampaignPlan) -> str:
    """A stable name for exactly this plan.

    What an approval is *for*.  A decision recorded against a campaign is a
    decision about the steps somebody read, and a run that quoted the
    approval id back while carrying a different plan would be the standing
    permission the approvals module exists not to have — so the digest
    travels in the approval's arguments and is compared on the way back in.
    Sorted keys and no whitespace, so a plan re-serialised by a different
    pydantic version is still the same plan.
    """
    body = json.loads(plan.model_dump_json())
    return hashlib.sha256(json.dumps(body, sort_keys=True,
                                     separators=(",", ":"))
                          .encode("utf-8")).hexdigest()[:32]


def campaign_meta(plan: CampaignPlan) -> Dict[str, Any]:
    """The run metadata that says *this run is a campaign*.

    Written beside the swarm's ``plan``/``steps_done`` checkpoint, and it is
    what lets ``--resume`` continue a campaign **as a campaign**.  The rule
    it extends is the CLI's own: which runner continues a recorded run is
    the *run's* fact and not the resuming command line's.  A recorded
    campaign resumed by the staged runner would re-run its steps without
    their artifacts and without their scopes, which is the half-continued
    resume the staged path already refuses in its own case.

    The whole plan and not a flag: the plan is immutable once approved, so
    the resumed stretch must run the plan that was approved rather than
    whichever file happens to be on disk now.
    """
    return {"campaign": json.loads(plan.model_dump_json()),
            "campaign_digest": plan_digest(plan)}


def _as_plan_steps(plan: CampaignPlan) -> List[PlanStep]:
    """A campaign's steps in the vocabulary the parent loop already speaks,
    in DAG order.

    ``id``/``goal``/``needs``/``done`` are the four the loop reads, and
    ``rung`` — which for a plan step names *how* the work is done — names
    the step's task template here, which is the same kind of fact.  So the
    ``plan`` field on the first ``step_started`` is the shape a consumer
    already renders, ``branch`` groups a step's records as it does a
    stage's, and the checkpoint a restart reads is the one
    :meth:`~core.runtime.swarm.PlanStep.as_state` writes.

    **Sorted here and nowhere else.**  The inherited loop pops ``queue[0]``
    when nothing may run beside it — "not the first *ready* step but the
    first step", which is right for a plan a planner wrote in the order it
    means them to happen and wrong for a plan file, where the steps are in
    whatever order a person typed them.  Sorting the list once at the door
    makes plan order a valid DAG order, and then the whole of the
    inherited scheduling is correct without a second scheduler:
    :func:`~core.campaign.validator.toposort` breaks ties by the plan's own
    order, so a plan already written in dependency order runs exactly as
    its author read it.

    A step the sort could not place — only reachable through a cycle, which
    :class:`CampaignRunner` refuses at construction — is appended rather
    than dropped, so this function cannot silently lose a step.
    """
    order = toposort(plan)
    placed = {sid: n for n, sid in enumerate(order)}
    steps = sorted(plan.steps,
                   key=lambda step: placed.get(step.step_id, len(placed)))
    return [PlanStep(id=step.step_id, goal=step.description,
                     rung=step.target_workflow,
                     needs=list(step.inputs_from),
                     done=step.success_criteria)
            for step in steps]


# ── the runner ──────────────────────────────────────────────────────────────


class CampaignRunner(SwarmRunner):
    """A campaign plan, dispatched as children of one :class:`Run`.

    Parameters:

    run:
        The turn.  Adopted whole — one plane, one clock, one supervisor,
        one observer, one ledger — exactly as
        :meth:`~core.runtime.swarm.SwarmRunner.from_run` adopts it, and
        through the same ``_adopt``, so a campaign and a staged turn are
        made of the same six objects.
    plan:
        The :class:`~core.contracts.campaign.CampaignPlan`.  Validated
        here; a plan with a fault raises :class:`CampaignRefused` naming
        every one of them, before anything is asked of a model.
    workspace:
        Where ``sessions/<campaign_id>/steps/<step_id>/`` lives — the
        handoff directories a step reads and writes.  Defaults to the
        process's working directory, which is what a person running
        ``--campaign-plan ./mission.json`` means.
    templates:
        ``{name: TaskTemplate}`` — the menu a plan's ``target_workflow``
        may pick from, on top of the kernel's installed workflows.  Built
        by the caller from the packs it loaded (:func:`templates_of`),
        because :mod:`core.skills.library` is the one owner of a pack's
        layout and this class must not become a second one.
    packs:
        ``{pack name: Personality}`` — what a step under a template
        belonging to that pack is told.  A step whose template names a pack
        nobody supplied runs under the turn's own persona, which is the
        single-skill campaign and is the common case.
    parallel:
        How many steps may run at once.  ``1``, the default, is serial.
        See :meth:`_wave` for why a wave is not simply "everything ready".
    auto_approve:
        Skip the approval.  ``--auto-approve`` on the command line and
        ``auto_approve=True`` in a test; it takes no id and answers
        nothing, it declines to ask.  The absence of an ``approve_if`` is
        the same absence :meth:`~core.runtime.approvals.ApprovalStore
        .request` documents.
    interactive:
        Whether a person is at a terminal and may edit the plan in
        ``$EDITOR`` (:func:`~core.campaign.hitl.review_plan`).  The
        decision is still written to the approval store — one mechanism,
        two ways to answer it.
    """

    def __init__(self, run: Run, plan: CampaignPlan, *,
                 workspace: Any = None,
                 templates: Optional[Mapping[str, TaskTemplate]] = None,
                 packs: Optional[Mapping[str, Personality]] = None,
                 parallel: int = 1,
                 auto_approve: bool = False,
                 interactive: bool = False,
                 summary_chars: Optional[int] = None):
        self._templates: Dict[str, TaskTemplate] = dict(templates or {})
        self._packs: Dict[str, Personality] = dict(packs or {})
        self._auto_approve = bool(auto_approve)
        self._interactive = bool(interactive)
        #: The plan's steps by id, in the schema's own vocabulary — what
        #: `_as_plan_steps` deliberately drops (the artifacts, the
        #: capabilities, the exports) and what this class needs back.
        self._steps: Dict[str, MissionStep] = {}
        #: What each step may do: the intersection, computed once from the
        #: plan rather than asked for at run time. `ROADMAP.md` §5.1
        #: invariant 10 — the LLM can only narrow, never escalate.
        self._scopes: Dict[str, Tuple[str, ...]] = {}
        self._plan = self._adopt_plan(plan)
        self._session = CampaignSession(Path(workspace or Path.cwd()),
                                        campaign_id=plan.campaign_id)
        #: The persona of the step running in THIS task, or ``""`` for the
        #: turn's own.  A context variable for the reason
        #: :attr:`~core.tools.capability.CapabilityEngine._constraints` is
        #: one: two steps of a wave are two tasks, and an attribute would
        #: give both of them whichever persona was set last.
        self._persona_var: "ContextVar[str]" = ContextVar(
            f"judais_lobi_campaign_persona_{id(self):x}", default="")
        self._adopt(run, None, summary_chars, parallel)
        self._adopt_templates()

    # ── what a plan may name, and what each step may do ─────────────────

    def _adopt_plan(self, plan: CampaignPlan) -> CampaignPlan:
        """Validate *plan* and derive everything this class reads off it.

        Called twice: at construction, and again when a person **edits** the
        plan in ``$EDITOR`` at HUMAN_REVIEW.  It is one method because the
        second call is the whole reason the first one cannot simply be
        inline — a review that produced a different plan while
        :attr:`_steps` and :attr:`_scopes` still described the plan it
        replaced would dispatch the *approved* steps under the *proposed*
        steps' artifacts and permissions, which is precisely the failure a
        human review exists to prevent.

        Returns the plan, so the caller assigns :attr:`_plan` from it and
        there is no window in which the two disagree.
        """
        faults = validate_campaign_plan(plan, self._vocabulary())
        if faults:
            raise CampaignRefused(
                f"campaign {plan.campaign_id!r} will not run: "
                + ", ".join(faults))
        self._steps = {step.step_id: step for step in plan.steps}
        self._scopes = {step.step_id: tuple(sorted(self._effective(step)))
                        for step in plan.steps}
        return plan

    def _vocabulary(self) -> Tuple[str, ...]:
        """Every name a step's ``target_workflow`` may take.

        The supplied templates and the kernel's installed workflows, so one
        class runs February's plans (``coding``/``generic``) and a pack's
        plans (``find_and_report``) without a second validator for each.
        The kernel's list is asked for rather than assumed, and a kernel
        that cannot be imported contributes nothing rather than failing —
        a campaign of pack templates owes the coding kernel nothing.
        """
        names = set(self._templates)
        try:
            from core.kernel.workflows import list_workflows
            names.update(list_workflows())
        except Exception:                       # pragma: no cover - defensive
            pass
        return tuple(sorted(names))

    def _effective(self, step: MissionStep) -> Set[str]:
        """What *step* may do: its own scopes, capped by its template's.

        Through :func:`~core.campaign.scope.effective_scopes`, which is the
        one place this repo writes the intersection.  A step names what it
        needs (``capabilities_required`` plus the optional ones it may
        use); a template that declares ``scopes:`` is a ceiling over that;
        a template that declares none has no opinion and caps nothing.  The
        profile and any ``--grant`` are the *other* half and are applied by
        the capability engine at dispatch, which is why they are not
        intersected here: a scope in this set that the profile lacks is
        still refused, and the refusal names the profile.
        """
        template = self._templates.get(step.target_workflow)
        wanted = list(step.capabilities_required) + \
            list(step.capabilities_optional)
        return effective_scopes(wanted,
                                None if template is None else template.scopes)

    def _adopt_templates(self) -> None:
        """Teach the inherited executor how to describe a template.

        :meth:`~core.runtime.swarm.SwarmRunner._step_objective` renders
        ``Do it via: <sentence for this step's rung>`` out of
        ``self._rung_sentences``, which ``_adopt`` builds per instance.  A
        campaign step's rung is its template's name, so putting the
        template's sentence in that dict is the whole of what it takes for
        the inherited prompt builder to describe a campaign step — instead
        of a second prompt builder that would then have to be kept saying
        the same thing.
        """
        for name, template in self._templates.items():
            self._rung_sentences[name] = template.sentence()

    # ── the persona a step runs under ───────────────────────────────────

    @property
    def _persona(self) -> str:
        """The bytes the step running in THIS task opens with.

        The turn's own persona everywhere else — the synthesizer, and any
        step whose template names no pack — so a single-skill campaign
        emits exactly the prompts a staged turn does.  A step whose
        template names a pack the caller supplied opens with that pack's
        skill instead, which is what makes a campaign a *mission set*
        rather than one skill run several times.
        """
        return self._persona_var.get() or self._run.personality.system_message

    def _persona_of(self, step_id: str) -> str:
        """The persona for one step, or ``""`` for the turn's own."""
        template = self._templates.get(
            self._steps[step_id].target_workflow) if step_id in self._steps \
            else None
        pack = self._packs.get(template.skill) if template else None
        return pack.system_message if pack is not None else ""

    # ── the turn ────────────────────────────────────────────────────────

    def run(self, objective: str = "",
            resumption: Optional[Any] = None) -> MissionTranscript:
        """:meth:`arun`, run to completion.  **This method is the wrapper.**

        The inherited one, with the objective made optional for the reason
        :meth:`arun` gives: a campaign's objective is a field of the plan.
        It makes no decision, emits no record and holds no state; the turn
        is :meth:`arun`, and both go through the one function this package
        has for "a synchronous caller of an asynchronous loop".
        """
        return super().run(objective, resumption)

    async def arun(self, objective: str = "",
                   resumption: Optional[Any] = None) -> MissionTranscript:
        """Announce, get the plan approved, then dispatch it.

        The staged turn's :meth:`~core.runtime.swarm.SwarmRunner.arun` with
        the two model round trips that decide *what to do* taken out and a
        person put in their place.  There is no router — a campaign is a
        campaign because somebody said so — and no planner: the steps were
        written or were drafted and then **read**.  What is left is the
        same shape: announce before anything is asked, hand the plan to
        :meth:`~core.runtime.swarm.SwarmRunner._staged`, and emit
        ``mission_finished`` from a ``finally`` however the turn ended.

        *objective* defaults to the plan's own, which is the honest default:
        a campaign's objective is a field of the thing that was approved,
        not a sentence typed beside it.

        *resumption* is a
        :class:`~core.runtime.resume.StagedResumption` — the same object
        the staged path resumes from, because a campaign checkpoints the
        same ``plan``/``steps_done`` — and a resumed campaign **does not
        ask for approval again**: the plan on the record is the plan that
        was approved, one run, one decision.
        """
        objective = objective or self._plan.objective
        self._ledger = Ledger()
        self._model.ledger = self._ledger
        self._started_at = self._bounds.begin()
        transcript = MissionTranscript(objective=objective,
                                       catalogue=list(self._run.offered),
                                       usage=self._ledger)
        try:
            if resumption is not None:
                self._called = list(resumption.called)
            else:
                self._observer.emit(MISSION_STARTED,
                                    **self._run.opening(objective))
                stop = self._bounds.stop()
                if stop is not None:
                    return Run._stopped(transcript, stop)
                if not self._approve(objective, transcript):
                    return transcript
                # The plan, in the metadata, BEFORE the first step of it
                # runs — and it is what makes a resume of this run a
                # campaign rather than a staged turn.
                self._checkpoint(**campaign_meta(self._plan))
            # AFTER the approval, and that is not tidiness: a person who
            # edits the plan in `$EDITOR` at HUMAN_REVIEW changes what runs,
            # and a list of steps read before they were asked would be the
            # plan they were shown rather than the plan they approved.
            return await self._staged(objective, _as_plan_steps(self._plan),
                                      transcript, resumption=resumption)
        finally:
            self._observer.emit(MISSION_FINISHED, **_finished_record(
                started_at=self._started_at,
                outcome=transcript.outcome,
                steps=len(transcript.steps),
                max_steps=self._bounds.max_steps,
                budget=transcript.budget,
                reason=transcript.reason,
                usage=self._ledger.as_record(self._model.rate)))

    # ── HUMAN_REVIEW, as an approval record ─────────────────────────────

    def _approve(self, objective: str,
                 transcript: MissionTranscript) -> bool:
        """Whether this plan may be dispatched.  ``False`` stops the turn.

        **One approvals mechanism, two ways to answer it.**  February's
        campaign had a HUMAN_REVIEW phase of its own — write the plan to a
        file, open ``$EDITOR``, read it back — and this harness had already
        built a durable approval store for gated tool calls, with a
        ``gate_requested`` record on the wire, an id that outlives the
        process and ``--approval <id>`` to carry a decision back into the
        next run.  Two mechanisms for "a person says yes" is one too many,
        and the one that survives is the durable one: an ``$EDITOR`` loop
        cannot be answered by a platform, cannot be answered tomorrow, and
        leaves no record of who said yes.

        So the plan is filed as an approval — :data:`CAMPAIGN_TOOL`, with
        the whole plan and its digest in ``arguments`` — and there are
        three ways it comes back approved:

        * ``auto_approve``: the caller declined to ask.  A test, or
          ``--auto-approve``.
        * a ticket: ``--approval <id>`` on a later run, resolved at the
          door by :func:`~core.runtime.approvals.resolve` like any other.
          The digest is compared, so a yes to one plan is not a yes to the
          plan that replaced it.
        * ``$EDITOR``, when a person is at a terminal: the plan is opened,
          what they save is re-validated, and the *decision they made by
          saving it* is written to the store as a decision.  The record
          exists either way, which is the whole point.

        Anything else ends the turn at ``awaiting_approval`` holding the
        plan — the same outcome word, the same ``gate_requested`` record
        and the same resume as a gated tool call, because it is the same
        kind of stop.
        """
        if self._auto_approve:
            return True
        ticket = self._run.store.ticket
        if ticket is not None and ticket.tool == CAMPAIGN_TOOL:
            if self._ticket_matches(ticket):
                ticket.spend()
                return True
        arguments = {"campaign_id": self._plan.campaign_id,
                     "digest": plan_digest(self._plan),
                     "plan": json.loads(self._plan.model_dump_json())}
        reason = (
            f"campaign {self._plan.campaign_id!r} proposes "
            f"{len(self._plan.steps)} step(s) and has not been approved. "
            f"The plan is on this record; approve it and pass the id back "
            f"as --approval <id>.")
        if self._interactive:
            edited = self._reviewed()
            if edited is not None:
                # Through `_adopt_plan`, so the steps, the artifacts and the
                # scopes this class reads are the EDITED plan's. It cannot
                # raise here: `_reviewed` already re-validated, and returns
                # `None` for a plan that no longer does.
                self._plan = self._adopt_plan(edited)
                return True
            reason = (f"{reason} The editor did not return a usable plan, "
                      f"so nothing was decided.")
        approval_id, trouble = self._run._request_approval(
            objective, CAMPAIGN_TOOL, arguments, reason)
        if trouble:
            reason = f"{reason} {trouble}"
        carried = {"approval_id": approval_id} if approval_id else {}
        self._observer.emit(GATE_REQUESTED, index=0, tool=CAMPAIGN_TOOL,
                            arguments=arguments, reason=reason, **carried)
        transcript.outcome = AWAITING_APPROVAL
        transcript.awaiting = {"tool": CAMPAIGN_TOOL,
                               "arguments": arguments, **carried}
        return False

    def _ticket_matches(self, ticket: Any) -> bool:
        """Whether an approved ticket is a yes to **this** plan.

        The digest and not the campaign id: an operator who edits a step
        and reruns with the same id is proposing a different campaign, and
        a decision made about the plan they read must not carry over to the
        plan they did not.  A store that cannot be read back answers
        ``False`` — a yes nobody can produce is not a yes.
        """
        store = self._run.store.approvals
        if store is None:
            return False
        try:
            approval = store.get(ticket.approval_id)
        except Exception:
            return False
        return str((approval.arguments or {}).get("digest") or "") == \
            plan_digest(self._plan)

    def _reviewed(self) -> Optional[CampaignPlan]:
        """The plan as a person edited it, or ``None`` if that did not work.

        :func:`~core.campaign.hitl.review_plan` is the one owner of the
        ``$EDITOR`` round trip and of reading back what was saved; what is
        added here is the re-validation, because a plan somebody edited is
        a plan that can have grown a cycle.  Every failure is ``None`` and
        the turn falls through to the durable request: an editor that is
        not configured, a person who saved nonsense, or a plan that no
        longer validates are all "nobody decided this", which is the state
        the approval record exists to hold.
        """
        path = self._session.campaign_dir / "campaign.plan.json"
        try:
            edited = review_plan(self._plan, path)
        except (HumanReviewError, OSError):
            return None
        if validate_campaign_plan(edited, self._vocabulary()):
            return None
        store = self._run.store.approvals
        if store is not None:
            try:
                approval_id = store.request(
                    tool=CAMPAIGN_TOOL,
                    arguments={"campaign_id": edited.campaign_id,
                               "digest": plan_digest(edited)},
                    objective=edited.objective,
                    run_id=self._run.store.run_id,
                    reason="reviewed in $EDITOR")
                store.decide(approval_id, approve=True, decided_by="editor",
                             note="saved from $EDITOR")
                store.consume(approval_id)
            except Exception:                   # pragma: no cover - defensive
                pass
        return edited

    # ── the four differences from a plan a model drew ───────────────────

    def _wave(self, queue: List[PlanStep],
              results: Dict[str, _StepOutcome]) -> List[PlanStep]:
        """Which steps run next, and only ones that may do the same things.

        The staged runner's answer, narrowed by one condition: every member
        of a wave must have the **same effective scopes**.

        That is not caution, it is the shape of the object.  A scope
        allowlist is set on the bus's one
        :class:`~core.tools.capability.CapabilityEngine`, because that is
        the object every dispatch consults; it is held in a context
        variable so that two children of one run can be narrowed
        differently, and a step's narrow therefore reaches exactly the task
        that set it.  A wave is a :func:`asyncio.gather` of tasks — so
        different scopes *would* in fact be honoured — but the wave is also
        the unit this class announces and checkpoints, and running two
        steps at once under two different sets of permissions is a claim
        this lane has not measured.  Equal scopes is the property that
        makes the wave obviously safe, and it costs a campaign nothing that
        matters: steps that may do the same things are exactly the steps a
        plan tends to fan out.

        ``parallel=1`` — the default — is one step at a time and this
        condition never fires.
        """
        wave = super()._wave(queue, results)
        if len(wave) <= 1:
            return wave
        first = self._scopes.get(wave[0].id)
        allowed = [step for step in wave
                   if self._scopes.get(step.id) == first]
        return allowed or wave[:1]

    def _redraw(self, objective: str, step: PlanStep,
                outcome: _StepOutcome, results: Dict[str, _StepOutcome],
                left: Optional[int]) -> List[PlanStep]:
        """Never.  A campaign plan is immutable once approved.

        ``ROADMAP.md`` §5.1, invariant 9: after the human approves a
        ``CampaignPlan`` the step DAG is frozen — steps may be retried,
        skipped or aborted, and inserting a step, reordering the DAG or
        changing a workflow assignment sends the campaign back to
        HUMAN_REVIEW.  This prevents the failure the invariant is named
        for: an LLM silently expanding the scope of what a person
        authorised.

        A staged turn redraws because its plan is the planner's guess; a
        campaign's plan is what somebody read and said yes to, and the
        harness quietly writing a different one would make the approval
        meaningless.  Returning ``[]`` is the inherited loop's own word for
        "out of moves": the failure becomes part of the answer, and the
        steps still queued are dropped rather than run against a hole —
        which is right here twice over, since their declared inputs are
        files the failed step did not write.
        """
        return []

    async def _execute_step(self, objective: str, step: PlanStep,
                            results: Dict[str, _StepOutcome],
                            left: Optional[int]):
        """One step, with its artifacts around it and its scopes under it.

        The middle is the staged runner's whole ``_execute_step`` — the
        child run, the gate, the supervisor's nudge and its verdicts, the
        ledger join — and it is called and not copied.  What a campaign
        adds is the three things that make a step a *task in a mission set*
        rather than a stage of one mission, and all three happen here
        because here is inside the step's own task and therefore inside its
        own context:

        1. **Handoff in.**  Every artifact this step declared it takes is
           copied out of the producing step's ``handoff_out/`` into this
           step's ``handoff_in/`` — by :func:`~core.campaign.handoff
           .materialize_handoff`, which refuses a symlink and refuses any
           path that would land outside those two directories.  What was
           actually materialised rides this step's ``step_started`` as
           ``artifacts.in``: a declared input whose producer never wrote it
           does not appear, and the step is told as much in its objective.
        2. **Least privilege.**  The plane is narrowed to this step's
           effective scopes.  Set here, in this coroutine, so that a
           sibling in the same wave is not narrowed by it — see
           :attr:`~core.tools.capability.CapabilityEngine._constraints`.
        3. **Handoff out.**  Every artifact this step declared it exports
           is looked for in its ``handoff_out/``.  A step that promised a
           file and did not write it **did not do the step**, whatever it
           said about itself — the campaign's own gate, mechanical, over
           and above the staged runner's.
        """
        mission = self._steps[step.id]
        step_dir = self._session.step_dir(step.id)
        arrived = self._handoff_in(mission, step_dir)
        self._observer.carry(branch=step.id,
                             artifacts={"in": arrived,
                                        "out": list(mission.exports)})
        self._plane.narrow(self._scopes.get(step.id, ()))
        persona = self._persona_of(step.id)
        if persona:
            self._persona_var.set(persona)
        outcome, attempts, evidence, spent = await super()._execute_step(
            objective, step, results, left)
        return (self._handoff_out(mission, step_dir, outcome),
                attempts, evidence, spent)

    def _step_objective(self, objective: str, step: PlanStep,
                        results: Dict[str, _StepOutcome],
                        failure: str = "") -> str:
        """The staged executor's prompt, plus the files this step owes.

        Appended rather than rewritten, for the reason the rung sentence is
        installed into the inherited dict rather than rendered here: the
        prompt a step is given has one builder, and a second one would
        eventually open with different bytes — which a served endpoint's
        prefix cache charges for.

        The paths are absolute and are named, because a step is a child run
        whose tools take paths: telling it *where* its inputs are and
        *where* its outputs go is the whole of the handoff contract from
        the model's side, and a step that has to guess writes its report
        somewhere the next step will not look.
        """
        text = super()._step_objective(objective, step, results, failure)
        brief = self._artifact_brief(step.id)
        return f"{text}\n\n{brief}" if brief else text

    # ── the artifacts ───────────────────────────────────────────────────

    def _artifact_brief(self, step_id: str) -> str:
        """What this step was handed and what it owes, as one paragraph."""
        mission = self._steps.get(step_id)
        if mission is None:                     # pragma: no cover - defensive
            return ""
        step_dir = self._session.step_dir(step_id)
        lines: List[str] = []
        arrived = sorted(
            str(path.relative_to(step_dir / HANDOFF_IN))
            for path in (step_dir / HANDOFF_IN).rglob("*") if path.is_file())
        if mission.handoff_artifacts:
            wanted = [ref.artifact_name for ref in mission.handoff_artifacts]
            missing = [name for name in wanted if name not in arrived]
            lines.append(
                f"Input artifacts from earlier steps are in "
                f"{step_dir / HANDOFF_IN} — read them there: "
                + (", ".join(arrived) if arrived else "(none arrived)"))
            if missing:
                lines.append(
                    f"These were expected and are NOT there: "
                    f"{', '.join(missing)}. Say so rather than inventing "
                    f"their contents.")
        if mission.exports:
            lines.append(
                f"Write these output artifacts, with exactly these names, "
                f"into {step_dir / HANDOFF_OUT}: "
                f"{', '.join(mission.exports)}. A later step reads them "
                f"from there, so the step is not done until they exist.")
        return "\n".join(lines)

    def _handoff_in(self, mission: MissionStep, step_dir: Path) -> List[str]:
        """Materialise this step's declared inputs.  Returns what arrived.

        :func:`~core.campaign.handoff.materialize_handoff` does the copying
        and owns every safety rule about it; this turns the paths it
        returns back into the artifact names the plan speaks, because those
        are what the record and the prompt say.
        """
        root = step_dir / HANDOFF_IN
        copied = materialize_handoff(self._session.campaign_dir, step_dir,
                                     mission.handoff_artifacts)
        names: List[str] = []
        for path in copied:
            try:
                names.append(str(Path(path).relative_to(root)))
            except ValueError:                  # pragma: no cover - defensive
                names.append(Path(path).name)
        return sorted(names)

    def _handoff_out(self, mission: MissionStep, step_dir: Path,
                     outcome: _StepOutcome) -> _StepOutcome:
        """Collect the step's exports, and fail it for the ones missing.

        The campaign's own gate, and it is mechanical on purpose.  The
        staged runner's gate asks whether the executor's *report* meets the
        step's success condition; a campaign step's success condition is
        very often a *file*, and a model that says "I have written the
        report" is not evidence that a report exists.  A declared export
        that is not in ``handoff_out/`` fails the step by name, which is
        also the only way the next step's handoff could have been honest.

        A step that already failed is left as it failed: the first reason
        is the reason, and appending "and it also did not write x" to a
        step that never ran would be noise.
        """
        if not outcome.ok or not mission.exports:
            return outcome
        root = step_dir / HANDOFF_OUT
        missing = [name for name in mission.exports
                   if not (root / name).is_file()]
        if not missing:
            return outcome
        return replace(
            outcome, ok=False, summary="",
            why=(f"the step declared it exports {', '.join(mission.exports)} "
                 f"and did not write {', '.join(missing)} into {root}"))

    # ── the checkpoint says which runner continues this run ─────────────

    def artifacts_of(self, step_id: str) -> List[str]:
        """The files one finished step actually left in its ``handoff_out``.

        For a caller that wants the campaign's products rather than its
        prose — the CLI prints them, and a platform collecting a mission
        set's output reads them.  Sorted, relative, files only.
        """
        root = self._session.step_dir(step_id) / HANDOFF_OUT
        return sorted(str(path.relative_to(root))
                      for path in root.rglob("*") if path.is_file())

    @property
    def campaign_dir(self) -> Path:
        """Where this campaign's steps and their artifacts live."""
        return self._session.campaign_dir


def resumed_campaign(meta: Mapping[str, Any]) -> Optional[CampaignPlan]:
    """The plan a recorded run was approved to execute, or ``None``.

    The reader beside :func:`campaign_meta`'s writer, so "is this run a
    campaign, and which plan is it" has one answer.  ``None`` for every run
    that is not one, which is what a staged or direct resume reads.  A
    metadata blob that will not parse back into a plan is ``None`` too: a
    resume that cannot recover the approved plan must fall back to refusing
    rather than invent one.
    """
    body = meta.get("campaign") if isinstance(meta, Mapping) else None
    if not isinstance(body, Mapping):
        return None
    try:
        return CampaignPlan.model_validate(dict(body))
    except Exception:
        return None
