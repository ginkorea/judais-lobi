# tests/test_critic_redactor.py — Tests for core.critic.redactor

"""The critique payload's redaction, now that it has one owner.

This module used to carry its own list of credential shapes — an OpenAI
key, a GitHub PAT, an AWS access key id, a Slack token — beside the audit
logger's list and the stream scrubber's. Three lists of one fact, and the
copy that drifts is the one discovered by a leak. The credential pass is
`core.redact.scrub_secrets` now and the location pass is `core.redact.scrub`;
what is left here is the two address shapes those two deliberately do not
touch, and the byte clamp.

The assertions changed with the owner. `[REDACTED]` said only that
*something* was taken out; `<redacted:api-key>` says what, and that is the
difference between a reader who can act on a redacted line and one who
cannot — so the tests name the token rather than testing for a hole.
"""

from core.critic.redactor import REDACTION_MARK, Redactor, was_redacted
from core.redact import scrub_secrets


def test_normal_redaction():
    r = Redactor(level="normal")
    text = "key sk-abc12345678901234567890 and ghp_abcdefabcdefabcdefabcdefabcdefabcd"
    redacted = r.redact(text)
    assert "sk-abc" not in redacted
    assert "ghp_" not in redacted
    assert redacted == "key <redacted:api-key> and <redacted:github-token>", (
        "the token names what was taken out; `[REDACTED]` did not")


def test_normal_redaction_is_the_shared_credential_pass_and_nothing_else():
    """One owner, asserted rather than described.

    A second list of credential shapes in this file would pass every test
    above while diverging from `core.redact` on the next provider prefix.
    """
    text = "sk-abc12345678901234567890 in /home/somebody at api.example.com"
    assert Redactor(level="normal").redact(text) == scrub_secrets(text)


def test_strict_redaction():
    r = Redactor(level="strict")
    text = "email test@example.com ip 192.168.1.1 host api.example.com /home/user"
    redacted = r.redact(text)
    assert "example.com" not in redacted
    assert "192.168" not in redacted
    assert "/home/user" not in redacted
    assert "<redacted:email>" in redacted
    assert "<redacted:ipv4>" in redacted
    assert "<home>" in redacted, (
        "the home directory is `core.redact.scrub`'s to rewrite, and it "
        "writes `<home>` — a second spelling here would be a second owner")


def test_strict_also_takes_the_credentials():
    """Strict is a superset. A level that widened the location scope and
    dropped the credential pass would be the worst of the two."""
    redacted = Redactor(level="strict").redact("sk-abc12345678901234567890")
    assert "<redacted:api-key>" in redacted


def test_normal_leaves_the_addresses_alone():
    """The levels have to differ, or `normal` is a word with no effect."""
    text = "host api.example.com and 192.168.1.1"
    assert Redactor(level="normal").redact(text) == text


def test_redact_and_clamp():
    r = Redactor(level="normal", max_bytes=10)
    text = "sk-abcdef123456789012345678901234567890"
    redacted, payload_hash, was_clamped, original_size = r.redact_and_clamp(text)
    assert was_clamped is True
    assert original_size > 10
    assert payload_hash
    assert "[TRUNCATED]" in redacted


def test_the_clamp_never_stands_in_for_the_redaction():
    """A payload cut to size with the key still inside it has leaked it."""
    key = "sk-abcdef123456789012345678901234567890"
    text = key + " " + "x" * 200_000
    redacted, _hash, was_clamped, _size = Redactor(
        level="normal", max_bytes=1024).redact_and_clamp(text)
    assert was_clamped is True
    assert key not in redacted
    assert redacted.startswith("<redacted:api-key>")


def test_was_redacted_reads_the_mark():
    assert was_redacted("a <redacted:api-key> b")
    assert not was_redacted("nothing was taken out")
    assert REDACTION_MARK in "<redacted:api-key>"
