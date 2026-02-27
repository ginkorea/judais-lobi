# core/critic/redactor.py — Secret stripping + payload clamping

from __future__ import annotations

import hashlib
import re
from typing import Iterable, Tuple


class Redactor:
    """Redacts secrets and optionally sensitive metadata from text."""

    NORMAL_PATTERNS = [
        re.compile(r"(sk-[a-zA-Z0-9]{20,})"),                 # OpenAI keys
        re.compile(r"(sk-ant-[a-zA-Z0-9]{20,})"),             # Anthropic keys
        re.compile(r"(ghp_[a-zA-Z0-9]{36,})"),                # GitHub PATs
        re.compile(r"(gho_[a-zA-Z0-9]{36,})"),                # GitHub OAuth tokens
        re.compile(r"(glpat-[a-zA-Z0-9\-]{20,})"),            # GitLab PATs
        re.compile(r"(AKIA[0-9A-Z]{16})"),                    # AWS access keys
        re.compile(r"(xox[bpsar]-[a-zA-Z0-9-]+)"),            # Slack tokens
        re.compile(r"(AIza[0-9A-Za-z\-_]{35})"),             # Google API keys
        re.compile(r"(?i)(password\s*[:=]\s*[^\s]+)"),
        re.compile(
            r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----.*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
            re.DOTALL,
        ),
        re.compile(
            r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----",
            re.DOTALL,
        ),
    ]

    STRICT_PATTERNS = [
        re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),              # IPv4
        re.compile(r"\b(?:[0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F]{0,4}\b"),  # IPv6
        re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),   # emails
        re.compile(r"\b[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b"),           # hostnames
        re.compile(r"/home/[A-Za-z0-9._-]+"),                        # /home/user
    ]

    def __init__(self, level: str = "strict", max_bytes: int = 65_536):
        self.level = level
        self.max_bytes = max_bytes

    def redact(self, text: str) -> str:
        redacted = text
        for pattern in self._patterns():
            redacted = pattern.sub("[REDACTED]", redacted)
        return redacted

    def redact_and_clamp(self, text: str) -> Tuple[str, str, bool, int]:
        redacted = self.redact(text)
        original_size = len(text.encode("utf-8", errors="ignore"))

        clamped = redacted
        was_clamped = False
        if self.max_bytes and original_size > self.max_bytes:
            suffix = " [TRUNCATED]"
            available = max(self.max_bytes - len(suffix.encode("utf-8")), 0)
            clamped_bytes = redacted.encode("utf-8", errors="ignore")[:available]
            clamped = clamped_bytes.decode("utf-8", errors="ignore") + suffix
            was_clamped = True

        payload_hash = self.hash_payload(clamped)
        return clamped, payload_hash, was_clamped, original_size

    @staticmethod
    def hash_payload(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()

    def _patterns(self) -> Iterable[re.Pattern]:
        if self.level == "strict":
            return list(self.NORMAL_PATTERNS) + list(self.STRICT_PATTERNS)
        return list(self.NORMAL_PATTERNS)
