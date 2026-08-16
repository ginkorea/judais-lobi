# core/runtime/approvals.py — the other half of a gate: the decision, written down

"""A gate is only half a mechanism until the yes is a record somebody wrote.

:mod:`core.runtime.mission` has had the **ask** since 0.7: ``--gate-tool``
names a tool the model may propose and the loop may not call, naming it ends
the run at :data:`~core.runtime.mission.AWAITING_APPROVAL`, and the proposed
arguments travel verbatim on ``gate_requested`` because what a person approves
has to be the bytes that would run.  What there was no half of is the answer.
The mission ended, the process exited, and the request lived in whatever the
consumer happened to keep — which is to say, in a socket, in a tab, in the
memory of the program that spawned us.  An approval that dies with a socket
gets re-asked, or worse, defaulted.

So this module makes the request a **file**, addressed by its own id, and the
decision an ordinary write from outside the run.

**The rule, in one line: there is no code path by which the agent's own
output causes an approval to pass.**  :meth:`ApprovalStore.request` writes a
record and returns; :meth:`ApprovalStore.decide` is the only way to
:data:`APPROVED`, it is never called from :mod:`core.runtime.mission` or
:mod:`core.runtime.swarm` (there is a test that greps for it), and it refuses
a decision that does not name a decider.

**Who the decider is, is the platform's question and not this framework's.**
There is no principal system here — no identity, no delegation, no
"is this caller a person" check, because a framework that invented one would
be inventing the platform's answer.  ``decided_by`` is a free string the
caller supplies, the platform fills it with whatever its own identity layer
calls the human who clicked, and the *only* thing core enforces is that the
string is not empty: a decision nobody signed is not a decision.  The
reference platform's version of this file (TAIPAN's ``mission/approvals.py``)
adds ``must_be_a_person`` on top of exactly this mechanism, and that is the
right place for it.

**Nothing defaults, and nothing expires into a yes.**  An undecided request
stays undecided.  There is no timeout that approves, no "proceed unless
refused", and :meth:`ApprovalStore.reconcile` — which a restart runs over
requests whose run is gone — resolves them as :data:`ABANDONED`, which is a
**refusal**.  Named separately from :data:`REFUSED` so an operator can tell
"somebody said no" from "nobody was asked", which are different facts.

**Answered once, and spent once.**  An approval widens a run's closed tool set
by exactly one tool, for exactly one run, after exactly one person said so.
:class:`ApprovalTicket` is that widening, resolved once at the door and spent
(:meth:`~ApprovalTicket.spend`) at the moment the approved tool is actually
dispatched — see :func:`resolve` for why dispatch and not run start.  A record
that a second run could pick up again would be a standing permission, and
there is no state anywhere here that says "this operator approves deletions".

**Where the files go.**  ``.judais-lobi/approvals/<id>.json`` under the current
directory, one file each, written through a temporary file and
:func:`os.replace` so a reader never sees half of one.
``JUDAIS_LOBI_APPROVALS`` moves the directory (a path) or turns persistence off
(``none``/``off``) — the same two conventions, and the same "explicitly, and
announced" rule, as :mod:`core.policy.audit`.  Off is a decision somebody
made: a deployment that gates a tool and keeps no record of the request has
made a gate nobody can answer, and the console says so rather than leaving it
to be discovered.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

from core.redact import scrub_secrets

__all__ = [
    "PENDING", "APPROVED", "REFUSED", "SPENT", "ABANDONED", "STATES",
    "RESOLVED", "APPROVALS_ENV", "APPROVALS_DIRNAME", "DISABLE_WORDS",
    "WHY_GATED",
    "Approval", "ApprovalStore", "ApprovalTicket", "resolve",
    "approvals_root", "default_approval_store",
    "ApprovalError", "NoSuchApproval", "AlreadyDecided", "AlreadySpent",
    "NotApproved", "NoDecider",
]


#: Nobody has answered.  The only state a request is born in.
PENDING = "pending"
#: A person said yes.  Reachable from :meth:`ApprovalStore.decide` and from
#: nowhere else in this repository.
APPROVED = "approved"
#: A person said no.
REFUSED = "refused"
#: An approval that has been carried into a dispatch.  Terminal, and *not* a
#: second yes: the widening it bought has been used.
SPENT = "spent"
#: The run that asked is gone — a restart, a killed process.  **A refusal.**
ABANDONED = "abandoned"

STATES: tuple = (PENDING, APPROVED, REFUSED, SPENT, ABANDONED)

#: Everything that is not still waiting.  Note that only :data:`APPROVED` lets
#: a tool be called, and that :data:`SPENT` is in here too: a decision already
#: carried into a run is as finished as one that was refused.
RESOLVED: frozenset = frozenset({APPROVED, REFUSED, SPENT, ABANDONED})

#: The variable a deployment moves or silences the approval store with.
APPROVALS_ENV = "JUDAIS_LOBI_APPROVALS"

#: Where the default directory lives, relative to the current directory.
APPROVALS_DIRNAME = Path(".judais-lobi") / "approvals"

#: The two words that mean "keep no durable record", case-insensitively.
#: Spelled the same as :data:`core.policy.audit.DISABLE_WORDS`, because an
#: operator who has learned one of this framework's off switches has learned
#: all of them.
DISABLE_WORDS = frozenset({"none", "off"})

#: What every request says about itself, for whoever is being asked.
WHY_GATED = (
    "The agent REQUESTED this. It has not happened and will not happen "
    "unless somebody decides it. Nothing here times out into a yes."
)

_ID_PREFIX = "ap_"


class ApprovalError(Exception):
    """Anything this module refuses.  One base, so a caller can catch it."""


class NoSuchApproval(ApprovalError, KeyError):
    """No record by that id, or an id that is not a name this store writes."""

    def __str__(self) -> str:                    # KeyError repr()s its args
        return self.args[0] if self.args else ""


class AlreadyDecided(ApprovalError, ValueError):
    """A second decision on a resolved request.  Refused, never overwritten."""


class AlreadySpent(ApprovalError, ValueError):
    """This decision has already been carried into a dispatch.

    An approval widens the closed set by one tool for one run, so a record a
    second run could pick up again would be a standing permission.
    """


class NotApproved(ApprovalError, PermissionError):
    """A run was handed a record that is not an approval, and stopped.

    Pending, refused, spent and abandoned are all this, and the message names
    which: nothing defaults into a yes, and a run that quietly treated an
    unanswered request as one would be the whole failure this module exists
    to prevent.
    """


class NoDecider(ApprovalError, ValueError):
    """A decision that names nobody.  A decision is signed or it is not one."""


def _now() -> str:
    """An ISO-8601 UTC stamp, to the second.

    Second resolution and not microseconds because the only thing anything
    reads these for is human ordering and "when was this answered", and a
    record a person is going to be shown should not need a lens.
    """
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    """Write *payload* to *path* so a reader never sees half of it.

    Temporary file in the destination directory, flushed, ``fsync``'d, then
    :func:`os.replace` — which is atomic within a filesystem, and the
    temporary file is a sibling so it always is one.

    LOCAL ON PURPOSE, AND MEANT TO BE DELETED.  The durable-store work is
    adding ``core.durable.atomic_write_json`` with exactly this body and a
    great deal more (append-only JSONL with per-record ``fsync``, a run
    store, monotonic sequence numbers).  This function exists so that this
    module does not have to wait for that one; when both are on the same
    branch, this is the call site to point at ``core.durable``, and there
    should be no second copy of the arithmetic left behind.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "w", dir=str(path.parent), prefix=".tmp-", suffix=".json",
        delete=False, encoding="utf-8")
    try:
        with handle:
            json.dump(dict(payload), handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(handle.name, path)
    except BaseException:
        # A staged file nobody replaced is litter, and litter in an approvals
        # directory is a request that looks like it exists and does not.
        try:
            os.unlink(handle.name)
        except OSError:                          # pragma: no cover - defensive
            pass
        raise


def approvals_root(env: Optional[str] = None) -> Optional[Path]:
    """Where approval records go, or ``None`` for explicitly disabled.

    *env* is the raw value of :data:`APPROVALS_ENV`; ``None`` reads the
    environment.  An unset or blank value is the default directory — the
    absence of a setting is not a request to keep no records, exactly as it
    is not for the audit log.
    """
    raw = os.getenv(APPROVALS_ENV) if env is None else env
    value = (raw or "").strip()
    if not value:
        return Path.cwd() / APPROVALS_DIRNAME
    if value.lower() in DISABLE_WORDS:
        return None
    return Path(value).expanduser()


def default_approval_store(env: Optional[str] = None) -> Optional["ApprovalStore"]:
    """The store a mission gets unless :data:`APPROVALS_ENV` says otherwise.

    ``None`` only when the environment says so in as many words, and a caller
    that receives ``None`` is expected to *say* so — see the console line in
    :func:`core.cli._mission`.  A gate whose request is not written down is a
    gate nobody can answer.
    """
    root = approvals_root(env)
    return None if root is None else ApprovalStore(root)


@dataclass
class Approval:
    """One request, and everything needed to decide it and to audit it later.

    ``arguments`` is what the model proposed, **verbatim**.  It is the whole
    reason a durable record beats a sentence in a transcript: a refusal in
    prose says no, and a record carrying the tool and the exact arguments
    lets somebody actually decide.  It is not rewritten, for the reason
    :data:`core.redact.WHY_VERBATIM` gives about the stream — what a person
    approves must be the bytes that were proposed, and a redacted argument
    approved here is a different call from the one that was asked about.

    The free text around it (:attr:`objective`, :attr:`reason`, :attr:`note`)
    *is* scrubbed for credentials on the way in, through the same pass and the
    same owner the audit log uses: an objective is a sentence somebody typed,
    and sentences people type are where pasted tokens live.
    """

    approval_id: str
    #: The tool the model named, as the bus dispatches it.
    tool: str
    arguments: Dict[str, Any] = field(default_factory=dict)
    #: The mission's objective — what the agent was asked to do, so a person
    #: deciding an hour later knows what they are deciding *for*.
    objective: str = ""
    #: The run this request came out of.  Free-form, and the string
    #: :meth:`ApprovalStore.reconcile` compares against the runs still alive.
    run_id: str = ""
    #: The harness's own sentence about why this stopped, as it went out on
    #: ``gate_requested.reason``.
    reason: str = ""
    state: str = PENDING
    requested_at: str = field(default_factory=_now)
    decided_at: str = ""
    #: Whoever answered, as the platform names them.  Free text: this
    #: framework has no principal system and must not pretend to one.
    decided_by: str = ""
    #: What the decider typed — the reason for a no, or a condition on a yes.
    note: str = ""
    #: When the approval was carried into a dispatch.  Set once, by
    #: :meth:`ApprovalStore.consume`.
    spent_at: str = ""

    @property
    def pending(self) -> bool:
        return self.state == PENDING

    def as_record(self) -> Dict[str, Any]:
        """The dict that goes on disk, plus the sentence for whoever reads it."""
        body = asdict(self)
        body["why_gated"] = WHY_GATED
        return body


class ApprovalStore:
    """Durable approvals, on disk, one JSON file each.

    Its own directory and its own ids rather than a section of the mission
    transcript, because the decision arrives from **outside the run**: a
    different process, sometimes a different day, and always after the
    mission that asked has exited.  Looking one up must not mean replaying a
    conversation.
    """

    def __init__(self, root: Any = None):
        # ``approvals_root("")`` and not ``approvals_root()``: constructing a
        # store is a decision to keep records, and reading the disable word
        # here would hand back an object whose directory nothing writes to.
        # Disabling is :func:`default_approval_store`'s answer, and it says so
        # by returning nothing at all.
        self.root = Path(root) if root else approvals_root("")
        self._lock = threading.RLock()

    # ── addressing ──────────────────────────────────────────────────────

    def _path(self, approval_id: str) -> Path:
        """The file for *approval_id*, or :class:`NoSuchApproval`.

        The id is validated as **path-safe** before it is joined to anything:
        these ids arrive on a command line from whoever is holding one, and a
        store that joined ``../../etc/passwd`` to its root would be reading
        and writing wherever it was pointed.  The shape is this module's own
        (``ap_`` and hex), so anything else is not a name this store ever
        wrote and the honest answer is that there is no such approval.
        """
        name = str(approval_id or "")
        if (not name.startswith(_ID_PREFIX)
                or len(name) <= len(_ID_PREFIX)
                or not name[len(_ID_PREFIX):].isalnum()):
            raise NoSuchApproval(
                f"{approval_id!r} is not an approval id this store wrote "
                f"(they look like {_ID_PREFIX}0f3c…)")
        return self.root / f"{name}.json"

    def _read(self, path: Path) -> Approval:
        body = json.loads(path.read_text(encoding="utf-8"))
        body.pop("why_gated", None)
        return Approval(**body)

    def _write(self, approval: Approval) -> None:
        _atomic_write_json(self._path(approval.approval_id),
                           approval.as_record())

    # ── the ask ─────────────────────────────────────────────────────────

    def request(self, *, tool: str, arguments: Optional[Mapping[str, Any]] = None,
                objective: str = "", run_id: str = "",
                reason: str = "") -> str:
        """Record that the agent asked.  Returns the id, and decides nothing.

        Note what this method does **not** take: any parameter by which a
        caller could pre-answer it.  There is no ``auto``, no ``default``, no
        ``approve_if``.  The absence is the control — a flag like that is
        reached for under a deadline and is exactly how a gate stops being
        one.
        """
        approval = Approval(
            approval_id=_ID_PREFIX + uuid.uuid4().hex[:16],
            tool=str(tool),
            arguments=dict(arguments or {}),
            objective=scrub_secrets(str(objective)),
            run_id=str(run_id),
            reason=scrub_secrets(str(reason)),
        )
        with self._lock:
            self._write(approval)
        return approval.approval_id

    def get(self, approval_id: str) -> Approval:
        """The record, or :class:`NoSuchApproval`."""
        with self._lock:
            path = self._path(approval_id)
            try:
                return self._read(path)
            except FileNotFoundError:
                raise NoSuchApproval(f"no approval {approval_id!r}") from None
            except (ValueError, TypeError) as exc:
                raise NoSuchApproval(
                    f"approval {approval_id!r} is not readable: {exc}") from None

    # ── the answer ──────────────────────────────────────────────────────

    def decide(self, approval_id: str, *, approve: bool, decided_by: str,
               note: str = "") -> Approval:
        """Somebody answers.  The only path to :data:`APPROVED` in this repo.

        ``approve`` is a required keyword with no default, which is small and
        deliberate: a default would decide what an omission means, and the two
        candidate meanings are "do nothing" and "do the thing".

        ``decided_by`` is required and must be non-empty.  Core cannot check
        that it names a *person* — this framework has no identity layer, and
        one invented here would be a guess at the platform's answer — but it
        can refuse a decision that names nobody at all, and it does.  The
        platform supplies the person; core supplies the record with room for
        them and the refusal when the room is left empty.
        """
        who = str(decided_by or "").strip()
        if not who:
            raise NoDecider(
                "a decision must name who made it: pass decided_by. This "
                "framework has no principal system and will not invent one, "
                "but an approval signed by nobody is not an approval.")
        with self._lock:
            approval = self.get(approval_id)
            if approval.state in RESOLVED:
                raise AlreadyDecided(
                    f"{approval_id} was already {approval.state} by "
                    f"{approval.decided_by or 'nobody in particular'} at "
                    f"{approval.decided_at or 'an unrecorded time'}. A gate "
                    f"is answered once.")
            approval.state = APPROVED if approve else REFUSED
            approval.decided_by = who
            approval.decided_at = _now()
            approval.note = scrub_secrets(str(note))
            self._write(approval)
            return approval

    def consume(self, approval_id: str) -> Approval:
        """Spend an approval on the dispatch that carries it.  Once.

        Refuses anything that is not :data:`APPROVED`, defensively: this is
        the last place before a gated tool is actually called, and pending is
        not approved here any more than it is anywhere else.
        """
        with self._lock:
            approval = self.get(approval_id)
            if approval.state == SPENT:
                raise AlreadySpent(
                    f"{approval_id} was already spent at {approval.spent_at}. "
                    f"A decision opens one tool for one run; ask again and "
                    f"answer it again.")
            if approval.state != APPROVED:
                raise NotApproved(
                    f"{approval_id} is {approval.state}, not approved. "
                    f"Nothing here times out into a yes.")
            approval.state = SPENT
            approval.spent_at = _now()
            self._write(approval)
            return approval

    def abandon(self, approval_id: str) -> Approval:
        """The run that asked is gone.  Resolves as a **refusal**, never a pass.

        Already-resolved records are returned untouched: a person's yes or no
        is not overwritten by a restart noticing that the process died.
        """
        with self._lock:
            approval = self.get(approval_id)
            if approval.state in RESOLVED:
                return approval
            approval.state = ABANDONED
            approval.decided_at = _now()
            approval.note = ("the run that asked for this ended before it was "
                             "answered; nothing was done")
            self._write(approval)
            return approval

    # ── reading the queue ───────────────────────────────────────────────

    def pending(self) -> List[Approval]:
        """Everything still waiting, oldest first.

        Oldest first because a queue of decisions is worked from the front,
        and because the oldest is the one whose run has been blocked longest.
        """
        out: List[Approval] = []
        with self._lock:
            if not self.root.is_dir():
                return out
            for path in sorted(self.root.glob(f"{_ID_PREFIX}*.json")):
                try:
                    approval = self._read(path)
                except (ValueError, TypeError, OSError):
                    # A half-written or hand-edited file is skipped rather
                    # than raised on: one unreadable record must not hide
                    # every other decision somebody is waiting to make.
                    continue
                if approval.state == PENDING:
                    out.append(approval)
        return sorted(out, key=lambda a: a.requested_at)

    def reconcile(self, live_run_ids: Iterable[str]) -> List[Approval]:
        """Abandon every pending request whose run is no longer alive.

        A refusal, not a pass — see :data:`ABANDONED`.  Returns what was
        abandoned, so a caller can say so rather than have it happen quietly.

        A pending record with **no** ``run_id`` is left alone.  Reconciliation
        is the question "is the run that asked still there", and a request
        that never named a run was not asked by one this can answer for; a
        library caller's record would otherwise be abandoned by the first
        restart that swept the directory.

        Deliberately **not** wired to startup here.  Nothing in this repo can
        yet say which runs are alive; the run-durability work owns that, and
        this method is the seam it will call.  Wiring it to a liveness check
        that guesses would abandon live requests, which is a refusal nobody
        made.
        """
        live = {str(run) for run in live_run_ids if str(run)}
        abandoned: List[Approval] = []
        for approval in self.pending():
            if not approval.run_id or approval.run_id in live:
                continue
            abandoned.append(self.abandon(approval.approval_id))
        return abandoned


class ApprovalTicket:
    """One approved record, resolved at the door and spendable exactly once.

    This is the whole of what an approval *does* to a run: it removes
    :attr:`tool` from the run's gated set, and nothing else changes anywhere.
    The narrowness is the point — one tool, one run, one decision — and it is
    an object rather than a boolean so that the spending is attached to the
    widening and cannot drift away from it.
    """

    def __init__(self, store: ApprovalStore, approval: Approval):
        self._store = store
        self._approval = approval
        self._spent = False

    @property
    def approval_id(self) -> str:
        return self._approval.approval_id

    @property
    def tool(self) -> str:
        """The one tool this ticket lifts out of the gated set."""
        return self._approval.tool

    @property
    def decided_by(self) -> str:
        return self._approval.decided_by

    @property
    def decided_at(self) -> str:
        return self._approval.decided_at

    @property
    def spent(self) -> bool:
        return self._spent

    def widen(self, gated: Iterable[str]) -> List[str]:
        """*gated* without this ticket's tool, in the order it arrived.

        The one owner of the subtraction, so the direct runner, the staged
        runner and the opening frame cannot disagree about which tools a run
        gates.
        """
        return [name for name in gated if name != self.tool]

    def spend(self) -> None:
        """Mark the decision used, at the moment the tool is dispatched.

        Called from the dispatch path and guarded here rather than there, so
        a run that calls the approved tool twice spends the approval once and
        a run that never calls it does not spend it at all.
        """
        if self._spent:
            return
        self._spent = True
        self._store.consume(self._approval.approval_id)


def resolve(store: Optional[ApprovalStore],
            approval_id: str) -> Optional[ApprovalTicket]:
    """The ticket for *approval_id*, or a refusal naming the state.

    ``""`` is ``None`` — a run resuming nothing, which is every ordinary run.

    Every state that is not :data:`APPROVED` raises :class:`NotApproved` and
    **says which state it is**.  A pending request is not a yes nobody got
    round to; a refused one is a no; a spent one is a yes that has already
    been used, and treating it as a second one is the standing permission this
    module exists to not have.  The refusal happens here, at the door, before
    a mission starts — an operator who passed the wrong id finds out in a
    second rather than after the model has been asked.

    **Why the spend is on dispatch and not here.**  The reference platform
    spends its decision on the turn that carries it back, which is the same
    thing when the turn is guaranteed to reach the tool.  Here it is not: a
    resumed run can answer without calling anything, exhaust its step budget,
    or fail to reach the tool plane at all, and a yes burned on a run where
    nothing happened teaches an operator to approve the same act twice.  So
    :meth:`ApprovalTicket.spend` fires from the dispatch path.  Nothing is
    widened by the delay — the ticket lifts one tool out of one run's gated
    set either way, and reaching a second run still takes somebody passing
    ``--approval`` again on purpose.
    """
    wanted = str(approval_id or "").strip()
    if not wanted:
        return None
    if store is None:
        raise NotApproved(
            f"{wanted} cannot be resolved: this run keeps no approval records "
            f"({APPROVALS_ENV} is set to a disabling word). A decision has to "
            f"be readable from outside the run that asked for it.")
    approval = store.get(wanted)
    if approval.state != APPROVED:
        raise NotApproved(
            f"{wanted} is {approval.state}, not approved — nothing was "
            f"widened and the tool stays gated. "
            + {
                PENDING: "Nobody has decided it yet, and it will not decide "
                         "itself.",
                REFUSED: (f"It was refused by "
                          f"{approval.decided_by or 'somebody'}"
                          + (f": {approval.note}" if approval.note else ".")),
                SPENT: (f"It was already spent at {approval.spent_at}. An "
                        f"approval opens one tool for one run; ask again and "
                        f"answer it again."),
                ABANDONED: "The run that asked for it ended before it was "
                           "answered, so it was abandoned — which is a "
                           "refusal.",
            }.get(approval.state, ""))
    return ApprovalTicket(store, approval)
