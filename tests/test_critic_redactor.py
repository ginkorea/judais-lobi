# tests/test_critic_redactor.py — Tests for core.critic.redactor

from core.critic.redactor import Redactor


def test_normal_redaction():
    r = Redactor(level="normal")
    text = "key sk-abc12345678901234567890 and ghp_abcdefabcdefabcdefabcdefabcdefabcd"
    redacted = r.redact(text)
    assert "sk-abc" not in redacted
    assert "ghp_" not in redacted
    assert "[REDACTED]" in redacted


def test_strict_redaction():
    r = Redactor(level="strict")
    text = "email test@example.com ip 192.168.1.1 host api.example.com /home/user"
    redacted = r.redact(text)
    assert "example.com" not in redacted
    assert "192.168" not in redacted
    assert "/home/user" not in redacted


def test_redact_and_clamp():
    r = Redactor(level="normal", max_bytes=10)
    text = "sk-abcdef123456789012345678901234567890"
    redacted, payload_hash, was_clamped, original_size = r.redact_and_clamp(text)
    assert was_clamped is True
    assert original_size > 10
    assert payload_hash
    assert "[TRUNCATED]" in redacted
