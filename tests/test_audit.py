# tests/test_audit.py — AuditLogger tests

import json
import pytest
from pathlib import Path

from core.contracts.schemas import AuditEntry
from core.policy.audit import AuditLogger


@pytest.fixture
def audit_log(tmp_path):
    return AuditLogger(path=tmp_path / "audit.jsonl")


class TestAuditLogBasic:
    def test_log_creates_file(self, audit_log):
        audit_log.log(AuditEntry(event_type="test"))
        assert audit_log.path.exists()

    def test_log_appends_jsonl(self, audit_log):
        audit_log.log(AuditEntry(event_type="first"))
        audit_log.log(AuditEntry(event_type="second"))
        lines = audit_log.path.read_text().strip().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0])["event_type"] == "first"
        assert json.loads(lines[1])["event_type"] == "second"

    def test_log_preserves_fields(self, audit_log):
        audit_log.log(AuditEntry(
            event_type="tool_dispatch",
            tool_name="git",
            action="push",
            scopes=["git.push"],
            verdict="allowed",
            session_id="abc123",
        ))
        entries = audit_log.tail(1)
        assert entries[0]["tool_name"] == "git"
        assert entries[0]["action"] == "push"
        assert entries[0]["session_id"] == "abc123"

    def test_log_timestamp_is_iso(self, audit_log):
        audit_log.log(AuditEntry(event_type="test"))
        entry = audit_log.tail(1)[0]
        assert "T" in entry["timestamp"]  # ISO format


class TestAuditTail:
    def test_tail_empty_log(self, audit_log):
        assert audit_log.tail() == []

    def test_tail_returns_last_n(self, audit_log):
        for i in range(10):
            audit_log.log(AuditEntry(event_type=f"event_{i}"))
        entries = audit_log.tail(3)
        assert len(entries) == 3
        assert entries[0]["event_type"] == "event_7"
        assert entries[2]["event_type"] == "event_9"

    def test_tail_all_when_fewer(self, audit_log):
        audit_log.log(AuditEntry(event_type="only"))
        entries = audit_log.tail(100)
        assert len(entries) == 1

    def test_tail_nonexistent_file(self, tmp_path):
        logger = AuditLogger(path=tmp_path / "nope.jsonl")
        assert logger.tail() == []


class TestSecretRedaction:
    def test_redact_openai_key(self, audit_log):
        audit_log.log(AuditEntry(
            event_type="test",
            detail="key is sk-abc12345678901234567890",
        ))
        entry = audit_log.tail(1)[0]
        assert "sk-abc" not in entry["detail"]
        assert "[REDACTED]" in entry["detail"]

    def test_redact_github_token(self, audit_log):
        audit_log.log(AuditEntry(
            event_type="test",
            detail="token ghp_abcdefghijklmnopqrstuvwxyz012345678901",
        ))
        entry = audit_log.tail(1)[0]
        assert "ghp_" not in entry["detail"]
        assert "[REDACTED]" in entry["detail"]

    def test_redact_aws_key(self, audit_log):
        audit_log.log(AuditEntry(
            event_type="test",
            detail="aws AKIAIOSFODNN7EXAMPLE",
        ))
        entry = audit_log.tail(1)[0]
        assert "AKIA" not in entry["detail"]
        assert "[REDACTED]" in entry["detail"]

    def test_redact_slack_token(self, audit_log):
        audit_log.log(AuditEntry(
            event_type="test",
            detail="slack xoxb-123-456-abc",
        ))
        entry = audit_log.tail(1)[0]
        assert "xoxb-" not in entry["detail"]
        assert "[REDACTED]" in entry["detail"]

    def test_no_redaction_for_safe_text(self, audit_log):
        audit_log.log(AuditEntry(
            event_type="test",
            detail="just a normal command: ls -la",
        ))
        entry = audit_log.tail(1)[0]
        assert entry["detail"] == "just a normal command: ls -la"

    def test_multiple_secrets_redacted(self, audit_log):
        audit_log.log(AuditEntry(
            event_type="test",
            detail="key1=sk-aaaabbbbccccddddeeeefffff key2=AKIAIOSFODNN7EXAMPLE",
        ))
        entry = audit_log.tail(1)[0]
        assert entry["detail"].count("[REDACTED]") == 2
