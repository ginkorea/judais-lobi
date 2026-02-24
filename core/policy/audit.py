# core/policy/audit.py — Append-only JSONL audit logger with secret redaction

import json
import re
from pathlib import Path
from typing import List, Optional

from core.contracts.schemas import AuditEntry


class AuditLogger:
    """Append-only JSONL audit logger.

    Default path: ``~/.judais_lobi_audit.jsonl``

    All entries are redacted for secrets before writing.
    """

    SECRET_PATTERNS = [
        re.compile(r'(sk-[a-zA-Z0-9]{20,})'),                    # OpenAI keys
        re.compile(r'(ghp_[a-zA-Z0-9]{36,})'),                    # GitHub PATs
        re.compile(r'(AKIA[A-Z0-9]{16})'),                        # AWS access keys
        re.compile(r'(xox[bpsar]-[a-zA-Z0-9-]+)'),               # Slack tokens
    ]

    def __init__(self, path: Optional[Path] = None):
        self._path = Path(path) if path else Path.home() / ".judais_lobi_audit.jsonl"

    @property
    def path(self) -> Path:
        return self._path

    def log(self, entry: AuditEntry) -> None:
        """Append an audit entry to the JSONL file.

        Secrets in the ``detail`` field are redacted before writing.
        """
        data = entry.model_dump()
        data["detail"] = self._redact(data.get("detail", ""))
        data["timestamp"] = data["timestamp"].isoformat()
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(data, default=str) + "\n")

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

    def _redact(self, text: str) -> str:
        """Replace known secret patterns with [REDACTED]."""
        for pattern in self.SECRET_PATTERNS:
            text = pattern.sub("[REDACTED]", text)
        return text
