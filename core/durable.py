# core/durable.py — writes that survive the process that made them

"""Durability, as three functions and one store.

Everything this harness knows about a run it has just done is in memory
until something writes it down, and until now the writing down was done
four different careless ways: ``path.write_text(...)`` in the session
manager, in the campaign session, in two caches and in the patch
worktree — a plain truncate-then-write that leaves a *half* file behind
when the process dies between the two — and a bare buffered ``append``
in :mod:`core.policy.audit`, which returns long before the bytes are on
a disk.  Neither is a bug you can find by reading the happy path.  Both
are the same bug: the record of what happened is less durable than the
thing that happened.

So there is one module, it imports nothing this repo owns (like
:mod:`core.bounding` and :mod:`core.redact`, and for the same reason —
every direction has to stay open), and it owns three decisions.

**Replacing a file is atomic or it is not done.**
:func:`atomic_write_text` and :func:`atomic_write_json` write a
temporary file *in the same directory*, flush it, ``fsync`` it, and
``os.replace`` it over the target.  A reader either sees the whole old
file or the whole new one, never a prefix, and a crash mid-write leaves
the old file intact rather than a truncated one.  The temporary file is
in the same directory because ``os.replace`` is only atomic within a
filesystem.

**Appending a line is durable or it is not recorded.**
:func:`fsync_append` opens for append, writes one line, flushes and
``fsync``s.  Append to a JSONL is the one write that does not need the
tempfile dance — a torn line is detectable and only the last line can
tear — but it does need the ``fsync``, because "the audit log said so"
is a claim about a disk and not about a buffer.

**A run is a numbered, append-only log plus a small metadata file.**
:class:`RunStore` is the primitive the mission's transcript is written
through.  One directory per run, one ``events.jsonl`` of envelopes, one
``meta.json`` replaced atomically.  Every envelope carries a ``seq``
that is monotonic per run, so a reader can say where it got to and be
replayed from there — which is what resume, orphan reconciliation and
"show me that mission again" all need and none of them can have from a
stream that was only ever a pipe.

**The reused-sequence bug, carried in on purpose.**  The reference
platform this primitive is ported from paid for one lesson the hard
way, and :data:`RunStore.CALLER_OWNED` is the shape of it: a caller read
the metadata, did some work, and wrote the whole object back — stamping
a ``last_seq`` that had moved on in the meantime, so the next append
reused numbers a reader had already seen and skipped past.  The reader
resumes with ``seq > cursor``; it therefore dropped every one of them,
and showed a blank transcript for a run whose records were on disk the
whole time.  :meth:`RunStore.save` writes back only the caller's own
fields onto the record *as it is now*, and ``last_seq`` is never the
caller's.  Whitelisted rather than fixed by asking callers to re-read
first: "remember to re-read before you save" is a rule that holds until
the next caller.

**Where the runs go, and how to turn them off.**  ``JUDAIS_LOBI_RUNS``
is either a path (used verbatim) or one of ``none``/``off``, which
disables persistence *explicitly* — deliberately the same two words and
the same shape as ``JUDAIS_LOBI_AUDIT`` in :mod:`core.policy.audit`, so
that a deployment learns one convention rather than two.  Unset is the
default directory, never disabled: silence is not a setting anybody
chose.  See :func:`runs_root`, which is to this module what
:func:`core.policy.audit.audit_path` is to that one, and
:func:`open_run_store`, which is :func:`~core.policy.audit
.default_audit_logger`.

Nothing here knows what a mission is.  It stores records; what a record
means is :mod:`core.runtime.contract`'s to say.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import (
    Any, Dict, Iterator, List, Mapping, Optional, Tuple, Union,
)

__all__ = [
    "RUNS_ENV", "RUNS_DIRNAME", "DISABLE_WORDS", "POLL_S",
    "atomic_write_text", "atomic_write_json", "fsync_append",
    "new_run_id", "valid_run_id", "runs_root", "open_run_store",
    "Run", "RunStore", "NoSuchRun",
]

#: The variable a deployment moves or silences the run store with.  Named
#: like :data:`core.policy.audit.AUDIT_ENV` because it does the same job.
RUNS_ENV = "JUDAIS_LOBI_RUNS"

#: Where the runs go by default, relative to the current directory —
#: beside ``.judais-lobi/audit/``, which is the other thing this harness
#: writes down about itself.
RUNS_DIRNAME = Path(".judais-lobi") / "runs"

#: The two words that mean "keep nothing", case-insensitively.  The same
#: two :data:`core.policy.audit.DISABLE_WORDS` uses: one convention.
DISABLE_WORDS = frozenset({"none", "off"})

#: How long :meth:`RunStore.follow` waits for a record before yielding
#: control so a transport can send a heartbeat and notice a reader that
#: has gone away.  A follower blocked forever on a mission that is
#: thinking is indistinguishable from one blocked on a mission that died.
POLL_S = 1.0

#: A run id that is safe as a path segment, checked as a **whitelist**
#: rather than by escaping what is dangerous.  An id this harness did not
#: mint must never become a directory: ``..`` and ``/`` are not merely
#: escaped here, they cannot match.
_RUN_ID = re.compile(r"^run_[0-9A-Za-z]{1,32}(?:-[0-9A-Za-z]{1,32})?$")

_PathLike = Union[str, os.PathLike]


def now() -> str:
    """UTC, to the second, ISO-8601.  One spelling of "when"."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_run_id() -> str:
    """``run_20260815T131102-9f3a1c04`` — sortable, unique, path-safe.

    The same shape as :func:`core.policy.audit.audit_run_id` and for the
    same two reasons: a directory listing stays chronological, and the
    random tail keeps two runs started in the same second apart.  The
    ``run_`` prefix is what :func:`valid_run_id` recognises, so an id
    from somewhere else cannot be mistaken for one of ours.
    """
    return (f"run_{datetime.now().strftime('%Y%m%dT%H%M%S')}"
            f"-{uuid.uuid4().hex[:8]}")


def valid_run_id(run_id: Any) -> bool:
    """Whether *run_id* is one this store will touch the disk for."""
    return bool(isinstance(run_id, str) and _RUN_ID.match(run_id))


# ── the two writes ───────────────────────────────────────────────────────────


def atomic_write_text(path: _PathLike, text: str, *,
                      encoding: str = "utf-8") -> Path:
    """Replace *path* with *text*, all of it or none of it.

    Signature deliberately shaped like ``Path.write_text`` — the call it
    replaces reads ``path.write_text(payload, encoding="utf-8")``
    everywhere in this repo, so adopting this is a one-line change at
    each site and not a rewrite of the caller.

    The staging file is a sibling (``os.replace`` is atomic within a
    filesystem and not across one) and it is removed if the replace
    fails, so a failure leaves the directory as it found it rather than
    strewn with ``tmpXXXX`` files nothing will ever collect.  The parent
    directory is created here rather than at the caller, because every
    caller was creating it and one of them will forget.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    staged = ""
    try:
        with tempfile.NamedTemporaryFile(
                "w", dir=str(target.parent), prefix=f".{target.name}.",
                suffix=".tmp", delete=False, encoding=encoding) as handle:
            staged = handle.name
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(staged, target)
    except BaseException:
        if staged:
            try:
                os.unlink(staged)
            except OSError:                     # pragma: no cover - raced
                pass
        raise
    return target


def atomic_write_json(path: _PathLike, obj: Any, *,
                      indent: Optional[int] = None) -> Path:
    """:func:`atomic_write_text` of ``json.dumps(obj)``.

    ``default=str`` for the same reason the event sink has it: a record
    holding a ``Path`` or a ``datetime`` must be written down as
    something, and refusing to write the metadata of a run because one
    field was not a primitive is the failure mode worth avoiding.
    """
    return atomic_write_text(
        path, json.dumps(obj, ensure_ascii=False, default=str, indent=indent))


def fsync_append(path: _PathLike, line: str) -> Path:
    """Append one *line* (a newline is added) and put it on the disk.

    The parent directory is created on this write and not before: a log
    nobody has written to must not leave a directory behind — which is
    exactly what a test suite constructing a default audit logger would
    otherwise scatter through a checkout.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "a", encoding="utf-8") as handle:
        handle.write(line + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return target


# ── where the runs live ──────────────────────────────────────────────────────


def runs_root(env: Optional[str] = None) -> Optional[Path]:
    """Where runs are recorded, or ``None`` for explicitly disabled.

    *env* is the raw value of :data:`RUNS_ENV`; ``None`` reads the
    environment.  Unset or blank is the default directory — the absence
    of a setting is not a request to keep no records.  Written to mirror
    :func:`core.policy.audit.audit_path` line for line, because a
    deployment that has learned how to move the audit log has thereby
    learned how to move this.
    """
    raw = os.getenv(RUNS_ENV) if env is None else env
    value = (raw or "").strip()
    if not value:
        return Path.cwd() / RUNS_DIRNAME
    if value.lower() in DISABLE_WORDS:
        return None
    return Path(value).expanduser()


def open_run_store(env: Optional[str] = None) -> Optional["RunStore"]:
    """The store a run is recorded in, or ``None`` when told not to.

    :func:`core.policy.audit.default_audit_logger`'s counterpart: the
    disable word is read *here* and answered by returning nothing at
    all, so a :class:`RunStore` that exists is always a store something
    writes to.
    """
    root = runs_root(env)
    return None if root is None else RunStore(root)


class NoSuchRun(KeyError):
    """No run by that id — and the same answer for an id we never minted.

    One exception for both, so a caller cannot distinguish "not there"
    from "not a name this store would ever use"; the second is a
    traversal attempt and it deserves no more information than the
    first.
    """


@dataclass
class Run:
    """One run's metadata: the store's half, then the caller's.

    ``last_seq`` is the store's and is persisted for the reason the
    whole module exists — a restart must not hand out a number a reader
    has already seen and skipped past.  :attr:`meta` is the caller's
    half, whatever it wants to be able to read back without replaying
    the log: the objective, the tool catalogue, the flags the run was
    spawned with.  **Not the credential it was spawned with** — see
    :meth:`RunStore.create`.
    """

    run_id: str
    created_at: str = field(default_factory=now)
    updated_at: str = field(default_factory=now)
    #: Monotonic; the last seq assigned.
    last_seq: int = 0
    #: The caller's own facts.  See :data:`RunStore.CALLER_OWNED`.
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> Dict[str, Any]:
        return asdict(self)


class RunStore:
    """Durable runs and their event logs.

    On disk::

        <root>/run_<stamp>-<hex>/meta.json      the Run record, replaced atomically
        <root>/run_<stamp>-<hex>/events.jsonl   one envelope per line, fsync'd

    An **envelope** is ``{"seq": n, "at": iso, "record": {...}}``.  The
    numbering is the store's and the record is the caller's, kept apart
    on purpose: a mission's records are governed by
    :mod:`core.runtime.contract`, and a store that added a field to them
    would be a second author of a document that has one.  So ``seq``
    does not travel on the wire — a consumer reading the NDJSON stream
    sees exactly what it saw before this module existed — and a consumer
    replaying from disk gets the cursor it needs in the envelope around
    it.

    Thread-safe by one lock over the whole store rather than one per
    run: the operations are short and a single lock is the version whose
    ordering is obvious.
    """

    def __init__(self, root: _PathLike) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        #: Woken on every append; followers wait on it rather than
        #: polling the filesystem to learn that something arrived.
        self._arrived = threading.Condition(self._lock)

    # ── layout ──────────────────────────────────────────────────────────

    def directory(self, run_id: str) -> Path:
        """This run's directory.  The traversal check lives here."""
        if not valid_run_id(run_id):
            raise NoSuchRun(run_id)
        return self.root / run_id

    def meta_path(self, run_id: str) -> Path:
        return self.directory(run_id) / "meta.json"

    def log_path(self, run_id: str) -> Path:
        return self.directory(run_id) / "events.jsonl"

    # ── the run ─────────────────────────────────────────────────────────

    def create(self, run_id: Optional[str] = None,
               meta: Optional[Mapping[str, Any]] = None) -> Run:
        """Mint (or adopt) a run id and lay out its directory.

        The store hands the id out — that is what makes it the one owner
        of it, and why a caller never has to guess a directory name to
        find a run again.  An explicit *run_id* is for the caller that
        already has one (a resumed run, a test), and it is validated the
        same way every other id is.

        *meta* is the caller's index over the log: enough to list runs
        without replaying them.  **A credential is never one of those
        facts.**  A run directory outlives the process, and the value of
        ``MCP_TOKEN`` written into ``meta.json`` is a token on somebody's
        disk long after the mission that was handed it has finished.
        """
        run = Run(run_id=run_id or new_run_id(), meta=dict(meta or {}))
        if not valid_run_id(run.run_id):
            raise NoSuchRun(run.run_id)
        with self._lock:
            self.directory(run.run_id).mkdir(parents=True, exist_ok=True)
            self.log_path(run.run_id).touch()
            self._write_meta(run)
        return run

    def _write_meta(self, run: Run) -> None:
        """Atomic replace, so a reader never sees half a record."""
        run.updated_at = now()
        atomic_write_json(self.meta_path(run.run_id), run.to_json())

    def _read_meta(self, run_id: str) -> Run:
        path = self.meta_path(run_id)
        if not path.exists():
            raise NoSuchRun(run_id)
        record = json.loads(path.read_text(encoding="utf-8"))
        return Run(**record)

    def meta(self, run_id: str) -> Run:
        """This run's record as it is on disk."""
        with self._lock:
            return self._read_meta(run_id)

    #: The fields a caller holding a :class:`Run` may write back.
    #:
    #: **This split is load-bearing and it was written after the bug** —
    #: see the module docstring.  A caller reads the record, works, and
    #: saves; ``append`` has moved ``last_seq`` on in between; writing
    #: the whole object back puts the stale counter on disk and the next
    #: append reuses numbers a reader has already passed.  Everything
    #: outside this tuple is re-read from disk on every save.
    CALLER_OWNED: Tuple[str, ...] = ("meta",)

    def save(self, run: Run) -> Run:
        """Persist the caller's fields onto the record as it is NOW."""
        with self._arrived:
            fresh = self._read_meta(run.run_id)
            for name in self.CALLER_OWNED:
                setattr(fresh, name, getattr(run, name))
            self._write_meta(fresh)
            return fresh

    def update_meta(self, run_id: str, **facts: Any) -> Run:
        """Merge *facts* into this run's ``meta``, read-modify-write.

        The safe half of the pair: the record is read inside the lock
        and written back in the same breath, so a caller that only wants
        to add one fact never has to hold a :class:`Run` across the work
        that would make it stale.  :meth:`save` exists for the caller
        that is already holding one.
        """
        with self._arrived:
            fresh = self._read_meta(run_id)
            fresh.meta.update(facts)
            self._write_meta(fresh)
            return fresh

    def list(self) -> List[Run]:
        """Every run this store holds, newest first.

        A directory it cannot read is skipped rather than fatal: one
        run's torn metadata must not make the other hundred unlistable.
        """
        found: List[Run] = []
        with self._lock:
            for entry in sorted(self.root.glob("run_*")):
                if not (entry / "meta.json").exists():
                    continue
                try:
                    record = json.loads(
                        (entry / "meta.json").read_text(encoding="utf-8"))
                    found.append(Run(**record))
                except (ValueError, OSError, TypeError):
                    continue
        return sorted(found, key=lambda r: r.created_at, reverse=True)

    # ── the log ─────────────────────────────────────────────────────────

    def append(self, run_id: str, record: Mapping[str, Any]) -> Dict[str, Any]:
        """Number it, write it, then wake the followers.  In that order.

        Numbered inside the lock so two threads writing to one run
        cannot collide, and written before the wake so a follower that
        reads the file rather than the notification cannot observe a
        gap.  ``last_seq`` is stamped from the envelope that was just
        written and never from an object somebody was holding.
        """
        with self._arrived:
            run = self._read_meta(run_id)
            envelope = {"seq": run.last_seq + 1, "at": now(),
                        "record": dict(record)}
            fsync_append(self.log_path(run_id),
                         json.dumps(envelope, ensure_ascii=False,
                                    allow_nan=False, default=str))
            run.last_seq = int(envelope["seq"])
            self._write_meta(run)
            self._arrived.notify_all()
            return envelope

    def since(self, run_id: str, cursor: int = 0) -> List[Dict[str, Any]]:
        """Every envelope after *cursor*, oldest first.

        A line that will not parse is skipped rather than fatal.  Only
        the last line can tear — a process killed between the write and
        the fsync — and the alternative is a transcript that will not
        open again, ever.
        """
        with self._lock:
            path = self.log_path(run_id)
            if not path.exists():
                raise NoSuchRun(run_id)
            out: List[Dict[str, Any]] = []
            with path.open(encoding="utf-8") as log:
                for line in log:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        envelope = json.loads(line)
                    except ValueError:
                        continue
                    if int(envelope.get("seq", 0)) > cursor:
                        out.append(envelope)
            return out

    def records(self, run_id: str, cursor: int = 0) -> List[Dict[str, Any]]:
        """:meth:`since`, unwrapped — the records as they were emitted.

        What a replay hands to something that speaks the event
        vocabulary and has no business knowing this module exists.
        """
        return [dict(e.get("record") or {}) for e in self.since(run_id, cursor)]

    def follow(self, run_id: str, cursor: int = 0, *,
               stop: Optional[threading.Event] = None,
               poll_s: float = POLL_S) -> Iterator[Optional[Dict[str, Any]]]:
        """Replay from *cursor*, then block for what comes next.

        Yields envelopes, and a ``None`` whenever the wait times out so
        the caller can send a heartbeat and notice a reader that has
        gone away.  The wake is a :class:`threading.Condition` rather
        than a directory poll — a writer in this process notifies
        directly, and the timeout is a bound on how long a *reader*
        waits, not the mechanism by which it learns.

        Ends when *stop* is set.  Without one it never ends, which is
        correct for a subscriber the caller drives and closes.
        """
        for envelope in self.since(run_id, cursor):
            cursor = max(cursor, int(envelope.get("seq", 0)))
            yield envelope
        while stop is None or not stop.is_set():
            with self._arrived:
                self._arrived.wait(poll_s)
            fresh = self.since(run_id, cursor)
            if not fresh:
                yield None
                continue
            for envelope in fresh:
                cursor = max(cursor, int(envelope.get("seq", 0)))
                yield envelope
