# tests/test_bus_grants.py
# End-to-end: ToolBus + SessionManager grant persistence + replay

import json
import pytest
from datetime import datetime, timezone, timedelta
from pathlib import Path

from core.tools.bus import ToolBus, ToolResult
from core.tools.capability import CapabilityEngine
from core.tools.descriptors import ToolDescriptor
from core.contracts.schemas import PermissionGrant, PolicyPack, ToolTrace
from core.sessions.manager import SessionManager


@pytest.fixture
def session_mgr(tmp_path):
    return SessionManager(tmp_path)


@pytest.fixture
def engine():
    return CapabilityEngine()


@pytest.fixture
def bus(engine):
    bus = ToolBus(capability_engine=engine)
    desc = ToolDescriptor(
        tool_name="test_tool",
        required_scopes=["test.scope"],
        description="A test tool",
    )
    bus.register(desc, lambda: (0, "ok", ""))
    return bus


class TestGrantPersistence:
    def test_write_grant_to_session(self, session_mgr):
        grant = PermissionGrant(tool_name="test_tool", scope="test.scope")
        path = session_mgr.write_grant(grant)
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["tool_name"] == "test_tool"
        assert data["scope"] == "test.scope"

    def test_write_multiple_grants(self, session_mgr):
        g1 = PermissionGrant(tool_name="a", scope="x")
        g2 = PermissionGrant(tool_name="b", scope="y")
        p1 = session_mgr.write_grant(g1)
        p2 = session_mgr.write_grant(g2)
        assert "grant_000" in p1.name
        assert "grant_001" in p2.name

    def test_load_grants(self, session_mgr):
        g1 = PermissionGrant(tool_name="a", scope="x")
        g2 = PermissionGrant(tool_name="b", scope="y")
        session_mgr.write_grant(g1)
        session_mgr.write_grant(g2)
        loaded = session_mgr.load_grants()
        assert len(loaded) == 2
        assert loaded[0]["tool_name"] == "a"
        assert loaded[1]["tool_name"] == "b"


class TestGrantReplay:
    def test_replay_grants_into_engine(self, session_mgr, engine, bus):
        """Save grants, load them, inject into engine, verify tool dispatch works."""
        # 1. Write grant
        grant = PermissionGrant(tool_name="test_tool", scope="test.scope")
        session_mgr.write_grant(grant)

        # 2. Load grants from session
        raw_grants = session_mgr.load_grants()
        grants = [PermissionGrant(**g) for g in raw_grants]

        # 3. New engine for replay
        replay_engine = CapabilityEngine()
        replay_engine.load_grants(grants)

        # 4. Create new bus with replayed engine
        replay_bus = ToolBus(capability_engine=replay_engine)
        desc = ToolDescriptor(
            tool_name="test_tool",
            required_scopes=["test.scope"],
        )
        replay_bus.register(desc, lambda: (0, "replayed", ""))

        # 5. Dispatch should succeed
        result = replay_bus.dispatch("test_tool")
        assert result.exit_code == 0
        assert result.stdout == "replayed"

    def test_replay_without_grant_denied(self, engine, bus):
        """Without replayed grants, tool dispatch is denied."""
        result = bus.dispatch("test_tool")
        assert result.exit_code == -1
        assert "denied" in result.stderr.lower()


class TestTimeScopedGrantReplay:
    def test_fresh_time_scoped_grant_works(self, session_mgr, engine, bus):
        grant = PermissionGrant(
            tool_name="test_tool", scope="test.scope",
            grant_duration_seconds=3600.0,
        )
        session_mgr.write_grant(grant)

        raw = session_mgr.load_grants()
        replay_engine = CapabilityEngine()
        replay_engine.load_grants([PermissionGrant(**g) for g in raw])

        replay_bus = ToolBus(capability_engine=replay_engine)
        replay_bus.register(
            ToolDescriptor(tool_name="test_tool", required_scopes=["test.scope"]),
            lambda: (0, "ok", ""),
        )
        result = replay_bus.dispatch("test_tool")
        assert result.exit_code == 0

    def test_expired_time_scoped_grant_denied(self, session_mgr):
        grant = PermissionGrant(
            tool_name="test_tool", scope="test.scope",
            grant_issued_at=datetime.now(timezone.utc) - timedelta(hours=2),
            grant_duration_seconds=60.0,
        )
        session_mgr.write_grant(grant)

        raw = session_mgr.load_grants()
        engine = CapabilityEngine()
        engine.load_grants([PermissionGrant(**g) for g in raw])

        bus = ToolBus(capability_engine=engine)
        bus.register(
            ToolDescriptor(tool_name="test_tool", required_scopes=["test.scope"]),
            lambda: (0, "ok", ""),
        )
        result = bus.dispatch("test_tool")
        assert result.exit_code == -1


class TestInvocationScopedGrantReplay:
    def test_invocation_grant_consumed_after_one_use(self, session_mgr):
        grant = PermissionGrant(
            tool_name="test_tool", scope="test.scope",
            grant_scope="invocation",
        )
        session_mgr.write_grant(grant)

        raw = session_mgr.load_grants()
        engine = CapabilityEngine()
        engine.load_grants([PermissionGrant(**g) for g in raw])

        bus = ToolBus(capability_engine=engine)
        bus.register(
            ToolDescriptor(tool_name="test_tool", required_scopes=["test.scope"]),
            lambda: (0, "ok", ""),
        )

        # First call succeeds
        r1 = bus.dispatch("test_tool")
        assert r1.exit_code == 0

        # Second call denied
        r2 = bus.dispatch("test_tool")
        assert r2.exit_code == -1


class TestToolTracePersistence:
    def test_write_and_load_traces(self, session_mgr):
        trace = ToolTrace(
            tool_name="test_tool",
            payload_summary="echo hello",
            exit_code=0,
            stdout_excerpt="hello",
            scopes_used=["shell.exec"],
        )
        path = session_mgr.write_tool_trace(trace)
        assert path.exists()

        traces = session_mgr.load_tool_traces()
        assert len(traces) == 1
        assert traces[0]["tool_name"] == "test_tool"
        assert traces[0]["exit_code"] == 0

    def test_multiple_traces(self, session_mgr):
        for i in range(3):
            trace = ToolTrace(tool_name=f"tool_{i}", exit_code=i)
            session_mgr.write_tool_trace(trace)
        traces = session_mgr.load_tool_traces()
        assert len(traces) == 3
