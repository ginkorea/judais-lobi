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


class ResultStoreConflict(RuntimeError):
    """Something is already registered under the store's tool name."""


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
        """Every successful result's text and typed payload.

        This is what "appeared in a tool output *of this run*" means to
        a grounding validator: the full text, not the bounded rendering
        the model saw, and the typed payload as well — an identifier the
        model correctly read out of a structured field is grounded even
        though the text block never spelled it.
        """
        texts: List[str] = []
        for stored in self._results:
            if not stored.succeeded:
                continue
            if stored.text:
                texts.append(stored.text)
            if stored.evidence:
                texts.append(stored.evidence)
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
        """The ``ToolDescriptor`` for reading this store."""
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
        """The callable ``ToolBus`` dispatches for :meth:`descriptor`."""
        def _read(handle: str = "", path: str = "", **_ignored: Any):
            return self.read(handle, path)
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

    def read(self, handle: str = "", path: str = "") -> Tuple[int, str, str]:
        """``(exit_code, stdout, stderr)`` — the ToolBus executor shape."""
        if not (handle or "").strip():
            return (0, self._index(), "")

        stored = self._by_handle.get(handle.strip())
        if stored is None:
            return (1, "", (
                f"No result under handle {handle!r} in this mission. "
                f"Handles: {', '.join(self._by_handle) or '(none yet)'}."
            ))

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
              branch: str = "", **_ignored: Any) -> Tuple[int, str, str]:
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
        return store.read(handle, path)


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
