# core/runtime/backends/local_backend.py — OpenAI-compatible local endpoint

"""A backend for a locally served, OpenAI-compatible chat endpoint.

This is what ``vllm serve`` (and llama.cpp's server, and LM Studio, and
Ollama's ``/v1`` shim) puts on a socket: ``POST {base}/chat/completions``
speaking the OpenAI request and response shape, and ``GET {base}/models``
listing what is loaded.

Deliberately **not** the ``openai`` SDK.  The SDK is a fine client for a
remote provider with an API key; here it would add a mandatory
``api_key`` to talk to a loopback port, and it hides the one thing this
backend exists to expose — the served model's real ``max_model_len``.
``requests`` is already a hard dependency of this package.

``base`` includes the version prefix.  ``http://127.0.0.1:8000/v1``, not
``http://127.0.0.1:8000`` — that is what an OpenAI-compatible server
advertises and what ``LOCAL_API_BASE`` is expected to hold.  A **bare
host** is repaired at construction rather than producing a 404 an hour
later; a base that already carries a path is left exactly as written,
because the prefix a deployment mounts on is its own business.  See
:meth:`LocalBackend._normalize_base`.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, replace
from types import SimpleNamespace
from typing import Any, Dict, Iterator, List, Optional, Tuple

import requests

from core.runtime.backends.base import (
    Backend,
    BackendCapabilities,
    ToolCallAccumulator,
    Usage,
    tool_calls_from,
    truncation_of,
)
from core.runtime.backends import policy, state
from core.runtime.backends.policy import CHAT_TIMEOUT

DEFAULT_LOCAL_API_BASE = "http://127.0.0.1:8000/v1"
DEFAULT_LOCAL_MODEL = "local-model"

#: How many completion tokens this backend asks for when nobody named a
#: number — the bound that used to be **absent**, which is the whole
#: reason this constant exists.
#:
#: A request with no ``max_tokens`` is not an unbounded request; it is a
#: request bounded by somebody else.  A served endpoint lets the model run
#: to ``max_model_len − prompt_tokens``, which at the 87,000-token prompts
#: of a real deployment is still tens of thousands of tokens, and the
#: effective ceiling then belongs to whoever times the turn out first — a
#: platform's turn budget, a proxy, an operator's patience.  None of those
#: can say *the answer was cut short*, because none of them is the thing
#: that cut it.  The harness sending its own number is what turns a stall
#: into a truncation with a name on it: see
#: :data:`~core.runtime.backends.base.TRUNCATED_REASONS`, which is how the
#: fact gets onto the wire.
#:
#: **4,096, and the number is not a taste.**  It is the output reserve this
#: harness has *already* subtracted from every prompt it built —
#: ``core.runtime.context_window`` defaults ``max_output_tokens`` to 4096
#: and sizes the input window at ``max_context − max_output`` — so it is
#: the one number in the tree that is already a statement about how long an
#: answer may be.  Asking the server for more than the window reserved room
#: for is the harness contradicting its own arithmetic, and on a full
#: window it is the request that 400s.  A test holds the two equal.
#:
#: **Raising it is one variable**, :data:`MAX_OUTPUT_TOKENS_ENV`, and a
#: deployment whose model reasons at length should raise it: the doctrine
#: here is that the harness lifts and never holds back, so a truncation is
#: a thing an operator is told about and can undo, never a ceiling they
#: were not consulted on.  What ended is the silent state — no bound the
#: harness set, and no way to say an answer was cut off.
DEFAULT_MAX_OUTPUT_TOKENS = 4096
MAX_RECOVERY_OUTPUT_TOKENS = 16384

#: Where a deployment raises (or lowers) :data:`DEFAULT_MAX_OUTPUT_TOKENS`.
#: Read here, like ``LOCAL_API_BASE`` and ``LOCAL_MODEL``, because it is
#: configuration of the endpoint this backend talks to.
MAX_OUTPUT_TOKENS_ENV = "JUDAIS_LOBI_MAX_OUTPUT_TOKENS"


def _env_max_output_tokens(name: str = MAX_OUTPUT_TOKENS_ENV) -> Optional[int]:
    """The completion ceiling from the environment, or ``None`` for the default.

    The ``MCP_TIMEOUT_S`` rule, deliberately: unset, blank, unparseable or
    non-positive all mean ``None`` and therefore
    :data:`DEFAULT_MAX_OUTPUT_TOKENS`.  **Zero is not a value** — a
    zero-token completion is every answer empty, which nobody asks for by
    that spelling — and a typo must not be able to turn the model off.
    """
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return None
    try:
        tokens = int(raw)
    except ValueError:
        return None
    return tokens if tokens > 0 else None

#: Seconds to wait on ``GET /models``.  Short: the probe is a convenience,
#: and a capabilities lookup must never be the thing that hangs a CLI.
PROBE_TIMEOUT = 5.0

#: ``CHAT_TIMEOUT`` — seconds to wait on ``POST /chat/completions`` — is
#: imported above from :mod:`core.runtime.backends.policy`, which owns it,
#: and re-exported so the name this module has always published keeps
#: resolving.  ``PROBE_TIMEOUT`` stays here because it is genuinely local:
#: five seconds is a statement about a convenience lookup on this host,
#: not about how long a completion may take.


@dataclass
class _StreamProgress:
    """How far a streamed call has got, for the timer thread to read.

    Mutable and unlocked on purpose.  It is written by the thread
    draining the stream and read by the one-shot timer that may fire
    beside it, and every field is a plain int, str or bool assignment —
    so the worst a race can do is report a count one frame stale, which
    is a sentence for a person to read and not a number anything computes
    with.  A lock here would be a lock taken on every frame of every
    streamed call to protect against being told 412 characters instead of
    419.
    """

    #: Whether the first frame carrying choices has arrived.  Until it
    #: has, a long call is :meth:`LocalBackend._late_first_byte`'s to
    #: explain and not this one's.
    arrived: bool = False
    #: Frames carrying choices, and content characters in them.
    frames: int = 0
    chars: int = 0
    #: The model id the SERVER put on its frames, once one has arrived.
    model: str = ""
    #: Whether the long-call state went out — and therefore whether there
    #: is a wait outstanding for the end of the stream to close.
    reported: bool = False


@dataclass(frozen=True)
class ServedModel:
    """What ``GET {base}/models`` said, or why it said nothing.

    ``reachable`` is the honest bit.  An unreachable server yields a
    ``ServedModel`` with ``reachable=False`` and ``max_model_len=None``
    — never a guessed context length, because a guessed context window
    is how a request gets truncated silently.

    ``served`` is every id the endpoint listed, in its order, and it is
    kept rather than collapsed into :attr:`model_id` because *the model
    we asked for is not among them* is a different fact to *the server
    said nothing*: the first is ``cold`` and the second is ``absent``,
    and a browser has to be able to say which.  See
    :meth:`LocalBackend.lists`.
    """

    model_id: str
    max_model_len: Optional[int] = None
    reachable: bool = False
    error: str = ""
    served: Tuple[str, ...] = ()


class LocalBackend(Backend):
    """Chat against an OpenAI-compatible endpoint on this host.

    Parameters
    ----------
    endpoint:
        Base URL **including** the version prefix.  Defaults to
        ``LOCAL_API_BASE`` then :data:`DEFAULT_LOCAL_API_BASE`.
    model:
        Served model name.  Defaults to ``LOCAL_MODEL``, then whatever
        ``GET {base}/models`` reports, then :data:`DEFAULT_LOCAL_MODEL`.
        The ``model`` argument to :meth:`chat` still wins when given.
    api_key:
        Sent as ``Authorization: Bearer`` when set.  Most local servers
        want no key; some are started with ``--api-key``.
    supports_tool_calls:
        Declared, not probed — see :attr:`capabilities`.
    max_output_tokens:
        The completion ceiling this backend asks for when a caller names
        none.  Defaults to :data:`MAX_OUTPUT_TOKENS_ENV` then
        :data:`DEFAULT_MAX_OUTPUT_TOKENS` — never to *no ceiling*, which
        is what it used to default to and what left the bound in
        somebody else's hands.  A ``max_tokens=`` on :meth:`chat` still
        wins.
    first_byte_queued_s:
        How long an accepted request may stay silent before the wait is
        reported as a state.  See
        :data:`core.runtime.backends.state.FIRST_BYTE_QUEUED_S`, which
        owns the number and the reasoning; a constructor argument
        because it is a property of the endpoint a deployment points at.
    streaming_long_s:
        How long a call that IS answering may keep answering before that
        is reported as a state.  See
        :data:`core.runtime.backends.state.STREAMING_LONG_S`, which owns
        the number, and a constructor argument for the same reason.
    """

    #: The word :class:`core.unified_client.UnifiedClient` routes on.
    provider_name = "local"

    def __init__(
        self,
        endpoint: Optional[str] = None,
        model: Optional[str] = None,
        max_context_tokens: Optional[int] = None,
        max_output_tokens: Optional[int] = None,
        api_key: Optional[str] = None,
        supports_tool_calls: bool = True,
        session: Any = None,
        first_byte_queued_s: float = state.FIRST_BYTE_QUEUED_S,
        streaming_long_s: float = state.STREAMING_LONG_S,
    ):
        raw = endpoint or os.getenv("LOCAL_API_BASE") or DEFAULT_LOCAL_API_BASE
        self.endpoint = self._normalize_base(raw)
        self._model = model or os.getenv("LOCAL_MODEL") or None
        self._max_context_tokens = max_context_tokens
        self._max_output_tokens = max_output_tokens
        # One effective number feeds both requests and capabilities, so an
        # environment override cannot exceed the input window's reserve.
        self._output_bound = (max_output_tokens if max_output_tokens is not None
                              else _env_max_output_tokens())
        self._recovery_output_bound: Optional[int] = None
        self._api_key = api_key or os.getenv("LOCAL_API_KEY") or None
        self._supports_tool_calls = supports_tool_calls
        self._session = session if session is not None else requests
        self._probed: Optional[ServedModel] = None
        self.first_byte_queued_s = first_byte_queued_s
        self.streaming_long_s = streaming_long_s
        self.last_usage = None
        self.last_tool_calls = []

    @property
    def output_bound(self) -> int:
        """The default sent on requests and reserved from their input window."""
        return (self._output_bound if self._output_bound is not None
                else self._recovery_output_bound or DEFAULT_MAX_OUTPUT_TOKENS)

    def recover_output_budget(self, usage: Dict[str, Any]) -> Optional[int]:
        """Raise an implicit default for one explicit caller-owned retry.

        No request is made here. An operator-set ceiling remains a ceiling.
        The caller must reserve the returned output allowance before retrying,
        and is responsible for the retry count and recording both calls.
        """
        if self._output_bound is not None or not truncation_of(usage.get("finish_reason")):
            return None
        prompt = usage.get("prompt_tokens")
        completion = usage.get("completion_tokens")
        if (type(prompt) is not int or prompt < 0
                or type(completion) is not int or completion < self.output_bound):
            return None
        context = self.capabilities.max_context_tokens
        if not context:
            return None
        raised = min(self.output_bound * 2, MAX_RECOVERY_OUTPUT_TOKENS,
                     context - prompt - 1024)
        if raised <= self.output_bound:
            return None
        self._recovery_output_bound = raised
        return raised

    # ── configuration ────────────────────────────────────────────────────

    @staticmethod
    def _normalize_base(base: str) -> str:
        """Strip a trailing slash; append ``/v1`` to a **bare host**.

        A base without the version prefix is the single most common
        misconfiguration of this backend, and it fails as a 404 on the
        first chat rather than at construction.  Repairing it here keeps
        that hour.

        **Only a bare host is repaired**, and that boundary was learned:
        the rule used to be "append ``/v1`` unless the last segment looks
        like ``v<digits>``", which turned the perfectly good OpenAI-
        compatible base ``https://host/v1beta/openai/`` into
        ``…/v1beta/openai/v1``.  A base that already carries a path is a
        path somebody typed — the prefix may be ``/v1``, ``/openai/v1``,
        ``/v1beta/openai`` or a reverse proxy's own mount point — and
        guessing a suffix onto it is how a working endpoint becomes a 404
        the backend put there itself.  Nothing is guessed where something
        was said; the repair is for the one case where nothing was.
        """
        base = (base or "").strip().rstrip("/")
        if not base:
            return DEFAULT_LOCAL_API_BASE
        # Everything after the scheme, or the whole string when a caller
        # wrote `host:8000` with no scheme at all.
        rest = base.partition("://")[2] or base
        if "/" not in rest:             # a bare host: nothing was said
            base = f"{base}/v1"
        return base

    @property
    def model(self) -> str:
        """The model name this backend will send when the caller gives none."""
        if self._model:
            return self._model
        probed = self.probe()
        return probed.model_id or DEFAULT_LOCAL_MODEL

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def _named_model(self) -> str:
        """The model name to put on a state report, without asking anyone.

        :attr:`model` probes when nothing was configured, and a report is
        the one caller that must never do that: it is made from inside a
        call that is already in trouble, sometimes from a timer thread,
        and a network round trip to fill in a label would be this
        harness making its own diagnosis slower.
        """
        return self._model or (self._probed.model_id if self._probed else "")

    def _report(self, word: str, *, model: Optional[str] = None,
                detail: str = "", retry_after_s: Optional[float] = None) -> None:
        """One state report, with this backend's names filled in."""
        self.report_state(
            word, model=self._named_model() if model is None else model,
            detail=detail, retry_after_s=retry_after_s)

    # ── probe ────────────────────────────────────────────────────────────

    def probe(self, refresh: bool = False) -> ServedModel:
        """``GET {base}/models``, cached.

        Never raises: an unreachable server is a fact about the server,
        and a backend that explodes when asked what it can do is useless
        for exactly the case you asked.

        It is also the one place two of the seven model states can be
        told apart, so it **reports** what it found: nothing on the
        socket is ``absent``, and a server that answers without listing
        the model this backend asks for is ``cold``.  Reported, not
        returned as well — a report goes nowhere unless somebody
        installed a sink, and the two callers that want the answer as a
        value already get the :class:`ServedModel`.
        """
        if self._probed is not None and not refresh:
            return self._probed

        fallback = self._model or ""
        try:
            res = self._session.get(
                f"{self.endpoint}/models",
                headers=self._headers(),
                timeout=PROBE_TIMEOUT,
            )
            res.raise_for_status()
            payload = res.json() or {}
        except Exception as exc:  # noqa: BLE001 — any failure is "unreachable"
            self._probed = ServedModel(
                model_id=fallback, reachable=False, error=f"{type(exc).__name__}: {exc}",
            )
            self._report(state.ABSENT, model=fallback,
                         detail=f"{self.endpoint}/models: "
                                f"{type(exc).__name__}: {exc}")
            return self._probed

        entries = payload.get("data") or []
        served = tuple(str(e.get("id")) for e in entries
                       if isinstance(e, dict) and e.get("id"))
        entry: Dict[str, Any] = {}
        if self._model:
            entry = next(
                (e for e in entries if isinstance(e, dict)
                 and self._same_model(e.get("id"), self._model)),
                {},
            )
        elif entries and isinstance(entries[0], dict):
            # Only when nobody named one. A listing's first entry is the
            # server's idea of what it serves; it is an answer to "what is
            # there", never to "what did you ask for", and reporting it as
            # the served model of a run that asked for something else is
            # the probe inventing a fact. That is what it used to do: this
            # backend, pointed at a hosted OpenAI-compatible endpoint with
            # `LOCAL_MODEL` set, reported a DIFFERENT model as served
            # because the listing spelled ids `models/<name>`.
            entry = entries[0]

        self._probed = ServedModel(
            # What was asked for wins. An endpoint that does not list the
            # model may still serve it — a listing is a courtesy and the
            # chat endpoint is the authority — so a named model is never
            # replaced here, only annotated with what the listing knew.
            model_id=str(self._model or entry.get("id") or fallback),
            max_model_len=self._as_int(entry.get("max_model_len")),
            reachable=True,
            served=served,
        )
        if not self.lists(self._probed):
            self._report(
                state.COLD, model=fallback,
                detail=(f"{self.endpoint} is up and serves "
                        + (", ".join(served) if served else "no model")))
        return self._probed

    def lists(self, probed: Optional[ServedModel] = None) -> bool:
        """Whether the endpoint listed the model this backend will ask for.

        The signal that separates ``queued`` from ``cold`` when a request
        has been accepted and nothing has come back: the server having
        the model is what makes a silence a queue rather than an empty
        GPU.  A backend that named no model asks for whatever is served,
        so *anything at all* on the list satisfies it.
        """
        probed = self.probe() if probed is None else probed
        if not probed.reachable:
            return False
        if not self._model:
            return bool(probed.served)
        return self._model in probed.served

    @staticmethod
    def _same_model(listed: Any, wanted: str) -> bool:
        """Whether a listing entry names the model the caller asked for.

        Exactly, or by the last path segment: an OpenAI-compatible listing
        may spell its ids with a namespace (``models/<name>``) while the
        chat endpoint takes the bare name, and a comparison that missed
        that would report a served model as absent and throw away the
        ``max_model_len`` sitting beside it.
        """
        listed = str(listed or "")
        if not listed or not wanted:
            return False
        return (listed == wanted
                or listed.rsplit("/", 1)[-1] == wanted.rsplit("/", 1)[-1])

    @staticmethod
    def _as_int(value: Any) -> Optional[int]:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    # ── chat ─────────────────────────────────────────────────────────────

    #: Harmony control tokens. gpt-oss models are trained to emit a structured
    #: header — ``<|start|>assistant<|channel|>commentary to=functions.f
    #: <|message|>…`` — and vLLM's harmony parser understands them on the way
    #: OUT. It also parses them on the way IN, and that is where this bites.
    _HARMONY_HEADER = re.compile(
        r"<\|start\|>.*?(?:<\|message\|>|$)", re.DOTALL)
    _HARMONY_TOKEN = re.compile(r"<\|[a-z_]+\|>")

    @classmethod
    def _strip_harmony(cls, text: str) -> str:
        """Remove harmony control structure from a message body.

        **Defensive, and honestly not the cure for the bug that prompted it.**
        This was written to fix Tai's ``500 unexpected tokens remaining in
        message header: Some("to=")``, on the theory that the mission loop
        appends the model's harmony-token reply to the conversation and sends
        it back, and the server chokes re-parsing it. Reasonable, and wrong:
        the request carries no harmony tokens at all — see
        :meth:`_locate_suspect_text`, which found none — and the same body
        succeeds or fails depending only on ``max_tokens``. The malformed
        header is in what the model GENERATES, and vLLM 500s parsing its own
        output when the server has no tool-call parser configured. That is
        fixed where it belongs, in TAIPAN's ``served_model.OUTPUT_PARSERS``.

        Kept anyway, because it is cheap and the reasoning behind it holds for
        a case that has simply not bitten yet: a history poisoned from
        somewhere else — a resumed session, a memory store written before the
        serving fix — should not be able to 500 the server. A conversation on
        disk outlives the bug that wrote it.

        The header form is removed whole rather than token by token, because
        ``to=`` lives inside it: dropping only ``<|…|>`` markers would leave
        ``commentary to=functions.f`` behind as prose, which would be the same
        parse error with the evidence removed.
        """
        if not text or "<|" not in text:
            return text
        cleaned = cls._HARMONY_HEADER.sub("", text)
        cleaned = cls._HARMONY_TOKEN.sub("", cleaned)
        return cleaned.strip()

    def chat(
        self,
        model: str,
        messages: List[Dict],
        stream: bool = False,
        max_tokens: Optional[int] = None,
        *,
        json_schema: Any = None,
        **extra: Any,
    ):
        """POST ``{base}/chat/completions``.

        Returns a ``str`` when ``stream`` is false and an iterator of
        SSE deltas when it is true — the same two return types
        ``OpenAIBackend.chat`` has, because ``core.cli`` branches on
        ``chunk.choices[0].delta.content`` and does not know which
        backend it is draining.

        ``**extra`` goes into the body verbatim, which is how ``tools``,
        ``tool_choice``, ``parallel_tool_calls`` and ``response_format``
        reach an OpenAI-compatible server.

        ``json_schema`` is the constrained decode, and it goes through
        :meth:`~core.runtime.backends.base.Backend.constrained_response_format`
        rather than through ``**extra``: the door checks the capability
        and builds the envelope, and what comes back is written into the
        body as ``response_format``.  Nothing is added when it is absent.

        WHAT THE CALLER SENDS DECIDES WHAT COMES BACK.  Native tool calls
        are always reported on :attr:`last_tool_calls`, whatever was
        asked.  What changes is the ``str`` this returns: by default a
        reply that carried tool calls and no text is rendered into the
        mission protocol's one JSON object — see :meth:`_as_mission_json`,
        which owns that rule and states it — and a caller **speaking
        native** gets the content back untouched instead, empty if that is
        what the model produced.  Speaking native is
        ``tool_choice="required"`` or ``parallel_tool_calls=True``; see
        :meth:`_speaking_native`.
        """
        # Asked BEFORE anything is cleared or sent: a schema this backend
        # may not be asked for is a refusal about the request, not a call
        # that happened.
        constrained = self.constrained_response_format(json_schema)
        # Cleared before anything is sent: a call that raises must not
        # leave the previous call's numbers — or its tool calls — standing
        # for a ledger to count, or a runner to dispatch, a second time.
        self.last_usage = None
        self.last_tool_calls = []
        body: Dict[str, Any] = {
            "model": model or self.model,
            # Inbound scrub: see `_strip_harmony`. A history carrying harmony
            # tokens is refused by the server with a 500, so this is not
            # tidying — it is the difference between a second turn and none.
            "messages": [
                {**m, "content": self._strip_harmony(m["content"])}
                if isinstance(m.get("content"), str) else m
                for m in messages
            ],
        }
        # ALWAYS a number, which is the change. A caller's `max_tokens=`
        # wins, then whatever the deployment declared or set in the
        # environment, then the default — and there is no longer a branch
        # in which the field is left off. See
        # `DEFAULT_MAX_OUTPUT_TOKENS`: an absent `max_tokens` is not an
        # unbounded request, it is a request bounded by somebody who
        # cannot report it.
        body["max_tokens"] = (
            max_tokens if max_tokens is not None
            else self.output_bound)
        body.update(extra)
        if constrained is not None:
            # AFTER the passthrough, so the typed argument wins over a
            # `response_format` somebody also wrote into `**extra` — the
            # same rule the rest of this repo reads a typed flag by. Two
            # of them is a caller contradicting itself, and the one that
            # went through the capability door is the one that was
            # checked.
            body["response_format"] = constrained

        # The request exists; nothing has been sent yet. `asking` never
        # reaches the wire — see `state.WAITING` — and what it does here
        # is start the clock the later words are measured against.
        self._report(state.ASKING, model=str(body["model"]))

        if stream:
            body["stream"] = True
            # ASK for the counts. An OpenAI-compatible server streaming a
            # completion sends no `usage` at all unless this is set — vLLM
            # and llama.cpp both follow OpenAI here — so a streamed call
            # without it can only ever report nothing, and a ledger that
            # is empty for every streamed turn looks exactly like a
            # provider that does not count. It costs one extra frame,
            # which carries no choices and is therefore never yielded as
            # a delta; see `_stream`.
            body.setdefault("stream_options", {"include_usage": True})
            return self._stream(body)
        return self._complete(body)

    #: Backoff (seconds) before each retry of a refused connection — an
    #: alias for :data:`core.runtime.backends.policy.CONNECT_RETRIES`,
    #: which owns it and states why.  Kept as a class attribute because
    #: callers read the budget off the backend they are holding.
    CONNECT_RETRIES = policy.CONNECT_RETRIES

    def _post(self, body: Dict[str, Any], stream: bool):
        """POST once, and again only if the connect never happened.

        Which failures are worth re-sending is
        :data:`core.runtime.backends.policy.ERROR_POLICY`, not a decision
        this method makes: a refused connect costs nothing to repeat, a
        status code or a mid-body timeout is the server ANSWERING and
        re-sending it would double a completion that may already be
        decoding.

        Each refused attempt is *reported* as ``absent`` as it happens
        and not once the budget is spent: three retries span seventeen
        seconds, which is seventeen seconds of a person watching a pane
        that could have said "nothing is listening on that port" in the
        first one.  The same word four times over is one record — the
        de-duplication is the run's, not this method's; see
        :meth:`core.runtime.run.Model.watching`.
        """
        return policy.retry_on_connect(
            lambda: self._session.post(
                f"{self.endpoint}/chat/completions",
                headers=self._headers(),
                json=body,
                timeout=CHAT_TIMEOUT,
                stream=stream,
            ),
            retries=self.CONNECT_RETRIES,
            on_connect_error=lambda exc: self.report_connect_error(
                exc, model=str(body.get("model") or self._named_model())),
        )

    #: How much of a server's error body to put in front of a caller — an
    #: alias for :data:`core.runtime.backends.policy.ERROR_DETAIL_CHARS`,
    #: read the same way and for the same reason as CONNECT_RETRIES above.
    ERROR_DETAIL_CHARS = policy.ERROR_DETAIL_CHARS

    #: Fragments that make a harmony-speaking server refuse a whole request.
    #: Not an exhaustive list of harmony syntax — the ones that have actually
    #: cost a session.
    _SUSPECT = ("to=", "<|", "|>")

    @classmethod
    def _locate_suspect_text(cls, body: Dict[str, Any]) -> str:
        """Name the message carrying text a harmony parser will reject.

        A server that answers *"unexpected tokens remaining in message
        header"* is telling you a message is malformed and not WHICH, and a
        mission prompt is twelve thousand characters across several turns.
        Finding it by eye cost most of an afternoon; finding it by grep costs
        nothing, so the failure does it for the next person.
        """
        found = []
        for i, m in enumerate(body.get("messages") or []):
            content = m.get("content")
            if not isinstance(content, str):
                continue
            for needle in cls._SUSPECT:
                at = content.find(needle)
                if at >= 0:
                    start = max(0, at - 60)
                    found.append(
                        f"messages[{i}] role={m.get('role')!r} contains "
                        f"{needle!r}: ...{content[start:at + 60]!r}...")
                    break
        return "\n  ".join(found)

    def _raise_for_status(self, res, body: Optional[Dict[str, Any]] = None) -> None:
        """The shared body-as-diagnosis rule, plus the harmony hint.

        :func:`core.runtime.backends.policy.raise_for_status` owns the
        rule — the status, the URL, and a bounded slice of what the server
        actually said, because ``requests``' own ``raise_for_status``
        produces ``500 Server Error for url ...`` and throws the sentence
        away. That mattered immediately: Tai reached a served gpt-oss-20b
        during the first bake-off and got ``500`` with nothing else, which
        is indistinguishable from the server being broken, so the run was
        reported as "the server rejects the request shape". The shape was
        in the body the whole time.

        What stays here is the half that is only true of this backend: a
        harmony-speaking server refuses a whole request over text
        somewhere else in the conversation, so the message names where —
        see :meth:`_locate_suspect_text`. It is appended by the error
        factory rather than by a second copy of the formatting, so the
        two raw-HTTP backends cannot drift on what a failure reads like.

        It is also where the server's own account of itself is turned
        into a state.  A **503** is the one answer that means *loading*,
        and it means it because the server said so rather than because
        this harness guessed from a silence; a **429** is *queued* for
        the same reason.  Which code says which is
        :data:`core.runtime.backends.policy.STATUS_STATES`, and anything
        else falls through to its :data:`~core.runtime.backends.policy.ERROR_POLICY`
        class.  The report goes out **before** the raise, because the
        exception is on its way to a caller that will end the turn with
        it and the state is what a watcher needed while the turn was
        still alive.
        """
        where = (self._locate_suspect_text(body or {})
                 if res.status_code >= 400 else "")
        word = policy.state_for_status(res.status_code)
        if word:
            self._report(
                word, model=str((body or {}).get("model") or self._named_model()),
                detail=policy.status_message(
                    res, f"{self.endpoint}/chat/completions",
                    detail_chars=self.ERROR_DETAIL_CHARS),
                retry_after_s=state.retry_after_seconds(
                    getattr(res, "headers", None)))

        def error(message: str, response) -> Exception:
            if where:
                message += ("\n\nText a harmony parser will refuse, in what "
                            "we sent:\n  " + where)
            return requests.HTTPError(message, response=response)

        policy.raise_for_status(
            res, f"{self.endpoint}/chat/completions",
            detail_chars=self.ERROR_DETAIL_CHARS, error=error)

    def _late_first_byte(self, body: Dict[str, Any]) -> None:
        """Queued, cold or absent — asked of ``/models``, not guessed.

        Runs on a timer thread when an accepted request has produced
        nothing for :attr:`first_byte_queued_s` seconds, which is the
        exact moment a deployment spent two weeks unable to explain.  The
        silence alone says nothing, so this **asks**: the endpoint
        listing the model means it is loaded and somebody else is in
        front of us (``queued``); the endpoint listing something else, or
        nothing, means the wait is for a model that is not there
        (``cold``); an endpoint that does not answer at all means the
        server went away mid-request (``absent``).  The last two are
        :meth:`probe`'s own words and are reported by it, so only the
        first is said here.

        A second round trip during a stalled call is a cheap thing to
        spend on the difference between *wait* and *fix it*, and it is
        bounded by :data:`PROBE_TIMEOUT`.
        """
        probed = self.probe(refresh=True)
        if not self.lists(probed):
            return
        self._report(
            state.QUEUED, model=str(body.get("model") or self._named_model()),
            detail=(f"the server accepted the request and has sent nothing "
                    f"for {self.first_byte_queued_s:g}s; {self.endpoint} "
                    f"lists the model, so it is loaded and this is a queue"))

    def _long_stream(self, body: Dict[str, Any],
                     progress: "_StreamProgress") -> bool:
        """The call is still answering — say so, once.  Or ask again.

        Runs on a timer thread :attr:`streaming_long_s` seconds after the
        request went out.  The gap it closes is the one the v1.4.0
        regression diagnosis is made of: five stalls whose entire trace
        was a ``step_started`` and then nothing, because the first byte
        had arrived inside twenty seconds, ``first_byte_within`` had
        stood down, and no instrument in this harness was watching a call
        that answers slowly rather than not at all.

        **Nothing is said when the first frame has not arrived.**  That
        wait belongs to :meth:`_late_first_byte`, which has already asked
        ``/models`` and said ``queued`` or ``cold`` about it, and a second
        opinion from here would be this backend disagreeing with itself
        about a silence.  So the word is only ever said about frames this
        backend actually watched go past — which is why it is a
        measurement and not a guess, and why the counts are in it.

        **But it asks again instead of standing down**, which is the
        difference between an instrument and a coincidence.  A one-shot
        that returned here would mean a call whose first token arrives
        AFTER the threshold — the server that is slow to start *and* slow
        to finish, which is the worse version of the same afternoon — is
        never reported at all: ``queued`` at twenty seconds, ``loaded``
        when the token lands, and then two hundred seconds of the same
        silence this word exists to end, now with a wait that was opened
        and closed to make it look accounted for.  Returning ``True``
        re-arms the same alarm for another :attr:`streaming_long_s` — see
        :func:`~core.runtime.backends.state.alarm_after` — so the windows
        stay aligned to the request clock, which is the clock ``since_s``
        is measured on.

        One report and no repeat once it HAS spoken: see
        :data:`STREAMING_LONG_S
        <core.runtime.backends.state.STREAMING_LONG_S>`.  The wait it
        opens is closed by :meth:`_stream`, which reports ``loaded`` when
        the frames stop and ``failed`` when they stop because the stream
        died.

        **The detail states no elapsed time**, and that is the re-arming
        above forcing an honest split rather than a stylistic choice.
        How long this call has been going is ``since_s``'s to say — the
        emitter measures it from the request, per call, and is the only
        thing here that knows which window fired.  A sentence naming
        :attr:`streaming_long_s` would be right on the first window and
        wrong on every later one: a call silent for 150s and then
        trickling reports ``since_s: 180`` beside prose claiming sixty,
        which is two fields of one record disagreeing about one fact.
        So the counts — which this backend did watch go past — stay, and
        the clock has one owner.
        """
        if not progress.arrived:
            return True
        progress.reported = True
        self._report(
            state.STREAMING,
            model=progress.model or str(body.get("model")
                                        or self._named_model()),
            detail=(f"the model is still answering — {progress.frames} "
                    f"frames and {progress.chars} characters of content so "
                    f"far"))
        return False

    def _stream_died(self, body: Dict[str, Any],
                     progress: "_StreamProgress", exc: BaseException) -> None:
        """Close a streaming wait that ended in an exception, not an answer.

        **Something must close a wait this backend opened**, and until
        this existed nothing did: a ``ConnectionError`` out of
        ``iter_lines`` after the long-call word had gone out reaches
        neither :meth:`_post`'s retry (the connect already succeeded) nor
        :meth:`_raise_for_status` (the status was already 200), so the
        run's de-duplicator kept the wait open — and then emitted the
        NEXT, healthy call's ``loaded`` against it, which is a ``loaded``
        on a call where nothing went wrong and which ``CONTRACT.md``
        forbids in as many words.  Worse when the failure ends the run:
        the last thing on the stream is a model still answering, after
        ``mission_finished``.

        ``failed`` and not a ``loaded`` that explains itself, because the
        two words are read differently by something that is not reading
        the sentence: a consumer clears a wait on ``loaded`` and shows
        the call as having recovered.  This call did not recover.  The
        word is read off :data:`~core.runtime.backends.policy.ERROR_POLICY`
        rather than written here — the ``timeout`` row, whose reasoning
        is exactly this case: *the request IS in flight — the server may
        be decoding it right now*.  A stream that dies mid-body is that
        row's situation, not the ``connect`` row's, which says the
        request never left this host.

        **Every way out that is not the end of the stream**, which is why
        the caller catches ``BaseException``: a consumer that walked away
        and a run that was cancelled leave exactly the same open wait as
        a broken socket, and the cancelled case is the one where a
        dangling *still answering* is most visible — it would be the last
        word on the stream, after ``mission_finished``.  ``failed`` is
        honest across all three, because what it says of the call is what
        is true of all of them: it did not deliver.  The detail names
        which, by exception type.

        Said only when the long-call word went out.  A stream that dies
        without one opened no wait, and the exception on its way to the
        caller is the whole of what happened.
        """
        if not progress.reported:
            return
        progress.reported = False
        self._report(
            policy.ERROR_POLICY["timeout"].state,
            model=progress.model or str(body.get("model")
                                        or self._named_model()),
            detail=(f"the stream stopped after {progress.frames} frames and "
                    f"{progress.chars} characters: "
                    f"{type(exc).__name__}: {exc}"))

    def _complete(self, body: Dict[str, Any]) -> str:
        with state.first_byte_within(self.first_byte_queued_s,
                                     lambda: self._late_first_byte(body)):
            res = self._post(body, stream=False)
        self._raise_for_status(res, body)
        payload = res.json() or {}
        # What actually answered, said as the SERVER names it: a request
        # for `local-model` served by `gpt-oss-20b` is a fact worth having
        # on the record, and it is the one moment this backend learns it.
        self._report(state.LOADED,
                     model=str(payload.get("model") or body.get("model") or ""))
        choices = payload.get("choices") or []
        first = choices[0] if choices else {}
        # Before the empty-choices return, not after it: a completion that
        # produced no content still spent the prompt, and a reply nobody
        # could use is exactly the call worth finding in the ledger.
        #
        # The finish reason is read off the CHOICE and handed to the counts,
        # because "how many tokens" and "and then it hit the ceiling" are
        # one fact about one call and a consumer that gets only the first
        # half has been told a truncated answer was complete.
        self.last_usage = Usage.from_payload(
            payload.get("usage"), first.get("finish_reason"))
        if not choices:
            return ""
        message = first.get("message") or {}
        # Always, and before the branch: what the model decided is a fact
        # about the reply, not about the protocol the caller asked for.
        self.last_tool_calls = tool_calls_from(message.get("tool_calls"))
        content = self._strip_harmony(message.get("content") or "")
        if self._speaking_native(body):
            # No synthesis. The caller reads `last_tool_calls` itself and
            # a manufactured JSON object would be a second, disagreeing
            # copy of the same decision. The harmony scrub still runs: it
            # repairs a server's own parser bug and has nothing to do with
            # which protocol is being spoken.
            return content
        return content or self._as_mission_json(self.last_tool_calls)

    @staticmethod
    def _speaking_native(body: Dict[str, Any]) -> bool:
        """Whether this request asked for tool calls in the provider's own shape.

        THE RULE, IN ONE PLACE.  A caller is speaking native when it sent
        ``tool_choice="required"`` or ``parallel_tool_calls=True``.  Either
        one is a request the mission protocol cannot express — the first
        constrains the decoder to emit a call rather than prose, the second
        asks for more calls than a one-tool-per-turn loop can dispatch —
        so a caller that sends one is telling this backend it will read
        :attr:`last_tool_calls` itself.

        ``tool_choice="auto"`` is NOT native speech, and that is the whole
        point of naming the rule this way: ``auto`` beside ``tools`` is
        what every deployed mission has sent since 10 August, it is there
        to stop vLLM 500ing on its own harmony output, and those runs must
        keep getting mission JSON back.
        """
        return (body.get("tool_choice") == "required"
                or body.get("parallel_tool_calls") is True)

    @staticmethod
    def _as_mission_json(calls: List[Dict[str, Any]]) -> str:
        """Render a native ``tool_calls`` reply into the mission protocol.

        The kernel reads one JSON object — ``{"tool": …, "arguments": {…}}`` —
        out of the reply text. A model given ``tools`` answers in the OpenAI
        tool-call field instead, with empty content, and the loop would see
        nothing and spend a repair turn asking for JSON it already has.

        Translating here rather than teaching the kernel two dialects is the
        adapter doing its job: this class exists to make one server's habits
        look like the protocol everything else speaks. The kernel stays
        unchanged and keeps working against a backend with no tool-call
        support at all.

        Only the FIRST call is rendered. The protocol is one tool per turn on
        purpose — the loop dispatches, appends the result, and asks again —
        and quietly dropping a second call would be worse than never seeing
        it, so the model is told what happened.

        **This is the DEFAULT and not the only mode.** Every call the model
        made — all of them, in order, arguments parsed — is on
        :attr:`last_tool_calls` whether or not this ran, so nothing is lost
        here; what is dropped is only this rendering's view of them. A
        caller that wants the calls themselves says so in the request and
        gets the content back unsynthesized instead: see
        :meth:`_speaking_native`, which owns that rule.

        *calls* is the NORMALIZED list — what
        :func:`~core.runtime.backends.base.tool_calls_from` made, which is
        what :attr:`last_tool_calls` already holds — rather than the raw
        message.  Both paths that render this now have one, and a streamed
        reply is assembled out of fragments and never had a message at
        all: rendering from the calls is what lets the streamed and the
        non-streamed reply be the same string rather than two dialects.
        """
        if not calls:
            return ""
        first = calls[0] or {}
        decision: Dict[str, Any] = {"tool": first.get("name") or "",
                                    "arguments": first.get("arguments") or {}}
        if len(calls) > 1:
            decision["note"] = (
                f"{len(calls)} tool calls were offered; this protocol takes "
                f"one per turn, so the rest were not run.")
        return json.dumps(decision)

    def _stream(self, body: Dict[str, Any]) -> Iterator[SimpleNamespace]:
        """Yield one delta per frame that has one, and keep the last usage.

        Two things are read off a frame now.  The counts, when the server
        sent them — with ``stream_options.include_usage`` they arrive on
        a **final frame of their own**, whose ``choices`` is empty — and
        the delta, when the frame has one.

        A frame with no choices is therefore not yielded.  It never was a
        delta: passing it on would hand ``core.cli`` a chunk whose
        ``choices[0]`` does not exist, and the usage frame is the first
        such frame this backend has ever met.  ``_as_delta`` is untouched
        and still describes exactly what a delta is.

        A third thing is read but never yielded: tool-call fragments.
        They arrive as pieces of a JSON string spread over many frames,
        so they are folded into an accumulator on the way past and
        published on :attr:`last_tool_calls` in the same ``finally`` as
        the counts — a half-arrived call is not a decision.  The frames
        themselves still reach the consumer untouched.

        **A streamed reply and a non-streamed one are the same reply.**
        A caller not speaking native gets its tool calls rendered into
        the mission protocol's one JSON object — see
        :meth:`_as_mission_json`, which is the whole reason a served
        gpt-oss answers a mission at all — and a streamed call must not
        lose that just because the text was assembled from frames.  So
        when the stream is over and nothing came through as ``content``,
        the rendering goes out as one last frame carrying it: a caller
        concatenating ``delta.content`` ends up holding exactly the
        string :meth:`_complete` would have returned.  Nothing is
        invented for a caller that DID get content, and nothing at all
        for one speaking native, which reads
        :attr:`last_tool_calls` itself.

        **Two alarms, and they watch opposite failures.**  The first-byte
        one asks why nothing has come back; the long-call one, armed for
        the whole request and never disarmed by a frame, says that
        something IS coming back and has been for a long time.  Before it
        existed a call that trickled for two hundred seconds produced no
        record at all — see :meth:`_long_stream`, which is where that
        costs a paragraph.
        """
        seen: Optional[Usage] = None
        calls = ToolCallAccumulator()
        spoke = False
        finish: Any = None
        # "Has the first frame landed" is ONE fact with one owner, and
        # that owner is the object the timer thread reads: a local beside
        # it would be a second copy of it, and the two would disagree in
        # exactly the window this whole change exists to describe.
        progress = _StreamProgress()
        try:
            # The alarm covers the request AND the wait for the first
            # frame, because on a streamed call those are the same wait
            # from outside: the POST returns as soon as the headers do
            # and the server may then think for a minute before the
            # first token. Disarmed by the first frame, and by the
            # `finally` for a consumer that walked away.
            #
            # The long-call alarm OUTSIDE it, covering the same request
            # and never disarmed early: the question it answers is about
            # the whole call, and `since_s` on the record is measured
            # from the request going out, so its clock and the record's
            # clock are the same clock.
            with state.alarm_after(
                    self.streaming_long_s,
                    lambda: self._long_stream(body, progress)), \
                 state.first_byte_within(
                    self.first_byte_queued_s,
                    lambda: self._late_first_byte(body)) as watch:
                res = self._post(body, stream=True)
                self._raise_for_status(res, body)
                for line in res.iter_lines():
                    if not line:
                        continue
                    if isinstance(line, bytes):
                        line = line.decode("utf-8", errors="replace")
                    if not line.startswith("data:"):
                        continue
                    data = line[len("data:"):].strip()
                    if not data or data == "[DONE]":
                        if data == "[DONE]":
                            break
                        continue
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    found = Usage.from_payload(chunk.get("usage"))
                    if found is not None:
                        seen = found
                    for choice in chunk.get("choices") or []:
                        delta = choice.get("delta") or {}
                        calls.add(delta.get("tool_calls"))
                        if delta.get("content"):
                            spoke = True
                            progress.chars += len(delta["content"])
                        # The reason arrives on the LAST frame with
                        # choices, which is a different frame from the one
                        # carrying the counts. Kept here and folded in at
                        # the end rather than looked for in one place,
                        # because a stream is where the two halves of one
                        # fact travel separately.
                        if choice.get("finish_reason"):
                            finish = choice["finish_reason"]
                    if not chunk.get("choices"):
                        continue
                    progress.frames += 1
                    if not progress.arrived:
                        # The first frame IS the model answering, so this
                        # is where a wait that was reported ends. The id
                        # is the server's own — see `_complete`.
                        watch.arrived()
                        progress.model = str(chunk.get("model")
                                             or body.get("model") or "")
                        progress.arrived = True
                        self._report(state.LOADED, model=progress.model)
                    yield self._as_delta(chunk)
                if not spoke and not self._speaking_native(body):
                    rendered = self._as_mission_json(calls.result())
                    if rendered:
                        yield self._content_frame(rendered)
                if progress.reported:
                    # The long-call state said a wait was on. A wait is
                    # announced once and CLOSED once — the rule
                    # `core.runtime.run._ModelStates` owns — so the end of
                    # the stream says so, and a pane that put up "still
                    # answering" takes it down. `loaded` HERE, because
                    # this stream finished; the stream that died has its
                    # own word, in `_stream_died`.
                    progress.reported = False
                    self._report(
                        state.LOADED,
                        model=progress.model or str(body.get("model") or ""),
                        detail=(f"the stream finished — {progress.frames} "
                                f"frames and {progress.chars} characters "
                                f"of content"))
        except BaseException as exc:
            # EVERY way out that is not the end of the stream, including
            # a `GeneratorExit` from a consumer that walked away and a
            # cancellation: a wait this backend opened must not outlive
            # the call, because the run's de-duplicator would spend the
            # NEXT call's `loaded` closing it. See `_stream_died`.
            self._stream_died(body, progress, exc)
            raise
        finally:
            # In a `finally` so that a consumer that walks away mid-stream
            # still leaves behind whatever had been reported by then —
            # the abandoned case is the one that has to work.
            self.last_usage = (
                seen if seen is None
                else replace(seen, finish_reason=truncation_of(finish)))
            self.last_tool_calls = calls.result()

    @staticmethod
    def _content_frame(text: str) -> SimpleNamespace:
        """One frame carrying *text* as content, in the shape of a delta.

        The synthesized rendering of a tool-call-only reply — see
        :meth:`_stream`.  Shaped by hand rather than through
        :meth:`_as_delta` because there is no chunk: the server never
        sent this, this backend wrote it, and the honest way to say so is
        that it carries neither an id nor a model.
        """
        return SimpleNamespace(
            id=None, model=None,
            choices=[SimpleNamespace(
                index=0, finish_reason=None,
                delta=SimpleNamespace(role=None, content=text,
                                      tool_calls=None))],
        )

    @staticmethod
    def _as_delta(chunk: Dict[str, Any]) -> SimpleNamespace:
        """Reshape one SSE chunk into what ``core.cli`` walks.

        ``SimpleNamespace`` and not a dataclass on purpose: the consumer
        is ``getattr`` chains written against the OpenAI SDK's objects,
        and matching that shape is the whole job.
        """
        choices = []
        for raw in chunk.get("choices") or []:
            delta = raw.get("delta") or {}
            choices.append(
                SimpleNamespace(
                    index=raw.get("index", 0),
                    finish_reason=raw.get("finish_reason"),
                    delta=SimpleNamespace(
                        role=delta.get("role"),
                        content=delta.get("content"),
                        tool_calls=delta.get("tool_calls"),
                    ),
                )
            )
        return SimpleNamespace(
            id=chunk.get("id"),
            model=chunk.get("model"),
            choices=choices,
        )

    # ── capabilities ─────────────────────────────────────────────────────

    @property
    def capabilities(self) -> BackendCapabilities:
        """What this endpoint can do, probed where probing can answer.

        ``max_context_tokens`` is the served model's ``max_model_len``
        when ``GET /models`` reports one, an explicit constructor value
        otherwise, and ``None`` when neither — never a guess.

        ``supports_tool_calls`` is **declared, not probed**: no field of
        ``/models`` answers it, and the OpenAI-compatible contract this
        backend speaks includes ``tools``.  A vLLM-served gpt-oss-20b
        honours it, which is why the default is ``True`` and why the old
        stub's ``False`` was wrong rather than cautious.  A server that
        does not, gets ``supports_tool_calls=False`` at construction.

        ``supports_parallel_tool_calls`` and
        ``supports_tool_choice_required`` follow that same declaration and
        cannot outrun it: a server told it does not speak ``tools`` must
        not be reported as speaking a constrained form of them.

        ``supports_json_schema`` is declared ``True``, and it is the one
        declaration here that comes with an honest degradation.  Every
        server this backend exists for speaks it — vLLM, SGLang and
        TensorRT-LLM all take ``response_format={"type": "json_schema",
        …}`` and hold the decode to the grammar — but a *different*
        OpenAI-compatible server may accept the parameter and ignore it,
        and no field of ``GET /models`` says which kind is listening.
        There is no probe to run, so the promise this flag makes is
        narrow: **the request will carry the schema**, not that the
        endpoint honoured it.  A server that ignores it answers
        unconstrained, and the CONSUMER's validator is what catches that
        — see :mod:`core.eval.extraction`, whose ``--constrained`` run
        counts a structurally invalid reply and says in the report that
        the endpoint likely ignored the schema.  Declaring ``False`` to
        avoid the case would refuse the servers the capability was built
        for; declaring ``True`` and leaving the check downstream is the
        arrangement that can tell the two apart.

        ``tool_choice="required"`` is the one of the two that was actually
        PROBED — 10 Aug 2026, vLLM 0.14.1 serving ``openai/gpt-oss-20b``,
        which returned a well-formed native call with ``content`` null.
        That is why it is ``True`` here rather than cautiously ``False``:
        a measured capability declared as absent is a measurement thrown
        away.  ``parallel_tool_calls`` was not probed and is declared on
        the same grounds as ``supports_tool_calls`` above — it is part of
        the OpenAI-compatible contract this backend speaks, and a server
        that does not honour it is a server constructed with
        ``supports_tool_calls=False``.
        """
        probed = self.probe()
        max_context = self._max_context_tokens
        if max_context is None:
            max_context = probed.max_model_len
        return BackendCapabilities(
            supports_streaming=True,
            supports_json_mode=True,
            supports_json_schema=True,
            supports_tool_calls=self._supports_tool_calls,
            supports_parallel_tool_calls=self._supports_tool_calls,
            supports_tool_choice_required=self._supports_tool_calls,
            max_context_tokens=max_context,
            max_output_tokens=self.output_bound,
        )
