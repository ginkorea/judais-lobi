#!/usr/bin/env python3
import argparse
import os
from pathlib import Path
from typing import Any, Dict
from rich.console import Console
from rich.markdown import Markdown

from core.contracts.schemas import ProfileMode
# The event name only, off the module that owns the vocabulary and imports
# nothing at all — the console echo below switches on it, and a second
# spelling of a record type is how a consumer comes to render nothing.
from core.runtime.contract import ANSWER_DELTA
from core.runtime.provider_config import PROVIDERS

GREEN = "\033[92m"
RESET = "\033[0m"
console = Console()


def _env_path(name: str):
    """A Path from an env var, or None. Used as an argparse default."""
    value = (os.getenv(name) or "").strip()
    return Path(value) if value else None


def _env_seconds(name: str):
    """A positive float from an env var, or None. An argparse default.

    ``None`` for unset, for a blank string, for something that is not a
    number, and for zero or less — every one of which means "nobody asked
    for a wall clock", and none of which is worth refusing a mission over.
    A typo'd ``MISSION_SECONDS=thirty`` running unbounded is the behaviour
    the variable's absence would have given; the same typo taken as a
    budget of nothing would kill the run before its first step, which is
    the failure that looks like a broken harness.

    The flag still wins where both are set, because this is the flag's
    default — the same arrangement every other ``MISSION_*`` pair has.
    """
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return None
    try:
        seconds = float(raw)
    except ValueError:
        return None
    return seconds if seconds > 0 else None


def strip_markdown(md: str) -> str:
    """Convert Markdown to plain text for optional TTS."""
    from io import StringIO
    from rich.console import Console as StrippedConsole
    from rich.text import Text

    sio = StringIO()
    stripped_console = StrippedConsole(file=sio, force_terminal=False, color_system=None)
    stripped_console.print(Markdown(md))
    return Text.from_markup(sio.getvalue()).plain


def _build_agent(AgentClass, args):
    """Return ``(agent, display_name)``.

    ``--personality`` swaps the ``PersonalityConfig`` and nothing else:
    the same ``Agent`` class, the same memory, the same tools.  JudAIs
    and Lobi are untouched — with no flag and neither personality
    variable set (see :func:`_personality_default`), this is the line
    that was here before.
    """
    from core.policy.profiles import select_profile

    # ``--unsandboxed`` resolves to the one word ``select_sandbox`` reads as
    # the opt-out; no flag leaves it ``None``, so ``JUDAIS_LOBI_SANDBOX`` and
    # then the auto path (bwrap when present) still decide. Flag beats env
    # beats auto, in that order, because a flag passed None never reaches the
    # env lookup.
    sandbox_request = "none" if getattr(args, "unsandboxed", False) else None

    # flag > env > default(SAFE), resolved in one place. An unknown value is
    # a refusal at the door — an operator who typed `--profile dveloper`
    # believes they opted up, and a silent fall-through to SAFE would run the
    # agent under fewer permissions than they asked for while saying nothing.
    try:
        profile = select_profile(getattr(args, "profile", None))
    except ValueError as exc:
        raise SystemExit(f"--profile: {exc}")

    if not getattr(args, "personality", None):
        return (
            AgentClass(model=args.model, provider=args.provider,
                       sandbox_request=sandbox_request, profile=profile),
            AgentClass.__name__,
        )

    from core.agent import Agent
    from core.contracts.schemas import PersonalityConfig

    config = PersonalityConfig.from_file(args.personality)
    agent = Agent(
        config=config,
        model=args.model or config.default_model,
        provider=args.provider or config.default_provider,
        sandbox_request=sandbox_request,
        profile=profile,
    )
    return agent, config.name


def _build_mcp_transport(args):
    """Pick a transport from the flags, or say precisely what is missing."""
    from core.tools.mcp_client import StdioTransport, StreamableHttpTransport

    if args.mcp_stdio and args.mcp_url:
        raise SystemExit(
            "--mcp-stdio and --mcp-url both name a server; pass one. "
            "stdio for a server on this host, url for one you reach over HTTP."
        )
    if args.mcp_stdio:
        import shlex
        parts = shlex.split(args.mcp_stdio)
        if not parts:
            raise SystemExit("--mcp-stdio is empty; it is a command line to run.")
        return StdioTransport(command=parts[0], args=parts[1:])
    if args.mcp_url:
        return StreamableHttpTransport(url=args.mcp_url, token=args.mcp_token)
    raise SystemExit(
        "--mission needs a server: --mcp-stdio '<command>' (or MCP_STDIO) "
        "for one on this host, or --mcp-url <url> (or MCP_URL) for one over "
        "HTTP. There is nothing to discover otherwise."
    )


def _load_skill(args):
    """The ``--skill`` manifest, or ``None``.

    A refusal here is a ``SystemExit`` and not a warning: an operator who
    named a skill and got a mission run without one would get a
    plausible answer produced by an agent holding the whole bus and none
    of the operational knowledge they meant to supply.
    """
    if not getattr(args, "skill", None):
        return None

    from core.runtime.skills import SkillManifestError, load_skill

    try:
        return load_skill(args.skill)
    except SkillManifestError as exc:
        raise SystemExit(f"--skill: {exc}")


def _resolve_gates(wanted, offered):
    """``--gate-tool`` names as the bus dispatches them, or a refusal.

    One question, one answer.  :func:`~core.tools.descriptors.same_tool`
    is this harness's rule for *"are these the same tool"*, already
    shared by :meth:`SkillManifest.resolve`, ``MissionRunner._near_miss``
    and the grounding ignore rule.  A gate was the last surface still
    asking it with ``in``, and exact membership is a rule the consumer
    cannot satisfy: TAIPAN passes the wire spelling off its own tool
    table (``compute_cancel_job``) while the bridge namespaces what it
    discovers (``mcp.compute_cancel_job``).  So every gate matched
    nothing, the ``🔒 gated:`` line never printed, and the call somebody
    was meant to approve was dispatched like any other.

    An unresolvable gate is a **refusal**, at the door, like a manifest
    naming a tool the server does not have.  Dropping it quietly is how
    the bug above stayed quiet for as long as it did: an operator who
    asked for a gate and got a mission without one has been told the
    opposite of what happened, by a run that looks perfectly normal.
    """
    from core.tools.descriptors import same_tool

    offered = list(offered)
    resolved, problems = [], []
    for name in wanted:
        matches = [candidate for candidate in offered
                   if same_tool(candidate, name)]
        if len(matches) == 1:
            if matches[0] not in resolved:
                resolved.append(matches[0])
        elif matches:
            problems.append(
                f"{name!r} matches {len(matches)} offered tools "
                f"({', '.join(sorted(matches))}); name it with its namespace "
                f"so the mission gates the intended one")
        else:
            problems.append(f"{name!r} is not a tool this mission offers")
    if problems:
        raise SystemExit(
            "--gate-tool: " + "; ".join(problems)
            + ".\nOffered: " + (", ".join(offered) or "(none)")
            + "\n\nA gate that names nothing is refused rather than ignored: "
              "a mission that runs without the gate you asked for is the one "
              "outcome you did not ask for.")
    return resolved


def _decide_approval(args):
    """``--approve``/``--refuse``: answer a gate, and exit.  Not a mission.

    A decision is a write from **outside** the run that asked, which is the
    whole reason the request is a file rather than a socket.  So this path
    builds no agent, opens no MCP transport, asks no model and emits no
    events: it resolves the store, calls
    :meth:`~core.runtime.approvals.ApprovalStore.decide`, says what happened
    and returns.  A run that could answer its own gate would not be a gate,
    and the cheapest way to guarantee it cannot is for the answering code to
    share nothing with the running code.

    ``--decided-by`` is required by :meth:`decide` and not by argparse, so the
    refusal a person sees is the one sentence this framework has an opinion
    about — a decision names who made it — rather than a usage block.  Core
    cannot check that the name is a *person*: there is no identity layer here
    and one invented would be a guess at the platform's.  A platform that
    knows who clicked calls the library instead of this command.
    """
    from core.runtime.approvals import (
        APPROVALS_ENV, ApprovalError, default_approval_store,
    )

    approve = bool(getattr(args, "approve", None))
    wanted = getattr(args, "approve", None) or getattr(args, "refuse", None)
    flag = "--approve" if approve else "--refuse"
    store = default_approval_store()
    if store is None:
        raise SystemExit(
            f"{flag}: this deployment keeps no approval records "
            f"({APPROVALS_ENV} is set to a disabling word), so there is "
            f"nothing to decide. A decision has to be readable from outside "
            f"the run that asked for it.")
    try:
        approval = store.decide(
            wanted, approve=approve,
            decided_by=getattr(args, "decided_by", "") or "",
            note=getattr(args, "note", "") or "")
    except ApprovalError as exc:
        raise SystemExit(f"{flag}: {exc}")

    verb = "APPROVED" if approve else "REFUSED"
    console.print(
        f"✅ {approval.approval_id} {verb} by {approval.decided_by} at "
        f"{approval.decided_at} — {approval.tool}({approval.arguments})",
        style="green" if approve else "yellow")
    if approve:
        # The exact next command, because the widening is narrow enough to be
        # easy to get wrong: this id, this once, and only if the run actually
        # calls the tool.
        console.print(
            f"   Resume the work with:  --mission --approval "
            f"{approval.approval_id} '<the objective>'\n"
            f"   It lifts {approval.tool} out of that ONE run's gated set and "
            f"is spent the moment the tool is dispatched.",
            style="cyan")
    else:
        console.print("   Nothing was called, and nothing will be.",
                      style="yellow")
    return 0


def _load_history(args):
    """The ``--history`` turns, or ``[]``.  Refusals are ``SystemExit``.

    A file and not an argv string, for the same reason ``--mcp-token``
    prefers the environment: a conversation can be many kilobytes, and
    argv is world-readable in ``/proc/<pid>/cmdline`` on a shared host.
    The analyst's prior questions do not belong in ``ps`` output.

    Refused loudly rather than dropped, because a dropped history is the
    bug this flag fixes wearing a different hat: the operator believes
    the agent has the conversation, and the agent answers cold.
    """
    path = getattr(args, "history", None)
    if not path:
        return []

    import json

    from core.runtime.mission import validate_history

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SystemExit(f"--history: cannot read {path}: {exc}")
    try:
        turns = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(
            f"--history: {path} is not valid JSON ({exc.msg} at line "
            f"{exc.lineno}). Expected an array of "
            f'{{"role": "user"|"assistant", "content": "..."}} objects.'
        )
    try:
        return validate_history(turns)
    except ValueError as exc:
        raise SystemExit(f"--history: {path}: {exc}")


def _mission_protocol(args) -> str:
    """``"json"`` or ``"native"``, or a refusal naming the two words.

    Empty — the flag's default, and what an unset ``MISSION_PROTOCOL``
    leaves — means ``json``, and it means it *here* rather than in the
    parser on purpose: ``--resume`` has to tell "nobody said" from
    "somebody said json", because a resumed run takes its protocol off its
    own record and a flag defaulting to a word would refuse every native
    resume that did not restate it.

    A word that is neither is a :class:`SystemExit` and not a fallback. A
    typo silently read as the default would run the protocol the operator
    did not ask for and file the result under the one they did.
    """
    from core.runtime.mission import JSON_PROTOCOL, PROTOCOLS

    wanted = (getattr(args, "protocol", "") or "").strip().lower()
    if not wanted:
        return JSON_PROTOCOL
    if wanted not in PROTOCOLS:
        raise SystemExit(
            f"--protocol: {wanted!r} is not a protocol this harness speaks. "
            f"Choose one of: {', '.join(PROTOCOLS)}.")
    return wanted


#: What ``MISSION_STREAM`` has to say to turn the streamed model call off.
#: Spelled as words a person types rather than as a single one, because the
#: variable reads as a switch and half of anybody's guesses at "off" are in
#: this set.  Anything else — including unset, including a typo — leaves
#: streaming ON, which is the safe direction: the worst an unrecognised
#: value costs is the deltas a consumer was going to get anyway.
STREAM_OFF = frozenset({"off", "0", "false", "no", "none"})


def _stream_is_off() -> bool:
    """``MISSION_STREAM``'s answer, read as ``--no-stream``'s default.

    Unset and blank both mean **on**, which is what every mission ran
    under from the release this arrived in.  Read at parser construction
    like every other environment default here, so a caller that exports
    the variable and passes the flag gets the flag.
    """
    return os.getenv("MISSION_STREAM", "").strip().lower() in STREAM_OFF


def _mission_streams(args, client) -> bool:
    """Whether this run's model calls stream.  On unless something says no.

    Two questions, in this order, because only one of them is a
    preference.  **Can** the backend stream — ``supports_streaming``, read
    through ``getattr`` with a ``False`` default like every other
    capability question here, because a library caller may hand ``Agent``
    any client and one that never heard of capabilities has not declared
    it.  And **should** it — ``--no-stream``, whose argparse default is
    already ``MISSION_STREAM``'s answer, so the flag wins over the
    variable the same way every other pair on this surface does.

    Turning it off is not a downgrade and needs no warning: the mission
    runs the identical loop, the ``answer`` record arrives at the identical
    moment, and what a consumer loses is the fragments before it.
    """
    if getattr(args, "no_stream", False):
        return False
    return bool(getattr(getattr(client, "capabilities", None),
                        "supports_streaming", False))


class _ProgressiveAnswer:
    """Print ``answer_delta`` fragments as they arrive, and nothing else.

    The mission's console rendering happens after the run — the steps, the
    grounding line, the answer — which on a minutes-long mission means a
    person watches a blank terminal for the whole of the last turn.  The
    fragments are already on the stream by then; this puts them on stdout
    as well, under the same header the finished answer gets.

    **The text printed is the text emitted**, straight off the record and
    therefore already through :func:`core.redact.scrub_record` — the
    console and the stream must not disagree about what an answer said,
    and a second scrub here would be a second owner of that rule.

    The final rendering is untouched.  What is printed live is a preview
    of a provisional decode; what is printed at the end is
    ``transcript.answer`` as Markdown, including any caveat the grounding
    path appended, and that is the line a person reads.
    """

    def __init__(self, console, style: str, name: str):
        self._console = console
        self._style = style
        self._name = name
        self._open = False

    def __call__(self, record: Dict[str, Any]) -> None:
        if record.get("event") == ANSWER_DELTA:
            if not self._open:
                self._console.print(f"🧞 {self._name}: ", style=self._style,
                                    end="")
                self._open = True
            self._console.print(str(record.get("text") or ""),
                                style=self._style, end="")
            return
        if self._open:
            # Any other record closes the line. The `answer` that follows
            # the fragments is the usual one, but a rejected reply or a
            # tool call does the same job: the next thing printed must not
            # continue somebody's half-streamed sentence.
            self._console.print("")
            self._open = False


def _watchers(*observers):
    """Fan one record out to each observer, or ``None`` when there are none.

    The sink goes FIRST wherever both are passed.  ``MissionRunner._emit``
    wraps the whole call in one ``try`` — an observer that throws must not
    end a mission — so an ordering that put the console before the machine
    channel would let a rich markup error cost a consumer the record.
    """
    kept = [observer for observer in observers if observer is not None]
    if not kept:
        return None
    if len(kept) == 1:
        return kept[0]

    def fan(record):
        for observer in kept:
            observer(record)

    return fan


def _mission_tools(manifest, discovered, style, bus=None):
    """The mission's tool subset: the skill's closed set, or everything.

    With no manifest this is the whole bridge, which is what the mission
    path did before skills existed.  It is a fallback and not a default
    posture — ``MissionRunner``'s own contract asks for a subset, and a
    governed deployment supplies one in a manifest.

    ``bus`` is passed so the resolve can see what the mission would
    actually be isolated by: a manifest whose closed set names a
    code-plane tool has to declare ``sandbox: bwrap``, and a manifest
    that declares it has to *get* it.  Read through
    :func:`~core.runtime.skills.sandbox_name`, which is the smallest
    seam available today (``ToolBus.sandbox``) and the line to rewire
    when sandbox selection becomes explicit.
    """
    if manifest is None:
        console.print(
            "⚠️  No --skill: the mission is offered every discovered tool. "
            "A skill manifest supplies the closed set and the operational "
            "knowledge that goes with it.",
            style="yellow",
        )
        return list(discovered)

    from core.runtime.skills import SkillToolsUnavailable, sandbox_name

    try:
        return manifest.resolve(discovered, sandbox=sandbox_name(bus))
    except SkillToolsUnavailable as exc:
        raise SystemExit(f"--skill: {exc}")


#: The argv-derived facts a run's metadata carries, and the deliberate
#: absence of two.  ``--mcp-url`` and ``--mcp-stdio`` are NOT here: a URL can
#: carry a token in its query string and a stdio command line can carry one as
#: an argument, and a run directory outlives the process that was handed it.
#: The transport a mission used is recoverable from the audit log of what it
#: called; a credential written into `meta.json` is a credential on somebody's
#: disk next month.
RUN_META_FLAGS = (
    "mission_steps", "provider", "model", "profile", "unsandboxed", "skill",
    "swarm", "events", "control", "history", "gate_tool", "temperature",
    "top_p", "seed",
)

#: The step budget a mission runs under when nobody says otherwise.
#:
#: A constant rather than an argparse ``default=`` because ``--mission-steps``
#: now has to be distinguishable from its own default: on ``--resume`` the
#: number means *this many further steps* and its absence means *the total the
#: run was started with* (see :meth:`core.runtime.resume.Recorded
#: .total_steps`), and a flag that defaults to ``8`` cannot tell "nobody said"
#: from "somebody said eight".
DEFAULT_MISSION_STEPS = 8


def _run_meta_flags(args) -> dict:
    """How this mission was spawned, as the run's own index over itself.

    Only flags that were actually given: a metadata file listing every
    default is a file in which the two settings somebody chose are invisible.
    Read through ``getattr`` so a caller building an ``args`` of its own —
    the tests do — is not obliged to carry the whole parser's surface.
    """
    given = {}
    for flag in RUN_META_FLAGS:
        value = getattr(args, flag, None)
        if value in (None, "", False, []):
            continue
        given[flag] = value
    return given


def _run_mission(elf, args, name, style):
    """:func:`_mission`, with its last traceback scrubbed on the way out.

    A mission is spawned by another program.  When it dies of something
    nobody handled, the only thing that program has to show a person is
    stderr — ``EXIT_CONTRACT["diagnostic"]`` says so — and the interpreter's
    own default writes that traceback with every absolute path on this host
    in it.  That is the leak that had TAIPAN's location sweep deferred rather
    than written.

    So the outermost frame of mission mode catches, renders the traceback
    through the same redactor the stream uses
    (:func:`core.redact.scrub`), writes it to stderr itself, and exits
    non-zero.  ``SystemExit`` and ``KeyboardInterrupt`` are **not** caught:
    the first is a refusal that already said what was wrong, and the second
    is a person, not a defect.
    """
    import sys
    import traceback

    from core.redact import scrub

    try:
        return _mission(elf, args, name, style)
    except Exception:
        sys.stderr.write(scrub(traceback.format_exc()))
        sys.stderr.flush()
        raise SystemExit(1)


def _mission(elf, args, name, style):
    """Discover tools over MCP, bridge them, and let the model choose.

    Everything the agent can reach in a mission arrives through
    ``tools/list`` and is dispatched through the agent's own ToolBus.
    No store, path or compute plane is touched from here.

    What the model is *told* comes from two files and no code: the
    persona (``--personality``) and the skill manifest (``--skill``).
    This function joins them in that order — who you are, then what you
    are doing — and supplies neither.
    """
    from core.durable import RUNS_ENV, open_run_store
    from core.budgets import Budgets, Cancellation, Deadline
    from core.redact import scrub
    from core.runtime.approvals import (
        APPROVALS_ENV, ApprovalError, default_approval_store, resolve,
    )
    from core.runtime.context_window import MissionWindow
    from core.runtime.control import ControlChannel
    from core.runtime.grounding import GroundingConfig, GroundingValidator
    from core.runtime.mission import (
        ANSWER_FUNCTION, AWAITING_APPROVAL, CANCELLED, JSON_PROTOCOL,
        NATIVE_PROTOCOL, MissionRunner,
    )
    from core.runtime.mission_stream import (
        close_on_sigterm, exit_as_signalled, open_sink,
    )
    from core.runtime.resume import (
        ORPHAN_STALE_S, ResumeRefused, open_for_resume, rebuild,
        reconcile_orphans,
    )
    from core.runtime.results import RESULT_TOOL
    from core.runtime.usage import PricingTable
    from core.tools.mcp_client import McpClient, McpUnavailable, McpConnectionError

    manifest = _load_skill(args)
    # The word, validated at the door; whether this run may speak it is
    # settled below, once `--resume` has had its say about which protocol
    # the run actually is.
    protocol = _mission_protocol(args)
    # Read and validated BEFORE the connection, like the grounding grammar
    # below: a malformed history is a refusal at the door, not a mission
    # that runs to completion answering questions nobody quite asked.
    history = _load_history(args)
    # And so is the approval. `resolve` refuses anything that is not an
    # approved, unspent record and NAMES the state it found — pending is not
    # a yes nobody got round to, spent is not a second yes. At the door for
    # the same reason as the history: an operator who pasted the wrong id
    # finds out in a second rather than after the model has been asked.
    approvals = default_approval_store()
    try:
        ticket = resolve(approvals, getattr(args, "approval", "") or "")
    except ApprovalError as exc:
        raise SystemExit(f"--approval: {exc}")
    transport = _build_mcp_transport(args)
    bus = elf.tools.bus

    # Said out loud, both ways round. A path tells an operator where to look
    # when somebody asks what this mission called; the absence of one is the
    # more important announcement, because an unaudited run is a decision
    # (JUDAIS_LOBI_AUDIT=off) and it should never be discovered afterwards by
    # finding an empty directory. The same fact rides the machine channel as
    # `mission_started.audit_ref`.
    from core.policy.audit import AUDIT_ENV

    if bus.audit_ref:
        console.print(f"🧾 audit: {bus.audit_ref}", style=style)
    else:
        console.print(
            f"🧾 audit: DISABLED — nothing this mission calls will be "
            f"recorded. Unset {AUDIT_ENV} (or point it at a path) to restore "
            f"the default",
            style="yellow",
        )

    # The durable transcript, opened BEFORE the connection for the same
    # reason the event sink is: a run that never reached a server is exactly
    # the run somebody comes looking for afterwards, and it has to have left
    # a directory. The store hands out the id — this function never mints one
    # — so there is one owner of "which run is this" and a consumer reading
    # `mission_started.run_id` can find the directory without guessing.
    #
    # Said out loud both ways round, like the audit line above it: a path
    # tells an operator where to look, and the absence of one is the more
    # important announcement, because keeping no transcript is a decision
    # (JUDAIS_LOBI_RUNS=off) and not a thing to discover later from an empty
    # directory.
    run_store = open_run_store()
    run_id = ""
    # What this mission is about and how many steps it may spend, resolved
    # here because `--resume` can change both: the objective comes off the
    # recorded run, and the budget is a TOTAL for that run rather than a
    # fresh allowance for this process.
    objective = args.message
    max_steps = (DEFAULT_MISSION_STEPS if args.mission_steps is None
                 else max(1, int(args.mission_steps)))
    resume_id = (getattr(args, "resume", "") or "").strip()
    recorded = None

    if resume_id:
        # Every refusal a resume can meet is answered here — before the
        # server is dialled and before the model is asked — for the reason
        # `--skill` and `--history` are read at the door. The worst of them
        # is the objective mismatch: a resume of the wrong run looks
        # exactly like a run continuing.
        try:
            recorded = open_for_resume(
                run_store, resume_id, objective=args.message,
                # What was TYPED, not what `_mission_protocol` resolved: an
                # unstated protocol takes the run's own, and the door
                # refuses only a stated one that disagrees with the record.
                protocol=(getattr(args, "protocol", "") or "").strip().lower())
        except ResumeRefused as exc:
            raise SystemExit(f"--resume: {exc}")
        run_id = recorded.run_id
        objective = recorded.objective
        max_steps = recorded.total_steps(args.mission_steps)
        # The run's, not this command line's. The replay rebuilds the
        # model's own turns in the shape they were made in, and the loop
        # about to send them has to be reading that shape back.
        protocol = recorded.protocol
        console.print(
            f"⏩ resume: {run_id} — {recorded.spent_steps} step(s) already "
            f"recorded, {max_steps} total for this run"
            + (f", stopped at a gate on {recorded.outcome}"
               if recorded.outcome else ""),
            style=style,
        )
    elif run_store is not None:
        # `objective` and the flags, and NOT the transport: an --mcp-url can
        # carry a token in its query string and an --mcp-stdio command line
        # can carry one as an argument, and this directory outlives the
        # process. `created_at` on the record is when the run started, so
        # nothing here restates it.
        run_id = run_store.create(meta={
            "objective": args.message,
            "flags": _run_meta_flags(args),
        }).run_id
        console.print(
            f"🧾 run: {run_id} — {run_store.directory(run_id)}", style=style)
    else:
        console.print(
            f"🧾 run: NOT RECORDED — this mission leaves no durable "
            f"transcript and cannot be replayed or resumed. Unset "
            f"{RUNS_ENV} (or point it at a path) to restore the default",
            style="yellow",
        )

    # WHETHER THIS BACKEND CAN SPEAK IT, before anything is dialled and
    # before the model is asked. The native protocol is nothing but two
    # capabilities — the tools declared as functions, and a decoder
    # constrained to them — so a backend that does not have them cannot
    # run it, and a mission that asked for the constrained decoder and
    # silently got prose would be MEASURED as the protocol it was not
    # running. That is the one outcome an experiment must not produce, so
    # this is a refusal naming both the capability and the way out, and
    # never a downgrade. Read through `getattr` with False defaults, like
    # every other capability question here: a library caller may hand
    # `Agent` any client, and one that never heard of capabilities has not
    # declared these.
    native = protocol == NATIVE_PROTOCOL
    if native:
        capabilities = getattr(elf.client, "capabilities", None)
        missing = [capability for capability in ("supports_tool_calls",
                                                 "supports_tool_choice_required")
                   if not getattr(capabilities, capability, False)]
        if missing:
            raise SystemExit(
                f"--protocol {NATIVE_PROTOCOL}: this backend "
                f"({getattr(elf.client, 'provider', '?')} / {elf.model}) "
                f"does not declare {' and '.join(missing)}. Run with "
                f"--protocol {JSON_PROTOCOL} — the default, and what every "
                f"mission ran under until now — or point --provider at a "
                f"backend that declares them.")
        console.print(
            f"🔤 protocol: {NATIVE_PROTOCOL} — the tools are declared as "
            f"functions and every reply is a call to one of them; finishing "
            f"is a call to mission_answer. A reply that does not parse and a "
            f"tool name nobody offers are unrepresentable rather than "
            f"caught, and arguments are checked against each tool's own "
            f"schema before it is dispatched",
            style=style,
        )

    # Every mission closes the logs of the runs nobody else will. A run
    # directory with no `mission_finished` leaves a follower waiting on a
    # stream that stopped mid-sentence, and the only evidence available for
    # "died" versus "still going" is how long ago the metadata was written
    # — so the rule is stated (ORPHAN_STALE_S) rather than assumed, and the
    # run this process is about to work on is excluded outright.
    reconciled = reconcile_orphans(run_store, live=run_id)
    if reconciled:
        console.print(
            f"🧾 reconciled: {len(reconciled)} orphaned run(s) — no "
            f"`mission_finished` and untouched for over "
            f"{int(ORPHAN_STALE_S)}s, so each log is closed as `incomplete`: "
            f"{', '.join(reconciled)}",
            style="yellow",
        )

    # Parsed BEFORE the connection, so an unusable regex or an unknown key is
    # a refusal at the door rather than at the end of an 11,000-second
    # mission. The validator itself is built twice: once here so `--skill`
    # can refuse, and again below once the offered set is known, because
    # `offering()` needs the tools the bus actually resolved.
    try:
        grounding = (GroundingConfig.from_mapping(manifest.grounding)
                     if manifest else None)
        validator = GroundingValidator.from_config(grounding)
    except ValueError as exc:
        raise SystemExit(f"--skill: {exc}")

    system_message = "\n\n".join(
        part for part in (elf.system_message, manifest.prompt if manifest else "")
        if part and part.strip()
    )

    def _function_schemas(names):
        """The offered tools as OpenAI function schemas, or ``[]``.

        **Declaring these is what stops a harmony model from 500ing the
        server.** gpt-oss emits its tool intent as a native header —
        ``to=functions.catalog_search_assets`` — whatever the prompt asks for.
        With no ``tools`` in the request there is no function namespace to
        resolve that against, and vLLM fails parsing its OWN model's output:

            500  unexpected tokens remaining in message header: Some("to=")

        Proven on 10 Aug against a live lease: identical body, 500 with no
        tools, ``finish_reason='tool_calls'`` with them. It is also why Goose
        never hit this and Tai hit it every single time — Goose declares tools
        and Tai did not.

        Declared from the bus rather than restated here, for the reason
        ``MissionRunner.catalogue`` gives: a second copy of a tool's contract
        disagrees with the first the day a server changes a description.

        PROBED 10 Aug 2026 against the live lease (vLLM **0.14.1** serving
        ``openai/gpt-oss-20b``; ``{"version":"0.14.1"}`` off ``/version``).
        Both grammar constraints the OpenAI schema defines are **supported**:

        * ``response_format={"type": "json_object"}`` returned
          ``{"answer": 42}`` — valid JSON, clean finish;
        * ``tool_choice="required"`` returned a well-formed native call,
          ``catalog_search_assets({"text": "assets we hold"})``, with
          ``content`` null and ``tool_calls`` populated.

        **This closes a whole failure class at zero token cost.** On the 10
        August suite Tai spent two turns on a malformed tool name and two more
        on invalid JSON before recovering, out of a budget of eight — a
        quarter of the mission burned on protocol rather than on the question.
        Neither mistake is representable under those flags: the decoder cannot
        emit a name outside the namespace, nor JSON that does not parse.

        Deliberately NOT wired here yet. It was probed the same day the
        grounding control was turned on, and enabling both at once would make
        the measured delta unattributable to either. It is the next commit,
        and the probe is recorded here so nobody has to lease a card to
        rediscover it.
        """
        schemas = []
        for name in names:
            info = bus.describe_tool(name)
            if "error" in info:
                continue
            parameters = info.get("input_schema") or {
                "type": "object", "properties": {}}
            schemas.append({"type": "function", "function": {
                "name": name,
                "description": info.get("description") or "",
                "parameters": parameters}})
        return schemas

    declared: list = []

    # SAMPLING, AND THE DECISION NOT TO CHOOSE ONE FOR YOU.
    #
    # Until 11 August 2026 no temperature, top_p or seed was set anywhere on
    # this path. The request carried `model`, `messages`, `tools` and
    # `tool_choice` and nothing else, so every mission ran at whatever the
    # server defaults to — ~1.0 for gpt-oss — and no configuration had ever
    # been run twice. Every measured difference between two arms sat on top of
    # unmeasured sampling variance of unknown size.
    #
    # These flags do NOT change that default, and that is deliberate. Pinning
    # `temperature=0` would make the agent easier to measure by making it a
    # different agent: it collapses the noise instead of measuring it, and the
    # thing shipped would no longer be the thing scored. The noise floor has
    # to be taken at the sampling the product actually runs at, or it is not a
    # floor. What was missing was not a temperature but the ABILITY to state
    # one and to see what went out — "server default" is a setting nobody
    # chose and a vLLM upgrade can move it with nothing in any log.
    #
    # So: unset by default, explicit when passed, and on the wire either way
    # where the recorder's `llm.request` layer captures it. Pinning one is a
    # pre-registered arm with its own prediction, not a Round 0 edit — the
    # same attribution discipline the decode probe above is held to.
    sampling = {name: value for name, value in (
        ("temperature", getattr(args, "temperature", None)),
        ("top_p", getattr(args, "top_p", None)),
        ("seed", getattr(args, "seed", None)),
    ) if value is not None}
    if sampling:
        console.print(
            "🎲 sampling: "
            + ", ".join(f"{k}={v}" for k, v in sorted(sampling.items()))
            + " — pinned for this run; unset means the server's own default",
            style=style)

    # ON, unless the backend cannot or the operator said not to. A streamed
    # call returns an iterator of frames instead of a string, and
    # `MissionRunner` takes either — see `_model_reply`, which drains the
    # frames into `answer_delta` records and hands the loop the same reply
    # string it has always had. `plain_chat_fn` below deliberately does NOT
    # stream: its callers are the swarm's router, planner, gates and
    # synthesizer, which read one small JSON object or one paragraph and
    # have nowhere to put a fragment.
    streaming = _mission_streams(args, elf.client)
    if streaming:
        console.print(
            "📝 streaming: the answer goes out in fragments as the model "
            "writes it (answer_delta), and the answer record that follows "
            "is still the whole of it — --no-stream / MISSION_STREAM=off "
            "turns this off and changes nothing else",
            style=style)

    def chat_fn(messages):
        # The mission loop still reads one JSON object out of the reply; the
        # backend renders any native tool_call back into that shape. So this
        # changes what the SERVER is told, not what the kernel understands.
        extra = dict(sampling)
        if native:
            # THE OTHER PROTOCOL, and it is entirely a property of this
            # request. `tool_choice="required"` is what makes a reply that
            # does not parse and a tool name nobody offers unrepresentable
            # rather than caught; `mission_answer` is declared beside the
            # real tools because under `required` the model has no other
            # way to say it is finished. The store's read tool is picked up
            # from the bus the same way everything else is — it registers
            # itself for the length of the run, so `_function_schemas`
            # returns it while the loop is running and nothing here has to
            # know when.
            extra.update({
                "tools": [*declared,
                          *_function_schemas([RESULT_TOOL]),
                          ANSWER_FUNCTION],
                "tool_choice": "required",
                "parallel_tool_calls": True,
            })
        elif declared and getattr(elf.client, "supports_tool_calls", True):
            extra.update({"tools": declared, "tool_choice": "auto"})
        return elf.client.chat(model=elf.model, messages=messages,
                               stream=streaming, **extra)

    def plain_chat_fn(messages, **extra):
        # No tool schemas, deliberately: the swarm's router, planner, gate
        # and synthesizer must answer their question in bare JSON or prose,
        # and a harmony model with a function namespace declared will answer
        # a yes/no question with a tool call.
        #
        # `**extra` is the ONE thing a caller may add, and today that is
        # `response_format` from `SwarmRunner._json_reply`. Sampling is
        # applied after it so a role cannot quietly re-pin a temperature
        # this run's operator chose.
        return elf.client.chat(model=elf.model, messages=messages,
                               stream=False, **extra, **dict(sampling))

    def usage_fn():
        # The side channel beside `chat`. Read straight after each of the
        # two functions above returns, by whichever runner made the call —
        # `chat` returns a string and cannot also return a number without
        # breaking every caller of it. `getattr` with a default because a
        # library caller may hand `Agent` a client that never heard of
        # usage, and a mission must not need one to run.
        return getattr(elf.client, "last_usage", None)

    def tool_calls_fn():
        # The second side channel beside `chat`, read the same way and for
        # the same reason: under the native protocol the decision is not in
        # the string `chat` returns, it is in the provider's `tool_calls`,
        # and `chat` cannot also return a list without breaking every
        # caller of it. Copied out rather than handed over — the backend
        # clears its own on the next call, and the loop is entitled to a
        # list that does not change underneath it.
        return list(getattr(elf.client, "last_tool_calls", []) or [])

    # Read once, here, where a deployment's provider and model are already
    # in hand. There is no price list in this repository and there must not
    # be one — prices move and differ per account — so this is `None` for
    # every deployment that did not write a `pricing:` block, and the
    # ledger then carries tokens and no cost.
    #
    # The provider is read off the CLIENT and not off the agent: the client
    # is the object that made the calls and reported the counts, and it is
    # what the banner above already names. Two readings of "which provider
    # ran" is how a bill gets computed against the wrong price list.
    rate = PricingTable.from_project().rate_for(
        str(getattr(elf.client, "provider", "") or ""), elf.model)

    # Opened BEFORE the connection, so that a harness watching this mission is
    # told about a server it could not reach. A stream that never produces a
    # byte and a mission that failed to start look identical from the far end
    # of a pipe, and only one of them is worth waiting on.
    try:
        sink = open_sink(getattr(args, "events", "") or "")
    except (ValueError, OSError) as exc:
        raise SystemExit(f"--events: {exc}")
    # One switch and one clock for this whole turn, built before the sink's
    # handler is installed because the handler throws the switch.
    #
    # A consumer stopping a turn sends SIGTERM and expects what was already
    # written to survive. Nothing made that true until there was a handler,
    # and the handler alone was not enough: closing the stream ON the signal
    # saved every record except the one that says the run is over. So the
    # first SIGTERM cancels, the loop winds up and writes its own
    # `mission_finished`, the `finally` below closes the sink, and
    # `exit_as_signalled` then makes the exit status the signal's.
    cancel = Cancellation()
    budgets = Budgets(max_steps=max_steps,
                      max_seconds=getattr(args, "mission_seconds", None))
    deadline = Deadline.of(budgets)
    close_on_sigterm(sink, cancel)

    # The other direction, opened here for the reason the sink is opened
    # before the connection: a platform that handed us a descriptor is
    # entitled to be refused at the door if we cannot read it, rather than
    # to discover minutes later that nothing it sent arrived. It is handed
    # the SAME cancellation the SIGTERM handler holds — `cancel` on the
    # channel and the first signal are one lever reached by two roads —
    # and its cause is `control`, not `sigterm`, so a run stopped this way
    # exits normally instead of dying of a signal nobody sent.
    try:
        control = ControlChannel.open(getattr(args, "control", "") or "",
                                      cancel=cancel)
    except (ValueError, OSError) as exc:
        if sink is not None:
            sink.close()
        raise SystemExit(f"--control: {exc}")
    if control is not None:
        console.print(
            f"🎛  control: {control.spec} — NDJSON commands in: inject, "
            f"cancel, cancel_step, gate_decision. A gate will WAIT here for "
            f"a decision instead of ending the mission",
            style=style,
        )

    try:
        with McpClient(transport) as client:
            from core.tools.mcp_client import McpToolBridge
            bridge = McpToolBridge(client, bus)
            discovered = bridge.sync()
            bridge.follow_changes()
            console.print(
                f"🔌 {name} connected to {transport.describe()} — "
                f"{len(discovered)} tool(s) discovered: "
                f"{', '.join(discovered) or '(none)'}",
                style=style,
            )
            tool_names = _mission_tools(manifest, discovered, style, bus)
            # The catalogue is not knowable until the server has answered,
            # so it joins the metadata here rather than at `create`. Through
            # `update_meta` and not by saving a held record: the runner is
            # about to start appending, and writing a whole record back over
            # one it read earlier is precisely the stale-`last_seq` bug
            # `core.durable` was written around.
            if run_store is not None:
                run_store.update_meta(run_id, catalogue=list(tool_names))
            declared[:] = _function_schemas(tool_names)
            # The identifier check must not flag the name of a tool this
            # mission offered — the harness wrote that name into the prompt
            # itself. Derived from the resolved set rather than typed into a
            # manifest's `ignore` list, which is how a mission came to spend
            # a repair turn deleting a true sentence about
            # `mcp.catalog_search_assets` while the list carried
            # `catalog.search_assets`. See `GroundingConfig.offering`.
            # `RESULT_TOOL` because `MissionRunner.offered` adds it: the
            # store is on the table too, and the model names it in prose.
            if grounding is not None:
                validator = GroundingValidator.from_config(
                    grounding.offering([*tool_names, RESULT_TOOL]))
            if manifest:
                console.print(
                    f"📜 skill {manifest.name} — {len(tool_names)} tool(s): "
                    f"{', '.join(tool_names)}"
                    + ("" if validator else "  (no grounding grammar)"),
                    style=style,
                )
            gated = _resolve_gates(getattr(args, "gate_tool", None) or [],
                                   tool_names)
            if ticket is not None:
                # The subtraction has ONE owner — the ticket — and it is
                # applied here as well as inside the runner so that the line
                # an operator reads and the set the loop enforces cannot
                # disagree about what this run gates.
                widened, gated = gated, ticket.widen(gated)
                if len(widened) == len(gated):
                    console.print(
                        f"⚠️  approval {ticket.approval_id} is for "
                        f"{ticket.tool}, which this run does not gate — "
                        f"nothing was widened, and the decision stays unspent",
                        style="yellow")
                else:
                    console.print(
                        f"🔓 approval {ticket.approval_id}: {ticket.tool} was "
                        f"approved by {ticket.decided_by} at "
                        f"{ticket.decided_at} — out of the gated set for THIS "
                        f"run only, and spent the moment it is dispatched",
                        style=style)
            if gated:
                console.print(
                    f"🔒 gated: {', '.join(gated)} — offered and not called; "
                    f"proposing one ends the mission for a person to decide",
                    style=style,
                )
                # Said where it matters and nowhere else: on a mission with no
                # gates there is nothing to record, and a line about approvals
                # on every run would be noise an operator learns to skip.
                if approvals is not None:
                    console.print(
                        f"🗒️  approvals: {approvals.root} — a proposal is "
                        f"written there and answered with --approve <id> "
                        f"--decided-by <who>",
                        style=style)
                else:
                    console.print(
                        f"🗒️  approvals: DISABLED — a gate will stop this "
                        f"mission and leave NO record for anybody to decide "
                        f"against. Unset {APPROVALS_ENV} (or point it at a "
                        f"path) to restore the default",
                        style="yellow")
            if history:
                console.print(
                    f"🧵 history: {len(history)} prior turn(s) seeded as "
                    f"chat messages ahead of the objective",
                    style=style,
                )
            # Built here and injected, rather than reached for inside the
            # loop: a library caller constructing a MissionRunner gets the
            # same bound by passing one, and this function stays the place
            # where a deployment's model, provider and endpoint meet.
            #
            # The client goes in unread: `capabilities` on the local
            # backend is a `GET /models` and the window defers it, so a
            # library caller pays for the probe only if it compacts.
            # Here it is paid immediately and on purpose — the line below
            # is the one place an operator finds out, BEFORE an
            # 11,000-second mission rather than after it, whether the
            # harness knows the endpoint's real window or is running on a
            # declared default. The probe is cached and the same server is
            # about to be asked a question anyway.
            window = MissionWindow(
                provider=getattr(elf, "provider", "") or "",
                model=elf.model,
                client=elf.client,
            )
            console.print(
                f"🪟 context: {window.limit_tokens} input tokens of "
                f"{window.profile.max_context_tokens} "
                f"({window.profile.source}) — older tool round-trips are "
                f"compacted out before the model is asked, and the whole of "
                f"every result stays in the mission store",
                style=style,
            )
            # Both bounds on one line, from the object the run is actually
            # held to, so the console cannot say "8 steps" while the loop
            # runs to 24. "no wall clock" is printed as such rather than
            # omitted: an operator who meant to pass --mission-seconds and
            # mistyped the variable should see that nothing is bounding the
            # waiting, at the top of a run that may last hours.
            console.print(
                f"⏱  budget: {budgets.describe()} — steps bound the work, "
                f"seconds bound the waiting; a mission that runs out says "
                f"which on its last record",
                style=style,
            )
            # The same word `mission_started` carries on the stream, printed
            # here for the person watching the console. `bwrap` means tool
            # subprocesses run write-isolated with the network denied unless a
            # tool asked and a stripped environment; `none` means no
            # isolation. Either way the in-process MCP tool plane is not
            # sandboxed — it dispatches inside this process and never reaches
            # a child.
            if bus.sandbox_name == "bwrap":
                console.print(
                    "🧱 sandbox: bwrap — tool subprocesses are write-isolated, "
                    "the network is denied unless a tool declares it, and the "
                    "environment is stripped to a small allow-list (MCP tools "
                    "dispatch in-process and are not sandboxed)",
                    style=style,
                )
            else:
                console.print(
                    "🔓 sandbox: none — tool subprocesses run WITHOUT isolation "
                    "(install bubblewrap, or unset JUDAIS_LOBI_SANDBOX/drop "
                    "--unsandboxed, to sandbox them)",
                    style="yellow",
                )
            # The sink is the machine channel and the echo is a person's;
            # both are observers, and neither is the other's client. Built
            # here, once, so the two runners below cannot be given
            # different watchers. With no `--events` and no streaming this
            # is `None` and the loop emits nothing, exactly as before.
            watcher = _watchers(
                sink,
                _ProgressiveAnswer(console, style, name) if streaming
                else None)
            if getattr(args, "swarm", False) and recorded is not None:
                # A resume continues the loop that was recorded, and what
                # was recorded is a MissionRunner's: the swarm's own
                # records are its sub-missions' renumbered into one stream.
                # Re-triaging and re-planning would be a different mission
                # under the same id, so `--swarm` is set aside for this
                # turn and said out loud rather than silently honoured.
                # (A run that was actually STAGED never reaches here — it
                # carries a checkpointed plan and is refused at the door.)
                console.print(
                    "🐝 swarm: set aside for this turn — --resume continues "
                    "the recorded loop, and re-triaging would be a different "
                    "mission under the same run id",
                    style="yellow",
                )
            if getattr(args, "swarm", False) and recorded is None:
                from core.runtime.swarm import SwarmRunner
                console.print(
                    "🐝 swarm: triage first; small questions run direct, "
                    "complex ones are planned, executed in small steps, "
                    "gated and synthesized — same model throughout",
                    style=style,
                )
                runner = SwarmRunner(
                    chat_fn, bus, tool_names,
                    system_message=system_message,
                    max_steps=max_steps,
                    validator=validator,
                    gated=gated,
                    approvals=approvals,
                    approval=ticket,
                    history=history,
                    observer=watcher,
                    plain_chat_fn=plain_chat_fn,
                    # Asked of the CLIENT, because the client is what knows
                    # which backend it is and the swarm holds only a
                    # function. `getattr` twice: a library caller's client
                    # need never have heard of capabilities, and a backend
                    # that cannot constrain its decoder is the default.
                    json_mode=bool(getattr(
                        getattr(elf.client, "capabilities", None),
                        "supports_json_mode", False)),
                    # The manifest is the only thing here that knows what
                    # the platform is called to `import`. Without it the
                    # planner is not offered the code+sdk rung at all.
                    sdk_import=manifest.sdk_import if manifest else "",
                    window=window,
                    run_store=run_store,
                    run_id=run_id,
                    usage_fn=usage_fn,
                    tool_calls_fn=tool_calls_fn,
                    protocol=protocol,
                    rate=rate,
                    deadline=deadline,
                    cancel=cancel,
                    control=control,
                )
            else:
                runner = MissionRunner(
                    chat_fn, bus, tool_names,
                    system_message=system_message,
                    max_steps=max_steps,
                    validator=validator,
                    gated=gated,
                    approvals=approvals,
                    approval=ticket,
                    history=history,
                    observer=watcher,
                    window=window,
                    run_store=run_store,
                    run_id=run_id,
                    usage_fn=usage_fn,
                    tool_calls_fn=tool_calls_fn,
                    protocol=protocol,
                    rate=rate,
                    deadline=deadline,
                    cancel=cancel,
                    control=control,
                )
            # AFTER the runner exists, because the replay renders a
            # recorded tool result through the runner's own
            # `_render_result` rather than a second copy of it — one owner
            # of what a result reads like in the conversation, so the
            # resumed model does not read a differently-worded transcript
            # of its own previous turns.
            resumption = None
            if recorded is not None:
                resumption = rebuild(runner, recorded)
                console.print(
                    f"⏩ replayed: {resumption.steps_replayed} step(s), "
                    f"{len(resumption.store.results)} stored result(s), "
                    f"continuing at index {resumption.next_index}",
                    style=style,
                )
                for sentence in resumption.lost:
                    console.print(f"   ⚠️  not replayed: {sentence}",
                                  style="yellow")
            # Passed only when there is one: `SwarmRunner.run` takes no
            # resumption and must not grow a parameter it can never be
            # given — the CLI builds a MissionRunner for every resume, and
            # a staged run is refused at the door before that.
            transcript = (runner.run(objective) if resumption is None
                          else runner.run(objective, resumption))
    except (McpUnavailable, McpConnectionError) as exc:
        # Scrubbed like everything else a mission says about a failure: this
        # message names the transport, and a transport is a URL, a socket path
        # or a command line on this host.
        console.print(f"❌ {scrub(str(exc))}", style="red")
        return
    finally:
        if sink is not None:
            sink.close()
        # In the same `finally` and for the same reason: the descriptor
        # belongs to whoever spawned us, and a run that ended badly is
        # exactly the one that must still let go of it. The reader is a
        # daemon thread and may be blocked on a pipe nobody will write to
        # again; it is not waited on.
        if control is not None:
            control.close()
        # In the `finally` for the same reason `mission_finished` is: a run
        # that ended badly is exactly the run whose audit gaps matter. The
        # bus already said the FIRST failure on stderr with its exception;
        # this is the count, and it is the line an operator sees whether the
        # mission answered, was killed, or never reached a server.
        failures = getattr(bus, "audit_failures", 0)
        if failures:
            console.print(
                f"⚠️  audit: {failures} entr{'y' if failures == 1 else 'ies'} "
                f"could NOT be written (see stderr) — this run is not fully "
                f"recorded",
                style="red",
            )

    for step in transcript.steps:
        # A turn's calls, and a JSON-protocol turn IS its call — so the
        # step stands in for a one-element list of itself and the two
        # protocols print through one loop. `step.calls` is empty on every
        # JSON run, which is why this line changes nothing about what an
        # operator has always seen; a native turn that dispatched three
        # tools prints three lines instead of hiding two of them.
        for call in step.calls or ([step] if step.tool else []):
            mark = "⚠️" if call.refused else "🔧"
            cut = f" [truncated → {call.handle}]" if call.truncated else ""
            console.print(f"{mark} {call.tool}({call.arguments}){cut}",
                          style=style)
            if call is not step and call.error:
                console.print(f"   {scrub(call.error)}", style="yellow")
        if step.error:
            console.print(f"   {scrub(step.error)}", style="yellow")

    report = transcript.grounding
    if report is not None and report.ran:
        # Three words, not two. "grounded" over an answer that cited nothing
        # is what six of the first ten measured missions printed, and it read
        # exactly like the line over an answer that cited three things right.
        if not report.grounded:
            state = "UNGROUNDED"
        elif not report.verified:
            state = "NOTHING CHECKED"
        else:
            state = "grounded"
        console.print(
            f"🔎 {state}: "
            + "; ".join(f"{r.check} — {r.detail}" for r in report.results
                        if r.configured),
            style=style if report.verified else "yellow",
        )

    if transcript.completed:
        # The same text the stream carried on `answer`, scrubbed the same way,
        # so the console and the record a pane renders say the same thing.
        console.print(Markdown(f"🧞 **{name}:** {scrub(transcript.answer)}"),
                      style=style)
    elif transcript.outcome == AWAITING_APPROVAL:
        # Distinguished from every other unfinished outcome, because it is the
        # only one where the right next move belongs to a person rather than
        # to the operator: nothing failed, and nothing was called.
        proposed = transcript.awaiting or {}
        console.print(
            f"⏸️  Waiting on a person: {name} proposed "
            f"{proposed.get('tool', '?')}({proposed.get('arguments', {})}) "
            f"and it was NOT called.",
            style="yellow",
        )
        # The id and the exact next command. A gate that told somebody they
        # had to decide, and not how, is a gate that gets answered by
        # deleting the flag.
        recorded = proposed.get("approval_id") or ""
        if recorded:
            console.print(
                f"   approval {recorded} — decide it with:\n"
                f"     --mission --approve {recorded} --decided-by <who> "
                f"[--note '<why>']\n"
                f"     --mission --refuse {recorded} --decided-by <who>\n"
                f"   then resume with:  --mission --approval {recorded} "
                f"'<the objective>'",
                style="cyan")
        else:
            console.print(
                "   No durable record was written, so there is no id to "
                "decide against. See the reason above.",
                style="red")
    elif transcript.reason == CANCELLED:
        # Not a failure, and it must not read like one. Somebody asked, and
        # the run wound up rather than being killed between records — which
        # is why there is a transcript above this line to read at all.
        console.print(
            f"🛑 Mission cancelled after {len(transcript.steps)} step(s). "
            f"It wound up on request: the transcript above is complete as far "
            f"as it goes, and the stream closed itself.",
            style="yellow",
        )
    elif transcript.budget is not None:
        # WHICH budget, with the numbers. "budget_exhausted" alone sent an
        # operator to lengthen a step cap that was not the thing that ran out.
        spent = transcript.budget
        console.print(
            f"⏹️  Mission ran out of {spent.which}: {spent.spent} of "
            f"{spent.limit}. Nothing failed — the run hit a bound you set.",
            style="yellow",
        )
    else:
        console.print(
            f"⏹️  Mission ended without an answer: {transcript.outcome}",
            style="yellow",
        )
    # Last, after everything a person or a consumer reads: a run that was
    # SIGTERM'd has now done all of a clean exit's work and owes only the
    # exit status, which must still be the signal's.
    exit_as_signalled(cancel)

    # Last, and only when a provider actually reported: an empty line here
    # would be a run claiming to have spent nothing, and "nothing reported"
    # is not "nothing spent". Rendered by the ledger itself so the console
    # and `mission_finished.usage` cannot disagree about the arithmetic.
    spent = transcript.usage.console_line(rate)
    if spent:
        console.print(spent, style=style)


def _main(AgentClass):
    parser = argparse.ArgumentParser(description=f"{AgentClass.__name__} CLI Interface")
    # Optional at the parser and checked below `parse_args`: it is required
    # for every entry point EXCEPT `--mission --resume` (the recorded run
    # already holds the objective) and `--approve`/`--refuse` (which answer a
    # gate and exit). argparse cannot express "required unless", and a
    # positional it thinks is optional with a refusal that names the
    # exception is a better error than a usage block.
    parser.add_argument("message", type=str, nargs="?", default=None,
                        help="Your message to the AI. Omit it only with "
                             "--mission --resume, --approve or --refuse")
    parser.add_argument("--empty", action="store_true", help="Start new conversation")
    parser.add_argument("--purge", action="store_true", help="Purge long-term memory")
    parser.add_argument("--secret", action="store_true", help="Do not save this message")

    parser.add_argument("--model", type=str, help="Model to use")
    parser.add_argument("--provider", type=str, choices=list(PROVIDERS),
                        help="Force provider backend "
                             "('local' = an OpenAI-compatible endpoint at "
                             "LOCAL_API_BASE serving LOCAL_MODEL)")
    parser.add_argument("--profile", type=str,
                        choices=[m.value for m in ProfileMode],
                        default=None,
                        help="Capability profile: deny-by-default is 'safe' "
                             "(read fs/git, run verifiers, call a connected "
                             "MCP server). 'dev' adds write + shell/python "
                             "exec, 'ops' adds deploy/network, 'god' is "
                             "wildcard. Unset falls back to JUDAIS_LOBI_PROFILE "
                             "then 'safe'; a flag beats the env var "
                             "(env: JUDAIS_LOBI_PROFILE)")
    # Both published names, in the published order — see
    # `_personality_default` and `TAI_PERSONALITY_ENV` below.
    parser.add_argument("--personality", type=Path,
                        default=_personality_default(),
                        help="Load a PersonalityConfig from a TOML/JSON/YAML "
                             "file instead of the built-in one "
                             "(env: TAI_PERSONALITY, then ELF_PERSONALITY)")

    # mission mode: the model picks the tool, from a server's tools/list
    parser.add_argument("--mission", action="store_true",
                        help="Run a mission: discover tools over MCP and let "
                             "the model choose them")
    parser.add_argument("--mcp-stdio", type=str, default=os.getenv("MCP_STDIO"),
                        help="MCP server to spawn over stdio, as a command line "
                             "(env: MCP_STDIO)")
    parser.add_argument("--mcp-url", type=str, default=os.getenv("MCP_URL"),
                        help="MCP server to reach over streamable HTTP "
                             "(env: MCP_URL)")
    parser.add_argument("--mcp-token", type=str, default=os.getenv("MCP_TOKEN"),
                        help="Bearer token for --mcp-url (env: MCP_TOKEN). "
                             "Prefer the env var; an argument is visible in ps")
    parser.add_argument("--mission-steps", type=int, default=None,
                        help=f"Hard cap on tool calls in a mission "
                             f"(default {DEFAULT_MISSION_STEPS}). With "
                             f"--resume it is read as that many FURTHER "
                             f"steps; unset, the resumed run is held to the "
                             f"total it was started with")
    parser.add_argument("--resume", type=str,
                        default=os.getenv("MISSION_RESUME", ""),
                        metavar="RUN_ID",
                        help="Carry on a recorded mission: the run id printed "
                             "when it started, which also rides the opening "
                             "frame as mission_started.run_id. The objective "
                             "comes off that run's own record, so the message "
                             "may be omitted; passing one that is not the "
                             "recorded objective is refused. A run that "
                             "already finished is refused too — except one "
                             "that ended awaiting_approval, which is waiting "
                             "on a person rather than on this harness "
                             "(env: MISSION_RESUME)")
    parser.add_argument("--mission-seconds", type=float,
                        default=_env_seconds("MISSION_SECONDS"),
                        help="Wall-clock budget for a mission, in seconds. "
                             "UNSET MEANS UNBOUNDED, and that is deliberate: "
                             "steps bound the work, seconds bound the "
                             "waiting, and a default nobody chose would kill "
                             "a slow local model mid-answer. Checked between "
                             "steps and before each model call, and shared by "
                             "every stage of a --swarm turn — one clock for "
                             "the mission, not one per sub-mission. A model "
                             "call already in flight is not interrupted, so "
                             "the real bound is this plus one round trip "
                             "(env: MISSION_SECONDS)")
    parser.add_argument("--swarm", action="store_true",
                        default=bool((os.getenv("MISSION_SWARM") or "").strip()),
                        help="Stage the mission when it needs staging: a "
                             "cheap triage call routes small questions "
                             "straight to the ordinary mission loop and "
                             "complex ones through plan / execute / gate / "
                             "synthesize — small specialized prompts over "
                             "the SAME model and the SAME tool bus. The "
                             "events vocabulary and the step cap are "
                             "unchanged (env: MISSION_SWARM)")
    parser.add_argument("--history", type=Path,
                        default=_env_path("MISSION_HISTORY"),
                        help="JSON file of prior conversation turns — an "
                             "array of {role: user|assistant, content} "
                             "objects, oldest first — seeded into the model's "
                             "message list as real chat turns ahead of the "
                             "objective. A chat-tuned model attends to "
                             "role-tagged turns and ignores the same turns "
                             "pasted into the objective as text, so a caller "
                             "passing this must NOT also fold the history "
                             "into the message. A file, not an argument: a "
                             "conversation is many KB and argv is visible in "
                             "ps (env: MISSION_HISTORY)")
    # Unset means UNSENT, not zero. See the note beside `chat_fn`: the default
    # is the server's own, deliberately, because a noise floor taken at a
    # temperature nobody ships is not a floor.
    parser.add_argument("--temperature", type=float, default=None,
                        help="Sampling temperature for a mission. Unset sends "
                             "none and the server's default applies — which "
                             "is what the product runs at, so a measurement "
                             "of the deployed agent leaves this alone")
    parser.add_argument("--top-p", type=float, default=None,
                        help="Nucleus sampling for a mission. Unset sends none")
    parser.add_argument("--seed", type=int, default=None,
                        help="Sampling seed for a mission, where the server "
                             "honours one. Unset sends none. NOT a determinism "
                             "guarantee: a batching server can still vary")
    # Default "" and not "json", deliberately: `--resume` has to be able to
    # tell "nobody said" from "somebody said json". See `_mission_protocol`.
    parser.add_argument("--protocol", type=str,
                        default=os.getenv("MISSION_PROTOCOL", ""),
                        metavar="json|native",
                        help="How the model is asked to decide. 'json' (the "
                             "default) is one JSON object per reply, parsed "
                             "here. 'native' declares the mission's tools as "
                             "functions, declares a mission_answer function "
                             "beside them, and asks the server for "
                             "tool_choice=required — so a reply that does not "
                             "parse and a tool name nobody offers become "
                             "unrepresentable rather than caught, and one "
                             "turn may call several tools. Refused at the "
                             "door on a backend that does not declare "
                             "supports_tool_calls and "
                             "supports_tool_choice_required. Off by default "
                             "until the eval harness has scored it "
                             "(env: MISSION_PROTOCOL)")
    # The variable is the flag's default, so the flag still wins — the same
    # arrangement every other pair on this surface has. Named for the thing
    # it turns OFF, because streaming is the default and a `--stream` flag
    # nobody needs to pass is a flag nobody reads.
    parser.add_argument("--no-stream", action="store_true",
                        default=_stream_is_off(),
                        help="Ask the model for the whole reply at once "
                             "instead of streaming it. Streaming is ON by "
                             "default wherever the backend declares "
                             "supports_streaming: the answer's own fragments "
                             "go out as answer_delta records while the model "
                             "is still writing, which is the only thing a "
                             "watcher has to show during the last turn of a "
                             "minutes-long mission. Turning it off changes "
                             "nothing else — the same answer record arrives "
                             "at the same moment (env: MISSION_STREAM=off)")
    parser.add_argument("--skill", type=Path, default=_env_path("MISSION_SKILL"),
                        help="A SKILL.md manifest (or a directory holding one) "
                             "supplying the mission's closed tool set, its "
                             "prompt and its grounding grammar "
                             "(env: MISSION_SKILL)")
    parser.add_argument("--events", type=str,
                        default=os.getenv("MISSION_EVENTS", ""),
                        help="Write an NDJSON account of the mission AS IT "
                             "HAPPENS: '-' for stdout, 'fd:N' for a pipe the "
                             "parent process passed, or a path. The vocabulary "
                             "is core/runtime/mission_stream.py "
                             "(env: MISSION_EVENTS)")
    parser.add_argument("--control", type=str,
                        default=os.getenv("MISSION_CONTROL", ""),
                        help="Read NDJSON commands INTO the running mission: "
                             "'fd:N' for a pipe the parent process passed, a "
                             "FIFO or a path, or '-' for stdin. One object "
                             "per line: {\"control\": \"inject\", \"text\": "
                             "\"...\"} puts an instruction in front of the "
                             "next model call, \"cancel\" stops the run, "
                             "\"cancel_step\" drops the rest of the current "
                             "step, and \"gate_decision\" answers a gate the "
                             "run is standing at. Bad lines are dropped with "
                             "a line on stderr. The vocabulary is "
                             "core/runtime/control.py (env: MISSION_CONTROL)")
    parser.add_argument("--gate-tool", action="append", default=None,
                        metavar="NAME",
                        help="A tool this deployment offers and GATES. It is "
                             "shown in the catalogue, marked; naming it ends "
                             "the mission holding the proposed arguments, and "
                             "the call is not made. Repeatable. No flag on a "
                             "mission run answers a gate; the answer arrives "
                             "as a durable record written from outside it.")
    parser.add_argument("--approval", type=str,
                        default=os.getenv("MISSION_APPROVAL", ""),
                        metavar="ID",
                        help="Carry a decision somebody already made into "
                             "this run. The approved tool leaves the gated "
                             "set for THIS run only and the approval is spent "
                             "the moment that tool is dispatched. A pending, "
                             "refused, spent or abandoned record is refused "
                             "at the door, naming the state — nothing "
                             "defaults into a yes (env: MISSION_APPROVAL)")
    # Not mission-mode contract flags, deliberately: see `_decide_approval`
    # and the note in CONTRACT.md. A platform that knows who its people are
    # calls `ApprovalStore.decide` from its own process; this is the operator
    # standing at a terminal with an id in their hand.
    parser.add_argument("--approve", type=str, default=None, metavar="ID",
                        help="Answer a gate YES and exit. Not a mission run: "
                             "no agent is built, no model is asked. Requires "
                             "--decided-by — a decision names who made it")
    parser.add_argument("--refuse", type=str, default=None, metavar="ID",
                        help="Answer a gate NO and exit. Requires "
                             "--decided-by")
    parser.add_argument("--decided-by", type=str, default="", metavar="WHO",
                        help="Who is answering the gate. Free text: this "
                             "framework has no principal system and will not "
                             "invent one, but it refuses a decision signed by "
                             "nobody")
    parser.add_argument("--note", type=str, default="",
                        help="What the decider wants recorded — the reason "
                             "for a no, or a condition on a yes")

    parser.add_argument("--unsandboxed", action="store_true",
                        help="Run tool subprocesses with NO isolation. The "
                             "default is a bwrap sandbox wherever bubblewrap "
                             "is installed (write isolation, network denied "
                             "unless a tool asks, a stripped environment); "
                             "this opts out of it. The env form is "
                             "JUDAIS_LOBI_SANDBOX=none, and =bwrap forces the "
                             "sandbox and refuses if bwrap is absent. In-process "
                             "MCP tools are unaffected either way.")

    parser.add_argument("--md", action="store_true", help="Non-streaming markdown output")
    parser.add_argument("--raw", action="store_true", help="Stream output (default)")

    # tools
    parser.add_argument("--search", action="store_true", help="Perform web search")
    parser.add_argument("--deep", action="store_true", help="Deep search")
    parser.add_argument("--research", action="store_true", help="Perform web research")
    parser.add_argument("--academic", action="store_true",
                        help="Use academic sources for research")
    parser.add_argument("--research-results", type=int, default=5,
                        help="Max search results for research")
    parser.add_argument("--research-pages", type=int, default=3,
                        help="Max pages to fetch for research")
    parser.add_argument("--shell", action="store_true", help="Generate and run shell code")
    parser.add_argument("--python", action="store_true", help="Generate and run Python code")
    parser.add_argument("--install-project", action="store_true",
                        help="Install Python project into elf venv")

    # memory recall
    parser.add_argument("--recall", nargs="+",
                        help="Recall past adventures (n [mode])")
    parser.add_argument("--long-term", type=int, help="Recall N best matches from memory")

    parser.add_argument("--summarize", action="store_true", help="Summarize tool output")
    parser.add_argument("--voice", action="store_true", help="Speak the response aloud (lazy TTS)")
    parser.add_argument("--campaign", action="store_true", help="Run a multi-step campaign")
    parser.add_argument("--campaign-plan", type=Path, help="Path to CampaignPlan JSON/YAML")
    parser.add_argument("--auto-approve", action="store_true", help="Skip HUMAN_REVIEW editor step")

    # RAG
    parser.add_argument("--rag", nargs="+",
                        help="RAG ops: crawl/find/delete/list/status/enhance")
    parser.add_argument("--dir", type=Path, help="Directory for RAG")
    parser.add_argument("--recursive", action="store_true", help="Recurse into directories")
    parser.add_argument("--include", action="append", help="Include globs")
    parser.add_argument("--exclude", action="append", help="Exclude globs")

    args = parser.parse_args()
    if getattr(args, "resume", "") and not args.mission:
        parser.error(
            "--resume continues a recorded MISSION; pass --mission with it. "
            "A chat turn keeps its own history and is not a run.")
    os.environ.setdefault("COQUI_TTS_LOG_LEVEL", "ERROR")

    # BEFORE the agent is built, and before anything reads `message`.
    # Answering a gate must share as little as possible with running one:
    # no persona, no memory, no tool bus, no model — nothing that could
    # reach the record except the one function that writes it.
    if args.approve and args.refuse:
        raise SystemExit(
            "--approve and --refuse are the two answers to the same "
            "question. Pass one.")
    if args.approve or args.refuse:
        return _decide_approval(args)
    if not (args.message or "").strip() and not getattr(args, "resume", ""):
        # ONE check for the positional, after the two commands that never
        # take one have returned. The remaining exception is a resume: the
        # recorded run already holds the objective.
        raise SystemExit(
            "a message is required — the question, or the mission's "
            "objective. The exceptions: `--mission --resume <run-id>` takes "
            "the objective from the run it continues, and --approve/--refuse "
            "answer a gate rather than ask anything.")

    print(f"{GREEN}👤 You: {args.message}{RESET}")

    # --- instantiate Elf ---
    elf, name = _build_agent(AgentClass, args)
    style = getattr(elf, "text_color", "cyan")
    provider_name = elf.client.provider.upper()
    console.print(f"🧠 Using provider: {provider_name} | Model: {elf.model}", style=style)

    # --- mission mode (the model chooses the tools) ---
    if args.mission:
        return _run_mission(elf, args, name, style)

    # --- lazy voice registration ---
    if args.voice:
        try:
            from core.tools.speak_text import SpeakTextTool
            elf.tools.register_tool("speak_text", SpeakTextTool())
        except Exception as e:
            console.print(f"⚠️ Voice unavailable: {e}", style="yellow")

    # --- RAG handling ---
    if args.rag:
        subcmd = args.rag[0]
        query = " ".join(args.rag[1:]) if len(args.rag) > 1 else args.message
        hits, msg = elf.handle_rag(subcmd, query, args.dir,
                                   recursive=args.recursive,
                                   includes=args.include, excludes=args.exclude)
        if msg:
            console.print(msg, style=style)
            if not args.secret:
                elf.memory.add_short("system", msg)
        if hits:
            console.print(f"📚 Injected {len(hits)} RAG hits", style=style)
        if subcmd != "enhance":
            return

    # --- Campaign handling ---
    if args.campaign or args.campaign_plan:
        if args.campaign_plan is not None:
            from core.contracts.campaign import CampaignPlan
            plan_path = args.campaign_plan
            raw = plan_path.read_text()
            if plan_path.suffix in {".yml", ".yaml"}:
                import yaml
                data = yaml.safe_load(raw) or {}
                plan = CampaignPlan.model_validate(data)
            else:
                plan = CampaignPlan.model_validate_json(raw)
            state = elf.run_campaign(plan, base_dir=Path.cwd(), auto_approve=args.auto_approve)
        else:
            state = elf.run_campaign_from_description(
                args.message, base_dir=Path.cwd(), auto_approve=args.auto_approve
            )
        console.print(f"Campaign finished: {state.status}", style=style)
        return

    # --- memory management ---
    if args.empty:
        elf.reset_history()
        console.print("🧹 Starting fresh.", style=style)
    if args.purge:
        elf.purge_memory()
        console.print(f"🧠 {name} purged long-term memory.", style=style)

    elf.enrich_with_memory(args.message)
    if args.search:
        elf.enrich_with_search(args.message, deep=args.deep)
        console.print(f"🔍 {name} searching...", style=style)
    if args.research:
        elf.enrich_with_research(
            args.message,
            max_results=args.research_results,
            max_pages=args.research_pages,
            mode="academic" if args.academic else "web",
        )
        console.print(f"📚 {name} researching...", style=style)

    if args.recall:
        n = int(args.recall[0])
        mode = args.recall[1] if len(args.recall) > 1 else None
        rows = elf.recall_adventures(n=n, mode=mode)
        reflection = elf.format_recall(rows) if rows else None
        if reflection:
            console.print(f"📖 Recall:\n{reflection}", style=style)
    else:
        reflection = None

    # =====================================================
    # 🧩 Restored Code Execution Hooks
    # =====================================================
    try:
        if args.python:
            code, result, success, summary = elf.run_python_task(args.message, reflection, summarize=args.summarize)
            console.print(f"🧠 {name} wrote Python:\n{code}", style=style)
            console.print(f"💥 Result:\n{result}", style=style)
            if summary:
                console.print(f"🧾 Summary:\n{summary}", style=style)
            return

        if args.shell:
            cmd, result, success, summary = elf.run_shell_task(args.message, reflection, summarize=args.summarize)
            console.print(f"🧠 {name} executed shell:\n{cmd}", style=style)
            console.print(f"💥 Output:\n{result}", style=style)
            if summary:
                console.print(f"🧾 Summary:\n{summary}", style=style)
            return
    except Exception as e:
        console.print(f"\n❌ Code execution error: {e}", style="red")
        return

    # =====================================================
    # 🧠 Normal Chat Path
    # =====================================================
    try:
        if args.md:
            reply = elf.chat(args.message, stream=False)
            console.print(Markdown(f"🧞 **{name}:** {reply}"), style=style)
            if args.voice:
                elf.tools.run("speak_text", strip_markdown(reply))
        else:
            resp_iter = elf.chat(args.message, stream=True)
            console.print(f"🧞 {name}: ", style=style, end="")
            reply = ""
            for chunk in resp_iter:
                if hasattr(chunk, "choices"):
                    delta = getattr(chunk.choices[0], "delta", None)
                    content = getattr(delta, "content", None) if delta else None
                    if content:
                        console.print(content, style=style, end="")
                        reply += content
            print()
            if args.voice and reply:
                elf.tools.run("speak_text", reply)

        if not args.secret:
            elf.history.append({"role": "assistant", "content": reply})
            elf.save_history()
            elf.remember(args.message, reply)

    except Exception as e:
        console.print(f"\n❌ Error: {e}", style="red")


def main_lobi():
    from lobi import Lobi
    _main(Lobi)


def main_judais():
    from judais import JudAIs
    _main(JudAIs)


#: Where Tai's ``PersonalityConfig`` is looked for, in order, and why the
#: search is two sources long rather than five.
#:
#: Tai's personality is content, and it belongs to whoever operates Tai —
#: on purpose, so that a claim Tai makes about governance sits under the
#: test suite that owns the governance. That makes it the one personality
#: this framework ships without shipping: judais-lobi has to find a file
#: it does not contain.
#:
#: It used to do that by guessing. Three fixed directories under ``$HOME``
#: and a sibling of the cwd, plus a deployment's own source layout frozen
#: into a relative-path constant — one developer's laptop, shipped inside
#: a package to every other machine. A guess that lands on the *wrong*
#: checkout is worse than no guess at all: it produces an agent whose
#: stated rules are not the rules it loaded, which is the exact failure
#: this resolution exists to prevent.
#:
#: What is left is what can be right by construction. An operator's
#: explicit path always wins. Otherwise the deployment package's own
#: resource, because if it imports, its ``tai.toml`` is the one matching
#: the code in that same environment. Nothing else is consulted, and
#: nothing is invented: the third outcome is a refusal that names what was
#: consulted.
TAI_PERSONALITY_ENV = ("TAI_PERSONALITY", "ELF_PERSONALITY")


def _personality_default():
    """The persona file an environment set, or ``None`` — for any entry.

    The order is :data:`TAI_PERSONALITY_ENV`: ``TAI_PERSONALITY`` first,
    then ``ELF_PERSONALITY``, then nothing, which leaves whichever
    built-in personality the typed entry point carries.  Two names
    because :data:`core.runtime.contract.ENV_VARS` publishes two:
    ``ELF_PERSONALITY`` is the historical one the reference deployment
    exports into the agent's environment, and ``TAI_PERSONALITY`` is the
    one the contract names.

    Until this read both, only :func:`main_tai` honoured
    ``TAI_PERSONALITY``.  The ``--personality`` default read
    ``ELF_PERSONALITY`` alone, so a consumer that set the *published*
    name and spawned ``judais --mission`` — the documented way to run a
    mission — got the JudAIs persona, and nothing on any stream said so.

    The published name wins where both are set.  Nothing regresses on
    that choice: the reference deployment exports only the historical
    one, so the two are never both set by anything that exists today,
    and a process that sets both has named the specific one on purpose.

    Unlike :func:`tai_personality_path` this does **not** require the
    file to exist.  A path that points nowhere becomes
    ``PersonalityConfig.from_file``'s "No personality file at ..." —
    which names the typo — rather than a silent fall-through to a
    built-in persona under an operator who believes they replaced it.
    """
    for var in TAI_PERSONALITY_ENV:
        found = _env_path(var)
        if found is not None:
            return found
    return None


#: The deployment package whose installed resources are consulted, and the
#: file inside it. Named in one place so the refusal cannot drift from the
#: lookup: an error message that names a package the code no longer tries
#: is a message that sends an operator to fix the wrong thing.
TAI_PERSONALITY_PACKAGE = "taipan.agent.personalities"
TAI_PERSONALITY_RESOURCE = "tai.toml"


def _installed_personality():
    """Tai's personality from the installed deployment package, or ``None``.

    The import is guarded and a missing package is an ordinary ``None``,
    not an error: this framework is installable and runnable on its own,
    and a deployment that is simply not present here is the common case
    rather than a fault.
    """
    try:
        from importlib.resources import files
        resource = files(TAI_PERSONALITY_PACKAGE) / TAI_PERSONALITY_RESOURCE
        if resource.is_file():
            return Path(str(resource))
    except (ImportError, ModuleNotFoundError, TypeError,
            AttributeError, OSError):
        pass
    return None


def tai_personality_path():
    """Tai's personality file, or ``None`` — never a guess.

    Returning ``None`` rather than a plausible default is the point. A
    missing personality would mean Tai starting on whatever config it was
    handed while still calling itself Tai in the banner. :func:`main_tai`
    turns ``None`` into a sentence naming exactly what was consulted.
    """
    for var in TAI_PERSONALITY_ENV:
        candidate = _env_path(var)
        if candidate and candidate.exists():
            return candidate
    return _installed_personality()


def _personality_refusal() -> str:
    """What was consulted, in the order it was consulted, and the fix.

    Composed from the constants above rather than typed out, and it
    distinguishes an env var that is unset from one that points at a file
    that is not there — the second is a typo, the first is a missing
    export, and they are not the same repair.
    """
    consulted = []
    for var in TAI_PERSONALITY_ENV:
        raw = (os.getenv(var) or "").strip()
        state = f"set to {raw!r}, which is not a file" if raw else "unset"
        consulted.append(f"  ${var} — {state}")
    consulted.append(
        f"  the installed {TAI_PERSONALITY_PACKAGE.split('.')[0]!r} package "
        f"({TAI_PERSONALITY_PACKAGE}/{TAI_PERSONALITY_RESOURCE}) — not found"
    )
    return (
        "Cannot find Tai's personality file (tai.toml).\n\n"
        "Tai's personality is content and belongs to the deployment that "
        "operates Tai, so that what Tai says about governance is tested "
        "against the governance itself. This framework does not contain "
        "it, and it does not guess at where a checkout of one might be.\n\n"
        "Consulted, in this order:\n"
        + "\n".join(consulted)
        + "\n\nPoint it at a file:\n"
        f"  export {TAI_PERSONALITY_ENV[0]}=/path/to/tai.toml\n"
        "  python main.py tai <message> --personality /path/to/tai.toml"
    )


def main_tai():
    """The mission-agent personality, by name.

    Everything Tai *is* lives in the TOML — the persona, the governance
    rules, the default provider and model. This function contributes one
    thing: that ``tai`` is a name you can type, and that typing it is
    enough.
    """
    import sys

    from core.agent import Agent

    if "--personality" not in sys.argv:
        found = tai_personality_path()
        if found is None:
            print(_personality_refusal(), file=sys.stderr)
            sys.exit(2)
        sys.argv += ["--personality", str(found)]

    _main(Agent)
