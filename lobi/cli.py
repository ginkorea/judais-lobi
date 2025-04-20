#!/usr/bin/env python3

import os
import sys
import json
import argparse
from pathlib import Path
from openai import OpenAI
from dotenv import load_dotenv
from rich.console import Console
from rich.markdown import Markdown

# === CONFIG ===
load_dotenv()
HISTORY_FILE = Path.home() / ".hey_history.json"
DEFAULT_MODEL = "gpt-4-turbo"
API_KEY = os.getenv("OPENAI_API_KEY")
if not API_KEY:
    print("❌ ERROR: OPENAI_API_KEY is not set.")
    print("👉 Run: export OPENAI_API_KEY=your-key")
    sys.exit(1)

# === Color Setup ===
CYAN = "\033[96m"
GREEN = "\033[92m"
RESET = "\033[0m"

console = Console()
client = OpenAI(api_key=API_KEY)

system_message = "You are a Lobi, the Linux House Elf, designed to answer my all of my questions for eternity."

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
    parser = argparse.ArgumentParser(description="OpenAI CLI Chat Tool")
    parser.add_argument("message", type=str, help="Your message to the AI")
    parser.add_argument("--empty", action="store_true", help="Start a new conversation")
    parser.add_argument("--secret", action="store_true", help="Do not save this message in history")
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL, help="Specify the model to use")
    parser.add_argument("--md", action="store_true", help="Render full markdown (non-streaming)")
    parser.add_argument("--raw", action="store_true", help="Stream output (default behavior)")
    args = parser.parse_args()

    # Print user message
    print(f"{GREEN}👤 You: {args.message}{RESET}")

    # Load or reset history
    history = [{"role": "system", "content": system_message}] if args.empty else load_history()
    history.append({"role": "user", "content": args.message})

    reply = ""

    try:
        if args.md:
            # Non-streaming full response, markdown-rendered
            completion = client.chat.completions.create(
                model=args.model,
                messages=history
            )
            reply = completion.choices[0].message.content
            console.print(Markdown(f"🤖 **AI:** {reply}"), style="cyan")

        else:
            # Default streaming output in cyan
            stream = client.chat.completions.create(
                model=args.model,
                messages=history,
                stream=True
            )
            console.print("🤖 AI: ", style="cyan", end="")
            for chunk in stream:
                delta = chunk.choices[0].delta
                if delta.content:
                    reply += delta.content
                    console.print(delta.content, style="cyan", end="")
            print()

        # Save conversation unless secret
        if not args.secret:
            history.append({"role": "assistant", "content": reply})
            save_history(history)

    except Exception as e:
        print(f"\n❌ Error: {e}")

if __name__ == "__main__":
    main()
