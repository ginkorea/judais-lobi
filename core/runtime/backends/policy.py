# core/runtime/backends/policy.py — the HTTP policy the raw-HTTP backends share

"""How long to wait, what to retry, and what to say when a server refuses.

**This module is the owner of that policy.**  It was written because the
Mistral backend imported ``CHAT_TIMEOUT`` and ``CONNECT_RETRIES`` from
:mod:`core.runtime.backends.local_backend` — the right instinct (one owner
per fact) pointed at the wrong owner.  Nothing about "a whole turn is too
much to pay for one refused connect" is about a vLLM endpoint on this
host, and a hosted provider should not have to import a local one to
learn it.  So the rule moved here, to a module that knows about neither.

It imports nothing from ``core`` on purpose: this is the bottom of the
stack, and a policy that can reach back up into the runtime stops being a
policy and becomes a second opinion about what the runtime is doing.

**One HTTP client per hosted provider, one policy module for the ones
that speak HTTP by hand.**  That is this repo's reading of "one HTTP
client for every hosted provider".  OpenAI and Anthropic each have an
official SDK that owns its own transport, retries and error types; using
it is cheaper and more correct than re-deriving them.  The local endpoint
(``requests``) and Mistral (``httpx``) are raw HTTP against a documented
shape, and *those two* are what would otherwise drift — so those two share
this module.  Four backends, two hand-written clients, one policy.

The error-class table is :data:`ERROR_POLICY`, stated as data rather than
as prose so a test can read it and a reader cannot mistake an accident for
a decision.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import (
    Any,
    Callable,
    Dict,
    Mapping,
    Optional,
    Sequence,
    Tuple,
    TypeVar,
)

import httpx
import requests

#: Seconds to wait on a chat completion.  Long: a cold vLLM server loads
#: weights for ~100s before it answers the first request, and a hosted
#: provider streaming a long answer holds the connection just as long.
CHAT_TIMEOUT = 600.0

#: Backoff (seconds) before each retry of a refused connect.  Three tries
#: spanning ~17s: an endpoint that bounces or hands off ports mid-session
#: comes back inside that window; one that is truly down fails just as
#: clearly 17 seconds later.  Measured 12 Aug 2026 against the local
#: endpoint — one mid-eval turn died at step 0 on a single refused connect
#: while the turns on either side of it succeeded — and the reasoning is
#: about the cost of losing a turn, not about which server refused.
CONNECT_RETRIES: Tuple[float, ...] = (2.0, 5.0, 10.0)

#: How much of a server's error body to put in front of a caller.  Enough
#: for an OpenAI-compatible ``{"object":"error","message":...}`` to arrive
#: whole; short enough that a stack trace does not become the error message.
ERROR_DETAIL_CHARS = 600

#: The exceptions that mean **the request never left**.  Both libraries
#: this module serves are named here rather than at the two call sites,
#: because "which failures are safe to re-send" is the policy.
#:
#: ``requests.exceptions.ConnectionError`` covers a refused, reset or
#: unresolved connect, and — through ``ConnectTimeout``, its subclass — a
#: connect that timed out.  ``httpx.ConnectError`` is the same fact minus
#: the timeout, which httpx files under ``TimeoutException`` instead; that
#: asymmetry belongs to the libraries, it is left alone, and ``timeout``
#: in :data:`ERROR_POLICY` says why not-retrying is the safe direction to
#: err in.
CONNECT_ERRORS: Tuple[type, ...] = (
    requests.exceptions.ConnectionError,
    httpx.ConnectError,
)


@dataclass(frozen=True)
class ErrorPolicy:
    """What to do about one class of failure, and why."""

    retry: bool
    why: str


#: One row per error class.  Read it before writing a fourth retry loop.
ERROR_POLICY: Dict[str, ErrorPolicy] = {
    "connect": ErrorPolicy(
        retry=True,
        why="The request never left this host, so nothing can have been "
            "billed or half-decoded. Re-sending has no consequences and "
            "buys back a turn an endpoint blip would otherwise cost."),
    "timeout": ErrorPolicy(
        retry=False,
        why="A read or write timeout means the request IS in flight — the "
            "server may be decoding it right now. Re-sending would run the "
            "completion twice, bill it twice, and possibly dispatch its "
            "tool call twice."),
    "4xx": ErrorPolicy(
        retry=False,
        why="The server answered, and it answered that the request is "
            "wrong. The same request will be wrong again. The body is the "
            "diagnosis and belongs in front of the operator — see "
            "`raise_for_status`."),
    "5xx": ErrorPolicy(
        retry=False,
        why="No retry today. A hosted 5xx mid-mission is a turn to lose, "
            "not a completion to double-bill: the provider may well have "
            "decoded the reply before failing to hand it back, and this "
            "repo has no idempotency key to say otherwise. Revisit when "
            "there is one."),
}

_T = TypeVar("_T")


def retry_on_connect(
    fn: Callable[[], _T],
    *,
    retries: Sequence[float] = CONNECT_RETRIES,
    sleep: Optional[Callable[[float], None]] = None,
    connect_errors: Tuple[type, ...] = CONNECT_ERRORS,
) -> _T:
    """Call *fn*, retrying only a connect that never happened.

    The loop both raw-HTTP backends used to write by hand, in one place.
    *fn* takes no arguments and is called again from scratch on each
    attempt — which matters for a streamed request, where the request is
    made inside ``__enter__`` and retrying means building and entering a
    fresh context manager rather than re-entering a spent one.

    One attempt, then one more per entry in *retries*, waiting that many
    seconds first.  Anything not in *connect_errors* propagates on the
    first raise: see :data:`ERROR_POLICY` — a status code, or a timeout
    mid-body, is the server ANSWERING.

    *sleep* defaults to ``time.sleep`` **resolved at call time**, not
    bound at import, so a test that patches ``time.sleep`` is obeyed and
    a unit test never actually waits 17 seconds.
    """
    waiter = sleep if sleep is not None else time.sleep
    last: Optional[BaseException] = None
    for wait in (0.0, *retries):
        if wait:
            waiter(wait)
        try:
            return fn()
        except connect_errors as exc:
            last = exc
    raise last  # type: ignore[misc]


def error_detail(res: Any, *, detail_chars: int = ERROR_DETAIL_CHARS) -> str:
    """What the server SAID about a failure, bounded.

    An OpenAI-compatible server — and Mistral, and a vLLM behind either —
    puts a real sentence in ``{"message": ...}``: which parameter it
    rejected, that ``max_tokens`` came out negative, that the model name
    does not match what is loaded.  A body that is not JSON, or JSON that
    is not an object, falls back to the raw text, because an unparseable
    body is still evidence.

    Returns ``""`` when the server said nothing at all — a fact the
    caller reports rather than papers over.
    """
    try:
        payload = res.json()
    except (ValueError, TypeError):
        payload = None
    detail = payload.get("message") if isinstance(payload, Mapping) else None
    if not detail:
        detail = getattr(res, "text", "")
    if not isinstance(detail, str):
        detail = json.dumps(detail)
    return (detail or "").strip()[:detail_chars]


def status_message(
    res: Any,
    url: str,
    *,
    detail_chars: int = ERROR_DETAIL_CHARS,
    subject: str = "the server",
) -> str:
    """The sentence a non-2xx deserves: the number, the URL, and the body."""
    detail = error_detail(res, detail_chars=detail_chars)
    return (f"{res.status_code} from {url}"
            + (f": {detail}" if detail
               else f" (and {subject} said nothing)"))


def _requests_error(message: str, res: Any) -> Exception:
    return requests.HTTPError(message, response=res)


def raise_for_status(
    res: Any,
    url: str,
    *,
    detail_chars: int = ERROR_DETAIL_CHARS,
    subject: str = "the server",
    error: Callable[[str, Any], Exception] = _requests_error,
) -> None:
    """Fail with what the server said, not just the number it returned.

    ``requests``' own ``raise_for_status`` produces ``500 Server Error for
    url ...`` and discards the body — and the body is the whole diagnosis.
    This cost most of an afternoon once: a served gpt-oss-20b answered
    ``500`` with nothing else, which is indistinguishable from the server
    being broken, so the run was reported as "the server rejects the
    request shape". The shape was in the body the whole time.

    A status below 400 returns without raising, so this can be called
    unconditionally.

    *error* builds the exception, because the two libraries that share
    this policy do not share an exception type and a caller already
    catching ``httpx.HTTPStatusError`` must keep catching it.  The
    default is the ``requests`` one; the httpx backend passes its own.
    """
    if res.status_code < 400:
        return
    raise error(
        status_message(res, url, detail_chars=detail_chars, subject=subject),
        res,
    )
