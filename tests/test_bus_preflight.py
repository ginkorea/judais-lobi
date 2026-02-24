# tests/test_bus_preflight.py — Preflight hooks, panic, audit in ToolBus

import json
import pytest

from core.tools.bus import ToolBus, ToolResult
from core.tools.descriptors import ToolDescriptor, HIGH_RISK_ACTIONS
from core.tools.capability import CapabilityEngine
from core.contracts.schemas import PolicyPack, AuditEntry
from core.policy.audit import AuditLogger
from core.policy.god_mode import GodModeSession


@pytest.fixture
def permissive_engine():
    return CapabilityEngine(PolicyPack(allowed_scopes=[
        "git.read", "git.write", "git.push", "git.fetch",
        "fs.read", "fs.write", "fs.delete",
    ]))


@pytest.fixture
def audit(tmp_path):
    return AuditLogger(path=tmp_path / "audit.jsonl")


@pytest.fixture
def god(audit):
    return GodModeSession(audit)


GIT_DESC = ToolDescriptor(
    tool_name="git",
    required_scopes=["git.read", "git.write", "git.push", "git.fetch"],
    action_scopes={
        "status": ["git.read"],
        "push": ["git.push"],
        "reset": ["git.write"],
    },
)


class TestPreflightHook:
    def test_high_risk_action_triggers_preflight(self, permissive_engine):
        captured = []
        bus = ToolBus(
            capability_engine=permissive_engine,
            preflight_hook=lambda ann: captured.append(ann),
        )
        bus.register(GIT_DESC, lambda action, **kw: (0, "ok", ""))
        bus.dispatch("git", action="push")
        assert len(captured) == 1
        assert captured[0]["type"] == "preflight"
        assert captured[0]["tool"] == "git"
        assert captured[0]["action"] == "push"

    def test_safe_action_no_preflight(self, permissive_engine):
        captured = []
        bus = ToolBus(
            capability_engine=permissive_engine,
            preflight_hook=lambda ann: captured.append(ann),
        )
        bus.register(GIT_DESC, lambda action, **kw: (0, "ok", ""))
        bus.dispatch("git", action="status")
        assert len(captured) == 0

    def test_no_hook_no_error(self, permissive_engine):
        bus = ToolBus(capability_engine=permissive_engine)
        bus.register(GIT_DESC, lambda action, **kw: (0, "ok", ""))
        result = bus.dispatch("git", action="push")
        assert result.exit_code == 0


class TestPanicSwitch:
    def test_panic_blocks_all_dispatch(self, permissive_engine, audit, god):
        god.activate(reason="test", capability_engine=permissive_engine)
        god.panic(capability_engine=permissive_engine)

        bus = ToolBus(
            capability_engine=permissive_engine,
            god_mode=god,
        )
        bus.register(GIT_DESC, lambda action, **kw: (0, "ok", ""))
        result = bus.dispatch("git", action="status")
        assert result.exit_code == -1
        error = json.loads(result.stderr)
        assert error["error"] == "panic_revoked"

    def test_panic_blocks_even_safe_tools(self, audit, god):
        engine = CapabilityEngine(PolicyPack(allowed_scopes=["fs.read"]))
        god.activate(reason="test", capability_engine=engine)
        god.panic(capability_engine=engine)

        bus = ToolBus(capability_engine=engine, god_mode=god)
        desc = ToolDescriptor(tool_name="t", required_scopes=["fs.read"])
        bus.register(desc, lambda: (0, "ok", ""))
        result = bus.dispatch("t")
        assert result.exit_code == -1

    def test_no_god_mode_no_panic_check(self, permissive_engine):
        bus = ToolBus(capability_engine=permissive_engine)
        bus.register(GIT_DESC, lambda action, **kw: (0, "ok", ""))
        result = bus.dispatch("git", action="status")
        assert result.exit_code == 0


class TestBusAuditLogging:
    def test_successful_dispatch_logged(self, permissive_engine, audit):
        bus = ToolBus(capability_engine=permissive_engine, audit=audit)
        bus.register(GIT_DESC, lambda action, **kw: (0, "ok", ""))
        bus.dispatch("git", action="status")
        entries = audit.tail()
        assert len(entries) >= 1
        assert entries[-1]["event_type"] == "tool_dispatch"
        assert entries[-1]["verdict"] == "allowed"
        assert entries[-1]["tool_name"] == "git"
        assert entries[-1]["action"] == "status"

    def test_denied_dispatch_logged(self, audit):
        engine = CapabilityEngine()  # deny all
        bus = ToolBus(capability_engine=engine, audit=audit)
        bus.register(GIT_DESC, lambda action, **kw: (0, "ok", ""))
        bus.dispatch("git", action="push")
        entries = audit.tail()
        assert any(e["verdict"] == "denied" for e in entries)

    def test_panic_dispatch_logged(self, permissive_engine, audit, god):
        god.activate(reason="test", capability_engine=permissive_engine)
        god.panic(capability_engine=permissive_engine)
        bus = ToolBus(
            capability_engine=permissive_engine,
            god_mode=god,
            audit=audit,
        )
        bus.register(GIT_DESC, lambda action, **kw: (0, "ok", ""))
        bus.dispatch("git", action="status")
        entries = audit.tail()
        verdicts = [e["verdict"] for e in entries]
        assert "panic_revoked" in verdicts

    def test_no_audit_no_error(self, permissive_engine):
        bus = ToolBus(capability_engine=permissive_engine)
        bus.register(GIT_DESC, lambda action, **kw: (0, "ok", ""))
        result = bus.dispatch("git", action="status")
        assert result.exit_code == 0
