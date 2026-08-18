# core/runtime/run.py — the loop, and the six things it is made of

"""One loop object, whose constructor is data.

:class:`~core.runtime.mission.MissionRunner` grew thirty parameters, and a
thirty-parameter constructor is not a wide seam — it is a missing one.  The
parameters are not thirty independent facts: they are six cohesive ones,
each with a class of decision behind it, and the day the staged path wanted
the same behaviour it copied ten of the thirty and hand-listed six of
``grounding``'s ten fields.  That is what a constructor with no shape costs,
and it is the whole argument for this module.

So :class:`Run` takes **six objects and nothing else**, and each one is the
one owner of a class of fact:

* :class:`Personality` — what the model is told and what it is held to: the
  system message, the seeded turns, the grounding validator, the critic;
* :class:`ToolPlane` — the only way out, and who may say yes to it: the
  bus, the closed set, the gated names, the store tool;
* :class:`Bounds` — everything that can stop a run: the wall clock, the
  cancellation, the control channel, an operator's step ceiling, and the
  supervisor that watches for a run going nowhere;
* :class:`Store` — what survives the process: the durable run log, the
  recorder, the approval store, a decision somebody already made;
* :class:`Observer` — every record out, and therefore the one place
  redaction happens and the one place the durable log is written;
* :class:`Model` — the client, the protocol and the side channels: what to
  ask, how to read the reply, what the call cost.

Six, and not five or eight, because six is how many owners there are.
``audit_ref``, ``sandbox`` and ``profile`` are **properties** of
:class:`ToolPlane` and not fields of anything: :mod:`core.runtime.mission`
already argues at length that a second resolver of "where the audit log is"
is worse than none, and this module reads all three through the functions
that argument produced.  Six objects is the count; six *owners* is the
point.

**Nothing here is new behaviour.**  The loop below is
:class:`MissionRunner`'s loop, moved: the same records in the same order
with the same bytes, down to the whitespace of a system turn, which a
served endpoint's prefix cache is keyed on.  ``MissionRunner`` is now the
**adapter** — its thirty parameters build these six objects and every
behaviour is delegated here — so a caller that has one keeps it, its
conformance suite (``tests/test_mission.py``) keeps testing the loop
through it, and ``tests/test_run_corpus.py`` replays four recorded runs
through this code and compares them to the recording record for record.

**The loop is a coroutine, and the method a caller already had is a
wrapper round it.**  :meth:`Run.arun` *is* the loop; :meth:`Run.run` runs
that coroutine to completion and does nothing else, which is what
``judais``, ``MissionRunner`` and the staged path call and why none of
them had to change.  Every ``await`` in it is at a point the loop already
chose to stop at — before and after a model call, around a dispatch, at a
gate's wait, between the frames of a streamed answer — so the *order* of
what a mission does is the order it always did, and the records are the
same records: the guard for that claim is ``tests/test_run_corpus.py``,
which replays four recorded runs through this code and compares them
field for field, and reports no drift in the prompts either.

What being a coroutine buys is that the waiting stops being a blocked
thread.  A model call goes out through :func:`asyncio.to_thread`, so a
59 tok/s endpoint no longer holds the loop while it writes; a dispatch
does too; a gate awaits the control channel instead of sleeping on it.
None of that is visible on the wire, and all of it is what makes
``asyncio.gather`` over :meth:`Run.child` possible — which is the
capability this was done for, and which is the parallel-children lane's
to spend (``ROADMAP.md`` §2.6.2).

The import runs one way at module level: this module reads the vocabulary —
the transcript shapes, the protocol text, the record builders, the bus
readers — out of :mod:`core.runtime.mission`, and that module reaches for
:class:`Run` inside ``MissionRunner.__init__``, which is a runtime import
for exactly that reason and the only place the arrow points back.

:class:`Run` is not :class:`core.durable.Run`, which is a row in a run
store.  The two do not meet: nothing here imports that one, and
:class:`Store` holds the :class:`~core.durable.RunStore` it comes out of.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from typing import (
    Any, Callable, Dict, FrozenSet, List, Mapping, Optional, Sequence, Tuple,
)

from core.bounding import MAX_RESULT_BYTES, bound_result
from core.budgets import BudgetExhausted, Deadline, cancelled
from core.durable import RunStore
from core.redact import scrub_record
from core.runtime.answer_stream import adrain as adrain_answer
from core.runtime.approvals import ApprovalStore, ApprovalTicket
from core.runtime.context_window import (
    Compaction, MissionWindow, default_compaction_note,
)
from core.runtime.contract import SCHEMA_VERSION
from core.runtime.control import (
    CANCEL_STEP, GATE_DECISION, GATE_WAIT_S, INJECT,
)
from core.runtime.grounding import GroundingReport, GroundingValidator
from core.runtime.mission import (
    ANSWER_FUNCTION, ANSWER_TOOL, AWAITING_APPROVAL, CANCEL_STEP_LATE,
    CANCEL_STEP_NOTE, CANCELLED, JSON_PROTOCOL, NATIVE_PROTOCOL,
    NATIVE_PROTOCOL_TEXT, PLANE_CHANGED, PROTOCOL, PROTOCOLS, MissionCall,
    MissionStep, MissionTranscript, _FENCE, _finished_record,
    _grounding_record, _profile_field, _protocol_field, _record_decision,
    _run_field, _takes_deadline, _takes_step, audit_ref_of, persist_record,
    sandbox_of, second_opinion, stacked, validate_history,
)
from core.runtime.mission_stream import (
    ANSWER, ANSWER_DELTA, GATE_REQUESTED, GROUNDING, MISSION_FINISHED,
    MISSION_STARTED, REPLY_REJECTED, STEP_STARTED, TOOL_CALL, TOOL_RESULT,
)
from core.runtime.mission_stream import Observer as Sink
from core.runtime.results import (
    BRANCH_ARGUMENT, RESULT_TOOL, BranchedStores, MissionResultStore,
)
from core.runtime.schema_check import check as check_arguments
from core.runtime.supervisor import (
    NUDGE, NUDGE_NOTE, STUCK, WIND_UP,
)
from core.runtime.usage import Ledger, Rate
from core.tools.descriptors import same_tool, summarize_input_schema

__all__ = ["Bounds", "Model", "Observer", "Personality", "Run", "Store",
           "ToolPlane"]


# ── what the model is told, and what it is held to ──────────────────────────


@dataclass(frozen=True)
class Personality:
    """The voice a run speaks in and the grammar it is checked against.

    Frozen, because none of it changes inside a run: a mission that
    re-wrote its own persona mid-loop would move the bytes under a served
    endpoint's prefix cache on a step nobody could point at.  What *does*
    change under a run is the catalogue, and that is :class:`ToolPlane`'s.

    ``history`` is validated **here**, at construction, by
    :func:`~core.runtime.mission.validate_history` — the one answer to "is
    this a conversation history this loop will seed", shared with the CLI —
    and what is kept is the cleaned list that function returns.  A refusal
    is loud for the reason it is loud there: a malformed history silently
    dropped reproduces the exact failure the feature exists to fix.
    """

    #: Persona and skill prompt, already joined by the caller.
    system_message: str = ""
    #: Prior turns, oldest first, seeded between the system turn and the
    #: objective.  ``()`` is a mission that starts cold.
    history: Sequence[Mapping[str, str]] = ()
    #: A :class:`~core.runtime.grounding.GroundingValidator`, or ``None``
    #: for a mission nobody configured a grammar for.
    grounding: Optional[GroundingValidator] = None
    #: A :class:`~core.critic.mission.MissionCritic`, or ``None``.
    #: Duck-typed rather than imported: a mission not using a critic must
    #: not pay for pydantic and a transport.
    critic: Any = None
    #: What the platform is called to ``import``, for the one planner rung
    #: that writes code against an SDK.  ``""`` withholds that rung.  The
    #: staged path is its only reader; it is here because it is a fact
    #: about what the model is told, which is what this object owns.
    sdk_import: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "history", validate_history(self.history))


# ── the only way out, and who may say yes to it ─────────────────────────────


@dataclass(frozen=True)
class ToolPlane:
    """The bus, the closed set, and the three facts read off the bus.

    Frozen, and :attr:`offered` is nonetheless a **live list**: what is
    offered changes under a running mission — a server registers a tool and
    notifies, the bridge picks it up — and :meth:`Run._relearn_the_plane`
    edits that list in place.  The membership moves; the object does not,
    which is what lets a child run share one plane with its parent.

    ``sandbox``, ``audit_ref`` and ``profile`` are **properties and never
    fields**.  Each is read off the bus through the function in
    :mod:`core.runtime.mission` that is already its one owner, and that
    module says at length why: a second resolver of "where the audit log
    is" is worse than none, because the day the two disagree the stream
    names a file nothing wrote to and a consumer believes it.
    """

    #: A :class:`~core.tools.bus.ToolBus`.  The only way out of here.
    bus: Any
    #: The mission's closed set — which registered tools this run may name.
    #: A subset, not the whole bus.  Live: see the class docstring.
    offered: Sequence[str] = ()
    #: Name to register the per-mission result store under, or ``""`` to
    #: run without one.
    store_tool: str = RESULT_TOOL
    #: Tool names that are offered and not dispatched.
    gated: FrozenSet[str] = frozenset()
    #: The function declarations a native request carries, when the caller
    #: builds them.  Written by the caller that owns the request; this loop
    #: never sends one.  Empty on every JSON-protocol run.
    schemas: Sequence[Mapping[str, Any]] = ()
    #: ``admits(grew, offered) -> names that may join``.  The runner asks;
    #: it never decides.  ``None`` admits whatever the bus grew.
    admits: Optional[Callable[[Sequence[str], Sequence[str]],
                              Sequence[str]]] = None
    #: Told when :attr:`offered` changes, with the new whole list.
    plane_changed: Optional[Callable[[List[str]], None]] = None
    #: Which child of the mission this plane is leased to, or ``""`` for the
    #: mission itself.  Set by :meth:`lease` and by nothing else; it is the
    #: key this plane's run publishes its result store under and the word
    #: that rides the store dispatch.  It is **not** ``Observer.name``: that
    #: names the records, this names the store, and they are the same string
    #: because they are the same child — :meth:`Run.child` sets both from
    #: one argument.
    store_branch: str = ""
    #: The stores of every child leasing this plane, behind one registered
    #: tool.  Shared by identity with every lease, which is the whole of how
    #: two children avoid colliding on ``mission_result``; created here when
    #: a caller does not hand one in, so an ordinary plane is an ordinary
    #: plane and :func:`~dataclasses.replace` — the ticket's widening,
    #: :meth:`narrow`, :meth:`lease` — carries the same one through.
    stores: Any = None

    def __post_init__(self) -> None:
        # A list of this object's own: a caller's sequence is data it still
        # holds, and the plane edits its membership in place.
        object.__setattr__(self, "offered",
                           [str(name) for name in self.offered])
        object.__setattr__(self, "store_tool",
                           (self.store_tool or "").strip())
        object.__setattr__(self, "gated",
                           frozenset(str(name) for name in self.gated if name))
        object.__setattr__(self, "store_branch",
                           str(self.store_branch or "").strip())
        if self.stores is None:
            object.__setattr__(self, "stores", BranchedStores())

    # ── the three facts that are read off the bus and never stored ──────

    @property
    def sandbox(self) -> str:
        """``"bwrap"`` or ``"none"`` — through
        :func:`~core.runtime.mission.sandbox_of`, which is its one owner."""
        return sandbox_of(self.bus)

    @property
    def audit_ref(self) -> Optional[str]:
        """The audit file this plane's dispatches are written to, or
        ``None`` — through :func:`~core.runtime.mission.audit_ref_of`."""
        return audit_ref_of(self.bus)

    @property
    def profile_field(self) -> Dict[str, Any]:
        """``{"profile": name}`` or ``{}`` — the opening frame's OPTIONAL
        field, in the shape the record wants it, through
        :func:`~core.runtime.mission._profile_field`.

        The dict and not the name, because *when the field is present* is
        the same decision as *what it says* and one owner holds both.
        """
        return _profile_field(self.bus)

    @property
    def profile(self) -> Optional[str]:
        """The capability profile governing this plane, or ``None``.

        The same fact :attr:`profile_field` states, for a reader that wants
        the word rather than the field — off the same owner, so the two can
        never disagree about whether there is one.
        """
        return self.profile_field.get("profile")

    def registered(self) -> Optional[List[str]]:
        """What the bus has registered, or ``None`` when it cannot say.

        ``getattr`` for the reason :func:`~core.runtime.mission.audit_ref_of`
        uses one: a caller may hand a run any object with ``dispatch`` and
        ``describe_tool``, and a fake bus in somebody's test suite is not
        obliged to know how to list itself.  A bus that cannot answer is a
        run whose offered set never changes, which is what every run did
        before this existed.
        """
        lister = getattr(self.bus, "list_tools", None)
        if lister is None:
            return None
        try:
            return [str(name) for name in lister()]
        except Exception:                       # pragma: no cover - defensive
            return None

    def takes_deadline(self) -> bool:
        """Whether this bus's ``dispatch`` accepts a ``deadline_s`` ceiling.

        Through :func:`~core.runtime.mission._takes_deadline`, which asks
        the signature and explains why a mission may not simply pass a
        timeout down.  Asked once per run and not per dispatch.
        """
        return _takes_deadline(self.bus)

    def takes_step(self) -> bool:
        """Whether this bus's ``dispatch`` accepts the audit's ``step``.

        Through :func:`~core.runtime.mission._takes_step`, the same probe
        of the same signature, and asked once per run for the same reason.
        """
        return _takes_step(self.bus)

    def lease(self, branch: str = "") -> "ToolPlane":
        """A plane for one child run, whose result store does not collide.

        The same plane in every respect a mission can see — the same bus,
        the same live :attr:`offered` list, the same gated set, the same
        schemas, the same ``admits`` and the same ``plane_changed``, all by
        identity — with one thing changed: :attr:`store_branch`, which is
        the key this child's :class:`~core.runtime.results.MissionResultStore`
        is published under in the :attr:`stores` registry the lease shares
        with its parent.

        **The model is told the same tool name on every branch**, and that
        is the decision this method is.  Two children on one bus used to
        collide outright:
        :meth:`~core.runtime.results.MissionResultStore.register_on` refuses
        a name that is taken, which is what stopped a staged turn from
        running two steps at once.  The other way out was a namespaced tool
        per child — ``mission_result@s1`` — and it is wrong twice over.  The
        name is in the protocol text the child is given, so two children
        would open with two different prompts for one job, and a served
        endpoint's prefix cache is keyed on those bytes; and a sibling's
        descriptor sitting on the bus is a name
        :meth:`Run._relearn_the_plane` reads as a tool the bus *grew* —
        with no ``admits`` to say otherwise, one child would be offered the
        other child's store.

        So there is one descriptor and it routes: see
        :class:`~core.runtime.results.BranchedStores`.  What a child adds to
        its own store dispatch is the branch it is, which the loop puts on
        the call after the schema check and only for the mission's own tool.

        A lease of a plane with no store tool is a plane with no store tool;
        the branch is still recorded, because it costs nothing and a caller
        that later gives the plane a store gets the right one.
        """
        leased = replace(self, store_branch=str(branch or ""))
        # The offered list back by IDENTITY. `__post_init__` gives every
        # plane a list of its own — right for a caller's sequence, and right
        # for `narrow`, which is a different plane — and wrong here: what is
        # offered changes under a running turn, `_relearn_the_plane` edits
        # the membership in place, and a lease with a copy would be a child
        # that never hears about a tool the bus grew. One plane, one answer
        # to "what may be called now", is the whole reason a child shares it.
        object.__setattr__(leased, "offered", self.offered)
        return leased

    # ── the result store, opened per branch and registered once ─────────

    def open_store(self, results: Any) -> str:
        """Publish *results* as this branch's, registering the tool once.

        Returns the registered name, or ``""`` when this plane runs without
        a store — the flag :meth:`Run.arun` already held, unchanged.
        """
        if not self.store_tool:
            return ""
        return self.stores.open(self.bus, self.store_tool,
                                self.store_branch, results)

    def close_store(self) -> None:
        """Drop this branch's store; withdraw the tool with the last one."""
        if self.store_tool:
            self.stores.close(self.bus, self.store_branch)

    def store_routing(self, name: str) -> Dict[str, Any]:
        """``{"branch": …}`` when *name* is this plane's store tool, else ``{}``.

        The dict and not the word, in the shape the dispatch wants it, for
        the reason :attr:`profile_field` is a dict: *whether* the keyword
        rides is the same decision as *what it says*, and one owner holds
        both.  Empty for an unbranched run, so a mission with no children
        dispatches exactly the call it always dispatched.
        """
        if not (self.store_branch and name and name == self.store_tool):
            return {}
        return {BRANCH_ARGUMENT: self.store_branch}

    def narrow(self, scopes: Sequence[str]) -> "ToolPlane":
        """This plane restricted to *scopes*, for a role that may do less.

        This is what ``CapabilityEngine.set_scope_constraints`` becomes now
        that governance has **one** surface instead of two.  The mission
        path narrows a plane already — a closed set plus per-tool profiles
        decides which registered tools a run may name — and the kernel path
        narrowed a *scope* allowlist on the bus's capability engine through
        a second method that only the orchestrator ever called.  Both are a
        plane admitting less than its bus can do, and after this both are
        one object's :meth:`narrow`.

        The constraint is applied to the bus's own
        :class:`~core.tools.capability.CapabilityEngine`, read off the bus
        through ``getattr`` exactly as
        :func:`~core.runtime.mission.audit_ref_of` reads the audit
        reference: a caller may hand a run any object with ``dispatch`` and
        ``describe_tool``, and a fake bus in a test suite owes no capability
        engine.  A bus with no engine to constrain is one whose dispatch was
        never scope-gated, and narrowing it is a no-op rather than a
        failure — the honest reading of "restrict what is already
        unrestricted".

        Returned, not mutated in place: the plane the orchestrator hands its
        roles is the value this returns, and the plane it started with is
        left as it was — a frozen object copied through
        :func:`~dataclasses.replace`, so a caller still holding the wider
        plane still holds the wider plane.  The *effect* — which scopes the
        engine now allows — lives on the shared engine, because that is the
        one object every dispatch consults; an allowlist that lived anywhere
        else would be a constraint the dispatch never read.  The
        orchestrator re-narrows at each phase boundary, so the engine's
        allowlist is this phase's and not the last one's, exactly as
        ``set_scope_constraints`` was called once per phase before it.
        """
        engine = getattr(self.bus, "capability_engine", None)
        if engine is not None and hasattr(engine, "set_scope_constraints"):
            engine.set_scope_constraints([str(scope) for scope in scopes])
        return replace(self)


# ── everything that can stop a run ──────────────────────────────────────────


@dataclass(frozen=True)
class Bounds:
    """Every number and switch that can end a run, in one object.

    **Nothing here is set by default.**  The framework imposes no budget of
    its own: ``max_steps`` is ``0`` — no ceiling — and ``deadline`` is
    ``None``, because a cap of eight decided how much work a question was
    worth, which is not a decision a framework can make.  Both are things
    an operator asks for, and running out of either is a recorded outcome
    that names which one.

    **The supervisor lives here**, and that is a decision worth the
    sentence.  It is what *replaced* the step budget: it watches for
    repetition and its ``stuck`` verdict is the one thing besides a clock
    and a person that ends a run, which is exactly what this object is a
    list of.  Putting it here also gets the sharing right for free — a
    child run inherits its parent's :class:`Bounds` unless it is handed
    others, so the swarm's sub-missions and the mission share **one**
    review budget the way they already share one :class:`~core.budgets
    .Deadline`.  Five supervisors for one turn would be five budgets, and
    a plan that loops across its steps is precisely the pattern no single
    sub-mission can see.

    ``started_at`` is the instant the *mission* began, which a staged run
    hands down so a sub-mission's ``elapsed_s`` counts from triage.
    ``None`` means "this run's own start", resolved in :meth:`Run.run` —
    resolved on the run and not written back here, because this object is
    frozen and shared and the resolution belongs to whoever is running.
    """

    #: A :class:`~core.budgets.Deadline`, or ``None`` for no wall clock.
    #: Shared, and first-start-wins, so a staged mission hands one clock to
    #: triage, the planner and every sub-mission.
    deadline: Optional[Deadline] = None
    #: A :class:`~core.budgets.Cancellation`, or any object with
    #: ``is_set()``.  ``None`` is a run nobody can stop.
    cancel: Any = None
    #: A :class:`~core.runtime.control.ControlChannel` — commands coming
    #: *in*, where :class:`Observer` is records going out — or ``None``.
    control: Any = None
    #: How long a gated call waits for a decision on :attr:`control`.
    gate_wait_s: float = GATE_WAIT_S
    #: The bound on what one tool result may add to the transcript.
    max_result_bytes: int = MAX_RESULT_BYTES
    #: When the mission began, on ``time.monotonic``.  See the docstring.
    started_at: Optional[float] = None
    #: An operator's hard ceiling on model turns, or ``0`` for none.
    max_steps: int = 0
    #: A :class:`~core.runtime.supervisor.Supervisor`, or ``None`` for a
    #: run nobody is watching.  Duck-typed: what a run needs is ``look``,
    #: ``saw_call`` and ``saw_rejection``.
    supervisor: Any = None

    def __post_init__(self) -> None:
        # Zero — or anything below it, which is a caller saying "no" in a
        # different dialect — is NO CEILING, and it is the default.
        object.__setattr__(self, "max_steps", max(0, int(self.max_steps)))
        object.__setattr__(self, "gate_wait_s",
                           max(0.0, float(self.gate_wait_s)))
        object.__setattr__(self, "max_result_bytes",
                           max(0, int(self.max_result_bytes)))

    def begin(self) -> float:
        """Start the wall clock, and answer when the run it bounds began.

        **The one owner of "a run's clock starts here".**  There were two:
        :meth:`Run.run` wound the :class:`~core.budgets.Deadline` and the
        staged path wound it again before triage, each with its own
        ``if deadline is not None``.  The two agreed only because
        :meth:`~core.budgets.Deadline.start` is first-start-wins — which
        is the property that makes one caller safe and is not an argument
        for two.

        The instant that comes back is ``started_at`` when a parent handed
        one down and *now* when nobody did, so a sub-mission's
        ``elapsed_s`` counts from the turn's triage rather than from its
        own first step.  Returned rather than written back: this object is
        frozen and shared, and whoever is running is the one that resolves
        it.
        """
        if self.deadline is not None:
            self.deadline.start()
        return time.monotonic() if self.started_at is None else self.started_at

    def stop(self) -> Optional[Tuple[str, Optional[BudgetExhausted], str]]:
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
        if cancelled(self.cancel):
            return self.cancelled_stop()
        exhausted = (self.deadline.exhausted()
                     if self.deadline is not None else None)
        if exhausted is not None:
            return "budget_exhausted", exhausted, ""
        return None

    @staticmethod
    def cancelled_stop() -> Tuple[str, Optional[BudgetExhausted], str]:
        """The verdict a run stopped by a person ends on.

        Its own method because there are two ways to be stopped by one and
        they must not describe it differently.  :meth:`stop` reaches it
        when the switch is found thrown at a drain point, which is how a
        ``SIGTERM``, a ``--control`` ``cancel`` and a library caller's
        :class:`~core.budgets.Cancellation` have always arrived; and
        :meth:`Run.arun` reaches it when the *task* running the loop is
        cancelled and an ``await`` raises
        :class:`asyncio.CancelledError`, which is how somebody holding the
        coroutine stops it.  Both are "a person stopped this", one word
        and one outcome — and a second spelling of it here is exactly the
        second emitter this package spent Phase 11 removing.
        """
        return "incomplete", None, CANCELLED


# ── what survives the process ───────────────────────────────────────────────


@dataclass(frozen=True)
class Store:
    """The durable half of a run: what is still there when the pipe breaks.

    One id serves the durable transcript and the approval request that
    names the run that asked, so a restart can tell a request whose run is
    gone from one whose run is still working.  ``""`` records nothing, and
    :meth:`~core.runtime.approvals.ApprovalStore.reconcile` leaves such a
    record alone rather than abandoning it.

    Named :attr:`runs` and not ``store`` because a mission's *result* store
    is a different object with a claim on that word, and two different
    things called the same word one line apart is how a caller passes the
    wrong one.  The result store is :attr:`Run.results`; this is the log.
    """

    #: A :class:`core.durable.RunStore`, or ``None`` to keep no transcript.
    runs: Optional[RunStore] = None
    #: The id of this run inside :attr:`runs`, and the id an approval
    #: request names.  ``""`` records nothing.
    run_id: str = ""
    #: A :class:`core.runtime.replay.Recorder`, or ``None``.  Duck-typed
    #: rather than imported: the recorder wraps the model and the bus at
    #: the caller's seam, and this module does not need its type to hold
    #: the fact that there is one.
    recorder: Any = None
    #: An :class:`~core.runtime.approvals.ApprovalStore`, or ``None``.
    approvals: Optional[ApprovalStore] = None
    #: An :class:`~core.runtime.approvals.ApprovalTicket` — a decision
    #: somebody already made, resolved at the door — or ``None``.
    ticket: Optional[ApprovalTicket] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_id", str(self.run_id or ""))


# ── every record out ────────────────────────────────────────────────────────


class Observer:
    """Every record a run emits, and the one place redaction happens.

    Not frozen and not a dataclass: it is a thing with behaviour, and the
    behaviour is the point.  :meth:`emit` is
    what ``MissionRunner._emit`` was — the durable log first, the
    watchers second,
    :func:`~core.redact.scrub_record` over everything, and nothing an
    observer does allowed to end a mission.

    Several sinks rather than one, because a caller already has several:
    the CLI's ``_watchers`` fans a record out to a pane, a file and a
    translator.  Zero sinks and no run store is the case that matters most
    — :meth:`emit` returns at its first line and a chat turn emits exactly
    the nothing it emits today.

    :attr:`store` is held here and not only on the :class:`Run` because
    persisting is *part of* emitting: the sink is a client of the durable
    log and not a second truth beside it, so a record a consumer saw is a
    record the transcript has.  It is the same :class:`Store` object the
    run holds, by identity.
    """

    def __init__(self, *sinks: Optional[Sink], branch: str = "",
                 store: Optional[Store] = None):
        #: The watchers, in the order they were given.  ``None`` sinks are
        #: dropped at the door so a caller may pass an optional one.
        self.sinks: Tuple[Sink, ...] = tuple(
            sink for sink in sinks if sink is not None)
        #: What a child run's records are called, and — since children can
        #: run at the same time — what every one of them carries on the
        #: wire as the OPTIONAL ``branch`` field.  ``""`` on the mission's
        #: own observer, and then no record carries the field at all: a
        #: run without children emits exactly the stream it always did.
        #: See :data:`core.runtime.contract.COMMON_OPTIONAL`.
        self.name = branch
        #: The durable log these records are written to.  See the class
        #: docstring; an empty :class:`Store` is "nothing is recorded".
        self.store = store if store is not None else Store()
        #: The next ``index`` a child's record may take in this run's ONE
        #: sequence.  Allocated by :meth:`branch`'s object **at emit time**
        #: and kept here, on the parent, because the sequence is the *run's*
        #: and not any one child's: a staged turn runs five sub-missions
        #: that each count their own steps from zero, and what a watcher
        #: must read is one mission with more steps.
        self._next_index = 0
        #: What makes the allocation above one act rather than a read and a
        #: write.  Held even though children share one event loop, where a
        #: coroutine cannot be interrupted between two statements: a
        #: :meth:`Run.run` called from a thread is a supported way in, the
        #: critic's verdict goes out through :func:`asyncio.to_thread`, and
        #: a numbering that is correct only because of where the awaits
        #: happen to be is a numbering the next refactor breaks silently.
        #: Uncontended it costs nothing, and what it buys is that two
        #: records can never take one number.
        #:
        #: It guards :attr:`_carried` too, and for a second reason: the
        #: pending ``plan`` must ride exactly one ``step_started``, and
        #: draining it in the same breath as the allocation makes that the
        #: step with the LOWEST new index — the first one on the wire —
        #: whichever child got there first.
        self._numbering = threading.Lock()
        #: Fields waiting for the next ``step_started`` **any** child emits
        #: — see :meth:`carry`.  Here rather than on a branch because the
        #: thing they are waiting for may not be the next record of the
        #: child that is running: a staged plan is announced before the
        #: first sub-mission exists, and a review of a failed gate happens
        #: between two of them.
        self._carried: Dict[str, Any] = {}

    def emit(self, event: str, **fields: Any) -> None:
        """One record to every watcher, or nothing.  Never raises.

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
        if not self.sinks and self.store.runs is None:
            return
        record = scrub_record({"event": event, **fields})
        # The store first, then the watcher: the sink is a CLIENT of the
        # durable log and not a second truth beside it, so a record a
        # consumer saw is a record the transcript has. The scrubbed copy
        # goes to both — a credential that must not reach a pane must not
        # reach a file on disk either.
        persist_record(self.store.runs, self.store.run_id, record)
        if not self.sinks:
            return
        try:
            for sink in self.sinks:
                sink(record)
        except Exception:                       # pragma: no cover - defensive
            pass

    def carry(self, **fields: Any) -> None:
        """Put *fields* on the next ``step_started`` a child of this
        observer emits.

        ``plan``, ``resumed`` and ``review`` are declared OPTIONAL on
        ``step_started`` and on no other event, so a field an event does
        not declare is a field a consumer meets with no sentence for.  Each
        of the three becomes true *between* records: a staged plan is drawn
        before the first sub-mission exists, a resumption is a fact about
        the stretch that is starting, and a review of a failed gate happens
        after one sub-mission ended and before the next begins.  So they
        wait here for the next step to ride, which is the next thing a
        watcher hears and the moment each of them starts being true.

        Waiting on the *parent* and not on a branch, because the child that
        will carry them may not exist yet — see :attr:`_carried`.  Called
        again with the same key replaces it: a plan as redrawn is the plan
        the steps arriving next belong to, not a second plan beside the one
        that was abandoned.

        **Which child takes them, when two are running.**  The one whose
        ``step_started`` gets the lowest of the new indices — the first of
        them on the wire — because the drain happens inside the same
        critical section the index is allocated in.  Exactly one step
        carries them, whatever the children do, and it is the earliest
        step of the stretch the fields are about, which is what a plan is
        a fact about.
        """
        with self._numbering:
            self._carried.update(fields)

    def _take(self) -> Dict[str, Any]:
        """What :meth:`carry` left, once.  Draining is the point: a field
        that arrived on every step would be a state restated rather than an
        event announced.

        **Called with :attr:`_numbering` already held** — by
        :meth:`_Branch.emit`, in the same breath as the allocation, which
        is what makes "exactly one step_started carries the plan" true of
        two children as well as of one.
        """
        carried, self._carried = self._carried, {}
        return carried

    def numbered(self, index: int) -> int:
        """*index* as it went out on the wire, for a caller that is not a
        record.

        The mission's own observer renumbers nothing, so this is the
        identity here; a stage's branch overrides it.  It exists because
        the **audit** needs the same number the stream carries: a loop
        counts its own steps from zero and the turn's sequence is the
        observer's, so an audit column filled in from the loop's counter
        would say "step 0" of two different children of one turn.  One
        owner of "what number is this step", asked rather than
        recalculated.
        """
        return index

    def branch(self, name: str = "", *, stage: bool = False,
               start_index: int = 0) -> "Observer":
        """A second observer for a child run, on the same sinks and log.

        The sinks and the :class:`Store` are shared **by identity**: one
        run, one log, one writer, whatever the records are called.  The
        child emits into what comes back and never learns that it is a
        child — which is the whole of what this is for, because a loop that
        knew would be a loop with a staged branch in it.

        *stage* is the one decision, and it is the difference between the
        two things a child run can be:

        * **the mission continued** (``False``) — the direct route of a
          staged turn, which is a whole agent answering the whole question.
          Its ``answer``, its ``grounding`` and its ``mission_finished``
          are the turn's, and only its ``mission_started`` is not: the
          parent announced the mission before triage, because triage is
          itself a call to the model and the contract's silence clause
          promises an opening ahead of the first one.  A second opening
          would render as a second mission.
        * **one stage of it** (``True``) — a plan step, whose bookkeeping
          belongs to the turn and not to it.  Only the five step-level
          records reach the stream, its ``index`` is renumbered into the
          parent's one sequence, and its opening *and* its closing are
          dropped — the turn's ``mission_finished`` is written where the
          turn ends, which is after the synthesizer and not after step
          three.

        *start_index* is where the global numbering begins, and it is ``0``
        everywhere except a resumed staged turn: those records go into the
        log an earlier stretch wrote, and numbering that started again
        would put two records with the same ``index`` in one run.  It is a
        **floor** on the parent's counter, applied when the first record
        of this branch is numbered rather than when the branch is built —
        see :class:`_Branch`.

        *name* is what every record of this child carries as ``branch``,
        and it is why a child of a mission with children should always have
        one: a consumer demultiplexing a parallel turn has nothing else to
        group on.
        """
        return _Branch(self, name, stage=stage, start_index=start_index)


class _Branch(Observer):
    """A child run's records, spoken as the parent's.

    What ``SwarmRunner._StageObserver`` and ``_OpenedAlready`` were, and
    they were two objects because they were reached as *callbacks* — a
    sub-runner was handed something record-shaped to call, and the two
    filters were the two shapes of that call.  A child is handed an
    :class:`Observer` now, so both are one subclass of one: the transform
    happens in :meth:`emit`, and what it emits into is the parent's own
    :meth:`Observer.emit` — the one choke point, where redaction happens
    and where the durable log is written.  One scrub, one append, one
    stream, whichever child spoke.

    Not a filter *beside* the parent but a caller *of* it, and that is the
    property that matters: there is no path from a child to a sink that
    does not pass through the parent, so a record a consumer saw is a
    record the transcript has.
    """

    #: What a **stage** contributes to the turn's stream: the records of
    #: work, and none of the bookkeeping.  A sub-mission's own opening and
    #: closing describe a mission a watcher must not be shown, and its
    #: ``answer`` is a step's summary rather than the turn's answer.
    _STAGE = frozenset({
        STEP_STARTED, REPLY_REJECTED, TOOL_CALL, TOOL_RESULT, GATE_REQUESTED,
    })

    def __init__(self, parent: Observer, name: str = "", *,
                 stage: bool = False, start_index: int = 0):
        super().__init__(*parent.sinks, branch=name, store=parent.store)
        self._parent = parent
        self._stage = bool(stage)
        # A FLOOR on the parent's counter, and nothing is taken from it
        # here. This used to read the counter at the door and hold the
        # value as an offset, which was deterministic exactly while the
        # children were built one after another and each had finished
        # before the next existed: two children constructed in one breath
        # both read the same number and numbered their steps on top of it,
        # so the turn emitted two records called `index: 0`. Nothing about
        # the read was wrong — a number cannot be allocated before there is
        # a record to give it to.
        self._floor = max(0, int(start_index))
        #: This child's local ``index`` -> the number it took in the turn's
        #: one sequence.  A step emits several records under one index —
        #: its ``step_started``, its calls, its results — and they are one
        #: step and must all say the same number, so the allocation happens
        #: once per local index rather than once per record.
        self._numbers: Dict[int, int] = {}

    def emit(self, event: str, **fields: Any) -> None:
        """One of this child's records, renamed into the parent's stream."""
        if self._stage:
            if event not in self._STAGE:
                return
        elif event == MISSION_STARTED:
            return
        # ONE critical section on the parent, holding both facts that are
        # the turn's rather than this child's: which number this record
        # takes, and whether it is the record the pending `plan` rides.
        # Together, because "the plan goes on the first step of the
        # stretch" is a statement about the numbering.
        renumber = self._stage and "index" in fields
        carried: Dict[str, Any] = {}
        if renumber or event == STEP_STARTED:
            with self._parent._numbering:
                if renumber:
                    fields = dict(fields, index=self._allocate(
                        int(fields["index"])))
                if event == STEP_STARTED:
                    carried = self._parent._take()
        if carried:
            # The record's own fields first and the carried ones after,
            # and a carried key REPLACES: a review the turn is carrying
            # is the review this step follows, whatever the child's own
            # supervisor had to say about the step before it.
            fields = {**fields, **carried}
        if self.name and "branch" not in fields:
            # Which child spoke, on every record this child emits — the
            # OPTIONAL field of `contract.COMMON_OPTIONAL`. `not in` and
            # not an overwrite, so that a branch of a branch keeps the
            # innermost name: the child that actually emitted the record
            # is the one a consumer can group on.
            fields["branch"] = self.name
        self._parent.emit(event, **fields)

    def numbered(self, local: int) -> int:
        """This child's step *local*, as the number the wire carries.

        Asked by :meth:`Run._dispatch` for the audit's ``step`` column, and
        answered out of the allocation :meth:`emit` already made — the
        ``step_started`` of a step is emitted before anything it dispatches,
        so the number exists by the time this is asked.  A step nothing has
        emitted yet is answered with the local number, which is what a run
        with no branch would have said anyway.

        Composed up the chain rather than returned flat, so a branch of a
        branch resolves through both.
        """
        if not self._stage:
            return self._parent.numbered(local)
        with self._parent._numbering:
            allocated = self._numbers.get(local)
        return self._parent.numbered(
            local if allocated is None else allocated)

    def _allocate(self, local: int) -> int:
        """This child's step *local*, as a number in the turn's sequence.

        **Called with the parent's numbering lock held.**  The first record
        of a step takes the next number the turn has; every later record of
        the same step is given the number that step already took.  So two
        children interleaving produce one strictly increasing sequence with
        no number used twice, and each child's own steps stay in the order
        it ran them — which is all a consumer needs to demultiplex on
        ``branch`` and all a consumer that ignores ``branch`` needs to read
        one ordered mission.
        """
        if local not in self._numbers:
            self._parent._next_index = max(self._parent._next_index,
                                           self._floor)
            self._numbers[local] = self._parent._next_index
            self._parent._next_index += 1
        return self._numbers[local]


# ── the client, the protocol, and the side channels ─────────────────────────


@dataclass
class Model:
    """What a run asks, how it reads the answer, and what the call cost.

    Not frozen, unlike the four above: :attr:`ledger` accumulates, and a
    caller that hands one in owns it.  Everything else here is settled
    before the first turn.

    ``ask`` is a **function** and not a client, which is the seam this
    harness has always had: the loop is confined to one injected callable
    and cannot ask a backend anything the caller did not offer.
    :attr:`usage_fn` and :attr:`tool_calls_fn` are nullary callables for
    the same reason — ``ask`` returns the reply and half a dozen callers
    depend on that shape, and handing the loop a client instead would give
    a deliberately confined loop something it could ask anything.
    """

    #: ``messages -> str`` or ``messages -> iterator of delta frames``.
    #: The CLI's ``chat_fn``.
    ask: Callable[..., Any]
    #: The same model with **no tools declared** — the CLI's
    #: ``plain_chat_fn``, which the supervisor, the router and the roles
    #: ask their questions through.  A question answered with a tool call
    #: is the failure it exists to prevent.  Read by the staged path.
    plain: Optional[Callable[..., Any]] = None
    #: :data:`~core.runtime.mission.JSON_PROTOCOL` or
    #: :data:`~core.runtime.mission.NATIVE_PROTOCOL`.
    protocol: str = JSON_PROTOCOL
    #: A :class:`~core.runtime.context_window.MissionWindow`, or ``None``
    #: for a loop that sends whatever it has accumulated.
    window: Optional[MissionWindow] = None
    #: Whether the caller's ``ask`` streams.  A fact about the request the
    #: caller builds, held here so one object answers "what is this model
    #: and how does it speak"; the loop reads the reply's *shape* and does
    #: not consult this.
    streaming: bool = True
    #: Whether the caller may ask for a JSON-shaped reply.  Read by the
    #: staged path's object-returning roles.
    json_mode: bool = False
    #: ``() -> Usage | None``, read after every call: what the provider
    #: said *that* call cost.  ``None`` accumulates nothing.
    usage_fn: Optional[Callable[[], Any]] = None
    #: ``() -> [{"id", "name", "arguments", ["arguments_raw"]}, …]``, read
    #: after every call under the native protocol.
    tool_calls_fn: Optional[Callable[[], Any]] = None
    #: A :class:`~core.runtime.usage.Rate`, or ``None``.  Only used to put
    #: ``cost`` beside the totals on ``mission_finished``.
    rate: Optional[Rate] = None
    #: An existing :class:`~core.runtime.usage.Ledger` to accumulate into,
    #: or ``None`` for a fresh one per run.
    #:
    #: ``None`` and not ``Ledger()``, which is what ``ROADMAP.md`` §2.6.1
    #: sketched, and the difference is behaviour: a ledger that lived on
    #: this object would be shared by every run of it, and a runner used
    #: twice would report the first run's tokens on the second.  "The
    #: caller's, or one per run" is what the loop has always done, and it
    #: is how a staged turn keeps ONE ledger across its sub-missions.
    ledger: Optional[Ledger] = None

    def __post_init__(self) -> None:
        if self.protocol not in PROTOCOLS:
            raise ValueError(
                f"protocol must be one of {', '.join(PROTOCOLS)}, got "
                f"{self.protocol!r}")

    @property
    def native(self) -> bool:
        """Whether this model is being spoken to in function calls."""
        return self.protocol == NATIVE_PROTOCOL

    def spend(self, ledger: Ledger) -> Dict[str, Any]:
        """Fold the last call into *ledger*; render its own field.

        Called once per step, immediately after :attr:`ask` returns, and
        the ``{"usage": …}`` it hands back is spread into whichever record
        that step goes on to emit — ``tool_call``, ``answer`` or
        ``reply_rejected``, the three records that follow a model call.

        ``{}`` when the provider reported nothing, so the field is
        **absent** rather than zero.  Never raises: a usage source that
        throws must not be able to end a mission, for the same reason an
        observer that throws cannot.

        The run's ledger is handed in rather than read off :attr:`ledger`,
        which is the caller's-or-none — see that field.  One owner of the
        fold either way: this is the only place :meth:`Ledger.add
        <core.runtime.usage.Ledger.add>` is called on a mission's turn.
        """
        try:
            usage = self.usage_fn() if self.usage_fn is not None else None
        except Exception:                       # pragma: no cover - defensive
            usage = None
        recorded = ledger.add(usage)
        return {"usage": recorded.as_record()} if recorded is not None else {}


# ── running a coroutine from code that is not one ───────────────────────────


def _to_completion(coro: Any) -> Any:
    """Run *coro* to completion and hand back what it returned.

    The whole of :meth:`Run.run`, and the one place this package decides
    what "a synchronous caller of an asynchronous loop" means.  Two cases,
    and the second is the one worth the words.

    **No loop is running on this thread** — every caller in this
    repository, and every library caller with a script.
    :func:`asyncio.run` gives the coroutine a fresh loop, runs it, cancels
    whatever it left behind and closes the loop.  A fresh loop per run and
    not one kept warm on the side: a loop that outlived the run would
    outlive the run's cancellation scope too, and a second run of the same
    :class:`Run` would inherit a callback queue nobody could point at.

    **A loop IS running on this thread** — a caller inside ``async def``
    who reached for ``run`` instead of ``arun``.  The coroutine goes to a
    worker thread with a loop of its own and this thread blocks on the
    result.  It is not what that caller should write — ``await
    run.arun(…)`` is, and it is one word shorter — but the alternative to
    answering them is :func:`asyncio.run` raising ``cannot be called from
    a running event loop`` on a method that has been synchronous since the
    first version of this harness, and a refactor that turns a working
    call into an exception is a refactor that changed something.  It
    blocks the loop it was called from, exactly as any synchronous call in
    a coroutine does; it does not deadlock, which is the property that
    matters and the one there is a test for.

    A child run never takes the second path.  A parent inside
    :meth:`Run.arun` awaits ``child.arun(...)`` — one loop, one thread,
    and the numbering, the ledger and the store shared by identity the way
    :meth:`Run.child` promises.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    # One thread, joined before this returns, and shut down with it: this
    # is a blocking call the caller asked for, not a background one.
    with ThreadPoolExecutor(max_workers=1,
                            thread_name_prefix="judais-run") as pool:
        return pool.submit(asyncio.run, coro).result()


# ── the loop ────────────────────────────────────────────────────────────────


class Run:
    """Seed the plan with a tool catalogue, then let the model drive.

    The loop itself — what a step is, what an answer is worth, what a
    dispatch emits — is unchanged from
    :class:`~core.runtime.mission.MissionRunner`, whose ``Parameters``
    section is still the long-form documentation of everything the six
    objects carry.  What is new is only that they arrive as six objects.

    Everything mutable about a run lives on **this** object and not on the
    six: the result store, the plane baseline, the pending plane news, the
    wind-up flag.  The six describe the run; this runs it.
    """

    def __init__(self, personality: Personality, plane: ToolPlane,
                 bounds: Bounds, store: Store, observer: Observer,
                 model: Model):
        self.personality = personality
        self.bounds = bounds
        self.store = store
        self.observer = observer
        self.model = model
        # A ticket does ONE thing: its tool leaves the gated set for this
        # run. Here, because this is where a Store's decision and a
        # ToolPlane's set meet, and through the ticket's own subtraction so
        # that the direct path, the staged path and the opening frame
        # cannot disagree about which tools are gated. The plane is left
        # alone — the same object, shared with a parent or a child — when
        # the ticket subtracts nothing from it.
        if store.ticket is not None:
            widened = frozenset(store.ticket.widen(plane.gated))
            if widened != plane.gated:
                plane = replace(plane, gated=widened)
        self.plane = plane
        if self.model.native and ANSWER_TOOL in self.offered:
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
        #: The mission's result store.  One per run object, cleared per
        #: run, and adopted whole from a resumption.  Not :attr:`store`,
        #: which is the durable log — see :class:`Store`.
        self.results = MissionResultStore()
        #: Set by a `stuck` verdict: the next turn is the LAST one, and it
        #: is a request for the best answer the run can write. Per run, so
        #: `run` resets it.
        self._winding_up = False
        #: Whether the step that just ran was a grounding repair turn — the
        #: one path that legitimately continues after an answer, and
        #: therefore the one thing that may follow a wind-up turn.
        self._repairing = False
        #: What the bus had registered when this run started, or ``None``
        #: before one has. The baseline for "the plane GREW", so a tool that
        #: was on the bus and deliberately left out of the closed set can
        #: never wander into it later.
        self._baseline: Optional[set] = None
        #: What changed since the last step boundary, rendered (``+mcp.x``,
        #: ``-mcp.y``) and waiting to be told to the model. Drained by
        #: :meth:`_plane_news`, which is the one place a step decides whether
        #: its system turn is the same bytes as the last one's.
        self._pending: List[str] = []
        # The instant the MISSION began, on `time.monotonic`. A staged run
        # hands its own down so a sub-mission's `mission_finished` counts
        # from triage, not from the sub-mission; `None` means "this run's
        # own start", set in `run`. Resolved here and not on `Bounds`,
        # which is frozen and may be shared with a parent that started
        # earlier.
        self._started_at = bounds.started_at
        # Asked once, of this bus, at construction — not per dispatch, and
        # not by declaring a flag a caller has to remember to set. See
        # `_deadline_ceiling` for why a mission may not simply pass one.
        self._bus_takes_deadline = plane.takes_deadline()
        # The same probe of the same signature, for the audit's step
        # column. A bus that does not name `step` gets no step, exactly as
        # a bus that does not name `deadline_s` gets no seconds.
        self._bus_takes_step = plane.takes_step()

    def child(self, *, personality: Optional[Personality] = None,
              bounds: Optional[Bounds] = None, branch: str = "",
              stage: bool = False, start_index: int = 0,
              ledger: Optional[Ledger] = None) -> "Run":
        """A sibling run: same store, same observer, same model, same plane.

        Shared **by identity**, which is the whole of what the object is
        for.  One :class:`Store` is one durable log and one approval
        store; one :class:`Observer` is one stream; one :class:`Model` is
        one ledger and therefore one invoice; one :class:`Bounds`, unless
        another is handed in, is one clock and **one supervisor** — the
        review budget a staged turn has to share for the same reason the
        clock is shared.

        What a caller overrides is what genuinely differs between a
        mission and its steps: the prompt the step is given
        (*personality*), and — rarely — a narrower set of bounds.  There
        is deliberately no step *portion*: the ceiling is an operator's
        and is not divided among children, and what watches a child going
        nowhere is the supervisor they share.

        *branch* names the child, and it names it in **two** places at
        once, which is why it is one argument: every record this child
        emits carries it as the OPTIONAL ``branch`` field
        (:meth:`Observer.branch`), and its result store is published under
        it so that two children on one bus do not collide on
        ``mission_result`` (:meth:`ToolPlane.lease`).  Those are the same
        fact — which child this is — and a caller that had to state it
        twice would eventually state it twice differently.  *stage* says
        what kind of child this is — the mission continued, or one stage
        of it; see :meth:`Observer.branch`, which documents both.
        *start_index* is where a resumed turn's numbering picks up.

        *ledger* is what makes children **gatherable**.  Handed one, the
        child spends into it rather than into the model's own, and the
        caller folds it back at the join through
        :meth:`~core.runtime.usage.Ledger.absorb` — single-threaded, in an
        order the caller chooses, so a turn's totals are the same numbers
        whichever child finished first.  ``None`` is a child sharing the
        parent's ledger by identity, which is what a child that runs alone
        should do: the direct route of a staged turn ends the turn, and its
        ``mission_finished`` carries the *turn's* invoice including the
        router call that chose it.

        A child with neither a name nor a stage shares the parent's
        observer outright, which is the only shape in which a child's
        ``mission_started`` still reaches a watcher.  Every caller in this
        package names its children, because every one of them is a child
        of a run that has already announced itself.

        **A child is awaited, not run.**  ``await child.arun(...)`` from
        inside a parent's :meth:`arun` is one loop, one thread and one
        numbering; ``child.run(...)`` from the same place would answer
        correctly and answer on a loop of its own, which is a child whose
        records were emitted from somewhere else and a sibling that could
        not be gathered beside it.  The synchronous façade is for a
        synchronous caller — see :func:`_to_completion`.

        The **plane is shared, and its offered set with it**.  That is the
        one thing a sub-mission did not get before: each built its own
        plane from the manifest's list, so a tool that arrived mid-turn
        was offered to the step that learned about it and to no later one.
        One plane is one answer to "what may be called now" for the whole
        turn, which is what a closed set is for.  A named child gets a
        *lease* of it — the same bus, the same live offered list, the same
        gated set, all by identity, with only the result store keyed to
        this child; see :meth:`ToolPlane.lease`.
        """
        return Run(
            personality if personality is not None else self.personality,
            self.plane.lease(branch) if branch else self.plane,
            bounds if bounds is not None else self.bounds,
            self.store,
            self.observer.branch(branch, stage=stage,
                                 start_index=start_index)
            if (branch or stage) else self.observer,
            self.model if ledger is None
            else replace(self.model, ledger=ledger),
        )

    @property
    def run_id(self) -> str:
        """The run this loop's records are being recorded under, or ``""``.

        Readable because the id is the only handle a caller has on the
        transcript afterwards, and the store — not the runner and not the
        CLI — is the one that hands it out.
        """
        return self.store.run_id

    @property
    def protocol(self) -> str:
        """Which protocol this loop is speaking, :data:`JSON_PROTOCOL` or
        :data:`NATIVE_PROTOCOL`.

        Readable because the caller that built the ``chat_fn`` has to
        declare the matching request, and a resume has to rebuild the
        matching messages — two decisions made outside this object about
        a fact it holds.
        """
        return self.model.protocol

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
        if self.plane.store_tool:
            return [*self.plane.offered, self.plane.store_tool]
        return list(self.plane.offered)

    # ── the plane, when it changes underneath a running mission ─────────

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
        if self._baseline is None:
            return []
        registered = self.plane.registered()
        if registered is None:
            return []
        now = set(registered)
        offered = set(self.plane.offered)
        grew = [name for name in registered
                if name not in self._baseline and name not in offered
                and name != self.plane.store_tool]
        joined = list(grew)
        if self.plane.admits is not None and grew:
            allowed = set(str(name) for name in
                          self.plane.admits(grew, self.offered))
            joined = [name for name in grew if name in allowed]
        gone = [name for name in self.plane.offered
                if name in self._baseline and name not in now]
        self._baseline = now
        if not joined and not gone:
            return []
        self.plane.offered[:] = [name for name in self.plane.offered
                                 if name not in gone] + joined
        changes = [f"+{name}" for name in joined] + [f"-{name}" for name in gone]
        self._pending.extend(changes)
        if self.plane.plane_changed is not None:
            try:
                self.plane.plane_changed(self.offered)
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
        news, self._pending = list(self._pending), []
        return news

    @property
    def gated(self) -> List[str]:
        """Offered tools that need a person, in catalogue order."""
        return [name for name in self.offered if name in self.plane.gated]

    # ── asking the model ────────────────────────────────────────────────

    async def _model_reply(self, messages: List[Dict[str, Any]],
                           index: int) -> str:
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

        **The call itself goes to a worker thread.**  ``ask`` is a
        synchronous callable — every backend in this tree is, and
        rewriting them is not this lane's — and it is where a mission
        spends most of its wall clock: on a 59 tok/s endpoint one answer
        is tens of seconds inside one function call.  Awaited through
        :func:`asyncio.to_thread`, those seconds are seconds the loop can
        spend elsewhere, which is what lets two children of one run have
        two calls in flight at once.  Nothing about the request or the
        reply changes: the same list of messages goes to the same
        callable and the same string comes back, and the thread it
        happened on is not a fact any record carries.

        The frames of a streamed reply are then awaited one at a time —
        see :func:`~core.runtime.answer_stream.adrain`, which shares the
        one fragment cut with the synchronous drain — so ``answer_delta``
        goes out *as* the answer decodes rather than after it, which is
        the whole reason that record exists.  A source that is already
        asynchronous is iterated as one; no backend here is yet, and
        refusing one would be this loop having an opinion about a shape
        it does not need to hold.
        """
        got = await asyncio.to_thread(self.model.ask, messages)
        if isinstance(got, str):
            return got
        if got is None or not (hasattr(got, "__iter__")
                               or hasattr(got, "__aiter__")):
            return str(got or "")

        part = 0

        def on_delta(text: str) -> None:
            nonlocal part
            self.observer.emit(ANSWER_DELTA, index=index, part=part, text=text)
            part += 1

        return await adrain_answer(got, on_delta, native=self.model.native,
                                   answer_tool=ANSWER_TOOL)

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
            info = self.plane.bus.describe_tool(name)
            if "error" in info:
                continue
            desc = info.get("description") or ""
            # Marked in the catalogue rather than withheld from it. See the
            # `gated` parameter: "there is no tool named X" is false and a
            # model told it reroutes around a capability it actually has.
            mark = (" [NEEDS APPROVAL — propose it and a person decides; the "
                    "call is not made until they do]"
                    if name in self.plane.gated else "")
            lines.append(f"- {name}: {desc}{mark}".rstrip())
            arguments = info.get("arguments") or summarize_input_schema(
                info.get("input_schema")
            )
            if arguments:
                lines.append(f"    arguments: {arguments}")
        return "\n".join(lines) if lines else "(no tools available)"

    def opening(self, objective: str) -> Dict[str, Any]:
        """The ``mission_started`` fields for this run.

        **One builder, and there are two emitters.**  This loop emits it
        from :meth:`run`; the staged path emits it before triage, because
        triage is itself a call to the model and the contract's silence
        clause promises an opening ahead of the first one.  Those were two
        hand-written dicts, and the second one's own comment admitted it —
        which is the arrangement that let ``grounding`` ship six of the ten
        fields its contract requires.  A consumer must not be able to read
        an internal decision of this harness (*which route did the router
        take*) off a record that promises it one vocabulary, and the only
        way to promise that is for there to be one place the record is
        built.

        Every field comes off an owner and none is restated here:
        :attr:`offered` is the plane's live set plus the store tool,
        :attr:`gated` is that set narrowed by the plane's gated names (a
        ticket having already been spent at construction),
        ``sandbox``/``audit_ref``/``profile`` are the three facts read off
        the bus, and ``schema_version`` is first and on the FIRST record so
        a consumer that is going to refuse this stream refuses it before it
        has rendered anything from it.

        ``history`` is a count and not the turns: a watcher needs to tell a
        seeded conversation from a cold start, and the turns themselves
        already travelled once.
        """
        return {
            "schema_version": SCHEMA_VERSION,
            "objective": objective,
            "catalogue": self.offered,
            "gated": self.gated,
            "max_steps": self.bounds.max_steps,
            "history": len(self.personality.history),
            # The word the bus's actual runner answers to — `bwrap` or
            # `none` — so a consumer learns from the opening frame whether
            # this mission's tool subprocesses are isolated, without
            # inferring it from the host.
            "sandbox": self.plane.sandbox,
            # The file every dispatch below is written to, and `None` says
            # there is no such file because somebody turned auditing off in
            # as many words. A consumer that finds no audit log and no
            # field cannot tell that from a harness that failed to open one.
            "audit_ref": self.plane.audit_ref,
            **_run_field(self.store.run_id),
            **_protocol_field(self.model.protocol),
            **self.plane.profile_field,
        }

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
            *(dict(turn) for turn in self.personality.history),
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
            self.personality.system_message,
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
        return (NATIVE_PROTOCOL_TEXT.strip() if self.model.native
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
        return 2 + len(self.personality.history)

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
        if not self.plane.store_tool:
            return note
        gone = (f" The results whose text was removed here are still in that "
                f"store: call {self.plane.store_tool}() with no handle "
                "for the "
                f"list of everything this mission has stored."
                if dropped_results else "")
        return (
            f"{note} Every result of this mission is still readable: call "
            f'{self.plane.store_tool}(handle="…", path="…") with the '
            "handle you "
            f"were given when it arrived.{gone}"
        )

    def _fit(
        self, messages: List[Dict[str, str]],
    ) -> Tuple[List[Dict[str, str]], Optional[Compaction]]:
        """``(messages to send, what was dropped or None)``.

        No window is the loop as it ran before there was one: the list
        goes out whole.
        """
        if self.model.window is None:
            return messages, None
        kept, compaction = self.model.window.fit(
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

    # ── how far the loop may go, and who is watching it ─────────────────

    def _indices(self, start: int):
        """The step numbers this run may use.

        A ``range`` when an operator set a ceiling and an unbounded count
        when nobody did — which is the default, and is the whole of "the
        framework imposes no step budget".  ONE place decides which, so
        the ``for`` below reads the same either way and there is no second
        spelling of "unbounded" to disagree with this one.

        An unbounded run leaves the loop by answering, by being stopped,
        or by being wound up: the ``budget_exhausted`` tail after the loop
        is reachable only when there is a ceiling to exhaust.
        """
        if self.bounds.max_steps <= 0:
            return itertools.count(start)
        return range(start, self.bounds.max_steps)

    def _supervise(self, objective: str, transcript: MissionTranscript,
                   messages: List[Dict[str, Any]],
                   injected: List[str]) -> Optional[Any]:
        """Ask the supervisor about the step that just ran, and act on it.

        ``None`` — no supervisor, or nothing to say — is a step that
        proceeds exactly as it did before this existed, and a
        ``step_started`` without a ``review`` field on it.

        The one place a verdict becomes behaviour, which is why the
        verdicts are read here and nowhere else:

        * ``progressing`` does nothing at all.  It still rides the record,
          because "something looked wrong and was judged fine" is a fact a
          watcher wants and an absence cannot state;
        * ``nudge`` says the note to the model **through the same
          mechanism an operator's ``inject`` uses** and appends it to the
          same ``injected`` list, because it is the same act — somebody
          outside the conversation putting a turn in it — and a second
          field for it would be a second thing to render.  A nudge whose
          reviewer wrote no note says nothing: there is nothing to say,
          and inventing a sentence here would be this loop writing the
          review;
        * ``stuck`` asks for the best answer this run can write and marks
          the transcript ``stuck`` **now** rather than at the end.  The
          reason is true from this moment whichever way the last turn
          goes, and a cancellation or a deadline arriving during it
          overwrites it on purpose: a person who threw the switch, or a
          clock an operator set, is the truer thing to report.
        """
        if self.bounds.supervisor is None:
            return None
        review = self.bounds.supervisor.look(
            objective, ledger=transcript.usage)
        if review is None:
            return None
        if review.verdict == NUDGE and review.note:
            note = NUDGE_NOTE.format(signal=review.sentence(),
                                     note=review.note)
            self._say(messages, note)
            injected.append(note)
        elif review.verdict == STUCK:
            self._say(messages, WIND_UP.format(signal=review.sentence()))
            self._winding_up = True
            transcript.reason = STUCK
        return review

    def _reject(self, index: int, problem: str, **fields: Any) -> None:
        """One rejected reply: on the stream, and in front of the watcher.

        Both halves in one method because there are five places a reply can
        be refused and five places to forget the second half of it — and a
        supervisor shown four rejections out of five is counting a pattern
        it cannot see the whole of.  The record is byte for byte the one
        this loop always emitted.
        """
        self.observer.emit(REPLY_REJECTED, index=index, problem=problem,
                           **fields)
        if self.bounds.supervisor is not None:
            self.bounds.supervisor.saw_rejection()

    # ── the loop ────────────────────────────────────────────────────────

    def run(self, objective: str,
            resumption: Optional[Any] = None) -> MissionTranscript:
        """:meth:`arun`, run to completion.  **This method is the wrapper.**

        Every caller this package has is synchronous — ``judais --mission``,
        :class:`~core.runtime.mission.MissionRunner`, the staged path, a
        library caller with a script — and none of them had to learn a new
        word when the loop became a coroutine.  What they call is this,
        and this is a policy about event loops and nothing else: it makes
        no decision about the mission, emits no record, and holds no state.
        The loop is :meth:`arun`.

        **The policy, in two cases.**  Called from a thread with no event
        loop running — which is every caller in this repository — the
        coroutine gets a fresh loop of its own through :func:`asyncio.run`,
        and that loop is closed when the run ends.  Called from *inside* a
        running loop, it goes to a worker thread with a fresh loop of its
        own and this thread blocks on the result: a caller that asked a
        blocking question is answered, rather than deadlocked on a loop it
        is itself standing in the way of.  See :func:`_to_completion`,
        which is where that costs a paragraph.

        A child run is the case that must not take the second path, and it
        does not: a parent inside :meth:`arun` awaits ``child.arun(...)``
        directly — that is what the parallel-children lane will hand to
        :func:`asyncio.gather` — so no child of a running loop opens a
        second one.
        """
        return _to_completion(self.arun(objective, resumption))

    async def arun(self, objective: str,
                   resumption: Optional[Any] = None) -> MissionTranscript:
        """Run the mission, or carry a recorded one on from where it stopped.

        **This is the loop.**  :meth:`run` is this method run to
        completion and is what everything in this package calls; the
        awaits are here, and there are five of them:

        * **the model call** — :meth:`_model_reply`, on a worker thread;
        * **each frame of a streamed reply** — inside that call, so
          ``answer_delta`` is emitted as the answer decodes;
        * **each dispatch** — :meth:`_dispatch`, on a worker thread,
          because a tool is a subprocess or a server and neither is quick;
        * **a gate's wait for a decision** — :meth:`_gate`, which awaits
          the control channel rather than sleeping on it;
        * **the verdict on an answer** — :meth:`_verdict`, which may ask a
          critic, which is another endpoint.

        Every one of them is a point this loop already stopped at.  A
        control command is still taken at the step boundary and at a call
        boundary and nowhere else; a stop is still asked about at the same
        two places; the records are the same records in the same order.

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
        # Through `Bounds.begin`, which is the one owner of "a run's clock
        # starts here" — the first start wins, so a sub-mission of a staged
        # run does not rewind the clock its parent already wound. What comes
        # back is the instant the MISSION began, which is a parent's when a
        # parent handed one down.
        started = self.bounds.begin()
        if self._started_at is None:
            self._started_at = started
        # Per run and not per runner: a runner used twice must not open its
        # second run already winding up from the first one's verdict.
        self._winding_up = False
        self._repairing = False
        offered = self.offered
        transcript = MissionTranscript(
            objective=objective, catalogue=list(offered),
            # A ledger the caller handed in is shared and must not be
            # reset here; without one, a fresh ledger per run, so a second
            # `run` on the same runner does not report the first one's
            # tokens.
            usage=self.model.ledger if self.model.ledger is not None
            else Ledger(),
        )
        if resumption is None:
            self.results.clear()
        else:
            # Adopted, not copied into: the handles the model was given
            # earlier in this run (`r1`, `r2`) have to keep addressing the
            # same results, and a store rebuilt beside the runner's own
            # would mean `mission_result` reads one and the grounding
            # validator reads the other.
            self.results = resumption.store
            transcript.steps.extend(resumption.steps)
        registered = self._register_store()
        # The baseline for "the plane grew", taken AFTER the store tool is on
        # the bus so the mission's own descriptor is never read as an
        # arrival. Everything registered at this instant — every local tool
        # the closed set left out included — is what this run was offered a
        # subset of, and only what appears later is ever put to `admits`.
        self._baseline = set(self.plane.registered() or ())
        self._pending = []
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
            self.observer.emit(MISSION_STARTED, **self.opening(objective))
        try:
            return await self._loop(objective, transcript, resumption)
        except asyncio.CancelledError:
            # Somebody holding this task cancelled it, and the await it was
            # sitting on raised. Caught, and the run ends the way a run
            # stopped by a person has always ended: the same outcome, the
            # same `reason`, and the `finally` below writing the same
            # `mission_finished`. Not re-raised, and that is the decision:
            # a caller of `run` would otherwise get an exception where the
            # exit contract promises a transcript, and a watcher would get
            # a stream that stops mid-mission — which is the state
            # `mission_finished` exists so that nobody is ever left in.
            #
            # A cancellation caught here does NOT stop a model call that is
            # already on a worker thread; nothing can, short of the
            # backend's own timeout. What it stops is this loop waiting for
            # it, which is what the person asked for.
            return self._stopped(transcript, self.bounds.cancelled_stop())
        finally:
            if registered:
                # This branch's store goes; the descriptor goes with the
                # LAST branch holding it. Nothing is left on the bus for
                # the same reason nothing ever was — it outlives the run.
                self.plane.close_store()
            # Nothing to withdraw from `bus.audit_context` any more, and
            # that is the point of `step` riding the dispatch: a column
            # that is a parameter of the call cannot be left behind on a
            # shared bus to stamp the next chat turn with this mission's
            # last index. See `_dispatch`.
            #
            # In `finally` so that a mission killed by an exception still tells
            # the watcher the mission is over. A stream that just stops is
            # indistinguishable from an agent that is thinking, and a pane
            # showing a spinner forever is the state an analyst cannot leave.
            # Through `_finished_record` and not by hand, because the staged
            # path emits this record too and a second hand-listing is how the
            # swarm's `grounding` came to carry six of ten fields.
            # `usage` is the run's totals and is ABSENT when no provider
            # reported anything — not three zeros.
            self.observer.emit(MISSION_FINISHED, **_finished_record(
                outcome=transcript.outcome,
                steps=len(transcript.steps),
                max_steps=self.bounds.max_steps,
                budget=transcript.budget,
                reason=transcript.reason,
                usage=transcript.usage.as_record(self.model.rate),
                started_at=self._started_at))

    def _register_store(self) -> str:
        """Put the result store on the bus for the length of this run.

        Registered and withdrawn rather than left there: the store holds
        one mission's results, and a descriptor that outlived the run
        would offer the next one a handle into the previous one's
        governed material.  It goes through the bus like everything else
        so the audit log records a read of it.

        Through the plane, which is where "one descriptor, several
        children's stores" is decided.  A run with no children is the same
        act it always was — one store, one registration, refused if the
        name is taken — and a child of a turn publishes its store under
        the branch it is, so two of them may run at once.  See
        :meth:`ToolPlane.open_store` and
        :class:`~core.runtime.results.BranchedStores`.
        """
        return self.plane.open_store(self.results)

    async def _loop(
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

        # Unbounded unless an operator asked for a ceiling — see `_indices`.
        # When they did, `self.bounds.max_steps` is the TOTAL for the run
        # and not
        # an allowance for this process (see `Recorded.total_steps`, which
        # is where the caller works out what that total is), so a resumed
        # run whose recorded steps already met it runs no steps and ends
        # `budget_exhausted`, which is the truth about it.
        for index in self._indices(start):
            # The wind-up turn has been asked and did not answer. Ending
            # here rather than inside the turn keeps every path a turn can
            # take — a parse error, a refused tool, a dispatch — exactly as
            # it was; what a wind-up changes is that there is no turn after
            # it. A grounding repair is the one continuation that is not a
            # further attempt at the mission, so it is allowed through.
            if self._winding_up and not self._repairing:
                transcript.outcome = "incomplete"
                return transcript
            self._repairing = False
            # Between steps AND before the model call, which in this loop
            # is one point: every path that continues — a parse error, a
            # refused tool, a grounding repair — comes back through here,
            # so a run cannot spend a repair turn past its deadline.
            stop = self.bounds.stop()
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
            # After the operator and before the ask, at the same boundary
            # and for the same reason: the supervisor's note is somebody
            # outside the conversation speaking into it, and the one moment
            # that is safe is the one where the model has finished a turn
            # and not begun the next. It goes after `_steer` so that an
            # operator who spoke on the same boundary is heard first — a
            # person outranks a watcher.
            review = self._supervise(objective, transcript, messages,
                                     injected)
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
            self.observer.emit(STEP_STARTED, index=index, **opening,
                       **({"catalogue": self.offered} if changed else {}),
                       **({"injected": injected} if injected else {}),
                       # On the step that FOLLOWS a review turn and no
                       # other, exactly as `compacted` is on the step whose
                       # conversation was shortened: the field is the record
                       # that a review happened, and one that arrived every
                       # step would be a state restated rather than an event
                       # announced.
                       **({"review": review.as_record()}
                          if review is not None else {}),
                       **({"compacted": compacted.as_record()}
                          if compacted is not None else {}))
            opening = {}
            reply = await self._model_reply(messages, index)
            # Read here and used below: whichever record this step emits
            # carries the cost of the call that produced it. One read per
            # call, because `last_usage` is a side channel that the NEXT
            # call clears.
            spent = self.model.spend(transcript.usage)
            step = MissionStep(index=index, raw_reply=reply)

            if self.model.native:
                # The whole of the other protocol, in one branch and one
                # method. Everything it decides — an answer, a gate, a stop
                # — is decided by the same helpers the lines below use, so
                # there is one owner for what a dispatch emits and one for
                # what an answer is worth.
                done, repairs = await self._native_turn(
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
                self._reject(index, problem, **spent)
                messages.append({"role": "user", "content": problem})
                continue

            if "answer" in decision:
                done, repairs = await self._answered(
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
                self._reject(index, problem, tool=name, **spent)
                messages.append({"role": "user", "content": problem})
                continue

            step.tool, step.arguments = name, dict(arguments)

            # `_offers` and not `name in offered`: the bus is the authority
            # on what exists, and it is asked again before a refusal.
            if not self._offers(name):
                problem = self._no_such_tool(name, self.offered)
                step.error = problem
                transcript.steps.append(step)
                self._reject(index, problem, tool=name, **spent)
                messages.append({"role": "user", "content": problem})
                continue

            if name in self.plane.gated:
                # `None` back means the gate was ANSWERED on the control
                # channel while the run stood at it — the call was
                # dispatched, or it was refused and said so — and this turn
                # carries on with the step that already happened.
                stopped = await self._gate(
                    objective, index, name, arguments, step, transcript,
                    messages=messages, spent=spent)
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
                self._reject(index, problem, tool=name, **spent)
                messages.append({"role": "user", "content": problem})
                continue

            # Checked again here, after the model call this step spent: the
            # clock may have run out while the endpoint was answering, and
            # `tool_call` is emitted BEFORE the dispatch, so a watcher told
            # a call was about to happen must not then be told the mission
            # ended without it. The proposal is recorded as a step that did
            # not run, in the model's own words about what it wanted.
            stop = self.bounds.stop()
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

            await self._dispatch(step, index, spent, messages)
            transcript.steps.append(step)

        transcript.outcome = "budget_exhausted"
        # Which budget, with the numbers. `steps` and not `seconds`: the
        # `for` ran to its end, so the clock — if there was one — still had
        # room, and a consumer told "budget_exhausted" and nothing else
        # cannot tell a mission that needed more turns from one that needed
        # a faster endpoint.
        transcript.budget = BudgetExhausted(
            "steps", self.bounds.max_steps, len(transcript.steps))
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
        if self.model.native and call_id:
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
            info = self.plane.bus.describe_tool(name)
        except Exception:                       # pragma: no cover - defensive
            return ""
        if not isinstance(info, dict) or "error" in info:
            return ""
        return check_arguments(name, info.get("input_schema"), arguments)

    async def _dispatch(self, slot: Any, index: int, spent: Dict[str, Any],
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
        self.observer.emit(TOOL_CALL, index=index, tool=name,
                   arguments=dict(arguments), **ordinal, **spent)
        if self.store.ticket is not None and name == self.store.ticket.tool:
            # HERE and not at the door: a resumed run that answers
            # without calling anything, or runs out of steps, has not
            # used anybody's yes, and burning one on a run where nothing
            # happened teaches an operator to approve the same act twice.
            # Before the dispatch, so a store that refuses to spend —
            # somebody else already did, the record moved underneath us —
            # stops the call rather than following it. That refusal is
            # allowed to end the mission: failing closed is the only
            # direction this may fail in.
            self.store.ticket.spend()
        # The remaining wall clock rides down as a ceiling on the call,
        # where the bus takes one, so a tool cannot run past the
        # deadline by more than its own bounded slack.
        call = dict(arguments)
        call.update(self._deadline_ceiling())
        # And the step this call belongs to, for the audit's own column.
        # It USED to be left in `bus.audit_context` — a mutable dict on a
        # bus that serves chat turns and kernel roles too — immediately
        # before the awaited dispatch below. One run at a time that was
        # merely indirect; two children of one turn dispatching at once
        # made it wrong, because the second child's write landed before
        # the first child's entry was built and both were stamped with
        # the second's index. A column that is wrong is worse than one
        # that is absent. It rides the call now, exactly as `deadline_s`
        # does and for the same reason: the keyword is the BUS's own and
        # is consumed there, so it is not an argument invented for
        # somebody else's schema. A bus that does not name it gets none.
        if self._bus_takes_step:
            # The number the WIRE carries, not this loop's own counter.
            # A stage counts its steps from zero and the turn's sequence is
            # the observer's, so an audit filled in from `index` would say
            # "step 0" of the first step of every child. One owner of
            # "which step is this" — see `Observer.numbered`.
            call["step"] = self.observer.numbered(index)
        # Which child is asking, for the mission's OWN store tool and for
        # nothing else. One `mission_result` is registered for the whole
        # turn — the model is told one name whatever branch it is on —
        # and the descriptor behind it routes on this word to the store
        # of the child that called. `{}` on every other tool and on every
        # run without children, so nothing else ever sees it. See
        # `ToolPlane.store_routing`.
        call.update(self.plane.store_routing(name))
        # On a worker thread, for the reason the model call is: a dispatch
        # is a subprocess or a server, it is the other place a mission
        # spends real time, and a loop blocked inside it is a loop that
        # cannot run a sibling child or drain a control channel. The bus
        # is unchanged and is still called exactly once with exactly these
        # arguments — `deadline_s` included, which is the only ceiling a
        # tool has ever been given and is not a timeout on this await.
        #
        # The MCP bus reaches its server through a second hop: a client
        # with its own loop on its own thread, entered by
        # `run_coroutine_threadsafe`. Awaiting that session directly from
        # here would delete the hop, and it is NOT done in this lane —
        # `ToolBus.dispatch` is where capability gating, the audit entry
        # and the sandbox live, and an async path to the session that
        # skipped them would be a second dispatcher with a different
        # governance story. See ROADMAP.md §2.6.3.
        result = await asyncio.to_thread(self.plane.bus.dispatch, name, **call)
        if self.bounds.supervisor is not None:
            # The WHOLE result and the exit code with it, not the bounded
            # rendering the model is shown: what makes a repetition a
            # repetition is whether the bytes are the same, two different
            # 40 KB listings cut to the same first 4 KB are not the same
            # result, and a tool that starts succeeding is progress even
            # when its output has not changed.
            self.bounds.supervisor.saw_call(
                name, arguments,
                f"{result.exit_code}\x00{result.stdout}\x00{result.stderr}")
        slot.exit_code = result.exit_code
        slot.output = result.stdout
        slot.error = result.stderr
        stored = self.results.record(
            name, arguments,
            text=result.stdout,
            evidence=getattr(result, "evidence", "") or "",
            exit_code=result.exit_code,
        )
        slot.handle = stored.handle
        rendered, slot.truncated = self._render_result(
            name, result, stored.handle,
            already=self.results.first_identical(stored),
        )
        # The WHOLE result, not the bounded rendering. The bound exists
        # because a model's context is finite; a watcher's is not, and a
        # pane showing an analyst 60% of a governed listing because the
        # model could only be shown that much would be inventing a limit
        # nobody imposed.
        self.observer.emit(TOOL_RESULT, index=index, tool=name,
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

    async def _answered(self, answer: str, index: int, step: MissionStep,
                        spent: Dict[str, Any],
                        messages: List[Dict[str, Any]],
                        transcript: MissionTranscript, repairs: int,
                        call_id: str = "",
                        ) -> Tuple[Optional[MissionTranscript], int]:
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

        :meth:`_verdict` is awaited **through
        :func:`asyncio.to_thread`** and is still an ordinary method,
        which is deliberate on both counts: it may ask a critic, which is
        a second endpoint and therefore a second thing not to block the
        loop on; and the staged path calls the same method from
        synchronous code, so it stays callable there.  One
        implementation, two callers, and the awaited one does not hold
        the loop while a critic thinks.
        """
        report = self._ground(answer, repairs)
        transcript.grounding = report

        if report is not None and report.ran and not report.grounded:
            if repairs < self.personality.grounding.max_repairs:
                repairs += 1
                problem = self._repairing_turn(report, repairs)
                step.error = problem
                transcript.steps.append(step)
                self._say(messages, problem, call_id)
                # The one continuation that is not another attempt at the
                # mission: the model answered and is being asked to say the
                # same thing with its citations in it. A wind-up turn that
                # produced an unsupported answer gets its repair turn for
                # exactly this reason — see the top of `_loop`.
                self._repairing = True
                return None, repairs
            # One repair turn was spent and the claim is still
            # unsupported. The answer is kept — deleting it would
            # hide a finding — and says so about itself.
            marked = self._caveated(report, repairs)
            transcript.grounding = marked
            transcript.answer = answer + marked.caveat
            transcript.outcome = "answered_with_caveat"
            transcript.steps.append(step)
            await asyncio.to_thread(
                self._verdict, transcript.objective, answer, marked,
                repairs=repairs, caveat=marked.caveat)
            self.observer.emit(ANSWER, text=transcript.answer,
                       outcome=transcript.outcome, **spent)
            return transcript, repairs

        if report is not None:
            # `report` and not a copy of it: `_ground` already put this
            # run's repair count on what it returned, which is the one
            # place that arithmetic happens.
            await asyncio.to_thread(
                self._verdict, transcript.objective, answer, report,
                repairs=repairs)
        transcript.answer = answer
        transcript.outcome = "answered"
        transcript.steps.append(step)
        self.observer.emit(ANSWER, text=answer,
                           outcome=transcript.outcome, **spent)
        return transcript, repairs

    # ── what an answer is worth: four owners, and TWO callers ───────────
    #
    # The staged path's synthesizer writes an answer too, over the whole
    # turn's evidence, and it used to check that answer with a loop of its
    # own — a second reading of "a report that could not run", a second
    # caveat, a second `grounding` record built by hand.  It calls these
    # four now.  What it cannot share is the *asking*: this loop's repair
    # is another turn of the loop and the synthesizer's is one more call
    # to a model with no tools, which are genuinely two things and not one
    # thing written twice.  Everything either of them decides ABOUT an
    # answer is here.

    def _repairing_turn(self, report: GroundingReport, repairs: int) -> str:
        """Announce a repair turn; return what to ask the model for.

        A repair turn is a whole extra round-trip to the model and, from
        outside, looks exactly like a stall.  Said out loud so a watcher
        can show WHY the answer is taking longer — the check caught
        something — and the record that follows it is the verdict.

        The prompt comes back rather than being written twice: the
        announcement and the question are one act, and the staged path
        spent its repair turns silently for as long as they were two.
        """
        self.observer.emit(GROUNDING, **_grounding_record(
            report, repairs=repairs, repairing=True))
        return self.personality.grounding.repair_prompt(report)

    def _caveated(self, report: GroundingReport,
                  repairs: int) -> GroundingReport:
        """The report an answer that stayed unsupported wears.

        The answer is kept — deleting it would hide a finding — and says
        so about itself, in the validator's own sentence.  The report is
        rebuilt rather than edited because what is carried forward is
        exactly ``results``: a caveat is a fact about the run and not a
        check that ran.
        """
        return GroundingReport(
            results=report.results, repairs=repairs,
            caveat=self.personality.grounding.caveat(report))

    def _verdict(self, objective: str, draft: str, report: GroundingReport,
                 *, repairs: int, caveat: str = "",
                 evidence: Optional[Sequence[str]] = None) -> None:
        """The ``grounding`` record, critic row included — the ONE emitter.

        Emitted BEFORE the ``answer`` it is about, always, so a consumer
        building a frame around the prose already knows what to mark it
        with.  A caveat that arrives after the text it qualifies is a
        caveat that can be rendered separately from it.

        *draft* is what the model wrote and not what the run will return:
        the critic is asked about the model's words, and the caveat is
        this harness's own sentence about them — a critic shown its own
        harness's caveat is being asked to review the grader.

        The second opinion is asked on the clean path too, where it
        declines: no rule in :mod:`core.critic.triggers` fires on a
        grounded answer, and the call is made anyway so that the decision
        has ONE owner.  A branch that skipped asking would be a second
        copy of the trigger policy, written in ``if``s.

        Synchronous, with two callers that reach it differently: the loop
        awaits it on a worker thread (see :meth:`_answered`) because the
        critic is an endpoint, and the staged path's synthesizer calls it
        straight, from code that is not in an event loop.  The record it
        writes is the same record either way — the emitting is
        :class:`Observer`'s, which is one choke point whichever thread
        reaches it, and the two callers are serialised by the ``await``.
        """
        self.observer.emit(GROUNDING, **_grounding_record(
            report, repairs=repairs, caveat=caveat,
            opinions=self._second_opinion(
                objective, draft, report,
                answered_with_caveat=bool(caveat), evidence=evidence)))

    def _second_opinion(self, objective: str, answer: str,
                        report: GroundingReport, *,
                        answered_with_caveat: bool,
                        evidence: Optional[Sequence[str]] = None,
                        ) -> List[Dict[str, Any]]:
        """This run's evidence, put to :func:`second_opinion`.

        A thin call and deliberately thin: what a critic row looks like is
        the module function's, and what THIS object contributes is the
        evidence its own result store holds — unless a caller names other
        evidence, which the staged path does because a turn's evidence is
        the union of five sub-missions' stores and no one of them.

        It runs **before** the ``answer`` record, like the grounding verdict
        it sits beside, so a consumer framing the prose has the whole
        verdict before the prose arrives.  Under streaming the text has
        already gone out as ``answer_delta`` fragments, so what this delays
        is the authoritative record and not the reader's first sight of the
        answer.
        """
        return second_opinion(
            self.personality.critic, objective, answer,
            self.results.evidence_texts() if evidence is None else evidence,
            unsupported=report.unsupported,
            answered_with_caveat=answered_with_caveat)

    async def _gate(self, objective: str, index: int, name: str,
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
        self.observer.emit(GATE_REQUESTED, index=index, tool=name,
                   arguments=dict(arguments), reason=reason, **carried)

        if waiting and approval_id:
            # Awaited, not slept on: the window is five minutes by default
            # because the thing on the other end is a person being paged,
            # and five minutes of `time.sleep` on the loop's own thread
            # would be five minutes in which this run's siblings could not
            # take a step. The wait itself is unchanged — same predicate,
            # same window, same three ways to come back with nothing — see
            # `ControlChannel.await_for`, which shares every decision it
            # makes with the synchronous `wait_for` beside it.
            decision = await self.bounds.control.await_for(
                lambda command: (
                    command.get("control") == GATE_DECISION
                    and command.get("approval_id") == approval_id),
                self._gate_window())
            if decision is not None:
                approved, trouble = _record_decision(
                    self.store.approvals, approval_id, decision)
                if not trouble:
                    return await self._answered_gate(
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
        return (self.bounds.control is not None
                and self.store.approvals is not None
                and self.bounds.gate_wait_s > 0)

    def _gate_window(self) -> float:
        """``min(what the caller allows, what is left of the clock)``.

        The deadline wins where it is shorter, because a run that waited
        five minutes for a person and then reported that it had run out of
        seconds would have spent the operator's whole budget standing
        still.  Negative remaining floors at zero — :meth:`wait_for
        <core.runtime.control.ControlChannel.wait_for>` returns at once,
        which is the honest reading of a clock that is already past.
        """
        window = self.bounds.gate_wait_s
        remaining = (self.bounds.deadline.remaining()
                     if self.bounds.deadline is not None else None)
        if remaining is not None:
            window = min(window, max(0.0, remaining))
        return window

    async def _answered_gate(self, approved: bool, decision: Dict[str, Any],
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
            await self._dispatch(slot, index, spent, messages)
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

        Never raises, for the reason :meth:`Model.spend` does not: a side
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
            raw = (self.model.tool_calls_fn()
                   if self.model.tool_calls_fn is not None else None)
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

    async def _native_turn(
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
            self._reject(index, problem,
                         **({"tool": tool} if tool else {}), **cost())
            self._say(messages, problem, call_id)

        if not calls:
            # Some servers answer in prose despite `tool_choice="required"`,
            # and prose that says something is an answer: refusing it would
            # spend a turn asking again for text already written. Prose that
            # says nothing is the one case with nothing to salvage.
            text = reply.strip()
            if text:
                return await self._answered(
                    text, index, step, cost(), messages, transcript,
                    repairs)
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
            return await self._answered(
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
            if name in self.plane.gated:
                # The turn ends HERE, on this call — unless somebody
                # answers the gate on the control channel while it stands,
                # in which case `_gate` dispatches (or refuses) this one
                # call and hands back `None`, and the calls after it run in
                # their turn. The ones before it have already run and are
                # on the record; the ones after it are not dispatched if
                # the mission stops, and the reason says how many.
                stopped = await self._gate(
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
            stop = self.bounds.stop()
            if stop is not None:
                call.error = self._no_time_to_call(name, stop)
                transcript.steps.append(step)
                return self._stopped(transcript, stop), repairs
            await self._dispatch(call, index, cost(), messages)

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
        if self.store.approvals is None:
            return "", ""
        try:
            return self.store.approvals.request(
                tool=tool, arguments=dict(arguments), objective=objective,
                run_id=self.store.run_id, reason=reason), ""
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
        if self.bounds.control is None:
            return []
        injected: List[str] = []
        # Arrival order, not kind order: two injections and a late
        # cancel_step reach the model in the order the operator sent them,
        # which is the only order they mean anything in.
        for command in self.bounds.control.poll():
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
                self.bounds.control.warn(
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
        if self.bounds.control is None:
            return False
        return bool(self.bounds.control.poll(only=(CANCEL_STEP,)))

    # ── being asked to stop, and running out of clock ───────────────────

    @staticmethod
    def _stopped(transcript: MissionTranscript,
                 stop: Tuple[str, Optional[BudgetExhausted], str],
                 ) -> MissionTranscript:
        """Write a :meth:`Bounds.stop` verdict onto the transcript and hand it
        back."""
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
        if self.bounds.deadline is None or not self._bus_takes_deadline:
            return {}
        remaining = self.bounds.deadline.remaining()
        if remaining is None:
            return {}
        return {"deadline_s": max(0.0, remaining)}

    def _ground(self, answer: str, repairs: int, *,
                evidence: Optional[Sequence[str]] = None,
                called: Optional[Sequence[str]] = None,
                ) -> Optional[GroundingReport]:
        """Validate the answer, or ``None`` when nothing is configured.

        *evidence* and *called* default to this run's own result store,
        which is every direct mission.  A staged turn names its own: its
        answer is written over what five sub-missions read, and a claim to
        have used a tool is true if *any* step used it, so neither fact is
        in one store.  The DECISIONS are the same either way — a check that
        could not run is a report with no opinion, and it must not be read
        as a pass — and that is what this method is the owner of.
        """
        if self.personality.grounding is None:
            return None
        report = self.personality.grounding.validate(
            answer,
            self.results.evidence_texts() if evidence is None else evidence,
            # Which tools this run dispatched, from the store that recorded
            # them — the plane-claim check's evidence, and the one place
            # that fact lives. See `MissionResultStore.called_tools`.
            called=(self.results.called_tools() if called is None
                    else called))
        # Reshaped, always, and with the run's own repair count on it. Two
        # facts ride out of here: what the checks said, which is
        # `results`, and how many repair turns this answer has already
        # cost, which the validator has no way to know. A report that says
        # `repairs: 0` after a repair turn is a `grounding` record that
        # understates the work — and a caller that fixed that itself was
        # the second owner of it. `caveat` is deliberately dropped: it is a
        # fact about the RUN, written by `_caveated` at the one moment it
        # becomes true.
        #
        # A report where every check said it could not run comes back the
        # same way, and it must not be read as a pass — `ran` is False on
        # it, and it is kept on the transcript for exactly that reason.
        return GroundingReport(results=report.results, repairs=repairs)

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
            f' Call {self.plane.store_tool}(handle="{already.handle}", '
            'path="...") '
            f"to read any field of it — the whole result is there, including "
            f"the parts the transcript truncated."
            if self.plane.store_tool else
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
            f'{self.plane.store_tool}(handle="{handle}", path="...") '
            "for one field."
            if handle and self.plane.store_tool else
            " The rest is not retrievable in this mission."
        )
        return bound_result(body, self.bounds.max_result_bytes, where=where)
