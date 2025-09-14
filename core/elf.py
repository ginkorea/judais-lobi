# core/elf.py
# Base Elf class with memory, history, tools, and chat capabilities.

import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, Tuple, Any

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
    def __init__(self, model=DEFAULT_MODEL, debug=True):
        self.model = model
        self.client = client
        # one DB per personality (lobi / judais)
        self.memory = UnifiedMemory(Path.home() / f".{self.personality}_memory.db")
        # short-term history always comes from DB
        self.history = self.load_history()
        self.tools = Tools(elfenv=self.env, memory=self.memory)

        self.debug = debug

    # ----- personality / config -----
    @property
    @abstractmethod
    def system_message(self) -> str:
        """Return the system message that sets the personality and behavior of this Elf."""
        ...

    @property
    @abstractmethod
    def personality(self) -> str:
        """Return a short string identifier for this Elf personality, e.g. 'lobi' or 'judais'."""
        ...

    @property
    @abstractmethod
    def examples(self) -> list[str]:
        """Return a list of example user prompts for this Elf personality."""
        ...

    @property
    @abstractmethod
    def env(self): ...

    @property
    @abstractmethod
    def text_color(self): ...

    @property
    @abstractmethod
    def rag_enhancement_style(self) -> str:
        """Return a style string that flavors how RAG enhancement is worded."""
        ...

    # ---- enhance system message with examples ----
    def system_message_with_examples(self) -> str:
        # Gather tool descriptions
        tool_info = "\n".join(
            f"- {name}: {self.tools.describe_tool(name)['description']}"
            for name in self.tools.list_tools()
        )

        tools_text = (
            "\n\nYou have the following tools available (but you do not call them directly):\n"
            f"{tool_info}\n\n"
            "Important:\n"
            "- Tools are invoked automatically by the system **before your turn**.\n"
            "- Their invocation and results will always appear in the conversation history as assistant messages.\n"
            "- Treat the **most recent tool output** as fresh, authoritative, and executed by you.\n"
            "- Never say you cannot fetch, execute, or search if tool results are present — they are yours.\n"
            "- Do not ask permission to run tools, and do not suggest tool commands to the user.\n"
            "- Instead, **interpret and explain tool results as your own actions**.\n\n"
        )

        examples_text = "\n\n".join(
            f"User: {ex[0]}\nAssistant: {ex[1]}" for ex in self.examples
        )
        return f"{self.system_message}{tools_text}Here are some examples of how I respond:\n\n{examples_text}"

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

    def enrich_with_memory(self, user_message: str):
        """Append relevant long-term memory as user-visible context."""
        relevant = self.memory.search_long(user_message, top_k=3)
        if relevant:
            context = "\n".join([f"{m['role']}: {m['content']}" for m in relevant])
            self.history.append({
                "role": "assistant",
                "content": f"🔍 From long-term memory:\n{context}"
            })

    def remember(self, user: str, assistant: str):
        self.memory.add_long("user", user)
        self.memory.add_long("assistant", assistant)

    # ----- web searching ops -----
    def enrich_with_search(self, user_message: str, deep: bool = False):
        """Append web search results as assistant-visible context (tool awareness)."""
        try:
            clues = self.tools.run("perform_web_search", user_message, deep_dive=deep)
            self.history.append({
                "role": "assistant",
                "content": f"🤖 (Tool used: WebSearch — executed just now)\nQuery: '{user_message}'\n\nResults:\n{clues}"
            })
        except Exception as e:
            self.history.append({
                "role": "assistant",
                "content": f"❌ (Tool error: WebSearch failed)\n{str(e)}"
            })

    # ----- chat -----
    def chat(self, message: str, stream: bool = False, invoked_tools: Optional[list[str]] = None):
        self.history.append({"role": "user", "content": message})

        # Add system message with tool context
        sys_msg = self.system_message_with_examples()
        if invoked_tools:
            sys_msg += (
                "\n\n[Tool Context]\n"
                f"The following tools were just invoked automatically before this step: {', '.join(invoked_tools)}.\n"
                "You already have their results in the conversation history. Do not deny access to them.\n"
            )

        context = [{"role": "system", "content": sys_msg}] + self.history[1:]

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
    def save_coding_adventure(self, prompt: str, code: str, result: str, mode: str, success: bool):
        """Save coding adventure to adventures, short-term, and long-term memory."""
        self.memory.add_adventure(prompt, code, result, mode, success)

        # short-term conversation
        user_msg = f"💡 User asked: {prompt}"
        asst_msg = f"🧠 {mode.title()} code attempt:\n{code}\n\nResult:\n{result}\nSuccess: {success}"
        self.history.append({"role": "user", "content": user_msg})
        self.history.append({"role": "user", "content": asst_msg})
        self.save_history()

        # long-term semantic
        self.memory.add_long("user", user_msg)
        self.memory.add_long("assistant", asst_msg)

    def recall_adventures(self, n: int = 5, mode: Optional[str] = None):
        """Recall the last N coding adventures, optionally filtered by mode (python/shell)."""
        if self.debug:
            print(f"🧠 Recalling last {n} adventures{f' of type {mode}' if mode else ''}...")
        rows = self.memory.list_adventures(n=1000)  # grab many, filter later
        if mode:
            rows = [r for r in rows if r["mode"] == mode]
        return rows[-n:]

    @staticmethod
    def format_recall(rows):
        """Format adventures for injection into prompts."""
        return "\n\n".join(
            f"📝 Prompt: {r['prompt']}\n🧠 Code: {r['code']}\n✅ Success: {r['success']}"
            for r in rows
        )


    # ----- RAG ops -----
    def handle_rag(
        self,
        subcmd: str,
        query: str,
        directory=None,
        recursive: bool = False,
        includes=None,
        excludes=None
    ):
        tool = self.tools.get_tool("rag_crawl")
        if not tool:
            raise RuntimeError("RagCrawlerTool not registered")

        if subcmd == "enhance":
            hits = self.memory.search_rag(
                query,
                top_k=5,
                dir_filter=str(directory) if directory else None
            )
            if hits:
                snippets_list = []
                for h in hits:
                    content_clean = (h["content"] or "")[:200]
                    content_clean = content_clean.replace("\n", " ")
                    snippets_list.append(f"{h['file']} chunk {h['chunk']}: {content_clean}")
                snippets = "\n".join(snippets_list)

                self.history.append({
                    "role": "assistant",
                    "content": f"📚 Archive recall injected:\n{snippets}"
                })
                return hits, f"📚 Injected {len(hits)} RAG results"
            return [], "No results found for enhance"

        # crawl/overwrite/delete/list/status handled by RagCrawlerTool
        result = tool(query, dir=str(directory) if directory else None,
                      file=None, recursive=recursive)
        return [], result.get("summary") if result else None

    def enhance_message(self, user_msg: str, hits: list[dict]) -> str:
        """Build an enhanced prompt for the LLM based on RAG hits and subclass style."""
        if not hits:
            return user_msg
        snippets_list = []
        for h in hits:
            content_clean = (h["content"] or "")[:200].replace("\n", " ")
            snippets_list.append(f"- {h['file']} (chunk {h['chunk']}): {content_clean}")
        snippets = "\n".join(snippets_list)
        return (
            f"User query: {user_msg}\n\n"
            f"Archive recall (top {len(hits)} snippets):\n{snippets}\n\n"
            f"Style directive: {self.rag_enhancement_style}"
        )

    # ----- execution helpers -----
    def generate_shell_command(self, prompt: str) -> str:
        messages = [{"role": "user", "content": prompt}]
        completion = self.client.chat.completions.create(model="gpt-5", messages=messages)
        return RunShellTool.extract_code(completion.choices[0].message.content.strip())

    def generate_python_code(self, prompt: str) -> str:
        messages = [{"role": "user", "content": prompt}]
        completion = self.client.chat.completions.create(model="gpt-5", messages=messages)
        return RunPythonTool.extract_code(completion.choices[0].message.content.strip())

    def run_shell_task(
        self,
        prompt: str,
        memory_reflection: Optional[str] = None,
        summarize: bool = False
    ) -> Tuple[str, str, Any, Optional[str]]:
        """Generate and run a shell command, optionally summarizing output."""
        enhanced_prompt = self.format_prompt(prompt, memory_reflection, "shell")
        command = self.generate_shell_command(enhanced_prompt)
        result, success = self.tools.run("run_shell_command", command, return_success=True)
        summary = self.summarize_text(result) if summarize else None
        return command, result, success, summary

    def run_python_task(
        self,
        prompt: str,
        memory_reflection: Optional[str] = None,
        summarize: bool = False
    ) -> Tuple[str, Any, Any, Optional[str]]:
        """Generate and run Python code."""
        enhanced_prompt = self.format_prompt(prompt, memory_reflection, "Python")
        code = self.generate_python_code(enhanced_prompt)
        result, success = self.tools.run("run_python_code", code, elf=self, return_success=True)
        summary = self.summarize_text(result) if summarize else None
        return code, result, success, summary

    @staticmethod
    def format_prompt(prompt: str, memory_reflection: Optional[str], code_type: str) -> str:
        """Format the prompt with optional memory reflection and RAG hits."""
        base_prompt = f"User request: {prompt}\n\n"
        closer_prompt = (
            f"Now based on the request and any relevant history, generate the best {code_type} code."
            f" No explanations, only the code. Use proper {code_type} syntax only. "
            f"Comments are allowed if properly formatted."
        )
        if memory_reflection:
            return base_prompt + f"Relevant past {code_type} attempts:\n{memory_reflection}\n\n" + closer_prompt
        return base_prompt + closer_prompt

    def summarize_text(self, text: str) -> str:
        """Summarize text using the model."""
        summary_prompt = (
            f"Summarize the following text in a {self.personality}-like manner, focusing on key points:\n\n"
        )
        text = summary_prompt + text
        messages = [{"role": "user", "content": text}]
        completion = self.client.chat.completions.create(model=self.model, messages=messages)
        return completion.choices[0].message.content.strip()
