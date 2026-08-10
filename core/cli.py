#!/usr/bin/env python3
import argparse
import os
from pathlib import Path
from rich.console import Console
from rich.markdown import Markdown

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
    and Lobi are untouched — with no flag and no ``ELF_PERSONALITY``,
    this is the line that was here before.
    """
    if not getattr(args, "personality", None):
        return AgentClass(model=args.model, provider=args.provider), AgentClass.__name__

    from core.agent import Agent
    from core.contracts.schemas import PersonalityConfig

    config = PersonalityConfig.from_file(args.personality)
    agent = Agent(
        config=config,
        model=args.model or config.default_model,
        provider=args.provider or config.default_provider,
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


def _mission_tools(manifest, discovered, style):
    """The mission's tool subset: the skill's closed set, or everything.

    With no manifest this is the whole bridge, which is what the mission
    path did before skills existed.  It is a fallback and not a default
    posture — ``MissionRunner``'s own contract asks for a subset, and a
    governed deployment supplies one in a manifest.
    """
    if manifest is None:
        console.print(
            "⚠️  No --skill: the mission is offered every discovered tool. "
            "A skill manifest supplies the closed set and the operational "
            "knowledge that goes with it.",
            style="yellow",
        )
        return list(discovered)

    from core.runtime.skills import SkillToolsUnavailable

    try:
        return manifest.resolve(discovered)
    except SkillToolsUnavailable as exc:
        raise SystemExit(f"--skill: {exc}")


def _run_mission(elf, args, name, style):
    """Discover tools over MCP, bridge them, and let the model choose.

    Everything the agent can reach in a mission arrives through
    ``tools/list`` and is dispatched through the agent's own ToolBus.
    No store, path or compute plane is touched from here.

    What the model is *told* comes from two files and no code: the
    persona (``--personality``) and the skill manifest (``--skill``).
    This function joins them in that order — who you are, then what you
    are doing — and supplies neither.
    """
    from core.runtime.grounding import GroundingConfig, GroundingValidator
    from core.runtime.mission import MissionRunner
    from core.tools.mcp_client import McpClient, McpUnavailable, McpConnectionError

    manifest = _load_skill(args)
    transport = _build_mcp_transport(args)
    bus = elf.tools.bus

    try:
        validator = GroundingValidator.from_config(
            GroundingConfig.from_mapping(manifest.grounding) if manifest else None
        )
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

    def chat_fn(messages):
        # The mission loop still reads one JSON object out of the reply; the
        # backend renders any native tool_call back into that shape. So this
        # changes what the SERVER is told, not what the kernel understands.
        extra = {}
        if declared and getattr(elf.client, "supports_tool_calls", True):
            extra = {"tools": declared, "tool_choice": "auto"}
        return elf.client.chat(model=elf.model, messages=messages,
                               stream=False, **extra)

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
            tool_names = _mission_tools(manifest, discovered, style)
            declared[:] = _function_schemas(tool_names)
            if manifest:
                console.print(
                    f"📜 skill {manifest.name} — {len(tool_names)} tool(s): "
                    f"{', '.join(tool_names)}"
                    + ("" if validator else "  (no grounding grammar)"),
                    style=style,
                )
            runner = MissionRunner(
                chat_fn, bus, tool_names,
                system_message=system_message,
                max_steps=args.mission_steps,
                validator=validator,
            )
            transcript = runner.run(args.message)
    except (McpUnavailable, McpConnectionError) as exc:
        console.print(f"❌ {exc}", style="red")
        return

    for step in transcript.steps:
        if step.tool:
            mark = "⚠️" if step.refused else "🔧"
            cut = f" [truncated → {step.handle}]" if step.truncated else ""
            console.print(f"{mark} {step.tool}({step.arguments}){cut}", style=style)
        if step.error:
            console.print(f"   {step.error}", style="yellow")

    report = transcript.grounding
    if report is not None and report.ran:
        state = "grounded" if report.grounded else "UNGROUNDED"
        console.print(
            f"🔎 {state}: "
            + "; ".join(f"{r.check} — {r.detail}" for r in report.results
                        if r.configured),
            style=style if report.grounded else "yellow",
        )

    if transcript.completed:
        console.print(Markdown(f"🧞 **{name}:** {transcript.answer}"), style=style)
    else:
        console.print(
            f"⏹️  Mission ended without an answer: {transcript.outcome}",
            style="yellow",
        )


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
    parser.add_argument("--personality", type=Path,
                        default=_env_path("ELF_PERSONALITY"),
                        help="Load a PersonalityConfig from a TOML/JSON/YAML "
                             "file instead of the built-in one "
                             "(env: ELF_PERSONALITY)")

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
    parser.add_argument("--skill", type=Path, default=_env_path("MISSION_SKILL"),
                        help="A SKILL.md manifest (or a directory holding one) "
                             "supplying the mission's closed tool set, its "
                             "prompt and its grounding grammar "
                             "(env: MISSION_SKILL)")

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


#: Where Tai's ``PersonalityConfig`` is looked for, in order, and why there are
#: four sources rather than a constant.
#:
#: Tai is TAIPAN's agent and its personality file lives in TAIPAN — on purpose,
#: so that a claim Tai makes about governance sits under the test suite that
#: owns the governance. That makes it the one personality this repository ships
#: without shipping: judais-lobi has to find a file it does not contain, and
#: must not hard-code a path on one developer's laptop to do it.
#:
#: The installed package is tried before the checkouts because it is the only
#: source that is right by construction: if ``taipan`` imports, its ``tai.toml``
#: is the one matching the SDK in that same environment. Env vars come first so
#: an operator can always overrule the search.
TAI_PERSONALITY_ENV = ("TAI_PERSONALITY", "ELF_PERSONALITY")
TAI_PERSONALITY_RELPATH = Path("src/taipan/agent/personalities/tai.toml")


def tai_personality_path():
    """Tai's personality file, or ``None`` — never a guess.

    Returning ``None`` rather than a plausible default is the point. A missing
    personality would mean Tai starting on whatever config it was handed while
    still calling itself Tai in the banner, which is the exact failure this
    file exists to prevent: an agent whose stated rules are not the rules it
    loaded. :func:`main_tai` turns ``None`` into a sentence naming everywhere
    it looked.
    """
    for var in TAI_PERSONALITY_ENV:
        candidate = _env_path(var)
        if candidate and candidate.exists():
            return candidate

    try:  # the installed SDK — right by construction when it is present
        from importlib.resources import files
        resource = files("taipan.agent.personalities") / "tai.toml"
        if resource.is_file():
            return Path(str(resource))
    except (ImportError, ModuleNotFoundError, TypeError, AttributeError):
        pass

    roots = []
    if os.getenv("TAIPAN_HOME"):
        roots.append(Path(os.environ["TAIPAN_HOME"]))
    roots += [Path.home() / "data" / "workspace" / "TAIPAN",
              Path.home() / "workspace" / "TAIPAN",
              Path.cwd().parent / "TAIPAN"]
    for root in roots:
        candidate = root / TAI_PERSONALITY_RELPATH
        if candidate.exists():
            return candidate
    return None


def main_tai():
    """TAIPAN's mission agent, by name.

    Everything Tai *is* lives in the TOML — the persona, the governance rules,
    the default provider and model. This function contributes one thing: that
    ``tai`` is a name you can type, and that typing it is enough.
    """
    import sys

    from core.agent import Agent

    if "--personality" not in sys.argv:
        found = tai_personality_path()
        if found is None:
            print(
                "Cannot find Tai's personality file (tai.toml).\n\n"
                "Tai is TAIPAN's agent and its personality ships in TAIPAN, so "
                "that what Tai says about governance is tested against the "
                "governance itself. This repository does not contain it.\n\n"
                "Any one of these fixes it:\n"
                "  pip install taipan                     # found by import\n"
                "  export TAIPAN_HOME=/path/to/TAIPAN\n"
                "  export TAI_PERSONALITY=/path/to/tai.toml\n"
                "  python main.py tai <message> --personality /path/to/tai.toml",
                file=sys.stderr)
            sys.exit(2)
        sys.argv += ["--personality", str(found)]

    _main(Agent)
