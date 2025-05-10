# core/tools/__init__.py

from core.tools.tool import Tool
from .run_shell import RunShellTool
from .run_python import RunPythonTool
from .install_project import InstallProjectTool
from .fetch_page import FetchPageTool
from .web_search import WebSearchTool
from typing import Callable, Union

class Tools:
    def __init__(self, elfenv=None):
        self.elfenv = elfenv
        self.registry: dict[str, Union[Tool, Callable[[], Tool]]] = {}
        self._register(RunShellTool())
        self._register(RunPythonTool(elfenv=elfenv))
        self._register(InstallProjectTool(elfenv=elfenv))
        self._register(FetchPageTool())
        self._register(WebSearchTool())
        self._register_lazy("speak_text", self._lazy_load_speak_text)

    def _register(self, _tool: Tool):
        self.registry[_tool.name] = _tool

    def _register_lazy(self, name: str, factory: Callable[[], Tool]):
        self.registry[name] = factory

    def _lazy_load_speak_text(self):
        from core.tools.voice import SpeakTextTool
        return SpeakTextTool()

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
