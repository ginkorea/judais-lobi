# core/policy/audit.py — Append-only JSONL audit logger with secret redaction

"""What this process did with its tools, written down where it can be read back.

Until 0.8.x this module was built, tested and reached by nobody: ``ToolBus``
accepted an ``audit=`` and ``Tools()`` never passed one, so the default
deployment — the one a platform actually spawns — kept no record of a single
tool call.  A framework that cannot say what it ran is not one you leave
unattended, so the logger is now attached by default and this module owns the
three decisions that made attaching it possible.

**Where the file goes.**  ``.judais-lobi/audit/<run-id>.jsonl`` under the
current directory, and the run id is generated once per process.  Per *run*
and not per *day*, because a mission has to be able to name its own audit
file on the stream (``mission_started.audit_ref``) and a name that also
covers everything else that ran today is not a reference to this mission.
The id sorts by time — ``20260815T131102-9f3a1c04`` — so a directory listing
is still chronological, and the random tail keeps two runs started in the
same second apart.

**How to move or silence it.**  ``JUDAIS_LOBI_AUDIT`` is either a path (used
verbatim, one file, parents created on first write) or one of ``none`` /
``off``, which disables auditing *explicitly*.  Explicitly is the point: a
disabled audit is announced on the console and travels on the stream as
``audit_ref: null``, so "there is no record of this run" is a fact a
consumer holds rather than one it has to infer from an empty directory.
Unset is the default path, never disabled — silence is not a setting anybody
chose.

**What never reaches the file.**  One list of patterns, here, applied to the
whole of ``detail`` — which is where the bus puts a dispatch's arguments, so
a token passed as a tool argument is covered by the same pass that covers a
token pasted into a message.  Two mechanisms, because they catch different
things:

* *shapes* — ``sk-…``, ``ghp_…``, ``AKIA…``, ``xox[bpsar]-…``, ``Bearer …``,
  and ``NAME=value`` / ``"NAME": "value"`` where the name ends in ``_KEY``,
  ``_TOKEN`` or ``_SECRET``;
* *values this process was given* — the value of every environment variable
  whose name ends in one of those suffixes (``MCP_TOKEN`` among them).  This
  is the half that matters, because a credential handed to a tool as an
  opaque argument looks like nothing in particular and no shape will find it.

Short environment values are left alone (:data:`AuditLogger.MIN_ENV_SECRET_LEN`):
a variable set to ``1`` or ``true`` would otherwise redact every digit in the
log and destroy the thing being protected.
"""

import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from core.durable import fsync_append
from core.redact import (
    MIN_SECRET_CHARS, SECRET_ENV_SUFFIXES, scrub_secrets, secret_values,
)
from core.contracts.schemas import AuditEntry

#: The variable a deployment moves or silences the audit log with.
AUDIT_ENV = "JUDAIS_LOBI_AUDIT"

#: Where the default file lives, relative to the current directory.
AUDIT_DIRNAME = Path(".judais-lobi") / "audit"

#: The two words that mean "no audit log at all", case-insensitively.
DISABLE_WORDS = frozenset({"none", "off"})

_RUN_ID: Optional[str] = None


def audit_run_id() -> str:
    """This process's run id, generated once and reused.

    One id per process rather than one per :class:`AuditLogger`, so that a
    caller building two :class:`~core.tools.Tools` registries — a chat one
    and a mission one, say — gets one file for the run rather than two
    halves of it that nothing relates.
    """
    global _RUN_ID
    if _RUN_ID is None:
        _RUN_ID = (datetime.now().strftime("%Y%m%dT%H%M%S")
                   + "-" + uuid.uuid4().hex[:8])
    return _RUN_ID


def audit_path(env: Optional[str] = None) -> Optional[Path]:
    """Where this run's audit log goes, or ``None`` for explicitly disabled.

    *env* is the raw value of :data:`AUDIT_ENV`; ``None`` reads the
    environment.  An unset or blank value is the default path — the absence
    of a setting is not a request to keep no records.
    """
    raw = os.getenv(AUDIT_ENV) if env is None else env
    value = (raw or "").strip()
    if not value:
        return Path.cwd() / AUDIT_DIRNAME / f"{audit_run_id()}.jsonl"
    if value.lower() in DISABLE_WORDS:
        return None
    return Path(value).expanduser()


def default_audit_logger(env: Optional[str] = None) -> Optional["AuditLogger"]:
    """The logger every default :class:`~core.tools.bus.ToolBus` gets.

    ``None`` only when :data:`AUDIT_ENV` says so in as many words.
    """
    path = audit_path(env)
    return None if path is None else AuditLogger(path=path)


class AuditLogger:
    """Append-only JSONL audit logger.

    Default path: this run's file under ``.judais-lobi/audit/`` — see
    :func:`audit_path`, which is the one place that decision is made.

    All entries are redacted for secrets before writing.
    """

    #: Redaction has ONE owner: :func:`core.redact.scrub_secrets`, the
    #: credential pass of the same redactor the mission stream runs — shapes
    #: (OpenAI, GitHub, AWS, Slack, ``Bearer …``, ``Authorization:``,
    #: ``*_KEY``/``*_TOKEN``/``*_SECRET``/``*_PASSWORD`` assignments) and the
    #: literal values of the credential-named environment variables this
    #: process was given.  Only the credential pass: the location passes
    #: (home directories, hostnames, venv paths) are deliberately not run
    #: here, because an operator's own audit record is *supposed* to name
    #: this host's files.  Values shorter than
    #: :data:`core.redact.MIN_SECRET_CHARS` are never treated as secrets.
    SECRET_ENV_SUFFIXES = SECRET_ENV_SUFFIXES
    MIN_ENV_SECRET_LEN = MIN_SECRET_CHARS

    def __init__(self, path: Optional[Path] = None):
        # ``audit_path("")`` and not ``audit_path()``: constructing a logger
        # is a decision to log, and reading the disable word here would give
        # back an object whose ``path`` nothing wrote to.  Disabling is
        # :func:`default_audit_logger`'s answer, and it says so by returning
        # nothing at all.
        self._path = Path(path) if path else audit_path("")

    @property
    def path(self) -> Path:
        return self._path

    def log(self, entry: AuditEntry) -> None:
        """Append an audit entry to the JSONL file.

        Secrets in the ``detail`` field are redacted before writing.

        The parent directory is created on the first write and not at
        construction: a logger nobody logs to must not leave a directory
        behind, which is exactly what a test suite constructing a default
        registry would otherwise scatter through the repository.  That is
        :func:`core.durable.fsync_append`'s rule now, and one owner of it.

        **And the line is on the disk before this returns.**  A buffered
        append returns as soon as the bytes are in the kernel, which is
        fine for a log nobody reads until later and wrong for this one:
        the audit file is what a run has to show for itself when the run
        did not survive, and the entries worth having are exactly the ones
        written in the minutes before a machine went down.  The
        ``fsync`` costs a syscall per dispatch — a dispatch that already
        cost a subprocess or a round trip to a server.
        """
        data = entry.model_dump()
        data["detail"] = self._redact(data.get("detail", ""))
        data["timestamp"] = data["timestamp"].isoformat()
        fsync_append(self._path, json.dumps(data, default=str))

    def tail(self, n: int = 20) -> List[dict]:
        """Read the last *n* entries from the audit log."""
        if not self._path.exists():
            return []
        lines = self._path.read_text(encoding="utf-8").strip().splitlines()
        entries = []
        for line in lines[-n:]:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return entries

    @classmethod
    def env_secrets(cls) -> List[str]:
        """Every credential-shaped environment value, longest first — read
        through the one owner, :func:`core.redact.secret_values`."""
        return secret_values()

    def _redact(self, text: str) -> str:
        """Credentials out, through :func:`core.redact.scrub_secrets`."""
        return scrub_secrets(text)
        for value in self.env_secrets():
            text = text.replace(value, "[REDACTED]")
        for pattern in self.SECRET_PATTERNS:
            text = pattern.sub(self._mask, text)
        return text
