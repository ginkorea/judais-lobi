#!/usr/bin/env python3
import argparse
import os
from pathlib import Path
from rich.console import Console
from rich.markdown import Markdown

GREEN = "\033[92m"
RESET = "\033[0m"
console = Console()


def strip_markdown(md: str) -> str:
    """Convert Markdown to plain text (for TTS)."""
    from io import StringIO
    from rich.console import Console as StrippedConsole
    from rich.text import Text
    sio = StringIO()
    StrippedConsole(file=sio, force_terminal=False, color_system=None).print(Markdown(md))
    return Text.from_markup(sio.getvalue()).plain


def _main(Elf):
    parser = argparse.ArgumentParser(description=f"{Elf.__name__} CLI Interface")
    parser.add_argument("message", type=str, help="Your message to the AI")

    # conversation / memory
    parser.add_argument("--empty", action="store_true", help="Start a new conversation")
    parser.add_argument("--purge", action="store_true", help="Purge long-term memory")
    parser.add_argument("--secret", action="store_true", help="Do not store this turn in history")

    # provider / model
    parser.add_argument("--model", type=str, help="Model to use (auto per provider)")
    parser.add_argument("--provider", type=str, choices=["openai", "mistral"],
                        help="Force provider backend")

    # output mode
    parser.add_argument("--md", action="store_true", help="Render output with markdown (non-stream)")
    parser.add_argument("--raw", action="store_true", help="Stream output (default)")

    # tools
    parser.add_argument("--search", action="store_true", help="Perform web search")
    parser.add_argument("--deep", action="store_true", help="Deep dive search")
    parser.add_argument("--shell", action="store_true", help="Write and run a shell command")
    parser.add_argument("--python", action="store_true", help="Write and run Python code")
    parser.add_argument("--install-project", action="store_true",
                        help="Install a Python project into the elf's venv")

    # recall
    parser.add_argument("--recall", nargs="+",
                        help="Recall last N adventures, optionally filter by mode (python/shell)")
    parser.add_argument("--long-term", type=int, help="Recall N best matches from long-term memory")

    # voice (lazy)
    parser.add_argument("--voice", action="store_true", help="Speak the response aloud (optional TTS)")

    # rag
    parser.add_argument("--rag", nargs="+",
                        help="RAG ops: crawl/find/delete/list/overwrite/status/enhance")
    parser.add_argument("--dir", type=Path, help="Directory filter for RAG")
    parser.add_argument("--recursive", action="store_true", help="Recurse subdirectories")
    parser.add_argument("--include", action="append", help="Glob(s) to include (repeatable)")
    parser.add_argument("--exclude", action="append", help="Glob(s) to exclude (repeatable)")

    args = parser.parse_args()

    # keep TTS quiet unless used
    os.environ["COQUI_TTS_LOG_LEVEL"] = "ERROR"

    invoked_tools = []
    if args.search:
        invoked_tools.append("WebSearch (deep)" if args.deep else "WebSearch")
    if args.rag:
        invoked_tools.append(f"RAG:{args.rag[0]}")
    if args.shell:
        invoked_tools.append("Shell")
    if args.python:
        invoked_tools.append("Python")

    print(f"{GREEN}\U0001f464 You: {args.message}{RESET}")

    # instantiate elf (provider/model resolved inside)
    elf = Elf(model=args.model, provider=args.provider)
    style = getattr(elf, "text_color", "cyan")
    console.print(f"🧠 Using provider: {elf.client.provider.upper()} | Model: {elf.model}", style=style)

    # Optional voice tool (lazy import/registration)
    if args.voice:
        try:
            from core.tools.speak_text import SpeakTextTool
            elf.tools.register_tool("speak_text", SpeakTextTool())
        except Exception as e:
            console.print(f"⚠️ Voice unavailable: {e}", style="yellow")

    # RAG
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
            console.print(f"📚 Injected {len(hits)} rag hits", style=style)
            if not args.secret:
                for h in hits:
                    elf.memory.add_short("system", f"RAG hit: {h}")
        if subcmd != "enhance":
            return

    # memory control
    if args.empty:
        elf.reset_history()
        console.print("🧹 Starting a new conversation", style=style)
    if args.purge:
        elf.purge_memory()
        console.print(f"🧠 {Elf.__name__} forgets everything long-term...", style=style)

    # enrich
    elf.enrich_with_memory(args.message)
    if args.search:
        elf.enrich_with_search(args.message, deep=args.deep)
        console.print(f"🔍 {Elf.__name__} searches…", style=style)

    # recall adventures
    memory_reflection = None
    if args.recall:
        n = int(args.recall[0])
        mode = args.recall[1] if len(args.recall) > 1 else None
        rows = elf.recall_adventures(n=n, mode=mode)
        if rows:
            memory_reflection = elf.format_recall(rows)
            console.print(f"📖 {Elf.__name__} recalls:\n{memory_reflection}", style=style)

    # tool-based execution
    if args.shell:
        command, result, success, summary = elf.run_shell_task(
            args.message, memory_reflection, summarize=args.summarize if hasattr(args, "summarize") else False
        )
        console.print(f"⚙️  {Elf.__name__} thinks:\n{command}", style=style)
        console.print(f"💥 Output:\n{result}", style=style)
        if summary:
            console.print(f"📝 Summary:\n{summary}", style=style)
            if args.voice:
                elf.tools.run("speak_text", summary)
        if not args.secret:
            elf.save_coding_adventure(args.message, command, result, "shell", success)
        return

    if args.python:
        code, result, success, summary = elf.run_python_task(
            args.message, memory_reflection, summarize=False
        )
        console.print(f"💻 {Elf.__name__} writes:\n{code}", style=style)
        console.print(f"📦 Result:\n{result}", style=style)
        if summary:
            console.print(f"🧾 Summary:\n{summary}", style=style)
            if args.voice:
                elf.tools.run("speak_text", summary)
        if not args.secret:
            elf.save_coding_adventure(args.message, code, result, "python", success)
        return

    # default chat path
    try:
        # Workaround: Mistral streaming SSE may differ; use non-stream for Mistral
        force_no_stream = (elf.client.provider.lower() == "mistral")
        use_stream = (not args.md) and (not force_no_stream) and (args.raw or True)

        if args.md or force_no_stream:
            reply = elf.chat(args.message, stream=False, invoked_tools=invoked_tools)
            console.print(Markdown(f"🧞 **{Elf.__name__}:** {reply}"), style=style)
            if args.voice:
                elf.tools.run("speak_text", strip_markdown(str(reply)))
        else:
            stream = elf.chat(args.message, stream=True, invoked_tools=invoked_tools)
            console.print(f"🧞 {Elf.__name__}: ", style=style, end="")
            reply = ""
            for chunk in stream:
                delta = getattr(chunk.choices[0], "delta", None)
                if delta and getattr(delta, "content", None):
                    seg = delta.content
                    reply += seg
                    console.print(seg, style=style, end="")
            print()
            if args.voice:
                elf.tools.run("speak_text", reply)

        if not args.secret:
            elf.history.append({"role": "assistant", "content": str(reply)})
            elf.save_history()
            elf.remember(args.message, str(reply))

    except Exception as e:
        console.print(f"\n❌ Error: {e}", style="red")


def main_lobi():
    from lobi import Lobi
    _main(Lobi)


def main_judais():
    from judais import JudAIs
    _main(JudAIs)
