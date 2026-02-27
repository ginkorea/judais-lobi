# core/agent.py
# Concrete Agent class. PersonalityConfig replaces Elf's abstract properties.

import os
from pathlib import Path
from typing import Optional, Tuple, Any, List, Dict

from dotenv import load_dotenv

from core.contracts.schemas import PersonalityConfig, PolicyPack
from core.unified_client import UnifiedClient
from core.memory import UnifiedMemory
from core.tools import Tools
from core.tools.run_shell import RunShellTool
from core.tools.run_python import RunPythonTool
from core.tools.capability import CapabilityEngine
from core.runtime.provider_config import DEFAULT_MODELS, resolve_provider
from core.runtime.messages import build_system_prompt, build_chat_context
from core.runtime.context_window import ContextWindowManager


class Agent:
    """Concrete agent class. PersonalityConfig replaces Elf's abstract properties.

    Exposes the same interface as Elf for backward compatibility.
    """

    def __init__(
        self,
        config: PersonalityConfig,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        debug: bool = True,
        client=None,
        memory=None,
        tools=None,
    ):
        self._config = config

        # Load environment from personality-specific env file
        env_path = Path(config.env_path).expanduser()
        if env_path.exists():
            load_dotenv(dotenv_path=env_path, override=True)

        # --- Provider resolution ---
        self.provider = resolve_provider(
            requested=provider or config.default_provider,
            has_injected_client=(client is not None),
        )
        self.model = model or config.default_model or DEFAULT_MODELS[self.provider]

        # --- Client / memory / tools ---
        self.client = client if client is not None else UnifiedClient(provider_override=self.provider)
        self.memory = memory if memory is not None else UnifiedMemory(
            Path.home() / f".{self.personality}_memory.db"
        )
        self.tools = tools if tools is not None else Tools(
            elfenv=self.env, memory=self.memory, enable_voice=False
        )

        self._context_manager = ContextWindowManager(project_root=Path.cwd())

        # Build initial history
        self.history = self._load_history()

        self.debug = debug
        if self.debug:
            from rich import print
            print(f"[green]🧠 Using provider:[/green] {self.provider.upper()} | "
                  f"[cyan]Model:[/cyan] {self.model}")

    # =======================
    # Properties (from config)
    # =======================
    @property
    def personality(self) -> str:
        return self._config.name

    @property
    def system_message(self) -> str:
        return self._config.system_message

    @property
    def examples(self) -> List[Tuple[str, str]]:
        return self._config.examples

    @property
    def text_color(self) -> str:
        return self._config.text_color

    @property
    def env(self) -> Path:
        return Path(self._config.env_path).expanduser()

    @property
    def rag_enhancement_style(self) -> str:
        return self._config.rag_enhancement_style

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
        if self._context_manager is not None:
            backend_caps = getattr(self.client, "capabilities", None)
            context, _stats = self._context_manager.build_messages(
                system_prompt=sys_prompt,
                history=self.history,
                invoked_tools=invoked_tools,
                provider=self.provider,
                model=self.model,
                backend_caps=backend_caps,
            )
        else:
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
        result = self.tools.run("run_shell_command", cmd, elf=self)
        # Phase 4: tools now return (rc, out, err) tuples
        if isinstance(result, tuple) and len(result) == 3:
            rc, out, err = result
            output = out if rc == 0 else (err or out)
            success = 1 if rc == 0 else 0
        else:
            output = str(result)
            success = 1
        summary = self.summarize_text(output) if summarize else None
        return cmd, output, success, summary

    def run_python_task(
        self, prompt: str, memory_reflection: Optional[str] = None, summarize: bool = False
    ) -> Tuple[str, Any, Any, Optional[str]]:
        enhanced = self._format_prompt(prompt, memory_reflection, "Python")
        code = self.generate_python_code(enhanced)
        result = self.tools.run("run_python_code", code, elf=self)
        # Phase 4: tools now return (rc, out, err) tuples
        if isinstance(result, tuple) and len(result) == 3:
            rc, out, err = result
            output = out if rc == 0 else (err or out)
            success = 1 if rc == 0 else 0
        else:
            output = str(result)
            success = 1
        summary = self.summarize_text(output) if summarize else None
        return code, output, success, summary

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
    def run_task(self, task_description: str, budget=None, session_manager=None,
                 policy=None):
        """Thin adapter: delegate an agentic task to the kernel orchestrator.

        Phase 4: Creates a CapabilityEngine with the given policy and passes
        the ToolBus to the orchestrator for capability-gated dispatch.
        """
        from core.kernel import Orchestrator

        # Set up capability engine for agentic mode
        if policy is not None:
            cap_engine = CapabilityEngine(policy)
            self.tools.bus._capability = cap_engine

        dispatcher = self._make_task_dispatcher()
        kwargs = {
            "dispatcher": dispatcher,
            "budget": budget,
            "tool_bus": self.tools.bus,
        }
        if session_manager is not None:
            kwargs["session_manager"] = session_manager
        orchestrator = Orchestrator(**kwargs)
        return orchestrator.run(task_description)

    def run_campaign(self, plan, base_dir: Optional[Path] = None,
                     auto_approve: bool = False, editor: Optional[str] = None):
        """Run a multi-step CampaignPlan through the CampaignOrchestrator."""
        from core.campaign import CampaignOrchestrator

        base = base_dir or Path.cwd()

        def dispatcher_factory(step):
            return self._make_task_dispatcher()

        orch = CampaignOrchestrator(
            dispatcher_factory=dispatcher_factory,
            base_dir=base,
            tool_bus=self.tools.bus,
        )
        return orch.run(plan, auto_approve=auto_approve, editor=editor)

    def draft_campaign_plan(self, mission: str, max_attempts: int = 2):
        from core.campaign.planner import draft_campaign_plan
        from core.kernel.workflows import list_workflows

        def chat_fn(messages):
            return self.client.chat(model=self.model, messages=messages, stream=False)

        return draft_campaign_plan(
            mission=mission,
            chat_fn=chat_fn,
            available_workflows=list_workflows(),
            max_attempts=max_attempts,
        )

    def run_campaign_from_description(
        self,
        mission: str,
        base_dir: Optional[Path] = None,
        auto_approve: bool = False,
        editor: Optional[str] = None,
    ):
        plan = self.draft_campaign_plan(mission)
        return self.run_campaign(plan, base_dir=base_dir, auto_approve=auto_approve, editor=editor)

    def _make_task_dispatcher(self):
        """Create a role dispatcher for agentic task execution.

        Phase 2 returns a stub that succeeds on every phase.
        Phase 7 overrides this with real role implementations.
        """
        from core.kernel import PhaseResult, SessionState

        class StubDispatcher:
            def dispatch(self, phase: str, state: SessionState) -> PhaseResult:
                return PhaseResult(success=True)

        return StubDispatcher()

    # =======================
    # CLI methods
    # =======================
    def recall_adventures(self, n: int = 10, mode=None) -> List[Dict]:
        """Recall past adventures from memory."""
        rows = self.memory.list_adventures(n=n)
        if mode:
            rows = [r for r in rows if r.get("mode") == mode]
        return rows

    def format_recall(self, rows: List[Dict]) -> str:
        """Format adventure rows for display."""
        lines = []
        for r in rows:
            status = "✅" if r.get("success") else "❌"
            lines.append(f"{status} [{r.get('mode', '?')}] {r.get('prompt', '')[:80]}")
        return "\n".join(lines)

    def handle_rag(self, subcmd: str, query: str, directory=None, **kw):
        """Delegate RAG operations to memory/tools."""
        if subcmd == "crawl":
            target = Path(directory) if directory else Path(".")
            result = self.tools.run("rag_crawler", str(target),
                                    recursive=kw.get("recursive", False),
                                    includes=kw.get("includes"),
                                    excludes=kw.get("excludes"),
                                    elf=self)
            return None, f"Crawled: {result}"

        if subcmd == "find":
            hits = self.memory.search_rag(query, dir_filter=str(directory) if directory else None)
            if hits:
                for hit in hits:
                    self.history.append({
                        "role": "assistant",
                        "content": f"📚 RAG [{hit['file']}]: {hit['content'][:200]}"
                    })
            return hits, f"Found {len(hits)} RAG results" if hits else "No RAG results found"

        if subcmd == "delete":
            target = Path(directory) if directory else Path(query)
            self.memory.delete_rag(target)
            return None, f"Deleted RAG entries for {target}"

        if subcmd == "list" or subcmd == "status":
            status = self.memory.rag_status()
            msg_parts = []
            for d, files in status.items():
                msg_parts.append(f"📁 {d}: {len(files)} files")
            return None, "\n".join(msg_parts) if msg_parts else "No RAG data"

        if subcmd == "enhance":
            hits = self.memory.search_rag(query, dir_filter=str(directory) if directory else None)
            if hits:
                rag_context = "\n".join(f"[{h['file']}]: {h['content'][:300]}" for h in hits)
                style = self.rag_enhancement_style
                self.history.append({
                    "role": "assistant",
                    "content": f"----\n#RAG CONTEXT - DO NOT REPEAT VERBATIM\n{style}\n{rag_context}\n----"
                })
            return hits, None

        return None, f"Unknown RAG command: {subcmd}"
