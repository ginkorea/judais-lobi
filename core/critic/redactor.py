# core/critic/redactor.py — payload clamping, over the one redactor

"""What leaves this host on its way to a critic, and how much of it.

There is **one owner of what a credential looks like** in this package and
it is :mod:`core.redact`.  This module used to be a second: a
``NORMAL_PATTERNS`` list carrying its own spellings of an OpenAI key, a
GitHub PAT, an AWS access key id and a Slack token, maintained beside the
audit logger's list and beside the stream scrubber's.  Three lists of the
same fact drift the day a provider changes a prefix, and the copy that
drifts is discovered by the leak.

So the credential pass here *is* :func:`core.redact.scrub_secrets`, and
the location pass — home directories, this host's names — *is*
:func:`core.redact.scrub`.  What is left in this file is the part
:mod:`core.redact` has no opinion about and should not: the two extra
identifier shapes a critique payload is worth stripping (an email address,
a bare IP or hostname), and the byte clamp, which is a statement about a
provider's request limit rather than about privacy.

The tokens changed with the owner.  ``[REDACTED]`` said only that
*something* was taken out; ``<redacted:api-key>`` says what, which is the
difference between a reader who can act on a redacted line and one who
cannot.
"""

from __future__ import annotations

import hashlib
import re
from typing import Iterable, Tuple

from core.redact import redacted, scrub, scrub_secrets

#: What a strict pass takes out that :func:`core.redact.scrub` does not.
#:
#: ``scrub`` removes *this host's* names and paths, which is the right scope
#: for an operator's own audit file.  A critique payload is going somewhere
#: else, so the scope widens to anybody's address and any address at all —
#: and that widening stops here rather than being pushed down into
#: :mod:`core.redact`, where it would start deleting the hostnames a local
#: audit record exists to name.
STRICT_PATTERNS: Tuple[Tuple["re.Pattern", str], ...] = (
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
     redacted("email")),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), redacted("ipv4")),
    (re.compile(r"\b(?:[0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F]{0,4}\b"),
     redacted("ipv6")),
    (re.compile(r"\b[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)*\.[a-zA-Z]{2,}\b"),
     redacted("host")),
)

#: The word this module used to write for everything.  Kept as a name so a
#: caller can still ask "was anything taken out of this?" without knowing
#: the vocabulary — see :func:`was_redacted`.
REDACTION_MARK = "<redacted:"


def was_redacted(text: str) -> bool:
    """Whether a redaction pass replaced anything in *text*."""
    return REDACTION_MARK in (text or "")


class Redactor:
    """Strips secrets from a critique payload and clamps it to a size.

    ``level`` is ``"strict"`` or ``"normal"``.  Normal is credentials only
    — the pass an operator's own machine may keep.  Strict adds every
    location and identity pass this package has, plus the addresses in
    :data:`STRICT_PATTERNS`, and is the default because the payload's
    destination is another company's model.
    """

    def __init__(self, level: str = "strict", max_bytes: int = 65_536):
        self.level = level
        self.max_bytes = max_bytes

    def redact(self, text: str) -> str:
        """Credentials always; locations and addresses under ``strict``."""
        if self.level != "strict":
            return scrub_secrets(text or "")
        # `scrub` is credentials + paths + this host's names, in one owner.
        redacted_text = scrub(text or "")
        for pattern, token in STRICT_PATTERNS:
            redacted_text = pattern.sub(token, redacted_text)
        return redacted_text

    def redact_and_clamp(self, text: str) -> Tuple[str, str, bool, int]:
        """``(payload, sha256, was_clamped, original_bytes)``.

        The clamp is a provider's request limit and not a privacy control,
        which is why it happens *after* the redaction and never instead of
        it: a payload cut to size with a key still in the first 64KB has
        leaked the key.
        """
        redacted_text = self.redact(text)
        original_size = len((text or "").encode("utf-8", errors="ignore"))

        clamped = redacted_text
        was_clamped = False
        if self.max_bytes and original_size > self.max_bytes:
            suffix = " [TRUNCATED]"
            available = max(self.max_bytes - len(suffix.encode("utf-8")), 0)
            clamped_bytes = redacted_text.encode(
                "utf-8", errors="ignore")[:available]
            clamped = clamped_bytes.decode("utf-8", errors="ignore") + suffix
            was_clamped = True

        payload_hash = self.hash_payload(clamped)
        return clamped, payload_hash, was_clamped, original_size

    @staticmethod
    def hash_payload(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()

    def _patterns(self) -> Iterable[Tuple["re.Pattern", str]]:
        """The address patterns this level applies on top of the shared
        passes.  Empty under ``normal``: credentials have one owner."""
        return STRICT_PATTERNS if self.level == "strict" else ()
