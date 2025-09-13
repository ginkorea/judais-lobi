# core/elf.py
# Base Elf class with memory, history, tools, and chat capabilities.

import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI
from core.memory import UnifiedMemory
from core.tools import Tools
from core.tools.run_shell import RunShellTool
from core.tools.run_python import RunPythonTool

load_dotenv(dotenv_path=Path.home() / ".elf_env")
DEFAULT_MODEL = "gpt-5-mini"
API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=API_KEY)


class Elf(ABC):
    def __init__(self, model=DEFAULT_MODEL):
        self.model = model
        self.client = client
        # one DB per personality (lobi / judais)
        self.memory = UnifiedMemory(Path.home() / f".{self.personality}_memory.db")
        # short-term history always comes from DB
        self.history = self.load_history()
        self.tools = Tools(elfenv=self.env)

    # ----- personality / config -----
    @property
    @abstractmethod
    def system_message(self) -> str: ...

    @property
    @abstractmethod
    def personality(self) -> str: ...

    @property
    @abstractmethod
    def env(self): ...

    @property
    @abstractmethod
    def text_color(self): ...

    # ----- short-term history -----
    def load_history(self):
        rows = self.memory.load_short(n=100)
        if not rows:
            return [{"role": "system", "content": self.system_message}]
        return [{"role": r["role"], "content": r["content"]} for r in rows]

    def save_history(self):
        self.memory.reset_short()
        for entry in self.history:
            self.memory.add_short(entry["role"], entry["content"])

    def reset_history(self):
        self.history = [{"role": "system", "content": self.system_message}]
        self.memory.reset_short()

    # ----- memory ops -----
    def purge_memory(self):
        self.memory.purge_long()

    def enrich_with_memory(self, user_message):
        relevant = self.memory.search_long(user_message, top_k=3)
        if relevant:
            context = "\n".join([f"{m['role']}: {m['content']}" for m in relevant])
            self.history.append({
                "role": "system",
                "content": f"🔍 Memory recalls:\n{context}"
            })

    def remember(self, user, assistant):
        self.memory.add_long("user", user)
        self.memory.add_long("assistant", assistant)

    # ----- web search -----
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

    # ----- chat -----
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

    # ----- adventures -----
    def save_coding_adventure(self, prompt, code, result, mode, success):
        self.memory.add_adventure(prompt, code, result, mode, success)

    def recall_adventures(self, n=5, result_type="both"):
        rows = self.memory.list_adventures(n=n)
        if result_type == "1":
            rows = [r for r in rows if r["success"]]
        elif result_type == "0":
            rows = [r for r in rows if not r["success"]]
        return rows[-n:]

    def recall_memory(self, n=5, result_type="both", long_term_n=0):
        reflections = self.recall_adventures(n=n, result_type=result_type)
        if not reflections:
            return ""
        return "\n\n".join(
            f"📝 Prompt: {r['prompt']}\n🧠 Code: {r['code']}\n✅ Result: {r['success']}"
            for r in reflections
        )

    # ----- archive memory handler -----
    def handle_archive(self, subcmd: str, query: str, directory: Optional[Path], recursive: bool = False):
        hits, msg = [], None
        if subcmd == "crawl":
            if directory and directory.is_file():
                self.memory.crawl_file(directory)
                hits = self.memory.search_rag(query, dir_filter=str(directory))
            else:
                self.memory.crawl_dir(directory or Path("."), recursive=recursive)
                hits = self.memory.search_rag(query, dir_filter=str(directory) if directory else None)

        elif subcmd == "find":
            hits = self.memory.search_rag(query, dir_filter=str(directory) if directory else None)

        elif subcmd == "list":
            import sqlite3
            with sqlite3.connect(self.memory.db_path) as con:
                rows = con.execute("SELECT DISTINCT dir FROM rag_chunks").fetchall()
                hits = [{"dir": r[0]} for r in rows]

        elif subcmd == "delete":
            if not directory:
                msg = "❌ --dir must be specified for delete"
            else:
                self.memory.delete_rag(directory)
                msg = f"🗑️ Deleted RAG entries for {directory}"

        elif subcmd == "overwrite":
            if not directory:
                msg = "❌ --dir must be specified for overwrite"
            else:
                added = self.memory.overwrite_rag(directory)
                msg = f"♻️ Overwrote {len(added)} chunks for {directory}"

        elif subcmd == "status":
            status = self.memory.rag_status()
            if not status:
                msg = "📂 Archive is empty."
            else:
                msg = status

        # inject into system prompt
        if hits:
            context = "\n\n".join([f"[{h.get('file', h.get('dir'))}] {h.get('content', '')}" for h in hits])
            self.history.append({"role": "system", "content": f"📚 Archive recalls:\n{context}"})
        return hits, msg

    # ----- execution helpers (used by CLI) -----
    def generate_shell_command(self, prompt, system_prompt=None):
        command_gen_prompt = [
            {"role": "system", "content": system_prompt or "Convert the user's request into a single-line bash command. No explanations. Only the command."},
            {"role": "user", "content": prompt}
        ]
        completion = self.client.chat.completions.create(model=self.model, messages=command_gen_prompt)
        return RunShellTool.extract_code(completion.choices[0].message.content.strip())

    def generate_python_code(self, prompt, system_prompt=None):
        code_gen_prompt = [
            {"role": "system", "content": system_prompt or "Convert the user's request into a single Python script. No explanations. Only the code."},
            {"role": "user", "content": prompt}
        ]
        completion = self.client.chat.completions.create(model=self.model, messages=code_gen_prompt)
        return RunPythonTool.extract_code(completion.choices[0].message.content.strip())
