# core/tools/__init__.py

from core.tools.tool import Tool
from .run_shell import RunShellTool
from .run_python import RunPythonTool
from .install_project import InstallProjectTool
from .fetch_page import FetchPageTool
from .web_search import WebSearchTool
from .voice import SpeakTextTool

class Tools:
    def __init__(self, elfenv=None):
        self.registry: dict[str, Tool] = {}
        self._register(RunShellTool())
        self._register(RunPythonTool(elfenv=elfenv))
        self._register(InstallProjectTool(elfenv=elfenv))
        self._register(FetchPageTool())
        self._register(WebSearchTool())
        self._register(SpeakTextTool())

    def _register(self, _tool: Tool):
        self.registry[_tool.name] = _tool

    def list_tools(self):
        return list(self.registry.keys())

    def get_tool(self, name: str):
        return self.registry.get(name)

    def describe_tool(self, name: str):
        _tool = self.get_tool(name)
        return _tool.info() if _tool else {"error": f"No such tool: {name}"}

    def run(self, name: str, *args, **kwargs):
        _tool = self.get_tool(name)
        if not _tool:
            raise ValueError(f"No such tool: {name}")
        return _tool(*args, **kwargs)
