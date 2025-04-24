#!/usr/bin/env python3

import sys
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
    args = parser.parse_args()

    print(f"{GREEN}👤 You: {args.message}{RESET}")

    elf = Lobi(model=args.model or "gpt-4o-mini")

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
