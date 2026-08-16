# tests/test_tools_registry.py

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.tools import Tools
from core.tools.tool import Tool
from core.tools.bus import ToolBus
from core.tools.capability import CapabilityEngine
from core.contracts.schemas import PolicyPack, ProfileMode


def _setup_mocks(MockWeb, MockResearch, MockFetch, MockShell, MockInstall, MockPython, spec=False):
    """Helper: configure mocked constructors so Tools.__init__ can register them."""
    mocks = {
        "run_shell_command": MockShell,
        "run_python_code": MockPython,
        "install_project": MockInstall,
        "fetch_page_content": MockFetch,
        "perform_web_search": MockWeb,
        "perform_web_research": MockResearch,
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
    @patch("core.tools.WebResearchTool")
    def test_list_tools(self, MockResearch, MockWeb, MockFetch, MockShell, MockInstall, MockPython):
        """Tools registry lists all registered tools."""
        _setup_mocks(MockWeb, MockResearch, MockFetch, MockShell, MockInstall, MockPython)
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
    @patch("core.tools.WebResearchTool")
    def test_get_tool(self, MockResearch, MockWeb, MockFetch, MockShell, MockInstall, MockPython):
        _setup_mocks(MockWeb, MockResearch, MockFetch, MockShell, MockInstall, MockPython, spec=True)
        tools = Tools(elfenv="/tmp/fake", memory=None, enable_voice=False)
        shell = tools.get_tool("run_shell_command")
        assert shell is not None
        assert tools.get_tool("nonexistent") is None

    @patch("core.tools.RunPythonTool")
    @patch("core.tools.InstallProjectTool")
    @patch("core.tools.RunShellTool")
    @patch("core.tools.FetchPageTool")
    @patch("core.tools.WebSearchTool")
    @patch("core.tools.WebResearchTool")
    def test_describe_tool(self, MockResearch, MockWeb, MockFetch, MockShell, MockInstall, MockPython):
        _setup_mocks(MockWeb, MockResearch, MockFetch, MockShell, MockInstall, MockPython, spec=True)
        tools = Tools(elfenv="/tmp/fake", memory=None, enable_voice=False)
        desc = tools.describe_tool("run_shell_command")
        assert "description" in desc

    @patch("core.tools.RunPythonTool")
    @patch("core.tools.InstallProjectTool")
    @patch("core.tools.RunShellTool")
    @patch("core.tools.FetchPageTool")
    @patch("core.tools.WebSearchTool")
    @patch("core.tools.WebResearchTool")
    def test_describe_unknown_tool(self, MockResearch, MockWeb, MockFetch, MockShell, MockInstall, MockPython):
        _setup_mocks(MockWeb, MockResearch, MockFetch, MockShell, MockInstall, MockPython)
        tools = Tools(elfenv="/tmp/fake", memory=None, enable_voice=False)
        desc = tools.describe_tool("nonexistent")
        assert "error" in desc

    @patch("core.tools.RunPythonTool")
    @patch("core.tools.InstallProjectTool")
    @patch("core.tools.RunShellTool")
    @patch("core.tools.FetchPageTool")
    @patch("core.tools.WebSearchTool")
    @patch("core.tools.WebResearchTool")
    def test_run_tool(self, MockResearch, MockWeb, MockFetch, MockShell, MockInstall, MockPython):
        _setup_mocks(MockWeb, MockResearch, MockFetch, MockShell, MockInstall, MockPython, spec=True)
        MockShell.return_value.return_value = "shell output"
        # `shell.exec` is not in the deny-by-default SAFE profile Tools() now
        # builds, so dispatching a shell command needs the intent stated:
        # GOD grants everything, which is what this registry test means by
        # "run the tool and give me its result". A SAFE default here would
        # return the capability_denied tuple instead — which is the subject
        # of test_capability / test_profiles, not of this dispatch test.
        tools = Tools(elfenv="/tmp/fake", memory=None, profile=ProfileMode.GOD)
        result = tools.run("run_shell_command", "echo hi")
        assert result == (0, "shell output", "")

    @patch("core.tools.RunPythonTool")
    @patch("core.tools.InstallProjectTool")
    @patch("core.tools.RunShellTool")
    @patch("core.tools.FetchPageTool")
    @patch("core.tools.WebSearchTool")
    @patch("core.tools.WebResearchTool")
    def test_run_unknown_tool_raises(self, MockResearch, MockWeb, MockFetch, MockShell, MockInstall, MockPython):
        _setup_mocks(MockWeb, MockResearch, MockFetch, MockShell, MockInstall, MockPython)
        tools = Tools(elfenv="/tmp/fake", memory=None, enable_voice=False)
        with pytest.raises(ValueError, match="No such tool"):
            tools.run("nonexistent", "arg")

    @patch("core.tools.RunPythonTool")
    @patch("core.tools.InstallProjectTool")
    @patch("core.tools.RunShellTool")
    @patch("core.tools.FetchPageTool")
    @patch("core.tools.WebSearchTool")
    @patch("core.tools.WebResearchTool")
    def test_no_rag_tool_without_memory(self, MockResearch, MockWeb, MockFetch, MockShell, MockInstall, MockPython):
        """When memory=None, RagCrawlerTool is not registered."""
        _setup_mocks(MockWeb, MockResearch, MockFetch, MockShell, MockInstall, MockPython)
        tools = Tools(elfenv="/tmp/fake", memory=None, enable_voice=False)
        assert "rag_crawl" not in tools.list_tools()


class TestToolsToolBusIntegration:
    @patch("core.tools.RunPythonTool")
    @patch("core.tools.InstallProjectTool")
    @patch("core.tools.RunShellTool")
    @patch("core.tools.FetchPageTool")
    @patch("core.tools.WebSearchTool")
    @patch("core.tools.WebResearchTool")
    def test_bus_property_exists(self, MockResearch, MockWeb, MockFetch, MockShell, MockInstall, MockPython):
        _setup_mocks(MockWeb, MockResearch, MockFetch, MockShell, MockInstall, MockPython)
        tools = Tools(elfenv="/tmp/fake", memory=None, enable_voice=False)
        assert isinstance(tools.bus, ToolBus)

    @patch("core.tools.RunPythonTool")
    @patch("core.tools.InstallProjectTool")
    @patch("core.tools.RunShellTool")
    @patch("core.tools.FetchPageTool")
    @patch("core.tools.WebSearchTool")
    @patch("core.tools.WebResearchTool")
    def test_bus_has_registered_tools(self, MockResearch, MockWeb, MockFetch, MockShell, MockInstall, MockPython):
        _setup_mocks(MockWeb, MockResearch, MockFetch, MockShell, MockInstall, MockPython)
        tools = Tools(elfenv="/tmp/fake", memory=None, enable_voice=False)
        bus_tools = tools.bus.list_tools()
        assert "run_shell_command" in bus_tools
        assert "run_python_code" in bus_tools
        assert "install_project" in bus_tools

    @patch("core.tools.RunPythonTool")
    @patch("core.tools.InstallProjectTool")
    @patch("core.tools.RunShellTool")
    @patch("core.tools.FetchPageTool")
    @patch("core.tools.WebSearchTool")
    @patch("core.tools.WebResearchTool")
    def test_custom_capability_engine(self, MockResearch, MockWeb, MockFetch, MockShell, MockInstall, MockPython):
        _setup_mocks(MockWeb, MockResearch, MockFetch, MockShell, MockInstall, MockPython)
        policy = PolicyPack(allowed_scopes=["shell.exec"])
        engine = CapabilityEngine(policy)
        tools = Tools(elfenv="/tmp/fake", memory=None, capability_engine=engine)
        assert tools.bus.capability_engine is engine

    @patch("core.tools.RunPythonTool")
    @patch("core.tools.InstallProjectTool")
    @patch("core.tools.RunShellTool")
    @patch("core.tools.FetchPageTool")
    @patch("core.tools.WebSearchTool")
    @patch("core.tools.WebResearchTool")
    def test_bus_describe_tool(self, MockResearch, MockWeb, MockFetch, MockShell, MockInstall, MockPython):
        _setup_mocks(MockWeb, MockResearch, MockFetch, MockShell, MockInstall, MockPython)
        tools = Tools(elfenv="/tmp/fake", memory=None, enable_voice=False)
        desc = tools.bus.describe_tool("run_shell_command")
        assert desc["name"] == "run_shell_command"
        assert "shell.exec" in desc["required_scopes"]


class TestToolsProfileDefault:
    """Deny-by-default: `Tools()` builds the SAFE profile, not allow-all.

    These do not mock the tool constructors — they only inspect the engine
    the bus was built with, so the real descriptors and their scopes apply.
    """

    def test_default_is_safe_not_wildcard(self):
        tools = Tools(elfenv=Path("/tmp/fake"), memory=None)
        engine = tools.bus.capability_engine
        assert engine.current_profile == "safe"
        # shell.exec is a DEV scope; under the default it is denied.
        assert engine.check("run_shell_command", ["shell.exec"]).allowed is False
        # fs.read is SAFE; it is allowed.
        assert engine.check("fs", ["fs.read"]).allowed is True

    def test_default_opens_the_mcp_plane(self):
        # A `--mission --skill` run over MCP must keep working under the
        # default: bridged tools carry `mcp.call`, which is a SAFE scope.
        tools = Tools(elfenv=Path("/tmp/fake"), memory=None)
        engine = tools.bus.capability_engine
        assert engine.check("mcp.governed_read", ["mcp.call"]).allowed is True

    def test_profile_kwarg_opts_up(self):
        tools = Tools(elfenv=Path("/tmp/fake"), memory=None, profile=ProfileMode.DEV)
        engine = tools.bus.capability_engine
        assert engine.current_profile == "dev"
        assert engine.check("run_shell_command", ["shell.exec"]).allowed is True

    def test_god_profile_grants_everything(self):
        tools = Tools(elfenv=Path("/tmp/fake"), memory=None, profile=ProfileMode.GOD)
        engine = tools.bus.capability_engine
        assert engine.check("t", ["anything.at.all"]).allowed is True

    def test_engine_and_profile_together_is_refused(self):
        engine = CapabilityEngine(PolicyPack(allowed_scopes=["*"]))
        with pytest.raises(ValueError, match="both capability_engine.* and profile"):
            Tools(elfenv=Path("/tmp/fake"), memory=None,
                  capability_engine=engine, profile=ProfileMode.DEV)

    def test_shell_dispatch_under_default_is_denied_naming_the_fix(self):
        # End to end through the bus: the tuple a denied shell tool returns
        # carries the refusal that names shell.exec and --profile dev.
        import json
        tools = Tools(elfenv=Path("/tmp/fake"), memory=None)
        rc, out, err = tools.run("run_shell_command", "ls -la")
        assert rc == -1
        denial = json.loads(err)
        assert denial["error"] == "capability_denied"
        assert "shell.exec" in denial["missing_scopes"]
        assert "--profile dev" in denial["message"]


def _mocked(fn):
    """The six constructor patches every test in this file needs, once."""
    for target in ("core.tools.WebResearchTool", "core.tools.WebSearchTool",
                   "core.tools.FetchPageTool", "core.tools.RunShellTool",
                   "core.tools.InstallProjectTool", "core.tools.RunPythonTool"):
        fn = patch(target)(fn)
    return fn


class TestAuditIsOnByDefault:
    """`AuditLogger` existed from Phase 4b and nothing ever passed one here.

    The default deployment — the one a platform spawns — therefore kept no
    record of a single tool call, which is the difference between a framework
    you can leave unattended and one you cannot. These tests hold the default
    down; `core/policy/audit.py` owns where the file goes.
    """

    @_mocked
    def test_the_default_bus_has_a_logger(self, MockResearch, MockWeb, MockFetch,
                                          MockShell, MockInstall, MockPython,
                                          tmp_path, monkeypatch):
        from core.policy.audit import AUDIT_ENV

        _setup_mocks(MockWeb, MockResearch, MockFetch, MockShell, MockInstall, MockPython)
        target = tmp_path / "run.jsonl"
        monkeypatch.setenv(AUDIT_ENV, str(target))
        tools = Tools(elfenv="/tmp/fake", memory=None)
        assert tools.bus.audit_ref == str(target)

    @_mocked
    def test_the_default_path_is_under_the_working_directory(
            self, MockResearch, MockWeb, MockFetch, MockShell, MockInstall,
            MockPython, tmp_path, monkeypatch):
        from core.policy.audit import AUDIT_ENV

        _setup_mocks(MockWeb, MockResearch, MockFetch, MockShell, MockInstall, MockPython)
        monkeypatch.delenv(AUDIT_ENV, raising=False)
        monkeypatch.chdir(tmp_path)
        tools = Tools(elfenv="/tmp/fake", memory=None)
        assert tools.bus.audit_ref.startswith(
            str(tmp_path / ".judais-lobi" / "audit"))

    @_mocked
    def test_a_dispatch_through_the_default_bus_is_recorded(
            self, MockResearch, MockWeb, MockFetch, MockShell, MockInstall,
            MockPython, tmp_path, monkeypatch):
        import json

        from core.policy.audit import AUDIT_ENV
        from core.tools.descriptors import ToolDescriptor

        _setup_mocks(MockWeb, MockResearch, MockFetch, MockShell, MockInstall, MockPython)
        target = tmp_path / "run.jsonl"
        monkeypatch.setenv(AUDIT_ENV, str(target))
        tools = Tools(elfenv="/tmp/fake", memory=None)
        tools.bus.register(ToolDescriptor(tool_name="probe"),
                           lambda **kw: (0, "ran", ""))
        tools.bus.dispatch("probe", q="x")
        line = json.loads(target.read_text().strip().splitlines()[-1])
        assert line["tool_name"] == "probe"
        assert line["verdict"] == "allowed"

    @_mocked
    def test_the_disable_word_turns_it_off_and_writes_nothing(
            self, MockResearch, MockWeb, MockFetch, MockShell, MockInstall,
            MockPython, tmp_path, monkeypatch):
        """Explicitly off, which is a decision, and it leaves no file — the
        stream says so as `audit_ref: null` rather than leaving a consumer to
        infer it from an empty directory."""
        from core.policy.audit import AUDIT_ENV
        from core.tools.descriptors import ToolDescriptor

        _setup_mocks(MockWeb, MockResearch, MockFetch, MockShell, MockInstall, MockPython)
        monkeypatch.setenv(AUDIT_ENV, "off")
        monkeypatch.chdir(tmp_path)
        tools = Tools(elfenv="/tmp/fake", memory=None)
        tools.bus.register(ToolDescriptor(tool_name="probe"),
                           lambda **kw: (0, "ran", ""))
        tools.bus.dispatch("probe")
        assert tools.bus.audit_ref is None
        assert list(tmp_path.iterdir()) == []

    @_mocked
    def test_a_caller_can_ask_for_no_audit_explicitly(
            self, MockResearch, MockWeb, MockFetch, MockShell, MockInstall,
            MockPython):
        """`audit=None` is a request; omitting the parameter is not. Without
        the sentinel the two would be the same call and the default would have
        to come down on the side of keeping no records."""
        _setup_mocks(MockWeb, MockResearch, MockFetch, MockShell, MockInstall, MockPython)
        tools = Tools(elfenv="/tmp/fake", memory=None, audit=None)
        assert tools.bus.audit_ref is None

    @_mocked
    def test_a_caller_can_supply_its_own_logger(
            self, MockResearch, MockWeb, MockFetch, MockShell, MockInstall,
            MockPython, tmp_path):
        from core.policy.audit import AuditLogger

        _setup_mocks(MockWeb, MockResearch, MockFetch, MockShell, MockInstall, MockPython)
        logger = AuditLogger(path=tmp_path / "mine.jsonl")
        tools = Tools(elfenv="/tmp/fake", memory=None, audit=logger)
        assert tools.bus.audit_ref == str(tmp_path / "mine.jsonl")
