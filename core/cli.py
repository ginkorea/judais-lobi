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
    """Convert Markdown to plain text for optional TTS."""
    from io import StringIO
    from rich.console import Console as StrippedConsole
    from rich.text import Text

    sio = StringIO()
    stripped_console = StrippedConsole(file=sio, force_terminal=False, color_system=None)
    stripped_console.print(Markdown(md))
    return Text.from_markup(sio.getvalue()).plain


def _main(Elf):
    parser = argparse.ArgumentParser(description=f"{Elf.__name__} CLI Interface")
    parser.add_argument("message", type=str, help="Your message to the AI")
    parser.add_argument("--empty", action="store_true", help="Start new conversation")
    parser.add_argument("--purge", action="store_true", help="Purge long-term memory")
    parser.add_argument("--secret", action="store_true", help="Do not save this message")

    parser.add_argument("--model", type=str, help="Model to use")
    parser.add_argument("--provider", type=str, choices=["openai", "mistral"],
                        help="Force provider backend")

    parser.add_argument("--md", action="store_true", help="Non-streaming markdown output")
    parser.add_argument("--raw", action="store_true", help="Stream output (default)")

    # tools
    parser.add_argument("--search", action="store_true", help="Perform web search")
    parser.add_argument("--deep", action="store_true", help="Deep search")
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

    # RAG
    parser.add_argument("--rag", nargs="+",
                        help="RAG ops: crawl/find/delete/list/status/enhance")
    parser.add_argument("--dir", type=Path, help="Directory for RAG")
    parser.add_argument("--recursive", action="store_true", help="Recurse into directories")
    parser.add_argument("--include", action="append", help="Include globs")
    parser.add_argument("--exclude", action="append", help="Exclude globs")

    args = parser.parse_args()

    os.environ.setdefault("COQUI_TTS_LOG_LEVEL", "ERROR")

    invoked_tools = []
    if args.search:
        invoked_tools.append("WebSearch (deep)" if args.deep else "WebSearch")
    if args.rag:
        invoked_tools.append(f"RAG:{args.rag[0]}")
    if args.shell:
        invoked_tools.append("Shell")
    if args.python:
        invoked_tools.append("Python")

    print(f"{GREEN}👤 You: {args.message}{RESET}")

    # --- instantiate Elf ---
    elf = Elf(model=args.model, provider=args.provider)
    style = getattr(elf, "text_color", "cyan")
    provider_name = elf.client.provider.upper()
    console.print(f"🧠 Using provider: {provider_name} | Model: {elf.model}", style=style)

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

    # --- memory management ---
    if args.empty:
        elf.reset_history()
        console.print("🧹 Starting fresh.", style=style)
    if args.purge:
        elf.purge_memory()
        console.print(f"🧠 {Elf.__name__} purged long-term memory.", style=style)

    elf.enrich_with_memory(args.message)
    if args.search:
        elf.enrich_with_search(args.message, deep=args.deep)
        console.print(f"🔍 {Elf.__name__} searching...", style=style)

    if args.recall:
        n = int(args.recall[0])
        mode = args.recall[1] if len(args.recall) > 1 else None
        rows = elf.recall_adventures(n=n, mode=mode)
        reflection = elf.format_recall(rows) if rows else None
        if reflection:
            console.print(f"📖 Recall:\n{reflection}", style=style)
    else:
        reflection = None

    # --- main chat path ---
    try:
        if args.md:
            reply = elf.chat(args.message, stream=False, invoked_tools=invoked_tools)
            console.print(Markdown(f"🧞 **{Elf.__name__}:** {reply}"), style=style)
            if args.voice:
                elf.tools.run("speak_text", strip_markdown(reply))
            final_reply = reply
        else:
            # Streaming mode (unified across providers)
            resp_iter = elf.chat(args.message, stream=True, invoked_tools=invoked_tools)
            console.print(f"🧞 {Elf.__name__}: ", style=style, end="")
            final_reply = ""
            for chunk in resp_iter:
                if hasattr(chunk, "choices"):
                    delta = getattr(chunk.choices[0], "delta", None)
                    content = getattr(delta, "content", None) if delta else None
                    if content:
                        console.print(content, style=style, end="")
                        final_reply += content
            print()
            if args.voice and final_reply:
                elf.tools.run("speak_text", final_reply)

        # --- persist ---
        if not args.secret:
            elf.history.append({"role": "assistant", "content": final_reply})
            elf.save_history()
            elf.remember(args.message, final_reply)

    except Exception as e:
        console.print(f"\n❌ Error: {e}", style="red")


def main_lobi():
    from lobi import Lobi
    _main(Lobi)


def main_judais():
    from judais import JudAIs
    _main(JudAIs)
