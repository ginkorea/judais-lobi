# core/tools/__init__.py
# Phase 4: Tools wraps ToolBus internally. Backward-compatible interface.

from core.tools.tool import Tool
from .run_shell import RunShellTool
from .run_python import RunPythonTool
from .install_project import InstallProjectTool
from .fetch_page import FetchPageTool
from .web_search import WebSearchTool
from .rag_crawler import RagCrawlerTool
from core.memory.memory import UnifiedMemory
from typing import Callable, List, Optional, Union

from core.tools.bus import ToolBus, ToolResult
from core.tools.capability import CapabilityEngine
from core.tools.sandbox import SandboxRunner, NoneSandbox
from core.tools.descriptors import (
    SHELL_DESCRIPTOR,
    PYTHON_DESCRIPTOR,
    INSTALL_DESCRIPTOR,
    WEB_SEARCH_DESCRIPTOR,
    FETCH_PAGE_DESCRIPTOR,
    RAG_CRAWLER_DESCRIPTOR,
    VOICE_DESCRIPTOR,
    FS_DESCRIPTOR,
    GIT_DESCRIPTOR,
    VERIFY_DESCRIPTOR,
    ToolDescriptor,
)
from core.tools.fs_tools import FsTool
from core.tools.git_tools import GitTool
from core.tools.verify_tools import VerifyTool
from core.tools.config_loader import load_project_config


class Tools:
    """Core tool registry. Wraps ToolBus for capability gating and sandboxed execution.

    Backward-compatible: list_tools(), describe_tool(), get_tool(), run() all work
    as before. The ToolBus is used internally for dispatch with capability checks.
    """

    def __init__(
        self,
        elfenv=None,
        memory: UnifiedMemory = None,
        enable_voice=False,
        capability_engine: Optional[CapabilityEngine] = None,
        sandbox: Optional[SandboxRunner] = None,
    ):
        self.elfenv = elfenv
        self.registry: dict[str, Union[Tool, Callable[[], Tool]]] = {}

        # Create ToolBus
        self._bus = ToolBus(
            capability_engine=capability_engine,
            sandbox=sandbox,
        )

        # Always-available tools
        shell_tool = RunShellTool()
        python_tool = RunPythonTool(elfenv=elfenv)
        install_tool = InstallProjectTool(elfenv=elfenv)
        fetch_tool = FetchPageTool()
        search_tool = WebSearchTool()

        self._register(shell_tool)
        self._register(python_tool)
        self._register(install_tool)
        self._register(fetch_tool)
        self._register(search_tool)

        # Register with ToolBus
        self._bus.register(SHELL_DESCRIPTOR, shell_tool)
        self._bus.register(PYTHON_DESCRIPTOR, python_tool)
        self._bus.register(INSTALL_DESCRIPTOR, install_tool)
        self._bus.register(FETCH_PAGE_DESCRIPTOR, fetch_tool)
        self._bus.register(WEB_SEARCH_DESCRIPTOR, search_tool)

        # Phase 4a: Consolidated multi-action tools
        fs_tool = FsTool()
        git_tool = GitTool()
        project_config = load_project_config()
        verify_tool = VerifyTool(config=project_config)

        self._bus.register(FS_DESCRIPTOR, fs_tool)
        self._bus.register(GIT_DESCRIPTOR, git_tool)
        self._bus.register(VERIFY_DESCRIPTOR, verify_tool)

        if memory:
            rag_tool = RagCrawlerTool(memory)
            self._register(rag_tool)
            self._bus.register(RAG_CRAWLER_DESCRIPTOR, rag_tool)

        # Only load voice if explicitly enabled
        if enable_voice:
            self._register_lazy("speak_text", self._lazy_load_speak_text)

    @property
    def bus(self) -> ToolBus:
        return self._bus

    # ---- registration helpers ----

    def _register(self, _tool: Tool):
        self.registry[_tool.name] = _tool

    def _register_lazy(self, name: str, factory: Callable[[], Tool]):
        self.registry[name] = factory

    # ---- lazy voice load ----

    @staticmethod
    def _lazy_load_speak_text():
        try:
            from core.tools.voice import SpeakTextTool
            return SpeakTextTool()
        except ImportError:
            class DummySpeakTool(Tool):
                name = "speak_text"
                description = "Dummy voice tool (TTS not installed)."
                def __call__(self, *args, **kwargs):
                    return "Voice output disabled (TTS not installed)."
            return DummySpeakTool()

    # ---- tool management ----

    def list_tools(self) -> List[str]:
        return list(self.registry.keys())

    def get_tool(self, name: str):
        tool = self.registry.get(name)
        if tool is None:
            return None
        if callable(tool) and not isinstance(tool, Tool):
            tool_instance = tool()
            self.registry[name] = tool_instance
            return tool_instance
        return tool

    def describe_tool(self, name: str) -> dict:
        # Prefer ToolBus descriptor if available
        bus_desc = self._bus.describe_tool(name)
        if "error" not in bus_desc:
            return bus_desc
        # Fallback to legacy info()
        _tool = self.get_tool(name)
        return _tool.info() if _tool else {"error": f"No such tool: {name}"}

    def run(self, name: str, *args, **kwargs):
        """Backward-compatible run. Delegates to tool directly.

        For capability-gated dispatch, use self._bus.dispatch() instead.
        """
        _tool = self.get_tool(name)
        if not _tool:
            raise ValueError(f"No such tool: {name}")

        result = _tool(*args, **kwargs)

        # Tool awareness injection
        elf = kwargs.get("elf")
        if elf:
            arg_summary = ", ".join(map(str, args))
            kwarg_summary = ", ".join(f"{k}={v}" for k, v in kwargs.items() if k != "elf")
            arg_text = "; ".join(filter(None, [arg_summary, kwarg_summary]))
            result_str = str(result)
            if len(result_str) > 500:
                result_str = result_str[:500] + "..."
            elf.history.append({
                "role": "assistant",
                "content": (
                    f"(Tool used: {name})\n"
                    f"Args: {arg_text or 'none'}\n"
                    f"Result (truncated):\n{result_str}"
                )
            })
        return result
