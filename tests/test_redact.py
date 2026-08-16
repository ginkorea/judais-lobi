# tests/test_redact.py — the one redactor, pattern by pattern

"""What a mission is allowed to say about the machine it ran on.

Table-driven on purpose.  A redactor is a list of patterns and the only
interesting question about each one is "in, and out"; a test file shaped like
prose hides which pattern is missing.  The negatives are as load-bearing as the
positives — a redactor that eats a URL a caller typed, or a tool result the
grounding validator is about to check, has broken the run it was protecting.

The environment is pinned by the ``pinned`` fixture rather than read off this
machine, so the table says the same thing on a laptop, in CI and on the pool.
"""

from __future__ import annotations

import os
import socket

import pytest

from core import redact
from core.redact import (
    SCRUBBED_FIELDS, VERBATIM_FIELDS, WHY_VERBATIM, redacted, scrub,
    scrub_record,
)

HOME = "/home/testuser"
HOSTNAME = "build01"
SECRET = "hunter2-hunter2"

#: The real, cached reader, kept before the autouse fixture replaces it with a
#: plain lambda.  ``TestWhereTheHostNamesComeFrom`` is the one place that wants
#: the reader itself rather than a fixed answer from it.
_REAL_HOSTNAMES = redact._local_hostnames


@pytest.fixture(autouse=True)
def pinned(monkeypatch, tmp_path):
    """One machine, whoever is running the tests.

    Every source the redactor reads at call time is fixed here: the home
    directory, the working directory, this host's names, and the set of
    secret-shaped environment variables — real ones are cleared so that a
    developer with an ``ANTHROPIC_API_KEY`` exported does not get a different
    answer from CI.
    """
    for name in list(os.environ):
        upper = name.upper()
        if upper.endswith(redact.SECRET_ENV_SUFFIXES):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HOME", HOME)
    monkeypatch.setenv("MISSION_API_KEY", SECRET)
    monkeypatch.setenv("MISSION_SHORT_TOKEN", "abc")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(redact, "_local_hostnames", lambda: (HOSTNAME,))
    return tmp_path


# ── every pattern, in and out ────────────────────────────────────────────────

#: ``(label, before, after)``.  The label is what a failure prints, so it names
#: the pattern rather than the string.
CASES = [
    ("a frame under this process's home",
     f'File "{HOME}/proj/app.py", line 12, in run',
     'File "<home>/proj/app.py", line 12, in run'),
    ("somebody else's home on this host",
     "PermissionError: /home/other/notes.md",
     "PermissionError: <home>/notes.md"),
    ("a macOS home",
     "FileNotFoundError: /Users/alice/Documents/report.txt",
     "FileNotFoundError: <home>/Documents/report.txt"),
    ("$HOME as a shell writes it",
     "looked in $HOME/bin",
     "looked in <home>/bin"),
    ("${HOME} as a shell writes it",
     "looked in ${HOME}/bin",
     "looked in <home>/bin"),
    ("a home inside a file:// URL, where the path rule would not have looked",
     f"could not open file://{HOME}/secret.txt",
     "could not open file://<home>/secret.txt"),
    ("a dependency's own frame keeps its module-relative tail",
     'File "/opt/venv/lib/python3.12/site-packages/httpx/_client.py", line 9',
     'File "<site-packages>/httpx/_client.py", line 9'),
    ("a Debian-packaged dependency is the same kind of frame",
     'File "/usr/lib/python3/dist-packages/urllib3/util.py", line 3',
     'File "<site-packages>/urllib3/util.py", line 3'),
    ("a standard-library frame keeps its module",
     'File "/usr/lib/python3.10/json/decoder.py", line 355',
     'File "<stdlib>/json/decoder.py", line 355'),
    ("a bare bearer token",
     "server said: Bearer abcdef1234567890 is expired",
     "server said: Bearer <redacted:bearer> is expired"),
    ("an Authorization header takes its value with it",
     "sent Authorization: Bearer abcdef1234567890",
     "sent Authorization: <redacted:Authorization>"),
    ("an OpenAI-shaped key that was never an environment variable",
     "401 for sk-abcdefghijklmnopqrst",
     f"401 for {redacted('api-key')}"),
    ("a GitHub PAT",
     "ghp_abcdefghijklmnopqrstuvwxyz0123456789 rejected",
     f"{redacted('github-token')} rejected"),
    ("an AWS access key id",
     "AKIAIOSFODNN7EXAMPLE denied",
     f"{redacted('aws-access-key-id')} denied"),
    ("a Slack token",
     "xoxb-1234-5678-abcdefgh revoked",
     f"{redacted('slack-token')} revoked"),
    ("the value of a secret-shaped environment variable, named not shown",
     f"connect failed with key {SECRET}",
     "connect failed with key <redacted:MISSION_API_KEY>"),
    ("this host, by name",
     f"cannot resolve {HOSTNAME} from here",
     "cannot resolve <host> from here"),
    ("an obviously internal FQDN",
     "connect to vault.build01.internal refused",
     "connect to <host> refused"),
    ("a .home.arpa name is the same shape",
     "printer.home.arpa is down",
     "<host> is down"),
]

#: The other half of the contract: things that look scrubbable and are not.
#: Each one is a way a redactor could break the run it was protecting.
SURVIVORS = [
    ("a URL a caller typed, which happens to have /home/ in its path",
     "GET https://example.com/home/joe/api returned 502"),
    ("loopback, which names nobody",
     "connect to http://localhost:8000/mcp refused"),
    ("loopback by address",
     "connect to 127.0.0.1:8000 refused"),
    ("a system binary, which names no person and no host",
     "ran /usr/bin/git and it exited 128"),
    ("a config file everybody has",
     "/etc/resolv.conf is empty"),
    ("a secret-shaped variable whose value is too short to be a secret",
     "the answer is abc"),
    ("prose with slashes in it",
     "yes/no, and/or, a/b"),
    ("a plain number, which is what a grounded answer is made of",
     "total_s: 80.847 across 3 assets"),
]


@pytest.mark.parametrize("label,before,after",
                         CASES, ids=[c[0] for c in CASES])
def test_the_pattern_is_removed(label, before, after):
    assert scrub(before) == after


@pytest.mark.parametrize("label,text",
                         SURVIVORS, ids=[c[0] for c in SURVIVORS])
def test_what_is_data_survives(label, text):
    """This module scrubs error text, not data.  Every string here is
    something a caller typed or a tool measured, and rewriting any of it would
    make the harness lie about the run rather than about the host."""
    assert scrub(text) == text


@pytest.mark.parametrize("label,before,after",
                         CASES, ids=[c[0] for c in CASES])
def test_scrubbing_twice_is_scrubbing_once(label, before, after):
    """A swarm's sub-mission emits through its own runner and again through
    the swarm's.  If the tokens were themselves scrubbable the second pass
    would eat the first one's output."""
    assert scrub(scrub(before)) == scrub(before)


class TestTheEdgesOfTheString:
    def test_a_non_string_comes_back_unchanged(self):
        """``scrub`` is called on whatever a field holds. A field holding an
        int must not become a field holding ``'<...>'``."""
        for value in (None, 3, 4.5, True, ["a"], {"a": 1}):
            assert scrub(value) is value

    def test_an_empty_string_is_left_alone(self):
        assert scrub("") == ""

    def test_a_whole_traceback_keeps_its_shape(self):
        """A scrubbed traceback is still a traceback: the frames, the line
        numbers and the exception line survive, and only the locations move."""
        text = (
            "Traceback (most recent call last):\n"
            f'  File "{HOME}/proj/core/cli.py", line 4, in main\n'
            "    run()\n"
            '  File "/opt/venv/lib/python3.12/site-packages/httpx/_client.py",'
            " line 9, in send\n"
            "    raise ConnectError(url)\n"
            f"httpx.ConnectError: {HOME}/sock\n"
        )
        out = scrub(text)
        assert HOME not in out
        assert "<home>/proj/core/cli.py" in out
        assert "<site-packages>/httpx/_client.py" in out
        assert "line 9, in send" in out
        assert out.count("File \"") == 2
        assert out.endswith("httpx.ConnectError: <home>/sock\n")


class TestWhereTheHostNamesComeFrom:
    """The patched fixture proves the substitution; this proves the reading."""

    def test_gethostname_and_its_short_form_are_both_spellings(self, monkeypatch):
        monkeypatch.setattr(socket, "gethostname", lambda: "box7.corp.example")
        _REAL_HOSTNAMES.cache_clear()
        try:
            names = _REAL_HOSTNAMES()
            assert "box7.corp.example" in names
            assert "box7" in names
        finally:
            _REAL_HOSTNAMES.cache_clear()

    def test_loopback_is_never_a_name_worth_hiding(self, monkeypatch):
        monkeypatch.setattr(socket, "gethostname", lambda: "localhost")
        _REAL_HOSTNAMES.cache_clear()
        try:
            assert "localhost" not in _REAL_HOSTNAMES()
        finally:
            _REAL_HOSTNAMES.cache_clear()

    def test_a_missing_etc_hostname_is_not_an_error(self, monkeypatch):
        """A container without one is a container that still runs missions."""
        real = open

        def refuse(path, *a, **kw):
            if str(path) == "/etc/hostname":
                raise FileNotFoundError(path)
            return real(path, *a, **kw)

        monkeypatch.setattr("builtins.open", refuse)
        monkeypatch.setattr(socket, "gethostname", lambda: "box7")
        _REAL_HOSTNAMES.cache_clear()
        try:
            assert _REAL_HOSTNAMES() == ("box7",)
        finally:
            _REAL_HOSTNAMES.cache_clear()


class TestTheWorkingDirectory:
    def test_a_frame_under_the_cwd_keeps_its_repository_relative_tail(self, pinned):
        """The developer reading this still has to find the frame. A path
        deleted is a frame nobody can open."""
        assert scrub(f'File "{pinned}/core/runtime/mission.py", line 12') == \
            'File "<cwd>/core/runtime/mission.py", line 12'

    def test_the_cwd_wins_over_the_home_it_sits_in(self, monkeypatch, tmp_path):
        """A checkout under ``$HOME`` is the ordinary case, and ``<home>/…``
        would throw away the half of the path that identifies the file."""
        inside = tmp_path / "home" / "testuser" / "proj"
        inside.mkdir(parents=True)
        monkeypatch.setenv("HOME", str(tmp_path / "home" / "testuser"))
        monkeypatch.chdir(inside)
        assert scrub(f"{inside}/core/x.py") == "<cwd>/core/x.py"


class TestSecretsAreReadByNameAndRemovedByValue:
    def test_the_variable_is_named_and_the_value_is_not(self):
        out = scrub(f"Authorization failed for {SECRET}")
        assert SECRET not in out
        assert "MISSION_API_KEY" in out

    def test_a_credential_set_after_import_is_still_found(self, monkeypatch):
        """The names are read at call time. A redactor holding the
        environment as it was at import misses exactly the credential
        somebody was careful about."""
        monkeypatch.setenv("LATE_TOKEN", "zzzzzzzzzzzz")
        assert scrub("saw zzzzzzzzzzzz") == "saw <redacted:LATE_TOKEN>"

    def test_a_variable_that_is_not_secret_shaped_is_not_hunted(self, monkeypatch):
        """``MCP_URL`` is configuration, not a credential, and replacing every
        occurrence of a URL would delete the diagnostic."""
        monkeypatch.setenv("MCP_URL", "https://mcp.example.com/sse")
        assert scrub("connect https://mcp.example.com/sse failed") == \
            "connect https://mcp.example.com/sse failed"

    def test_the_longest_value_is_replaced_first(self, monkeypatch):
        """Two variables where one value is a prefix of the other: replacing
        the short one first would carve the long one in half and leave the
        tail of a credential in the message."""
        monkeypatch.setenv("SHORT_TOKEN", "abcdefgh")
        monkeypatch.setenv("LONG_TOKEN", "abcdefghijklmnop")
        assert scrub("key abcdefghijklmnop here") == \
            "key <redacted:LONG_TOKEN> here"


# ── which fields move, and which do not ──────────────────────────────────────


class TestTheFieldListIsTheContract:
    def test_no_field_is_on_both_lists(self):
        assert not (SCRUBBED_FIELDS & VERBATIM_FIELDS)

    def test_every_verbatim_field_says_why(self):
        """The reasons live in one place so the next person to add a field
        finds the argument instead of reinventing it."""
        assert set(WHY_VERBATIM) == set(VERBATIM_FIELDS)
        for name, why in WHY_VERBATIM.items():
            assert len(why) > 20, name

    def test_the_evidence_is_not_touched(self):
        """``output`` is what the grounding validator checks the answer
        against, byte for byte, out of the mission store. A stream whose copy
        had been rewritten would show a pane an answer citing an identifier
        the pane can no longer find."""
        leak = f"{HOME}/data/corpus.abc123"
        record = scrub_record({
            "event": "tool_result", "tool": "catalog.search",
            "arguments": {"q": leak}, "ok": True, "exit_code": 0,
            "output": leak, "error": f"warning from {leak}",
            "handle": "r1", "truncated": False,
        })
        assert record["output"] == leak
        assert record["arguments"] == {"q": leak}
        assert record["error"] == "warning from <home>/data/corpus.abc123"

    def test_an_argument_called_text_is_still_an_argument(self):
        """Names are matched at any depth, so recursion has to stop at a
        verbatim field or a tool argument that happens to be called ``text``
        would be scrubbed as if it were an answer."""
        record = scrub_record({
            "event": "tool_call", "index": 0, "tool": "search",
            "arguments": {"text": f"{HOME}/q", "nested": {"error": f"{HOME}/n"}},
        })
        assert record["arguments"]["text"] == f"{HOME}/q"
        assert record["arguments"]["nested"]["error"] == f"{HOME}/n"

    def test_a_nested_detail_is_reached(self):
        """``grounding.checks[*].detail`` is covered by naming ``detail``
        once, which is the whole reason the list is names and not paths."""
        record = scrub_record({
            "event": "grounding", "ran": True, "caveat": f"see {HOME}/a",
            "silent": ["identifier"],
            "checks": [{"check": "identifier", "detail": f"in {HOME}/b",
                        "unsupported": [f"{HOME}/c"]}],
        })
        assert record["caveat"] == "see <home>/a"
        assert record["checks"][0]["detail"] == "in <home>/b"
        assert record["checks"][0]["unsupported"] == ["<home>/c"]
        assert record["checks"][0]["check"] == "identifier"
        assert record["silent"] == ["identifier"]

    def test_the_record_that_went_in_is_not_mutated(self):
        """The runner keeps its own transcript; a redactor that edited the
        dict in place would rewrite the mission's memory of itself."""
        original = {"event": "answer", "text": f"{HOME}/a", "outcome": "answered"}
        scrub_record(original)
        assert original["text"] == f"{HOME}/a"

    def test_a_redactor_that_raises_fails_closed(self, monkeypatch):
        """An unscrubbed traceback on somebody's browser is the one outcome
        this module exists to prevent, so a broken redactor drops the text
        rather than passing it through."""
        monkeypatch.setattr(redact, "_walk",
                            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom")))
        record = scrub_record({"event": "answer", "text": f"{HOME}/a",
                               "outcome": "answered"})
        assert record["text"] == redact.FAILED
        assert record["outcome"] == "answered"
