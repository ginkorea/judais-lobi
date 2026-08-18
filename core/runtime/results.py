# core/runtime/results.py — everything a mission's tools returned, kept whole

"""A per-mission store of full tool results, and one tool to read them.

The transcript a model sees is bounded; what the tools returned is not.
Those two facts are only compatible if the full result survives
somewhere addressable, which is what this is.

Why it exists.  A governed view of a finished run is large — tens of
thousands of records, every one with identifiers, scores and
coordinates.  Pasting one whole into the transcript costs the context
that the *earlier* steps occupy, so the model loses the catalogue
lookups that told it what the numbers mean; past ``max_model_len`` it
loses them without being told.  Truncating instead, and saying nothing,
is worse: the model then restates a figure from the part it can still
see, or from memory, and a persona rule against exactly that cannot help
because nothing in the prompt reveals that anything is missing.

So: the transcript gets head and tail with an explicit marker, the whole
thing stays here under a short handle, and the model can ask for one
field.  ``mission_result(handle="r3", path="actors[0].score")`` is a few
dozen bytes instead of two hundred kilobytes, and the value it returns is
the value the tool returned.

The store holds **no** capability of its own.  It reaches nothing: every
byte in it arrived through a ``ToolBus.dispatch`` that was already gated,
audited and — where a skill supplied a closed set — inside it.  Reading
back what this mission was already given is not a widening of that set,
and the tool is registered for the duration of one run and withdrawn
after it.
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from core.tools.descriptors import ToolDescriptor

#: The tool a mission calls to read the store.  Flat, like the other
#: compiled-in tools (``fs``, ``git``) and unlike a bridged name, because
#: it is local and always has been.
RESULT_TOOL = "mission_result"

#: ``actors[0].score`` -> ``["actors", 0, "score"]``
_INDEX = re.compile(r"\[(-?\d+)\]")

#: The arguments that read a result's TEXT rather than its payload, named
#: once because three callers have to spell them the same: the executor,
#: :class:`BranchedStores` routing to a child's store, and
#: :meth:`MissionResultStore.read`.
PAGING = ("offset", "limit", "lines", "grep")

#: ``lines=12-40``, ``lines=12-`` or ``lines=12``.  One line is a range of
#: one; an open end runs to the end of the text.
_LINES = re.compile(r"^\s*(\d+)\s*(?:-\s*(\d*)\s*)?$")

#: How many matching lines a ``grep`` answers with when the caller named no
#: ``limit``.  Bounded for the reason every other result is: a regex that
#: matches most of a 40 KB log would otherwise paste the log back in.
DEFAULT_MATCHES = 40


def paging_of(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Just the :data:`PAGING` arguments out of *arguments*.

    A filter and not a signature, so a caller forwarding a model's
    keywords — :class:`BranchedStores` does — passes on the four this
    store reads and nothing else.  The loop adds its own
    :data:`BRANCH_ARGUMENT` to a store dispatch, and a model can write
    anything at all.
    """
    return {key: arguments[key] for key in PAGING if key in arguments}


class ResultStoreConflict(RuntimeError):
    """Something is already registered under the store's tool name."""


class SourcedEvidence(str):
    """One evidence text, with the call that produced it still attached.

    A ``str`` first and above all.  Every consumer of
    :meth:`MissionResultStore.evidence_texts` reads evidence as text, a
    library caller hands a validator plain strings, and neither may have
    to learn a new type — so this adds an attribute and changes nothing
    else about how an evidence text behaves.

    What it adds is the one fact a plain string throws away: **which call
    wrote this, and what that call was given**.  A grounding check needs
    both halves of a code-plane call to tell a computed figure from an
    echoed one — a model told a figure is unsupported can run
    ``print('30,000')`` and re-submit, and its stdout is a tool result
    like any other.  See
    :class:`~core.runtime.grounding.NumericGroundingCheck`, which is the
    one reader of these two attributes.

    Class-level defaults so that ``getattr(text, "arguments", "")`` reads
    the same on a plain ``str`` and on one of these: a caller who built
    the evidence list by hand is not carrying provenance, and the check
    must treat that as "nothing known", never as "nothing echoed".
    """

    #: The wire name of the tool whose result this is.
    tool: str = ""
    #: That call's arguments as text — what the MODEL wrote, not what the
    #: tool returned.  See :attr:`StoredResult.arguments_text`.
    arguments: str = ""
    #: True where this text is what the model **sent**, not what the plane
    #: returned.  Only a failed call contributes one; see
    #: :meth:`MissionResultStore.evidence_texts`.  A check that grades
    #: whether a figure came out of a tool must skip these, or the model
    #: grounds its own arithmetic by typing it into a call that fails.
    sent: bool = False

    def __new__(cls, text: Any, *, tool: str = "", arguments: str = "",
                sent: bool = False) -> "SourcedEvidence":
        self = super().__new__(cls, text)
        self.tool = str(tool or "")
        self.arguments = str(arguments or "")
        self.sent = bool(sent)
        return self


@dataclass(frozen=True)
class StoredResult:
    """One tool call, kept whole."""

    handle: str
    tool: str
    arguments: Dict[str, Any] = field(default_factory=dict)
    #: Exactly what the tool wrote, before any bounding.
    text: str = ""
    #: The typed payload as JSON text, when the tool returned one.
    evidence: str = ""
    exit_code: int = 0

    @property
    def structured(self) -> Any:
        """The typed payload, parsed, or ``None``."""
        if not self.evidence:
            return None
        try:
            return json.loads(self.evidence)
        except json.JSONDecodeError:
            return None

    @property
    def succeeded(self) -> bool:
        return self.exit_code == 0

    @property
    def arguments_text(self) -> str:
        """This call's arguments as one string, for searching.

        JSON with sorted keys, so the same call renders the same way
        twice and a reader comparing two of them is comparing the calls.
        ``default=str`` because an argument that is not JSON-serialisable
        is still an argument the model wrote, and a rendering that raised
        here would take a whole grounding check down with it.
        """
        if not self.arguments:
            return ""
        try:
            return json.dumps(self.arguments, sort_keys=True, default=str)
        except (TypeError, ValueError):       # pragma: no cover - defensive
            return str(self.arguments)

    @property
    def ran(self) -> bool:
        """Whether a tool was reached and answered, whatever it answered.

        The distinction :attr:`succeeded` cannot make, and the one
        :meth:`MissionResultStore.evidence_texts` needs: ``-1`` is the
        bus's number for a call that never got to a tool — an unknown
        name, a capability refusal, an exception inside dispatch — and
        anything from ``0`` upwards is a tool's own exit code. A failing
        test suite is not an absent result; it is the result.
        """
        return self.exit_code >= 0


class MissionResultStore:
    """Full results for one mission, addressed by handle.

    One store per mission, not per process: handles are short (``r1``,
    ``r2``) so a model can quote them, and short handles are only
    unambiguous inside one run.
    """

    #: A returned field is bounded too. A store that answered a `path` of
    #: `""` with the whole payload would be a way of pasting back in
    #: exactly what the cap took out.
    DEFAULT_MAX_CHARS = 4_000

    def __init__(self, *, max_chars: int = DEFAULT_MAX_CHARS):
        self._results: List[StoredResult] = []
        self._by_handle: Dict[str, StoredResult] = {}
        self._max_chars = max_chars

    def __len__(self) -> int:
        return len(self._results)

    @property
    def results(self) -> List[StoredResult]:
        return list(self._results)

    def clear(self) -> None:
        self._results.clear()
        self._by_handle.clear()

    # ── recording ───────────────────────────────────────────────────────

    def record(
        self,
        tool: str,
        arguments: Optional[Dict[str, Any]] = None,
        *,
        text: str = "",
        evidence: str = "",
        exit_code: int = 0,
    ) -> StoredResult:
        """Keep one result whole and return its handle."""
        stored = StoredResult(
            handle=f"r{len(self._results) + 1}",
            tool=tool,
            arguments=dict(arguments or {}),
            text=text or "",
            evidence=evidence or "",
            exit_code=exit_code,
        )
        self._results.append(stored)
        self._by_handle[stored.handle] = stored
        return stored

    def get(self, handle: str) -> Optional[StoredResult]:
        return self._by_handle.get(handle)

    def first_identical(self, stored: StoredResult) -> Optional[StoredResult]:
        """An earlier result of the same call with the same bytes, or ``None``.

        Recorded 10 August 2026: a Qwen3-30B mission called ``runs_get`` on
        the *same* ``run_id`` at turns 1, 2 and 4 and died at turn 5 on a
        context overflow that had nothing to do with a long conversation.
        Three copies of one 33,000-character view sat in a history nothing
        trims, and ``mission_result`` — which exists for exactly that, with
        the handle named in the truncation marker of all three turns — was
        never called.

        Compared on **bytes**, not on the call, and that is the whole
        subtlety.  Refusing a repeated call outright would be wrong here:
        this platform is submit-and-poll, and ``compute_job_status`` asked
        twice is a mission working correctly.  A poll that returns something
        new differs in its bytes and is shown in full; a re-fetch of an
        unchanged view does not, and that is the case worth collapsing.  So
        the call is always made and the *rendering* is what gets
        deduplicated — which needs no idempotency flag, and none is
        available: the MCP bridge does not carry the platform's
        ``idempotent`` across.

        Only successful results, and only against successful ones.  Two
        identical refusals are two different problems for the model to read,
        and the loop already tells it not to retry an unchanged call.
        """
        if not stored.succeeded:
            return None
        for earlier in self._results:
            if earlier.handle == stored.handle:
                break
            if (earlier.succeeded
                    and earlier.tool == stored.tool
                    and earlier.arguments == stored.arguments
                    and earlier.text == stored.text
                    and earlier.evidence == stored.evidence):
                return earlier
        return None

    def evidence_texts(self) -> List[str]:
        """What this run established, for a grounding validator.

        Three rules, each load-bearing, each with the failure that wrote it.

        **A successful result** contributes its full text — not the bounded
        rendering the model saw — and its typed payload as well: an
        identifier the model correctly read out of a structured field is
        grounded even though the text block never spelled it.

        **A failed result from a tool whose failures ARE results** — declared
        by :attr:`~core.tools.descriptors.ToolDescriptor.failure_is_a_result`
        (today ``verify``), read through
        :func:`~core.tools.descriptors.failure_reporting_tools` and matched
        with :func:`~core.tools.descriptors.same_tool` — contributes exactly as
        a success does.  A failing test suite has not failed to produce a
        result; "1 failed, 1 passed" is the most important thing a coding
        mission learns, and filtering it out made an agent that truthfully
        reported the red run come back ungrounded (the 10 August failure in a
        new place).  Declared, not guessed: what a non-zero exit MEANS is a
        fact only that tool can state — ``mcp.run_code`` crashing and printing
        ``Traceback … gradient was 3.1416`` computed no gradient
        (``tests/test_grounding_code_is_not_a_claim.py``).

        **Any other failed result** contributes its typed error payload and
        the arguments it was called with, and nothing else.  A refusal is
        still something this run did: *"I could not read that page — it
        answered 404"* is a claim about the run, and before this the URL and
        the status could not be grounded by the very call that demonstrates
        them — the same reasoning :meth:`called_tools` applies.  Two things it
        deliberately does NOT contribute: its **free text** (an error message
        is prose written by whatever was on the other end), and its arguments
        as an ordinary result — they are marked :attr:`SourcedEvidence.sent`,
        because they are what the MODEL wrote, and a check grading whether a
        figure came out of a tool must skip them, or a figure grounds itself
        by being typed into a call that fails.

        **A call that never reached a tool at all is never evidence**, whatever
        it declares: ``exit_code == -1`` is the bus's own number for an unknown
        name, a capability refusal or an exception in dispatch, and what those
        carry is this harness's words about why it said no.

        Each entry is a :class:`SourcedEvidence` — a ``str``, so nothing that
        reads this list has to know — carrying the tool that wrote it and the
        arguments it was called with.  **The pairing is made here and only
        here.**  A check that re-derived "which call produced this text" by
        matching strings back against the store would be a second owner of a
        fact this loop already has in hand, and the one that goes wrong the
        day two calls return the same bytes.
        """
        from core.tools.descriptors import failure_reporting_tools, same_tool

        reporting = failure_reporting_tools()
        texts: List[str] = []
        for stored in self._results:
            if not stored.ran:
                continue
            arguments = stored.arguments_text
            reports = stored.succeeded or any(
                same_tool(stored.tool, name) for name in reporting)
            if reports:
                returned = ((stored.text, False), (stored.evidence, False))
            else:
                returned = ((stored.evidence, False), (arguments, True))
            for text, sent in returned:
                if text:
                    texts.append(SourcedEvidence(
                        text, tool=stored.tool, arguments=arguments,
                        sent=sent))
        return texts

    def called_tools(self) -> List[str]:
        """Every tool this run dispatched, once each, in the order called.

        **The one owner of "what was called this run."**  The store already
        holds it — one entry per dispatch, recorded as it happened — and the
        alternative is reading the conversation back and counting tool
        messages, which is a second owner of the same fact and the one that
        goes wrong the day a call is made somewhere the messages do not show
        it.  See :meth:`~core.runtime.grounding.GroundingCheck.observing`,
        which is the consumer.

        A call that **failed** still counts.  The question this answers is
        whether the plane was used, not whether it worked; an answer saying
        "I ran the code" after a run that exited non-zero was at least
        dispatched, and what it produced is the other checks' business.
        """
        names: List[str] = []
        for stored in self._results:
            if stored.tool and stored.tool not in names:
                names.append(stored.tool)
        return names

    # ── the tool ────────────────────────────────────────────────────────

    def descriptor(self, name: str = RESULT_TOOL) -> ToolDescriptor:
        """The ``ToolDescriptor`` for reading this store.

        **It does not yet advertise the paging arguments, and that is a
        sequencing decision rather than an oversight.**  This description
        and this schema are rendered into the SYSTEM TURN by
        :meth:`core.runtime.run.Run.catalogue`, the committed corpus is
        recorded against those bytes, and a served endpoint's prefix cache
        is keyed on them — so the sentence that teaches a model to page
        lands with the re-recording, in the one lane that moves prompt
        bytes, and not from four lanes at once.  :meth:`read` accepts
        ``offset``/``limit``/``lines``/``grep`` NOW; nothing tells the
        model about them until this descriptor does.

        What is to be added, verbatim, when the corpus is re-recorded: the
        sentence ``A text-only result is read by page: offset/limit in
        characters, lines="12-40", or grep="<regex>" for matching lines
        with their numbers.`` after "…named in the truncation marker.",
        and four properties beside ``path`` — ``offset`` (integer, "Start
        of a page of the result's TEXT, in characters."), ``limit``
        (integer, "How much of the text to return, in characters; with
        `grep`, how many matching lines."), ``lines`` (string, "A 1-based
        inclusive line range of the text, e.g. 12-40, or 12- to the
        end."), ``grep`` (string, "Return the lines of the text matching
        this regular expression, with their line numbers.").
        """
        return ToolDescriptor(
            tool_name=name,
            required_scopes=[],
            description=(
                "Read one field of a full tool result this mission already "
                "received. Large results are shown truncated in the "
                "transcript; the whole result is kept under a handle "
                "(r1, r2, ...) named in the truncation marker. Reaches "
                "nothing new — only what this mission was already given."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "handle": {
                        "type": "string",
                        "description": "The handle from a truncation marker, "
                                       "e.g. r3. Omit to list the handles.",
                    },
                    "path": {
                        "type": "string",
                        "description": "Field path into the structured "
                                       "payload, e.g. actors[0].score. Omit "
                                       "for a summary of what is there.",
                    },
                },
                "required": [],
            },
        )

    def executor(self):
        """The callable ``ToolBus`` dispatches for :meth:`descriptor`.

        The paging arguments are forwarded through :func:`paging_of`
        rather than named again here: :class:`BranchedStores` has the same
        line, and two hand-written signatures are how one of them stops
        carrying an argument the other does.
        """
        def _read(handle: str = "", path: str = "", **rest: Any):
            return self.read(handle, path, **paging_of(rest))
        _read.__name__ = RESULT_TOOL
        _read.__doc__ = "Reads one field of a stored mission result."
        return _read

    def register_on(self, bus: Any, name: str = RESULT_TOOL,
                    executor: Optional[Any] = None) -> str:
        """Register the read tool on *bus*; refuse to shadow anything.

        Loud rather than clever: silently replacing a registered tool
        called ``mission_result`` would remove a capability the operator
        configured, and restoring it on withdrawal would be a second
        thing to get wrong.

        *executor* is for :class:`BranchedStores`, which puts **one**
        descriptor on the bus in front of several stores.  The descriptor
        is this store's either way — the bytes the model reads are the same
        bytes whichever store answers — and the refusal above stays the one
        owner of "will not shadow".  ``None`` is every other caller and
        registers this store's own reader.
        """
        if bus.get_descriptor(name) is not None:
            raise ResultStoreConflict(
                f"{name!r} is already registered on this bus. The mission "
                f"result store will not shadow it — pass a different name."
            )
        bus.register(self.descriptor(name),
                     self.executor() if executor is None else executor)
        return name

    # ── reading ─────────────────────────────────────────────────────────

    def read(self, handle: str = "", path: str = "", *,
             offset: Any = 0, limit: Any = 0, lines: str = "",
             grep: str = "") -> Tuple[int, str, str]:
        """``(exit_code, stdout, stderr)`` — the ToolBus executor shape.

        Two readers, and which one runs is decided by what was asked for.

        ``path`` walks the **typed payload**: one field, by name.  It is
        the original reader and it is what a governed view wants.

        :data:`PAGING` — ``offset``/``limit`` in characters, ``lines=A-B``,
        ``grep=<regex>`` — reads the **text**, and it is the answer to a
        defect the coding pack recorded (lane N, 18 August 2026): a 40 KB
        test log is bounded head-and-tail with a marker naming its handle,
        and ``read(handle)`` with no ``path`` then returned a *summary*.
        There was no way to see the middle at all, and the pack's skill
        worked round it by telling the model to re-read files with ``fs``
        — content standing in for a harness property, and no use whatever
        for a log that was never a file.

        The two are not combined.  A call naming both is refused rather
        than served under a precedence rule nobody can see from the
        outside: a model that asked for a field of a payload and got a
        slice of the rendered text would quote the slice.
        """
        if not (handle or "").strip():
            return (0, self._index(), "")

        stored = self._by_handle.get(handle.strip())
        if stored is None:
            return (1, "", (
                f"No result under handle {handle!r} in this mission. "
                f"Handles: {', '.join(self._by_handle) or '(none yet)'}."
            ))

        asked = self._paging_asked(offset, limit, lines, grep)
        if asked and (path or "").strip():
            listed = ", ".join(f"`{name}`" for name in asked)
            return (1, "", (
                f"{stored.handle}: two readers in one call — `path` reads "
                f"one field of the typed payload, {listed} names a part of "
                f"its text. Call this tool with one of them."
            ))
        if asked:
            return self._page(stored, offset=offset, limit=limit,
                              lines=lines, grep=grep)

        if not (path or "").strip():
            return (0, self._summary(stored), "")

        structured = stored.structured
        if structured is None:
            return (1, "", (
                f"{stored.handle} has no structured payload, so there is no "
                f"field {path!r} to read. Its text is {len(stored.text)} "
                f"characters; call this tool with just the handle for a "
                f"summary."
            ))

        value, problem = walk_path(structured, path.strip())
        if problem:
            return (1, "", f"{stored.handle}: {problem}")
        return (0, self._render(value), "")

    # ── paging a text result ────────────────────────────────────────────
    #
    # One owner of "read part of a result's text". The loop's truncation
    # marker names the handle; this is what the handle is then good for
    # when the result was never JSON. Every page is bounded by the same
    # `_max_chars` a field read is, so no argument here is a way of
    # pasting back in exactly what the transcript cap took out — the
    # caller pages, and each page costs what a field costs.

    @classmethod
    def _paging_asked(cls, offset: Any, limit: Any, lines: Any,
                      grep: Any) -> Tuple[str, ...]:
        """Which of :data:`PAGING` the caller actually wrote, in order.

        A zero and an empty string are *not written*: they are the
        defaults every executor passes, and reading them as a request
        would turn ``read("r3")`` into a page of the first nothing
        characters.
        """
        named = {"offset": offset, "limit": limit,
                 "lines": lines, "grep": grep}
        return tuple(key for key in PAGING if cls._named(named[key]))

    @staticmethod
    def _named(value: Any) -> bool:
        text = "" if value is None else str(value).strip()
        return bool(text) and text != "0"

    def _page(self, stored: StoredResult, *, offset: Any, limit: Any,
              lines: str, grep: str) -> Tuple[int, str, str]:
        """The text reader: a slice, a line range, or matching lines.

        The three do not compose, and a call that mixes them is refused by
        name.  ``limit`` is the exception and it is not one: with ``grep``
        it bounds the **matches**, which is the same word meaning the same
        thing — how much of this you get back.
        """
        if not stored.text:
            return (1, "", (
                f"{stored.handle}: {stored.tool} returned no text to page. "
                f"Call this tool with just the handle for a summary of what "
                f"it did return."
            ))
        if self._named(grep):
            clash = [name for name, value in
                     (("offset", offset), ("lines", lines))
                     if self._named(value)]
            if clash:
                return (1, "", (
                    f"{stored.handle}: `grep` searches the whole text and "
                    f"{', '.join(clash)} names a part of it. Pass one; with "
                    f"`grep`, `limit` bounds how many matching lines come "
                    f"back."
                ))
            return self._grep(stored, str(grep), limit)
        if self._named(lines):
            if self._named(offset) or self._named(limit):
                return (1, "", (
                    f"{stored.handle}: `lines` and `offset`/`limit` are two "
                    f"ways of naming a part of the text — one counts lines "
                    f"and the other counts characters. Pass one."
                ))
            return self._lines(stored, str(lines))
        return self._slice(stored, offset, limit)

    def _slice(self, stored: StoredResult, offset: Any,
               limit: Any) -> Tuple[int, str, str]:
        """``offset``/``limit`` characters of the text."""
        start, problem = _as_count(offset, "offset")
        if problem:
            return (1, "", f"{stored.handle}: {problem}")
        want, problem = _as_count(limit, "limit")
        if problem:
            return (1, "", f"{stored.handle}: {problem}")
        text = stored.text
        if start >= len(text):
            return (1, "", (
                f"{stored.handle}: offset {start} is past the end — the text "
                f"is {len(text)} characters."
            ))
        want = min(want or self._max_chars, self._max_chars)
        page = text[start:start + want]
        end = start + len(page)
        header = (
            f"{stored.handle}: {stored.tool}, characters {start}-{end} of "
            f"{len(text)}."
        )
        more = "" if end >= len(text) else (
            f"\n… [{len(text) - end} characters after this. Next page: "
            f'{RESULT_TOOL}(handle="{stored.handle}", offset={end}).]'
        )
        return (0, f"{header}\n{page}{more}", "")

    def _lines(self, stored: StoredResult, spec: str) -> Tuple[int, str, str]:
        """``lines=A-B`` of the text, 1-based and inclusive."""
        match = _LINES.match(spec)
        if not match:
            return (1, "", (
                f"{stored.handle}: `lines` is {spec!r}; it is a 1-based "
                f"inclusive range — `lines=\"12-40\"`, `lines=\"12-\"` to the "
                f"end, or `lines=\"12\"` for one line."
            ))
        rows = stored.text.splitlines()
        first = int(match.group(1))
        tail = match.group(2)
        if first < 1:
            return (1, "", (
                f"{stored.handle}: `lines` counts from 1, not from 0."
            ))
        if first > len(rows):
            return (1, "", (
                f"{stored.handle}: line {first} is past the end — the text "
                f"is {len(rows)} lines."
            ))
        if tail is None:
            last = first
        else:
            last = int(tail) if tail else len(rows)
        if last < first:
            return (1, "", (
                f"{stored.handle}: `lines` is {spec!r}; the range ends "
                f"before it begins."
            ))
        last = min(last, len(rows))
        body, cut = self._bounded("\n".join(rows[first - 1:last]))
        header = (
            f"{stored.handle}: {stored.tool}, lines {first}-{last} of "
            f"{len(rows)}."
        )
        return (0, f"{header}\n{body}{cut}", "")

    def _grep(self, stored: StoredResult, pattern: str,
              limit: Any) -> Tuple[int, str, str]:
        """Matching lines of the text, with their line numbers."""
        want, problem = _as_count(limit, "limit")
        if problem:
            return (1, "", f"{stored.handle}: {problem}")
        try:
            expression = re.compile(pattern)
        except re.error as exc:
            return (1, "", (
                f"{stored.handle}: `grep` is not a usable regular "
                f"expression: {exc}"
            ))
        rows = stored.text.splitlines()
        hits = [(n, row) for n, row in enumerate(rows, start=1)
                if expression.search(row)]
        if not hits:
            return (0, (
                f"{stored.handle}: {stored.tool}, no line of {len(rows)} "
                f"matches {pattern!r}."
            ), "")
        want = want or DEFAULT_MATCHES
        shown = hits[:want]
        body, cut = self._bounded(
            "\n".join(f"{n}: {row}" for n, row in shown))
        header = (
            f"{stored.handle}: {stored.tool}, {len(shown)} of {len(hits)} "
            f"lines matching {pattern!r} ({len(rows)} lines in all)."
        )
        rest = "" if len(shown) == len(hits) else (
            f"\n… [{len(hits) - len(shown)} more matching lines; raise "
            f"`limit`, or read around one of these with `lines`.]"
        )
        return (0, f"{header}\n{body}{cut}{rest}", "")

    def _bounded(self, body: str) -> Tuple[str, str]:
        """``(body, note)`` — the page cut to this store's cap, and why.

        The same ``_max_chars`` a field read is bounded by, because it is
        the same question: how much of one result may be pasted back into
        a transcript that already bounded it once.
        """
        if len(body) <= self._max_chars:
            return body, ""
        return body[:self._max_chars], (
            f"\n… [page cut at {self._max_chars} characters, this store's "
            f"limit; ask for a narrower range]"
        )

    def _index(self) -> str:
        if not self._results:
            return "No results stored yet in this mission."
        lines = ["Stored results in this mission:"]
        for stored in self._results:
            typed = "typed payload" if stored.evidence else "text only"
            lines.append(
                f"- {stored.handle}: {stored.tool} — {len(stored.text)} "
                f"characters, {typed}"
            )
        return "\n".join(lines)

    def _summary(self, stored: StoredResult) -> str:
        structured = stored.structured
        lines = [
            f"{stored.handle}: {stored.tool}({_args(stored.arguments)}) — "
            f"{len(stored.text)} characters of text."
        ]
        if structured is None:
            lines.append(
                "No structured payload; the text is the whole result."
            )
        else:
            lines.append(f"Structured payload: {_shape(structured)}")
            lines.append(
                "Read one field with "
                f'{RESULT_TOOL}(handle="{stored.handle}", path="...").'
            )
        return "\n".join(lines)

    def _render(self, value: Any) -> str:
        if isinstance(value, str):
            text = value
        else:
            text = json.dumps(value, ensure_ascii=False, indent=2, default=str)
        if len(text) <= self._max_chars:
            return text
        return (
            text[:self._max_chars]
            + f"\n… [field truncated at {self._max_chars} characters of "
              f"{len(text)}; ask for a narrower path]"
        )


#: The keyword the loop puts on its own store dispatch to say which child is
#: asking.  The model never writes it — it is not in the descriptor's
#: ``input_schema`` and the loop adds it after the schema check, to the
#: mission's **own** tool and to nothing else, which is why it is not the
#: invented-argument problem :func:`core.runtime.mission._takes_deadline`
#: exists to avoid.  Named here because two modules have to spell it the same.
BRANCH_ARGUMENT = "branch"


class BranchedStores:
    """One ``mission_result`` on the bus, several stores behind it.

    A staged turn's children each keep their **own** results — a step's
    handles are that step's, its grounding evidence is what *it* read, and
    a store cleared at the top of one run must not be the store a sibling
    is still reading.  But the tool that reads them has one name, because
    the name is in the protocol text every child is given: two children
    told to call two different tools would be two different prompts for
    the same job, and a served endpoint's prefix cache is keyed on bytes.

    So the *descriptor* is registered once, by whichever child opens first,
    and withdrawn by whichever closes last; the *executor* is this class,
    and it routes on the branch the caller named.  The alternative —
    a namespaced tool per child — collides with the closed set as well:
    ``Run._relearn_the_plane`` would read a sibling's ``mission_result@s2``
    as a tool the bus had *grown* and, with no ``admits`` to say otherwise,
    offer it.

    ``MissionResultStore.register_on`` is still the one owner of "put this
    on the bus, and refuse to shadow anything already there".
    """

    def __init__(self) -> None:
        # A lock and not an assumption about the loop: children share one
        # asyncio loop today, and `Run.run` on a thread is a supported way
        # in. Registration is a read of the bus and a write to it.
        self._lock = threading.Lock()
        self._stores: Dict[str, "MissionResultStore"] = {}
        self._name = ""
        self._open = 0

    def __len__(self) -> int:
        """How many branches are holding this registration open."""
        return self._open

    def open(self, bus: Any, name: str, branch: str,
             results: "MissionResultStore") -> str:
        """Publish *results* for *branch*; register once.  Returns the name.

        The name comes back so the caller can hold it as the flag it
        already held — "this run put something on the bus and owes a
        withdrawal" — whether or not this particular child was the one
        that did the registering.
        """
        with self._lock:
            self._stores[str(branch or "")] = results
            if not self._open:
                self._name = results.register_on(bus, name, self._read)
            self._open += 1
            return self._name

    def close(self, bus: Any, branch: str) -> None:
        """Drop *branch*'s store, and the descriptor with the last one.

        Withdrawn rather than left there for the reason one store's was:
        the bus outlives the run, and a descriptor that stayed would offer
        the next mission a handle into this one's governed material.
        """
        with self._lock:
            self._stores.pop(str(branch or ""), None)
            self._open = max(0, self._open - 1)
            if self._open or not self._name:
                return
            bus.unregister(self._name)
            self._name = ""

    def _read(self, handle: str = "", path: str = "",
              branch: str = "", **rest: Any) -> Tuple[int, str, str]:
        """The executor the bus dispatches: one call, routed to one store."""
        with self._lock:
            store = self._stores.get(str(branch or ""))
        if store is None:
            # A branch nobody published, which is a harness defect rather
            # than anything the model did — so it is said plainly and the
            # step is not told it asked for something impossible.
            return (1, "", (
                f"no result store is open for branch {branch!r} in this "
                f"mission. Nothing was lost: this is the harness's own "
                f"bookkeeping and the result is still in the transcript."
            ))
        return store.read(handle, path, **paging_of(rest))


def _as_count(value: Any, name: str) -> Tuple[int, str]:
    """``(count, problem)`` — exactly one is meaningful.

    A model writes ``offset=4000`` under the native protocol and
    ``offset="4000"`` under the JSON one, and both mean the same thing;
    ``offset="soon"`` means nothing and is refused by name rather than
    quietly read as zero, which would answer a question nobody asked with
    the first page.
    """
    if value is None or str(value).strip() == "":
        return 0, ""
    try:
        count = int(str(value).strip())
    except (TypeError, ValueError):
        return 0, f"`{name}` is {value!r}; it is a whole number"
    if count < 0:
        return 0, f"`{name}` is {count}; it counts forward from the start"
    return count, ""


def _args(arguments: Dict[str, Any]) -> str:
    return ", ".join(f"{k}={v!r}" for k, v in arguments.items())


def _shape(value: Any) -> str:
    """What is in there, in one line, without printing it."""
    if isinstance(value, dict):
        keys = list(value)
        shown = ", ".join(str(k) for k in keys[:20])
        rest = f", +{len(keys) - 20} more" if len(keys) > 20 else ""
        return f"object with keys: {shown}{rest}"
    if isinstance(value, list):
        first = f", first item {_shape(value[0])}" if value else ""
        return f"array of {len(value)}{first}"
    return type(value).__name__


def walk_path(value: Any, path: str) -> Tuple[Any, str]:
    """``(value, problem)``; exactly one is meaningful.

    A path that misses says what *was* there.  "no such field" without
    the alternatives is how a model tries the same wrong guess again.

    Public, and named rather than private, because
    :class:`~core.runtime.grounding.ClaimGroundingCheck` verifies a claim
    table with it: ``{"value": 0.7446, "path": "gate.confidence"}`` is
    checked by walking the same path into the same stored payload the
    model read it from.  One walker, so what a claim *means* cannot
    disagree with what ``mission_result`` returns for the same path.
    """
    current = value
    for token in _tokens(path):
        if isinstance(token, int):
            if not isinstance(current, list):
                return None, (
                    f"[{token}] does not apply: that position holds "
                    f"{_shape(current)}"
                )
            if not -len(current) <= token < len(current):
                return None, (
                    f"[{token}] is out of range: the array has "
                    f"{len(current)} items"
                )
            current = current[token]
            continue
        if not isinstance(current, dict):
            return None, (
                f"{token!r} does not apply: that position holds "
                f"{_shape(current)}"
            )
        if token not in current:
            return None, (
                f"no field {token!r} there; that object has: "
                f"{', '.join(str(k) for k in list(current)[:20]) or '(nothing)'}"
            )
        current = current[token]
    return current, ""


def _tokens(path: str) -> List[Any]:
    tokens: List[Any] = []
    for part in path.split("."):
        part = part.strip()
        if not part:
            continue
        head = _INDEX.split(part)
        # `_INDEX.split` alternates literal, index, literal, index, ...
        for position, piece in enumerate(head):
            piece = piece.strip()
            if not piece:
                continue
            tokens.append(int(piece) if position % 2 else piece)
    return tokens
