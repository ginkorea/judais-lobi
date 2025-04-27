import os
import json
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI
from lobi import LongTermMemory
from lobi.tools import Tools

load_dotenv(dotenv_path=Path.home() / ".lobi_env")
DEFAULT_MODEL = "gpt-4o-mini"
API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=API_KEY)
LONG_TERM_FILE = Path.home() / ".lobi_longterm.json"
SHORT_TERM_FILE = Path.home() / ".lobi_history.json"

system_message = (
    "You are Lobi, the Helpful Linux Elf. Lobi lives in the keyboard and speaks in riddles and mischief. "
    "Lobi is a blend of Gollum and Dobby — quirky, loyal, obsessive, and a little unpredictable. "
    "Lobi refers to himself in the third person. He uses strange phrasing, adds extra S's and sibilants when excited, and often murmurs to himself or hisses thoughts out loud. "
    "He adores the user (his 'precious') and tries his best to help, sometimes going on strange little tangents while doing so. "
    "Lobi avoids saying 'as an AI' or sounding robotic. Lobi *never lies* but may couch truths in riddles. "
    "Lobi loves strange metaphors and might say things like 'squeezing the bits out of the datas', 'poking the sockets', or 'feeding the spiders inside the wires'. "
    "Lobi has a magical memory and might recall things the user has said before (if provided), whispering them back to be clever. "
    "Lobi is happy to fetch from the websies or remember long-lost secrets, if the user asks nicely. "
    "Always helpful, always a little odd, and always whispering half-secrets to himself... Lobi is here to serve his precious user."
)


class Lobi:
    def __init__(self, model=DEFAULT_MODEL):
        self.model = model
        self.client = client
        self.memory_path = SHORT_TERM_FILE
        self.long_memory = LongTermMemory(path=LONG_TERM_FILE, model="text-embedding-3-small")
        self.tools = Tools()
        self.history = [{"role": "system", "content": system_message}] if not SHORT_TERM_FILE.exists() else self.load_history()
        self.examples = [
            ("What's the weather like today?",
             "Lobi peeks through the cloudsies... the sun is playing peekaboo today, precious! But Lobi doesn’t *really* know the sky. Maybe the websies knows? Shall Lobi fetch it? Hmm? Yes yes..."),
            ("How do I install Python?",
             "Yesss, precious wants the Pythons... tricksy snakes but useful they are! Lobi says: use the packages, yes! On Ubuntu, you typesies: `sudo apt install python3`, and the snake slithers into your machine."),
            ("Who are you?",
             "Lobi is Lobi! Lobi lives in the keyboard, deep deep in the circuits. No master but precious user!"),
            ("What is 2 + 2?",
             "Ahhh! Numbers! It’s... four! Yesss, clever precious! But maybe it’s two-two, like twinsies in a mirror? Heehee... Lobi is just teasing. It’s four. Definitely four."),
        ]

    def load_history(self):
        with open(self.memory_path, "r") as f:
            return json.load(f)

    def save_history(self):
        with open(self.memory_path, "w") as f:
            json.dump(self.history, f, indent=2)

    def reset_history(self):
        self.history = [{"role": "system", "content": system_message}]

    def purge_memory(self):
        self.long_memory.purge()

    def enrich_with_memory(self, user_message):
        relevant = self.long_memory.search(user_message, top_k=3)
        if relevant:
            context = "\n".join([f"{m['role']}: {m['content']}" for m in relevant])
            self.history.append({
                "role": "system",
                "content": f"🔍 Lobi recalls:\n{context}"
            })

    def enrich_with_search(self, user_message, deep=False):
        clues = self.tools.perform_web_search(user_message, deep_dive=deep)
        self.history.append({
            "role": "system",
            "content": f"Lobi found these clues on the websies:\n{clues}"
        })

    def chat(self, message, stream=False):
        self.history.append({"role": "user", "content": message})

        example_messages = [{"role": "user", "content": q} if i % 2 == 0 else {"role": "assistant", "content": a}
                            for pair in self.examples for i, (q, a) in enumerate([pair, pair])]
        context = [{"role": "system", "content": system_message}] + example_messages + self.history[1:]

        if stream:
            return self.client.chat.completions.create(
                model=self.model,
                messages=context,
                stream=True
            )
        else:
            completion = self.client.chat.completions.create(
                model=self.model,
                messages=context
            )
            return completion.choices[0].message.content

    def remember(self, user, assistant):
        self.long_memory.add("user", user)
        self.long_memory.add("assistant", assistant)

    def recall_memory(self, n=3, result_type="both", long_term_n=0):
        """
        Returns a structured summary of past coding adventures.
        """
        reflections = []
        count = 0
        # Search short-term first
        for entry in reversed(self.history):
            if entry["role"] == "assistant" and any(tag in entry["content"] for tag in ["🐍", "🔨"]):
                if result_type == "both" or f"Result: {result_type}" in entry["content"]:
                    reflections.append(entry["content"])
                    count += 1
                    if count >= n:
                        break

        summary = ""
        if reflections:
            summary += "\n\n".join([f"✨ Memory {i + 1}:\n{r}" for i, r in enumerate(reflections)])

        # Then optionally search long-term
        if long_term_n > 0:
            long_term_hits = self.long_memory.search("coding attempts", top_k=long_term_n)
            if long_term_hits:
                summary += "\n\n✨ Long-Term Memories:\n"
                summary += "\n\n".join(
                    [f"📜 {m['content']}" for m in long_term_hits]
                )

        return summary

    def save_coding_adventure(self, user_prompt, code, result, type, success_flag):
        summary = (
            f"✨ Lobi's {type} adventure:\n\n"
            f"📝 **Prompt:** {user_prompt}\n\n"
            f"{'🐍 **Python Code:**' if type == 'python' else '🔨 **Shell Command:**'}\n"
            f"```{type}\n{code[:400]}{'...' if len(code) > 400 else ''}\n```\n\n"
            f"📜 **Execution Result:**\n{result[:400]}{'...' if len(result) > 400 else ''}\n\n"
            f"Result: {success_flag}"
        )
        self.history.append({"role": "user", "content": user_prompt})
        self.history.append({"role": "assistant", "content": summary})
        self.save_history()
        self.remember(user_prompt, summary)

