# tests/test_tools_registry.py

import pytest
from unittest.mock import MagicMock, patch

from core.tools import Tools
from core.tools.tool import Tool


def _setup_mocks(MockWeb, MockFetch, MockShell, MockInstall, MockPython, spec=False):
    """Helper: configure mocked constructors so Tools.__init__ can register them."""
    mocks = {
        "run_shell_command": MockShell,
        "run_python_code": MockPython,
        "install_project": MockInstall,
        "fetch_page": MockFetch,
        "perform_web_search": MockWeb,
    }
    for name, mock_cls in mocks.items():
        instance = MagicMock(spec=Tool) if spec else MagicMock()
        instance.name = name
        instance.info.return_value = {"name": name, "description": f"Mock {name}"}
        mock_cls.return_value = instance
    return mocks


class TestToolsRegistry:
    @patch("core.tools.RunPythonTool")
    @patch("core.tools.InstallProjectTool")
    @patch("core.tools.RunShellTool")
    @patch("core.tools.FetchPageTool")
    @patch("core.tools.WebSearchTool")
    def test_list_tools(self, MockWeb, MockFetch, MockShell, MockInstall, MockPython):
        """Tools registry lists all registered tools."""
        _setup_mocks(MockWeb, MockFetch, MockShell, MockInstall, MockPython)
        tools = Tools(elfenv="/tmp/fake", memory=None, enable_voice=False)
        names = tools.list_tools()
        assert "run_shell_command" in names
        assert "run_python_code" in names
        assert "install_project" in names

    @patch("core.tools.RunPythonTool")
    @patch("core.tools.InstallProjectTool")
    @patch("core.tools.RunShellTool")
    @patch("core.tools.FetchPageTool")
    @patch("core.tools.WebSearchTool")
    def test_get_tool(self, MockWeb, MockFetch, MockShell, MockInstall, MockPython):
        _setup_mocks(MockWeb, MockFetch, MockShell, MockInstall, MockPython, spec=True)
        tools = Tools(elfenv="/tmp/fake", memory=None, enable_voice=False)
        shell = tools.get_tool("run_shell_command")
        assert shell is not None
        assert tools.get_tool("nonexistent") is None

    @patch("core.tools.RunPythonTool")
    @patch("core.tools.InstallProjectTool")
    @patch("core.tools.RunShellTool")
    @patch("core.tools.FetchPageTool")
    @patch("core.tools.WebSearchTool")
    def test_describe_tool(self, MockWeb, MockFetch, MockShell, MockInstall, MockPython):
        _setup_mocks(MockWeb, MockFetch, MockShell, MockInstall, MockPython, spec=True)
        tools = Tools(elfenv="/tmp/fake", memory=None, enable_voice=False)
        desc = tools.describe_tool("run_shell_command")
        assert "description" in desc

    @patch("core.tools.RunPythonTool")
    @patch("core.tools.InstallProjectTool")
    @patch("core.tools.RunShellTool")
    @patch("core.tools.FetchPageTool")
    @patch("core.tools.WebSearchTool")
    def test_describe_unknown_tool(self, MockWeb, MockFetch, MockShell, MockInstall, MockPython):
        _setup_mocks(MockWeb, MockFetch, MockShell, MockInstall, MockPython)
        tools = Tools(elfenv="/tmp/fake", memory=None, enable_voice=False)
        desc = tools.describe_tool("nonexistent")
        assert "error" in desc

    @patch("core.tools.RunPythonTool")
    @patch("core.tools.InstallProjectTool")
    @patch("core.tools.RunShellTool")
    @patch("core.tools.FetchPageTool")
    @patch("core.tools.WebSearchTool")
    def test_run_tool(self, MockWeb, MockFetch, MockShell, MockInstall, MockPython):
        _setup_mocks(MockWeb, MockFetch, MockShell, MockInstall, MockPython, spec=True)
        # Override the __call__ return for the shell mock
        MockShell.return_value.return_value = "shell output"
        tools = Tools(elfenv="/tmp/fake", memory=None, enable_voice=False)
        result = tools.run("run_shell_command", "echo hi")
        assert result == "shell output"

    @patch("core.tools.RunPythonTool")
    @patch("core.tools.InstallProjectTool")
    @patch("core.tools.RunShellTool")
    @patch("core.tools.FetchPageTool")
    @patch("core.tools.WebSearchTool")
    def test_run_unknown_tool_raises(self, MockWeb, MockFetch, MockShell, MockInstall, MockPython):
        _setup_mocks(MockWeb, MockFetch, MockShell, MockInstall, MockPython)
        tools = Tools(elfenv="/tmp/fake", memory=None, enable_voice=False)
        with pytest.raises(ValueError, match="No such tool"):
            tools.run("nonexistent", "arg")

    @patch("core.tools.RunPythonTool")
    @patch("core.tools.InstallProjectTool")
    @patch("core.tools.RunShellTool")
    @patch("core.tools.FetchPageTool")
    @patch("core.tools.WebSearchTool")
    def test_no_rag_tool_without_memory(self, MockWeb, MockFetch, MockShell, MockInstall, MockPython):
        """When memory=None, RagCrawlerTool is not registered."""
        _setup_mocks(MockWeb, MockFetch, MockShell, MockInstall, MockPython)
        tools = Tools(elfenv="/tmp/fake", memory=None, enable_voice=False)
        assert "rag_crawl" not in tools.list_tools()
