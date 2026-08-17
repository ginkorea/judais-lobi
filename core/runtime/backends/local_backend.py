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
advertises and what ``LOCAL_API_BASE`` is expected to hold.  A base that
omits it is repaired at construction with a warning rather than
producing a 404 an hour later.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Dict, Iterator, List, Optional

import requests

from core.runtime.backends.base import (
    Backend,
    BackendCapabilities,
    ToolCallAccumulator,
    Usage,
    tool_calls_from,
)

DEFAULT_LOCAL_API_BASE = "http://127.0.0.1:8000/v1"
DEFAULT_LOCAL_MODEL = "local-model"

#: Seconds to wait on ``GET /models``.  Short: the probe is a convenience,
#: and a capabilities lookup must never be the thing that hangs a CLI.
PROBE_TIMEOUT = 5.0
#: Seconds to wait on ``POST /chat/completions``.  Long: a cold vLLM
#: server loads weights for ~100s before it answers the first request.
CHAT_TIMEOUT = 600.0


@dataclass(frozen=True)
class ServedModel:
    """What ``GET {base}/models`` said, or why it said nothing.

    ``reachable`` is the honest bit.  An unreachable server yields a
    ``ServedModel`` with ``reachable=False`` and ``max_model_len=None``
    — never a guessed context length, because a guessed context window
    is how a request gets truncated silently.
    """

    model_id: str
    max_model_len: Optional[int] = None
    reachable: bool = False
    error: str = ""


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
    """

    def __init__(
        self,
        endpoint: Optional[str] = None,
        model: Optional[str] = None,
        max_context_tokens: Optional[int] = None,
        max_output_tokens: Optional[int] = None,
        api_key: Optional[str] = None,
        supports_tool_calls: bool = True,
        session: Any = None,
    ):
        raw = endpoint or os.getenv("LOCAL_API_BASE") or DEFAULT_LOCAL_API_BASE
        self.endpoint = self._normalize_base(raw)
        self._model = model or os.getenv("LOCAL_MODEL") or None
        self._max_context_tokens = max_context_tokens
        self._max_output_tokens = max_output_tokens
        self._api_key = api_key or os.getenv("LOCAL_API_KEY") or None
        self._supports_tool_calls = supports_tool_calls
        self._session = session if session is not None else requests
        self._probed: Optional[ServedModel] = None
        self.last_usage = None
        self.last_tool_calls = []

    # ── configuration ────────────────────────────────────────────────────

    @staticmethod
    def _normalize_base(base: str) -> str:
        """Strip a trailing slash; append ``/v1`` when it is missing.

        A base without the version prefix is the single most common
        misconfiguration of this backend, and it fails as a 404 on the
        first chat rather than at construction.  Repairing it here keeps
        that hour.
        """
        base = (base or "").strip().rstrip("/")
        if not base:
            return DEFAULT_LOCAL_API_BASE
        tail = base.rsplit("/", 1)[-1]
        if not tail.startswith("v") or not tail[1:].isdigit():
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

    # ── probe ────────────────────────────────────────────────────────────

    def probe(self, refresh: bool = False) -> ServedModel:
        """``GET {base}/models``, cached.

        Never raises: an unreachable server is a fact about the server,
        and a backend that explodes when asked what it can do is useless
        for exactly the case you asked.
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
            return self._probed

        entries = payload.get("data") or []
        entry: Dict[str, Any] = {}
        if self._model:
            entry = next(
                (e for e in entries if isinstance(e, dict) and e.get("id") == self._model),
                {},
            )
        if not entry and entries and isinstance(entries[0], dict):
            entry = entries[0]

        self._probed = ServedModel(
            model_id=str(entry.get("id") or fallback),
            max_model_len=self._as_int(entry.get("max_model_len")),
            reachable=True,
        )
        return self._probed

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
        limit = max_tokens if max_tokens is not None else self._max_output_tokens
        if limit is not None:
            body["max_tokens"] = limit
        body.update(extra)

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

    #: Backoff (seconds) before each retry of a refused connection. Three
    #: tries spanning ~17s: a vLLM endpoint that bounces or hands off ports
    #: mid-session comes back inside that window; one that is truly down
    #: fails just as clearly 17 seconds later. Measured 12 Aug 2026: one
    #: mid-eval turn died at step 0 on a single refused connect while the
    #: turns on either side of it succeeded — a whole turn is too much to
    #: pay for one blip.
    CONNECT_RETRIES = (2.0, 5.0, 10.0)

    def _post(self, body: Dict[str, Any], stream: bool):
        last: Exception | None = None
        for wait in (0.0, *self.CONNECT_RETRIES):
            if wait:
                time.sleep(wait)
            try:
                return self._session.post(
                    f"{self.endpoint}/chat/completions",
                    headers=self._headers(),
                    json=body,
                    timeout=CHAT_TIMEOUT,
                    stream=stream,
                )
            except requests.exceptions.ConnectionError as exc:
                # Refused/reset connect only — an HTTP error or a mid-body
                # timeout is the server ANSWERING, and re-sending those
                # would double a completion that may already be decoding.
                last = exc
        raise last  # type: ignore[misc]

    #: How much of a server's error body to put in front of a caller. Enough
    #: for vLLM's `{"object":"error","message":...}` to arrive whole; short
    #: enough that a stack trace does not become the error message.
    ERROR_DETAIL_CHARS = 600

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
        """Fail with what the server SAID, not just the number it returned.

        ``requests``' own ``raise_for_status`` produces ``500 Server Error for
        url ...`` and discards the body — and the body is the whole diagnosis.
        An OpenAI-compatible server puts a real sentence there: which parameter
        it rejected, that ``max_tokens`` came out negative, that the model name
        does not match what is loaded.

        This mattered immediately. Tai reached a served gpt-oss-20b during the
        first bake-off and got ``500`` with nothing else, which is
        indistinguishable from the server being broken — so the run was
        reported as "the server rejects the request shape", which was a guess.
        The shape was in the body the whole time.

        Same fix, same reason, as `RemoteSshComputeProvider._sh` in TAIPAN:
        bounded, and in front of the operator.
        """
        if res.status_code < 400:
            return
        try:
            detail = (res.json() or {}).get("message") or res.text
        except ValueError:
            detail = res.text
        detail = (detail or "").strip()[:self.ERROR_DETAIL_CHARS]
        message = (f"{res.status_code} from {self.endpoint}/chat/completions"
                   + (f": {detail}" if detail
                      else " (and the server said nothing)"))
        where = self._locate_suspect_text(body or {})
        if where:
            message += ("\n\nText a harmony parser will refuse, in what we "
                        "sent:\n  " + where)
        raise requests.HTTPError(message, response=res)

    def _complete(self, body: Dict[str, Any]) -> str:
        res = self._post(body, stream=False)
        self._raise_for_status(res, body)
        payload = res.json() or {}
        # Before the empty-choices return, not after it: a completion that
        # produced no content still spent the prompt, and a reply nobody
        # could use is exactly the call worth finding in the ledger.
        self.last_usage = Usage.from_payload(payload.get("usage"))
        choices = payload.get("choices") or []
        if not choices:
            return ""
        message = choices[0].get("message") or {}
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
        """
        res = self._post(body, stream=True)
        self._raise_for_status(res, body)
        seen: Optional[Usage] = None
        calls = ToolCallAccumulator()
        spoke = False
        try:
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
                if not chunk.get("choices"):
                    continue
                yield self._as_delta(chunk)
            if not spoke and not self._speaking_native(body):
                rendered = self._as_mission_json(calls.result())
                if rendered:
                    yield self._content_frame(rendered)
        finally:
            # In a `finally` so that a consumer that walks away mid-stream
            # still leaves behind whatever had been reported by then —
            # the abandoned case is the one that has to work.
            self.last_usage = seen
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
            supports_tool_calls=self._supports_tool_calls,
            supports_parallel_tool_calls=self._supports_tool_calls,
            supports_tool_choice_required=self._supports_tool_calls,
            max_context_tokens=max_context,
            max_output_tokens=self._max_output_tokens,
        )
