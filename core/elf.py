# core/elf.py

import os
import json
from abc import ABC, abstractmethod
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
from openai import OpenAI
from core.memory import LongTermMemory
from core.tools import Tools

load_dotenv(dotenv_path=Path.home() / ".elf_env")
DEFAULT_MODEL = "gpt-4o-mini"
API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=API_KEY)

class Elf(ABC):
    def __init__(self, short_term_file, long_term_file, model=DEFAULT_MODEL):
        self.model = model
        self.client = client
        self.memory_path = short_term_file
        self.long_memory = LongTermMemory(path=long_term_file, model="text-embedding-3-small")
        self.history = [{"role": "system", "content": self.system_message}] if not short_term_file.exists() else self.load_history()
        self.tools = Tools(elfenv=self.env)

    @property
    @abstractmethod
    def system_message(self) -> str:
        pass

    @property
    @abstractmethod
    def personality(self) -> str:
        pass

    @property
    @abstractmethod
    def env(self):
        pass

    @property
    @abstractmethod
    def text_color(self):
        pass

    def load_history(self):
        with open(self.memory_path, "r") as f:
            return json.load(f)

    def save_history(self):
        with open(self.memory_path, "w") as f:
            json.dump(self.history, f, indent=2)

    def reset_history(self):
        self.history = [{"role": "system", "content": self.system_message}]

    def purge_memory(self):
        self.long_memory.purge()

    def enrich_with_memory(self, user_message):
        relevant = self.long_memory.search(user_message, top_k=3)
        if relevant:
            context = "\n".join([f"{m['role']}: {m['content']}" for m in relevant])
            self.history.append({
                "role": "system",
                "content": f"🔍 Memory recalls:\n{context}"
            })

    def enrich_with_search(self, user_message, deep=False):
        try:
            clues = self.tools.run("perform_web_search", user_message, deep_dive=deep)
            self.history.append({
                "role": "system",
                "content": f"🌐 Web search returned clues:\n{clues}"
            })
        except Exception as e:
            self.history.append({
                "role": "system",
                "content": f"❌ Web search failed: {str(e)}"
            })

    def chat(self, message, stream=False):
        self.history.append({"role": "user", "content": message})
        context = [{"role": "system", "content": self.system_message}] + self.history[1:]

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

    def save_coding_adventure(self, prompt, code, result, mode, success):
        log_entry = {
            "prompt": prompt,
            "code": code,
            "result": result,
            "mode": mode,
            "success": bool(success),
            "timestamp": datetime.now().isoformat()
        }
        log_file = self.memory_path.with_suffix(".adventures.json")
        history = []
        if log_file.exists():
            with open(log_file, "r") as f:
                try:
                    history = json.load(f)
                except json.JSONDecodeError:
                    history = []
        history.append(log_entry)
        history = history[-100:]  # keep latest 100 entries
        with open(log_file, "w") as f:
            json.dump(history, f, indent=2)

    def recall_adventures(self, n=5, result_type="both"):
        log_file = self.memory_path.with_suffix(".adventures.json")
        if not log_file.exists():
            return []
        with open(log_file, "r") as f:
            try:
                history = json.load(f)
            except json.JSONDecodeError:
                return []
        if result_type == "1":
            history = [h for h in history if h["success"]]
        elif result_type == "0":
            history = [h for h in history if not h["success"]]
        return history[-n:]

    def recall_memory(self, n=5, result_type="both", long_term_n=0):
        reflections = self.recall_adventures(n=n, result_type=result_type)
        if not reflections:
            return ""
        return "\n\n".join(
            f"📝 Prompt: {r['prompt']}\n🧠 Code: {r['code']}\n✅ Result: {r['success']}" for r in reflections
        )
