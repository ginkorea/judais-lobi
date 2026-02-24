# tests/test_profile_schemas.py — ProfileMode, GodModeGrant, AuditEntry tests

import pytest
from datetime import datetime, timezone, timedelta
from core.contracts.schemas import ProfileMode, GodModeGrant, AuditEntry


class TestProfileMode:
    def test_values(self):
        assert ProfileMode.SAFE == "safe"
        assert ProfileMode.DEV == "dev"
        assert ProfileMode.OPS == "ops"
        assert ProfileMode.GOD == "god"

    def test_is_string(self):
        assert isinstance(ProfileMode.SAFE, str)

    def test_iteration_order(self):
        modes = list(ProfileMode)
        assert modes == [ProfileMode.SAFE, ProfileMode.DEV, ProfileMode.OPS, ProfileMode.GOD]

    def test_from_string(self):
        assert ProfileMode("safe") is ProfileMode.SAFE
        assert ProfileMode("god") is ProfileMode.GOD


class TestGodModeGrant:
    def test_defaults(self):
        g = GodModeGrant(reason="testing")
        assert g.activated_by == "user"
        assert g.reason == "testing"
        assert g.ttl_seconds == 300.0
        assert g.panic_revoked is False
        assert isinstance(g.activated_at, datetime)

    def test_custom_ttl(self):
        g = GodModeGrant(reason="deploy", ttl_seconds=60.0)
        assert g.ttl_seconds == 60.0

    def test_serialization(self):
        g = GodModeGrant(reason="test")
        data = g.model_dump()
        assert data["reason"] == "test"
        assert "activated_at" in data

    def test_panic_revoked(self):
        g = GodModeGrant(reason="test", panic_revoked=True)
        assert g.panic_revoked is True


class TestAuditEntry:
    def test_defaults(self):
        e = AuditEntry()
        assert e.event_type == ""
        assert e.tool_name == ""
        assert e.action == ""
        assert e.scopes == []
        assert e.verdict == ""

    def test_tool_dispatch_entry(self):
        e = AuditEntry(
            event_type="tool_dispatch",
            tool_name="git",
            action="push",
            scopes=["git.push"],
            verdict="allowed",
        )
        assert e.event_type == "tool_dispatch"
        assert e.tool_name == "git"
        assert e.action == "push"

    def test_serialization(self):
        e = AuditEntry(event_type="panic", profile="safe", verdict="panic_revoked")
        data = e.model_dump()
        assert data["event_type"] == "panic"
        assert data["profile"] == "safe"
