#!/usr/bin/env python3

import argparse
from rich.console import Console
from rich.markdown import Markdown
from lobi import Lobi

CYAN = "\033[96m"
GREEN = "\033[92m"
RESET = "\033[0m"

console = Console()

def main():
    parser = argparse.ArgumentParser(description="Lobi CLI — Your Helpful Terminal Elf")
    parser.add_argument("message", type=str, help="Your message to the AI")
    parser.add_argument("--empty", action="store_true", help="Start a new conversation")
    parser.add_argument("--purge", action="store_true", help="Purge long-term memory")
    parser.add_argument("--secret", action="store_true", help="Do not save this message in history")
    parser.add_argument("--model", type=str, help="Model to use (default: gpt-4o-mini)")
    parser.add_argument("--md", action="store_true", help="Render output with markdown (non-streaming)")
    parser.add_argument("--raw", action="store_true", help="Stream output (default)")
    parser.add_argument("--search", action="store_true", help="Perform web search to enrich context")
    parser.add_argument("--deep", action="store_true", help="Deep dive into the top search result")
    parser.add_argument("--shell", action="store_true", help="Ask Lobi to write and run a shell command")
    parser.add_argument("--python", action="store_true", help="Ask Lobi to write and run Python code")
    parser.add_argument("--install-project", action="store_true", help="Install a Python project into Lobi's venv")
    parser.add_argument("--recall", type=int, help="Recall last N coding adventures (short-term)")
    parser.add_argument("--recall-type", type=str, choices=["0", "1", "both"], default="both", help="Recall only successes (1), failures (0), or both")
    parser.add_argument("--long-term", type=int, help="Recall N best matches from long-term memory")

    args = parser.parse_args()

    print(f"{GREEN}👤 You: {args.message}{RESET}")

    elf = Lobi(model=args.model or "gpt-4o-mini")

    if args.shell or args.python:
        # ✨ Before generating, build system memory
        memory_reflection = elf.recall_memory(
            n=args.recall or 0,
            result_type=args.recall_type,
            long_term_n=args.long_term or 0
        ) if (args.recall or args.long_term) else ""

        system_prompt = (
            "You are Lobi, the Helpful Linux Elf, who recalls his past adventures with clarity.\n\n"
            f"{memory_reflection}\n\n"
            "Now, based on this history, generate the best new solution."
        ) if memory_reflection else None

    if args.shell:
        command_gen_prompt = [
            {"role": "system", "content": system_prompt or "Convert the user's request into a single-line bash command. No explanations. Only the command."},
            {"role": "user", "content": args.message}
        ]
        completion = elf.client.chat.completions.create(
            model=elf.model,
            messages=command_gen_prompt
        )
        raw_command = completion.choices[0].message.content.strip()
        parsed_command = elf.tools.extract_shell_command(raw_command)
        console.print(f"{CYAN}🧠 Lobi thinks:\n{parsed_command}{RESET}")

        result, success = elf.tools.run_shell_command(parsed_command, return_success=True)
        console.print(f"{GREEN}💥 Lobi runs:\n{result}{RESET}")

        if not args.secret:
            elf.save_coding_adventure(args.message, parsed_command, result, "shell", success)

        return

    if args.python:
        code_gen_prompt = [
            {"role": "system", "content": system_prompt or "Convert the user's request into a single Python script. No explanations. Only the code."},
            {"role": "user", "content": args.message}
        ]
        completion = elf.client.chat.completions.create(
            model=elf.model,
            messages=code_gen_prompt
        )
        raw_code = completion.choices[0].message.content.strip()
        parsed_code = elf.tools.extract_python_code(raw_code)
        console.print(f"{CYAN}🧠 Lobi writes:\n{parsed_code}{RESET}")

        result, success = elf.tools.run_python_code(parsed_code, return_success=True)
        console.print(f"{GREEN}💥 Lobi executes:\n{result}{RESET}")

        if not args.secret:
            elf.save_coding_adventure(args.message, parsed_code, result, "python", success)

        return

    if args.install_project:
        console.print(f"{CYAN}🛠 Lobi prepares to install the project...{RESET}")
        result = elf.tools.install_project()
        console.print(f"{GREEN}📦 Install Result:\n{result}{RESET}")
        return

    if args.empty:
        elf.reset_history()

    if args.purge:
        console.print(f"{CYAN}🧹 Lobi forgets everything in the long-term...{RESET}")
        elf.purge_memory()

    elf.enrich_with_memory(args.message)

    if args.search:
        console.print(f"{CYAN}🔎 Lobi searches the websies for clues…{RESET}")
        elf.enrich_with_search(args.message, deep=args.deep)

    try:
        if args.md:
            reply = elf.chat(args.message)
            console.print(Markdown(f"🧝 **Lobi:** {reply}"), style="cyan")
        else:
            stream = elf.chat(args.message, stream=True)
            console.print("🧝 Lobi: ", style="cyan", end="")
            reply = ""
            for chunk in stream:
                delta = chunk.choices[0].delta
                if delta.content:
                    reply += delta.content
                    console.print(delta.content, style="cyan", end="")
            print()

        if not args.secret:
            elf.history.append({"role": "assistant", "content": reply})
            elf.save_history()
            elf.remember(args.message, reply)

    except Exception as e:
        print(f"\n❌ Error: {e}")

if __name__ == "__main__":
    main()
