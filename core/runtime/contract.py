# core/runtime/contract.py — the seam between this harness and whoever runs it

"""What a consumer may rely on, written down as data rather than as habit.

This harness is run by other programs.  TAIPAN spawns ``judais --mission``,
reads the NDJSON off an inherited descriptor, and renders it to an analyst;
it pins a release of this repo and moves at its own pace.  Everything such a
consumer needs to know used to be *convention* — nine names in a docstring,
outcome words scattered through the loop, a ``repairing`` field nobody had
written down, and an exit contract that existed only as the reading habits of
the code on the far end of the pipe.  Convention is fine while one person
holds both halves.  It stops being fine the moment the halves have separate
release cycles, which is now.

So the seam is **this module**, and it is data:

* :data:`EVENTS` — the closed vocabulary of record types;
* :data:`FIELDS` — what each record type always carries, verified against the
  emitters rather than against the prose that describes them;
* :data:`OPTIONAL` — fields a record may carry and a consumer must not require;
* :data:`OUTCOMES` — every word ``mission_finished`` can say;
* :data:`CLI_FLAGS` and :data:`ENV_VARS` — the surface a consumer spawns us by;
* :data:`EXIT_CONTRACT` — what "the mission is over" means, including when it
  is over because something went wrong;
* :func:`conforms` — a pure stdlib check a consumer imports and runs against a
  stream it just read, so "the harness changed" is a failing assertion in
  somebody's test suite rather than a blank pane on a Tuesday.

**The compatibility rule.**  :data:`SCHEMA_VERSION` is carried on every
``mission_started``.

* Adding an event, or adding an optional field to an existing event, is a
  **minor** change and does not bump it.  That is safe because a consumer
  drops record types it does not know — TAIPAN's ``bridge.READS`` is a
  frozenset and anything outside it is discarded silently, with a test that
  fails when this repo declares something new so the shrug is a decision
  somebody made rather than a frame nobody noticed.
* Renaming a field, removing one, moving one out of :data:`FIELDS`, or
  changing what an existing required field means is a **breaking** change and
  **bumps** :data:`SCHEMA_VERSION`.  A consumer that pins
  ``contract.SCHEMA_VERSION == 1`` finds out at import, which is the only
  moment at which finding out is cheap.

Nothing here imports anything this repo owns, and nothing here imports outside
the standard library.  A consumer vendoring this one file gets the whole seam.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Any, Dict, List, Mapping

__all__ = [
    "SCHEMA_VERSION", "EVENTS", "FIELDS", "OPTIONAL", "OUTCOMES",
    "CLI_FLAGS", "ENV_VARS", "EXIT_CONTRACT", "conforms",
    "MISSION_STARTED", "STEP_STARTED", "REPLY_REJECTED", "TOOL_CALL",
    "TOOL_RESULT", "GATE_REQUESTED", "ANSWER", "GROUNDING", "MISSION_FINISHED",
]


#: The version of everything below.  Carried on ``mission_started`` so a
#: consumer reads it off the stream rather than off the package metadata of
#: whatever happened to be installed on the host that spawned us.
SCHEMA_VERSION = 1


# ── the vocabulary ───────────────────────────────────────────────────────────
#
# The names live here rather than in `mission_stream`, which imports them back,
# because a stream is one way to carry these records and this is what they ARE.
# A caller supplying its own observer — a queue, a websocket, a test — speaks
# the same vocabulary without going near NDJSON.

#: The mission has begun.  ``objective``, ``catalogue`` (the tool names the
#: model was offered, in order), ``gated`` (offered but needing a person),
#: ``max_steps``, ``history`` (how many prior conversation turns were seeded
#: ahead of the objective — a count, so a watcher can tell a continued
#: conversation from a cold start without the turns travelling twice), and
#: ``schema_version``.
#:
#: It carries no ``plan``, and a staged mission's is not late in arriving so
#: much as not yet drawn: this record is emitted before the first call to the
#: model, and on ``--swarm`` the router and the planner are both such calls.
#: See :data:`STEP_STARTED` and the ``silence`` clause of
#: :data:`EXIT_CONTRACT`.
MISSION_STARTED = "mission_started"

#: A step of the plan/act loop is about to ask the model.  ``index``, and
#: ``compacted`` on the steps where the conversation had to be shortened to
#: fit the model's context window; see :data:`OPTIONAL`.
#:
#: A staged (``--swarm``) mission adds ``plan`` to the first one each plan
#: produces — the plan as drawn, and again as redrawn, on the first step it
#: is about to be worked through.  See :data:`OPTIONAL`.
STEP_STARTED = "step_started"

#: The model's reply was not a decision this loop could act on — unparseable,
#: not an object, no ``tool`` and no ``answer``, or a tool nobody offers.
#: ``index``, ``problem`` (the sentence handed back to the model), ``tool`` when
#: one was named.  A recorded step, never a crash, and never a guess at intent.
REPLY_REJECTED = "reply_rejected"

#: The model named a tool and the loop is about to dispatch it.  ``index``,
#: ``tool``, ``arguments``.  **Emitted before the call**, which is what lets a
#: watcher show what is about to happen rather than only what happened.
TOOL_CALL = "tool_call"

#: The bus answered.  ``index``, ``tool``, ``arguments``, ``ok``, ``exit_code``,
#: ``output`` (stdout, whole — bounding is what the *model* is shown, not what a
#: watcher is), ``error`` (stderr), ``handle`` (the mission store's handle for
#: the full result), ``truncated``.
TOOL_RESULT = "tool_result"

#: The model named a tool this deployment offers **and gates**: the call was not
#: made, and it will not be made unless somebody says so.  ``index``, ``tool``,
#: ``arguments``, ``reason``.  The mission ends here — see
#: :data:`~core.runtime.mission.AWAITING_APPROVAL`.
#:
#: The arguments travel verbatim, because what a person approves has to be the
#: bytes that would run.
GATE_REQUESTED = "gate_requested"

#: The model finished.  ``text`` and ``outcome``.  One event, after any
#: grounding repair turns, carrying exactly what
#: :attr:`MissionTranscript.answer` will carry — ``outcome`` beside it because
#: an answer that came out of a caveat path is a different thing to render
#: than one that did not, and a consumer should not have to wait for
#: ``mission_finished`` to find out which it is holding.
ANSWER = "answer"

#: What the grounding validator said, when one was configured.  ``ran``,
#: ``grounded``, ``verified``, ``repairs``, ``repairing``, ``caveat``,
#: ``unsupported``, ``silent``, ``uncited``, ``checks`` (``[{check, configured,
#: grounded, verdict, considered, minimum, unsupported, detail}]``).  Absent
#: entirely when no grammar was supplied — an absent report and a clean one are
#: different facts.
#:
#: ``repairing`` is true on the **interim** report emitted when the validator
#: caught something and the loop is spending a repair turn on it.  It exists
#: because a repair turn is a whole extra round-trip to the model and, from
#: outside, looks exactly like a stall; a consumer shows it as work in progress
#: and — this is the part that was convention until now — must **not** latch it
#: as the mission's verdict.  A repaired answer gets a second ``grounding``
#: with ``repairing`` false, and that one is the verdict.
#:
#: So are ``grounded`` and ``verified``.  The first says nothing unsupported
#: was found; the second says something was found to check at all.  A
#: consumer reading only ``grounded`` cannot tell an answer that cited three
#: things correctly from one that cited nothing — which is what six of the
#: first ten measured missions did.
GROUNDING = "grounding"

#: Terminal.  ``outcome`` — the transcript's own word, one of
#: :data:`OUTCOMES` — plus ``steps`` and ``max_steps``.  Both counts, because
#: they are only meaningful against each other: six steps of a stated
#: twenty-four is not an agent that ran out of room, and a consumer holding
#: only ``steps`` has no way to keep a reader from reading it as one.
MISSION_FINISHED = "mission_finished"

#: The closed vocabulary, so a consumer can assert it knows all of them.
EVENTS: tuple[str, ...] = (
    MISSION_STARTED, STEP_STARTED, REPLY_REJECTED, TOOL_CALL, TOOL_RESULT,
    GATE_REQUESTED, ANSWER, GROUNDING, MISSION_FINISHED,
)


# ── what each record always carries ──────────────────────────────────────────

#: Required fields per event: present on **every** emission of that event, from
#: every path that emits it — the direct loop in :mod:`core.runtime.mission`
#: and the staged one in :mod:`core.runtime.swarm` alike.  A consumer may index
#: these without a default.  Read off the emitters, not off the prose: where
#: the two disagreed the prose was corrected, because what a consumer receives
#: is decided by ``_emit`` and not by a docstring.
FIELDS: dict[str, tuple[str, ...]] = {
    MISSION_STARTED: ("schema_version", "objective", "catalogue", "gated",
                      "max_steps", "history"),
    STEP_STARTED: ("index",),
    REPLY_REJECTED: ("index", "problem"),
    TOOL_CALL: ("index", "tool", "arguments"),
    TOOL_RESULT: ("index", "tool", "arguments", "ok", "exit_code", "output",
                  "error", "handle", "truncated"),
    GATE_REQUESTED: ("index", "tool", "arguments", "reason"),
    ANSWER: ("text", "outcome"),
    GROUNDING: ("ran", "grounded", "verified", "repairs", "repairing",
                "caveat", "unsupported", "silent", "uncited", "checks"),
    MISSION_FINISHED: ("outcome", "steps", "max_steps"),
}

#: Fields an event may carry and a consumer must therefore reach for with a
#: default.  Listed rather than left to be discovered, so that "optional" is a
#: statement this repo made and not an accident of which path happened to run.
OPTIONAL: dict[str, tuple[str, ...]] = {
    #: ``sandbox`` — ``"bwrap"`` or ``"none"``, the isolation the tool
    #: subprocesses of this mission ran under.  ``"bwrap"`` is write
    #: isolation with the network denied unless a tool declared it and the
    #: child's environment stripped to a small allow-list; ``"none"`` is no
    #: isolation, reached only by an explicit opt-out or a host without
    #: bubblewrap.  It is the framework's default-safe choice announced on
    #: the opening frame so a consumer knows what a call was run under
    #: without inferring it from the host — and it describes the subprocess
    #: plane only: an in-process MCP tool dispatches inside this process and
    #: touches no sandbox whatever this says.  Optional because a consumer
    #: from before it existed must still read the record; present on both the
    #: direct and the staged path.
    #:
    #: ``profile`` — the capability profile the run is governed by, one of
    #: :class:`~core.contracts.schemas.ProfileMode`'s values (``safe``,
    #: ``dev``, ``ops``, ``god``).  Deny-by-default means ``safe`` unless
    #: ``--profile`` / ``JUDAIS_LOBI_PROFILE`` opted up, and a watcher reading
    #: the opening frame can see which — a ``safe`` mission and a ``god`` one
    #: are otherwise indistinguishable on the wire.  Absent (not ``null``)
    #: when the bus was built from a raw capability engine that never recorded
    #: a profile name, so it is read with a default like every OPTIONAL field.
    MISSION_STARTED: ("sandbox", "profile"),
    #: ``plan`` — ``[{id, goal, rung}]``, the staged mission's plan, on the
    #: first ``step_started`` that plan produces.  Absent on a direct
    #: mission, which has no plan to show, and absent on every later step.
    #:
    #: It rode ``mission_started`` until the silence clause was made true of
    #: the staged path as well: that record is now emitted before triage,
    #: which is itself a model call, and a plan cannot travel on a record
    #: written before anything asked for one.  Moving an OPTIONAL field is a
    #: minor change — a consumer reads it with a default or it was never
    #: reading it as optional.
    #:
    #: ``compacted`` — ``{dropped_turns, dropped_messages, freed_chars,
    #: tokens_before, tokens_after, limit_tokens, profile}``, present only on
    #: the steps where older tool round-trips had to be dropped from the
    #: conversation to keep it inside the model's context window.  Absent on
    #: every other step, and absent for the whole run when the caller
    #: supplied no window.
    #:
    #: It is on the stream because the alternative is the failure it
    #: prevents: an agent whose earlier evidence quietly left its prompt
    #: looks, from outside, exactly like an agent that had it all along.
    #: Nothing is lost to the *run* — ``tool_result`` already carried the
    #: whole of every result, the mission's store still holds them, and the
    #: grounding validator reads the store rather than the conversation.
    #: The counts are per step and not a running total; a consumer wanting
    #: the run's total adds them up.
    STEP_STARTED: ("plan", "compacted"),
    #: ``tool`` — the name the model wrote, when it wrote one.  Absent when
    #: the reply was rejected before a name could be read out of it.
    REPLY_REJECTED: ("tool",),
}


# ── the words the end of a mission can say ───────────────────────────────────

#: Every value ``outcome`` can carry, on ``mission_finished`` and on ``answer``.
#:
#: ``incomplete`` is the transcript's default and therefore the word a mission
#: ends on when it ended by **raising** — ``mission_finished`` is emitted from a
#: ``finally``, so a crash still closes the stream, and it closes it holding the
#: outcome nothing got round to setting.  A consumer treating ``incomplete`` as
#: "stopped, and the reason is on stderr" is reading it correctly.
OUTCOMES: tuple[str, ...] = (
    "answered",
    "answered_with_caveat",
    "awaiting_approval",
    "budget_exhausted",
    "incomplete",
)


# ── how a consumer spawns us ─────────────────────────────────────────────────

#: The mission-mode flags a consumer may rely on.  Every one of these is
#: accepted by the parser :func:`core.cli._main` builds and there is a test
#: that says so; the rest of the CLI is a person's surface and may move.
CLI_FLAGS: tuple[str, ...] = (
    "--mission", "--mcp-url", "--mission-steps", "--provider", "--model",
    "--profile", "--skill", "--swarm", "--events", "--history", "--gate-tool",
    "--temperature", "--top-p", "--seed",
)

#: The environment a consumer may set.  Same standing as :data:`CLI_FLAGS`:
#: read somewhere in ``core/``, and tested to still be.
#:
#: ``MCP_TOKEN`` and ``MCP_CLIENT_NAME`` are the tool plane's credential and
#: the name it is announced under; ``MCP_URL`` and ``MCP_STDIO`` are the
#: environment forms of the two transports; ``ELF_PERSONALITY`` and
#: ``TAI_PERSONALITY`` point at persona files, on **every** entry point and not
#: only ``tai`` — ``TAI_PERSONALITY`` first where both are set;
#: ``LOCAL_API_BASE`` and ``LOCAL_MODEL`` aim the local backend;
#: ``MISSION_SKILL``, ``MISSION_SWARM``, ``MISSION_EVENTS`` and
#: ``MISSION_HISTORY`` are the environment forms of ``--skill``, ``--swarm``,
#: ``--events`` and ``--history``; ``JUDAIS_LOBI_PROFILE`` is the environment
#: form of ``--profile`` — the capability profile the run is governed by, and
#: since the default is now the deny-by-default ``safe`` profile, the variable
#: a consumer sets when a hosted mission needs more than read-only.
#:
#: Where a variable has a flag beside it, it is that flag's argparse
#: default, so the flag still wins: a consumer that exports one and passes
#: the other gets the one it passed.
ENV_VARS: tuple[str, ...] = (
    "MCP_TOKEN", "MCP_CLIENT_NAME", "MCP_URL", "MCP_STDIO",
    "ELF_PERSONALITY", "TAI_PERSONALITY",
    "LOCAL_API_BASE", "LOCAL_MODEL",
    "MISSION_SKILL", "MISSION_SWARM", "MISSION_EVENTS", "MISSION_HISTORY",
    "JUDAIS_LOBI_PROFILE",
)


# ── what "over" means ────────────────────────────────────────────────────────

#: The exit contract, stated here because it used to live only in the reading
#: habits of the program on the other end of the pipe.  Each clause is a fact
#: about this harness that a consumer is entitled to build on.
EXIT_CONTRACT: Mapping[str, str] = MappingProxyType({
    "stdout": (
        "stdout is prose for a person — panels, emoji, the transcript printed "
        "after the fact. It is not a machine channel and a consumer must not "
        "parse it. It changes whenever the console rendering changes, which is "
        "as often as somebody improves it."),
    "events": (
        "The event sink is the only machine channel. `--events -` writes it to "
        "stdout for somebody with jq, `--events fd:N` to an inherited "
        "descriptor, `--events PATH` to a file opened for append. A consumer "
        "spawning us uses fd: or a path, never `-`, so that the console "
        "rendering and the record stream never share bytes."),
    "silence": (
        "A mission that emits ZERO events has failed. `mission_started` is "
        "emitted before the model is asked and before the tool plane is "
        "touched — before the FIRST call, which on `--swarm` is the router's "
        "own and not the first step's — so an empty stream is a harness that "
        "never got that far: a cold model server, a refused token, an "
        "unreachable MCP endpoint. It is never an empty answer, and a "
        "consumer must report it as a failure rather than render a blank "
        "reply."),
    "finished": (
        "`mission_finished` is emitted from a `finally`, so a mission killed "
        "by an exception still closes its own stream. A stream that simply "
        "stops is indistinguishable from an agent that is thinking, and a pane "
        "showing a spinner forever is the state an analyst cannot leave."),
    "sigterm": (
        "On SIGTERM the sink is flushed and closed before the process dies, so "
        "the events already written are on the transcript. The default "
        "disposition is then restored and the signal re-raised, so the exit "
        "status is still the signal's — a consumer that asked a turn to wind "
        "up sees it wound up, not a spurious clean exit."),
    "diagnostic": (
        "stderr carries the diagnostic. Its tail is what a consumer shows when "
        "a mission produced no events, or produced events and then stopped "
        "without an answer. It is a traceback, and it is SCRUBBED BEFORE IT IS "
        "WRITTEN: home directories, this host's name, credentials held in this "
        "process's environment and absolute frame paths are replaced with "
        "stable tokens — `<home>`, `<host>`, `<cwd>`, `<site-packages>`, "
        "`<stdlib>`, `<redacted:NAME>` — by `core.redact`, the same redactor "
        "every free-text field on the event stream (`error`, `problem`, "
        "`reason`, `text`, `caveat`, `detail`, `unsupported`) passes through. "
        "So a consumer may show it to somebody who is not an operator. It is "
        "still a traceback: prose for a person, never a machine channel. "
        "`tool_result.output` and `arguments` are deliberately NOT scrubbed — "
        "they are the evidence and the call, and the mission store holds the "
        "same bytes."),
})


# ── the check a consumer runs ────────────────────────────────────────────────

def conforms(record: Dict[str, Any]) -> List[str]:
    """Everything wrong with one record, as sentences.  Empty means fine.

    Pure, stdlib, and no opinion about *where* the record came from: a
    consumer feeds it lines it just parsed out of an NDJSON file, a test feeds
    it the dicts an observer collected, and both get the same answer.

    What it checks is exactly what :data:`FIELDS` and :data:`EVENTS` promise —
    that the record names an event this version declares, that every required
    field for that event is present, and that any ``schema_version`` it
    carries is one this module understands.  It deliberately does **not**
    check types or complain about extra keys: an added optional field is a
    minor change by the rule at the top of this module, and a checker that
    failed on one would make every additive release a breaking one.
    """
    problems: List[str] = []
    if not isinstance(record, dict):
        return [f"not a record: {type(record).__name__}"]

    version = record.get("schema_version")
    if version is not None and version != SCHEMA_VERSION:
        problems.append(
            f"schema_version is {version!r}; this contract is {SCHEMA_VERSION}")

    event = record.get("event")
    if event is None:
        problems.append("no 'event' field")
        return problems
    if event not in FIELDS:
        problems.append(f"unknown event {event!r}")
        return problems

    for name in FIELDS[event]:
        if name not in record:
            problems.append(f"{event}: missing required field {name!r}")
    return problems
