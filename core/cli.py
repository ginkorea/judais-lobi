#!/usr/bin/env python3
import argparse
import os
from pathlib import Path
from rich.console import Console
from rich.markdown import Markdown

from core.contracts.schemas import ProfileMode
from core.runtime.provider_config import PROVIDERS

GREEN = "\033[92m"
RESET = "\033[0m"
console = Console()


def _env_path(name: str):
    """A Path from an env var, or None. Used as an argparse default."""
    value = (os.getenv(name) or "").strip()
    return Path(value) if value else None


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
    from core.redact import scrub
    from core.runtime.context_window import MissionWindow
    from core.runtime.grounding import GroundingConfig, GroundingValidator
    from core.runtime.mission import AWAITING_APPROVAL, MissionRunner
    from core.runtime.mission_stream import close_on_sigterm, open_sink
    from core.runtime.results import RESULT_TOOL
    from core.runtime.usage import PricingTable
    from core.tools.mcp_client import McpClient, McpUnavailable, McpConnectionError

    manifest = _load_skill(args)
    # Read and validated BEFORE the connection, like the grounding grammar
    # below: a malformed history is a refusal at the door, not a mission
    # that runs to completion answering questions nobody quite asked.
    history = _load_history(args)
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

    def chat_fn(messages):
        # The mission loop still reads one JSON object out of the reply; the
        # backend renders any native tool_call back into that shape. So this
        # changes what the SERVER is told, not what the kernel understands.
        extra = dict(sampling)
        if declared and getattr(elf.client, "supports_tool_calls", True):
            extra.update({"tools": declared, "tool_choice": "auto"})
        return elf.client.chat(model=elf.model, messages=messages,
                               stream=False, **extra)

    def plain_chat_fn(messages):
        # No tool schemas, deliberately: the swarm's router, planner, gate
        # and synthesizer must answer their question in bare JSON or prose,
        # and a harmony model with a function namespace declared will answer
        # a yes/no question with a tool call.
        return elf.client.chat(model=elf.model, messages=messages,
                               stream=False, **dict(sampling))

    def usage_fn():
        # The side channel beside `chat`. Read straight after each of the
        # two functions above returns, by whichever runner made the call —
        # `chat` returns a string and cannot also return a number without
        # breaking every caller of it. `getattr` with a default because a
        # library caller may hand `Agent` a client that never heard of
        # usage, and a mission must not need one to run.
        return getattr(elf.client, "last_usage", None)

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
    # A consumer stopping a turn sends SIGTERM and expects what was already
    # written to survive. Nothing made that true until this line.
    close_on_sigterm(sink)

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
            if gated:
                console.print(
                    f"🔒 gated: {', '.join(gated)} — offered and not called; "
                    f"proposing one ends the mission for a person to decide",
                    style=style,
                )
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
            if getattr(args, "swarm", False):
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
                    max_steps=args.mission_steps,
                    validator=validator,
                    gated=gated,
                    history=history,
                    observer=sink,
                    plain_chat_fn=plain_chat_fn,
                    # The manifest is the only thing here that knows what
                    # the platform is called to `import`. Without it the
                    # planner is not offered the code+sdk rung at all.
                    sdk_import=manifest.sdk_import if manifest else "",
                    window=window,
                    usage_fn=usage_fn,
                    rate=rate,
                )
            else:
                runner = MissionRunner(
                    chat_fn, bus, tool_names,
                    system_message=system_message,
                    max_steps=args.mission_steps,
                    validator=validator,
                    gated=gated,
                    history=history,
                    observer=sink,
                    window=window,
                    usage_fn=usage_fn,
                    rate=rate,
                )
            transcript = runner.run(args.message)
    except (McpUnavailable, McpConnectionError) as exc:
        # Scrubbed like everything else a mission says about a failure: this
        # message names the transport, and a transport is a URL, a socket path
        # or a command line on this host.
        console.print(f"❌ {scrub(str(exc))}", style="red")
        return
    finally:
        if sink is not None:
            sink.close()
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
        if step.tool:
            mark = "⚠️" if step.refused else "🔧"
            cut = f" [truncated → {step.handle}]" if step.truncated else ""
            console.print(f"{mark} {step.tool}({step.arguments}){cut}", style=style)
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
    else:
        console.print(
            f"⏹️  Mission ended without an answer: {transcript.outcome}",
            style="yellow",
        )

    # Last, and only when a provider actually reported: an empty line here
    # would be a run claiming to have spent nothing, and "nothing reported"
    # is not "nothing spent". Rendered by the ledger itself so the console
    # and `mission_finished.usage` cannot disagree about the arithmetic.
    spent = transcript.usage.console_line(rate)
    if spent:
        console.print(spent, style=style)


def _main(AgentClass):
    parser = argparse.ArgumentParser(description=f"{AgentClass.__name__} CLI Interface")
    parser.add_argument("message", type=str, help="Your message to the AI")
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
    parser.add_argument("--mission-steps", type=int, default=8,
                        help="Hard cap on tool calls in a mission")
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
    parser.add_argument("--gate-tool", action="append", default=None,
                        metavar="NAME",
                        help="A tool this deployment offers and GATES. It is "
                             "shown in the catalogue, marked; naming it ends "
                             "the mission holding the proposed arguments, and "
                             "the call is not made. Repeatable. There is "
                             "deliberately no flag that answers a gate.")

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
    os.environ.setdefault("COQUI_TTS_LOG_LEVEL", "ERROR")

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
