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

from core.kernel.budgets import BudgetConfig
from core.kernel.orchestrator import PhaseResult
from core.kernel.state import SessionState

_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.MULTILINE)


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
    #: Everything the roles said and were told, in order. The transcript is
    #: the session's working memory; artifacts are its output.
    trace: List[str] = field(default_factory=list)

    def schema_for(self, phase: str) -> Optional[Type]:
        if self.workflow is None:
            return None
        return self.workflow.phase_schemas.get(phase)

    def ask(self, messages: List[Dict[str, str]]) -> str:
        """One turn at the model, capped by the per-role context budget.

        The cap is characters against ``max_context_tokens_per_role``
        times four. A rough conversion on purpose: the exact tokeniser
        belongs to whichever backend is loaded, and this is a guardrail
        against a role pasting a whole repository into a prompt, not an
        accounting system. ``ContextWindowManager`` does the real thing
        on the chat path.
        """
        cap = self.budget.max_context_tokens_per_role * 4
        trimmed = []
        for message in messages:
            content = message.get("content") or ""
            if len(content) > cap:
                content = (
                    content[:cap]
                    + f"\n[...truncated at the {cap}-character per-role budget]"
                )
            trimmed.append({**message, "content": content})
        return str(self.chat(trimmed) or "")

    def dispatch(self, tool: str, *args: Any, **kwargs: Any):
        """Run a tool through the bus. The only way out of a role."""
        if self.tool_bus is None:
            raise RoleRefused(
                f"this phase needs the {tool!r} tool and no ToolBus was "
                f"given to the dispatcher"
            )
        return self.tool_bus.dispatch(tool, *args, **kwargs)

    def remember(self, line: str) -> None:
        cap = self.budget.max_tool_output_bytes_in_context
        if len(line) > cap:
            line = line[:cap] + f"\n[...truncated at {cap} bytes]"
        self.trace.append(line)

    def recent(self, n: int = 6) -> str:
        return "\n\n".join(self.trace[-n:])


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
        reply = ctx.ask(self.compose(state, ctx, schema))
        ctx.remember(f"[{self.phase}] {reply}")
        if schema is None:
            return reply
        return self._parse(reply, schema)

    def compose(self, state: SessionState, ctx: RoleContext,
                schema: Optional[Type]) -> List[Dict[str, str]]:
        """The messages for this turn. Override to add phase context."""
        system = ctx.system_message or "You are an autonomous engineering agent."
        rules = self.instruction
        if schema is not None:
            keys = ", ".join([*schema.model_fields, *self.extra_keys])
            rules = f"{rules}\n\n{self.JSON_CONTRACT.format(keys=keys)}"
        user = f"Task: {state.task_description}"
        recent = ctx.recent()
        if recent:
            user += f"\n\nWhat has happened so far:\n{recent}"
        return [
            {"role": "system", "content": f"{system}\n\nPhase {self.phase}.\n{rules}"},
            {"role": "user", "content": user},
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
    goes into the trace, and the PATCH turn that follows is composed
    with ``ctx.recent()`` — the diagnosis is how the next attempt knows
    what went wrong. One phase writes to disk, and it is the one the
    checkpoint brackets.
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
    ):
        if workflow is None:
            from core.kernel.workflows import get_coding_workflow
            workflow = get_coding_workflow()
        self._ctx = RoleContext(
            chat=chat_fn,
            tool_bus=tool_bus,
            workflow=workflow,
            budget=budget or BudgetConfig(),
            system_message=system_message,
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

        # RUN's report is what CRITIQUE scores and what the orchestrator's
        # rollback keys on, so it is kept where the next phase can find it.
        if name == "RUN" and result.output is not None:
            state.artifacts["_run_report"] = result.output
            result.success = bool(getattr(result.output, "passed", False))
        return result
