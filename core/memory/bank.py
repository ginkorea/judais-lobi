# core/memory/bank.py — the memory bank: core, recall, and what writes to them

"""Three tiers of memory, and three different rules about when they arrive.

Simple RAG is normally implemented incorrectly: it pulls too much and the
wrong thing into a context that then has less room for the objective.
Ignoring retrieval entirely is the other error — an agent that has done
this work before and cannot say so is an agent that learns nothing.  So
what this module implements is not one retrieval mechanism with a knob on
it but **three tiers, each with its own insertion rule**, and the rules are
the design:

* **Core memory** — pinned, tiny, self-edited.  A handful of blocks per
  principal and skill (``preference``, ``fact``, ``lesson``, ``persona``),
  hard-capped at :data:`CORE_MEMORY_TOKENS`, rendered into the *system
  turn* of every run.  It is always there and it is therefore not allowed
  to grow: the cap is what keeps it honest, and a write that would breach
  it is refused naming the cap rather than silently trimming the oldest
  thing somebody deliberately pinned.  It changes only through the
  ``memory_write`` tool — each edit carrying a ``reason`` and the evidence
  it came from — or through an operator at ``python -m core.memory``.

* **Recall memory** — retrieved on demand and **never auto-stuffed**.  One
  tool, :meth:`MemoryBank.recall`, over two stores: the EPISODIC one (the
  durable :class:`~core.durable.RunStore` — what actually happened, by
  objective and answer) and the SEMANTIC one (distilled NOTES written by a
  bounded reflection step at the end of a run).  Notes, not raw chunks: a
  chunk is what the corpus happened to contain and a note is what the run
  decided was worth keeping.  What comes back is ranked and then **cut to a
  hard token budget** (:data:`RECALL_TOKENS`), because the failure mode of
  retrieval is not a bad ranking, it is a good ranking of forty things.

* **Working memory** — already built, and named here so nobody builds it
  twice: the per-mission result store (``mission_result`` handles), the
  context window's compaction, the swarm's step summaries and the
  supervisor's history.  Nothing in this module touches it.

The one concession to "ignoring retrieval is naive" is :meth:`hint`: at the
start of a run the harness may render a **titles-only** line beside the
objective — *"2 remembered notes may bear on this: …; …"* — and nothing
else.  It is about 150 tokens, it goes in the USER turn and never in the
system turn (the system turn is a served endpoint's cache prefix and a line
that moved per-objective would cost a cache miss on every step of every
mission), and it only appears when something actually scores.  The model
then decides whether to spend a call on ``memory_recall``.  A hint is an
offer; a retrieval is a decision the model makes.

**Nothing here changes what is on the wire.**  A recall and a write are
ordinary ``tool_call``/``tool_result`` records dispatched through the
:class:`~core.tools.bus.ToolBus`, so they are audited, redacted,
capability-checked and — because a tool result is evidence — citable by the
grounding validator.  A recalled note is DATED EVIDENCE and says so: see
:data:`MEMORY_POLICY`.

**The principal is attributed, not authenticated.**  This framework has no
principal system and will not invent one — :mod:`core.runtime.approvals`
says the same thing about who approved a gate, in the same words, for the
same reason.  ``principal`` here is a string an operator supplies
(``JUDAIS_LOBI_MEMORY_PRINCIPAL``, default ``"default"``) that partitions
the bank so two people or two deployments sharing a directory do not read
each other's memory.  It is a filing decision.  A caller that needs it to
be a security boundary needs a different directory, and this module will
not pretend otherwise.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from core.context.formatter import estimate_tokens
from core.durable import DISABLE_WORDS
from core.redact import scrub
from core.tools.descriptors import (
    MEMORY_RECALL_DESCRIPTOR, MEMORY_RECALL_TOOL, MEMORY_WRITE_DESCRIPTOR,
    MEMORY_WRITE_TOOL,
)

__all__ = [
    "BLOCK_KINDS", "CORE_MEMORY_TOKENS", "DEFAULT_PRINCIPAL", "HALF_LIFE_DAYS",
    "HINT_THRESHOLD", "HINT_TOKENS", "MAX_NOTES_PER_RUN", "MEMORY_ENV",
    "MEMORY_POLICY", "NOTE_BODY_TOKENS", "PRINCIPAL_ENV", "RECALL_HINT_TITLES",
    "RECALL_K", "RECALL_TOKENS", "REFLECTION_PROMPT", "Block", "MemoryBank",
    "Note", "bank_root", "open_bank", "score",
]


# ── the knobs, and why each one is the size it is ───────────────────────────

#: How many tokens of core memory may be pinned into every system turn.
#: A thousand is about six or eight blocks: enough for the standing
#: corrections and preferences a deployment actually accumulates, and small
#: enough that a mission's context is still mostly the mission.  A write
#: that would breach it is REFUSED and names the cap — see
#: :meth:`MemoryBank.write`.
CORE_MEMORY_TOKENS = 1_000

#: The hard ceiling on what one ``memory_recall`` hands back.  The point of
#: a budget here is that a good ranking of forty notes is still forty notes.
RECALL_TOKENS = 600

#: The most results one recall may return, whatever ``k`` asks for.
RECALL_K = 5

#: How many note titles the start-of-run hint may name.  ``0`` turns the
#: hint off entirely, which is the setting for a deployment that wants
#: retrieval to be the model's idea and nobody else's.
RECALL_HINT_TITLES = 3

#: The hint's own budget.  It is deliberately an order of magnitude below
#: :data:`RECALL_TOKENS`: a hint is a list of titles, not an answer.
HINT_TOKENS = 150

#: How relevant × recent × important a note must be before its title is
#: worth naming in the hint at all.  Below this the honest hint is silence.
HINT_THRESHOLD = 0.05

#: A note's body, capped.  A "note" that runs to a page is a transcript
#: with a title on it.
NOTE_BODY_TOKENS = 80

#: How many notes one run's reflection may write.  Usually the right answer
#: is zero and the prompt says so.
MAX_NOTES_PER_RUN = 3

#: The half-life of relevance, in days.  A fact learned a fortnight ago is
#: worth half what the same fact learned today is worth, which is the
#: generative-agents recency term with a number a deployment can argue with.
HALF_LIFE_DAYS = 14.0

#: What a core block may be.  Four kinds and not free text: the kind is what
#: an operator sorts by when the cap forces a choice.
BLOCK_KINDS: Tuple[str, ...] = ("preference", "fact", "lesson", "persona")

#: Where the bank lives.  UNSET MEANS NO BANK — unlike
#: :data:`core.durable.RUNS_ENV`, whose absence still keeps records.  Memory
#: is a thing a deployment opts into, and a run with no bank configured must
#: produce byte-identical prompts to one from before this module existed.
MEMORY_ENV = "JUDAIS_LOBI_MEMORY"

#: Which partition of the bank a run reads and writes.
PRINCIPAL_ENV = "JUDAIS_LOBI_MEMORY_PRINCIPAL"

#: The partition an unconfigured deployment gets.
DEFAULT_PRINCIPAL = "default"

#: The sentence a skill's system text gets when a bank is present, and the
#: only thing this module asserts about memory in a prompt.  Both halves are
#: load-bearing: the first stops the model treating a note as current truth,
#: and the second stops it waiting to be handed something.
MEMORY_POLICY = (
    "Memory: a recalled fact is DATED — it was true when it was written and "
    "may not be true now; re-verify with a tool when the objective needs "
    f"current. Nothing is retrieved for you: call {MEMORY_RECALL_TOOL}"
    '(query="…") when the objective touches something this deployment may '
    f"already know, and {MEMORY_WRITE_TOOL} only for something that will "
    "still matter next month."
)


# ── two rows ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Block:
    """One pinned line of core memory.

    ``label`` is the key: one block per label per (principal, skill), so a
    standing correction that is restated arrives as a ``replace`` and not as
    a second copy of itself two lines further down.
    """

    label: str
    kind: str
    body: str
    reason: str = ""
    source: str = ""
    run_id: str = ""
    as_of: str = ""
    id: int = 0

    def render(self) -> str:
        """The one line this block occupies in a system turn."""
        dated = f" (as of {self.as_of})" if self.as_of else ""
        return f"- [{self.kind}] {self.label}: {self.body}{dated}"


@dataclass(frozen=True)
class Note:
    """One distilled thing a finished run thought worth keeping.

    ``sources`` are ``run_id/seq`` pairs rendered as strings — the evidence
    the note came out of, so a model that recalls it can go and read the run
    rather than take the note's word for it.
    """

    title: str
    body: str
    importance: int = 3
    as_of: str = ""
    sources: Sequence[str] = ()
    run_id: str = ""
    ts: int = 0
    id: int = 0
    #: Set by :meth:`MemoryBank.ranked_notes`; never persisted.
    score: float = 0.0

    @property
    def handle(self) -> str:
        """What a model quotes to read this note and its sources whole."""
        return f"n{self.id}"

    def render(self) -> str:
        """The block one recalled note occupies in a tool result."""
        dated = f" [{self.as_of}]" if self.as_of else ""
        where = (f"\n    sources: {', '.join(self.sources)}"
                 if self.sources else "")
        return (f"{self.handle}{dated} (importance {self.importance}) "
                f"{self.title}\n    {self.body}{where}")


# ── where a bank lives ──────────────────────────────────────────────────────


def bank_root(env: Optional[str] = None) -> Optional[Path]:
    """The directory a bank lives in, or ``None`` for no bank at all.

    *env* is the raw value of :data:`MEMORY_ENV`; ``None`` reads the
    environment.  **Unset or blank means no bank**, which is the one place
    this deliberately differs from :func:`core.durable.runs_root`: a run
    store that defaults on costs a directory, and a memory bank that
    defaulted on would change the bytes of every system turn on every
    deployment that upgraded — including the ones that never asked for
    memory.  ``none``/``off`` are accepted too so that an operator who
    exports the variable in a profile can turn it off in one place.
    """
    raw = os.getenv(MEMORY_ENV) if env is None else env
    value = (raw or "").strip()
    if not value or value.lower() in DISABLE_WORDS:
        return None
    return Path(value).expanduser()


def open_bank(env: Optional[str] = None, *, principal: Optional[str] = None,
              skill: str = "", runs: Any = None,
              embedding_client: Any = None) -> Optional["MemoryBank"]:
    """The bank a run uses, or ``None`` when nobody configured one.

    :func:`core.durable.open_run_store`'s counterpart, and written to
    mirror it: the disable word is read *here* and answered by returning
    nothing at all, so a :class:`MemoryBank` that exists is always one
    something reads and writes.

    The episodic half needs a :class:`~core.durable.RunStore`, and unless
    the caller hands one in this asks :func:`core.durable.open_run_store`
    for the same store the mission is already recording to.  One owner of
    "where runs are": that function.
    """
    root = bank_root(env)
    if root is None:
        return None
    if runs is None:
        from core.durable import open_run_store
        runs = open_run_store()
    return MemoryBank(root, principal=principal, skill=skill, runs=runs,
                      embedding_client=embedding_client)


# ── ranking ─────────────────────────────────────────────────────────────────

_WORD = re.compile(r"[a-z0-9]+")

#: Words that carry no signal about *which* note is wanted.  Short and
#: hand-written rather than a stopword corpus: the point is only to stop
#: "the" and "what" from making every note equally relevant.
_STOP = frozenset("""
a an and are as at be but by can did do does for from had has have how if
in into is it its of on or so than that the their them then there these they
this to was were what when where which who why will with you your
""".split())


def _terms(text: str) -> List[str]:
    """The words a query or a note is matched on, lowercased and stopped."""
    return [word for word in _WORD.findall((text or "").lower())
            if word not in _STOP and len(word) > 1]


def _lexical(query_terms: Sequence[str], document: str,
             frequencies: Dict[str, int], documents: int) -> float:
    """Idf-weighted term overlap in ``[0, 1]``.  The no-network path.

    A BM25 without the length saturation, which a corpus of one-sentence
    notes does not need: what is left is the half that matters, which is
    that a term appearing in every note tells you nothing and a term
    appearing in one tells you everything.  Normalized by the query's own
    total idf so the number means "how much of what was asked for is here"
    and is therefore comparable between one query and the next.
    """
    if not query_terms:
        return 0.0
    present = set(_terms(document))
    wanted = 0.0
    found = 0.0
    for term in dict.fromkeys(query_terms):
        idf = math.log(1.0 + documents / (1.0 + frequencies.get(term, 0)))
        wanted += idf
        if term in present:
            found += idf
    return (found / wanted) if wanted else 0.0


def _recency(ts: int, at: Optional[float] = None) -> float:
    """``0.5 ** (age in days / half-life)`` — in ``(0, 1]``, never zero.

    Never zero because a decayed note is stale, not wrong: an old note that
    is the *only* thing matching a query should still be reachable, and it
    is the ranking's job to put today's above it rather than to delete it.
    """
    now = time.time() if at is None else at
    age_days = max(0.0, (now - float(ts or 0)) / 86_400.0)
    return 0.5 ** (age_days / HALF_LIFE_DAYS)


def _importance(rating: int) -> float:
    """``1``–``5`` as the model rated it, mapped onto ``0.2``–``1.0``."""
    return max(1, min(5, int(rating or 3))) / 5.0


def score(relevance: float, ts: int, importance: int,
          at: Optional[float] = None) -> float:
    """``relevance × recency × importance`` — the whole ranking, in one line.

    A **product** and not the weighted sum the generative-agents paper
    used, and the difference is the one that matters here: with a sum, a
    five-star note from this morning outranks everything whether or not it
    has anything to do with the question, which is precisely the failure
    this module exists to avoid.  With a product, a note that does not
    match the query scores zero and is not recalled at all — retrieval that
    pulls the wrong thing is worse than retrieval that pulls nothing,
    because the wrong thing is also *in the way*.

    Each factor is normalized into ``(0, 1]`` by the three helpers above, so
    each of the three can be shown to move the order on its own.
    """
    return relevance * _recency(ts, at) * _importance(importance)


# ── the reflection ──────────────────────────────────────────────────────────

#: The one prompt a finished run's reflection is asked.  Bounded on both
#: sides: what goes in is a summary of the run, and what may come back is at
#: most :data:`MAX_NOTES_PER_RUN` short notes as one JSON object.
#:
#: "Usually the answer is none" is in the prompt on purpose.  A reflection
#: step that is asked "what did you learn" without being told that nothing
#: is the common answer will write three notes about every run it ever sees,
#: and a bank full of "the user asked about X and I answered" is a bank
#: whose recall is noise.
REFLECTION_PROMPT = """\
A task just finished. Write down only what will still be useful on a
DIFFERENT task weeks from now: a standing preference, a stable fact about
this deployment, or a lesson learned from something that went wrong.

Usually the right answer is NO notes. Do not write down this task's answer,
anything a tool description already says, anything that will be false next
week, or anything that only restates the objective.

Objective:
{objective}

Answer given:
{answer}

What the tools returned (bounded):
{evidence}

Reply with ONE JSON object and nothing else:
{{"notes": [{{"title": "at most 8 words", "body": "at most 60 words", \
"importance": 1}}]}}
At most {max_notes} notes, and [] is a good answer. importance: 5 = would
change how a future task is done, 1 = trivia.
"""


def _first_json_object(text: str) -> Optional[dict]:
    """The first balanced ``{...}`` in *text*, parsed, or ``None``.

    Deliberately not :meth:`core.runtime.run.Run._parse`, which is the one
    owner of *how a mission decision is read* and answers with a refusal the
    model is then shown.  This reads a side call that no mission depends on:
    a reflection that comes back as prose with an object in the middle of it
    still knows three things, and a reflection that comes back as nothing at
    all costs the run nothing.
    """
    raw = text if isinstance(text, str) else ""
    depth = 0
    start = -1
    in_string = False
    escaped = False
    for position, character in enumerate(raw):
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character == "{":
            if depth == 0:
                start = position
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    parsed = json.loads(raw[start:position + 1])
                except ValueError:
                    return None
                return parsed if isinstance(parsed, dict) else None
    return None


# ── the bank ────────────────────────────────────────────────────────────────


class MemoryBank:
    """Core blocks, distilled notes, and a read over the run store.

    One SQLite file in *path*, partitioned by ``(principal, skill)``.  The
    partition is a filing decision and not a security boundary — see the
    module docstring, and :mod:`core.runtime.approvals`, which says the same
    thing about who decided a gate.

    ``skill`` is the empty string for a mission with no skill manifest, and
    that is a partition like any other: a deployment that runs one skill and
    one ad-hoc mission keeps two sets of blocks, which is what "per skill"
    was asked for.
    """

    #: The file inside the bank directory.
    FILENAME = "bank.db"

    def __init__(self, path: Any, *, principal: Optional[str] = None,
                 skill: str = "", runs: Any = None,
                 embedding_client: Any = None,
                 core_tokens: int = CORE_MEMORY_TOKENS,
                 recall_tokens: int = RECALL_TOKENS,
                 hint_titles: int = RECALL_HINT_TITLES,
                 embedding_model: str = "text-embedding-3-large"):
        self.root = Path(path).expanduser()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / self.FILENAME
        raw_principal = (principal if principal is not None
                         else os.getenv(PRINCIPAL_ENV))
        self.principal = (raw_principal or "").strip() or DEFAULT_PRINCIPAL
        self.skill = (skill or "").strip()
        #: The episodic half.  ``None`` is a bank whose recall is notes only,
        #: which is what a caller with no durable run store has.
        self.runs = runs
        self._embedding_client = embedding_client
        self._embedding_model = embedding_model
        self.core_tokens = int(core_tokens)
        self.recall_tokens = int(recall_tokens)
        self.hint_titles = int(hint_titles)
        #: The run the ``memory_write`` tool stamps on what it writes.  Set
        #: by :meth:`register_on`, because that is a per-run act.
        self.run_id = ""
        self._ensure_db()

    # ── schema ──────────────────────────────────────────────────────────

    def _ensure_db(self) -> None:
        with sqlite3.connect(self.db_path) as con:
            con.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS blocks(
                id INTEGER PRIMARY KEY,
                principal TEXT NOT NULL,
                skill TEXT NOT NULL,
                label TEXT NOT NULL,
                kind TEXT NOT NULL,
                body TEXT NOT NULL,
                reason TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT '',
                run_id TEXT NOT NULL DEFAULT '',
                as_of TEXT NOT NULL DEFAULT '',
                ts INTEGER NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS blocks_key
                ON blocks(principal, skill, label);
            CREATE TABLE IF NOT EXISTS notes(
                id INTEGER PRIMARY KEY,
                principal TEXT NOT NULL,
                skill TEXT NOT NULL,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                importance INTEGER NOT NULL DEFAULT 3,
                as_of TEXT NOT NULL DEFAULT '',
                sources TEXT NOT NULL DEFAULT '[]',
                run_id TEXT NOT NULL DEFAULT '',
                digest TEXT NOT NULL,
                embedding BLOB,
                ts INTEGER NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS notes_digest
                ON notes(principal, skill, digest);
            """)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    @property
    def _where(self) -> Tuple[str, Tuple[str, str]]:
        """The partition clause every statement in here is scoped by."""
        return "principal=? AND skill=?", (self.principal, self.skill)

    # ── tier 1: core memory ─────────────────────────────────────────────

    def blocks(self) -> List[Block]:
        """This partition's pinned blocks, oldest first.

        Oldest first and not by importance: core memory has no importance
        rating, because everything in it was pinned deliberately and a
        ranking over six lines is arithmetic pretending to be a decision.
        The order a person put them in is the order they read in.
        """
        clause, values = self._where
        with self._connect() as con:
            rows = con.execute(
                f"SELECT id,label,kind,body,reason,source,run_id,as_of "
                f"FROM blocks WHERE {clause} ORDER BY id", values).fetchall()
        return [Block(id=row[0], label=row[1], kind=row[2], body=row[3],
                      reason=row[4], source=row[5], run_id=row[6],
                      as_of=row[7]) for row in rows]

    def core(self) -> str:
        """The section a system turn gets, or ``""`` for no bank content.

        **Never empty when a bank exists**, because the policy sentence is
        the half that has to be there even with nothing pinned: the tools
        are on the plane either way, and a model offered ``memory_recall``
        with no sentence explaining that nothing is retrieved for it will
        either never call it or treat what it gets back as current.

        Rendered here and nowhere else.
        :meth:`core.runtime.run.Run.system_turn` stacks the string this
        returns after the catalogue, so the bytes a served endpoint caches
        are decided in one place.
        """
        return _core_text(MEMORY_POLICY, self.blocks())

    def core_tokens_used(self, extra: Optional[Block] = None,
                         replacing: str = "") -> int:
        """What :meth:`core` would cost, optionally with one more block.

        The cap is measured on the **rendered** block and not on the sum of
        the bodies, because the rendering is what a system turn actually
        pays for: the kind, the label and the date are bytes too.
        """
        pinned = [block for block in self.blocks() if block.label != replacing]
        if extra is not None:
            pinned.append(extra)
        return estimate_tokens(_core_text(MEMORY_POLICY, pinned))

    def write(self, action: str, *, label: str = "", kind: str = "fact",
              body: str = "", reason: str = "", source: str = "",
              run_id: str = "", as_of: str = "") -> Tuple[int, str, str]:
        """Edit core memory.  ``(exit_code, stdout, stderr)``.

        ``add`` / ``replace`` / ``delete``, and every one of them needs a
        **reason**; the two that write need a **source** as well.  That is
        not bookkeeping: a block is pinned into every future system turn of
        this principal, and one that nobody can trace back to the evidence
        it came from is a sentence the deployment will still be reading in
        six months with no way to tell whether it was ever true.  ``source``
        is whatever names the evidence — a result handle from the run that
        learned it (``r3``), a run id, or ``operator`` when a person typed
        it.

        **An over-cap write is refused and names the cap.**  Not trimmed,
        not rotated: the blocks in there were each pinned on purpose, and a
        bank that silently evicts one to make room for another is a bank
        that loses the standing correction nobody noticed going.  The
        refusal says which cap, what it would have cost, and that a delete
        is the way to make room.

        The text is scrubbed through :func:`core.redact.scrub` on the way in
        — the one redactor — because a block outlives the run that wrote it
        and a token pasted into a "fact" would be pinned into every system
        turn from then on.
        """
        verb = (action or "").strip().lower()
        if verb not in ("add", "replace", "delete"):
            return (1, "", f"action must be one of: add, replace, delete "
                           f"(got {action!r}).")
        key = (label or "").strip()
        if not key:
            return (1, "", "label is required: it is the key a later "
                           "replace or delete names.")
        clean_reason = scrub((reason or "").strip())
        if not clean_reason:
            return (1, "", "reason is required — say why this belongs in "
                           "memory that every future run will read.")
        clean_source = scrub((source or "").strip())
        if verb != "delete" and not clean_source:
            return (1, "", "source is required: name the evidence this came "
                           "from — a result handle (r3), a run id, or "
                           "'operator'.")

        clause, values = self._where
        if verb == "delete":
            with self._connect() as con:
                cursor = con.execute(
                    f"DELETE FROM blocks WHERE {clause} AND label=?",
                    (*values, key))
                gone = cursor.rowcount
            if not gone:
                return (1, "", f"no core memory block labelled {key!r} for "
                               f"principal {self.principal!r}.")
            return (0, f"deleted core memory block {key!r} ({clean_reason})",
                    "")

        block_kind = (kind or "").strip().lower()
        if block_kind not in BLOCK_KINDS:
            return (1, "", f"kind must be one of: {', '.join(BLOCK_KINDS)} "
                           f"(got {kind!r}).")
        clean_body = scrub((body or "").strip())
        if not clean_body:
            return (1, "", "body is required — the sentence to remember.")

        existing = {block.label for block in self.blocks()}
        if verb == "add" and key in existing:
            return (1, "", f"a block labelled {key!r} is already pinned; use "
                           f"action='replace' to change it.")
        if verb == "replace" and key not in existing:
            return (1, "", f"no block labelled {key!r} to replace; use "
                           f"action='add'.")

        candidate = Block(label=key, kind=block_kind, body=clean_body,
                          reason=clean_reason, source=clean_source,
                          run_id=(run_id or self.run_id),
                          as_of=(as_of or _today()))
        would_cost = self.core_tokens_used(
            candidate, replacing=key if verb == "replace" else "")
        if would_cost > self.core_tokens:
            return (1, "", (
                f"refused: core memory is capped at {self.core_tokens} "
                f"tokens and this would take it to {would_cost}. Core memory "
                f"is pinned into every system turn, so nothing is evicted to "
                f"make room — delete a block you no longer need "
                f"(action='delete') and write this again."))

        with self._connect() as con:
            con.execute(f"DELETE FROM blocks WHERE {clause} AND label=?",
                        (*values, key))
            con.execute(
                "INSERT INTO blocks(principal,skill,label,kind,body,reason,"
                "source,run_id,as_of,ts) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (self.principal, self.skill, key, block_kind, clean_body,
                 clean_reason, clean_source, candidate.run_id,
                 candidate.as_of, int(time.time())))
        return (0, f"{'added' if verb == 'add' else 'replaced'} core memory "
                   f"block {key!r} ({would_cost}/{self.core_tokens} tokens "
                   f"used)", "")

    # ── tier 2: recall ──────────────────────────────────────────────────

    def notes(self) -> List[Note]:
        """Every note in this partition, newest first."""
        return [_note_of(row) for row in self._note_rows("")]

    def _note_rows(self, since: str = "") -> List[Sequence[Any]]:
        """The raw rows, embedding included, newest first."""
        clause, values = self._where
        floor = _epoch(since)
        with self._connect() as con:
            rows = con.execute(
                f"SELECT id,title,body,importance,as_of,sources,run_id,ts,"
                f"embedding FROM notes WHERE {clause} ORDER BY ts DESC, "
                f"id DESC", values).fetchall()
        return [row for row in rows if not floor or int(row[7] or 0) >= floor]

    def add_note(self, title: str, body: str, *, importance: int = 3,
                 sources: Sequence[str] = (), run_id: str = "",
                 as_of: str = "", ts: Optional[int] = None) -> Optional[Note]:
        """Write one note, or ``None`` when it is one this bank already has.

        De-duplicated on ``sha256(title|body)`` inside the partition, which
        is what stops a deployment that runs the same weekly task from
        accumulating fifty copies of the same lesson and then ranking them
        all above everything else.  The body is capped at
        :data:`NOTE_BODY_TOKENS` and scrubbed, for the reason a block is.
        """
        clean_title = scrub((title or "").strip())
        clean_body = _cap(scrub((body or "").strip()), NOTE_BODY_TOKENS)
        if not clean_title or not clean_body:
            return None
        digest = hashlib.sha256(
            f"{clean_title}\x00{clean_body}".encode("utf-8")).hexdigest()
        rating = _rating(importance)
        stamp = int(time.time()) if ts is None else int(ts)
        stamped = as_of or _today()
        listed = [str(source) for source in sources]
        blob = self._embedding(f"{clean_title}. {clean_body}")
        with self._connect() as con:
            cursor = con.execute(
                "INSERT OR IGNORE INTO notes(principal,skill,title,body,"
                "importance,as_of,sources,run_id,digest,embedding,ts) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (self.principal, self.skill, clean_title, clean_body, rating,
                 stamped, json.dumps(listed), run_id or self.run_id, digest,
                 blob, stamp))
            if not cursor.rowcount:
                return None
            note_id = cursor.lastrowid
        return Note(id=note_id, title=clean_title, body=clean_body,
                    importance=rating, as_of=stamped, sources=listed,
                    run_id=run_id or self.run_id, ts=stamp)

    def ranked_notes(self, query: str, *, since: str = "",
                     at: Optional[float] = None) -> List[Note]:
        """Every note that scores above zero for *query*, best first.

        Above zero and not above a threshold: the threshold is
        :meth:`hint`'s business, because an offer nobody asked for has to
        clear a bar that an answer to a direct question does not.
        """
        terms = _terms(query)
        rows = self._note_rows(since)
        if not rows:
            return []
        frequencies: Dict[str, int] = {}
        for row in rows:
            for term in set(_terms(f"{row[1]} {row[2]}")):
                frequencies[term] = frequencies.get(term, 0) + 1
        query_vector = self._embedding(query) if terms else None
        scored: List[Note] = []
        for row in rows:
            note = _note_of(row)
            relevance = _lexical(terms, f"{note.title} {note.body}",
                                 frequencies, len(rows))
            if query_vector is not None and row[8]:
                relevance = max(relevance, _cosine(query_vector, row[8]))
            if relevance <= 0.0:
                continue
            scored.append(_scored(
                note, score(relevance, note.ts, note.importance, at)))
        scored.sort(key=lambda note: (-note.score, -note.ts, -note.id))
        return scored

    def ranked_runs(self, query: str, *, since: str = "",
                    at: Optional[float] = None) -> List[Dict[str, Any]]:
        """The episodic half: past runs that match, best first.

        Read off the :class:`~core.durable.RunStore` and not off a table of
        this module's own.  The run store already holds what happened —
        objective, outcome, answer, in ``meta`` — and a second copy of it
        here would be a second owner of the same fact and the one that goes
        stale.  What comes back is a handle (the ``run_id``) the model can
        read further through, which is the same bargain ``mission_result``
        strikes with a big tool result.

        An episodic hit is rated 3 — the middle — because nobody rated it.
        That leaves recency and relevance to decide its place, rather than
        letting the tier out-rank a note by construction.
        """
        if self.runs is None:
            return []
        try:
            listed = self.runs.list()
        except Exception:                       # pragma: no cover - defensive
            return []
        terms = _terms(query)
        floor = _epoch(since)
        documents: List[Tuple[Any, str, int]] = []
        for run in listed:
            meta = dict(getattr(run, "meta", {}) or {})
            text = " ".join(str(meta.get(key) or "") for key in
                            ("objective", "answer", "outcome", "skill"))
            stamp = _epoch(str(getattr(run, "created_at", "") or ""))
            if floor and stamp and stamp < floor:
                continue
            documents.append((run, text, stamp))
        if not documents:
            return []
        frequencies: Dict[str, int] = {}
        for _run, text, _stamp in documents:
            for term in set(_terms(text)):
                frequencies[term] = frequencies.get(term, 0) + 1
        found: List[Dict[str, Any]] = []
        for run, text, stamp in documents:
            relevance = _lexical(terms, text, frequencies, len(documents))
            if relevance <= 0.0:
                continue
            meta = dict(getattr(run, "meta", {}) or {})
            found.append({
                "handle": str(run.run_id),
                "objective": str(meta.get("objective") or ""),
                "outcome": str(meta.get("outcome") or ""),
                "answer": str(meta.get("answer") or ""),
                "at": str(getattr(run, "created_at", "") or ""),
                "score": score(relevance, stamp, 3, at),
            })
        found.sort(key=lambda hit: -hit["score"])
        return found

    def recall(self, query: str = "", k: int = RECALL_K, kind: str = "",
               since: str = "", handle: str = "",
               **_ignored: Any) -> Tuple[int, str, str]:
        """The recall tool.  ``(exit_code, stdout, stderr)``.

        One tool and not three, and the ``handle`` argument is why: a note
        recalled by query is a summary, and the model that wants the run it
        came out of asks the same tool for the handle rather than learning a
        second name.  ``handle="n7"`` reads one note whole with its sources;
        ``handle="run_…"`` reads that run's objective, outcome and answer.

        Bounded twice over: at most ``k`` results (itself capped at
        :data:`RECALL_K`) and at most :attr:`recall_tokens` of text,
        whichever binds first.  What was cut is said out loud, because a
        model shown four of nine hits and told nothing will believe it has
        seen the bank.
        """
        if (handle or "").strip():
            return self._read_handle(handle.strip())
        wanted = (query or "").strip()
        if not wanted:
            return (1, "", "query is required: say what you are trying to "
                           "remember, in the words you would search for.")
        limit = max(1, min(_as_int(k, RECALL_K), RECALL_K))
        which = (kind or "").strip().lower()
        if which not in ("", "note", "run"):
            return (1, "", f"kind must be 'note', 'run', or omitted for both "
                           f"(got {kind!r}).")

        rendered: List[str] = []
        matched = 0
        if which in ("", "note"):
            hits = self.ranked_notes(wanted, since=since)
            matched += len(hits)
            rendered.extend(note.render() for note in hits[:limit])
        if which in ("", "run") and len(rendered) < limit:
            hits = self.ranked_runs(wanted, since=since)
            matched += len(hits)
            for hit in hits[:limit - len(rendered)]:
                rendered.append(
                    f"{hit['handle']} [{hit['at'][:10]}] past run "
                    f"({hit['outcome'] or 'unknown outcome'})\n"
                    f"    objective: {_cap(hit['objective'], 40)}")

        if not rendered:
            return (0, f"nothing in memory matches {wanted!r}. Nothing is "
                       f"being withheld: this bank holds no note or past run "
                       f"that mentions it.", "")
        kept, dropped = _fit(rendered, self.recall_tokens)
        tail = ""
        if dropped or matched > len(kept):
            tail = (f"\n({matched} matched, {len(kept)} shown — bounded to "
                    f"{self.recall_tokens} tokens. Narrow the query, or read "
                    f"one whole with handle=.)")
        return (0, "\n".join(kept) + tail, "")

    def _read_handle(self, handle: str) -> Tuple[int, str, str]:
        """One note or one past run, whole.  The source read."""
        if handle.startswith("n") and handle[1:].isdigit():
            clause, values = self._where
            with self._connect() as con:
                row = con.execute(
                    f"SELECT id,title,body,importance,as_of,sources,run_id,ts"
                    f" FROM notes WHERE {clause} AND id=?",
                    (*values, int(handle[1:]))).fetchone()
            if row is None:
                return (1, "", f"no note {handle!r} in this bank.")
            note = _note_of(row)
            return (0, f"{note.render()}\n    written during run "
                       f"{note.run_id or '(unrecorded)'}", "")
        if self.runs is None:
            return (1, "", f"{handle!r} is not a note handle (n1, n2, …) and "
                           f"this bank has no run store to read runs from.")
        try:
            run = self.runs.meta(handle)
        except Exception:
            return (1, "", f"no note or past run under handle {handle!r}.")
        meta = dict(getattr(run, "meta", {}) or {})
        return (0, "\n".join([
            f"{run.run_id} [{getattr(run, 'created_at', '')}]",
            f"    objective: {_cap(str(meta.get('objective') or ''), 60)}",
            f"    outcome: {meta.get('outcome') or '(unrecorded)'}",
            f"    answer: {_cap(str(meta.get('answer') or ''), 200)}",
        ]), "")

    # ── the offer: titles, and nothing else ─────────────────────────────

    def hint(self, objective: str, *, at: Optional[float] = None) -> str:
        """``"(2 remembered notes may bear on this: …; …)"``, or ``""``.

        Titles only, and never a body: the whole argument of this module is
        that pulling content in unasked is what simple RAG gets wrong, and a
        title is the smallest thing that lets a model decide whether to ask.
        Nothing scoring above :data:`HINT_THRESHOLD` means silence — an
        empty offer is worse than none, because it teaches the model that
        the bank is empty.

        Rendered into the USER turn beside the objective by
        :meth:`core.runtime.run.Run.seed`, never into the system turn: the
        system turn is the byte-stable prefix a served endpoint caches, and
        a line that changes with the objective would move it every run.
        """
        if self.hint_titles <= 0:
            return ""
        hits = [note for note in self.ranked_notes(objective, at=at)
                if note.score >= HINT_THRESHOLD][:self.hint_titles]
        if not hits:
            return ""
        titles = "; ".join(note.title for note in hits)
        plural = "note" if len(hits) == 1 else "notes"
        return _cap(
            f"({len(hits)} remembered {plural} may bear on this: {titles}. "
            f"Call {MEMORY_RECALL_TOOL} if any of them is worth reading.)",
            HINT_TOKENS)

    # ── the reflection ──────────────────────────────────────────────────

    def reflect(self, *, objective: str, answer: str, evidence: str = "",
                ask: Any = None, run_id: str = "",
                sources: Sequence[str] = ()) -> List[Note]:
        """One bounded call to a model with no tools; up to three notes.

        ``ask`` is :attr:`core.runtime.run.Model.plain` — the same model
        with no tools declared, which is what every other side question in
        this harness is asked through.  Exactly one call, whatever comes
        back, and **any failure is silent**: a reflection happens after the
        run has already answered, and a bank that could fail a finished
        mission would be a memory system that made the harness less reliable
        than not having one.

        What is written is scrubbed, capped and de-duplicated by
        :meth:`add_note`, so a model that returns the same lesson it
        returned last week adds nothing.
        """
        if ask is None:
            return []
        prompt = REFLECTION_PROMPT.format(
            objective=_cap(objective or "", 120),
            answer=_cap(answer or "", 300),
            evidence=_cap(evidence or "(none)", 400),
            max_notes=MAX_NOTES_PER_RUN)
        try:
            reply = ask([{"role": "user", "content": prompt}])
        except Exception:
            return []
        parsed = _first_json_object(reply if isinstance(reply, str)
                                    else str(reply or ""))
        if not parsed:
            return []
        proposed = parsed.get("notes")
        if not isinstance(proposed, list):
            return []
        written: List[Note] = []
        for item in proposed[:MAX_NOTES_PER_RUN]:
            if not isinstance(item, dict):
                continue
            note = self.add_note(
                str(item.get("title") or ""), str(item.get("body") or ""),
                importance=_rating(item.get("importance")),
                sources=sources, run_id=run_id or self.run_id)
            if note is not None:
                written.append(note)
        return written

    # ── the plane ───────────────────────────────────────────────────────

    def tool_names(self) -> List[str]:
        """The two names this bank puts on a plane, in catalogue order."""
        return [MEMORY_RECALL_TOOL, MEMORY_WRITE_TOOL]

    def register_on(self, bus: Any, *, run_id: str = "") -> List[str]:
        """Put the two tools on *bus* for the length of one run.

        Returns **what this call registered**, which is what the caller must
        withdraw — and it is not always both.  A name already on the bus is
        left alone rather than shadowed: a staged turn's sub-mission shares
        its parent's plane, and a child that replaced its parent's
        registration and then withdrew it would take the tools away from the
        turn that is still running.
        :class:`~core.runtime.results.MissionResultStore` refuses a conflict
        loudly instead, and the difference is that its store holds one run's
        results while a bank is the same bank either way.
        """
        self.run_id = run_id or self.run_id
        registered: List[str] = []
        for descriptor, executor in (
            (MEMORY_RECALL_DESCRIPTOR, self._recall_executor()),
            (MEMORY_WRITE_DESCRIPTOR, self._write_executor()),
        ):
            if bus.get_descriptor(descriptor.tool_name) is not None:
                continue
            bus.register(descriptor, executor)
            registered.append(descriptor.tool_name)
        return registered

    def _recall_executor(self):
        def _read(query: str = "", k: int = RECALL_K, kind: str = "",
                  since: str = "", handle: str = "", **_ignored: Any):
            return self.recall(query=query, k=k, kind=kind, since=since,
                               handle=handle)
        _read.__name__ = MEMORY_RECALL_TOOL
        _read.__doc__ = "Reads remembered notes and past runs."
        return _read

    def _write_executor(self):
        def _edit(action: str = "", **kwargs: Any):
            return self.write(action, **{
                name: str(kwargs.get(name) or "") for name in
                ("label", "kind", "body", "reason", "source", "as_of")
            })
        _edit.__name__ = MEMORY_WRITE_TOOL
        _edit.__doc__ = "Adds, replaces or deletes one core memory block."
        return _edit

    # ── embeddings, when a client was configured ────────────────────────

    def _embedding(self, text: str) -> Optional[bytes]:
        """The vector for *text*, or ``None`` on the lexical path.

        ``None`` is the base path and not a degraded one: the whole ranking
        works on :func:`_lexical` with no network at all, and an embedding
        client is an *improvement* a deployment opts into by passing one.
        A client that raises is treated as no client for this call — an
        embedding endpoint being down must not stop a note being written.
        """
        if self._embedding_client is None or not (text or "").strip():
            return None
        try:
            import numpy as np

            from core.memory.memory import normalize
            response = self._embedding_client.embeddings.create(
                input=text[:8000], model=self._embedding_model)
            vector = np.array(response.data[0].embedding, dtype="float32")
            return normalize(vector).tobytes()
        except Exception:
            return None

    # ── operator surface ────────────────────────────────────────────────

    def stats(self) -> Dict[str, Any]:
        """What is in this partition, for the operator CLI."""
        return {
            "path": str(self.db_path),
            "principal": self.principal,
            "skill": self.skill,
            "blocks": len(self.blocks()),
            "core_tokens": self.core_tokens_used(),
            "core_cap": self.core_tokens,
            "notes": len(self.notes()),
            "partitions": self.partitions(),
        }

    def partitions(self) -> List[Tuple[str, str]]:
        """Every ``(principal, skill)`` this file holds, blocks or notes.

        Listed so an operator who mistyped a principal sees an empty
        partition beside the populated one rather than an empty bank.
        """
        with self._connect() as con:
            rows = con.execute(
                "SELECT DISTINCT principal, skill FROM blocks "
                "UNION SELECT DISTINCT principal, skill FROM notes "
                "ORDER BY 1, 2").fetchall()
        return [(row[0], row[1]) for row in rows]

    def purge(self, *, notes: bool = True, blocks: bool = False) -> int:
        """Delete this partition's notes, and its blocks if asked.  Count."""
        clause, values = self._where
        gone = 0
        with self._connect() as con:
            if notes:
                gone += con.execute(
                    f"DELETE FROM notes WHERE {clause}", values).rowcount
            if blocks:
                gone += con.execute(
                    f"DELETE FROM blocks WHERE {clause}", values).rowcount
        return gone


# ── small shared helpers ────────────────────────────────────────────────────


def _core_text(policy: str, blocks: Sequence[Block]) -> str:
    """The rendered core section.  ONE renderer, two callers.

    :meth:`MemoryBank.core` renders what a system turn gets and
    :meth:`MemoryBank.core_tokens_used` measures what a *candidate* write
    would cost.  If those two disagreed by so much as a heading, the cap
    would be enforced against a string nothing ever sends.
    """
    parts = [policy]
    if blocks:
        parts.append("Core memory (kept between runs):\n"
                     + "\n".join(block.render() for block in blocks))
    return "\n\n".join(parts)


def _today() -> str:
    """Today, as the date a block or note was true on."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _epoch(stamp: str) -> int:
    """An ISO date or timestamp as seconds, or ``0`` when unreadable."""
    text = (stamp or "").strip().replace("Z", "")
    if not text:
        return 0
    for shape, width in (("%Y-%m-%dT%H:%M:%S", 19), ("%Y-%m-%d %H:%M:%S", 19),
                         ("%Y-%m-%d", 10)):
        try:
            parsed = datetime.strptime(text[:width], shape)
        except ValueError:
            continue
        return int(parsed.replace(tzinfo=timezone.utc).timestamp())
    return 0


def _cap(text: str, tokens: int) -> str:
    """*text*, cut to *tokens* with a marker, through the one estimator."""
    body = text or ""
    if estimate_tokens(body) <= tokens:
        return body
    return body[:max(0, tokens * 4 - 1)].rstrip() + "…"


def _fit(blocks: Sequence[str], budget: int) -> Tuple[List[str], bool]:
    """As many whole blocks as fit in *budget*.  ``(kept, anything dropped)``.

    Whole blocks: half a note is a note whose date is missing, and the date
    is the half that says when it was true.  The first block is always kept
    — a budget so small that nothing fits is a misconfiguration, and
    answering it with silence would look like an empty bank.
    """
    kept: List[str] = []
    used = 0
    for block in blocks:
        cost = estimate_tokens(block) + 1
        if kept and used + cost > budget:
            return kept, True
        kept.append(block)
        used += cost
    return kept, False


def _rating(value: Any) -> int:
    """A model's ``importance``, clamped to 1–5; 3 when it wrote nonsense."""
    try:
        return max(1, min(5, int(value)))
    except (TypeError, ValueError):
        return 3


def _as_int(value: Any, fallback: int) -> int:
    """An integer argument a model supplied, or *fallback*."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _note_of(row: Sequence[Any]) -> Note:
    try:
        sources = json.loads(row[5] or "[]")
    except ValueError:
        sources = []
    return Note(id=row[0], title=row[1], body=row[2],
                importance=int(row[3] or 3), as_of=row[4],
                sources=([str(source) for source in sources]
                         if isinstance(sources, list) else []),
                run_id=row[6], ts=int(row[7] or 0))


def _scored(note: Note, value: float) -> Note:
    return Note(id=note.id, title=note.title, body=note.body,
                importance=note.importance, as_of=note.as_of,
                sources=list(note.sources), run_id=note.run_id, ts=note.ts,
                score=value)


def _cosine(left: Optional[bytes], right: Optional[bytes]) -> float:
    """Cosine of two stored vectors, in ``[0, 1]``; ``0`` on any mismatch.

    Both are normalized at write time (:meth:`MemoryBank._embedding` goes
    through :func:`core.memory.memory.normalize`, which is the one owner of
    that), so the inner product IS the cosine and there is nothing to divide
    by here.  Negative similarities are clamped: this factor multiplies, and
    a negative would flip the sign of a score.
    """
    if not left or not right:
        return 0.0
    try:
        import numpy as np
        one = np.frombuffer(left, dtype="float32")
        other = np.frombuffer(right, dtype="float32")
        if one.shape != other.shape or one.size == 0:
            return 0.0
        return max(0.0, float(one @ other))
    except Exception:                           # pragma: no cover - defensive
        return 0.0
