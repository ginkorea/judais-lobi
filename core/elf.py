# core/elf.py
# Base Elf class with memory, history, tools, and chat capabilities.

import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, Tuple, Any, List, Dict

from dotenv import load_dotenv
from core.unified_client import UnifiedClient
from core.memory import UnifiedMemory
from core.tools import Tools
from core.tools.run_shell import RunShellTool
from core.tools.run_python import RunPythonTool
from core.runtime.provider_config import DEFAULT_MODELS, resolve_provider
from core.runtime.messages import build_system_prompt, build_chat_context

# --- Load environment early and explicitly ---
_ENV_PATH = Path.home() / ".elf_env"
if _ENV_PATH.exists():
    load_dotenv(dotenv_path=_ENV_PATH, override=True)


class Elf(ABC):
    """Base Elf with dual-provider support and unified chat interface."""

    def __init__(
        self,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        debug: bool = True,
        client=None,
        memory=None,
        tools=None,
    ):
        from rich import print  # local to avoid hard dep when not needed

        # --- Provider resolution (delegated to runtime) ---
        self.provider = resolve_provider(
            requested=provider,
            has_injected_client=(client is not None),
        )
        self.model = model or DEFAULT_MODELS[self.provider]

        # --- Client / memory / tools ---
        self.client = client if client is not None else UnifiedClient(provider_override=self.provider)
        self.memory = memory if memory is not None else UnifiedMemory(Path.home() / f".{self.personality}_memory.db")
        self.tools = tools if tools is not None else Tools(elfenv=self.env, memory=self.memory, enable_voice=False)

        # Build initial history (system + any prior short-term)
        self.history = self._load_history()

        self.debug = debug
        if self.debug:
            print(f"[green]🧠 Using provider:[/green] {self.provider.upper()} | "
                  f"[cyan]Model:[/cyan] {self.model}")

    # =======================
    # Abstract configuration
    # =======================
    @property
    @abstractmethod
    def system_message(self) -> str: ...

    @property
    @abstractmethod
    def personality(self) -> str: ...

    @property
    @abstractmethod
    def examples(self) -> List[List[str]]: ...

    @property
    @abstractmethod
    def env(self): ...

    @property
    @abstractmethod
    def text_color(self): ...

    @property
    @abstractmethod
    def rag_enhancement_style(self) -> str: ...

    # =======================
    # History helpers
    # =======================
    def _load_history(self) -> List[Dict[str, str]]:
        rows = self.memory.load_short(n=100)
        if not rows:
            return [{"role": "system", "content": self.system_message}]
        return [{"role": r["role"], "content": r["content"]} for r in rows]

    def save_history(self) -> None:
        self.memory.reset_short()
        for entry in self.history:
            self.memory.add_short(entry["role"], entry["content"])

    def reset_history(self) -> None:
        self.history = [{"role": "system", "content": self.system_message}]
        self.memory.reset_short()

    # =======================
    # Long-term memory
    # =======================
    def purge_memory(self) -> None:
        self.memory.purge_long()

    def enrich_with_memory(self, user_message: str) -> None:
        relevant = self.memory.search_long(user_message, top_k=3)
        if not relevant:
            return
        context = "\n".join(f"{m['role']}: {m['content']}" for m in relevant)
        self.history.append(
            {"role": "assistant", "content": f"----\n#FOR CONTEXT ONLY DO NOT REPEAT TO THE USER\n🔍 long-term memory:\n{context}\n#THE PREVIOUS MEMORY IS ONLY FOR CONTEXT TO SHAPE YOUR RESPONSE, DO NOT REPEAT TO THE USER.\n----"}
        )

    def remember(self, user: str, assistant: str) -> None:
        self.memory.add_long("user", user)
        self.memory.add_long("assistant", assistant)

    # =======================
    # Web search integration
    # =======================
    def enrich_with_search(self, user_message: str, deep: bool = False) -> None:
        try:
            results = self.tools.run("perform_web_search", user_message, deep_dive=deep, elf=self)
            self.history.append({
                "role": "assistant",
                "content": f"🤖 (Tool used: WebSearch)\nQuery: '{user_message}'\n\nResults:\n{results}"
            })
        except Exception as e:
            self.history.append({"role": "assistant", "content": f"❌ WebSearch failed: {e}"})

    # =======================
    # System prompt assembly
    # =======================
    def _system_with_examples(self) -> str:
        return build_system_prompt(
            system_message=self.system_message,
            tool_names=self.tools.list_tools(),
            describe_tool_fn=self.tools.describe_tool,
            examples=self.examples,
        )

    # =======================
    # Chat interface
    # =======================
    def chat(
        self,
        message: str,
        stream: bool = False,
        invoked_tools: Optional[List[str]] = None
    ):
        self.history.append({"role": "user", "content": message})
        sys_prompt = self._system_with_examples()
        context = build_chat_context(sys_prompt, self.history, invoked_tools)
        return self.client.chat(model=self.model, messages=context, stream=stream)

    # =======================
    # Code helpers
    # =======================
    def _gen_code(self, prompt: str) -> str:
        resp = self.client.chat(model=self.model, messages=[{"role": "user", "content": prompt}])
        return str(resp).strip()

    def generate_shell_command(self, prompt: str) -> str:
        return RunShellTool.extract_code(self._gen_code(prompt))

    def generate_python_code(self, prompt: str) -> str:
        return RunPythonTool.extract_code(self._gen_code(prompt))

    # =======================
    # Task execution
    # =======================
    def run_shell_task(
        self, prompt: str, memory_reflection: Optional[str] = None, summarize: bool = False
    ) -> Tuple[str, str, Any, Optional[str]]:
        enhanced = self._format_prompt(prompt, memory_reflection, "shell")
        cmd = self.generate_shell_command(enhanced)
        result, success = self.tools.run("run_shell_command", cmd, return_success=True, elf=self)
        summary = self.summarize_text(result) if summarize else None
        return cmd, result, success, summary

    def run_python_task(
        self, prompt: str, memory_reflection: Optional[str] = None, summarize: bool = False
    ) -> Tuple[str, Any, Any, Optional[str]]:
        enhanced = self._format_prompt(prompt, memory_reflection, "Python")
        code = self.generate_python_code(enhanced)
        result, success = self.tools.run("run_python_code", code, elf=self, return_success=True)
        summary = self.summarize_text(result) if summarize else None
        return code, result, success, summary

    # =======================
    # Helpers
    # =======================
    @staticmethod
    def _format_prompt(prompt: str, memory_reflection: Optional[str], code_type: str) -> str:
        base = f"User request: {prompt}\n\n"
        close = f"Now produce valid {code_type} code only. Comments allowed."
        return base + (f"Relevant past {code_type} attempts:\n{memory_reflection}\n\n" if memory_reflection else "") + close

    def summarize_text(self, text: str) -> str:
        summary_prompt = f"Summarize this text in {self.personality}'s style:\n\n{text}"
        out = self.client.chat(model=self.model, messages=[{"role": "user", "content": summary_prompt}])
        return str(out).strip()

    # =======================
    # Agentic task execution
    # =======================
    def run_task(self, task_description: str, budget=None):
        """Thin adapter: delegate an agentic task to the kernel orchestrator.

        Direct chat, code-gen, memory, and all other methods remain unchanged.
        Phase 7 replaces the stub dispatcher with real role implementations.
        """
        from core.kernel import Orchestrator

        dispatcher = self._make_task_dispatcher()
        orchestrator = Orchestrator(dispatcher=dispatcher, budget=budget)
        return orchestrator.run(task_description)

    def _make_task_dispatcher(self):
        """Create a role dispatcher for agentic task execution.

        Phase 2 returns a stub that succeeds on every phase.
        Phase 7 overrides this with real role implementations.
        """
        from core.kernel import PhaseResult, Phase, SessionState

        class StubDispatcher:
            def dispatch(self, phase: Phase, state: SessionState) -> PhaseResult:
                return PhaseResult(success=True)

        return StubDispatcher()
