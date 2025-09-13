# A CLI interface for interacting with Elf subclasses like Lobi and JudAIs.
# core/cli.py

import argparse
from rich.console import Console
from rich.markdown import Markdown
from pathlib import Path
from core.tools.run_shell import RunShellTool
from core.tools.run_python import RunPythonTool
import sqlite3

GREEN = "\033[92m"
RESET = "\033[0m"

console = Console()

def strip_markdown(md: str) -> str:
    from io import StringIO
    from rich.console import Console as StrippedConsole
    from rich.markdown import Markdown
    from rich.text import Text

    sio = StringIO()
    stripped_console = StrippedConsole(file=sio, force_terminal=False, color_system=None)
    stripped_console.print(Markdown(md))
    return Text.from_markup(sio.getvalue()).plain

def _main(Elf):
    parser = argparse.ArgumentParser(description=f"{Elf.__name__} CLI Interface")
    parser.add_argument("message", type=str, help="Your message to the AI")
    parser.add_argument("--empty", action="store_true", help="Start a new conversation")
    parser.add_argument("--purge", action="store_true", help="Purge long-term memory")
    parser.add_argument("--secret", action="store_true", help="Do not save this message in history")
    parser.add_argument(
        "--model",
        type=str,
        help="Model to use (default: gpt-4.1-mini). Options: gpt-4.1-mini, gpt-4.1, gpt-5"
    )
    parser.add_argument("--md", action="store_true", help="Render output with markdown (non-streaming)")
    parser.add_argument("--raw", action="store_true", help="Stream output (default)")
    parser.add_argument("--search", action="store_true", help="Perform web search to enrich context")
    parser.add_argument("--deep", action="store_true", help="Deep dive into the top search result")
    parser.add_argument("--shell", action="store_true", help="Write and run a shell command")
    parser.add_argument("--python", action="store_true", help="Write and run Python code")
    parser.add_argument("--install-project", action="store_true", help="Install a Python project into the elf's venv")
    parser.add_argument("--recall", type=int, help="Recall last N coding adventures (short-term)")
    parser.add_argument("--recall-type", type=str, choices=["0", "1", "both"], default="both", help="Recall only successes (1), failures (0), or both")
    parser.add_argument("--long-term", type=int, help="Recall N best matches from long-term memory")
    parser.add_argument("--summarize", action="store_true", help="Summarize the output of a shell command")
    parser.add_argument("--voice", action="store_true", help="Speak the response aloud")

    # Archive / RAG
    parser.add_argument("--archive", nargs="+", help="Archive ops: crawl [dir|file], find <query>, list, delete, overwrite")
    parser.add_argument("--dir", type=Path, help="Target directory or file for archive operations")

    args = parser.parse_args()

    print(f"{GREEN}\U0001f464 You: {args.message}{RESET}")

    elf = Elf(model=args.model or "gpt-4.1-mini")
    style = getattr(elf, "text_color", "cyan")

    # ----- Shell Mode -----
    if args.shell or args.python:
        memory_reflection = elf.recall_memory(
            n=args.recall or 0,
            result_type=args.recall_type,
            long_term_n=args.long_term or 0
        ) if (args.recall or args.long_term) else ""

        system_prompt = (
            f"You are {Elf.__name__}, who recalls past adventures with clarity.\n\n"
            f"{memory_reflection}\n\n"
            "Now, based on this history, generate the best new solution."
        ) if memory_reflection else None

    if args.shell:
        command_gen_prompt = [
            {"role": "system", "content": system_prompt or "Convert the user's request into a single-line bash command. No explanations. Only the command."},
            {"role": "user", "content": args.message}
        ]
        completion = elf.client.chat.completions.create(model=elf.model, messages=command_gen_prompt)
        raw_command = completion.choices[0].message.content.strip()
        parsed_command = RunShellTool.extract_code(raw_command)
        console.print(f"\U0001f9e0 {Elf.__name__} thinks:\n{parsed_command}", style=style)

        result, success = elf.tools.run("run_shell_command", parsed_command, return_success=True)
        console.print(f"\U0001f4a5 {Elf.__name__} runs:\n{result}", style=style)

        if args.summarize:
            summary = elf.summarize_text(result)
            console.print(f"\U0001f4dc Summary:\n{summary}", style=style)
            if args.voice:
                elf.tools.run("speak_text", summary)

        if not args.secret:
            elf.save_coding_adventure(args.message, parsed_command, result, "shell", success)
        return

    # ----- Python Mode -----
    if args.python:
        code_gen_prompt = [
            {"role": "system", "content": system_prompt or "Convert the user's request into a single Python script. No explanations. Only the code."},
            {"role": "user", "content": args.message}
        ]
        completion = elf.client.chat.completions.create(model=elf.model, messages=code_gen_prompt)
        raw_code = completion.choices[0].message.content.strip()
        parsed_code = RunPythonTool.extract_code(raw_code)
        console.print(f"\U0001f9e0 {Elf.__name__} writes:\n{parsed_code}", style=style)

        result, success = elf.tools.run("run_python_code", parsed_code, elf=elf, return_success=True)
        console.print(f"\U0001f4a5 {Elf.__name__} executes:\n{result}", style=style)

        if not args.secret:
            elf.save_coding_adventure(args.message, parsed_code, result, "python", success)
        return

    # ----- Project Install -----
    if args.install_project:
        result = elf.tools.run("install_project")
        console.print(f"\U0001f4e6 Install Result:\n{result}", style=style)
        return

    # ----- Conversation Reset / Purge -----
    if args.empty:
        elf.reset_history()

    if args.purge:
        elf.purge_memory()
        console.print(f"\U0001f9f9 {Elf.__name__} forgets everything in the long-term...", style=style)

    # ----- Archive / RAG -----
    if args.archive:
        subcmd = args.archive[0]
        query = " ".join(args.archive[1:]) if len(args.archive) > 1 else args.message
        hits = []

        if subcmd == "crawl":
            if args.dir and args.dir.is_file():
                elf.memory.crawl_file(args.dir)
                hits = elf.memory.search_rag(query, dir_filter=str(args.dir))
            else:
                elf.memory.crawl_dir(args.dir or Path("."))
                hits = elf.memory.search_rag(query, dir_filter=str(args.dir) if args.dir else None)
        elif subcmd == "find":
            hits = elf.memory.search_rag(query, dir_filter=str(args.dir) if args.dir else None)
        elif subcmd == "list":
            with sqlite3.connect(elf.memory.db_path) as con:
                rows = con.execute("SELECT DISTINCT dir FROM rag_chunks").fetchall()
                hits = [{"dir": r[0]} for r in rows]
        elif subcmd == "delete":
            if not args.dir:
                console.print("❌ --dir must be specified for delete", style="red")
            else:
                elf.memory.delete_rag(args.dir)
                console.print(f"🗑️ Deleted RAG entries for {args.dir}", style="yellow")

        elif subcmd == "overwrite":
            if not args.dir:
                console.print("❌ --dir must be specified for overwrite", style="red")
            else:
                added = elf.memory.overwrite_rag(args.dir)
                console.print(f"♻️ Overwrote {len(added)} chunks for {args.dir}", style="yellow")

        elif subcmd == "status":
            status = elf.memory.rag_status()
            if not status:
                console.print("📂 Archive is empty.", style="yellow")
            else:
                for d, files in status.items():
                    console.print(f"📁 {d}", style="cyan")
                    for f in files:
                        console.print(f"   📄 {Path(f['file']).name} ({f['chunks']} chunks)", style="green")

        if hits:
            context = "\n\n".join(
                [f"[{h.get('file', h.get('dir'))}] {h.get('content','')}" for h in hits]
            )
            elf.history.append({"role": "system", "content": f"📚 Archive recalls:\n{context}"})
            console.print(f"📚 Injected {len(hits)} archive hits", style=style)

    # ----- Memory & Web Search -----
    elf.enrich_with_memory(args.message)

    if args.search:
        elf.enrich_with_search(args.message, deep=args.deep)
        console.print(f"\U0001f50e {Elf.__name__} searches the websies…", style=style)

    # ----- Chat -----
    try:
        if args.md:
            reply = elf.chat(args.message)
            console.print(Markdown(f"\U0001f9dd **{Elf.__name__}:** {reply}"), style=style)
            if args.voice:
                elf.tools.run("speak_text", strip_markdown(reply))
        else:
            stream = elf.chat(args.message, stream=True)
            console.print(f"\U0001f9dd {Elf.__name__}: ", style=style, end="")
            reply = ""
            for chunk in stream:
                delta = chunk.choices[0].delta
                if delta.content:
                    reply += delta.content
                    console.print(delta.content, style=style, end="")
            print()
            if args.voice:
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
