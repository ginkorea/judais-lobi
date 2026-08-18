# core/runtime/resume.py — picking a mission back up, and closing the ones nobody will

"""What a recorded run is worth after the process that made it is gone.

:mod:`core.durable` made a mission's records survive the process.  That is
half of a durable run.  The other half is being able to *use* them: to open
a run somebody killed, put the loop back in the state it was in, and carry
on; and to notice the runs nobody will ever carry on and close their logs
so a follower is not left waiting on a stream that stopped mid-sentence.

Three things live here, and they are deliberately separate:

**The door** (:func:`open_for_resume`).  Every refusal a resume can meet is
answered *before* a model is asked or a server is dialled: an id this store
never minted, a run that already ended, an objective that is not the one on
record.  A refusal names both halves of what disagreed — the resume of the
wrong run is the failure this whole feature can produce that nothing else
would catch, because it looks exactly like a run continuing.

**The replay** (:func:`rebuild`).  The recorded stream, read back into the
three things :class:`~core.runtime.mission.MissionRunner` carries between
steps: the transcript's steps, the mission result store, and the message
list.  It is a *reconstruction* and not a recording — the loop's own
messages were never on the wire, because the contract carries what happened
and not what the harness said about it — so the reconstruction goes through
the runner's own :meth:`~core.runtime.mission.MissionRunner._render_result`
rather than a second copy of it here.  One owner: a private rendering in
this module would drift from the loop's the first time either changed, and
the resumed model would read a differently-worded transcript of its own
previous turns.

A **staged** (``--swarm``) run is rebuilt differently, and the difference
is the design of :mod:`core.runtime.swarm` rather than a shortcut: a
staged step runs in its own small :class:`MissionRunner` with its own
seed, and what travels between steps is a *summary* and never a
transcript.  So :class:`StagedResumption` carries no message list at all,
and its absence is not a loss — the resumed steps read exactly what they
would have read had the process never died.  What it carries instead is
what the plan carries: the checkpointed plan, the settled steps'
summaries, and the results the recorded stretch's tools returned.  See
:func:`_rebuild_staged`.

What cannot come back is written down rather than papered over — see
:attr:`Resumption.lost` and the ``LOST_*`` sentences below.

**Reconciliation** (:func:`reconcile_orphans`).  A run directory with no
``mission_finished`` in it is either a mission that died or a mission that
is still going, and the difference is asked of the **kernel**: a process
running a run holds an ``flock`` on it (:meth:`core.durable.RunStore.hold`)
for as long as it lives, so a free lock is a dead run and a held one is a
live one, whatever either has been writing.  The metadata clock survives
only as the fallback for a platform with no ``flock``, and there it is
widened past the longest thing a live run legitimately does in silence —
standing at a gate — because the old sixty-second rule closed live runs.
See :data:`ORPHAN_STALE_S` and :data:`ORPHAN_FALLBACK_MARGIN_S`.

Nothing here decides an approval.  A run that stopped at a gate is
resumable — the gated set is applied on the resumed turn exactly as it was
on the first one, so a mission whose gate nobody has answered proposes the
call and stops again.  That is correct, and it is the seam a decision
record plugs into later.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence

from core.durable import LOCKS, NoSuchRun, Run, RunStore, now
from core.runtime.mission import (
    AWAITING_APPROVAL, JSON_PROTOCOL, NATIVE_PROTOCOL, MissionCall,
    MissionStep,
)
from core.runtime.mission_stream import (
    ANSWER, GATE_REQUESTED, GROUNDING, MISSION_FINISHED, MISSION_STARTED,
    REPLY_REJECTED, STEP_STARTED, TOOL_CALL, TOOL_RESULT,
)
from core.runtime.messages import assistant_turn
from core.runtime.results import MissionResultStore

__all__ = [
    "ORPHAN_OUTCOME", "ORPHAN_STALE_S", "ORPHAN_FALLBACK_MARGIN_S",
    "orphan_window", "RESUMABLE_OUTCOMES", "RESUMED",
    "ResumeRefused", "Recorded", "Resumption", "StagedResumption",
    "open_for_resume", "rebuild", "reconcile_orphans", "recorded_outcome",
    "resumed_record",
]


#: How long a run's metadata has to have been untouched before this harness
#: is willing to *consider* it an orphan.  The second half of the question —
#: is anybody running it? — is the lock, and the lock is the half that
#: decides.  See :func:`reconcile_orphans`.
#:
#: The guard exists because "no ``mission_finished`` in the log" is not the
#: question anybody actually wants answered.  A mission that has been
#: thinking for forty seconds has no ``mission_finished`` either, and a
#: second process that closed its log out from under it would put a
#: terminal record in the middle of a live stream — a follower would render
#: the mission as over and stop reading, and the answer that arrived
#: afterwards would go to nobody.
#:
#: ``updated_at`` moves on **every** append (see
#: :meth:`core.durable.RunStore.append`) and on every heartbeat of a
#: :class:`~core.durable.RunHold`, so a run doing anything at all — and a
#: held run doing nothing at all — is fresh.  Sixty seconds is chosen
#: against the slowest thing a mission does between records, one call to a
#: cold local model, and it is a constant rather than a literal because it
#: is the number to raise on a deployment whose model is slower than that.
#:
#: **It was once the whole rule, and as the whole rule it was wrong.**  A
#: live run legitimately says nothing for five minutes while it stands at a
#: gate waiting for a decision (:data:`~core.runtime.control.GATE_WAIT_S`),
#: and sixty seconds of that was enough for any sibling ``judais --mission``
#: to close its log, abandon its pending approval, and leave it to append a
#: second ``mission_finished`` with a different outcome when it finished.
ORPHAN_STALE_S = 60.0

#: How much longer than the gate window the **fallback** clock waits, on a
#: platform that has no ``flock`` to read.
#:
#: :func:`orphan_window` is ``max(stale_s, GATE_WAIT_S + this)``: never
#: below the longest silence a live run is entitled to, plus room for the
#: turn that follows the decision to write its next record.  It is only ever
#: the fallback — where :data:`core.durable.LOCKS` is true the lock answers
#: and this number is not consulted — but where it is the only answer it has
#: to be an answer that cannot close a run that is waiting for a person.
ORPHAN_FALLBACK_MARGIN_S = 60.0


def orphan_window(stale_s: Optional[float] = None,
                  locks: Optional[bool] = None) -> float:
    """How long a run must have been quiet before the clock may close it.

    ``None`` — nobody stated a number — is :data:`ORPHAN_STALE_S` where the
    kernel can be asked (:data:`core.durable.LOCKS`), because there the
    clock is only a cheap first filter and the lock is what decides; and
    where it cannot be asked the clock is the whole rule, so the default is
    widened to ``GATE_WAIT_S + ORPHAN_FALLBACK_MARGIN_S``.  That floor is
    the whole point: a **default** must not be able to close a run that is
    standing at a gate waiting for a person.

    **A stated number is the caller's and is used as given**, floor and
    all.  An operator who passes ``stale_s=0`` to :func:`reconcile_orphans`
    — ``core.server``'s ``--reconcile-stale`` is the one that does — is
    saying "close what is quiet now", and a floor that quietly ignored them
    would be an argument that does nothing.  The default is the one this
    module is responsible for; a number somebody typed is theirs.

    One function so the arithmetic is derived in one place and a test can
    ask for it rather than restating it.
    """
    from core.runtime.control import GATE_WAIT_S

    if stale_s is not None:
        return max(0.0, float(stale_s))
    readable = LOCKS if locks is None else bool(locks)
    if readable:
        return ORPHAN_STALE_S
    return max(ORPHAN_STALE_S, float(GATE_WAIT_S) + ORPHAN_FALLBACK_MARGIN_S)


#: The OPTIONAL field the first ``step_started`` of a resumed stretch
#: carries.  See :data:`core.runtime.contract.OPTIONAL`.
RESUMED = "resumed"

#: What ``mission_finished.outcome`` says for a run this module closed
#: because nobody else was going to.  The transcript's own default word —
#: reconciliation is not a new kind of ending, it is the ending the run
#: already had, written down by somebody else.
ORPHAN_OUTCOME = "incomplete"

#: The recorded outcomes a run may be picked back up from, as data rather
#: than as a condition somewhere in :func:`open_for_resume`.
#:
#: ``""`` is a log with no ``mission_finished`` at all: a process that died
#: without reaching the ``finally`` that would have closed it.
#:
#: ``incomplete`` is the same thing one step further on — the transcript's
#: default word, and therefore what a mission killed by an *exception*
#: records, because ``mission_finished`` is emitted from a ``finally`` and a
#: crash still closes its own stream.  It is also what
#: :func:`reconcile_orphans` writes.  Refusing it would mean the two
#: commonest ways a mission dies were the two it could never be resumed
#: from, and that a background reconciliation quietly took resumability away
#: from every orphan sixty seconds after it was born.
#:
#: ``awaiting_approval`` is the outcome that is not an ending: nothing
#: failed, nothing was called, and the next move belongs to a person.
#:
#: Everything else **concluded**.  ``answered`` and
#: ``answered_with_caveat`` produced the thing the mission was for, and
#: ``budget_exhausted`` is a cap doing its job — resuming past it would be a
#: way of spending a budget the operator set, which is precisely what
#: :meth:`Recorded.total_steps` exists to prevent.  A conclusion is a
#: record, not a mission in progress.
RESUMABLE_OUTCOMES = ("", ORPHAN_OUTCOME, AWAITING_APPROVAL)


# ── what a replay cannot give back ───────────────────────────────────────────
#
# Each of these is a sentence that goes into `Resumption.lost`, written once
# here so the caller that shows them and the test that asserts them are
# reading the same string.

LOST_STRUCTURED = (
    "the typed payload of every replayed tool result: `structuredContent` "
    "never travelled on the event stream, so a replayed result has its text "
    "and not its parsed fields — grounding still sees the text, and "
    "mission_result(handle=…, path=…) will refuse a field path into a "
    "replayed result"
)
LOST_REJECTED_REPLY = (
    "the text of {n} rejected model repl{y}: `reply_rejected` carries the "
    "refusal and not the reply, because the reply is precisely the thing "
    "that did not parse — the correction is replayed verbatim and the turn "
    "it corrected comes back empty"
)
LOST_REPAIR_TURN = (
    "{n} grounding repair turn{s}: the answer a validator refused is not on "
    "the stream (`answer` is emitted once, at the end), so the turn is "
    "counted against the step budget and its two messages are not replayed"
)
LOST_SCRUBBED = (
    "the unscrubbed text of {n} failed tool result{s}: `error` is redacted "
    "at the emitter, so what the resumed model reads back is the scrubbed "
    "sentence a watcher saw"
)
LOST_STAGED_EVIDENCE = (
    "the raw tool output behind {n} completed plan step{s}: a staged "
    "resume rebuilds its grounding evidence from `tool_result.output` on "
    "the event stream, which is scrubbed and bounded, so the validator "
    "that checks the synthesized answer sees what a watcher saw rather "
    "than what the tool returned"
)
LOST_NATIVE_IDS = (
    "the provider's own ids for {n} replayed tool call{s}, and any opaque "
    "field it attached to them: a `tool_call_id` is the server's and never "
    "travelled on the event stream, so the rebuilt turns quote ids this "
    "process minted — the conversation is well-formed and the model will "
    "not recognise the ids as its own"
)


class ResumeRefused(Exception):
    """This run will not be resumed, and the message says exactly why.

    An exception rather than a returned ``(ok, reason)`` because every
    caller of :func:`open_for_resume` has the same and only sane response —
    stop, and print the sentence — and a refusal that can be ignored by
    forgetting to check a tuple is a refusal that will be.
    """


# ── the door ─────────────────────────────────────────────────────────────────


@dataclass
class Recorded:
    """One recorded run, admitted for resuming.  Facts only, no rebuild."""

    run_id: str
    #: The objective on record.  The resumed loop is seeded with this and
    #: never with a caller's paraphrase of it.
    objective: str
    #: The store's metadata record as it was at the door.
    meta: Run
    #: Every record in the log, oldest first, unwrapped.
    records: List[Dict[str, Any]]
    #: The last ``seq`` the log held when this run was admitted — the cursor
    #: a follower reading it would be sitting on, and what the resumed
    #: stretch announces as ``resumed.from_seq``.
    from_seq: int
    #: The recorded ``mission_started.max_steps``: the ceiling this run was
    #: started with, and the total the resumed stretch is held to unless the
    #: caller states a new one.  See :meth:`total_steps`.
    max_steps: int
    #: The recorded terminal outcome: ``""`` for a log with no
    #: ``mission_finished``, ``"incomplete"`` for a run whose process
    #: crashed or was reconciled, ``"awaiting_approval"`` for one stopped at
    #: a gate.  Nothing else gets through the door — see
    #: :data:`RESUMABLE_OUTCOMES`.
    outcome: str
    #: The protocol the recorded stretch was run under, off its own
    #: ``mission_started.protocol`` — absent there means
    #: :data:`~core.runtime.mission.JSON_PROTOCOL`, which is every run
    #: recorded before the field existed.
    #:
    #: It is a property of the RUN and not of the resuming command line,
    #: which is why it is read here and refused at the door when the two
    #: disagree: the replay rebuilds the model's own turns, and a native
    #: turn is an assistant message carrying ``tool_calls`` answered by
    #: ``tool`` messages where a JSON one is text answered by a user turn.
    #: Rebuilding one shape and then sending the other is a 400 at best
    #: and a model reading somebody else's transcript at worst.
    protocol: str = JSON_PROTOCOL
    #: Whether this run was a staged (``--swarm``) turn.  Read off the
    #: metadata and not off the stream: the plan rides one ``step_started``
    #: and a run killed before its first step never emitted one, while its
    #: checkpoint was written before that step was asked.
    staged: bool = False
    #: The checkpointed plan, every field of every step, as
    #: :meth:`core.runtime.swarm.PlanStep.as_state` wrote it.
    plan: List[Dict[str, Any]] = field(default_factory=list)
    #: The checkpointed step outcomes, as
    #: :meth:`core.runtime.swarm.SwarmRunner._step_done` wrote them.
    steps_done: List[Dict[str, Any]] = field(default_factory=list)
    #: Whether the staged run has already spent its one plan redraw.
    replanned: bool = False

    def total_steps(self, more: Optional[int]) -> int:
        """The step ceiling for the whole run — recorded steps included.

        **The rule, stated once.**  ``max_steps`` bounds a *mission*, not a
        process.  A resume that started the count again would turn a
        ceiling into a per-process one, which anybody could widen by
        killing the mission and resuming it, and the flag would stop
        meaning what it says.

        So with *more* ``None`` — no ``--mission-steps`` on the resuming
        command line — the total is the one the run was started with, and
        the steps already in the log count against it: a run that spent 5
        of 8 has 3 left.  **A run started with no ceiling resumes with no
        ceiling**, which is the same rule read against a recorded ``0``:
        the operator set nothing then and has said nothing now, and
        inventing a bound at the moment a run is picked back up would be
        the resume deciding something the run never did.

        With *more* given, the operator has restated the ceiling on purpose
        and it is read as *that many further steps*: the total becomes what
        has been spent plus what they asked for — on an unbounded run too,
        which is how a ceiling is put on a run that had none.  Either way
        ``mission_finished`` reports ``steps`` and ``max_steps`` as totals
        for the run, so the two remain comparable across a resume.

        **``0`` is no ceiling here too**, and that is the one word this
        method may not read differently from the rest of the harness.
        ``max_steps: 0`` is what ``mission_started`` and
        ``mission_finished`` carry for an unbounded run, and
        ``--mission-steps 0`` on a fresh mission means unbounded; read as
        "nought further steps" a resume would end ``budget_exhausted``
        before its first turn, which is the same flag meaning opposite
        things on two command lines.  So a stated ``0`` takes the ceiling
        **off** the run — an operator who types a number is restating the
        bound on purpose, and this is the number that says there is none.
        """
        spent = self.spent_steps
        if more is None:
            return 0 if self.max_steps <= 0 else max(self.max_steps, spent)
        if int(more) <= 0:
            return 0
        return spent + int(more)

    @property
    def spent_steps(self) -> int:
        """How many step indices this run has already used.

        Counted off ``step_started`` and not off the steps that finished,
        deliberately: a step that was asked and whose model call never
        returned cost the round trip, and reusing its index would put two
        records with the same ``index`` in one log.
        """
        highest = -1
        for record in self.records:
            if record.get("event") == STEP_STARTED:
                highest = max(highest, int(record.get("index", 0)))
        return highest + 1


def recorded_outcome(records: Sequence[Mapping[str, Any]]) -> str:
    """The outcome of the last ``mission_finished``, or ``""``.

    ``""`` means the log has no terminal record: an orphan, or a run that
    is going on right now.  This function cannot tell those apart and does
    not try — that is what :data:`ORPHAN_STALE_S` is for.
    """
    outcome = ""
    for record in records:
        if record.get("event") == MISSION_FINISHED:
            outcome = str(record.get("outcome") or "")
    return outcome


def open_for_resume(store: Optional[RunStore], run_id: str, *,
                    objective: str = "", protocol: str = "") -> Recorded:
    """Admit *run_id* for resuming, or refuse and say which rule it broke.

    Every check here happens before a server is dialled and before a model
    is asked, for the reason ``--skill`` and ``--history`` are validated at
    the door: a refusal that arrives at the end of an 11,000-second mission
    is a refusal that cost what it was meant to save.

    The objective check is the one worth reading twice.  A resume that
    silently accepted a different objective would run the *recorded* one
    while the operator watched for the one they typed, and nothing on the
    stream or the console would look wrong — so a mismatch is refused
    naming both strings, and an omitted objective is filled in from the
    record rather than guessed at.
    """
    if store is None:
        raise ResumeRefused(
            "there is no run store to resume from: persistence is turned "
            "off (JUDAIS_LOBI_RUNS=none|off), so no mission left a "
            "transcript. Unset it, or point it at the directory the "
            "recorded run is in.")
    try:
        meta = store.meta(run_id)
        records = store.records(run_id)
    except NoSuchRun:
        raise ResumeRefused(
            f"no run {run_id!r} under {store.root}. Run ids are minted by "
            f"the store and printed when a mission starts; they also ride "
            f"the opening frame as `mission_started.run_id`.") from None

    opening = [r for r in records if r.get("event") == MISSION_STARTED]
    if not opening:
        raise ResumeRefused(
            f"run {run_id} never got as far as opening — its log holds no "
            f"`mission_started`, so there is no objective, no catalogue and "
            f"no step to continue from. Start a fresh mission.")

    outcome = recorded_outcome(records)
    if outcome not in RESUMABLE_OUTCOMES:
        raise ResumeRefused(
            f"run {run_id} has already finished: it ended in "
            f"{outcome!r}. A concluded run is a record, not a mission in "
            f"progress. The outcomes that can be picked back up are "
            f"{', '.join(repr(o) for o in RESUMABLE_OUTCOMES if o)} and a "
            f"log with no `mission_finished` at all.")

    # A staged run is admitted on its CHECKPOINT and not on its stream. The
    # plan rides one `step_started`, so a turn killed before its first step
    # emitted no plan at all — while `_staged` wrote the checkpoint before
    # asking for that step. What is refused is only what cannot be rebuilt:
    # a run that says it was staged and does not say what the plan was.
    staged, plan, steps_done = _checkpointed_plan(meta)
    if staged and not plan:
        raise ResumeRefused(
            f"run {run_id} was a staged (--swarm) mission and its plan is "
            f"not in meta.json, so there is nothing to continue with: the "
            f"steps it had left are unknown, and asking the planner again "
            f"would put a different mission under this run's id. Steps "
            f"done: {_steps_done_sentence(meta)}. Start a fresh mission.")

    # Read before the objective check and refused beside it, because it is
    # the same class of mistake: a resume that ran the recorded mission in
    # a protocol it was not recorded in looks exactly like a run
    # continuing, right up to the point where the model is handed turns it
    # cannot have written. Unstated on the command line means "whatever the
    # run was", which is why `--protocol` defaults to empty rather than to
    # `json` — a flag that cannot tell "nobody said" from "somebody said
    # json" would silently refuse every native resume.
    recorded_protocol = str(opening[-1].get("protocol") or JSON_PROTOCOL)
    asked = (protocol or "").strip()
    if asked and asked != recorded_protocol:
        raise ResumeRefused(
            f"run {run_id} was recorded under --protocol "
            f"{recorded_protocol} and this command says {asked}. The "
            f"replay rebuilds the model's own turns in the shape they were "
            f"made in, so the two have to match: pass --protocol "
            f"{recorded_protocol}, or omit it and the run supplies it.")

    recorded_objective = str(opening[-1].get("objective") or "")
    wanted = (objective or "").strip()
    if wanted and wanted != recorded_objective:
        raise ResumeRefused(
            f"run {run_id} is not that mission. It was started with "
            f"{recorded_objective!r} and this command says {wanted!r}. "
            f"Resuming would run the recorded objective while you watched "
            f"for yours, and nothing on the stream would look wrong — so "
            f"pass the recorded objective, or omit it and the run supplies "
            f"it.")

    return Recorded(
        run_id=run_id,
        objective=recorded_objective,
        meta=meta,
        records=records,
        from_seq=int(meta.last_seq),
        max_steps=int(opening[-1].get("max_steps") or 0),
        outcome=outcome,
        protocol=recorded_protocol,
        staged=staged,
        plan=plan,
        steps_done=steps_done,
        replanned=bool(meta.meta.get("replanned")),
    )


def _checkpointed_plan(meta: Run):
    """``(staged, plan, steps_done)`` off a run's metadata.

    A run is staged when it carries *either* half of the checkpoint
    :meth:`core.runtime.swarm.SwarmRunner._checkpoint` writes, because the
    two are written together and a run holding one of them is a run whose
    store took half a write.  Reading only ``plan`` would call that run
    direct and hand it to the ordinary loop, which is the half-continued
    resume this whole path exists to refuse.
    """
    plan = meta.meta.get("plan")
    done = meta.meta.get("steps_done")
    staged = plan is not None or done is not None
    steps = [dict(entry) for entry in plan
             if isinstance(entry, Mapping) and entry.get("id")] \
        if isinstance(plan, list) else []
    outcomes = [dict(entry) for entry in done
                if isinstance(entry, Mapping) and entry.get("id")] \
        if isinstance(done, list) else []
    return staged, steps, outcomes


def _steps_done_sentence(meta: Run) -> str:
    """The swarm's checkpoint as one line, for the refusal above.

    Shown when a staged run cannot be continued, because "what was already
    done" is the half an operator deciding what to do next actually needs
    — a refusal that says only *no* leaves them to read a JSONL by hand.
    """
    done = meta.meta.get("steps_done") or []
    if not isinstance(done, list) or not done:
        return "(none recorded)"
    parts = []
    for entry in done:
        if not isinstance(entry, dict):
            continue
        summary = str(entry.get("summary") or "").strip()
        parts.append(f"{entry.get('id', '?')} {entry.get('outcome', '?')}"
                     + (f" — {summary}" if summary else ""))
    return "; ".join(parts) or "(none recorded)"


# ── the replay ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _Result:
    """The three fields ``_render_result`` reads off a dispatch result.

    Not a ``ToolResult``: the bus's shape is the bus's, and a replay is not
    a dispatch.  What it has to be is *whatever the renderer reads*, which
    is these three attributes and nothing else.
    """

    exit_code: int
    stdout: str
    stderr: str


def resumed_record(from_seq: int, steps_replayed: int) -> Dict[str, Any]:
    """The ``resumed`` field of the first ``step_started`` after a resume.

    ``from_seq`` is where the earlier half of this run's log ends, so a
    consumer that joined late can fetch it; ``steps_replayed`` is how many
    steps precede the one it is about to render, so the ``index`` on that
    record — which continues the earlier numbering rather than starting
    again — is not read as a gap.

    One function and not a method apiece, because a direct resume and a
    staged one produce the same record for the same reason, and a second
    hand-listing of a contract-declared shape is the arrangement that let
    the swarm emit six of the ``grounding`` record's ten fields.
    """
    return {"from_seq": int(from_seq), "steps_replayed": int(steps_replayed)}


@dataclass
class Resumption:
    """A recorded run, back in the shapes the loop carries between steps.

    Handed to :meth:`core.runtime.mission.MissionRunner.run` as its
    ``resumption``.  Everything on it is what that method would otherwise
    have built for itself on step zero.
    """

    run_id: str
    objective: str
    from_seq: int
    #: The transcript's steps, oldest first.
    steps: List[MissionStep] = field(default_factory=list)
    #: The mission result store, re-recorded from the log.  The runner
    #: **adopts** this object rather than copying out of it, so the handles
    #: the model was given (``r1``, ``r2``) still address the same results.
    store: MissionResultStore = field(default_factory=MissionResultStore)
    #: Everything the loop appended to :meth:`~MissionRunner.seed`'s list,
    #: in order.  The seed itself is rebuilt by the runner, because it is a
    #: function of the persona, the catalogue and the history — all of
    #: which belong to the resuming process and not to the log.
    tail: List[Dict[str, str]] = field(default_factory=list)
    #: The index the resumed loop starts at.
    next_index: int = 0
    #: The grounding repair turns already spent, so a resumed run cannot
    #: buy itself a fresh allowance of them.
    repairs: int = 0
    #: ``{tool, arguments, reason}`` when the run stopped at a gate.
    gate: Optional[Dict[str, Any]] = None
    #: What the stream could not give back, in sentences.  See the
    #: ``LOST_*`` constants: this is shown to an operator, not swallowed.
    lost: List[str] = field(default_factory=list)

    @property
    def steps_replayed(self) -> int:
        return len(self.steps)

    def as_record(self) -> Dict[str, Any]:
        """The ``resumed`` field of the first ``step_started`` after this."""
        return resumed_record(self.from_seq, self.steps_replayed)


@dataclass
class StagedResumption:
    """A staged run's checkpoint, back in the shapes the swarm carries.

    Handed to :meth:`core.runtime.swarm.SwarmRunner.run` as its
    ``resumption``, and it is a much smaller thing than :class:`Resumption`
    on purpose: **a staged step has no conversation to give back.**  Each
    step of a plan runs in its own small
    :class:`~core.runtime.mission.MissionRunner` with its own seed, and what
    travels between steps is a *summary* rather than a transcript — which is
    the whole design of :mod:`core.runtime.swarm`.  So there is no message
    tail here, and its absence is not a loss: the resumed steps read exactly
    what they would have read had the process never died.

    What is here is what the plan carries: the plan itself, the settled
    steps' summaries, the evidence the grounding validator will check the
    synthesized answer against, and the numbers that keep one run one run.
    """

    run_id: str
    objective: str
    from_seq: int
    #: The checkpointed plan, every field of every step.
    plan: List[Dict[str, Any]] = field(default_factory=list)
    #: The checkpointed step outcomes, in the order they were reached.
    steps_done: List[Dict[str, Any]] = field(default_factory=list)
    #: The results the recorded stretch's tools returned, re-recorded from
    #: the event log.  The swarm does not adopt this store — each
    #: sub-mission keeps its own — but it is the one owner of *what was
    #: called* and *what came back*, so the evidence and the plane-claim
    #: set below are read off it rather than derived a second time.
    store: MissionResultStore = field(default_factory=MissionResultStore)
    #: The global step index the resumed stretch starts numbering at.
    next_index: int = 0
    #: How many tool turns the recorded stretch spent, against the run's
    #: ``max_steps`` total.
    steps_spent: int = 0
    #: Whether the run has already spent its one plan redraw.
    replanned: bool = False
    #: What the stream could not give back, in sentences.
    lost: List[str] = field(default_factory=list)

    @property
    def evidence(self) -> List[str]:
        """What the grounding validator checks the answer against."""
        return self.store.evidence_texts()

    @property
    def called(self) -> List[str]:
        """Every tool the recorded stretch dispatched, once each."""
        return self.store.called_tools()

    @property
    def steps_replayed(self) -> int:
        return self.steps_spent

    def as_record(self) -> Dict[str, Any]:
        """The ``resumed`` field of the first ``step_started`` after this."""
        return resumed_record(self.from_seq, self.steps_replayed)


def rebuild(runner: Any, recorded: Recorded) -> Resumption:
    """The recorded stream, read back into the loop's own state.

    *runner* is the :class:`~core.runtime.mission.MissionRunner` that is
    about to continue the run, and it is passed for exactly one reason: the
    text a tool result takes in the conversation is
    :meth:`~core.runtime.mission.MissionRunner._render_result`'s to write.
    That method reads the bound and the store's tool name off the runner
    and touches nothing else, so calling it here is a *use* of the one
    owner rather than a reach into its state.  The alternative — rendering
    a replayed result in this module — is the arrangement that let the
    swarm hand-list six grounding fields where the direct path emitted ten.

    The model's own replies are the part that has to be reconstructed
    rather than read.  They were never on the stream: the contract carries
    what the loop *did* with a reply, not the reply.  A reply that named a
    tool comes back as the canonical
    ``{"tool": …, "arguments": …}`` of the ``tool_call`` record, which is
    the same decision in a possibly different spelling — a model that
    fenced its JSON or ordered its keys differently gets its own turn back
    tidied.  A reply that did **not** parse cannot come back at all, and
    that is not an oversight: it is the one text the contract deliberately
    does not carry.
    """
    if recorded.staged:
        # *runner* is not used, and that is the fact worth reading: a
        # staged rebuild renders no conversation, because a staged step's
        # conversation is its own sub-mission's and is built fresh. The
        # parameter stays in the signature so one call site serves both
        # kinds of run — see `StagedResumption`.
        return _rebuild_staged(recorded)
    resumption = Resumption(run_id=recorded.run_id,
                            objective=recorded.objective,
                            from_seq=recorded.from_seq)
    if recorded.protocol == NATIVE_PROTOCOL:
        return _rebuild_native(runner, recorded, resumption)
    store = resumption.store
    tail = resumption.tail

    index = 0
    rejected = 0
    repaired = 0
    scrubbed = 0
    pending_reply = ""

    for record in recorded.records:
        event = record.get("event")

        if event == STEP_STARTED:
            index = int(record.get("index", 0))
            pending_reply = ""

        elif event == REPLY_REJECTED:
            rejected += 1
            # Empty, and deliberately not a guess. See the module docstring
            # and LOST_REJECTED_REPLY: the alternative is a turn attributed
            # to the model that the model did not write.
            tail.append({"role": "assistant", "content": ""})
            tail.append({"role": "user",
                         "content": str(record.get("problem") or "")})
            step = MissionStep(index=index, raw_reply="",
                               error=str(record.get("problem") or ""))
            if record.get("tool"):
                step.tool = str(record["tool"])
            resumption.steps.append(step)

        elif event == TOOL_CALL:
            pending_reply = _reply_for(record)
            tail.append({"role": "assistant", "content": pending_reply})

        elif event == TOOL_RESULT:
            (name, arguments, exit_code, output, error, stored, rendered,
             truncated) = _replay_result(runner, store, record)
            if error:
                scrubbed += 1
            tail.append({"role": "user", "content": rendered})
            resumption.steps.append(MissionStep(
                index=index, raw_reply=pending_reply, tool=name,
                arguments=arguments, exit_code=exit_code, output=output,
                error=error, handle=stored.handle, truncated=truncated,
            ))
            if stored.handle != str(record.get("handle") or stored.handle):
                resumption.lost.append(
                    f"handle {record.get('handle')!r} was re-minted as "
                    f"{stored.handle!r}: the recorded results do not number "
                    f"the way this store does, so a handle the model was "
                    f"given earlier now addresses a different result")
            pending_reply = ""

        elif event == GATE_REQUESTED:
            name = str(record.get("tool") or "")
            arguments = dict(record.get("arguments") or {})
            reason = str(record.get("reason") or "")
            tail.append({"role": "assistant", "content": _reply_for(record)})
            # The live loop returned here and never wrote a user turn. The
            # reason is put back as one because it is true, it is on the
            # wire, and a conversation handed to a model ending on the
            # model's own turn is a conversation with nothing to answer.
            tail.append({"role": "user", "content": reason})
            resumption.steps.append(MissionStep(
                index=index, raw_reply=_reply_for(record), tool=name,
                arguments=arguments, error=reason,
            ))
            resumption.gate = {"tool": name, "arguments": arguments,
                               "reason": reason}

        elif event == GROUNDING:
            resumption.repairs = max(resumption.repairs,
                                     int(record.get("repairs") or 0))
            if record.get("repairing"):
                repaired += 1
                resumption.steps.append(MissionStep(index=index,
                                                    raw_reply=""))

        elif event == ANSWER:
            # Only reachable on a log the door let through, which means a
            # gated run whose earlier stretch somehow answered. Recorded as
            # a loss rather than dropped in silence.
            resumption.lost.append(
                "an `answer` record in a run that was not finished: the "
                "answer text is replayed as the model's own turn is not, "
                "and the resumed loop starts from the step after it")

    resumption.next_index = recorded.spent_steps
    if store.results:
        resumption.lost.append(LOST_STRUCTURED)
    if rejected:
        resumption.lost.append(LOST_REJECTED_REPLY.format(
            n=rejected, y="y" if rejected == 1 else "ies"))
    if repaired:
        resumption.lost.append(LOST_REPAIR_TURN.format(
            n=repaired, s="" if repaired == 1 else "s"))
    if scrubbed:
        resumption.lost.append(LOST_SCRUBBED.format(
            n=scrubbed, s="" if scrubbed == 1 else "s"))
    return resumption


def _rebuild_staged(recorded: Recorded) -> StagedResumption:
    """A staged run's checkpoint and stream, back into the swarm's state.

    Two sources, each for what it owns.  The **checkpoint** owns the plan
    and the settled steps: those are decisions the staged runner made and
    wrote down, and no amount of reading the stream back recovers a
    ``done`` condition or a step's bounded summary.  The **stream** owns
    what the tools returned, because the checkpoint never held it — so the
    results are re-recorded here into a
    :class:`~core.runtime.results.MissionResultStore`, which is then the
    one owner of both the grounding evidence and the plane-claim set, the
    same as it is on a live turn.

    The store is re-recorded rather than the evidence being collected into
    a list here, and that is not ceremony: ``evidence_texts`` reads a
    failed result differently from a successful one — its typed error
    payload and its arguments, never its free text — and ``called_tools``
    does not read it differently at all, and a second reading of the log
    beside them would be a second answer to the two questions the live
    path already has one answer each for.
    """
    store = MissionResultStore()
    for record in recorded.records:
        if record.get("event") != TOOL_RESULT:
            continue
        store.record(
            str(record.get("tool") or ""),
            dict(record.get("arguments") or {}),
            text=str(record.get("output") or ""),
            # Empty for `LOST_STRUCTURED`'s reason: the typed payload never
            # travelled on the event stream.
            evidence="",
            exit_code=int(record.get("exit_code") or 0),
        )
    resumption = StagedResumption(
        run_id=recorded.run_id,
        objective=recorded.objective,
        from_seq=recorded.from_seq,
        plan=[dict(step) for step in recorded.plan],
        steps_done=[dict(entry) for entry in recorded.steps_done],
        store=store,
        # The same number for both, and it is the log's: every tool turn a
        # sub-mission spent emitted one `step_started` under the global
        # numbering `_StageObserver` gave it, so the high-water mark is at
        # once what was spent and where the next one starts.
        next_index=recorded.spent_steps,
        steps_spent=recorded.spent_steps,
        replanned=recorded.replanned,
    )
    settled = sum(1 for entry in resumption.steps_done
                  if str(entry.get("outcome") or "") in ("ok", "failed"))
    if store.results:
        resumption.lost.append(LOST_STAGED_EVIDENCE.format(
            n=settled, s="" if settled == 1 else "s"))
    return resumption


def _replay_result(runner: Any, store: MissionResultStore,
                   record: Mapping[str, Any]):
    """One recorded ``tool_result`` back into the store, rendered as the
    loop rendered it.

    Shared by both protocols' rebuilds so there is one answer to "what does
    a replayed result look like": the store is re-recorded in the same
    order, which is what keeps the handles (``r1``, ``r2``) addressing the
    same results, and the text goes through the runner's own
    ``_render_result``.  A second copy of this in the native rebuild would
    be a second owner of the transcript the resumed model reads.

    Returns ``(name, arguments, exit_code, output, error, stored,
    rendered, truncated)``.
    """
    name = str(record.get("tool") or "")
    arguments = dict(record.get("arguments") or {})
    output = str(record.get("output") or "")
    error = str(record.get("error") or "")
    exit_code = int(record.get("exit_code") or 0)
    # `evidence` is empty because it never travelled: see LOST_STRUCTURED.
    # Everything else is on the record.
    stored = store.record(name, arguments, text=output, evidence="",
                          exit_code=exit_code)
    result = _Result(exit_code=exit_code, stdout=output, stderr=error)
    rendered, truncated = runner._render_result(
        name, result, stored.handle, already=store.first_identical(stored),
    )
    return (name, arguments, exit_code, output, error, stored, rendered,
            truncated)


def _rebuild_native(runner: Any, recorded: Recorded,
                    resumption: Resumption) -> Resumption:
    """The same replay, in the shape a native turn takes.

    The difference is not cosmetic.  A JSON turn is one assistant message
    of text answered by one user message; a native turn is one assistant
    message carrying **every** call it made, followed by one ``tool``
    message per call quoting that call's id.  A server will refuse the
    conversation if either half is missing — an unanswered ``tool_calls``
    or a ``tool`` message answering nothing — so the records of one step
    are buffered and flushed together rather than appended as they arrive.

    The ids are minted here.  A ``tool_call_id`` is the provider's and
    never travelled on the event stream (the contract carries what
    happened, not what the wire looked like), so the rebuilt turns quote
    ids this process invented.  They are internally consistent, which is
    what the server checks, and the loss is recorded in
    :attr:`Resumption.lost` rather than passed off as a faithful replay.

    A gate is closed off the same way: the recorded ``reason`` becomes the
    ``tool`` message answering the proposed call, so the conversation the
    resumed loop sends does not end on an unanswered call.
    """
    store = resumption.store
    tail = resumption.tail

    index = 0
    minted = 0
    rejected = 0
    repaired = 0
    scrubbed = 0
    # One step's worth: the calls the model made, the message answering
    # each, and any turn-level correction that has to follow them.
    calls: List[Dict[str, Any]] = []
    answers: List[str] = []
    notes: List[str] = []
    step_calls: List[MissionCall] = []

    def flush() -> None:
        nonlocal calls, answers, notes, step_calls
        if calls:
            # Through the loop's own owner of that shape — see
            # `core.runtime.messages.assistant_turn`. A rebuilt turn and a
            # live one are the same bytes, including whatever opaque field
            # a provider requires back on a call, for any caller that can
            # still supply one; this replay cannot, and says so in
            # `LOST_NATIVE_IDS`.
            tail.append(assistant_turn("", calls))
            for call, answer in zip(calls, answers):
                tail.append({"role": "tool", "tool_call_id": call["id"],
                             "content": answer})
            resumption.steps.append(MissionStep(
                index=index, raw_reply="", calls=list(step_calls)))
            # A correction that belonged to a call this replay could not
            # reconstruct — see LOST_REJECTED_REPLY — comes back as a user
            # turn after the results rather than as a tool message
            # answering nothing.
            for note in notes:
                tail.append({"role": "user", "content": note})
        else:
            for note in notes:
                tail.append({"role": "assistant", "content": ""})
                tail.append({"role": "user", "content": note})
                resumption.steps.append(
                    MissionStep(index=index, raw_reply="", error=note))
        calls, answers, notes, step_calls = [], [], [], []

    for record in recorded.records:
        event = record.get("event")

        if event == STEP_STARTED:
            flush()
            index = int(record.get("index", 0))

        elif event == REPLY_REJECTED:
            rejected += 1
            notes.append(str(record.get("problem") or ""))

        elif event == TOOL_CALL:
            minted += 1
            calls.append({"id": f"resumed_{index}_{len(calls)}",
                          "tool": str(record.get("tool") or ""),
                          "arguments": dict(record.get("arguments") or {})})

        elif event == TOOL_RESULT:
            if not calls:
                continue
            (name, arguments, exit_code, output, error, stored, rendered,
             truncated) = _replay_result(runner, store, record)
            if error:
                scrubbed += 1
            answers.append(rendered)
            step_calls.append(MissionCall(
                tool=name, arguments=arguments, call_id=calls[-1]["id"],
                ordinal=len(step_calls), exit_code=exit_code, output=output,
                error=error, handle=stored.handle, truncated=truncated))
            if stored.handle != str(record.get("handle") or stored.handle):
                resumption.lost.append(
                    f"handle {record.get('handle')!r} was re-minted as "
                    f"{stored.handle!r}: the recorded results do not number "
                    f"the way this store does, so a handle the model was "
                    f"given earlier now addresses a different result")

        elif event == GATE_REQUESTED:
            minted += 1
            name = str(record.get("tool") or "")
            arguments = dict(record.get("arguments") or {})
            reason = str(record.get("reason") or "")
            calls.append({"id": f"resumed_{index}_{len(calls)}",
                          "tool": name, "arguments": arguments})
            # The live loop returned here and answered nothing. The reason
            # is put back as this call's result because it is true, it is
            # on the wire, and a declared call with no answer is a request
            # a server refuses outright.
            answers.append(reason)
            step_calls.append(MissionCall(
                tool=name, arguments=arguments, call_id=calls[-1]["id"],
                ordinal=len(step_calls), error=reason))
            resumption.gate ={"tool": name, "arguments": arguments,
                               "reason": reason}

        elif event == GROUNDING:
            resumption.repairs = max(resumption.repairs,
                                     int(record.get("repairs") or 0))
            if record.get("repairing"):
                repaired += 1
                # A repair turn spent a step and left no call behind it, so
                # it is counted here exactly as the JSON rebuild counts it:
                # the budget was spent whether or not the two messages can
                # come back. See LOST_REPAIR_TURN.
                resumption.steps.append(MissionStep(index=index,
                                                    raw_reply=""))

        elif event == ANSWER:
            resumption.lost.append(
                "an `answer` record in a run that was not finished: the "
                "answer text is replayed as the model's own turn is not, "
                "and the resumed loop starts from the step after it")

    flush()
    resumption.next_index = recorded.spent_steps
    if store.results:
        resumption.lost.append(LOST_STRUCTURED)
    if minted:
        resumption.lost.append(LOST_NATIVE_IDS.format(
            n=minted, s="" if minted == 1 else "s"))
    if rejected:
        resumption.lost.append(LOST_REJECTED_REPLY.format(
            n=rejected, y="y" if rejected == 1 else "ies"))
    if repaired:
        resumption.lost.append(LOST_REPAIR_TURN.format(
            n=repaired, s="" if repaired == 1 else "s"))
    if scrubbed:
        resumption.lost.append(LOST_SCRUBBED.format(
            n=scrubbed, s="" if scrubbed == 1 else "s"))
    return resumption


def _reply_for(record: Mapping[str, Any]) -> str:
    """The model's reply, as the loop's own protocol spells it.

    ``json.dumps`` with the two keys in the order :data:`PROTOCOL
    <core.runtime.mission.PROTOCOL>` states them, because this string is
    read back by the same model on the next turn and a reply in the shape
    the protocol asked for is the one worth teaching by example.
    """
    return json.dumps({"tool": str(record.get("tool") or ""),
                       "arguments": dict(record.get("arguments") or {})},
                      ensure_ascii=False)


# ── reconciliation ───────────────────────────────────────────────────────────


def reconcile_orphans(store: Optional[RunStore], *, live: str = "",
                      stale_s: Optional[float] = None,
                      at: Optional[datetime] = None) -> List[str]:
    """Close the logs of runs nobody is going to close.  Returns their ids.

    A run whose log has no ``mission_finished`` is one of two things, and
    the log cannot tell them apart: a mission that died — the machine went
    down, somebody killed the process, the pipe it was writing to broke —
    or a mission that is *running right now* in another process.  The first
    leaves a follower waiting on a stream that will never say another word,
    which is exactly the spinner-forever state ``EXIT_CONTRACT["finished"]``
    exists to prevent.  The second must not be touched at all.

    **The question is put to the kernel.**  A run being run is a run being
    held (:meth:`core.durable.RunStore.hold`), and a held run is skipped
    however long it has been quiet.  An orphan is a run whose lock is
    **free** and whose log has no ending.  That is the whole rule where
    ``flock`` exists, and it is the only formulation that cannot be wrong
    about a run that is legitimately silent: a gate waiting up to
    :data:`~core.runtime.control.GATE_WAIT_S` for a person, a cold model
    on its first token, a sandboxed tool halfway through a build.

    The clock stays for two jobs and neither of them is deciding.  Where a
    run has been claimed (:meth:`core.durable.RunStore.claimed` — it has a
    lock file, so whatever ran it takes locks) the clock is a cheap first
    filter and :data:`ORPHAN_STALE_S` is enough: a free lock on such a run
    settles it.  Where a run has **not** been claimed — an older release
    wrote it, or a library caller holding its own store — there is nothing
    to read, so the clock is the whole rule and :func:`orphan_window`
    widens it past the longest silence a live run is entitled to.  Same on
    a platform with no ``flock`` at all.  A :class:`~core.durable.RunHold`
    also touches ``updated_at`` every :data:`~core.durable.HEARTBEAT_S`, so
    even the wide window sees a held run as fresh.

    *stale_s* ``None`` is that whole arrangement; a number is the caller's
    own and is used as typed for both kinds of run — see
    :func:`orphan_window`.

    *live* — the run this process is about to work on — is excluded
    outright rather than left to either mechanism.

    **This was a live bug.**  Before the lock, liveness was "the metadata
    moved in the last sixty seconds", and a run standing at a gate was
    closed by the next ``judais --mission`` to start in the same runs root:
    its pending approval was abandoned, and when the decision arrived it
    appended a second ``mission_finished`` with a different outcome onto a
    log a follower had already been told was over.  The second half of that
    is prevented independently, by the store: see
    :class:`~core.durable.RunClosed`.

    What is appended is a ``mission_finished`` with the transcript's own
    default outcome, :data:`ORPHAN_OUTCOME`, and the counts read off the
    log: ``steps`` is how many ``step_started`` records it holds and
    ``max_steps`` is what its opening frame said.  No reason field and no
    new event — this is the ending the run already had, written down by
    somebody else, and a consumer that has to learn a word to read it would
    be learning one about *this function* rather than about the mission.
    That the reconciliation happened is a fact about the run and not about
    the mission, so it goes in the metadata as ``orphaned_at``.

    Never raises: a run directory that cannot be read is skipped, for the
    same reason :meth:`RunStore.list` skips one — reconciling ninety-nine
    runs and failing on the hundredth is worth more than failing on all of
    them.
    """
    if store is None:
        return []
    stamp = (at or datetime.now(timezone.utc)).timestamp()
    claimed_window = orphan_window(stale_s, locks=True)
    unclaimed_window = orphan_window(stale_s, locks=False)
    closed: List[str] = []
    for run in store.list():
        if run.run_id == live:
            continue
        try:
            # Which clock this run is read by depends on whether anybody
            # ever claimed it. A run with a lock file was run by a process
            # that takes locks, so a FREE lock means that process is gone
            # and the short window is enough. A run without one was written
            # by somebody who never said whether it was alive — an older
            # release, a library caller holding its own store — and it gets
            # the wide window, which is never shorter than the longest
            # silence a live run is entitled to.
            claimed = LOCKS and store.claimed(run.run_id)
            window = claimed_window if claimed else unclaimed_window
            if _updated_at(run) > stamp - window:
                continue
            # The lock, last of the cheap checks and first in authority:
            # a held run is being run, whatever its clock says.
            if store.held(run.run_id):
                continue
            records = store.records(run.run_id)
            if recorded_outcome(records):
                continue
            store.append(run.run_id, {
                "event": MISSION_FINISHED,
                "outcome": ORPHAN_OUTCOME,
                "steps": sum(1 for r in records
                             if r.get("event") == STEP_STARTED),
                "max_steps": _opening_max_steps(records),
            })
            store.update_meta(run.run_id, orphaned_at=now())
        except Exception:                       # pragma: no cover - defensive
            continue
        closed.append(run.run_id)
    return closed


def _updated_at(run: Run) -> float:
    """*run*'s ``updated_at`` as a POSIX timestamp, or ``inf``.

    ``inf`` for a stamp that will not parse, so an unreadable clock reads
    as "too recent to touch".  Fail closed: appending a terminal record to
    a mission that is still going is the mistake worth not making, and the
    cost of the other one is a directory that stays open until somebody
    looks.
    """
    try:
        stamp = datetime.fromisoformat(str(run.updated_at))
    except (TypeError, ValueError):
        return float("inf")
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.timestamp()


def _opening_max_steps(records: Sequence[Mapping[str, Any]]) -> int:
    for record in records:
        if record.get("event") == MISSION_STARTED:
            return int(record.get("max_steps") or 0)
    return 0
