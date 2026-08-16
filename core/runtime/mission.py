# core/runtime/mission.py — the loop where the model chooses the tool

"""A plan/act loop seeded with ``tools/list``.

Everywhere else in this package the *operator* chooses the tool: you
type ``--shell`` and a shell tool runs, ``--search`` and a search tool
runs.  That works because the tool set is fixed and the person typing
knows it.

It cannot work for an agent talking to a server it discovers at runtime.
Nobody can add a flag for a tool that did not exist when the CLI was
written.  So the mission flow inverts it: the catalogue is put in front
of the model, and the model names the tool.

The loop is deliberately small and its refusals are deliberately loud:

* every call goes through ``ToolBus.dispatch``, so capability gating,
  the panic switch and the audit log all still apply.  The runner never
  touches a store, a path or a compute plane itself, and holds no HTTP
  client of its own;
* the model replies with **one** JSON object and nothing else.  A reply
  that does not parse is handed back to the model as a parse error
  rather than guessed at;
* a tool the model invented is a refused step with the real catalogue
  repeated, not a crash;
* the step budget is a hard stop.  Running out is a recorded outcome
  (``budget_exhausted``) and not a silent truncation;
* a tool result is **bounded** before it enters the transcript, and the
  whole of it stays in a per-mission store the model can read one field
  of.  See :mod:`core.runtime.results` for why an unbounded paste is a
  correctness problem and not a tidiness one;
* the **conversation** is bounded too, when the caller supplies a
  window: bounding each result says nothing about the sum of them, and
  the sum is what meets ``max_model_len``.  Oldest round trips go first,
  the persona, catalogue, seeded turns, objective and newest result stay,
  and the drop is a record on the stream rather than a shorter prompt
  nobody mentioned.  See :class:`~core.runtime.context_window.MissionWindow`;
* an answer is **checked against the run's own tool output** when the
  skill supplied a grammar for it.  See :mod:`core.runtime.grounding`.

Two of those are configured by content the harness does not own: the
tool subset and the prompt come from a skill manifest
(:mod:`core.runtime.skills`), and so does the identifier grammar.  The
loop supplies the mechanism and nothing else.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from core.bounding import MAX_RESULT_BYTES, bound_result
from core.runtime.context_window import (
    Compaction, MissionWindow, default_compaction_note,
)
from core.runtime.contract import SCHEMA_VERSION
from core.runtime.grounding import GroundingReport, GroundingValidator
from core.runtime.mission_stream import (
    ANSWER, GATE_REQUESTED, GROUNDING, MISSION_FINISHED, MISSION_STARTED,
    REPLY_REJECTED, STEP_STARTED, TOOL_CALL, TOOL_RESULT, Observer,
)
from core.runtime.results import RESULT_TOOL, MissionResultStore
from core.tools.descriptors import same_tool, summarize_input_schema


def _profile_field(bus: Any) -> Dict[str, Any]:
    """``{"profile": name}`` when the bus knows its capability profile, else
    ``{}``.

    The ``profile`` on ``mission_started`` is the OPTIONAL field that lets a
    watcher see, in the opening frame, which capability profile a run is
    governed by — a deny-by-default ``safe`` mission and a ``god`` one look
    identical on the wire otherwise. Absent (not ``null``) when the bus was
    built from a raw capability engine that never recorded a profile name, so
    "profile" is a fact the stream states only when there is one to state.
    One owner: the swarm's opening frame reads it from here too.
    """
    engine = getattr(bus, "capability_engine", None)
    name = getattr(engine, "current_profile", None) if engine is not None else None
    return {"profile": name} if name else {}


#: The whole protocol between the loop and the model.  Kept in one string
#: because a contract split across three f-strings is a contract that
#: drifts from the parser below it.
PROTOCOL = """\
You are working a mission with tools. Reply with exactly one JSON object \
and no other text, no code fence, no commentary.

To use a tool:
  {"tool": "<tool name from the catalogue>", "arguments": {...}}

To finish:
  {"answer": "<your final answer>"}

Use only tool names from the catalogue below, spelled exactly. Call one \
tool per reply. Base every statement on a tool result you actually \
received; if the tools cannot support a statement, say so in the answer \
instead of asserting it.
"""

_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.MULTILINE)

#: Bounds on a seeded conversation history, chosen as a safety net and not
#: a working limit.  The one caller that seeds history today (TAIPAN's
#: Mission Pane) already caps what it sends at 12 turns of ≤4,000
#: characters — ~48 KB worst case — so anything near these numbers is a
#: caller that lost its own cap, and the honest response is a refusal at
#: the door rather than a silent trim.  An oversized history has the same
#: defect as an unbounded tool result (see :mod:`core.bounding`): it can push
#: the catalogue and the protocol out of a small model's window with
#: nothing in the answer saying so.
HISTORY_MAX_TURNS = 100
HISTORY_MAX_CHARS = 262_144


def validate_history(turns: Any) -> List[Dict[str, str]]:
    """*turns* as a clean ``[{"role", "content"}, …]``, or ``ValueError``.

    The one answer to "is this a conversation history this loop will
    seed".  Both callers use it — :class:`MissionRunner` on whatever it
    is constructed with, and the CLI on what ``--history`` read from disk
    — so a history the CLI accepted is a history the runner accepts, and
    the refusal text is identical wherever the bad shape arrives.

    Refusals are loud on purpose.  A malformed history silently dropped
    would reproduce the exact failure this feature exists to fix: an
    agent that looks like it has the conversation and answers as if it
    does not.
    """
    # A tuple is allowed because it is what a Python caller's default
    # argument looks like; anything else — a dict, a string — is a caller
    # holding the wrong shape, and coercing it would validate its pieces
    # rather than the mistake.
    if not isinstance(turns, (list, tuple)):
        raise ValueError(
            f"history must be a JSON array of "
            f'{{"role": "user"|"assistant", "content": "..."}} objects, '
            f"got {type(turns).__name__}"
        )
    if len(turns) > HISTORY_MAX_TURNS:
        raise ValueError(
            f"history has {len(turns)} turns; the cap is "
            f"{HISTORY_MAX_TURNS}. Trim it at the caller — a silent trim "
            f"here would hide which turns the model never saw."
        )
    cleaned: List[Dict[str, str]] = []
    total = 0
    for index, turn in enumerate(turns):
        if not isinstance(turn, dict):
            raise ValueError(
                f"history[{index}] must be an object with 'role' and "
                f"'content', got {type(turn).__name__}"
            )
        role = turn.get("role")
        content = turn.get("content")
        if role not in ("user", "assistant"):
            raise ValueError(
                f"history[{index}].role must be 'user' or 'assistant', "
                f"got {role!r}. System text belongs to the harness, and "
                f"tool turns are this mission's own to make."
            )
        if not isinstance(content, str):
            raise ValueError(
                f"history[{index}].content must be a string, got "
                f"{type(content).__name__}"
            )
        total += len(content)
        cleaned.append({"role": role, "content": content})
    if total > HISTORY_MAX_CHARS:
        raise ValueError(
            f"history totals {total} characters; the cap is "
            f"{HISTORY_MAX_CHARS}. Trim it at the caller."
        )
    return cleaned


def _grounding_record(report: "GroundingReport", *, repairs: int = 0,
                      repairing: bool = False, caveat: str = "") -> Dict[str, Any]:
    """A :class:`GroundingReport` as the observer's ``grounding`` fields.

    Read off the report with ``getattr`` defaults rather than by unpacking a
    known shape: this module's job is to say what the validator said, and a
    check the validator grows next month should reach a watcher as a row in
    ``checks`` rather than as an ``AttributeError`` inside a mission.
    """
    return {
        "ran": bool(getattr(report, "ran", False)),
        "grounded": bool(getattr(report, "grounded", False)),
        # Grounded AND something was actually checked. Carried beside
        # `grounded` rather than instead of it because they are different
        # facts and a watcher that cannot tell them apart is the watcher six
        # missions looked clean to on 10 August.
        "verified": bool(getattr(report, "verified", False)),
        "repairs": repairs,
        "repairing": repairing,
        "caveat": caveat or (getattr(report, "caveat", "") or ""),
        # The tokens themselves, not a count of them. "3 figures were not in
        # any tool output" sends a reader looking; "0.181 was not" tells them
        # where, and 0.181 is the exact figure this check was written after.
        "unsupported": list(getattr(report, "unsupported", ()) or ()),
        # Which checks found nothing in the answer at all, and which of those
        # the skill had required to find something.
        "silent": list(getattr(report, "silent", ()) or ()),
        "uncited": list(getattr(report, "uncited", ()) or ()),
        "checks": [
            {"check": getattr(row, "check", ""),
             "configured": bool(getattr(row, "configured", False)),
             "grounded": bool(getattr(row, "grounded", False)),
             "verdict": getattr(row, "verdict", ""),
             "considered": len(getattr(row, "considered", ()) or ()),
             "minimum": int(getattr(row, "minimum", 0) or 0),
             "unsupported": list(getattr(row, "unsupported", ()) or ()),
             "detail": getattr(row, "detail", "")}
            for row in (getattr(report, "results", ()) or ())
        ],
    }


@dataclass
class MissionStep:
    """One turn: what the model said, and what came back."""

    index: int
    raw_reply: str
    tool: Optional[str] = None
    arguments: Dict[str, Any] = field(default_factory=dict)
    exit_code: Optional[int] = None
    output: str = ""
    error: str = ""
    #: Handle of the full result in the mission's store, when there is one.
    handle: str = ""
    #: Whether what the model was shown was cut down from :attr:`output`.
    truncated: bool = False

    @property
    def refused(self) -> bool:
        return self.exit_code is not None and self.exit_code != 0


#: Terminal outcome for a mission that named a tool this deployment offers and
#: **gates**. The call was not made.  It is not "refused" and it is not
#: "answered": the mission stopped because it reached something a person has to
#: say yes to, and the harness has no way to be that person.
#:
#: Written as its own outcome rather than folded into ``incomplete`` because a
#: caller resuming a gated mission has to be able to tell "nobody has decided
#: yet" from "the model gave up", and those are the same string otherwise.
AWAITING_APPROVAL = "awaiting_approval"


@dataclass
class MissionTranscript:
    """The whole run, in the order it happened."""

    objective: str
    catalogue: List[str] = field(default_factory=list)
    steps: List[MissionStep] = field(default_factory=list)
    answer: Optional[str] = None
    outcome: str = "incomplete"
    #: What the grounding validator said, when one was configured.
    grounding: Optional[GroundingReport] = None
    #: The gated call this mission stopped at, as ``{tool, arguments}``, when
    #: :attr:`outcome` is :data:`AWAITING_APPROVAL`.
    awaiting: Optional[Dict[str, Any]] = None

    @property
    def completed(self) -> bool:
        """Whether the mission produced an answer.

        ``answered_with_caveat`` counts: the answer exists and was
        returned. What it could not support is on the answer itself, in
        words, which is the point of appending a caveat rather than
        discarding the run.
        """
        return self.outcome in ("answered", "answered_with_caveat")


class MissionRunner:
    """Seed the plan with a tool catalogue, then let the model drive.

    Parameters
    ----------
    chat_fn:
        ``messages -> str``.  Injected rather than an ``Agent`` so the
        loop is testable without a backend and so it cannot reach past
        the client it was given.
    bus:
        A :class:`~core.tools.bus.ToolBus`.  The only way out of here.
    tool_names:
        Which registered tools this mission may use.  A subset, not the
        whole bus: a mission agent is given the mission's tools, and
        handing it ``run_shell_command`` because it happened to be
        registered is how a governed run stops being governed.  A skill
        manifest supplies this set; see
        :meth:`core.runtime.skills.SkillManifest.resolve`.
    system_message:
        Persona and skill prompt, already joined by the caller.
    validator:
        A :class:`~core.runtime.grounding.GroundingValidator`, or
        ``None`` for a mission nobody configured a grammar for.  ``None``
        runs exactly as this loop ran before one existed, and the
        transcript's ``grounding`` stays ``None`` rather than claiming a
        clean check.
    store_tool:
        Name to register the per-mission result store under, or ``""``
        to run without one.  Without it, a bounded result is a result
        with a hole in it and nothing to fill the hole from.

    gated:
        Tool names that are **offered and not dispatched**.  The model
        sees them in the catalogue, marked; naming one ends the mission
        at :data:`AWAITING_APPROVAL` with the proposed arguments intact
        and nothing called.

        Offered rather than withheld, on purpose.  A tool simply left
        out of the set produces "there is no tool named X", which is
        false — it exists, this deployment serves it, and the true
        sentence is *somebody has to say yes first*.  A model told the
        false version reroutes around it and reports the capability as
        absent; a model told the true one asks.  And a gate is only
        worth having if what a person approves is the bytes that would
        run, which means the call has to be *proposed* before it is
        stopped.

        The harness supplies the mechanism and never the decision.
        There is deliberately no parameter here by which a caller could
        pre-answer one.
    history:
        Prior conversation turns, oldest first, as
        ``[{"role": "user"|"assistant", "content": …}, …]`` — the
        analyst's questions and the agent's final answers, never the
        tool-call plumbing of earlier missions.  Seeded into the message
        list **as messages**, between the system prompt and the current
        objective.

        As messages and not as text folded into the objective, because
        that difference was measured: a chat-tuned model attends to
        role-tagged turns in its own chat template and skates over the
        same turns pasted into one user string.  On 12 August 2026 a
        served gpt-oss-20b, given the prior turns as an "Earlier in this
        conversation:" preamble inside the objective, answered "tell me
        more about headline #2" by web-searching the literal string
        "headline #2" — the headlines were in the prompt and the model
        never looked.  The default ``()`` is a mission that starts cold,
        exactly as every mission started before this parameter existed.
    observer:
        ``dict -> None``, called with one record per thing that happens.
        See :mod:`core.runtime.mission_stream` for the vocabulary; it is
        a published contract rather than these dataclasses' field names.
        ``None`` runs exactly as this loop ran before one existed.

        A mission on a local model is minutes long, and a caller holding
        only :meth:`run` has nothing to show for any of them.
    window:
        A :class:`~core.runtime.context_window.MissionWindow`, or ``None``
        for a loop that sends whatever it has accumulated.

        ``None`` is what this loop did until now, and what it did was
        grow one message list across every step of the budget and hand
        the whole of it to the backend each time.  Each result is
        bounded (``MAX_RESULT_BYTES``) and each is at most one step's
        worth, so nothing here is individually large; the sum is.  Eight
        steps of bounded results is a quarter of a megabyte of prompt,
        and against a served model with a real ``max_model_len`` the end
        of that is a 400 from the server or a silent eviction inside it
        — the second being the dangerous one, because the model then
        answers from a conversation it can no longer fully see and
        nothing in the answer says which half went.

        With a window, the compactable middle is dropped oldest-first
        before each step, the persona/catalogue/history/objective prefix
        and the newest round trip survive, and the drop is announced on
        the stream as ``step_started.compacted``.  Nothing is lost to the
        *run*: the whole of every result stays in :attr:`store`, which is
        what the grounding validator reads and what the model can still
        address by handle.

    The store tool is offered **in addition to** ``tool_names``, and
    that is not a hole in a closed set: it reaches nothing outside the
    mission.  Every byte it can return already arrived through a gated,
    audited ``dispatch`` of a tool the set allowed, and was shown to
    this same model a moment earlier in truncated form.
    """

    def __init__(
        self,
        chat_fn: Callable[[List[Dict[str, str]]], Any],
        bus: Any,
        tool_names: Sequence[str],
        *,
        system_message: str = "",
        max_steps: int = 8,
        validator: Optional[GroundingValidator] = None,
        max_result_bytes: int = MAX_RESULT_BYTES,
        store_tool: str = RESULT_TOOL,
        gated: Sequence[str] = (),
        history: Sequence[Dict[str, str]] = (),
        observer: Optional[Observer] = None,
        window: Optional[MissionWindow] = None,
    ):
        self._chat = chat_fn
        self._bus = bus
        self._tool_names = list(tool_names)
        self._system_message = system_message
        self._max_steps = max_steps
        self._validator = validator
        self._max_result_bytes = max(0, int(max_result_bytes))
        self._store_tool = (store_tool or "").strip()
        self._store = MissionResultStore()
        self._gated = frozenset(str(name) for name in gated if name)
        # Validated here as well as at the CLI, because the CLI is one
        # caller of several and a runner seeded with a system turn or a
        # non-string content would fail somewhere much less legible than
        # this line.
        self._history = validate_history(history)
        self._observer = observer
        self._window = window

    @property
    def store(self) -> MissionResultStore:
        """The mission's result store.  One per runner, cleared per run."""
        return self._store

    @property
    def offered(self) -> List[str]:
        """Every tool name the model may name: the set, plus the store."""
        if self._store_tool:
            return [*self._tool_names, self._store_tool]
        return list(self._tool_names)

    @property
    def gated(self) -> List[str]:
        """Offered tools that need a person, in catalogue order."""
        return [name for name in self.offered if name in self._gated]

    # ── telling a watcher ───────────────────────────────────────────────

    def _emit(self, event: str, **fields: Any) -> None:
        """One record to the observer, or nothing.  Never raises.

        A mission must not fail because somebody was watching it, so an
        observer that throws is dropped rather than propagated — the
        alternative is a browser tab closing and taking an 11,000 s
        submission with it.
        """
        if self._observer is None:
            return
        try:
            self._observer({"event": event, **fields})
        except Exception:                       # pragma: no cover - defensive
            pass

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
            info = self._bus.describe_tool(name)
            if "error" in info:
                continue
            desc = info.get("description") or ""
            # Marked in the catalogue rather than withheld from it. See the
            # `gated` parameter: "there is no tool named X" is false and a
            # model told it reroutes around a capability it actually has.
            mark = (" [NEEDS APPROVAL — propose it and a person decides; the "
                    "call is not made until they do]"
                    if name in self._gated else "")
            lines.append(f"- {name}: {desc}{mark}".rstrip())
            arguments = info.get("arguments") or summarize_input_schema(
                info.get("input_schema")
            )
            if arguments:
                lines.append(f"    arguments: {arguments}")
        return "\n".join(lines) if lines else "(no tools available)"

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
        """
        system = "\n\n".join(
            part for part in (
                self._system_message.strip(),
                PROTOCOL.strip(),
                "Tool catalogue:\n" + self.catalogue(),
            ) if part
        )
        return [
            {"role": "system", "content": system},
            *(dict(turn) for turn in self._history),
            {"role": "user", "content": objective},
        ]

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
        return 2 + len(self._history)

    def _compaction_note(self, dropped_turns: int, freed_chars: int) -> str:
        """The default notice, plus where the dropped bytes still are.

        The generic sentence says the work was done and the paste was
        removed.  Only the runner knows the store's name, and naming it
        here is the same teaching move as
        :meth:`_say_it_is_unchanged`: the moment the model loses a result
        from the transcript is the moment to tell it that the result is
        still addressable, because a rule stated 2,000 tokens upstream in
        a persona does not survive to the turn it binds.
        """
        note = default_compaction_note(dropped_turns, freed_chars)
        if not self._store_tool:
            return note
        return (
            f"{note} Every result of this mission is still readable: call "
            f'{self._store_tool}(handle="…", path="…") with the handle you '
            f"were given when it arrived."
        )

    def _fit(
        self, messages: List[Dict[str, str]],
    ) -> Tuple[List[Dict[str, str]], Optional[Compaction]]:
        """``(messages to send, what was dropped or None)``.

        No window is the loop as it ran before there was one: the list
        goes out whole.
        """
        if self._window is None:
            return messages, None
        return self._window.fit(
            messages, pinned=self.pinned, note=self._compaction_note,
        )

    # ── the loop ────────────────────────────────────────────────────────

    def run(self, objective: str) -> MissionTranscript:
        self._store.clear()
        offered = self.offered
        transcript = MissionTranscript(objective=objective, catalogue=list(offered))
        registered = self._register_store()
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
        self._emit(MISSION_STARTED, schema_version=SCHEMA_VERSION,
                   objective=objective, catalogue=list(offered),
                   gated=self.gated, max_steps=self._max_steps,
                   history=len(self._history),
                   sandbox=self._bus.sandbox_name,
                   **_profile_field(self._bus))
        try:
            return self._loop(objective, offered, transcript)
        finally:
            if registered:
                self._bus.unregister(registered)
            # In `finally` so that a mission killed by an exception still tells
            # the watcher the mission is over. A stream that just stops is
            # indistinguishable from an agent that is thinking, and a pane
            # showing a spinner forever is the state an analyst cannot leave.
            # `max_steps` beside `steps` because the two are only meaningful
            # against each other. Six of a stated twenty-four is not an agent
            # that ran out of room, and a consumer holding only the six has no
            # way to stop a reader reading it as one.
            self._emit(MISSION_FINISHED, outcome=transcript.outcome,
                       steps=len(transcript.steps),
                       max_steps=self._max_steps)

    def _register_store(self) -> str:
        """Put the result store on the bus for the length of this run.

        Registered and withdrawn rather than left there: the store holds
        one mission's results, and a descriptor that outlived the run
        would offer the next one a handle into the previous one's
        governed material.  It goes through the bus like everything else
        so the audit log records a read of it.
        """
        if not self._store_tool:
            return ""
        return self._store.register_on(self._bus, self._store_tool)

    def _loop(
        self, objective: str, offered: Sequence[str], transcript: MissionTranscript,
    ) -> MissionTranscript:
        messages = self.seed(objective)
        repairs = 0

        for index in range(self._max_steps):
            # Before the ask, not after the reply: what is compacted is
            # what this step is about to send, and a watcher told about it
            # afterwards has already rendered the turn it applied to.
            messages, compacted = self._fit(messages)
            self._emit(STEP_STARTED, index=index,
                       **({"compacted": compacted.as_record()}
                          if compacted is not None else {}))
            reply = str(self._chat(messages) or "")
            step = MissionStep(index=index, raw_reply=reply)
            messages.append({"role": "assistant", "content": reply})

            decision, problem = self._parse(reply)
            if problem:
                step.error = problem
                transcript.steps.append(step)
                self._emit(REPLY_REJECTED, index=index, problem=problem)
                messages.append({"role": "user", "content": problem})
                continue

            if "answer" in decision:
                answer = str(decision["answer"])
                report = self._ground(answer, repairs)
                transcript.grounding = report

                if report is not None and report.ran and not report.grounded:
                    if repairs < self._validator.max_repairs:
                        repairs += 1
                        problem = self._validator.repair_prompt(report)
                        step.error = problem
                        transcript.steps.append(step)
                        # A repair turn is a whole extra round-trip to the
                        # model and, from outside, looks exactly like a stall.
                        # Said out loud so a watcher can show WHY the answer
                        # is taking longer — the check caught something.
                        self._emit(GROUNDING, **_grounding_record(
                            report, repairs=repairs, repairing=True))
                        messages.append({"role": "user", "content": problem})
                        continue
                    # One repair turn was spent and the claim is still
                    # unsupported. The answer is kept — deleting it would
                    # hide a finding — and says so about itself.
                    caveat = self._validator.caveat(report)
                    marked = GroundingReport(
                        results=report.results, repairs=repairs, caveat=caveat,
                    )
                    transcript.grounding = marked
                    transcript.answer = answer + caveat
                    transcript.outcome = "answered_with_caveat"
                    transcript.steps.append(step)
                    # The verdict BEFORE the answer, so a consumer building a
                    # frame around the prose already knows what to mark it
                    # with. A caveat that arrives after the text it qualifies
                    # is a caveat that can be rendered separately from it.
                    self._emit(GROUNDING, **_grounding_record(
                        marked, repairs=repairs, caveat=caveat))
                    self._emit(ANSWER, text=transcript.answer,
                               outcome=transcript.outcome)
                    return transcript

                if report is not None:
                    transcript.grounding = GroundingReport(
                        results=report.results, repairs=repairs,
                    )
                    self._emit(GROUNDING, **_grounding_record(
                        transcript.grounding, repairs=repairs))
                transcript.answer = answer
                transcript.outcome = "answered"
                transcript.steps.append(step)
                self._emit(ANSWER, text=answer, outcome=transcript.outcome)
                return transcript

            name = str(decision.get("tool") or "")
            arguments = decision.get("arguments") or {}
            if not isinstance(arguments, dict):
                problem = (
                    f'"arguments" must be a JSON object, got '
                    f"{type(arguments).__name__}. Retry with one JSON object."
                )
                step.tool, step.error = name, problem
                transcript.steps.append(step)
                self._emit(REPLY_REJECTED, index=index, tool=name,
                           problem=problem)
                messages.append({"role": "user", "content": problem})
                continue

            step.tool, step.arguments = name, dict(arguments)

            if name not in offered:
                problem = self._no_such_tool(name, offered)
                step.error = problem
                transcript.steps.append(step)
                self._emit(REPLY_REJECTED, index=index, tool=name,
                           problem=problem)
                messages.append({"role": "user", "content": problem})
                continue

            if name in self._gated:
                # STOP. Not dispatched, not retried, and not handed back to
                # the model to work around — the mission ends here holding the
                # exact call it proposed, and somebody who is not this process
                # decides what happens to it.
                reason = (
                    f"{name} needs a person's approval on this deployment. It "
                    f"has been proposed exactly as written and NOT called. "
                    f"Nothing further happens on this mission until somebody "
                    f"decides.")
                step.error = reason
                transcript.steps.append(step)
                transcript.outcome = AWAITING_APPROVAL
                transcript.awaiting = {"tool": name,
                                       "arguments": dict(arguments)}
                self._emit(GATE_REQUESTED, index=index, tool=name,
                           arguments=dict(arguments), reason=reason)
                return transcript

            self._emit(TOOL_CALL, index=index, tool=name,
                       arguments=dict(arguments))
            result = self._bus.dispatch(name, **arguments)
            step.exit_code = result.exit_code
            step.output = result.stdout
            step.error = result.stderr
            stored = self._store.record(
                name, arguments,
                text=result.stdout,
                evidence=getattr(result, "evidence", "") or "",
                exit_code=result.exit_code,
            )
            step.handle = stored.handle
            rendered, step.truncated = self._render_result(
                name, result, stored.handle,
                already=self._store.first_identical(stored),
            )
            transcript.steps.append(step)
            # The WHOLE result, not the bounded rendering. The bound exists
            # because a model's context is finite; a watcher's is not, and a
            # pane showing an analyst 60% of a governed listing because the
            # model could only be shown that much would be inventing a limit
            # nobody imposed.
            self._emit(TOOL_RESULT, index=index, tool=name,
                       arguments=dict(arguments),
                       ok=result.exit_code == 0, exit_code=result.exit_code,
                       output=result.stdout or "", error=result.stderr or "",
                       handle=stored.handle, truncated=step.truncated)
            messages.append({"role": "user", "content": rendered})

        transcript.outcome = "budget_exhausted"
        return transcript

    def _ground(self, answer: str, repairs: int) -> Optional[GroundingReport]:
        """Validate the answer, or ``None`` when nothing is configured."""
        if self._validator is None:
            return None
        report = self._validator.validate(answer, self._store.evidence_texts())
        if not report.ran:
            # Every check said it could not run. That is a report with no
            # opinion, and it must not be read as a pass — it is kept on
            # the transcript for exactly that reason.
            return GroundingReport(results=report.results, repairs=repairs)
        return report

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
            f' Call {self._store_tool}(handle="{already.handle}", path="...") '
            f"to read any field of it — the whole result is there, including "
            f"the parts the transcript truncated."
            if self._store_tool else
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
            f'{self._store_tool}(handle="{handle}", path="...") for one field.'
            if handle and self._store_tool else
            " The rest is not retrievable in this mission."
        )
        return bound_result(body, self._max_result_bytes, where=where)
