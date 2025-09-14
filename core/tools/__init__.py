# core/tools/__init__.py

from core.tools.tool import Tool
from .run_shell import RunShellTool
from .run_python import RunPythonTool
from .install_project import InstallProjectTool
from .fetch_page import FetchPageTool
from .web_search import WebSearchTool
from .rag_crawler import RagCrawlerTool
from core.memory.memory import UnifiedMemory
from typing import Callable, Union

class Tools:
    def __init__(self, elfenv=None, memory: UnifiedMemory = None):
        self.elfenv = elfenv
        self.registry: dict[str, Union[Tool, Callable[[], Tool]]] = {}
        self._register(RunShellTool())
        self._register(RunPythonTool(elfenv=elfenv))
        self._register(InstallProjectTool(elfenv=elfenv))
        self._register(FetchPageTool())
        self._register(WebSearchTool())
        if memory:
            self._register(RagCrawlerTool(memory))
        self._register_lazy("speak_text", self._lazy_load_speak_text)

    def _register(self, _tool: Tool):
        self.registry[_tool.name] = _tool

    def _register_lazy(self, name: str, factory: Callable[[], Tool]):
        self.registry[name] = factory

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
                    return "⚠️ Voice output disabled (TTS not installed)."

            return DummySpeakTool()

    def list_tools(self):
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

    def describe_tool(self, name: str):
        _tool = self.get_tool(name)
        return _tool.info() if _tool else {"error": f"No such tool: {name}"}

    def run(self, name: str, *args, **kwargs):
        _tool = self.get_tool(name)
        if not _tool:
            raise ValueError(f"No such tool: {name}")
        return _tool(*args, **kwargs)
