# core/kernel/roles.py — the phase roles the orchestrator dispatches to

"""What actually happens inside a phase.

The orchestrator has always decided *which* phase runs next; nothing
decided what happened *in* one. ``Agent._make_task_dispatcher`` returned
a ``StubDispatcher`` whose whole body was ``return PhaseResult(success=
True)``, so ``run_task()`` walked INTAKE → … → COMPLETED, wrote nothing,
changed nothing, and reported success. That is the worst shape a stub
can take: not missing, but indistinguishable from working.

This module supplies the missing half.

**Three kinds of role, and the split is not an implementation detail.**
Some phases are a question for a model; some are a fact about the
repository. Asking a model to produce a ``RepoMapResult`` would be
asking it to invent a file listing it cannot see, and asking it whether
the tests passed would be asking it to invent an exit code. So:

* :class:`LLMPhaseRole` — the model is asked, and its reply must parse
  into the phase's schema. INTAKE, CONTRACT, PLAN.
* :class:`ToolPhaseRole` — a tool is dispatched through the ToolBus and
  the artifact is built from what came back. REPO_MAP, RUN, CRITIQUE.
* :class:`AuthoredToolPhaseRole` — the model *authors a request* and a
  tool then *settles* it: the artifact records what the tool actually
  did, not what the model asked for. RETRIEVE, PATCH, FIX.

The third kind exists because of a bug this module shipped with. PATCH
was an :class:`LLMPhaseRole`: it asked the model for a ``PatchSet``,
the ``PatchSet`` validated, the phase succeeded — and nothing ever put
it on disk. ``PatchEngine.apply`` existed, was tested, and was called
from no role. RUN then ran the tests against an unchanged tree and
passed, CRITIQUE scored a diff that was never written, and the session
walked INTAKE → COMPLETED producing artifacts that each validated and
connected to nothing. Exactly the shape named above: *not missing, but
indistinguishable from working*.

Asking a model for a patch is legitimate — a patch is a proposal, and
proposing is what a model is for. Believing the patch landed because
the model said so is the same error as asking it whether the tests
passed. So the phase has two halves and the second one is a tool: the
model authors, ``patch apply`` disposes, and the phase fails if the
tool says the change did not land.

All three share :meth:`PhaseRole.run`, which is **final**, and the reason it
is final is the bug above: *a role never declares its own success*. The
template asks the subclass for an output and then decides, from whether
that output satisfies the phase's schema, whether the phase succeeded.
A subclass physically cannot return ``PhaseResult(success=True)``,
because it never constructs a ``PhaseResult`` at all.

**Nothing here reaches past the ToolBus.** A role that wants the
filesystem dispatches ``fs``; a role that wants the tests dispatches
``verify``. The orchestrator has already narrowed the capability engine
to the phase's scopes by the time :meth:`run` is called, so a role
asking for something the phase may not do gets a structured
``capability_denied`` and turns it into a failed phase — which burns a
retry and is visible in the audit log, rather than being a traceback.
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple, Type

from core.bounding import bound_result
from core.kernel.budgets import BudgetConfig
from core.kernel.orchestrator import PhaseResult
from core.kernel.state import SessionState
from core.runtime.context_window import (
    COMPACTION_MARK, Compaction, ContextConfig, MissionWindow,
    ModelContextProfile,
)

_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.MULTILINE)

#: Trace lines a role's prompt is offered. The window below decides how
#: many of them actually go — this is only how far back a role looks.
TRANSCRIPT_TURNS = 6

#: The newest trace line a role's prompt will never drop. One, not two:
#: the last thing in a role's transcript is the result the next reply is
#: made of, and a prompt that has evicted it asks the model to continue
#: from work it can no longer see. Compare
#: :data:`~core.runtime.context_window.MISSION_MIN_TAIL`, which keeps the
#: whole round trip because a mission's transcript *is* the conversation;
#: a role's is working memory the phase rebuilds every turn.
ROLE_MIN_TAIL = 1


def role_compaction_note(dropped_turns: int, freed_chars: int,
                         dropped_results: int = 0) -> str:
    """What a role is told in place of the trace lines that were dropped.

    Said out loud for the reason the mission's note is: a phase handed a
    silently shortened transcript cannot see that anything is missing, and
    the coding loop's answer to "I cannot see the test output" is to run
    the tests again — a phase out of a budget of thirty spent
    rediscovering something it was told and then had taken away.

    *dropped_results* is the third argument every note callable is handed
    by :meth:`~core.runtime.context_window.MissionWindow.fit`.  It is
    counted and not said here: a role's trace is phases talking, and the
    window's tool/chat distinction has nothing to name in it.
    """
    return (
        f"{COMPACTION_MARK} Earlier phases of this task were removed from "
        f"this prompt so that it fits the model's context window: "
        f"{dropped_turns} model turn(s), {freed_chars} characters. Those "
        f"phases ran and their artifacts are on disk — what is gone is the "
        f"paste of them, not the work. Do not repeat a step merely because "
        f"its output is no longer above."
    )


class RoleWindow(MissionWindow):
    """The window one role's prompt is fitted to. The smaller limit wins.

    Two numbers meet here. ``BudgetConfig.max_context_tokens_per_role`` is
    what a deployment is willing to spend on a single phase; the resolved
    profile's ``max_input_tokens`` is what the endpoint will actually
    accept. **The smaller of the two wins**, and the asymmetry is the
    point: the per-role budget is a *choice* and exceeding it only costs
    money, while the profile is a *fact* and exceeding it is a request the
    server refuses — so neither number may be raised by the other.

    *base* is a window the caller already built (the CLI builds one for the
    mission path from the same provider, model and client). Its profile is
    reused rather than resolved a second time, so a role prompt never costs
    a second ``GET /models`` and never disagrees with the mission loop
    about how big the window is. With no base there is no model profile at
    all: nothing is probed, and the per-role budget is the whole limit —
    which is what a library caller gets until it passes one, and what every
    test that injects a fake client gets without asking.

    Everything else — the estimate, the pinned prefix, dropping the oldest
    round trips whole, the note left in their place — is
    :class:`~core.runtime.context_window.MissionWindow`'s, unchanged.
    """

    def __init__(self, base: Optional[MissionWindow] = None, *,
                 per_role_tokens: int = 0,
                 min_tail_messages: int = ROLE_MIN_TAIL):
        # An empty ContextConfig rather than the default one: with a base
        # the manager is never consulted, and without a base there is no
        # profile to resolve, so `ContextConfig.from_project()` would be a
        # project-file read whose answer nothing ever looks at.
        super().__init__(config=ContextConfig(),
                         min_tail_messages=min_tail_messages)
        self._base = base
        self._per_role = max(0, int(per_role_tokens))

    @property
    def profile(self) -> ModelContextProfile:
        if self._base is None:
            return ModelContextProfile(self._per_role, 0,
                                       source="per_role_budget")
        return self._base.profile

    @property
    def limit_tokens(self) -> int:
        """Input tokens one role turn may fill: the smaller of the two."""
        model_limit = self.profile.max_input_tokens
        if self._per_role <= 0:
            return model_limit
        if model_limit <= 0:
            return self._per_role
        return min(self._per_role, model_limit)


def _truncate_messages(messages: List[Dict[str, str]],
                       cap_chars: int) -> List[Dict[str, str]]:
    """Cut any single message longer than *cap_chars*, saying so in it.

    What is left of the guard :meth:`RoleContext.ask` used to be, kept for
    the one thing the window cannot do: shrink a message it is not allowed
    to drop. A message that is on its own larger than the whole window — a
    repository pasted into the task, a tool result that reached the trace
    ahead of the byte bound — would otherwise be sent entire no matter what
    the accounting said.
    """
    trimmed = []
    for message in messages:
        content = message.get("content") or ""
        if len(content) > cap_chars:
            content = (
                content[:cap_chars]
                + f"\n[...truncated at the {cap_chars}-character prompt limit]"
            )
        trimmed.append({**message, "content": content})
    return trimmed


class RoleMisdeclared(TypeError):
    """A role subclass is unusable, with every reason in one message."""


class RoleRefused(Exception):
    """A role could not produce its output. Becomes a failed phase.

    An exception rather than a return value so a subclass cannot
    accidentally report a refusal as an output — the same reason
    :meth:`PhaseRole.run` is final.
    """


def _stub(method: Callable) -> Callable:
    """Mark a base-class method as a placeholder a subclass must replace.

    ``__init_subclass__`` used to detect an unimplemented method by
    comparing it against :class:`PhaseRole`'s own attribute. That works
    for exactly one level: an intermediate base which introduces a
    *new* required method has its own stub inherited by the subclass,
    the identity check against ``PhaseRole`` finds nothing to compare,
    and a subclass that implements neither half is declared usable. The
    marker travels with the function instead of with the class, so the
    check is level-independent.
    """
    method._role_stub = True  # type: ignore[attr-defined]
    return method


# ---------------------------------------------------------------------------
# The context a role is given
# ---------------------------------------------------------------------------

@dataclass
class RoleContext:
    """Everything a role may touch, and nothing else.

    Deliberately not the ``Agent``: a role holding an agent could reach
    ``agent.tools.run`` (which bypasses nothing, but does bypass the
    phase-scoped engine's *intent*), ``agent.memory``, and the
    filesystem through either. What a role gets is a chat function, a
    bus, and the workflow's own schema table.
    """

    chat: Callable[[List[Dict[str, str]]], Any]
    tool_bus: Any = None
    workflow: Any = None
    budget: BudgetConfig = field(default_factory=BudgetConfig)
    system_message: str = ""
    #: Everything the roles said and were told, in order, with who said it.
    #: The transcript is the session's working memory; artifacts are its
    #: output. One list, and not a list of lines beside a list of speakers,
    #: because two lists holding halves of one fact drift the first time
    #: something appends to only one of them.
    turns: List[Dict[str, str]] = field(default_factory=list)
    #: The window this session's model actually has, as the caller built it
    #: — a :class:`~core.runtime.context_window.MissionWindow`, the same
    #: class and the same three inputs the CLI's mission path uses. ``None``
    #: means no model profile is known and nothing will be probed to find
    #: one; the per-role budget is then the whole limit.
    window: Optional[MissionWindow] = None
    #: Every compaction this context has made, oldest first. Drained by the
    #: dispatcher onto the :class:`PhaseResult`, so the orchestrator can
    #: write it where the phase's other records go.
    compactions: List[Compaction] = field(default_factory=list)
    #: The :class:`~core.runtime.run.Bounds` this session's roles are held
    #: to: one clock, one operator ceiling, one control channel — the same
    #: object the mission loop is bounded by (Phase 11, one runtime). Handed
    #: in **by construction** so a role gets the deadline and the control
    #: channel the mission path has, even where the kernel path passes the
    #: default — no clock, no ceiling, ``None`` — today. Typed ``Any`` so
    #: this module stays a cheap import: the loop object it comes from pulls
    #: in every backend, and a role file that imported it at module load
    #: would make ``import core.kernel`` wait on that.
    bounds: Optional[Any] = None
    #: The durable half a role writes through — a
    #: :class:`~core.runtime.run.Store`. The seam is here even though the
    #: kernel path hands ``Store.none()`` today: a role given a store by
    #: construction is a role whose work survives the process the day the
    #: kernel path grows one, without a second wiring being invented then.
    store: Optional[Any] = None
    _window: Optional[RoleWindow] = field(default=None, init=False,
                                          repr=False, compare=False)
    #: The composed :class:`~core.runtime.run.Model` — ``ask``, ``window``
    #: and ``ledger`` in one object, the mission loop's own. Built once at
    #: first :meth:`ask`, so a role's usage folds into one ledger across the
    #: phase rather than into a fresh one per turn. Lazy for the reason
    #: :attr:`bounds` is.
    _model: Optional[Any] = field(default=None, init=False,
                                  repr=False, compare=False)

    @property
    def trace(self) -> List[str]:
        """The transcript as the lines it has always been.

        Read-only, deliberately: :meth:`remember` is the only writer, and
        it is the only place that knows who said the line.
        """
        return [turn["content"] for turn in self.turns]

    @property
    def prompt_window(self) -> RoleWindow:
        """The effective window: :attr:`window` narrowed by the budget."""
        if self._window is None:
            self._window = RoleWindow(
                self.window,
                per_role_tokens=self.budget.max_context_tokens_per_role,
            )
        return self._window

    @property
    def model(self) -> Any:
        """The :class:`~core.runtime.run.Model` this role asks through.

        ``RoleContext.ask`` used to be a hand-rolled model: a chat callable,
        a window, and — before the ledger existed — nowhere to put what a
        call cost.  Phase 11 makes it the mission loop's own object.  ``ask``
        is the role's ``chat``, ``window`` is the effective
        :class:`RoleWindow`, and ``ledger`` is one :class:`~core.runtime
        .usage.Ledger` built once and folded into on every turn — so a
        role's usage has the seam the mission's does, through the same
        :meth:`Model.spend`, even while the kernel path reports nothing yet.

        Built at first read and cached, so one phase's turns share one
        ledger rather than each opening a fresh one.  Imported here rather
        than at module load for the reason :attr:`bounds` is typed ``Any``:
        the loop object pulls in every backend, and a role file that loaded
        it eagerly would make ``import core.kernel`` wait on that.
        """
        if self._model is None:
            from core.runtime.run import Model
            from core.runtime.usage import Ledger
            self._model = Model(ask=self.chat, window=self.prompt_window,
                                ledger=Ledger())
        return self._model

    def schema_for(self, phase: str) -> Optional[Type]:
        if self.workflow is None:
            return None
        return self.workflow.phase_schemas.get(phase)

    def ask(self, messages: List[Dict[str, str]], *,
            pinned: Optional[int] = None) -> str:
        """One turn at the model, bounded by the window a role may fill.

        The turn goes through the composed :attr:`model` — a
        :class:`~core.runtime.run.Model` whose ``window`` is this role's
        effective :class:`RoleWindow` and whose ``ask`` is the role's chat
        function — so the kernel's roles ask a backend the same way the
        mission loop does.  What is sent is byte-for-byte what it was: the
        same window, the same estimator, the same per-message character cap,
        the same :func:`role_compaction_note` where a dropped round trip
        was.

        Two bounds, answering two different questions.

        The **window** decides what is sent. :class:`RoleWindow` — the
        smaller of the per-role budget and the model's real input budget —
        estimates the list with this repository's one estimator, drops the
        oldest trace round trips whole, and leaves
        :func:`role_compaction_note` where they were. Every drop is
        appended to :attr:`compactions`, so a shorter prompt is something
        the session recorded rather than something that happened to it.

        The **character cap** is the per-message backstop this whole method
        used to be. It is kept for what the window cannot do — shrink a
        message it is not allowed to drop — and it is now four characters
        to the token against the *effective* limit, not against the
        per-role budget alone as it was.

        *pinned* is how many messages at the front are not compactable.
        ``None`` pins all of them: a caller that has not said which part of
        its prompt is history is not one whose history may be dropped.

        The call's usage folds into the model's ledger through
        :meth:`Model.spend`, which is a no-op until a caller wires a usage
        source — the seam, not a second accountant.
        """
        model = self.model
        window = model.window
        limit = window.limit_tokens
        prompt = (_truncate_messages(messages, limit * 4) if limit > 0
                  else list(messages))
        fitted, compaction = window.fit(
            prompt,
            pinned=len(prompt) if pinned is None else pinned,
            note=role_compaction_note,
        )
        if compaction is not None:
            self.compactions.append(compaction)
        reply = str(model.ask(fitted) or "")
        model.spend(model.ledger)
        return reply

    def drain_compactions(self) -> List[Compaction]:
        """Take the compactions made since the last drain, and forget them.

        Drained rather than read so that a phase's record carries the
        compactions *that phase* made. A running total on the context would
        make every later phase's record a superset of every earlier one's,
        and a reader counting them would count the first phase's ten times.
        """
        drained, self.compactions = self.compactions, []
        return drained

    def dispatch(self, tool: str, *args: Any, **kwargs: Any):
        """Run a tool through the bus. The only way out of a role."""
        if self.tool_bus is None:
            raise RoleRefused(
                f"this phase needs the {tool!r} tool and no ToolBus was "
                f"given to the dispatcher"
            )
        return self.tool_bus.dispatch(tool, *args, **kwargs)

    def remember(self, line: str, *, speaker: str = "user") -> None:
        """One trace line, bounded to the tool-output budget.

        Head *and* tail, through :func:`core.bounding.bound_result`, and
        not the head-only cut this used to do.  A trace line is a tool
        result rendered for a later phase to read, and a tool result puts
        its totals at the end — a head-only cut kept the invocation and
        threw away the counts, which is the half the FIX and CRITIQUE
        phases are looking for.

        *speaker* is who the line came from, recorded here because here is
        the only place that knows: ``"assistant"`` for a reply the model
        wrote, ``"user"`` — the default, and the conservative one — for a
        result a tool produced. :meth:`transcript` needs it to hand the
        window whole round trips to drop, and of the two ways to get it
        wrong, a tool result mislabelled as the model's own words is the
        one that changes what the model believes it said.
        """
        line, _ = bound_result(line, self.budget.max_tool_output_bytes_in_context)
        self.turns.append({"role": speaker, "content": line})

    def recent(self, n: int = TRANSCRIPT_TURNS) -> str:
        return "\n\n".join(turn["content"] for turn in self.turns[-n:])

    def transcript(self, n: int = TRANSCRIPT_TURNS) -> List[Dict[str, str]]:
        """The last *n* trace lines as chat messages.

        The same lines :meth:`recent` renders, one message each instead of
        one blob. Separate messages because that is what gives the window
        something to drop: folded into a single turn, "what has happened so
        far" is one message that either fits whole or is cut mid-sentence by
        a character count, and the phase whose tool result was in the middle
        of it never learns that it went.
        """
        return [dict(turn) for turn in self.turns[-n:]]


# ---------------------------------------------------------------------------
# The base
# ---------------------------------------------------------------------------

class PhaseRole(ABC):
    """One phase's turn. Subclasses supply an output; never a verdict."""

    #: Workflow phase this role serves. Checked at class creation.
    phase: str = ""
    #: What this phase must produce, in words that go into the prompt or
    #: the failure message. Checked at class creation for the same reason
    #: a transport's ``name`` is: it is the string a human reads when this
    #: phase is the one that went wrong.
    instruction: str = ""

    _REQUIRED: Tuple[str, ...] = ("produce",)
    _FINAL: Tuple[str, ...] = ("run",)

    def __init_subclass__(cls, **kw: Any) -> None:
        super().__init_subclass__(**kw)
        # `cls.__dict__` and not `getattr`: `abstract` marks *this* class
        # as an intermediate base, and inheriting it would exempt every
        # role beneath it. It did. `LLMPhaseRole.abstract` is True, so
        # IntakeRole, PlanRole, PatchRole and every ToolPhaseRole came
        # through here and returned on the first line — the declaration
        # checks ran on nothing that ships. They happened to be declared
        # correctly, which is the only reason it never showed.
        if cls.__dict__.get("abstract", False):
            return
        problems = cls._declaration_problems()
        if problems:
            raise RoleMisdeclared(
                f"{cls.__name__} is not a usable PhaseRole:\n  - "
                + "\n  - ".join(problems)
            )

    @classmethod
    def _declaration_problems(cls) -> List[str]:
        """Every reason this class is unusable, gathered not raised.

        Gathered and not raised so an intermediate base that adds its
        own requirements can extend the list rather than raise a second
        exception. A subclass told about one mistake at a time learns
        about the next one only after a round trip, and the whole point
        of checking at class creation is that the whole answer arrives
        at once.
        """
        problems: List[str] = []
        if not cls.phase:
            problems.append(
                "`phase` is empty; the dispatcher keys roles by phase name "
                "and an unnamed one can never be selected"
            )
        if not cls.instruction:
            problems.append(
                "`instruction` is empty; it is what the model is told to "
                "produce and what a human reads when this phase is the one "
                "that failed, so a blank one costs both of them"
            )
        for attr in cls._REQUIRED:
            impl = getattr(cls, attr, None)
            if impl is None or getattr(impl, "_role_stub", False):
                problems.append(
                    f"does not implement `{attr}`; the base's stub refuses "
                    f"rather than inventing an answer"
                )
        for attr in cls._FINAL:
            if attr in cls.__dict__:
                problems.append(
                    f"overrides `{attr}`, which is final. It is the one place "
                    f"success is decided, and it decides it from whether the "
                    f"output validates — never from the role's own opinion. "
                    f"A role that could return PhaseResult(success=True) is "
                    f"StubDispatcher again, one class further down. Override "
                    f"`produce` instead"
                )
        return problems

    # ── the template. FINAL. ────────────────────────────────────────────

    def run(self, state: SessionState, ctx: RoleContext) -> PhaseResult:
        """Produce, then validate, then judge. In that order, always.

        1. ask the subclass for an output — the only part that varies;
        2. validate it against the phase's schema, if the workflow
           declares one. This happens here and not only in the
           orchestrator because the orchestrator validates only when a
           session manager is present, and a phase that "succeeded" with
           unusable output is exactly the failure this module exists to
           end;
        3. construct the ``PhaseResult``. The subclass never does.
        """
        try:
            output = self.produce(state, ctx)
        except RoleRefused as exc:
            return PhaseResult(success=False, error=str(exc))
        except Exception as exc:  # noqa: BLE001 — a role must not crash the run
            return PhaseResult(
                success=False,
                error=f"{self.phase} raised {type(exc).__name__}: {exc}",
            )

        schema = ctx.schema_for(self.phase)
        if schema is None:
            return PhaseResult(success=True, output=output)

        try:
            validated = (
                output if isinstance(output, schema)
                else schema.model_validate(output)
            )
        except Exception as exc:  # noqa: BLE001 — pydantic's own error text
            return PhaseResult(
                success=False,
                error=(
                    f"{self.phase} produced something that is not a "
                    f"{schema.__name__}: {exc}"
                ),
            )
        return PhaseResult(success=True, output=validated)

    # ── what a subclass supplies ────────────────────────────────────────

    @abstractmethod
    @_stub
    def produce(self, state: SessionState, ctx: RoleContext) -> Any:
        """Return this phase's output, or raise :class:`RoleRefused`."""
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Roles that ask the model
# ---------------------------------------------------------------------------

def _dispatch_and_remember(ctx: RoleContext, phase: str,
                           tool: Tuple[str, Optional[str]], **kwargs):
    """Run one tool through the bus and put the outcome in the trace.

    Shared by the two kinds of role that dispatch, so that "what the
    tool returned" is recorded identically whether the tool *is* the
    phase or only settles it. A role whose dispatch went unrecorded is
    a role whose failure has to be reconstructed from its consequences.
    """
    name, action = tool
    result = (ctx.dispatch(name, action=action, **kwargs) if action
              else ctx.dispatch(name, **kwargs))
    ctx.remember(
        f"[{phase}] {name}{'.' + action if action else ''} "
        f"exit={result.exit_code}\n{result.stdout or result.stderr}"
    )
    return result


class LLMPhaseRole(PhaseRole):
    """Asks the model and parses the reply into the phase's schema."""

    abstract = True

    #: Appended to the instruction when the phase has a schema. The model
    #: is shown the field names rather than told to "return valid JSON",
    #: because the second reliably produces valid JSON of the wrong shape.
    JSON_CONTRACT = (
        "Reply with exactly one JSON object and nothing else — no prose, no "
        "code fence. Keys: {keys}. Use only those keys."
    )

    #: Keys this role accepts beyond the schema's own. Pydantic ignores
    #: extras, so a role can ask for working input the artifact does not
    #: carry — but the model has to be *told* the key exists, or the
    #: contract line above forbids the very thing the instruction asks for.
    extra_keys: Tuple[str, ...] = ()

    def produce(self, state: SessionState, ctx: RoleContext) -> Any:
        schema = ctx.schema_for(self.phase)
        messages = self.compose(state, ctx, schema)
        # What :meth:`compose` put in front of the transcript is what this
        # phase cannot do without — the role prompt and the task — so that
        # is what the window pins. Counted rather than declared as a
        # constant so that a subclass which adds a message to the prefix
        # gets it pinned without having to know it had to say so.
        history = ctx.transcript()
        pinned = max(0, len(messages) - len(history))
        reply = ctx.ask(messages, pinned=pinned)
        ctx.remember(f"[{self.phase}] {reply}", speaker="assistant")
        if schema is None:
            return reply
        return self._parse(reply, schema)

    def compose(self, state: SessionState, ctx: RoleContext,
                schema: Optional[Type]) -> List[Dict[str, str]]:
        """The messages for this turn. Override to add phase context.

        The role prompt and the task first, then the transcript as one
        message per line. The transcript used to be folded into the task's
        own message, which made the prompt two messages long and therefore
        indivisible: when it did not fit there was nothing to drop, only
        something to cut in half. As separate turns the window can drop the
        oldest round trips whole and say so — and the model sees its own
        earlier replies as its own, which is what they were.
        """
        system = ctx.system_message or "You are an autonomous engineering agent."
        rules = self.instruction
        if schema is not None:
            keys = ", ".join([*schema.model_fields, *self.extra_keys])
            rules = f"{rules}\n\n{self.JSON_CONTRACT.format(keys=keys)}"
        history = ctx.transcript()
        user = f"Task: {state.task_description}"
        if history:
            user += "\n\nWhat has happened so far is in the turns below."
        return [
            {"role": "system", "content": f"{system}\n\nPhase {self.phase}.\n{rules}"},
            {"role": "user", "content": user},
            *history,
        ]

    def _parse(self, reply: str, schema: Type) -> Any:
        text = _FENCE.sub("", (reply or "").strip()).strip()
        if not text:
            raise RoleRefused(
                f"{self.phase} asked for a {schema.__name__} and the model "
                f"returned nothing"
            )
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise RoleRefused(
                f"{self.phase} asked for a {schema.__name__} as JSON and the "
                f"model returned something else ({exc.msg}). First 120 "
                f"characters: {text[:120]!r}"
            ) from exc
        return self.fill(data)

    def fill(self, data: Any) -> Any:
        """Last chance to supply fields the model has no way to know."""
        return data


class AuthoredToolPhaseRole(LLMPhaseRole):
    """The model authors a request; a tool settles it. The tool wins.

    A phase of this kind has an output the model alone cannot produce
    honestly. PATCH is the case that named the kind: the model writes
    search/replace blocks — that is authorship, and only a model can do
    it — but whether those blocks *matched real text and reached disk*
    is a fact about the filesystem. The old PATCH role stopped after the
    authoring half, and a ``PatchSet`` that had touched nothing
    validated exactly as well as one that had rewritten the repository.

    So :meth:`produce` is final here for the same reason
    :meth:`PhaseRole.run` is final one level up. ``run`` denies a role
    the right to declare its own success; ``produce`` denies it the
    right to *skip the settlement* and hand back the model's proposal as
    though it were an outcome. A subclass supplies :meth:`settle` and
    nothing else, and a subclass that supplies neither is refused at
    class creation rather than at the end of a green run.

    :attr:`settles_with` names the tool that does the settling. It is
    checked at class creation alongside ``phase`` and ``instruction``,
    and all three problems arrive in one message: a role of this kind
    with no tool would dispatch nothing, which is the defect wearing the
    new base class's name.
    """

    abstract = True

    #: ``(tool_name, action)`` the settlement dispatches through the bus.
    #: ``action`` may be None for single-action tools.
    settles_with: Tuple[str, Optional[str]] = ("", None)

    _REQUIRED = ("produce", "settle")
    _FINAL = ("run", "produce")

    @classmethod
    def _declaration_problems(cls) -> List[str]:
        problems = super()._declaration_problems()
        tool_name, _action = cls.settles_with
        if not tool_name:
            problems.append(
                "`settles_with` names no tool; a role of this kind exists "
                "precisely because the model's answer is a proposal that "
                "something else has to carry out, and one that dispatches "
                "nothing is an LLMPhaseRole with a misleading base class"
            )
        return problems

    def produce(self, state: SessionState, ctx: RoleContext) -> Any:
        authored = super().produce(state, ctx)
        return self.settle(state, ctx, authored)

    @_stub
    def settle(self, state: SessionState, ctx: RoleContext,
               authored: Any) -> Any:
        """Carry out what the model asked for; return the real outcome.

        Raise :class:`RoleRefused` when the tool says it did not happen.
        Returning the authored proposal anyway is the defect.
        """
        raise NotImplementedError

    def call(self, ctx: RoleContext, *, remember: bool = True, **kwargs):
        """Dispatch :attr:`settles_with` through the bus.

        ``remember=False`` for a settlement that dispatches many times
        and writes its own summary: twelve symbol bodies in the trace
        push everything a later phase needs out of ``ctx.recent()``,
        which is a context budget spent on transcript rather than on
        the work.
        """
        if not remember:
            name, action = self.settles_with
            return (ctx.dispatch(name, action=action, **kwargs) if action
                    else ctx.dispatch(name, **kwargs))
        return _dispatch_and_remember(ctx, self.phase, self.settles_with,
                                      **kwargs)


class IntakeRole(LLMPhaseRole):
    phase = "INTAKE"
    instruction = (
        "Restate the task as a contract: what is being asked, the "
        "constraints it must respect, and how anyone would know it was "
        "done. Do not plan and do not write code."
    )

    def fill(self, data):
        data.setdefault("task_id", "intake")
        data.setdefault("description", "")
        return data


class ContractRole(IntakeRole):
    phase = "CONTRACT"
    instruction = (
        "Tighten the contract: make every acceptance criterion something "
        "that can be checked by running something, not by reading it."
    )


class PlanRole(LLMPhaseRole):
    phase = "PLAN"
    instruction = (
        "Produce an ordered plan of small steps. Each step names one "
        "target file and one action (create, modify, delete, test). "
        "Do not write the code yet."
    )

    def fill(self, data):
        data.setdefault("task_id", "plan")
        data.setdefault("steps", [])
        return data


class RetrieveRole(AuthoredToolPhaseRole):
    """Ask for symbols by name, then fetch their spans through the bus.

    The model names what it needs; ``repo_map symbol`` fetches it. That
    ordering is the context discipline ROADMAP Phase 8 asks for: a phase
    that wanted ``Orchestrator.run`` gets 60 lines with a
    ``path:start-end`` citation, not 363 lines of the file it lives in
    and not the one-line signature the excerpt carries.

    A symbol the map cannot resolve comes back as its refusal — "that
    name is ambiguous, here are the candidates" — and is put in the pack
    as such. Dropping it silently would leave the next phase believing
    it had been given something it was not.
    """

    phase = "RETRIEVE"
    instruction = (
        "Name the symbols the plan needs to read, as a JSON list of "
        "strings under `symbols` — bare names, or Class.method. Their "
        "source will be fetched for you and put in `repo_map_excerpt`. "
        "Ask for nothing you will not read."
    )

    extra_keys = ("symbols",)
    settles_with = ("repo_map", "symbol")

    #: Enough to work from, few enough to stay inside the context budget.
    MAX_SYMBOLS = 12

    def settle(self, state: SessionState, ctx: RoleContext, authored: Any):
        pack = authored
        wanted = self._requested(pack)
        if not wanted or ctx.tool_bus is None:
            # Asking for no symbols is a legitimate answer here — unlike
            # PATCH, where an empty proposal is the phase declining to do
            # the only thing it exists for.
            return pack

        fetched = []
        for name in wanted[:self.MAX_SYMBOLS]:
            result = self.call(ctx, remember=False, name=name)
            fetched.append(
                result.stdout if result.exit_code == 0
                else f"# {name}: not retrieved — {result.stderr}"
            )
        joined = "\n\n".join(fetched)
        ctx.remember(f"[RETRIEVE] fetched {len(fetched)} symbol(s)")

        existing = pack.get("repo_map_excerpt") or "" if isinstance(pack, dict) \
            else getattr(pack, "repo_map_excerpt", "")
        merged = "\n\n".join(part for part in (existing, joined) if part)
        if isinstance(pack, dict):
            pack["repo_map_excerpt"] = merged
        return pack

    def _requested(self, pack) -> List[str]:
        raw = pack.get("symbols") if isinstance(pack, dict) else None
        if not isinstance(raw, list):
            return []
        return [str(s).strip() for s in raw if str(s).strip()]

    def fill(self, data):
        data.setdefault("task_id", "retrieve")
        return data


class PatchRole(AuthoredToolPhaseRole):
    """Write the patches, then put them on disk. Both halves, or neither.

    **Why the application lives inside PATCH and not in a phase of its
    own.** Three things pin it here.

    The first is the capability scopes. ``fs.write`` and ``git.write``
    are granted to PATCH and to no other phase of the coding workflow —
    CRITIQUE and RUN are read-only by declaration. Writing anywhere else
    would mean widening a phase that is deliberately narrow, and the
    orchestrator has already narrowed the engine by the time
    :meth:`settle` runs, so the write is checked against exactly the
    scopes the workflow says this phase may use.

    The second is recovery. The orchestrator checkpoints
    ``pre_PATCH_NNN`` immediately before entering PATCH and rolls back
    to it when RUN fails. Application inside PATCH sits inside that
    bracket already. A separate APPLY phase would sit *outside* it and
    would need a checkpoint of its own — a second recovery path, which
    is the thing not to build.

    The third is that a phase boundary between authoring and landing is
    a place the run can stop with the first half done and the second
    never attempted, reporting success for the half that ran. That is
    the defect this class was rewritten to remove, relocated by one
    phase rather than fixed.

    **Why not a plain :class:`ToolPhaseRole` over the patch tool.**
    Because the patches themselves are the model's work. A ToolPhaseRole
    does not ask the model at all, and something has to write the
    search/replace blocks. The phase needs both halves, which is what
    :class:`AuthoredToolPhaseRole` is.

    **Why the patch lands in the tree and not in a worktree.**
    ``PatchEngine.apply`` defaults to ``use_worktree=True``, which
    creates a branch, writes there, and leaves the repository untouched
    until an explicit merge. RUN dispatches ``verify test`` against the
    repository. A worktree would therefore reproduce the original bug
    one level down: the change would be real, on disk, and in a
    directory the tests never look at, and RUN would go green against
    the unchanged tree exactly as it did before. It is also a second
    recovery path — create/merge/discard — beside the checkpoint the
    orchestrator already keeps. So the change lands where the tests run,
    and rollback stays the orchestrator's.

    A consequence worth stating rather than discovering: the
    orchestrator's rollback restores the *artifacts* directory, not the
    working tree, so a failed RUN leaves the applied change on disk for
    FIX to patch further. That is what the FIX → PATCH loop needs —
    FIX's ``search_block`` has to match the file as it is now — and the
    tree's own recovery is the user's git checkout.
    """

    phase = "PATCH"
    instruction = (
        "Write the change as search/replace patches. `search_block` must "
        "be text that exists in the file exactly as written, including "
        "indentation. Change one thing per patch."
    )
    settles_with = ("patch", "apply")

    def fill(self, data):
        data.setdefault("task_id", "patch")
        data.setdefault("patches", [])
        return data

    def settle(self, state: SessionState, ctx: RoleContext, authored: Any):
        from core.contracts.schemas import PatchSet

        try:
            patch_set = (authored if isinstance(authored, PatchSet)
                         else PatchSet.model_validate(authored))
        except Exception as exc:  # noqa: BLE001 — pydantic's own error text
            raise RoleRefused(
                f"{self.phase} produced something that is not a PatchSet, so "
                f"there was nothing to apply: {exc}"
            ) from exc

        if not patch_set.patches:
            raise RoleRefused(
                f"{self.phase} produced a PatchSet with no patches. An empty "
                f"change validates against the schema and alters nothing, "
                f"which is the one outcome this phase must not report as "
                f"success"
            )

        result = self.call(
            ctx,
            patch_set_json=patch_set.model_dump_json(),
            # See the class docstring: the tests run in the repository,
            # so the change has to land in the repository.
            use_worktree=False,
        )
        if result.exit_code != 0:
            raise RoleRefused(
                f"the patch did not apply: "
                f"{self._why(result) or 'no detail'}"
            )

        state.artifacts["_diff"] = self._diff_of(result)
        return patch_set

    @staticmethod
    def _why(result) -> str:
        """The per-file reason the apply failed, not just its exit code.

        FIX is told "the tests failed, read the failure above" and the
        failure it needs to read is *which search block did not match*.
        The engine reports that per file; handing on a bare exit code
        would make the next attempt a guess.
        """
        detail = result.stderr.strip()
        try:
            data = json.loads(result.stdout or "{}")
        except json.JSONDecodeError:
            return detail or (result.stdout or "").strip()
        reasons = [
            f"{f.get('file_path')}: {f.get('error')}"
            for f in data.get("file_results", [])
            if not f.get("success") and f.get("error")
        ]
        return "; ".join(reasons) or detail or (result.stdout or "").strip()

    @staticmethod
    def _diff_of(result) -> str:
        """The diff of what the engine actually wrote.

        Parked on ``state.artifacts`` under ``_diff`` because CRITIQUE
        reads it there — and until now nothing wrote it, so
        ``LLMReviewTier`` was handed ``""`` on every live run and
        returned UNKNOWN forever. ``CompositeJudge`` takes an UNKNOWN
        tier's weight out of the denominator, which is right when a
        reviewer is genuinely unavailable and is exactly what made this
        absence invisible: the composite score was the same number it
        would have been if the reviewer had read the diff and approved.
        """
        try:
            data = json.loads(result.stdout or "{}")
        except json.JSONDecodeError:
            return ""
        return str(data.get("diff") or "")


class FixRole(LLMPhaseRole):
    """Diagnose the failure. PATCH lands the change; FIX does not.

    FIX subclassed :class:`PatchRole`, and once PatchRole started
    applying, FIX would have applied too — but the workflow's branch
    rule sends FIX straight to PATCH, which asks for the change again
    and applies it again. The first application replaces the very text
    the second one searches for, so the second fails against a file that
    is already correct, and the run halts on a patch that worked.

    So this phase reads the failure and says what it means. Its reply
    goes into the trace, and the PATCH turn that follows is composed with
    ``ctx.transcript()`` — the diagnosis is how the next attempt knows
    what went wrong, and it is the newest turn in that transcript, which
    is the one the window will never drop. One phase writes to disk, and
    it is the one the checkpoint brackets.
    """

    phase = "FIX"
    instruction = (
        "The tests failed. Read the failure above and say what it means: "
        "which assertion or error, in which file, and what about the last "
        "change caused it. Name the fix in one or two sentences. The next "
        "phase writes it — do not write the patch here, and do not "
        "re-submit the previous one."
    )


# ---------------------------------------------------------------------------
# Roles that run a tool
# ---------------------------------------------------------------------------

class ToolPhaseRole(PhaseRole):
    """Dispatches a tool through the bus and builds the artifact from it.

    The model is not asked. A repository map and a test exit code are
    facts, and a phase that asked a language model for either would be
    manufacturing them.
    """

    abstract = True

    #: ``(tool_name, action)``. ``action`` may be None for single-action tools.
    tool: Tuple[str, Optional[str]] = ("", None)

    def call(self, ctx: RoleContext, **kwargs):
        return _dispatch_and_remember(ctx, self.phase, self.tool, **kwargs)


class RepoMapRole(ToolPhaseRole):
    phase = "REPO_MAP"
    instruction = "Build the repository map from the repository, not from memory."
    tool = ("repo_map", "excerpt")

    def produce(self, state: SessionState, ctx: RoleContext):
        result = self.call(ctx)
        if result.exit_code != 0:
            raise RoleRefused(
                f"the repo map could not be built: "
                f"{result.stderr or result.stdout or 'no detail'}"
            )
        from core.context.models import RepoMapResult

        try:
            return RepoMapResult.model_validate_json(result.stdout)
        except Exception:
            # The tool returned something that is not a serialised
            # RepoMapResult. Keep the text — it is the map a human would
            # read — and do not invent the counts.
            return RepoMapResult(excerpt=result.stdout)


class RunRole(ToolPhaseRole):
    phase = "RUN"
    instruction = "Run the test suite and report exactly what it returned."
    tool = ("verify", "test")

    def produce(self, state: SessionState, ctx: RoleContext):
        from core.contracts.schemas import RunReport

        result = self.call(ctx)
        return RunReport(
            exit_code=result.exit_code,
            stdout=result.stdout[:8000],
            stderr=result.stderr[:8000],
            passed=result.exit_code == 0,
        )


class CritiqueRole(ToolPhaseRole):
    """Score the change: tests and lint from tools, review from the model.

    The default judge is built from the role context and not in
    ``__init__``, because the tier that reviews the diff needs a way to
    ask the model and ``__init__`` has none. A bare ``CompositeJudge()``
    gives ``LLMReviewTier`` no ``chat_fn``, so it returned UNKNOWN on
    every run for a second, independent reason beyond the missing diff —
    and a judge whose review tier can never speak is a two-tier judge
    that reports itself as three.
    """

    phase = "CRITIQUE"
    instruction = "Score the change with the composite judge, not by opinion."
    tool = ("verify", "lint")

    def __init__(self, judge=None):
        self._judge = judge

    def produce(self, state: SessionState, ctx: RoleContext):
        judge = self._judge or self._default_judge(ctx)
        lint = self.call(ctx)
        run_report = state.artifacts.get("_run_report")
        test_rc = getattr(run_report, "exit_code", 0) if run_report else 0
        return judge.evaluate(
            test_exit_code=test_rc,
            test_stdout=getattr(run_report, "stdout", "") if run_report else "",
            lint_exit_code=lint.exit_code,
            lint_stdout=lint.stdout,
            diff=state.artifacts.get("_diff", ""),
        )

    @staticmethod
    def _default_judge(ctx: RoleContext):
        from core.judge import CompositeJudge, LintTier, LLMReviewTier, TestTier

        # ctx.ask and not ctx.chat: the reviewer is a role's turn at the
        # model like any other and is capped by the same per-role context
        # budget, so a large diff cannot quietly spend the whole window.
        return CompositeJudge([
            TestTier(), LintTier(), LLMReviewTier(chat_fn=ctx.ask),
        ])


class FinalizeRole(PhaseRole):
    phase = "FINALIZE"
    instruction = "Report what happened. Count what is on disk, do not summarise from memory."

    def produce(self, state: SessionState, ctx: RoleContext):
        from core.contracts.schemas import FinalReport

        produced = [k for k in state.artifacts if not k.startswith("_")]
        return FinalReport(
            task_description=state.task_description,
            outcome="completed",
            artifacts_produced=produced,
            total_iterations=state.total_iterations,
        )


# ---------------------------------------------------------------------------
# The dispatcher
# ---------------------------------------------------------------------------

def default_roles() -> List[PhaseRole]:
    """The coding workflow's ten. A phase with no role here is refused by
    name rather than quietly succeeding — which is the whole point."""
    return [
        IntakeRole(), ContractRole(), RepoMapRole(), PlanRole(),
        RetrieveRole(), PatchRole(), CritiqueRole(), RunRole(),
        FixRole(), FinalizeRole(),
    ]


class LLMRoleDispatcher:
    """Routes a phase to its role. Refuses phases it has no role for.

    Replaces ``StubDispatcher``. The refusal matters as much as the
    execution: an unmapped phase now fails the phase, burns a retry and
    halts the session with the phase named, instead of returning success
    and letting the state machine walk to COMPLETED having done nothing.
    """

    def __init__(
        self,
        chat_fn: Callable[[List[Dict[str, str]]], Any],
        tool_bus=None,
        workflow=None,
        budget: Optional[BudgetConfig] = None,
        system_message: str = "",
        roles: Optional[List[PhaseRole]] = None,
        window: Optional[MissionWindow] = None,
    ):
        """*window* is the model's real context window, built by the caller
        from the provider, model and client it is about to use — the same
        object the CLI's mission path builds. ``None`` leaves the per-role
        budget as the only limit and probes nothing, which is what a caller
        with a stubbed client wants and what every caller got before there
        was a window to pass.
        """
        if workflow is None:
            from core.kernel.workflows import get_coding_workflow
            workflow = get_coding_workflow()
        self._ctx = RoleContext(
            chat=chat_fn,
            tool_bus=tool_bus,
            workflow=workflow,
            budget=budget or BudgetConfig(),
            system_message=system_message,
            window=window,
        )
        self._roles: Dict[str, PhaseRole] = {
            role.phase: role for role in (roles if roles is not None
                                          else default_roles())
        }

    @property
    def context(self) -> RoleContext:
        return self._ctx

    @property
    def phases(self) -> List[str]:
        return sorted(self._roles)

    def dispatch(self, phase: str, state: SessionState) -> PhaseResult:
        name = getattr(phase, "name", phase)
        role = self._roles.get(name)
        if role is None:
            return PhaseResult(
                success=False,
                error=(
                    f"no role is registered for phase {name!r}; this "
                    f"dispatcher serves {', '.join(self.phases)}"
                ),
            )
        result = role.run(state, self._ctx)
        # Carried out on the result rather than left on the context: the
        # orchestrator is the half of this that has a session manager, and
        # a compaction nobody wrote down is the silent truncation the
        # window exists to replace.
        result.compactions = self._ctx.drain_compactions()

        # RUN's report is what CRITIQUE scores and what the orchestrator's
        # rollback keys on, so it is kept where the next phase can find it.
        if name == "RUN" and result.output is not None:
            state.artifacts["_run_report"] = result.output
            result.success = bool(getattr(result.output, "passed", False))
        return result
