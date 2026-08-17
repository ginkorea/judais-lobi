# core/runtime/context_window.py — Context window tracking + auto-compaction

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from core.bounding import MAX_RESULT_BYTES
from core.context.formatter import estimate_tokens
from core.tools.config_loader import load_project_config


@dataclass(frozen=True)
class ModelContextProfile:
    max_context_tokens: int
    max_output_tokens: int
    source: str = "default"

    @property
    def max_input_tokens(self) -> int:
        return max(self.max_context_tokens - self.max_output_tokens, 0)


@dataclass
class ContextConfig:
    max_context_tokens: Optional[int] = None
    max_output_tokens: Optional[int] = None
    max_tool_output_bytes_in_context: int = MAX_RESULT_BYTES
    min_tail_messages: int = 6
    max_summary_chars: int = 2400
    provider_defaults: Dict[str, int] = field(default_factory=dict)
    model_overrides: Dict[str, int] = field(default_factory=dict)

    @staticmethod
    def from_project(project_root=None) -> "ContextConfig":
        cfg = load_project_config(project_root)
        ctx = cfg.get("context", {}) if isinstance(cfg, dict) else {}
        return ContextConfig(
            max_context_tokens=ctx.get("max_context_tokens"),
            max_output_tokens=ctx.get("max_output_tokens"),
            max_tool_output_bytes_in_context=int(
                ctx.get("max_tool_output_bytes_in_context", MAX_RESULT_BYTES)
            ),
            min_tail_messages=int(ctx.get("min_tail_messages", 6)),
            max_summary_chars=int(ctx.get("max_summary_chars", 2400)),
            provider_defaults=dict(ctx.get("provider_defaults", {}) or {}),
            model_overrides=dict(ctx.get("model_overrides", {}) or {}),
        )


DEFAULT_MODEL_CONTEXTS: Dict[str, ModelContextProfile] = {
    # Conservative defaults; override in .judais-lobi.yml if needed.
    "gpt-4o": ModelContextProfile(128000, 4096, source="default"),
    "gpt-4o-mini": ModelContextProfile(128000, 4096, source="default"),
    "gpt-4.1": ModelContextProfile(128000, 4096, source="default"),
    "gpt-4.1-mini": ModelContextProfile(128000, 4096, source="default"),
    "gpt-4-turbo": ModelContextProfile(128000, 4096, source="default"),
    "gpt-4": ModelContextProfile(8192, 2048, source="default"),
    "gpt-3.5-turbo": ModelContextProfile(16384, 2048, source="default"),
    "codestral-latest": ModelContextProfile(32768, 4096, source="default"),
    "mistral-large-latest": ModelContextProfile(32768, 4096, source="default"),
}

DEFAULT_PROVIDER_CONTEXTS: Dict[str, int] = {
    "openai": 128000,
    # Conservative floor (Haiku 4.5); the anthropic backend's MODEL_LIMITS
    # is the owner and reaches here through backend_caps when the model is known.
    "anthropic": 200000,
    "mistral": 32768,
    "local": 32768,
}

@dataclass
class ContextStats:
    total_tokens: int
    limit_tokens: int
    was_compacted: bool
    summary_tokens: int = 0
    removed_messages: int = 0
    profile_source: str = "default"


class ContextWindowManager:
    """Builds a token-bounded message list with optional compaction."""

    def __init__(self, config: Optional[ContextConfig] = None, project_root=None):
        self._config = config or ContextConfig.from_project(project_root)

    def build_messages(
        self,
        system_prompt: str,
        history: List[Dict[str, str]],
        invoked_tools: Optional[List[str]],
        provider: str,
        model: str,
        backend_caps=None,
    ) -> Tuple[List[Dict[str, str]], ContextStats]:
        from core.runtime.messages import build_chat_context

        messages = build_chat_context(system_prompt, history, invoked_tools)
        profile = self.resolve_profile(provider, model, backend_caps)
        compacted, stats = self._compact(messages, profile)
        return compacted, stats

    def resolve_profile(
        self,
        provider: str,
        model: str,
        backend_caps=None,
    ) -> ModelContextProfile:
        """How much room this provider/model/endpoint actually has.

        Public because it has a second caller: :class:`MissionWindow` needs
        the same answer for the mission loop, and a second copy of this
        cascade would be a second opinion about how big the window is.  The
        private name is kept as an alias for the callers that had it.
        """
        cfg = self._config
        # Backend capabilities override (instance-aware).
        #
        # `max_ctx` alone is enough, and that is not a loosening.  A served
        # model's `max_model_len` is the ONE number here that is measured
        # rather than assumed — `LocalBackend.capabilities` reads it off
        # `GET /models` — while `max_output_tokens` is a setting nobody is
        # obliged to have declared.  Requiring both meant that the moment a
        # real 8,192-token endpoint failed to also state an output reserve,
        # the probe was discarded and a 32,768 provider default was used in
        # its place: the exact request that 400s, chosen over the exact
        # number that would have prevented it.
        if backend_caps is not None:
            max_ctx = getattr(backend_caps, "max_context_tokens", None)
            max_out = getattr(backend_caps, "max_output_tokens", None)
            if max_ctx:
                return ModelContextProfile(
                    int(max_ctx),
                    int(max_out or cfg.max_output_tokens or 4096),
                    source="backend",
                )

        # Model overrides from config
        if cfg.model_overrides and model in cfg.model_overrides:
            max_ctx = int(cfg.model_overrides[model])
            max_out = int(cfg.max_output_tokens or 4096)
            return ModelContextProfile(max_ctx, max_out, source="config")

        # Global config overrides
        if cfg.max_context_tokens:
            max_ctx = int(cfg.max_context_tokens)
            max_out = int(cfg.max_output_tokens or 4096)
            return ModelContextProfile(max_ctx, max_out, source="config")

        # Default model lookup
        base = DEFAULT_MODEL_CONTEXTS.get(model, ModelContextProfile(16384, 2048, source="fallback"))

        if model not in DEFAULT_MODEL_CONTEXTS:
            provider_default = DEFAULT_PROVIDER_CONTEXTS.get(provider)
            if provider_default:
                base = ModelContextProfile(provider_default, base.max_output_tokens, source="provider_default")

        # Provider default override
        if cfg.provider_defaults and provider in cfg.provider_defaults:
            max_ctx = int(cfg.provider_defaults[provider])
            max_out = int(cfg.max_output_tokens or base.max_output_tokens)
            base = ModelContextProfile(max_ctx, max_out, source="provider_default")

        # There is no client-side VRAM cap at the end of this cascade any
        # more.  It used to be one: for ``provider == "local"``, probe the
        # GPUs of the machine *running this process* and cap the window by
        # their total VRAM.  That answered a question the client cannot
        # answer.  The local backend speaks HTTP to a serving endpoint, and
        # in a real deployment that endpoint is another box entirely — how
        # much VRAM the CLI host has says nothing about how long a context
        # the server accepts, and one GPU versus four is a serving-layer
        # decision (vLLM's ``--tensor-parallel-size``, TRT-LLM's TP config).
        # The server already answers the question honestly: the `backend`
        # branch at the top of this method reads `max_model_len` off
        # ``GET /models``.  When that probe fails, a declared default is a
        # stated guess; a cap derived from the wrong machine's device list
        # is a wrong number wearing a measurement's clothes — and it cost a
        # `torch` import at resolve time to produce.
        return base

    #: The name this cascade was resolved by before it had a second caller.
    _resolve_profile = resolve_profile

    def _compact(
        self, messages: List[Dict[str, str]], profile: ModelContextProfile
    ) -> Tuple[List[Dict[str, str]], ContextStats]:
        limit = profile.max_input_tokens
        total_tokens = _estimate_messages_tokens(messages)
        if total_tokens <= limit:
            return messages, ContextStats(total_tokens, limit, False, profile_source=profile.source)

        if len(messages) <= 2:
            return messages, ContextStats(total_tokens, limit, False, profile_source=profile.source)

        system = messages[0]
        tail = messages[1:][-self._config.min_tail_messages :]
        head = messages[1:-self._config.min_tail_messages]
        summary = _summarize_messages(head, self._config.max_summary_chars)

        compacted = [system, summary] + tail
        new_tokens = _estimate_messages_tokens(compacted)

        # Shrink summary until within limit or minimal
        while new_tokens > limit and len(summary["content"]) > 120:
            summary["content"] = summary["content"][: max(120, int(len(summary["content"]) * 0.8))] + "…"
            compacted = [system, summary] + tail
            new_tokens = _estimate_messages_tokens(compacted)

        stats = ContextStats(
            total_tokens=new_tokens,
            limit_tokens=limit,
            was_compacted=True,
            summary_tokens=_estimate_messages_tokens([summary]),
            removed_messages=len(head),
            profile_source=profile.source,
        )
        return compacted, stats


def _estimate_messages_tokens(messages: List[Dict[str, str]]) -> int:
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        total += estimate_tokens(content) + 4
    return total


def _summarize_messages(messages: List[Dict[str, str]], max_chars: int) -> Dict[str, str]:
    lines: List[str] = []
    for msg in messages:
        role = msg.get("role", "unknown")
        content = (msg.get("content") or "").strip().replace("\n", " ")
        snippet = content[:220]
        if len(content) > 220:
            snippet += "…"
        lines.append(f"{role}: {snippet}")

    body = "\n".join(lines)
    if len(body) > max_chars:
        body = body[: max_chars - 1] + "…"

    return {
        "role": "assistant",
        "content": (
            "Context summary (auto-compacted for context window):\n"
            f"{body}"
        ),
    }


# ── the mission's window ─────────────────────────────────────────────────────
#
# `ContextWindowManager` above answers the chat path's question: "here is a
# system prompt and a history, give me a list that fits."  The mission loop
# asks a different one.  Its message list is not a history it owns — it is a
# transcript the loop appends to, twice per step, for as many steps as the
# budget allows, and the pieces of it are not interchangeable: the catalogue
# tells the model which tools exist, the seeded turns are the conversation the
# analyst is continuing, the objective is the question, and the newest result
# is what the next reply is made of.  Summarising that list from the front
# would dissolve exactly the parts that must survive.
#
# So the mission gets its own *policy* and the same *arithmetic*: the profile
# cascade and the token estimate are `ContextWindowManager`'s, reached through
# `resolve_profile`, because two answers to "how big is the window" is the
# defect this module exists to prevent.

#: How many of the newest messages a mission compaction will never drop: the
#: model's last decision and the result it produced.  A window that can evict
#: the latest result has turned a context problem into a correctness one — the
#: model would be asked to continue from work it can no longer see, which is
#: the failure mode `MissionRunner._bound`'s marker exists to prevent one
#: level down.
MISSION_MIN_TAIL = 2

#: Every notice this module leaves in place of what it dropped begins with
#: this.  A second compaction recognises the first one's notice by it and
#: *replaces* it, rather than leaving the model a stack of notices about
#: notices — see :func:`default_compaction_note` and, in
#: :mod:`core.kernel.roles`, ``role_compaction_note``.
COMPACTION_MARK = "[context]"

#: The order eviction considers round trips in, lowest first.  This is the
#: whole of the drop policy, said once as data.
#:
#: * ``note`` — a notice an EARLIER compaction left.  It is about to be
#:   rewritten with this compaction's numbers, so keeping the stale one costs
#:   tokens to say something less true.
#: * ``orphan`` — a message no model turn of its own precedes: half a round
#:   trip, which reads to the model as an answer to a question it never asked.
#: * ``tool`` — a model decision and the tool output that answered it.  These
#:   go BEFORE conversation because the output is already in the mission's
#:   result store under a handle the model can still read, and because they
#:   are the bulk: one governed listing outweighs every user turn in the run.
#: * ``chat`` — a turn somebody actually said.  Cheap, and the thing
#:   coreference needs ("headline #2", "the second one"), so it is last.
EVICTION_ORDER = ("note", "orphan", "tool", "chat")


@dataclass(frozen=True)
class Compaction:
    """What one compaction removed, in the numbers a watcher can render.

    ``dropped_turns`` counts *model decisions* removed, which is what a
    person means by a turn; ``dropped_messages`` counts the dicts, which is
    what the arithmetic was done on.  Both, because they differ and a
    consumer told only one of them will assume the other.

    Per compaction, never a running total: each is emitted on the
    ``step_started`` it happened before, and a consumer that wants the run's
    total adds them up.
    """

    dropped_turns: int
    dropped_messages: int
    freed_chars: int
    tokens_before: int
    tokens_after: int
    limit_tokens: int
    profile_source: str
    #: How many of the dropped turns were TOOL round trips — a decision and
    #: the output that answered it.  Last and defaulted so that every
    #: existing construction of this class keeps working; on the record
    #: because "eleven turns went" and "eleven tool results went" are
    #: different sentences to a person reading a shortened mission, and
    #: because it is the number that says the policy did what it says it
    #: does.  Additive, so no ``SCHEMA_VERSION`` bump — see ``CONTRACT.md``.
    dropped_results: int = 0

    def as_record(self) -> Dict[str, Any]:
        """The mission stream's ``compacted`` field.  See ``CONTRACT.md``."""
        return {
            "dropped_turns": self.dropped_turns,
            "dropped_messages": self.dropped_messages,
            "freed_chars": self.freed_chars,
            "tokens_before": self.tokens_before,
            "tokens_after": self.tokens_after,
            "limit_tokens": self.limit_tokens,
            "profile": self.profile_source,
            "dropped_results": self.dropped_results,
        }


def default_compaction_note(dropped_turns: int, freed_chars: int,
                            dropped_results: int = 0) -> str:
    """What the model is told in place of the round trips that were dropped.

    Said out loud for the reason the truncation marker is: a silently
    shortened conversation is worse than a short one, because the model
    cannot see that anything is missing and re-runs a tool it already
    called — spending a step out of a budget of eight to rediscover
    something it was told and then had taken away.

    *dropped_results* is how many of those turns were tool round trips.
    Named separately because it is the actionable half: a tool result is
    still addressable in the mission's store, and a caller that knows the
    store's name says so on top of this — see
    :meth:`~core.runtime.mission.MissionRunner._compaction_note`.  A note
    callable given to :meth:`MissionWindow.fit` is called with all three
    arguments positionally.
    """
    kinds = (f", {dropped_results} of them tool result(s)"
             if dropped_results else "")
    return (
        f"{COMPACTION_MARK} Earlier steps of this mission were removed from "
        f"this conversation so that it fits the model's context window: "
        f"{dropped_turns} model turn(s), {freed_chars} characters{kinds}. "
        f"Those calls were made and their results have not changed — what "
        f"is gone is the paste of them, not the work. Do not repeat a call "
        f"merely because its output is no longer above."
    )


class MissionWindow:
    """Keeps a mission's message list inside the backend's real window.

    Parameters
    ----------
    provider, model:
        What the profile cascade keys off when the endpoint says nothing.
    client:
        Anything with a ``capabilities`` attribute — a
        :class:`~core.unified_client.UnifiedClient`, a backend, a test
        double.  Read **lazily**, at the first fit rather than at
        construction, because on the local backend reading it is a
        ``GET /models`` against a server that may still be loading weights,
        and building a runner must not be the thing that waits on it.  A
        lookup that raises is a window with no measurement, not a mission
        that failed to start: the cascade then falls back to the same
        declared defaults it uses when nobody passes a client at all.
    config:
        A :class:`ContextConfig`, for a caller stating the limit itself.
    manager:
        A :class:`ContextWindowManager` to share.  Supplied rather than
        built when a caller already has one.
    min_tail_messages:
        The newest messages that are never dropped; see
        :data:`MISSION_MIN_TAIL`.
    """

    def __init__(
        self,
        provider: str = "",
        model: str = "",
        *,
        client: Any = None,
        config: Optional[ContextConfig] = None,
        manager: Optional[ContextWindowManager] = None,
        min_tail_messages: int = MISSION_MIN_TAIL,
    ):
        self._manager = manager or ContextWindowManager(config=config)
        self._provider = provider or ""
        self._model = model or ""
        self._client = client
        self._min_tail = max(1, int(min_tail_messages))
        self._profile: Optional[ModelContextProfile] = None

    @property
    def profile(self) -> ModelContextProfile:
        """The resolved window, measured once and remembered."""
        if self._profile is None:
            caps = None
            if self._client is not None:
                try:
                    caps = getattr(self._client, "capabilities", None)
                except Exception:       # pragma: no cover - defensive
                    caps = None
            self._profile = self._manager.resolve_profile(
                self._provider, self._model, caps,
            )
        return self._profile

    @property
    def limit_tokens(self) -> int:
        """Input tokens this window allows, output reserve already taken out."""
        return self.profile.max_input_tokens

    def estimate(self, messages: Sequence[Dict[str, str]]) -> int:
        """This module's one token estimate, over a message list."""
        return _estimate_messages_tokens(list(messages))

    def fit(
        self,
        messages: Sequence[Dict[str, str]],
        *,
        pinned: int,
        note: Optional[Callable[[int, int], str]] = None,
    ) -> Tuple[List[Dict[str, str]], Optional[Compaction]]:
        """``(messages that fit, what was dropped)``; the second is ``None``
        when nothing had to be.

        *pinned* is how many messages at the FRONT are not compactable —
        for a mission, the system turn (persona, protocol, catalogue), the
        seeded ``--history`` turns, and the objective.  Dropping any of
        those produces an agent that has forgotten which tools exist or
        what it was asked, which is a worse failure than the one being
        fixed.

        Everything after them is grouped into whole round trips — see
        :func:`round_trips` — and evicted in :data:`EVICTION_ORDER`:
        a stale notice, then a stranded half round trip, then TOOL round
        trips oldest-first, and only then the oldest turns somebody
        actually said.  Dropping stops as soon as the list fits, and the
        newest round trip is never dropped whatever the numbers say.  A
        *note* goes where they were, so the model is told rather than
        quietly given a shorter conversation.

        **Tool output goes before conversation, and that is the policy.**
        Both are "the oldest thing here", so a stride that took whichever
        came first took a user's question — the cheapest message in the
        list and the one coreference needs — as readily as a 33,000
        character listing that is still sitting in the result store under
        a handle the model can read.  One of those is recoverable and one
        is not.

        A list that cannot be made to fit — a pinned prefix larger than
        the window — is returned as short as this can make it, with the
        record saying so in ``tokens_after``.  Refusing to send it would
        turn a degraded mission into no mission, and the numbers are on
        the stream either way.
        """
        kept = list(messages)
        limit = self.limit_tokens
        if limit <= 0:
            return kept, None

        pinned = max(0, min(int(pinned), len(kept)))
        head, tail = kept[:pinned], kept[pinned:]
        note_fn = note or default_compaction_note
        dropped: List[Dict[str, str]] = []
        results = 0

        def assembled() -> List[Dict[str, str]]:
            if not dropped:
                return head + tail
            return head + [{"role": "user", "content": note_fn(
                _turns(dropped), _chars(dropped), results)}] + tail

        total = _estimate_messages_tokens(assembled())
        before = total
        if total <= limit:
            return kept, None

        groups = round_trips(tail)
        alive = list(range(len(groups)))
        # The newest round trip is not in the running at all: see
        # `MISSION_MIN_TAIL`. Held by index rather than by identity so that
        # two byte-identical round trips cannot be confused for each other.
        newest = len(groups) - 1
        order = sorted(
            range(len(groups)),
            key=lambda i: (EVICTION_ORDER.index(round_trip_kind(groups[i])), i),
        )

        def evict(index: int) -> None:
            nonlocal tail, total, results
            alive.remove(index)
            dropped.extend(groups[index])
            if round_trip_kind(groups[index]) == "tool":
                results += 1
            tail = [message for i in alive for message in groups[i]]
            total = _estimate_messages_tokens(assembled())

        for index in order:
            if total <= limit:
                break
            if index == newest:
                continue
            if len(tail) - len(groups[index]) < self._min_tail:
                continue
            evict(index)

        # A tail that starts with anything but the model's own turn starts
        # with a result whose call was dropped — a half round trip, which
        # reads to the model as an answer to a question it never asked.
        # Structurally impossible after the loop above, which evicts those
        # first; kept as the invariant rather than as an assumption about
        # the loop's ordering.
        while (alive and alive[0] != newest
               and round_trip_kind(groups[alive[0]]) in ("note", "orphan")
               and len(tail) - len(groups[alive[0]]) >= self._min_tail):
            evict(alive[0])

        if not dropped:
            return kept, None

        return assembled(), Compaction(
            dropped_turns=_turns(dropped),
            dropped_messages=len(dropped),
            freed_chars=_chars(dropped),
            tokens_before=before,
            tokens_after=total,
            limit_tokens=limit,
            profile_source=self.profile.source,
            dropped_results=results,
        )


def round_trips(
    messages: Sequence[Dict[str, Any]],
) -> List[List[Dict[str, Any]]]:
    """*messages* grouped into round trips, oldest first, nothing lost.

    A round trip is **one model turn plus the messages that answer it**,
    and there are two shapes of answer because there are two protocols:

    * the JSON protocol the mission loop reads — one ``user`` message
      carrying the rendered tool result, or the harness's refusal of the
      reply;
    * the native tool-call protocol — an ``assistant`` turn carrying
      ``tool_calls`` followed by **N** ``{"role": "tool"}`` messages, one
      per call it made in that single turn.

    So the unit is not a fixed number of messages, and that is the whole
    reason this exists: a stride of two split a parallel native round trip
    down the middle and left the model tool output for a call it could no
    longer see it had made.

    Anything the walk cannot attach to a model turn — a stale notice, a
    result whose call an earlier compaction already took — becomes a group
    of its own rather than being appended to somebody else's, so that
    :meth:`MissionWindow.fit` can drop it *first* instead of stranding it.
    """
    groups: List[List[Dict[str, Any]]] = []
    index, total = 0, len(messages)
    while index < total:
        group = [messages[index]]
        index += 1
        if group[0].get("role") == "assistant":
            while index < total and messages[index].get("role") == "tool":
                group.append(messages[index])
                index += 1
            # One `user` answer, and only when no tool message already
            # answered: the two protocols do not mix inside one turn, and
            # a `user` message after a native round trip is a new turn.
            if (len(group) == 1 and index < total
                    and messages[index].get("role") == "user"):
                group.append(messages[index])
                index += 1
        groups.append(group)
    return groups


def round_trip_kind(group: Sequence[Dict[str, Any]]) -> str:
    """Which bucket of :data:`EVICTION_ORDER` one round trip is in.

    A round trip counts as ``tool`` on any of the three signals a tool
    call leaves, because a mission may be running either protocol and a
    reply may be wrapped in prose the harness later refused:

    * a ``{"role": "tool"}`` message answered it (native);
    * the model turn carries ``tool_calls`` (native, before the answers
      arrive);
    * the model turn's text names a ``"tool"`` (the JSON protocol —
      substring rather than a parse, so a fenced or prose-wrapped reply
      is still recognised for what it was).

    Ordering, not correctness: the worst a misread does is drop a chat
    turn one place earlier than it deserved.
    """
    lead = group[0] if group else {}
    if lead.get("role") != "assistant":
        content = str(lead.get("content") or "")
        return "note" if content.startswith(COMPACTION_MARK) else "orphan"
    if any(message.get("role") == "tool" for message in group[1:]):
        return "tool"
    if lead.get("tool_calls"):
        return "tool"
    return "tool" if '"tool"' in str(lead.get("content") or "") else "chat"


def _turns(messages: Sequence[Dict[str, str]]) -> int:
    """Model decisions among *messages* — what a person means by a turn."""
    return sum(1 for m in messages if m.get("role") == "assistant")


def _chars(messages: Sequence[Dict[str, str]]) -> int:
    return sum(len(str(m.get("content") or "")) for m in messages)
