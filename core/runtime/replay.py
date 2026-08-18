# core/runtime/replay.py — record what a run was given, and give it again

"""Everything a mission needed from outside itself, written down and served back.

:mod:`core.durable` made a run's **records** survive the process and
:mod:`core.runtime.resume` made them usable — a killed run can be picked
back up and carried on.  Both are about *continuing*.  This module is
about the other thing you want from a recorded run, and it is not the
same thing at all: **running it again**.

Resume continues a run with a live model against a live tool plane.
Replay re-runs a *finished* one with the model it already had and (by
default) the tool results it already got, on a laptop with no server and
no GPU.  The loop is the real loop — the same
:class:`~core.runtime.mission.MissionRunner`, the same grounding
validator, the same records out — and only its two outside edges are
recordings.  That is what makes the interesting question askable:

    *if the grounding grammar had been stricter yesterday, what would
    yesterday's ten missions have said?*

Nothing else in this repository can answer that.  A live re-run asks a
sampling model the same question twice and measures the difference
between two samples; a unit test measures a fabricated answer.  A replay
measures **the change**, because everything except the change is a byte
for byte repeat.

## What is recorded, and where

Beside ``events.jsonl`` in the same run directory, under the same
``JUDAIS_LOBI_RUNS`` policy:

``model.jsonl``
    One fsync'd line per model call, in call order::

        {"call": 1, "at": "…", "kind": "mission",
         "request": {"messages": [...], "extra": {…}},
         "reply": {"content": "…", "tool_calls": [...], "usage": {…}|null}}

    ``kind`` is ``"mission"`` for the loop's own calls and ``"plain"``
    for the swarm's roles — the router, the planner, the gate and the
    synthesizer, which go through ``plain_chat_fn`` and see no tool
    schemas.  Both are numbered in one sequence because they happened in
    one sequence, and a replay that served them out of order would be
    running a different mission.  ``extra`` is the rest of the request as
    it went out: ``tools``, ``tool_choice``, ``response_format``,
    ``stream``, and whatever sampling the run pinned.  ``tool_calls`` and
    ``usage`` are the two **side channels** — read off the backend after
    the call, exactly as :class:`~core.runtime.mission.MissionRunner`
    reads them, because under the native protocol the decision is not in
    the string the call returned.

``tools.jsonl``
    The tool plane, as this run met it.  Line one is the **catalogue**,
    numbered ``0`` because it is not a call::

        {"call": 0, "at": "…", "catalogue": [ <describe_tool(name)>, … ]}

    and every line after it is one dispatch::

        {"call": 1, "at": "…", "tool": "mcp.governed_view",
         "arguments": {"args": [], "kwargs": {…}},
         "result": {"exit_code": 0, "stdout": "…", "stderr": "",
                    "structured": {…}|null}}

    The ``tool_call``/``tool_result`` records in ``events.jsonl`` already
    carry the name, the arguments, the output and the exit code, and a
    replay could *almost* be driven off them.  Almost is the problem:
    ``structuredContent`` — the typed half of an MCP result — never
    travelled on the event stream, which is the first sentence of
    :data:`core.runtime.resume.LOST_STRUCTURED`.  A replay driven off the
    events would hand the model a result the live run never saw.  So the
    raw dispatch is recorded here, and the replayed run has the bytes.

**These two files are as sensitive as ``events.jsonl``, they live in the
same directory, and one variable governs all three.**  ``messages`` holds
the persona, the catalogue and every tool output the model was shown —
the same material the event log holds, and ``JUDAIS_LOBI_RUNS=none``
keeps none of it.

They are scrubbed **less** than the event log, and the difference is the
whole design.  :func:`core.redact.scrub_record` takes five families out
of a record on its way to a pane: credentials, absolute paths, this
host's name, and so on.  Here only the first two run —
:func:`core.redact.scrub_secrets`, credentials and nothing else — because
the other three are *the model's input*, and a recording whose paths were
rewritten is a recording of a prompt nobody ever sent.  Replaying it
would measure a run that did not happen, which is the one thing a replay
must not do.

The credential is the exception that proves it, and it is an exception on
the evidence.  ``MCP_TOKEN`` is a transport header: it reaches
:class:`~core.tools.mcp_client.McpClient` and never a prompt, so taking
it out of the request cannot change the request.  What it *can* reach is
a **reply** — a model told about a token, or a server echoing back the
header it rejected — and that is a leak rather than an input.  So one
rule holds for the whole run directory, the one
:meth:`core.durable.RunStore.create` already states for ``meta.json``: a
credential is never written down here, whichever file it arrived in.

## Drift, and why there is no ``--replay-loose``

A replay serves the recorded replies **by ordinal**.  Before serving call
*n* it compares the messages it was just handed against the messages
recorded for call *n*, canonicalised as JSON; a difference is **drift**,
and the first one is reported on the console, written into the new run's
``meta.json`` and counted.

It is not a refusal, and that is a decision worth defending.  The whole
point of a replay is to change one thing and see what it does, and some
of the things worth changing *are in the prompt*: a repair sentence, a
caveat, a catalogue description.  A run whose prompt changed at turn four
still tells you what the grounding verdict became, and refusing it would
make the feature useless for exactly the experiment it exists for.  What
must never happen is that the change is **invisible** — so drift is on
the record, in the meta of the replayed run, where a scorer reads it and
a report shows it.

There is deliberately no flag that turns the comparison off.  A loose
replay measures nothing: if you do not know whether the model was
answering the question you think it was answering, the number at the end
is a number about an unknown run.  The comparison is free, so it is
always made, and the only choice offered is what to *do* about it — which
is: say so, and carry on.

Two things the replay legitimately does not reproduce, both stated rather
than papered over:

* **``answer_delta``.**  A recording holds the reply, not the frames it
  arrived in, so a replay hands the loop a whole string and streaming is
  off.  The ``answer`` record is authoritative and arrives identically —
  which is the same sentence ``--no-stream`` already carries.
* **wall clock and ids.**  ``elapsed_s``, ``at``, ``run_id`` and any
  provider id are properties of the run that is happening now.  A test
  comparing a replay to its recording compares everything else.

## Where the replayed run goes

Into a **new run directory**, with a new id, whose ``meta.json`` carries
``replay_of`` and ``drift``.  Not back into the recorded one: a replay is
a run, it emits the whole stream from ``mission_started`` to
``mission_finished``, and appending it to the log it was made from would
produce a run with two openings and two endings — the exact shape
:meth:`core.runtime.mission.MissionRunner.run` refuses to make on a
resume.  It also means the replayed run is an ordinary run directory:
anything that scores a run scores it without knowing it is one, and it
can itself be replayed.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from typing import (
    Any, Callable, Dict, Iterable, Iterator, List, Mapping, Optional,
    Sequence, Tuple,
)

from core.durable import NoSuchRun, Run, RunStore, fsync_append, now
from core.redact import scrub_secrets
from core.runtime.answer_stream import AnswerStream
from core.runtime.backends.base import Usage
from core.runtime.contract import MISSION_STARTED

__all__ = [
    "MODEL_LOG", "TOOL_LOG", "REPLAY_TOOLS", "TOOLS_LIVE",
    "TOOLS_RECORDED", "CATALOGUE_CALL",
    "Recorder", "RecordingBus",
    "Recording", "ReplayBus", "ReplayModel", "ReplayExhausted",
    "ReplayRefused", "canonical", "first_difference", "open_for_replay",
    "without_credentials",
]

#: The model log, beside ``events.jsonl`` in the run directory.
MODEL_LOG = "model.jsonl"

#: The tool log, beside it.  Line one is the catalogue; see the module
#: docstring.
TOOL_LOG = "tools.jsonl"

#: The ordinal a catalogue line carries.  Zero, because it is the plane a
#: run was offered and not a call it made, and because it lets a reader
#: tell the two apart without a type tag.
CATALOGUE_CALL = 0

#: Serve the recorded tool results.  The default, and the reason a replay
#: needs no server: every result the model was shown is already on disk.
TOOLS_RECORDED = "recorded"

#: Dispatch against the real plane, with the model still a recording.  For
#: the experiment where the *tools* are what changed — a server that now
#: returns a field it did not — and it needs ``--mcp-url``/``--mcp-stdio``
#: like any other mission.
TOOLS_LIVE = "live"

REPLAY_TOOLS: Tuple[str, ...] = (TOOLS_RECORDED, TOOLS_LIVE)


# ── one spelling of "the same" ───────────────────────────────────────────────


def canonical(value: Any) -> str:
    """*value* as the one JSON string this module compares by.

    Sorted keys and no incidental whitespace, so two dicts that differ
    only in the order Python happened to build them in are the same
    message.  ``default=str`` for the reason
    :func:`core.durable.atomic_write_json` has it: refusing to compare
    two requests because one held a ``Path`` would be a worse answer than
    comparing their renderings.
    """
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), default=str)


def without_credentials(value: Any) -> Any:
    """*value* with every credential in it replaced, and nothing else.

    :func:`core.redact.scrub_secrets` over every string, walked rather
    than applied to the serialised line, so a secret that happens to
    contain a character JSON escapes is still matched — a redactor that
    only works on values nobody quoted is a redactor that misses the
    interesting one.

    The one owner of *what a credential looks like* stays
    :mod:`core.redact`.  What is decided here is only **which** of its
    five families run over a recording, and the answer is the two that
    cannot change what the model was asked.  See the module docstring.
    """
    if isinstance(value, str):
        return scrub_secrets(value)
    if isinstance(value, dict):
        return {key: without_credentials(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [without_credentials(item) for item in value]
    return value


def first_difference(left: Sequence[Any], right: Sequence[Any]) -> Optional[int]:
    """The index of the first element that differs, or ``None``.

    A shorter list differs at the point it runs out, which is the honest
    reading: a request with three messages where four were recorded is
    not "the same up to the end", it is a different request.
    """
    for index in range(max(len(left), len(right))):
        if index >= len(left) or index >= len(right):
            return index
        if canonical(left[index]) != canonical(right[index]):
            return index
    return None


def _jsonable(value: Any) -> Any:
    """*value* if :mod:`json` can write it, else its ``str``.

    Applied to the two side channels and to ``extra``, both of which come
    from a caller-supplied client and may hold anything at all.  A model
    call must not fail because the thing recording it could not serialise
    a provider's object, so the fallback is a rendering rather than an
    exception.
    """
    try:
        json.dumps(value, allow_nan=False, default=None)
        return value
    except (TypeError, ValueError):
        return json.loads(json.dumps(value, default=str))


def _usage_payload(usage: Any) -> Optional[Dict[str, Any]]:
    """A provider's usage as a mapping, or ``None`` for "nothing reported".

    Round-trips through :meth:`core.runtime.backends.base.Usage.as_record`
    where there is one, because that is the shape
    :meth:`~core.runtime.backends.base.Usage.from_payload` reads back —
    one owner of what a usage report looks like, so a replayed run's
    ledger is the recorded run's ledger and not an approximation of it.
    """
    if usage is None:
        return None
    record = getattr(usage, "as_record", None)
    if callable(record):
        try:
            return dict(record())
        except Exception:                       # pragma: no cover - defensive
            return None
    if isinstance(usage, dict):
        return dict(usage)
    return None


def _read_log(path: Any) -> List[Dict[str, Any]]:
    """Every parseable line of a JSONL, oldest first.

    A line that will not parse is skipped rather than fatal, for the
    reason :meth:`core.durable.RunStore.since` gives: only the last line
    can tear, and the alternative is a recording that will not open
    again.
    """
    if not path.exists():
        return []
    out: List[Dict[str, Any]] = []
    with path.open(encoding="utf-8") as log:
        for line in log:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if isinstance(record, dict):
                out.append(record)
    return out


# ── the recorder ─────────────────────────────────────────────────────────────


class Recorder:
    """Writes ``model.jsonl`` and ``tools.jsonl`` for one run.

    Constructed by the CLI when a run store is on — which is the default
    — and wired in at exactly two places, because two places is how many
    outside edges a mission has:

    * :meth:`wrap` goes around the one function that calls the backend,
      so both ``chat_fn`` and ``plain_chat_fn`` are covered by wrapping
      it twice with different ``kind``\\ s rather than by two wrappers
      that would drift;
    * :meth:`bus` goes around the tool bus, as a proxy rather than a hook
      on :class:`~core.tools.bus.ToolBus`, because the bus serves chat
      turns and kernel roles as well as missions and has no business
      learning what a run directory is.

    *side* is how the two side channels are read after a call — a
    callable returning ``(usage, tool_calls)``.  Passed in rather than
    reached for, because the object holding them is the backend on a live
    run and the :class:`ReplayModel` on a replayed one, and this class
    must not know the difference.

    Call numbering continues an existing file rather than starting again,
    so a **resumed** run appends to the recording it is continuing and the
    ordinals still say what order things happened in.
    """

    def __init__(self, store: RunStore, run_id: str, *,
                 side: Optional[Callable[[], Tuple[Any, Any]]] = None) -> None:
        directory = store.directory(run_id)
        self.run_id = run_id
        self.model_path = directory / MODEL_LOG
        self.tools_path = directory / TOOL_LOG
        self._side = side or (lambda: (None, []))
        self._lock = threading.Lock()
        self._calls = _highest_call(self.model_path)
        self._dispatches = _highest_call(self.tools_path)

    # ── the model ───────────────────────────────────────────────────────

    def wrap(self, ask: Callable[..., Any], *, kind: str) -> Callable[..., Any]:
        """*ask*, recording every call.  Same shape in, same shape out.

        *ask* is ``(messages, **extra) -> str | iterator``, which is the
        shape :meth:`core.runtime.mission.MissionRunner._model_reply`
        already accepts either half of.

        **A streamed reply is teed, not buffered.**  The wrapper returns a
        generator that yields each frame the moment it arrives — the
        deltas a pane is rendering must not wait on a recorder — and folds
        each one into an :class:`~core.runtime.answer_stream.AnswerStream`
        on the way past, purely to accumulate ``content``.  That class is
        used with ``native=True`` and no ``answer_tool``, which switches
        *both* decoders off: what is wanted here is the reply, not the
        answer inside it, and the loop's own drain is the one place that
        decodes.  The record is written when the iterator is exhausted,
        in a ``finally``, so a server that died mid-answer still leaves
        the fragments it managed on disk.
        """
        def recorded(messages: Sequence[Dict[str, Any]], **extra: Any) -> Any:
            request = {"messages": [dict(m) for m in messages],
                       "extra": _jsonable(dict(extra))}
            got = ask(messages, **extra)
            if isinstance(got, str) or got is None or not hasattr(got, "__iter__"):
                self.model_call(kind, request, str(got or ""))
                return got
            return self._tee(kind, request, got)

        return recorded

    def _tee(self, kind: str, request: Dict[str, Any],
             chunks: Iterable[Any]) -> Iterator[Any]:
        stream = AnswerStream(lambda _text: None, native=True)
        try:
            for chunk in chunks:
                stream.feed(chunk)
                yield chunk
        finally:
            self.model_call(kind, request, stream.close())

    def model_call(self, kind: str, request: Dict[str, Any],
                   content: str) -> Dict[str, Any]:
        """Write one ``model.jsonl`` line and hand it back.

        The side channels are read **here**, after the call and before the
        record, which is the same moment and the same order the loop reads
        them in.  Reading them earlier would record the previous call's.

        Preferred over the ``side()`` callable is the per-call slot
        :func:`core.runtime.backends.base.capturing` opens around the call
        that is running on this context — the same slot ``Model.spend``
        prefers, for the same reason: under two gathered children sharing
        one client the shared ``last_usage`` can already be the sibling's by
        the time this line runs, and a recording that bills one child for
        the other's call replays as the wrong run.  A slot nobody filled
        (a scripted client, a replayed run) falls back to ``side()``, which
        is what every serial recording always read.
        """
        try:
            from core.runtime.backends.base import _capture
            slot = _capture.get()
        except Exception:                       # pragma: no cover - defensive
            slot = None
        if slot is not None and slot.filled:
            usage, tool_calls = slot.usage, list(slot.tool_calls)
        else:
            try:
                usage, tool_calls = self._side()
            except Exception:                   # pragma: no cover - defensive
                usage, tool_calls = None, []
        with self._lock:
            self._calls += 1
            record = {
                "call": self._calls,
                "at": now(),
                "kind": kind,
                "request": request,
                "reply": {
                    "content": content,
                    "tool_calls": _jsonable(list(tool_calls or [])),
                    "usage": _usage_payload(usage),
                },
            }
            fsync_append(self.model_path,
                         canonical(without_credentials(record)))
        return record

    # ── the tool plane ──────────────────────────────────────────────────

    def bus(self, bus: Any) -> "RecordingBus":
        """*bus*, recording every dispatch into ``tools.jsonl``."""
        return RecordingBus(bus, self)

    def catalogue(self, bus: Any, names: Sequence[str]) -> Dict[str, Any]:
        """Write the plane this run was offered, as the bus describes it.

        ``describe_tool`` and not a second rendering of a tool's contract,
        for the reason :meth:`core.runtime.mission.MissionRunner.catalogue`
        gives: the day a server changes a description, a copy disagrees.
        It is also exactly what :class:`ReplayBus` has to hand back, so a
        replayed run builds its system prompt and its function schemas
        from the same bytes the recorded run did.
        """
        described = []
        for name in names:
            try:
                info = bus.describe_tool(name)
            except Exception:                   # pragma: no cover - defensive
                continue
            if isinstance(info, dict) and "error" not in info:
                described.append(_jsonable(dict(info)))
        record = {"call": CATALOGUE_CALL, "at": now(), "catalogue": described}
        with self._lock:
            fsync_append(self.tools_path,
                         canonical(without_credentials(record)))
        return record

    def dispatch(self, tool: str, arguments: Dict[str, Any],
                 result: Any) -> Dict[str, Any]:
        """Write one dispatch and hand the line back.

        ``structured`` is :attr:`~core.tools.bus.ToolResult.evidence`,
        parsed back into JSON where it is JSON — which for an MCP tool it
        is, because that field is where ``structuredContent`` arrives (see
        :meth:`core.tools.mcp_client.McpCallResult.as_tuple_with_evidence`).
        Parsed rather than kept as text so the recording holds the typed
        payload and not a rendering of it; the string is kept when it is
        not JSON, because a tool is entitled to put anything there.
        """
        with self._lock:
            self._dispatches += 1
            record = {
                "call": self._dispatches,
                "at": now(),
                "tool": tool,
                "arguments": _jsonable(arguments),
                "result": {
                    "exit_code": int(getattr(result, "exit_code", -1)),
                    "stdout": str(getattr(result, "stdout", "") or ""),
                    "stderr": str(getattr(result, "stderr", "") or ""),
                    "structured": _structured(getattr(result, "evidence", None)),
                },
            }
            fsync_append(self.tools_path,
                         canonical(without_credentials(record)))
        return record


def _structured(evidence: Any) -> Any:
    """A tool's typed payload as JSON, as text, or ``None``."""
    if evidence is None or evidence == "":
        return None
    if isinstance(evidence, (dict, list)):
        return evidence
    try:
        return json.loads(str(evidence))
    except ValueError:
        return str(evidence)


def _highest_call(path: Any) -> int:
    """The largest ``call`` in an existing log, or ``0``."""
    highest = 0
    for record in _read_log(path):
        try:
            highest = max(highest, int(record.get("call", 0)))
        except (TypeError, ValueError):         # pragma: no cover - defensive
            continue
    return highest


class _Proxy:
    """Forward everything to a wrapped object except what a subclass names.

    Both the recording bus and the replay bus are *almost* the bus they
    wrap: the runner reads ``describe_tool``, ``list_tools``,
    ``audit_context``, ``audit_ref``, ``sandbox_name``, ``register`` and
    ``unregister`` off it, and a proxy that reimplemented any of those
    would be a second answer to a question the bus already answers.  So
    the default is to forward, and each subclass overrides the one method
    it exists for.
    """

    def __init__(self, bus: Any) -> None:
        object.__setattr__(self, "_bus", bus)

    def __getattr__(self, name: str) -> Any:
        return getattr(object.__getattribute__(self, "_bus"), name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name.startswith("_"):
            object.__setattr__(self, name, value)
        else:
            setattr(object.__getattribute__(self, "_bus"), name, value)


class RecordingBus(_Proxy):
    """A tool bus that writes every dispatch to ``tools.jsonl``.

    The signature of :meth:`dispatch` restates ``action`` and
    ``deadline_s`` **by name** rather than letting them fall into
    ``**kwargs``, and that is not tidiness.
    :func:`core.runtime.mission._takes_deadline` asks the signature
    whether the bus accepts a wall-clock ceiling, and a proxy that
    swallowed the parameter into ``**kwargs`` would quietly answer no —
    a mission with ``--mission-seconds`` would stop bounding its tool
    calls the moment recording was switched on.  Naming them also keeps
    them out of the recorded ``arguments``, which is right: the ceiling
    is a fact about the run's clock and not about the call, and a replay
    keyed on it would miss every result the moment the clock differed.
    """

    def __init__(self, bus: Any, recorder: Recorder) -> None:
        super().__init__(bus)
        self._recorder = recorder

    def dispatch(self, tool_name: str, *args: Any,
                 action: Optional[str] = None,
                 deadline_s: Optional[float] = None,
                 **kwargs: Any) -> Any:
        result = object.__getattribute__(self, "_bus").dispatch(
            tool_name, *args, action=action, deadline_s=deadline_s, **kwargs)
        try:
            self._recorder.dispatch(
                tool_name, _arguments(args, kwargs, action), result)
        except Exception:                       # pragma: no cover - defensive
            # A recording that could not be written must not cost a tool
            # call, for the reason `ToolBus._log_audit` swallows its own:
            # the thing being recorded is more important than the record.
            pass
        return result


def _arguments(args: Sequence[Any], kwargs: Dict[str, Any],
               action: Optional[str] = None) -> Dict[str, Any]:
    """The dispatch's arguments in the shape both halves agree on.

    ``{"args": [...], "kwargs": {...}}`` is
    :meth:`core.tools.bus.ToolBus._log_audit`'s own shape, reused so a
    recording and an audit line describe one call the same way.
    ``action`` joins it only when there is one, so the ordinary
    single-action call keys identically to the way it always did.
    """
    shaped: Dict[str, Any] = {"args": list(args), "kwargs": dict(kwargs)}
    if action:
        shaped["action"] = action
    return shaped


# ── the door ─────────────────────────────────────────────────────────────────


class ReplayRefused(Exception):
    """This recording will not be replayed, and the message says why.

    An exception and not a returned reason, for
    :class:`core.runtime.resume.ResumeRefused`'s reason: every caller has
    the same and only sane response, and a refusal that can be ignored by
    forgetting to check a tuple is one that will be.
    """


class ReplayExhausted(Exception):
    """The run asked for a model call the recording does not have.

    Raised **from inside the loop**, which is where it is discovered.  It
    is the honest end of a replay whose changed grounding bought itself a
    repair turn the recorded run never took: there is no model here, so
    there is no reply, and inventing one would put a sentence nobody
    generated into a transcript somebody is about to score.

    The loop's ``mission_finished`` still goes out — it is emitted from a
    ``finally`` — so the replayed run closes its own stream as
    ``incomplete`` and the drift is already in its metadata.  What the CLI
    adds is the sentence saying which call ran off the end.
    """


@dataclass
class Recording:
    """One recorded run, admitted for replay.  Facts only, no serving."""

    run_id: str
    #: The objective on record.  The replayed loop is seeded with this and
    #: never with a caller's paraphrase of it.
    objective: str
    #: The store's metadata record as it was at the door.
    meta: Run
    #: Every event record in the log, oldest first, unwrapped.
    records: List[Dict[str, Any]]
    #: Every ``model.jsonl`` line, in call order.
    calls: List[Dict[str, Any]]
    #: Every ``tools.jsonl`` dispatch line, in call order.
    dispatches: List[Dict[str, Any]] = field(default_factory=list)
    #: The last catalogue line's tools, as ``describe_tool`` rendered them.
    catalogue: List[Dict[str, Any]] = field(default_factory=list)
    #: The protocol the recorded run was made under.
    protocol: str = ""
    #: The recorded ``mission_started.max_steps``.
    max_steps: int = 0
    #: Which plane the replay will use — see :data:`REPLAY_TOOLS`.
    tools: str = TOOLS_RECORDED

    @property
    def names(self) -> List[str]:
        """The recorded catalogue's tool names, in the order it held them."""
        return [str(entry.get("name") or "") for entry in self.catalogue
                if entry.get("name")]

    @property
    def recorded_tools(self) -> bool:
        """Whether the tool plane is a recording rather than a server."""
        return self.tools == TOOLS_RECORDED

    def model(self, **kwargs: Any) -> "ReplayModel":
        """The chat function this recording serves."""
        return ReplayModel(self.calls, **kwargs)

    def bus(self, bus: Any) -> "ReplayBus":
        """*bus*, with the recorded plane in front of it."""
        return ReplayBus(bus, self.catalogue, self.dispatches)


def open_for_replay(store: Optional[RunStore], run_id: str, *,
                    objective: str = "", tools: str = TOOLS_RECORDED) -> Recording:
    """Admit *run_id* for replay, or refuse and name the rule it broke.

    Every refusal is answered here, before a run directory is minted and
    before a loop is built, for the reason
    :func:`core.runtime.resume.open_for_resume` answers its own at the
    door: a refusal that arrives at the end is a refusal that cost what it
    was meant to save.

    The refusals are the incomplete recordings, and each names the file
    that is missing, because "replay failed" over a run somebody recorded
    yesterday is the message that gets a feature deleted.  The objective
    check is :func:`~core.runtime.resume.open_for_resume`'s, verbatim in
    substance: replaying the wrong run looks exactly like replaying the
    right one.
    """
    if tools not in REPLAY_TOOLS:
        raise ReplayRefused(
            f"--replay-tools: {tools!r} is not a plane this harness serves. "
            f"Choose one of: {', '.join(REPLAY_TOOLS)}.")
    if store is None:
        raise ReplayRefused(
            "there is no run store to replay from: persistence is turned "
            "off (JUDAIS_LOBI_RUNS=none|off), so no mission left a "
            "recording. Unset it, or point it at the directory the "
            "recorded run is in.")
    try:
        meta = store.meta(run_id)
        records = store.records(run_id)
    except NoSuchRun:
        raise ReplayRefused(
            f"no run {run_id!r} under {store.root}. Run ids are minted by "
            f"the store and printed when a mission starts; they also ride "
            f"the opening frame as `mission_started.run_id`.") from None

    directory = store.directory(run_id)
    calls = [line for line in _read_log(directory / MODEL_LOG)
             if line.get("request") is not None]
    if not calls:
        raise ReplayRefused(
            f"run {run_id} has no {MODEL_LOG}: it was recorded before this "
            f"harness kept the model's own input and output, or it never "
            f"reached a model. A replay serves the recorded replies, so "
            f"without that file there is nothing to serve. `--resume` "
            f"continues such a run against a live model; replay cannot.")

    opening = [r for r in records if r.get("event") == MISSION_STARTED]
    if not opening:
        raise ReplayRefused(
            f"run {run_id} never got as far as opening — its log holds no "
            f"`mission_started`, so there is no objective and no catalogue "
            f"to replay against.")

    recorded_objective = str(opening[-1].get("objective") or "")
    wanted = (objective or "").strip()
    if wanted and wanted != recorded_objective:
        raise ReplayRefused(
            f"run {run_id} is not that mission. It was started with "
            f"{recorded_objective!r} and this command says {wanted!r}. "
            f"Replaying would re-run the recorded objective while you "
            f"watched for yours, and nothing on the stream would look "
            f"wrong — so pass the recorded objective, or omit it and the "
            f"run supplies it.")

    lines = _read_log(directory / TOOL_LOG)
    catalogue: List[Dict[str, Any]] = []
    for line in lines:
        if isinstance(line.get("catalogue"), list):
            catalogue = [entry for entry in line["catalogue"]
                         if isinstance(entry, dict)]
    dispatches = [line for line in lines if line.get("tool")]

    if tools == TOOLS_RECORDED and not catalogue:
        raise ReplayRefused(
            f"run {run_id} has no recorded tool plane ({TOOL_LOG} holds no "
            f"catalogue), so a replay with --replay-tools {TOOLS_RECORDED} "
            f"has no tools to offer the model and would build a different "
            f"prompt than the one that was recorded. Replay it with "
            f"--replay-tools {TOOLS_LIVE} against the server it ran on.")

    return Recording(
        run_id=run_id,
        objective=recorded_objective,
        meta=meta,
        records=records,
        calls=calls,
        dispatches=dispatches,
        catalogue=catalogue,
        protocol=str(opening[-1].get("protocol") or ""),
        max_steps=int(opening[-1].get("max_steps") or 0),
        tools=tools,
    )


# ── the model, served back ───────────────────────────────────────────────────


class ReplayModel:
    """Serves recorded replies in order, and says where the run diverged.

    Shaped like a backend on purpose: :attr:`last_usage` and
    :attr:`last_tool_calls` are set on every served call, so the CLI's
    ``usage_fn`` and ``tool_calls_fn`` read a replay exactly as they read
    a client and the loop cannot tell the difference.  That matters more
    than it looks: under the native protocol the *decision* is in the tool
    calls, not in the returned string, and a replay that served only the
    string would replay a native run as a run that said nothing.

    *on_drift* is called once, with the first divergence, so the CLI can
    print it and the run's metadata can hold it before anything else
    happens — a replay that crashed later would otherwise lose the one
    fact explaining why.
    """

    def __init__(self, calls: Sequence[Mapping[str, Any]], *,
                 on_drift: Optional[Callable[[Dict[str, Any]], None]] = None):
        self._calls = [dict(call) for call in calls]
        self._served = 0
        self._on_drift = on_drift
        #: The first divergence, or ``None``.  See the module docstring.
        self.drift: Optional[Dict[str, Any]] = None
        #: How many served calls saw messages the recording did not have.
        self.drifted = 0
        self.last_usage: Optional[Usage] = None
        self.last_tool_calls: List[Dict[str, Any]] = []

    @property
    def served(self) -> int:
        return self._served

    def serving(self, kind: str) -> Callable[..., str]:
        """The ``(messages, **extra) -> str`` this recording answers *kind* with.

        Two callables over one ordinal rather than two queues, because the
        mission's calls and the swarm's roles happened in one order and a
        replay that served them from separate queues would run the router
        against the loop's fourth turn.
        """
        def ask(messages: Sequence[Dict[str, Any]], **extra: Any) -> str:
            return self.serve(kind, list(messages))

        return ask

    def serve(self, kind: str, messages: List[Dict[str, Any]]) -> str:
        """The next recorded reply, its side channels, and any drift."""
        if self._served >= len(self._calls):
            raise ReplayExhausted(
                f"the recording has {len(self._calls)} model call(s) and "
                f"this run wants call {self._served + 1} ({kind}). A replay "
                f"has no model: the run has diverged far enough to need a "
                f"turn that was never recorded — a repair turn a stricter "
                f"grounding grammar bought itself, most likely. What ran "
                f"before this point is on the record and the run's "
                f"`mission_finished` says `incomplete`.")
        call = self._calls[self._served]
        self._served += 1
        self._check(call, kind, messages)
        reply = call.get("reply") or {}
        self.last_usage = Usage.from_payload(reply.get("usage"))
        self.last_tool_calls = [dict(entry) for entry
                                in (reply.get("tool_calls") or [])
                                if isinstance(entry, dict)]
        return str(reply.get("content") or "")

    def _check(self, call: Mapping[str, Any], kind: str,
               messages: List[Dict[str, Any]]) -> None:
        recorded = list((call.get("request") or {}).get("messages") or [])
        where = first_difference(messages, recorded)
        recorded_kind = str(call.get("kind") or "")
        if where is None and (not recorded_kind or recorded_kind == kind):
            return
        self.drifted += 1
        if self.drift is not None:
            return
        ordinal = int(call.get("call") or self._served)
        if where is None:
            detail = (f"replay drift: call {ordinal} was recorded as a "
                      f"{recorded_kind!r} call and this run made it as "
                      f"{kind!r}")
            where = -1
        else:
            detail = (f"replay drift: call {ordinal} differs at message "
                      f"{where} — the run is no longer asking what the "
                      f"recording asked, and the reply it gets is still "
                      f"the recorded one")
        self.drift = {"call": ordinal, "kind": kind, "message": where,
                      "detail": detail}
        if self._on_drift is not None:
            try:
                self._on_drift(dict(self.drift))
            except Exception:                   # pragma: no cover - defensive
                pass

    def as_record(self) -> Dict[str, Any]:
        """What the replayed run's ``meta.json`` carries about the drift."""
        return {"first": self.drift, "calls": self.drifted,
                "served": self._served, "recorded": len(self._calls)}


# ── the tool plane, served back ──────────────────────────────────────────────


@dataclass(frozen=True)
class _Result:
    """What :meth:`~core.runtime.mission.MissionRunner._dispatch` reads.

    Not a :class:`~core.tools.bus.ToolResult`: the bus's shape is the
    bus's, a replay is not a dispatch, and this module deliberately does
    not import the tool layer — the same decision, for the same reason,
    as :class:`core.runtime.resume._Result`.  What it has to be is
    whatever the caller reads off a result, which is these five
    attributes.
    """

    exit_code: int
    stdout: str
    stderr: str
    tool_name: str = ""
    evidence: Optional[str] = None


class ReplayBus(_Proxy):
    """A tool plane made of a recording: no server, no subprocess, no clock.

    :meth:`describe_tool` answers from the recorded catalogue where it
    can, so the system prompt a replayed run builds is the prompt the
    recorded run was given — a replay whose catalogue came from whatever
    tools happen to be registered on this laptop would drift at message
    zero of every call and measure nothing.  Names the recording does not
    hold fall through to the wrapped bus, which is what serves
    ``mission_result``: the store registers itself for the length of a run
    and is in-process, deterministic and not part of the recording.

    :meth:`dispatch` serves recorded results keyed by tool and by
    canonicalised arguments, in the order they were recorded.  A key whose
    recorded results are used up serves the last of them again — a loop
    that made the same call twice got an answer both times, and this is
    the only answer the recording has for it.  A call the recording never
    saw gets a **refusal-shaped result** rather than a live dispatch: the
    point of ``--replay-tools recorded`` is that nothing leaves the
    process, and a silent fall-through to the real plane would make a
    replay reach a server on a run somebody thought was offline.
    """

    def __init__(self, bus: Any, catalogue: Sequence[Mapping[str, Any]],
                 dispatches: Sequence[Mapping[str, Any]]) -> None:
        super().__init__(bus)
        self._described = {str(entry.get("name")): dict(entry)
                           for entry in catalogue if entry.get("name")}
        self._served: Dict[str, int] = {}
        self._recorded: Dict[str, List[Dict[str, Any]]] = {}
        for line in dispatches:
            key = _key(str(line.get("tool") or ""), line.get("arguments") or {})
            self._recorded.setdefault(key, []).append(dict(line))
        self._missing: List[str] = []

    @property
    def missing(self) -> List[str]:
        """Every ``(tool, arguments)`` this replay was asked for and did
        not have.  Read by a test and by nothing else — the refusal itself
        is what the model is told.

        A property rather than an attribute because :class:`_Proxy`
        forwards every public *assignment* to the bus it wraps, which is
        the right default for a proxy and would otherwise have quietly
        hung this list off somebody's :class:`~core.tools.bus.ToolBus`.
        """
        return self._missing

    def describe_tool(self, name: str) -> Dict[str, Any]:
        described = self._described.get(str(name))
        if described is not None:
            return dict(described)
        return object.__getattribute__(self, "_bus").describe_tool(name)

    def list_tools(self) -> List[str]:
        names = list(self._described)
        for name in object.__getattribute__(self, "_bus").list_tools():
            if name not in self._described:
                names.append(name)
        return names

    def dispatch(self, tool_name: str, *args: Any,
                 action: Optional[str] = None,
                 deadline_s: Optional[float] = None,
                 **kwargs: Any) -> Any:
        """The recorded result for this call, or a refusal naming the gap.

        ``deadline_s`` is named and dropped for
        :class:`RecordingBus`'s reason and one more: a replay has no
        clock worth honouring, and a recorded result cannot time out.
        """
        key = _key(tool_name, _arguments(args, kwargs, action))
        recorded = self._recorded.get(key)
        if not recorded:
            self._missing.append(key)
            return _Result(
                exit_code=-1, stdout="", tool_name=tool_name,
                stderr=json.dumps({
                    "error": "not_in_recording",
                    "tool": tool_name,
                    "message": (
                        f"{tool_name} was not called with these arguments in "
                        f"the recorded run, so this replay has no result for "
                        f"it. The step ends here rather than reaching a "
                        f"server: --replay-tools recorded is offline by "
                        f"construction. Re-run it with --replay-tools live "
                        f"to dispatch against the real plane."),
                }))
        index = min(self._served.get(key, 0), len(recorded) - 1)
        self._served[key] = index + 1
        result = recorded[index].get("result") or {}
        structured = result.get("structured")
        return _Result(
            exit_code=int(result.get("exit_code", 0)),
            stdout=str(result.get("stdout") or ""),
            stderr=str(result.get("stderr") or ""),
            tool_name=tool_name,
            evidence=(None if structured is None
                      else structured if isinstance(structured, str)
                      else canonical(structured)),
        )


def _key(tool: str, arguments: Any) -> str:
    """The one string a recorded call and a replayed one are matched on."""
    return canonical([tool, arguments])
