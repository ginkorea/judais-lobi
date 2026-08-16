# core/runtime/agui.py — the mission stream, spoken as AG-UI

"""An optional translator from this harness's records into AG-UI events.

A platform that renders a mission in a browser needs the records this harness
writes turned into whatever its frontend subscribes to, and for a growing
number of frontends that is **AG-UI** — an open protocol of typed event frames
(``RUN_STARTED``, ``TEXT_MESSAGE_CONTENT``, ``TOOL_CALL_RESULT`` …) that
several agent UIs already speak.  The reference deployment wrote that
translation once, inside its own repository, and everything it learned writing
it — where the grounding verdict has to ride, why a rejected reply must never
be rendered as prose, that one answer has to arrive as several bounded frames
— was learned at the cost of turns an analyst saw go wrong.  The second
platform should not pay for those again, so the **mechanism** lives here and
the platform keeps its own content.

Nothing in this repo imports this module.  It is here for a driver's author
(``PLATFORMS.md`` §"Driving it"), it depends on no AG-UI SDK, and it costs a
run that never asks for it nothing at all: it imports
:mod:`core.runtime.contract` and the standard library, and it emits plain
dicts.  A caller that wants typed SDK objects constructs them from these; a
caller that is about to write JSON down a socket writes these.

## Two entry points

:func:`translate` is a pure function over a whole run — every record, in
order, becoming an iterator of AG-UI event dicts.  It is what a *replay*
wants: a run read back out of :class:`~core.durable.RunStore` with
``since(0)`` is exactly this input, and its ``{seq, at, record}`` envelopes
are unwrapped on the way in so a caller does not have to.

:class:`Translator` is the same translation with the state left open, for a
*live* follower: ``feed(record)`` returns the frames that record produced and
``close()`` returns the frames that end a stream which stopped.  ``RunStore``'s
``follow(cursor)`` feeds it directly.

Both are deterministic.  No clock is read, no id is random, and the same
records translate to the same frames every time — which is what lets a
consumer replay a transcript and get the pane it had, and what lets a test
assert on the whole output rather than on a shape.

## What it claims: nothing

Every value on every frame came off a record, or is a correlation id this
module minted from one.  There is no judgement here about whether a result may
be quoted, whether a tool is safe, or what an answer means — those are the
platform's, made from the tool name and the grounding report this module
carries through verbatim.  There are no tool names in this file, no gated
list, no handle rules, no citation grammar.  A translator that had an opinion
about any of them would be a second place where a platform's policy lives, and
the first one would be wrong within a release.

## The three shapes worth explaining

**A rejected reply is MECHANICS, and the frame says so.**  ``reply_rejected``
becomes ``CUSTOM``/:data:`CUSTOM_REPLY_REJECTED` and never, under any
condition, a ``TEXT_MESSAGE``.  The loop's correction prompt — *"that was not
valid JSON"*, *"there is no tool named …"* — is the harness talking to the
model about shape, and rendered as content it reads as the agent saying
something incoherent to the analyst.  The reference deployment shipped it as
content first and watched two such frames land above answers the model had
recovered from perfectly well.  The distinction that matters is *recovered*
versus *failed*, and that is only known at the end of the turn, so this module
does not decide it: it marks the frame ``mechanics: true`` and hands the
consumer everything needed to buffer the rejections and flush them only for a
turn that ended without an answer.  Marking is the mechanism; the buffering
policy is the platform's.

**The grounding verdict rides the answer's own frames.**  A caveat delivered
as a sibling event is one a dropped frame, a reconnect resuming from a cursor
between two frames, or a frontend that batches customs can separate from the
prose it qualifies — and the separation fails silently in the dangerous
direction, because unmarked prose reads as a finding.  So the verdict is
carried three ways at once: inline on every ``TEXT_MESSAGE_CONTENT`` frame
this module fans out, on the ``CUSTOM``/:data:`CUSTOM_ANSWER` that states the
authoritative text, and — the part that makes it renderable as a badge rather
than a sibling — on the ``CUSTOM``/:data:`CUSTOM_GROUNDING` report itself, as
``messageId``: the id of the message it judges.  An interim report
(``repairing: true``) is emitted immediately, because a repair turn is a whole
extra round-trip and from outside looks exactly like a stall — and it
**never closes the message** and is never latched as the verdict.  The second
report is the verdict.

**One answer, several bounded frames.**  ``answer`` is one record carrying the
whole text, and a measured report-register answer is tens of thousands of
characters.  Nothing bounds an outbound frame, so :func:`answer_deltas` splits
the text at line boundaries — never inside a fenced code block, and an
over-long single line ships whole, because a bounded frame is hygiene and a
split fence is a rendering failure.  When the harness emits real
``answer_delta`` records the provisional deltas are relayed as they arrive and
the ``answer`` record that always follows is authoritative: it closes the
message and states the full text on its own ``CUSTOM`` frame, so a consumer
that accumulated the provisional parts replaces them rather than trusting
them.  When it does not, this module fans the answer out itself — so the
consumer's incremental path is the one exercised either way, and the day the
harness streams tokens nothing downstream changes.

## The rules a consumer can hold this to

* **The vocabulary is read, not copied.**  The events and their required
  fields come from :mod:`core.runtime.contract` at import; :data:`HANDLED` is
  every event this module has a mapping for, and ``tests/test_agui.py`` fails
  when the contract declares one it does not.  A tenth event is a decision
  somebody makes rather than a frame nobody noticed.
* **A record type this module does not know is dropped**, which is the
  contract's own rule for consumers.
* **Nothing is dropped from a record it does know.**  AG-UI's own fields are
  spelled the protocol's way (``threadId``, ``toolCallId``, ``messageId``);
  everything else the record carried travels beside them under the harness's
  own spelling, and a ``CUSTOM`` frame's ``value`` is the record as the
  harness wrote it.  So an optional field added in a minor release reaches the
  browser without this file changing.
* **Absence travels as absence.**  A key the harness omitted is omitted here.
  A default cannot tell a field nobody set from one set to null or zero, and
  several fields on this stream — ``audit_ref``, ``usage``, ``protocol`` —
  mean different things absent than they do empty.
* **``tool_result.output`` is verbatim.**  This module never truncates it.
  What the *model* was shown is already bounded and says so (``truncated``);
  what a watcher is shown is the caller's decision, made where the socket is.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional

from core.runtime import contract

__all__ = [
    "AG_UI_TYPES",
    "RUN_STARTED", "RUN_FINISHED", "RUN_ERROR",
    "STEP_STARTED", "STEP_FINISHED",
    "TEXT_MESSAGE_START", "TEXT_MESSAGE_CONTENT", "TEXT_MESSAGE_END",
    "TOOL_CALL_START", "TOOL_CALL_ARGS", "TOOL_CALL_END", "TOOL_CALL_RESULT",
    "CUSTOM",
    "CUSTOM_PREFIX", "CUSTOM_OPENING", "CUSTOM_ANSWER", "CUSTOM_GROUNDING",
    "CUSTOM_REPLY_REJECTED", "CUSTOM_GATE_REQUESTED",
    "ANSWER_DELTA_LIMIT", "answer_deltas",
    "HANDLED", "SILENCE", "UNFINISHED", "VERDICT_OMITS",
    "Translator", "translate",
]


# ── AG-UI's vocabulary, spelled its way ──────────────────────────────────────
#
# The names are the public protocol's (https://docs.ag-ui.com) and are written
# out rather than imported: this module's whole point is that a platform can
# use it without taking on an SDK, and a constant that costs a dependency is
# not a constant.  They are the frames a mission actually produces; the rest of
# the protocol's vocabulary (`MESSAGES_SNAPSHOT`, `RAW`, the thinking frames) is
# not here because nothing on this stream is one.

#: Lifecycle.  Every stream this module produces opens with `RUN_STARTED` and
#: closes with exactly one of the other two — including a stream that stopped,
#: which is what :meth:`Translator.close` is for.
RUN_STARTED = "RUN_STARTED"
RUN_FINISHED = "RUN_FINISHED"
RUN_ERROR = "RUN_ERROR"

#: A step of the plan/act loop.  The harness announces the start of one and
#: never the end, so the end is inferred here: a step is finished by the next
#: step opening, or by the run ending.
STEP_STARTED = "STEP_STARTED"
STEP_FINISHED = "STEP_FINISHED"

#: The answer, as a message that starts, streams and ends.
TEXT_MESSAGE_START = "TEXT_MESSAGE_START"
TEXT_MESSAGE_CONTENT = "TEXT_MESSAGE_CONTENT"
TEXT_MESSAGE_END = "TEXT_MESSAGE_END"

#: A tool call.  ``START`` names it, ``ARGS`` carries the arguments as a JSON
#: string (one frame — this harness knows the whole call before it dispatches
#: it and does not stream arguments), ``END`` closes the argument stream, and
#: ``RESULT`` is the separate message carrying what came back.  That order is
#: the protocol's, and it is why ``END`` precedes ``RESULT`` here.
TOOL_CALL_START = "TOOL_CALL_START"
TOOL_CALL_ARGS = "TOOL_CALL_ARGS"
TOOL_CALL_END = "TOOL_CALL_END"
TOOL_CALL_RESULT = "TOOL_CALL_RESULT"

#: The protocol's escape hatch, and the honest destination for everything this
#: harness says that AG-UI has no frame for: the opening posture, the context
#: window compaction, a gate, the grounding report, a rejected reply.  Shaped
#: as the protocol shapes it — ``{"type": "CUSTOM", "name": …, "value": …}`` —
#: so a conforming frontend receives it without special-casing this harness.
CUSTOM = "CUSTOM"

#: Every AG-UI type this module can emit, so a consumer can assert it handles
#: all of them.
AG_UI_TYPES: tuple[str, ...] = (
    RUN_STARTED, RUN_FINISHED, RUN_ERROR,
    STEP_STARTED, STEP_FINISHED,
    TEXT_MESSAGE_START, TEXT_MESSAGE_CONTENT, TEXT_MESSAGE_END,
    TOOL_CALL_START, TOOL_CALL_ARGS, TOOL_CALL_END, TOOL_CALL_RESULT,
    CUSTOM,
)


# ── the CUSTOM names, namespaced ─────────────────────────────────────────────
#
# Prefixed, because `CUSTOM` is a shared channel: a frontend rendering this
# harness beside anything else needs to know whose custom it is holding, and
# two unrelated things under one bare word is how a renderer starts guessing.

#: What every custom this module emits is called after.
CUSTOM_PREFIX = "mission."

#: The opening posture: the tools the agent was offered and which of them need
#: a person, the profile and sandbox it runs under, the audit file, the durable
#: run id, the protocol — the whole ``mission_started`` record as the harness
#: wrote it.  An analyst reading a refusal cannot tell "I am not allowed to"
#: from "there is no route from here" without it.
CUSTOM_OPENING = CUSTOM_PREFIX + "opening"

#: The answer's authoritative text, right after its ``TEXT_MESSAGE_END``.
CUSTOM_ANSWER = CUSTOM_PREFIX + "answer"

#: The grounding report, carrying ``messageId`` — the answer it judges.
CUSTOM_GROUNDING = CUSTOM_PREFIX + "grounding"

#: A reply the loop could not act on.  Mechanics; see the module docstring.
CUSTOM_REPLY_REJECTED = CUSTOM_PREFIX + "reply_rejected"

#: A tool the deployment gates: proposed, not called, waiting on a person.
CUSTOM_GATE_REQUESTED = CUSTOM_PREFIX + "gate_requested"


# ── how an unfinished stream ends ────────────────────────────────────────────

#: ``RUN_ERROR.code`` for a mission that emitted **nothing at all**.  The exit
#: contract's ``silence`` clause: ``mission_started`` is written before the
#: model is asked and before the tool plane is touched, so an empty stream is a
#: harness that never got that far — a cold model server, a refused token, an
#: unreachable endpoint.  It is never an empty answer, and a consumer must
#: report it as a failure rather than render a blank reply.  Which is why
#: :meth:`Translator.close` emits a run that started and errored rather than
#: nothing: nothing is the state an analyst cannot leave.
SILENCE = "silence"

#: ``RUN_ERROR.code`` for a stream that carried records and then stopped
#: without ``mission_finished``.  The harness writes that record from a
#: ``finally``, so its absence means the process died between the two — and a
#: stream that simply stops is indistinguishable from an agent that is
#: thinking.
UNFINISHED = "unfinished"


# ── the answer, in frames ────────────────────────────────────────────────────

#: Rough ceiling on one answer delta, in characters.  A measured
#: report-register answer was 46,032 characters, and nothing bounds an outbound
#: frame or a stored one — so one frame per couple of paragraphs is the
#: difference between a transcript that replays smoothly and a single frame the
#: size of a chapter.
ANSWER_DELTA_LIMIT = 2000

#: A fenced code block, which :func:`answer_deltas` will not split.
_FENCE = re.compile(r"```([A-Za-z0-9_+-]*)\n(.*?)```", re.DOTALL)


def answer_deltas(text: str, limit: int = ANSWER_DELTA_LIMIT) -> List[str]:
    """The answer as delta frames whose concatenation is exactly the answer.

    Splits at line boundaries only, and never inside a fenced code block: half
    a fence renders as prose, and a citation token split across two frames is
    one no consumer can resolve in either.  A single line longer than *limit*
    ships whole rather than split — a bounded frame is hygiene and a broken
    token is a correctness failure, so when the two conflict the limit loses.

    ``"".join(answer_deltas(t)) == t`` for every *t*, which is the whole
    contract: a consumer accumulating the frames holds the answer.
    """
    if len(text) <= limit:
        return [text]
    segments: List[str] = []
    cursor = 0
    for fence in _FENCE.finditer(text):
        segments.extend(text[cursor:fence.start()].splitlines(keepends=True))
        segments.append(fence.group(0))
        cursor = fence.end()
    segments.extend(text[cursor:].splitlines(keepends=True))
    deltas: List[str] = []
    buffer = ""
    for segment in segments:
        if buffer and len(buffer) + len(segment) > limit:
            deltas.append(buffer)
            buffer = ""
        buffer += segment
    if buffer:
        deltas.append(buffer)
    return deltas


# ── reading a record ─────────────────────────────────────────────────────────

#: The grounding fields left off the compact verdict that rides the answer's
#: own frames.  ``checks`` is the per-check detail — the bulky half, and the
#: half a badge does not need; it is on :data:`CUSTOM_GROUNDING` in full.
#: Stated as what is OMITTED rather than as what is kept, so a field the
#: contract adds to ``grounding`` reaches the frames it qualifies without this
#: module being edited.
VERDICT_OMITS: tuple[str, ...] = ("checks",)


def _unwrap(item: Any) -> Optional[Mapping[str, Any]]:
    """The record inside a store envelope, or the record itself.

    ``RunStore`` writes ``{seq, at, record}`` and a mission writes the record
    bare, so a replay and a live follower hand this module two shapes of the
    same thing.  Told apart by the wire record always having ``event`` and the
    envelope never having one — which cannot misfire, rather than by looking
    for ``seq``, which a future envelope field might not carry.
    """
    if not isinstance(item, Mapping):
        return None
    if "event" not in item and isinstance(item.get("record"), Mapping):
        return item["record"]
    return item


def _said(record: Mapping[str, Any], *, without: Iterable[str] = ()) -> Dict[str, Any]:
    """The record as the harness wrote it, minus the names given.

    Membership and not ``get``: a key the harness omitted stays omitted, so a
    consumer can tell "nothing was said" from "null was said" — which for
    ``audit_ref`` and ``usage`` are different facts and only one of them is
    somebody's decision.
    """
    skip = set(without) | {"event"}
    return {name: value for name, value in record.items() if name not in skip}


def _extras(record: Mapping[str, Any], event: str) -> Dict[str, Any]:
    """Whatever the record carries beyond what its event requires.

    Read off :data:`~core.runtime.contract.FIELDS` rather than off a list here,
    so an optional field added in a minor release — ``compacted``, ``resumed``,
    ``call``, whatever comes next — travels without this module knowing its
    name.  Sorted, because determinism is a promise this module makes and dict
    order is the emitter's business.
    """
    required = set(contract.FIELDS.get(event, ()))
    return {name: record[name]
            for name in sorted(record) if name not in required and name != "event"}


def _ordinal(value: Any) -> int:
    """A record's ``index`` or ``call`` as an integer, and 0 when it said
    nothing.  Ids are minted from these and an id containing ``None`` is one no
    consumer can correlate."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


# ── the translator ───────────────────────────────────────────────────────────

@dataclass
class Translator:
    """One mission's records, becoming AG-UI frames.

    Stateful in four ways, and all four are correlation rather than judgement:
    which step is open (so it can be finished), which tool calls are open (so
    they can be closed), whether a message is open and how many provisional
    deltas it has taken (so the ``answer`` record knows whether to fan out or
    to replace), and the last non-interim grounding verdict (so the answer's
    own frames can carry it).

    ``thread_id`` and ``run_id`` are the caller's: this harness has no notion
    of a conversation and its ``run_id`` — when it keeps one — names a durable
    directory rather than an AG-UI run.  A ``run_id`` left empty is filled from
    the ``run_id`` the harness announces on ``mission_started``, when it
    announces one, so a caller that does not care gets the useful thing.
    """

    thread_id: str = ""
    run_id: str = ""
    #: The ceiling on a fanned-out answer frame.  The caller's, because the
    #: caller owns the socket the frames go down.
    delta_limit: int = ANSWER_DELTA_LIMIT

    _opened: bool = False
    _closed: bool = False
    _seen: int = 0
    _step: Optional[int] = None
    _step_open: bool = False
    _open_calls: List[str] = field(default_factory=list)
    _message: str = ""
    _deltas: int = 0
    _verdict: Optional[Dict[str, Any]] = None

    # -- the two entry points ------------------------------------------------
    def feed(self, item: Mapping[str, Any]) -> List[Dict[str, Any]]:
        """Zero or more AG-UI frames for one record, or one store envelope.

        A record whose ``event`` this module has no mapping for is **dropped**,
        which is the contract's own rule for a consumer: the harness may grow
        an event a given frontend has no opinion about, and a turn must not
        fail over one.  What makes that safe is the test, not the silence —
        ``tests/test_agui.py`` fails the moment :data:`HANDLED` stops covering
        :data:`~core.runtime.contract.EVENTS`.
        """
        record = _unwrap(item)
        if record is None:
            return []
        # Counted before the vocabulary check, because what :meth:`close`
        # needs to know is whether the MISSION said anything — not whether
        # this module had an opinion about it.
        self._seen += 1
        # The contract's vocabulary and not this class's method names.  A
        # handler this module happens to carry for an event the contract has
        # not declared — which is exactly what an unmerged half of a release
        # looks like from here — must not fire, or a consumer would receive
        # frames for a record type nobody has agreed exists.
        event = str(record.get("event") or "")
        if event not in contract.EVENTS:
            return []
        # No second guard for a missing handler: :data:`HANDLED` is asserted
        # equal to the contract's vocabulary, so an event nothing maps is a
        # failing test here rather than a branch no mutation can reach.
        return getattr(self, "_on_" + event)(record)

    def close(self) -> List[Dict[str, Any]]:
        """The frames that end a stream which stopped on its own.

        Empty after ``mission_finished``, which already closed everything.
        Otherwise: whatever is still open, and then a ``RUN_ERROR`` — because
        the exit contract says a mission that stops without that record is a
        mission that died, and a pane spinning forever is the state an analyst
        cannot leave.  A stream that carried nothing at all gets the same
        treatment under :data:`SILENCE`, so the empty case is a failure
        somebody can render rather than a blank.

        Call it at EOF, and **not** on a partial window: a replay of
        ``since(cursor)`` that has not reached the end of the run is a stream
        that has not stopped.
        """
        if self._closed:
            return []
        frames = self._open()
        frames += self._close_calls()
        frames += self._close_message()
        frames += self._close_step()
        code = SILENCE if not self._seen else UNFINISHED
        frames.append(self._error(code, _ENDED[code]))
        self._closed = True
        return frames

    # -- frames --------------------------------------------------------------
    def _frame(self, kind: str, /, **payload: Any) -> Dict[str, Any]:
        """One AG-UI frame.  ``kind`` is positional-only because payloads are
        splatted in and a harness field called ``kind`` — which a tool result
        may perfectly well carry — would otherwise collide with it and take
        the translation down with a ``TypeError``."""
        return {"type": kind, **payload}

    def _custom(self, name: str, value: Mapping[str, Any]) -> Dict[str, Any]:
        """A ``CUSTOM`` frame in the protocol's own shape.

        *value* is passed as a mapping and not as keywords on purpose: it is
        very often a whole harness record, and a record field that happened to
        be called ``name`` would otherwise collide with this parameter and
        take the translation down inside somebody's socket loop.
        """
        return {"type": CUSTOM, "name": name, "value": dict(value)}

    def _open(self) -> List[Dict[str, Any]]:
        """``RUN_STARTED``, once, before anything else.

        Emitted lazily rather than only on ``mission_started`` so that a
        replay joining a run part-way through — which is what a cursor is for
        — still produces a conforming stream instead of frames belonging to a
        run that never started.
        """
        if self._opened:
            return []
        self._opened = True
        return [self._frame(RUN_STARTED, threadId=self.thread_id,
                            runId=self.run_id)]

    def _error(self, code: str, message: str,
               said: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        """``RUN_ERROR``, carrying whatever the harness managed to say."""
        return self._frame(RUN_ERROR, **{
            **(said or {}), "threadId": self.thread_id, "runId": self.run_id,
            "code": code, "message": message})

    # -- correlation ---------------------------------------------------------
    def _message_id(self, index: Any) -> str:
        """The id of the answer of one step.

        ``msg-<index>``, minted rather than read: the wire carries no message
        id, and a repaired answer is still the answer of the step it was
        written on.  Deterministic, so a replay badges the same message the
        live stream badged.
        """
        return f"msg-{_ordinal(index)}"

    def _call_id(self, record: Mapping[str, Any]) -> str:
        """The id of one tool call.

        ``call-<index>-<call>``, and both halves are needed: ``index`` numbers
        the model turn, and under a native protocol one turn may dispatch
        several tools distinguished only by ``call``.  Minted the same way from
        the ``tool_call`` and from its ``tool_result``, so the pair correlates
        without this module having to remember which call is open — which is
        what lets a follower that joined between the two still tie them
        together.
        """
        return f"call-{_ordinal(record.get('index'))}-{_ordinal(record.get('call'))}"

    def _close_step(self) -> List[Dict[str, Any]]:
        if not self._step_open:
            return []
        self._step_open = False
        return [self._frame(STEP_FINISHED, stepName=f"step-{_ordinal(self._step)}")]

    def _close_calls(self) -> List[Dict[str, Any]]:
        """``TOOL_CALL_END`` for every call still open.

        A call with no result is not a bug on this side: a gated tool is never
        dispatched, and a harness that died mid-subprocess never reported one.
        Left open, it is an argument stream a frontend waits on forever.
        """
        frames = [self._frame(TOOL_CALL_END, toolCallId=call)
                  for call in self._open_calls]
        self._open_calls = []
        return frames

    def _close_message(self) -> List[Dict[str, Any]]:
        if not self._message:
            return []
        frames = [self._frame(TEXT_MESSAGE_END, messageId=self._message)]
        self._message = ""
        self._deltas = 0
        return frames

    # -- the mapping ---------------------------------------------------------
    def _on_mission_started(self, record: Mapping[str, Any]) -> List[Dict[str, Any]]:
        """The run begins, and the posture it begins under is said out loud."""
        if not self.run_id:
            self.run_id = str(record.get("run_id") or "")
        frames = self._open()
        frames.append(self._custom(CUSTOM_OPENING, _said(record)))
        return frames

    def _on_step_started(self, record: Mapping[str, Any]) -> List[Dict[str, Any]]:
        """A step opens, and whatever else the harness said about it.

        ``compacted``, ``resumed``, ``plan`` and anything a later release adds
        each become their own ``CUSTOM``, named ``mission.<field>``: they are
        facts about the loop's own machinery — the conversation was shortened,
        this run continues an earlier one — and a frontend that has an opinion
        about one of them should not have to unpack a frame about the others
        to find it.  Read off the record rather than off a list here, so the
        next one arrives without an edit.
        """
        frames = self._open()
        frames += self._close_step()
        self._step = _ordinal(record.get("index"))
        self._step_open = True
        frames.append(self._frame(STEP_STARTED, stepName=f"step-{self._step}"))
        for name, value in _extras(record, contract.STEP_STARTED).items():
            frames.append(self._custom(CUSTOM_PREFIX + name,
                                       {"index": self._step, name: value}))
        return frames

    def _on_reply_rejected(self, record: Mapping[str, Any]) -> List[Dict[str, Any]]:
        """Mechanics.  Never a ``TEXT_MESSAGE`` — see the module docstring.

        ``mechanics: true`` is on the frame so that "this is the loop talking
        to the model about shape" is something a consumer can branch on rather
        than a convention it has to know.  Whether to show it as it happens or
        hold it until the turn's fate is known is the consumer's call, and both
        need it marked.
        """
        frames = self._open()
        frames.append(self._custom(CUSTOM_REPLY_REJECTED,
                                   {**_said(record), "mechanics": True}))
        return frames

    def _on_tool_call(self, record: Mapping[str, Any]) -> List[Dict[str, Any]]:
        """The model named a tool and the loop is about to dispatch it.

        Before the call, which is the point: a watcher shows what is about to
        happen rather than only what happened.  The arguments go out as the
        protocol wants them — one JSON string — with sorted keys, because the
        same call has to serialize the same way twice.
        """
        call_id = self._call_id(record)
        tool = str(record.get("tool") or "")
        frames = self._open()
        if call_id not in self._open_calls:
            self._open_calls.append(call_id)
        # ``usage``, ``call`` and anything a later release adds ride the frame
        # that opens the call, because the protocol has nowhere else to put
        # them and dropping them would make this module the place a field goes
        # to die.  The protocol's own names are written last, so they win over
        # a harness field that ever comes to share one.
        frames.append(self._frame(TOOL_CALL_START, **{
            **_extras(record, contract.TOOL_CALL),
            "index": record.get("index"),
            "toolCallId": call_id, "toolName": tool}))
        frames.append(self._frame(
            TOOL_CALL_ARGS, toolCallId=call_id,
            delta=json.dumps(record.get("arguments") or {},
                             ensure_ascii=False, sort_keys=True, default=str)))
        return frames

    def _on_tool_result(self, record: Mapping[str, Any]) -> List[Dict[str, Any]]:
        """The bus answered.

        ``END`` then ``RESULT``: the first closes the argument stream and the
        second is a separate message, which is the protocol's order and not an
        accident of this file.

        ``content`` is ``output`` **verbatim**, whether the call succeeded or
        not, and ``error`` travels beside it rather than replacing it — a
        failed call that produced output before it failed produced evidence,
        and a translator that swapped one for the other would be deciding
        which half of a failure is worth reading.  Nothing here is truncated:
        ``truncated`` describes what the MODEL was shown, and what a watcher is
        shown is bounded where the socket is.
        """
        call_id = self._call_id(record)
        tool = str(record.get("tool") or "")
        frames = self._open()
        if call_id not in self._open_calls:
            # A result whose call this stream never carried — a follower that
            # joined between the two.  It still has to be attributable, so the
            # call is opened here and closed on the next line.
            frames.append(self._frame(TOOL_CALL_START, toolCallId=call_id,
                                      toolName=tool))
            self._open_calls.append(call_id)
        self._open_calls.remove(call_id)
        frames.append(self._frame(TOOL_CALL_END, toolCallId=call_id))
        # `toolName` rides the result as well as the call, because a consumer
        # deciding what a result may be quoted or cited as decides it from the
        # tool that produced it — and a follower that joined between the two
        # halves has only this frame to read it off.
        frames.append(self._frame(TOOL_CALL_RESULT, **{
            **_said(record, without=("output",)),
            "messageId": f"{call_id}-result", "toolCallId": call_id,
            "toolName": tool, "role": "tool",
            "content": record.get("output")}))
        return frames

    def _on_gate_requested(self, record: Mapping[str, Any]) -> List[Dict[str, Any]]:
        """An act a person has to answer for.

        The arguments travel **verbatim**, because what a person approves has
        to be the bytes that would run, and ``approval_id`` travels with them
        when the deployment keeps durable records — a gate is answered from
        outside the run that asked, sometimes on a different day, so the
        request needs a name that outlives the process.

        Not an AG-UI tool call: nothing was dispatched, and a frontend that saw
        ``TOOL_CALL_START`` for a call that will never run would show work in
        progress for a mission that has stopped.
        """
        frames = self._open()
        frames.append(self._custom(CUSTOM_GATE_REQUESTED, _said(record)))
        return frames

    def _on_grounding(self, record: Mapping[str, Any]) -> List[Dict[str, Any]]:
        """The fabrication check's verdict, carrying the message it judges.

        ``messageId`` is the whole lesson: a report delivered as a sibling of
        the answer is one a renderer has to guess the subject of, and it will
        guess "the last thing I drew".  With the id on it, the report badges
        the answer.

        An interim report (``repairing: true``) is emitted — a repair turn is a
        round-trip that looks like a stall from outside — and does two things
        it must not do at all: it does not close the message, and it is not
        latched as the verdict.  A repaired answer gets a second report, and
        that one is the verdict.
        """
        message = self._message or self._message_id(self._step)
        report = _said(record)
        if not record.get("repairing"):
            self._verdict = {name: value for name, value in report.items()
                             if name not in VERDICT_OMITS}
        return self._open() + [
            self._custom(CUSTOM_GROUNDING, {**report, "messageId": message})]

    def _on_answer_delta(self, record: Mapping[str, Any]) -> List[Dict[str, Any]]:
        """A provisional piece of the answer, as the model writes it.

        Present only when the harness emits ``answer_delta`` records; the
        ``answer`` record ALWAYS follows and is authoritative, so what these
        frames buy is that the reader sees prose arriving rather than a
        spinner.  A consumer must be prepared to replace what it accumulated
        here with the text on :data:`CUSTOM_ANSWER`.
        """
        message = self._message_id(record.get("index"))
        frames = self._open()
        if self._message != message:
            frames += self._close_message()
            frames.append(self._frame(TEXT_MESSAGE_START, messageId=message,
                                      role="assistant"))
            self._message = message
            self._deltas = 0
        self._deltas += 1
        frames.append(self._frame(TEXT_MESSAGE_CONTENT, messageId=message,
                                  delta=str(record.get("text") or "")))
        return frames

    def _on_answer(self, record: Mapping[str, Any]) -> List[Dict[str, Any]]:
        """The answer, and the two roads to it.

        **Deltas were seen for this step**: the message is already open and
        carries provisional text, so this closes it and states the full text
        on :data:`CUSTOM_ANSWER` as the authoritative replacement.  The harness
        may have appended a caveat or spent a repair turn since the first
        delta went out, so the accumulated fragments are not the answer — the
        record is.

        **No deltas were seen**: this fans the text out itself, into bounded
        ``TEXT_MESSAGE_CONTENT`` frames whose concatenation is exactly the
        answer.  The consumer's incremental path is therefore the one exercised
        on every run, and the day the harness streams tokens nothing
        downstream of this changes.

        Either way the verdict rides the frames — inline on each fanned-out
        delta, and on the custom — so a reconnect resuming from a cursor
        between two frames cannot separate an ungrounded answer from the fact
        that it is one.
        """
        text = str(record.get("text") or "")
        message = self._message or self._message_id(self._step)
        verdict = dict(self._verdict) if self._verdict is not None else None
        frames = self._open()
        if self._message:
            frames += self._close_message()
        else:
            frames.append(self._frame(TEXT_MESSAGE_START, messageId=message,
                                      role="assistant"))
            for delta in answer_deltas(text, self.delta_limit):
                payload: Dict[str, Any] = {"messageId": message, "delta": delta}
                if verdict is not None:
                    payload["grounding"] = dict(verdict)
                frames.append(self._frame(TEXT_MESSAGE_CONTENT, **payload))
            frames.append(self._frame(TEXT_MESSAGE_END, messageId=message))
        said = _said(record)
        if verdict is not None:
            said["grounding"] = verdict
        said["messageId"] = message
        frames.append(self._custom(CUSTOM_ANSWER, said))
        return frames

    def _on_mission_finished(self, record: Mapping[str, Any]) -> List[Dict[str, Any]]:
        """Terminal.  ``RUN_FINISHED``, unless the run crashed.

        **The rule.**  ``incomplete`` is the transcript's default and therefore
        the word a mission ends on when it ended by *raising* — the record is
        written from a ``finally``, so a crash still closes the stream and
        closes it holding the outcome nothing got round to setting.  It is also
        the word a **cancelled** run ends on, and there the record says why
        (``reason: "cancelled"``).  So:

        * ``incomplete`` with **no** ``reason`` → ``RUN_ERROR``.  Something
          went wrong and the harness did not get to say what; the diagnostic is
          on its stderr, which the exit contract says is what a consumer shows.
        * ``incomplete`` **with** a ``reason`` → ``RUN_FINISHED``, and
          ``cancelled: true`` when the reason is cancellation.  A person
          pressing stop is not an error, and rendering somebody's own decision
          as a failure tells them something went wrong with the thing they
          asked for.
        * every other outcome → ``RUN_FINISHED``.  ``budget_exhausted``
          included: a run that hit a hard bound did what it was told, and the
          ``budget`` field on the frame says which bound it was.

        ``steps`` and ``max_steps`` both travel, because they are only
        meaningful against each other — six steps of a stated twenty-four is
        not an agent that ran out of room — and so do ``usage``, ``budget``,
        ``reason`` and ``elapsed_s`` when the harness stated them.
        """
        frames = self._open()
        frames += self._close_calls()
        frames += self._close_message()
        frames += self._close_step()
        outcome = str(record.get("outcome") or "")
        reason = record.get("reason")
        said = _said(record)
        self._closed = True
        if outcome == "incomplete" and reason is None:
            frames.append(self._error(
                outcome, _CRASHED.format(steps=record.get("steps")), said))
            return frames
        # `cancelled` only when it is true.  A field states a fact when there
        # is one to state, and a `cancelled: false` on every ordinary finish is
        # a claim about a decision nobody made.
        cancelled = {"cancelled": True} if reason == "cancelled" else {}
        frames.append(self._frame(RUN_FINISHED, **{
            **said, **cancelled,
            "threadId": self.thread_id, "runId": self.run_id}))
        return frames


#: The sentence on the ``RUN_ERROR`` of a run that ended as ``incomplete``
#: without saying why.  It does NOT say the agent said nothing about it — it
#: almost always did, on its error stream, and a consumer that discarded that
#: and then asserted the silence it created is the failure this points away
#: from.
_CRASHED: str = (
    "The mission ended after {steps} step(s) without an answer and without a "
    "reason. That is what this harness reports when a run stopped by raising: "
    "the diagnostic is the tail of its stderr.")

#: The sentence on each :meth:`Translator.close` ending, by code.
_ENDED: Dict[str, str] = {
    SILENCE: (
        "The mission produced no records at all. Its opening frame is written "
        "before the model is asked and before the tool plane is touched, so "
        "this is a harness that never got that far — not an empty answer."),
    UNFINISHED: (
        "The record stream ended without a terminal record. The harness writes "
        "one from a `finally`, so its absence means the process died between "
        "the last record and the end of the run."),
}


#: Every mission event this module has a mapping for, computed from the
#: contract rather than written down: a name is here when the contract declares
#: it AND this class has a handler for it.  ``tests/test_agui.py`` holds it
#: equal to :data:`~core.runtime.contract.EVENTS`, so an event added to the
#: contract fails that test until somebody decides what a browser should see —
#: which is the whole reason the set is computed and then asserted rather than
#: simply trusted.
HANDLED: frozenset[str] = frozenset(
    name for name in contract.EVENTS if hasattr(Translator, "_on_" + name))


def translate(records: Iterable[Mapping[str, Any]], *, thread_id: str = "",
              run_id: str = "",
              delta_limit: int = ANSWER_DELTA_LIMIT) -> Iterator[Dict[str, Any]]:
    """A whole run's records, as AG-UI frames.  Pure, ordered, deterministic.

    Takes wire records or ``RunStore`` envelopes, in either case in the order
    the mission wrote them, and yields the frames — closing the stream at the
    end, which for a run that never wrote ``mission_finished`` means a
    ``RUN_ERROR`` rather than a pane that keeps spinning.  For a *partial*
    window, or for a live follower, drive a :class:`Translator` directly and
    call ``close()`` only at EOF.
    """
    translator = Translator(thread_id=thread_id, run_id=run_id,
                            delta_limit=delta_limit)
    for item in records:
        for frame in translator.feed(item):
            yield frame
    for frame in translator.close():
        yield frame
