# tests/test_audit.py — AuditLogger tests

import json
import pytest
from pathlib import Path

from core.contracts.schemas import AuditEntry
from core.policy.audit import (
    AUDIT_ENV,
    AuditLogger,
    audit_path,
    audit_run_id,
    default_audit_logger,
)


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

    def test_redact_bearer_token_keeps_the_word(self, audit_log):
        """A bearer credential is the one this harness is handed most often —
        ``--mcp-token`` is exactly that — and it has no distinguishing shape
        at all. The word survives because "a bearer credential was passed" is
        worth reading; the token does not."""
        audit_log.log(AuditEntry(
            event_type="test",
            detail='{"Authorization": "Bearer eyJhbGciOiJIUzI1NiJ9.payload"}',
        ))
        detail = audit_log.tail(1)[0]["detail"]
        assert "eyJhbGciOiJIUzI1NiJ9" not in detail
        assert "Bearer [REDACTED]" in detail

    def test_redact_lowercase_bearer(self, audit_log):
        audit_log.log(AuditEntry(
            event_type="test", detail="curl -H 'authorization: bearer sh0rtish-but-long-enough'",
        ))
        detail = audit_log.tail(1)[0]["detail"]
        assert "sh0rtish" not in detail
        assert "bearer [REDACTED]" in detail

    @pytest.mark.parametrize("name", ["MCP_TOKEN", "SOME_API_KEY", "APP_SECRET"])
    def test_redact_an_assignment_to_a_credential_name(self, audit_log, name):
        """``NAME=value`` and ``"NAME": "value"`` for anything ending in
        ``_KEY``/``_TOKEN``/``_SECRET``. The name stays: which credential was
        passed is the part of the entry worth having."""
        audit_log.log(AuditEntry(
            event_type="test", detail=f"{name}=zzzz-the-actual-value",
        ))
        detail = audit_log.tail(1)[0]["detail"]
        assert "zzzz-the-actual-value" not in detail
        assert f"{name}=[REDACTED]" in detail

    def test_redact_a_credential_name_in_json(self, audit_log):
        audit_log.log(AuditEntry(
            event_type="test", detail='{"MCP_TOKEN": "zzzz-the-actual-value"}',
        ))
        detail = audit_log.tail(1)[0]["detail"]
        assert "zzzz-the-actual-value" not in detail
        assert "[REDACTED]" in detail

    def test_a_name_that_merely_contains_key_is_left_alone(self, audit_log):
        """``keystore=…`` and ``monkey=…`` are not credentials. A redactor
        that eats ordinary arguments is one an operator learns to ignore."""
        audit_log.log(AuditEntry(
            event_type="test", detail="keystore=/var/lib/keys monkey=business",
        ))
        assert audit_log.tail(1)[0]["detail"] == (
            "keystore=/var/lib/keys monkey=business")


class TestRedactingWhatTheEnvironmentGave:
    """The half that matters.

    A credential handed to a tool as an opaque argument — ``fetch(url=…,
    token="hunter2hunter2")`` — matches no shape whatsoever, so no pattern
    list will ever find it. What the harness *does* know is which values it
    was started with, and those are redacted wherever they appear.
    """

    def test_the_value_of_a_token_variable_is_redacted_anywhere(
            self, audit_log, monkeypatch):
        monkeypatch.setenv("MCP_TOKEN", "opaque-value-nothing-would-match")
        audit_log.log(AuditEntry(
            event_type="test",
            detail='{"args": [], "kwargs": {"auth": "opaque-value-nothing-would-match"}}',
        ))
        detail = audit_log.tail(1)[0]["detail"]
        assert "opaque-value-nothing-would-match" not in detail
        assert "[REDACTED]" in detail

    @pytest.mark.parametrize("name", ["X_KEY", "X_TOKEN", "X_SECRET"])
    def test_every_declared_suffix(self, audit_log, monkeypatch, name):
        monkeypatch.setenv(name, "value-of-" + name.lower() + "-here")
        audit_log.log(AuditEntry(
            event_type="test", detail="saw value-of-" + name.lower() + "-here",
        ))
        assert "value-of-" not in audit_log.tail(1)[0]["detail"]

    def test_a_variable_that_is_not_credential_named_is_not_a_secret(
            self, audit_log, monkeypatch):
        """``LOCAL_MODEL=gpt-oss-20b`` is configuration, and an audit log with
        the model name blanked out of every line is a worse log."""
        monkeypatch.setenv("LOCAL_MODEL", "gpt-oss-20b-served")
        audit_log.log(AuditEntry(event_type="test", detail="model gpt-oss-20b-served"))
        assert audit_log.tail(1)[0]["detail"] == "model gpt-oss-20b-served"

    def test_a_short_value_is_not_treated_as_a_secret(
            self, audit_log, monkeypatch):
        """``DEBUG_TOKEN=1`` would otherwise redact every ``1`` in the file,
        which is a redactor destroying the record it exists to protect."""
        monkeypatch.setenv("DEBUG_TOKEN", "1")
        audit_log.log(AuditEntry(event_type="test", detail="exit_code 1 in 1 step"))
        assert audit_log.tail(1)[0]["detail"] == "exit_code 1 in 1 step"

    def test_the_longest_value_wins_when_one_contains_another(
            self, audit_log, monkeypatch):
        """A prefix redacted first would leave the tail of the longer secret
        sitting in the file next to a ``[REDACTED]``."""
        monkeypatch.setenv("A_TOKEN", "abcdefgh")
        monkeypatch.setenv("B_TOKEN", "abcdefgh-and-more")
        audit_log.log(AuditEntry(event_type="test", detail="tok abcdefgh-and-more"))
        assert audit_log.tail(1)[0]["detail"] == "tok [REDACTED]"

    def test_env_secrets_lists_only_credential_names(self, monkeypatch):
        monkeypatch.setenv("WHATEVER_TOKEN", "long-enough-value")
        monkeypatch.setenv("WHATEVER_HOST", "long-enough-value-too")
        assert "long-enough-value" in AuditLogger.env_secrets()
        assert "long-enough-value-too" not in AuditLogger.env_secrets()


class TestWhereTheFileGoes:
    """The path decision, which has exactly one owner: :func:`audit_path`."""

    def test_the_default_is_one_file_per_run_under_the_working_directory(
            self, tmp_path, monkeypatch):
        """Per RUN and not per DAY, because a mission names its own audit
        file on the stream and a name that also covers everything else that
        ran today is not a reference to this mission."""
        monkeypatch.delenv(AUDIT_ENV, raising=False)
        monkeypatch.chdir(tmp_path)
        path = audit_path()
        assert path.parent == tmp_path / ".judais-lobi" / "audit"
        assert path.name == f"{audit_run_id()}.jsonl"

    def test_the_run_id_is_generated_once_per_process(self):
        """Two registries built by one process share a file rather than
        splitting the run into halves nothing relates."""
        assert audit_run_id() == audit_run_id()

    def test_the_run_id_sorts_by_time_and_is_unique(self):
        stamp, _, tail = audit_run_id().partition("-")
        assert len(stamp) == len("YYYYmmddTHHMMSS") and stamp[8] == "T"
        assert len(tail) == 8

    def test_an_env_path_is_used_verbatim(self, tmp_path):
        assert audit_path(str(tmp_path / "elsewhere.jsonl")) == \
            tmp_path / "elsewhere.jsonl"

    @pytest.mark.parametrize("word", ["none", "off", "NONE", " Off "])
    def test_the_disable_words_mean_no_file_at_all(self, word):
        assert audit_path(word) is None
        assert default_audit_logger(word) is None

    def test_blank_is_not_a_request_to_stop_auditing(self, tmp_path, monkeypatch):
        """An unset or empty variable is the absence of a setting. Silence is
        not something anybody chose, and the default has to come down on the
        side of keeping records."""
        monkeypatch.chdir(tmp_path)
        assert audit_path("") is not None
        assert audit_path("   ") is not None

    def test_default_audit_logger_writes_where_the_env_says(self, tmp_path):
        target = tmp_path / "nested" / "run.jsonl"
        logger = default_audit_logger(str(target))
        logger.log(AuditEntry(event_type="test"))
        assert target.exists()

    def test_the_directory_is_made_on_the_first_write_and_not_before(
            self, tmp_path):
        """A logger nobody logs to must leave nothing behind — otherwise a
        test suite that merely builds a default registry scatters empty
        directories through the checkout."""
        target = tmp_path / "made" / "later" / "run.jsonl"
        logger = AuditLogger(path=target)
        assert not target.parent.exists()
        logger.log(AuditEntry(event_type="test"))
        assert target.parent.exists()

    def test_a_logger_with_no_path_lands_on_the_default(self, tmp_path, monkeypatch):
        monkeypatch.delenv(AUDIT_ENV, raising=False)
        monkeypatch.chdir(tmp_path)
        assert AuditLogger().path.parent == tmp_path / ".judais-lobi" / "audit"

    def test_a_logger_with_no_path_ignores_the_disable_word(
            self, tmp_path, monkeypatch):
        """Constructing a logger IS a decision to log. Disabling is
        ``default_audit_logger``'s answer and it says so by returning
        nothing — an object whose ``path`` nothing ever writes to would be a
        third state nobody asked for."""
        monkeypatch.setenv(AUDIT_ENV, "off")
        monkeypatch.chdir(tmp_path)
        assert AuditLogger().path.parent == tmp_path / ".judais-lobi" / "audit"
