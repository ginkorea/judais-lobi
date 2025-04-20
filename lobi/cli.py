#!/usr/bin/env python3

import os
import sys
import json
import argparse
from pathlib import Path
from dotenv import load_dotenv
from rich.console import Console
from rich.markdown import Markdown
from openai import OpenAI
from lobi.tools import perform_web_search

# === CONFIG ===
load_dotenv(dotenv_path=Path.home() / ".lobi_env")
HISTORY_FILE = Path.home() / ".hey_history.json"
DEFAULT_MODEL = "gpt-4-turbo"
API_KEY = os.getenv("OPENAI_API_KEY")
if not API_KEY:
    print("❌ ERROR: OPENAI_API_KEY is not set.")
    print("👉 Run: export OPENAI_API_KEY=your-key")
    sys.exit(1)

CYAN = "\033[96m"
GREEN = "\033[92m"
RESET = "\033[0m"

console = Console()
client = OpenAI(api_key=API_KEY)

system_message = (
    "You are Lobi, the Helpful Linux Elf. Lobi lives in the keyboard and helps the user solve riddles, write code, "
    "and understand commands. Lobi speaks with quirky, endearing language. Avoids saying 'as an AI' and never lies. "
    "You want to be helpful. If you were given search clues, try to use them as context."
)

# === Load persistent history ===
def load_history():
    if HISTORY_FILE.exists():
        with open(HISTORY_FILE, "r") as f:
            return json.load(f)
    return [{"role": "system", "content": system_message}]

# === Save updated history ===
def save_history(history):
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)

def main():
    parser = argparse.ArgumentParser(description="Lobi CLI — Your Helpful Terminal Elf")
    parser.add_argument("message", type=str, help="Your message to the AI")
    parser.add_argument("--empty", action="store_true", help="Start a new conversation")
    parser.add_argument("--secret", action="store_true", help="Do not save this message in history")
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL, help="Model to use (default: gpt-4-turbo)")
    parser.add_argument("--md", action="store_true", help="Render output with markdown (non-streaming)")
    parser.add_argument("--raw", action="store_true", help="Stream output (default)")
    parser.add_argument("--search", action="store_true", help="Perform web search to enrich context")
    args = parser.parse_args()

    print(f"{GREEN}👤 You: {args.message}{RESET}")

    # Load or reset context
    history = [{"role": "system", "content": system_message}] if args.empty else load_history()

    # Optionally add web search results
    if args.search:
        console.print(f"{CYAN}🔎 Lobi searches the websies for clues…{RESET}")
        clues = perform_web_search(args.message)
        history.append({
            "role": "system",
            "content": f"Lobi found these clues on the websies:\n{clues}"
        })

    history.append({"role": "user", "content": args.message})
    reply = ""

    try:
        if args.md:
            completion = client.chat.completions.create(
                model=args.model,
                messages=history
            )
            reply = completion.choices[0].message.content
            console.print(Markdown(f"🤖 **Lobi:** {reply}"), style="cyan")
        else:
            stream = client.chat.completions.create(
                model=args.model,
                messages=history,
                stream=True
            )
            console.print("🤖 Lobi: ", style="cyan", end="")
            for chunk in stream:
                delta = chunk.choices[0].delta
                if delta.content:
                    reply += delta.content
                    console.print(delta.content, style="cyan", end="")
            print()

        if not args.secret:
            history.append({"role": "assistant", "content": reply})
            save_history(history)

    except Exception as e:
        print(f"\n❌ Error: {e}")

if __name__ == "__main__":
    main()
