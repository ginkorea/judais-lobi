# core/redact.py — the one place an error string stops naming this host

"""What a mission may say about the machine it ran on, decided once.

``core.runtime.contract``'s ``EXIT_CONTRACT`` used to end its ``diagnostic``
clause with a warning in capital letters: stderr "CARRIES ABSOLUTE PATHS FROM
THIS HOST; a consumer that shows it to anybody but an operator must scrub it
first."  That sentence was true, and it was the reason TAIPAN's location sweep
— the pass that would have let an analyst see a failure instead of a spinner —
was deferred rather than written.  A consumer cannot scrub what it does not
have a vocabulary for, and every consumer writing its own regexes is the same
mistake as every emitter writing its own bounding: N implementations, N
disagreements, and the first one that misses is the one that ships.

So the harness scrubs its own errors, at the emitter, through this module.

**What it removes.**  Five families, in this order, because the order is part
of the behaviour:

1. **The values of secret-shaped environment variables that are set in this
   process.**  The *names* are read from ``os.environ`` at call time and the
   *values* are what get replaced — by ``<redacted:OPENAI_API_KEY>``, naming
   the variable so an operator learns which credential was in the message
   without learning the credential.  First, so that a token which also looks
   like a path or a hostname is reported as the token it is.
2. **Authorization headers and known key shapes** — ``Bearer …``,
   ``Authorization: …``, ``sk-…``, ``ghp_…``, ``AKIA…``, ``xox?-…``.  These
   are the credentials that reach a message without ever having been an
   environment variable: a server echoing back the header it rejected.
3. **Absolute paths**, rewritten rather than deleted, because a frame with no
   path is a frame nobody can find.  A path under ``site-packages`` keeps its
   module-relative tail (``<site-packages>/httpx/_client.py``), a path under
   the working directory keeps its repository-relative tail
   (``<cwd>/core/runtime/mission.py``), a path under the interpreter's own
   library keeps the module (``<stdlib>/json/decoder.py``), and a path under
   anybody's home directory becomes ``<home>/…``.  ``/usr/bin/git`` is left
   alone: it names no person and no host.
4. **This process's home directory wherever else it appears** — inside a
   ``file://`` URL, concatenated into a message, spelled ``$HOME``.
5. **This host's name**: ``socket.gethostname()``, whatever ``/etc/hostname``
   says, and obvious internal FQDN shapes (``.local``, ``.internal``, ``.lan``,
   ``.intranet``, ``.corp``, ``.home.arpa``).  Deliberately conservative —
   loopback is left alone and a public domain is left alone, because a URL a
   caller typed is *data*, and this module scrubs error text, not data.

**Replacement tokens are stable and greppable.**  ``<home>``, ``<host>``,
``<cwd>``, ``<site-packages>``, ``<stdlib>``, ``<redacted:NAME>``.  A consumer
that wants to know whether a message was scrubbed greps for them, and a
developer reading a scrubbed traceback still knows what kind of thing was
taken out.  Scrubbing is idempotent: none of the tokens matches any of the
patterns, so a record that passes two emitters is not scrubbed twice into
nonsense.

**What it does NOT touch, and why that list lives here.**  A redactor applied
to everything is a redactor that eventually eats the evidence.  The fields a
stream record may carry are split in two — :data:`SCRUBBED_FIELDS` and
:data:`VERBATIM_FIELDS` — and :data:`WHY_VERBATIM` gives the reason for every
member of the second, in one place, so that the next person to add a field
finds the argument rather than reinventing it.  The load-bearing one is
``tool_result.output``: the grounding validator verifies an answer against the
mission *store's* copy of a result, byte for byte, and a stream whose copy had
been rewritten would show a pane an answer citing an identifier the pane can no
longer find.  The store and the stream must agree, so the stream is not
touched.

**Why ``core/redact.py`` and not a package.**  Same reason as
:mod:`core.bounding`: the callers are in :mod:`core.runtime`, :mod:`core.cli`
and — when somebody takes the one-line change in :class:`AuditLogger` —
:mod:`core.policy`.  This module imports nothing this repository owns and
nothing outside the standard library, so every direction is open and none of
them is a cycle.
"""

from __future__ import annotations

import functools
import os
import re
import socket
from typing import Any, Dict, List, Mapping, Sequence, Tuple

__all__ = [
    "scrub", "scrub_record", "redacted",
    "SCRUBBED_FIELDS", "VERBATIM_FIELDS", "WHY_VERBATIM",
    "HOME", "HOST", "CWD", "SITE_PACKAGES", "STDLIB", "FAILED",
    "SECRET_ENV_SUFFIXES", "MIN_SECRET_CHARS",
]


# ── the tokens a reader will meet ────────────────────────────────────────────

#: A home directory — this process's or anybody's.
HOME = "<home>"
#: This host's name, or an internal FQDN pointing at it.
HOST = "<host>"
#: The directory the process was started in.
CWD = "<cwd>"
#: An installed dependency's own file, tail preserved.
SITE_PACKAGES = "<site-packages>"
#: A standard-library file, tail preserved.
STDLIB = "<stdlib>"
#: What a field becomes when the redactor itself failed.  Fail closed: an
#: unscrubbed message is the one outcome this module exists to prevent.
FAILED = "<redaction-failed>"


def redacted(name: str) -> str:
    """The token that stands in for a credential, naming what it was.

    ``<redacted:OPENAI_API_KEY>`` rather than ``[REDACTED]``, because an
    operator debugging a 401 needs to know *which* credential the server saw
    and must not need the value to find out.
    """
    return f"<redacted:{name}>"


# ── which fields carry error text, and which carry evidence ──────────────────

#: Every field on a stream record that may carry free text derived from an
#: exception, a refusal, or the model's own prose.  Matched by NAME, at any
#: depth, so ``grounding.checks[*].detail`` is covered by naming ``detail``
#: once.
SCRUBBED_FIELDS = frozenset({
    # tool_result.error — the tool's stderr, which is where
    # `ToolBus.dispatch`'s "Tool execution error: <exc>" and the MCP bridge's
    # "mcp_unreachable: <exc>" land.  The single largest leak.
    "error",
    # reply_rejected.problem — the refusal, which quotes the reply that was
    # refused and the parser's complaint about it.
    "problem",
    # gate_requested.reason — prose written about a call nobody made.
    "reason",
    # answer.text — the answer, which is where an exception ends up on the
    # path where an exception becomes the answer.
    "text",
    # grounding.caveat and grounding.checks[*].detail — prose the validator
    # wrote about the answer, quoting the answer.
    "caveat",
    "detail",
    # grounding.unsupported — the tokens themselves, lifted out of the answer.
    # A path-shaped token is a path.
    "unsupported",
    # step_started.injected — what an operator typed at a running mission
    # over the control channel. Free text by definition, and scrubbed for
    # the same reason `problem` is: an operator quotes a path, and the
    # pane that renders this is the pane `<home>` exists to keep host
    # detail out of. NOT verbatim: nothing downstream checks these bytes
    # against a stored copy the way grounding checks `output`, so there is
    # no second reader for the scrub to disagree with. The MODEL is told
    # the operator's words exactly; the stream states them scrubbed.
    "injected",
    # tool — on `tool_call`, `tool_result` and `gate_requested` this is a name
    # the bus resolved and scrubbing it is a no-op; on `reply_rejected` it is
    # whatever string the model put in its JSON, which is model prose and has
    # been a path.  One rule for one field name, and the rule has to hold on
    # the event where the name was never validated.
    "tool",
})

#: Fields that are **never** scrubbed, and recursion stops at them — an
#: ``arguments`` dict may perfectly well have a key called ``text`` and that
#: key is still a tool argument, not an error message.
VERBATIM_FIELDS = frozenset({
    "output", "arguments", "objective", "catalogue", "gated",
    "handle", "outcome", "plan", "silent", "uncited", "check", "verdict",
    "sandbox", "profile", "audit_ref", "approval_id",
})

#: The argument for every member of :data:`VERBATIM_FIELDS`, in one place.
WHY_VERBATIM: Mapping[str, str] = {
    "output": (
        "The whole of a tool result. The grounding validator verifies the "
        "answer against the mission store's copy of this text, byte for byte; "
        "scrubbing the stream's copy would make the pane and the store "
        "disagree, and an identifier the answer cited would vanish from the "
        "only place a reader could check it."),
    "arguments": (
        "The call as the model proposed it. A gate exists so that a person "
        "approves the exact bytes that would have run — a redacted argument "
        "is a different call, and approving it would approve something "
        "nobody saw."),
    "objective": (
        "What the caller asked for, in the caller's own words. The caller "
        "already holds it; rewriting it would only make the record disagree "
        "with the request that produced it."),
    "catalogue": (
        "Tool names resolved from the bus, and the set a consumer matches "
        "`tool` against."),
    "gated": "Tool names resolved from the bus.",
    "handle": (
        "An opaque key into the mission store. A consumer resolves results by "
        "it, so it has to survive intact."),
    "outcome": (
        "One word from the closed vocabulary in `contract.OUTCOMES`. There is "
        "nothing in it to scrub and a consumer switches on it."),
    "plan": (
        "`{id, goal, rung}` written by the planner before any tool ran, so it "
        "cannot carry a frame from this host; and a consumer renders it as "
        "the shape of the turn."),
    "silent": "Names of checks that found nothing — check names, not prose.",
    "uncited": "Names of checks that found nothing — check names, not prose.",
    "check": "The name of a grounding check.",
    "verdict": "One word from the validator's own closed set.",
    "sandbox": (
        "One of two closed words, `bwrap` or `none`, chosen by the harness "
        "and never containing anything a redactor would look for."),
    "profile": "One of the four ProfileMode names, chosen by the harness.",
    "audit_ref": (
        "The path of the audit file, stated ON PURPOSE so a consumer can "
        "find the record; a scrubbed path names a file nobody can open. It "
        "is a path on the spawning host and the contract says so."),
    "approval_id": (
        "The name of the durable approval record, generated by this harness "
        "out of `ap_` and hex. It is how a decision is ADDRESSED — a "
        "rewritten one names a file nobody can answer — and there is nothing "
        "in it a redactor would look for."),
}


# ── what counts as a secret ──────────────────────────────────────────────────

#: An environment variable whose NAME ends in one of these has a value worth
#: hiding.  The name is what is read; the value is what is replaced.
SECRET_ENV_SUFFIXES: Tuple[str, ...] = ("_KEY", "_TOKEN", "_SECRET", "_PASSWORD")

#: Below this, a value is too short to be a credential and too likely to be a
#: word that happens to appear in a sentence.  Replacing "abc" everywhere it
#: occurred would corrupt the message it was trying to protect.
MIN_SECRET_CHARS = 8

_EXACT_SECRET_NAMES = frozenset({"KEY", "TOKEN", "SECRET", "PASSWORD"})


def _secret_values() -> List[Tuple[str, str]]:
    """``(value, variable name)`` for every secret set in this process.

    Read at call time rather than at import: a library caller may set a
    credential after importing us, and a redactor holding the environment as
    it was at import is a redactor that misses exactly the credential somebody
    was careful about.

    Longest value first, so that a variable whose value is a prefix of
    another's does not carve the longer one in half.
    """
    found: List[Tuple[str, str]] = []
    for name, value in os.environ.items():
        upper = name.upper()
        if not (upper.endswith(SECRET_ENV_SUFFIXES) or upper in _EXACT_SECRET_NAMES):
            continue
        value = value or ""
        if len(value.strip()) < MIN_SECRET_CHARS:
            continue
        found.append((value, name))
    found.sort(key=lambda pair: len(pair[0]), reverse=True)
    return found


_BEARER = re.compile(r"(?i)\b(bearer\s+)([A-Za-z0-9._\-+/=]{8,})")
#: A header and everything after it up to the next delimiter.  Greedy on
#: purpose: ``Authorization: Bearer abc`` is two tokens and taking only the
#: first would leave the credential sitting next to a label announcing it.
_HEADER = re.compile(
    r"(?i)\b(authorization|proxy-authorization|x-api-key|api[_-]?key)"
    r"\s*[:=]\s*([^\r\n,;'\")}\]]{4,})")
_SHAPES: Sequence[Tuple["re.Pattern", str]] = (
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{12,}"), redacted("api-key")),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}"), redacted("github-token")),
    (re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{12,}"), redacted("aws-access-key-id")),
    (re.compile(r"\bxox[bpsare]-[A-Za-z0-9\-]{8,}"), redacted("slack-token")),
)


#: ``NAME=value`` and ``"NAME": "value"`` for any NAME ending in a secret
#: suffix.  The name survives and the value does not: an audit line that says
#: ``MCP_TOKEN=`` was passed is worth reading, one that says what it was is a
#: leak.  Came from the audit logger's own list when the two redactors were
#: folded into one owner.
_ASSIGNMENT = re.compile(
    r"([A-Za-z0-9_]*(?:_KEY|_TOKEN|_SECRET|_PASSWORD)[\"']?\s*[:=]\s*[\"']?)"
    r"([^\s\"',;}]{4,})",
    re.IGNORECASE,
)


def _credentials(text: str) -> str:
    for value, name in _secret_values():
        if value in text:
            text = text.replace(value, redacted(name))
    text = _HEADER.sub(lambda m: f"{m.group(1)}: {redacted(m.group(1))}", text)
    text = _BEARER.sub(lambda m: f"{m.group(1)}{redacted('bearer')}", text)
    text = _ASSIGNMENT.sub(
        lambda m: m.group(1) + redacted(m.group(1).split("=")[0].split(":")[0]
                                        .strip("\"' ") or "secret"), text)
    for pattern, token in _SHAPES:
        text = pattern.sub(token, text)
    return text


def scrub_secrets(text: str) -> str:
    """Credentials only — no paths, no hostnames.

    The pass the audit logger uses.  An operator's own append-only record
    of what ran on this host is *supposed* to name this host's files, so
    the location passes of :func:`scrub` would destroy the record; the
    credential pass is the one thing both surfaces must agree on, and it
    has one owner here.  Total and idempotent, like :func:`scrub`.
    """
    if not isinstance(text, str) or not text:
        return text
    return _credentials(text)


def secret_values() -> List[str]:
    """The credential values this process holds, longest first — for callers
    that need the list itself and not a scrubbed string."""
    return [value for value, _name in _secret_values()]


# ── what counts as a path ────────────────────────────────────────────────────

#: An absolute POSIX path, refusing to start in the middle of one.  The
#: lookbehind is what keeps ``https://example.com/home/joe`` intact: there the
#: ``/home`` is preceded by a word character and this does not match it.  A URL
#: a caller typed is data.
_PATH = re.compile(r"(?<![\w/.~\-])(/(?:[A-Za-z0-9._+\-@]+/)*[A-Za-z0-9._+\-@]+)")
_STDLIB_DIR = re.compile(r"/lib(?:64)?/python\d+(?:\.\d+)*/")
_ANY_HOME = re.compile(r"^/(?:home|Users)/[^/]+")
_VENDORED = ("/site-packages", "/dist-packages")


def _cwd() -> str:
    try:
        return os.getcwd()
    except OSError:                             # pragma: no cover - no cwd
        return ""


def _home() -> str:
    home = os.path.expanduser("~")
    return home if home and home not in ("~", "/") else ""


def _rewrite_path(path: str) -> str:
    for marker in _VENDORED:
        if marker + "/" in path:
            return SITE_PACKAGES + path.split(marker, 1)[1]
    cwd = _cwd()
    if cwd and (path == cwd or path.startswith(cwd + "/")):
        return CWD + path[len(cwd):]
    inside = _STDLIB_DIR.search(path)
    if inside:
        return STDLIB + "/" + path[inside.end():]
    home = _home()
    if home and (path == home or path.startswith(home + "/")):
        return HOME + path[len(home):]
    anybody = _ANY_HOME.match(path)
    if anybody:
        return HOME + path[anybody.end():]
    # /usr/bin/git, /etc/passwd: absolute, and neither a person nor a host.
    return path


def _paths(text: str) -> str:
    def _one(match: "re.Match") -> str:
        path = match.group(1)
        trailing = ""
        while path and path[-1] in ".,;:":
            trailing = path[-1] + trailing
            path = path[:-1]
        if not path or path == "/":
            return match.group(0)
        return _rewrite_path(path) + trailing

    text = _PATH.sub(_one, text)
    # The mop-up: this process's own home wherever the boundary rule above
    # would not have looked — inside a file:// URL, concatenated into a word,
    # or spelled the way a shell spells it.
    home = _home()
    if home and home in text:
        text = text.replace(home, HOME)
    return text.replace("${HOME}", HOME).replace("$HOME", HOME)


# ── what counts as this host ─────────────────────────────────────────────────

_LOOPBACK = frozenset({"localhost", "localhost.localdomain", "loopback"})
_INTERNAL_FQDN = re.compile(
    r"(?<![\w.\-])(?:[A-Za-z0-9](?:[A-Za-z0-9\-]*[A-Za-z0-9])?\.)+"
    r"(?:local|internal|lan|intranet|corp|localdomain|home\.arpa)(?![\w\-])")


@functools.lru_cache(maxsize=1)
def _local_hostnames() -> Tuple[str, ...]:
    """Every spelling of this machine's name, longest first.

    Cached because ``/etc/hostname`` does not change under a running mission
    and :func:`scrub` is called once per record.  A test that wants a
    different machine monkeypatches and calls ``_local_hostnames.cache_clear``.
    """
    names = set()
    try:
        names.add(socket.gethostname())
    except OSError:                             # pragma: no cover - defensive
        pass
    try:
        with open("/etc/hostname", encoding="utf-8") as handle:
            names.add(handle.read().strip())
    except OSError:
        pass
    spellings = set()
    for name in names:
        name = (name or "").strip()
        if not name:
            continue
        spellings.add(name)
        spellings.add(name.split(".", 1)[0])
    keep = [n for n in spellings
            if len(n) >= 3 and n.lower() not in _LOOPBACK
            and not n.replace(".", "").isdigit()]
    return tuple(sorted(keep, key=len, reverse=True))


def _hosts(text: str) -> str:
    def _fqdn(match: "re.Match") -> str:
        if match.group(0).lower().startswith("localhost."):
            return match.group(0)
        return HOST

    text = _INTERNAL_FQDN.sub(_fqdn, text)
    for name in _local_hostnames():
        text = re.sub(r"(?<![\w.\-])" + re.escape(name) + r"(?![\w\-])",
                      HOST, text)
    return text


# ── the redactor ─────────────────────────────────────────────────────────────

def scrub(text: str) -> str:
    """One string, with everything this host owns taken out of it.

    Pure apart from reading ``os.environ``, ``os.getcwd`` and this machine's
    name, total on any input (a non-string comes back unchanged), and
    idempotent — none of the replacement tokens matches any of the patterns,
    so a record that passes two emitters is scrubbed once in effect.
    """
    if not isinstance(text, str) or not text:
        return text
    return _hosts(_paths(_credentials(text)))


def _walk(value: Any, scrubbing: bool) -> Any:
    if isinstance(value, str):
        return scrub(value) if scrubbing else value
    if isinstance(value, Mapping):
        out: Dict[Any, Any] = {}
        for key, item in value.items():
            if key in VERBATIM_FIELDS:
                out[key] = item
            elif key in SCRUBBED_FIELDS:
                out[key] = _walk(item, True)
            else:
                out[key] = _walk(item, scrubbing)
        return out
    if isinstance(value, (list, tuple)):
        return [_walk(item, scrubbing) for item in value]
    return value


def scrub_record(record: Mapping[str, Any]) -> Dict[str, Any]:
    """One stream record, with its free-text fields scrubbed and nothing else.

    Applied at the emitter — ``MissionRunner._emit`` and ``SwarmRunner._emit``
    — so that no future emitter can forget it, and so that a library caller
    supplying its own observer is given the same records a pane is.

    Which fields move and which do not is :data:`SCRUBBED_FIELDS` and
    :data:`VERBATIM_FIELDS`; the reasons are :data:`WHY_VERBATIM`.  Names are
    matched at any depth, and recursion stops at a verbatim field so that an
    ``arguments`` dict with a ``text`` key keeps its argument.

    Fails **closed**.  If the redactor itself raises, the scrubbed fields come
    back as :data:`FAILED` rather than as themselves: a mission that lost a
    sentence is a nuisance, and a mission that shipped an unscrubbed traceback
    to a browser is the thing this module exists to stop.
    """
    try:
        return _walk(dict(record), False)
    except Exception:                           # pragma: no cover - defensive
        safe: Dict[str, Any] = {}
        for key, item in dict(record).items():
            safe[key] = FAILED if key in SCRUBBED_FIELDS else item
        return safe
