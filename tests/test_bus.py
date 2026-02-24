# tests/test_bus.py

import pytest
from unittest.mock import MagicMock

from core.tools.bus import ToolBus, ToolResult
from core.tools.descriptors import ToolDescriptor, SandboxProfile
from core.tools.capability import CapabilityEngine
from core.tools.sandbox import NoneSandbox
from core.contracts.schemas import PermissionGrant, PolicyPack


class TestToolResult:
    def test_basic_result(self):
        r = ToolResult(exit_code=0, stdout="ok", stderr="", tool_name="test")
        assert r.exit_code == 0
        assert r.stdout == "ok"
        assert r.tool_name == "test"
        assert r.granted_scopes == []

    def test_result_with_scopes(self):
        r = ToolResult(
            exit_code=0, stdout="", stderr="",
            tool_name="t", granted_scopes=["a.b"],
        )
        assert r.granted_scopes == ["a.b"]


class TestToolBusRegistration:
    def test_register_and_list(self):
        bus = ToolBus()
        desc = ToolDescriptor(tool_name="test_tool")
        bus.register(desc, lambda: None)
        assert "test_tool" in bus.list_tools()

    def test_list_empty(self):
        bus = ToolBus()
        assert bus.list_tools() == []

    def test_register_multiple(self):
        bus = ToolBus()
        bus.register(ToolDescriptor(tool_name="a"), lambda: None)
        bus.register(ToolDescriptor(tool_name="b"), lambda: None)
        assert len(bus.list_tools()) == 2

    def test_describe_tool(self):
        bus = ToolBus()
        desc = ToolDescriptor(
            tool_name="t", description="A test tool",
            required_scopes=["x.y"],
        )
        bus.register(desc, lambda: None)
        info = bus.describe_tool("t")
        assert info["name"] == "t"
        assert info["description"] == "A test tool"
        assert "x.y" in info["required_scopes"]

    def test_describe_unknown_tool(self):
        bus = ToolBus()
        info = bus.describe_tool("nope")
        assert "error" in info

    def test_get_descriptor(self):
        bus = ToolBus()
        desc = ToolDescriptor(tool_name="t")
        bus.register(desc, lambda: None)
        assert bus.get_descriptor("t") is desc

    def test_get_descriptor_missing(self):
        bus = ToolBus()
        assert bus.get_descriptor("nope") is None


class TestToolBusDispatch:
    def _make_permissive_bus(self):
        """Bus with all scopes allowed."""
        policy = PolicyPack(allowed_scopes=[
            "shell.exec", "python.exec", "pip.install",
            "http.read", "fs.read", "audio.output",
        ])
        engine = CapabilityEngine(policy)
        return ToolBus(capability_engine=engine)

    def test_dispatch_unknown_tool(self):
        bus = ToolBus()
        result = bus.dispatch("nonexistent")
        assert result.exit_code == -1
        import json
        error = json.loads(result.stderr)
        assert error["error"] == "unknown_tool"

    def test_dispatch_tuple_result(self):
        bus = self._make_permissive_bus()
        desc = ToolDescriptor(tool_name="t", required_scopes=["shell.exec"])
        bus.register(desc, lambda cmd: (0, "output", ""))
        result = bus.dispatch("t", "echo hi")
        assert result.exit_code == 0
        assert result.stdout == "output"
        assert result.tool_name == "t"
        assert "shell.exec" in result.granted_scopes

    def test_dispatch_string_result(self):
        bus = self._make_permissive_bus()
        desc = ToolDescriptor(tool_name="t", required_scopes=["fs.read"])
        bus.register(desc, lambda: "some text")
        result = bus.dispatch("t")
        assert result.exit_code == 0
        assert result.stdout == "some text"

    def test_dispatch_executor_exception(self):
        bus = self._make_permissive_bus()
        desc = ToolDescriptor(tool_name="t", required_scopes=["shell.exec"])
        bus.register(desc, lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        result = bus.dispatch("t")
        assert result.exit_code == -1
        assert "RuntimeError" in result.stderr

    def test_dispatch_with_kwargs(self):
        bus = self._make_permissive_bus()
        desc = ToolDescriptor(tool_name="t", required_scopes=["shell.exec"])

        def executor(cmd, timeout=None):
            return (0, f"ran with timeout={timeout}", "")

        bus.register(desc, executor)
        result = bus.dispatch("t", "ls", timeout=30)
        assert "timeout=30" in result.stdout

    def test_no_scopes_always_allowed(self):
        """Tools with no required scopes bypass capability check."""
        bus = ToolBus()  # default deny-all engine
        desc = ToolDescriptor(tool_name="t", required_scopes=[])
        bus.register(desc, lambda: (0, "ok", ""))
        result = bus.dispatch("t")
        assert result.exit_code == 0


class TestToolBusCapabilityGating:
    def test_denied_returns_structured_error(self):
        engine = CapabilityEngine()  # deny-by-default
        bus = ToolBus(capability_engine=engine)
        desc = ToolDescriptor(
            tool_name="run_shell_command",
            required_scopes=["shell.exec"],
        )
        bus.register(desc, lambda cmd: (0, "ok", ""))
        result = bus.dispatch("run_shell_command", "ls")
        assert result.exit_code == -1
        import json
        denial = json.loads(result.stderr)
        assert denial["error"] == "capability_denied"
        assert denial["tool"] == "run_shell_command"
        assert "shell.exec" in denial["missing_scopes"]
        assert result.evidence is not None

    def test_granted_allows_execution(self):
        engine = CapabilityEngine()
        engine.add_grant(PermissionGrant(
            tool_name="run_shell_command", scope="shell.exec",
        ))
        bus = ToolBus(capability_engine=engine)
        desc = ToolDescriptor(
            tool_name="run_shell_command",
            required_scopes=["shell.exec"],
        )
        bus.register(desc, lambda cmd: (0, "ok", ""))
        result = bus.dispatch("run_shell_command", "ls")
        assert result.exit_code == 0

    def test_partial_grant_denied(self):
        engine = CapabilityEngine()
        engine.add_grant(PermissionGrant(
            tool_name="install_project", scope="python.exec",
        ))
        bus = ToolBus(capability_engine=engine)
        desc = ToolDescriptor(
            tool_name="install_project",
            required_scopes=["python.exec", "pip.install"],
        )
        bus.register(desc, lambda path: (0, "ok", ""))
        result = bus.dispatch("install_project", ".")
        assert result.exit_code == -1
        assert "pip.install" in result.stderr

    def test_policy_allows_bypass(self):
        policy = PolicyPack(allowed_scopes=["shell.exec"])
        engine = CapabilityEngine(policy)
        bus = ToolBus(capability_engine=engine)
        desc = ToolDescriptor(
            tool_name="run_shell_command",
            required_scopes=["shell.exec"],
        )
        bus.register(desc, lambda cmd: (0, "ok", ""))
        result = bus.dispatch("run_shell_command", "ls")
        assert result.exit_code == 0


class TestToolBusNetworkGating:
    def test_network_denied(self):
        """Network tool denied when http.read not granted."""
        engine = CapabilityEngine()
        bus = ToolBus(capability_engine=engine)
        desc = ToolDescriptor(
            tool_name="perform_web_search",
            required_scopes=["http.read"],
            requires_network=True,
            network_scopes=["http.read"],
        )
        bus.register(desc, lambda q: "results")
        result = bus.dispatch("perform_web_search", "test")
        assert result.exit_code == -1
        assert "denied" in result.stderr.lower()

    def test_network_allowed(self):
        policy = PolicyPack(allowed_scopes=["http.read"])
        engine = CapabilityEngine(policy)
        bus = ToolBus(capability_engine=engine)
        desc = ToolDescriptor(
            tool_name="perform_web_search",
            required_scopes=["http.read"],
            requires_network=True,
            network_scopes=["http.read"],
        )
        bus.register(desc, lambda q: "results")
        result = bus.dispatch("perform_web_search", "test")
        assert result.exit_code == 0
        assert result.stdout == "results"


class TestToolBusActionAwareDispatch:
    """Phase 4a: action-aware dispatch for multi-action tools."""

    def _make_bus_with_scopes(self, scopes):
        policy = PolicyPack(allowed_scopes=scopes)
        engine = CapabilityEngine(policy)
        return ToolBus(capability_engine=engine)

    def test_action_specific_scope_check(self):
        bus = self._make_bus_with_scopes(["git.read"])
        desc = ToolDescriptor(
            tool_name="git",
            required_scopes=["git.read", "git.write", "git.push", "git.fetch"],
            action_scopes={
                "status": ["git.read"],
                "commit": ["git.write"],
            },
        )
        bus.register(desc, lambda action, **kw: (0, f"did {action}", ""))
        # git.read is granted — status should work
        result = bus.dispatch("git", action="status")
        assert result.exit_code == 0
        assert result.stdout == "did status"
        assert result.granted_scopes == ["git.read"]

    def test_action_denied_when_scope_missing(self):
        bus = self._make_bus_with_scopes(["git.read"])
        desc = ToolDescriptor(
            tool_name="git",
            required_scopes=["git.read", "git.write"],
            action_scopes={
                "status": ["git.read"],
                "commit": ["git.write"],
            },
        )
        bus.register(desc, lambda action, **kw: (0, "ok", ""))
        # git.write not granted — commit should be denied
        result = bus.dispatch("git", action="commit")
        assert result.exit_code == -1
        import json
        denial = json.loads(result.stderr)
        assert denial["error"] == "capability_denied"
        assert "git.write" in denial["missing_scopes"]
        assert denial["action"] == "commit"

    def test_no_action_uses_full_scopes(self):
        bus = self._make_bus_with_scopes(["fs.read"])
        desc = ToolDescriptor(
            tool_name="fs",
            required_scopes=["fs.read", "fs.write", "fs.delete"],
            action_scopes={"read": ["fs.read"]},
        )
        bus.register(desc, lambda: (0, "ok", ""))
        # Without action, checks all required_scopes — fs.write/delete missing
        result = bus.dispatch("fs")
        assert result.exit_code == -1

    def test_unknown_action_falls_back_to_required_scopes(self):
        bus = self._make_bus_with_scopes(["git.read", "git.write", "git.push", "git.fetch"])
        desc = ToolDescriptor(
            tool_name="git",
            required_scopes=["git.read", "git.write", "git.push", "git.fetch"],
            action_scopes={"status": ["git.read"]},
        )
        bus.register(desc, lambda action, **kw: (0, "ok", ""))
        # Unknown action falls back to full required_scopes
        result = bus.dispatch("git", action="unknown_action")
        assert result.exit_code == 0

    def test_action_passes_to_executor(self):
        bus = self._make_bus_with_scopes(["verify.run"])
        desc = ToolDescriptor(
            tool_name="verify",
            required_scopes=["verify.run"],
            action_scopes={"lint": ["verify.run"]},
        )
        captured = {}
        def executor(action, **kwargs):
            captured["action"] = action
            return (0, "ok", "")
        bus.register(desc, executor)
        bus.dispatch("verify", action="lint")
        assert captured["action"] == "lint"

    def test_describe_tool_includes_actions(self):
        bus = ToolBus()
        desc = ToolDescriptor(
            tool_name="git",
            action_scopes={"status": ["git.read"], "commit": ["git.write"]},
        )
        bus.register(desc, lambda: None)
        info = bus.describe_tool("git")
        assert "actions" in info
        assert "status" in info["actions"]
        assert "commit" in info["actions"]

    def test_structured_unknown_tool_error(self):
        bus = ToolBus()
        result = bus.dispatch("nonexistent")
        assert result.exit_code == -1
        import json
        error = json.loads(result.stderr)
        assert error["error"] == "unknown_tool"

    def test_evidence_field_on_denial(self):
        bus = ToolBus()
        desc = ToolDescriptor(tool_name="t", required_scopes=["x.y"])
        bus.register(desc, lambda: (0, "ok", ""))
        result = bus.dispatch("t")
        assert result.exit_code == -1
        assert result.evidence is not None
        import json
        evidence = json.loads(result.evidence)
        assert evidence["error"] == "capability_denied"


class TestToolBusProperties:
    def test_capability_engine_property(self):
        engine = CapabilityEngine()
        bus = ToolBus(capability_engine=engine)
        assert bus.capability_engine is engine

    def test_sandbox_property(self):
        sandbox = NoneSandbox()
        bus = ToolBus(sandbox=sandbox)
        assert bus.sandbox is sandbox

    def test_default_engine_and_sandbox(self):
        bus = ToolBus()
        assert isinstance(bus.capability_engine, CapabilityEngine)
        assert isinstance(bus.sandbox, NoneSandbox)
