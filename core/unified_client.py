import os
from typing import List, Dict, Any, Optional

from core.runtime.backends.openai_backend import OpenAIBackend
from core.runtime.backends.anthropic_backend import AnthropicBackend
from core.runtime.backends.mistral_backend import MistralBackend
from core.runtime.backends.local_backend import LocalBackend


class UnifiedClient:
    """
    Unified client — thin router that delegates to backend implementations.
    """

    def __init__(self, provider_override: Optional[str] = None, openai_client=None,
                 backend=None):
        self.provider = (provider_override or os.getenv("ELF_PROVIDER") or "openai").lower()

        if backend is not None:
            self._backend = backend
        elif self.provider == "openai":
            self._backend = OpenAIBackend(openai_client=openai_client)
        elif self.provider == "anthropic":
            # Key and SDK are the backend's to check, and it refuses by
            # name: a deployment that asked for Anthropic and got a
            # different provider's answer would be the opposite of what
            # it asked for.
            self._backend = AnthropicBackend()
        elif self.provider == "mistral":
            self._backend = MistralBackend()
        elif self.provider == "local":
            # Config lives in LOCAL_API_BASE / LOCAL_MODEL and is read by the
            # backend itself.  Nothing is contacted here: constructing a client
            # must not require the server to already be up.
            self._backend = LocalBackend()
        else:
            raise ValueError(f"Unsupported provider: {self.provider}")

    def chat(self, model: str, messages: List[Dict[str, Any]], stream: bool = False,
             **kwargs: Any):
        return self._backend.chat(model, messages, stream, **kwargs)

    @property
    def capabilities(self):
        return self._backend.capabilities

    @property
    def default_model(self) -> str:
        """The model this backend sends when the caller names none, or ``""``.

        The third side channel, and the one with a cost: on the local
        backend reading it is ``LOCAL_MODEL`` or a ``GET /models`` against
        the server, so nothing asks unless nothing else can answer — see
        :func:`core.runtime.provider_config.resolve_model`, its only
        caller.

        ``getattr`` with a default for the reason :attr:`last_usage` uses
        one: a caller may inject any object as ``backend=``, and a backend
        with no opinion about model names must say so rather than raise.
        """
        return str(getattr(self._backend, "model", "") or "")

    @property
    def last_usage(self):
        """What the provider said the last completion cost, or ``None``.

        A side channel rather than a return value: :meth:`chat` returns a
        ``str`` or an iterator and every caller in this tree branches on
        exactly those two, so a third shape would be a breaking change to
        every one of them for the sake of a number most of them ignore.

        ``getattr`` with a default because a caller may inject any object
        as ``backend=`` — a stub in a test, a platform's own adapter —
        and a backend that never heard of usage must report nothing
        rather than raise. Nothing reported is ``None``, never zero: see
        :class:`core.runtime.backends.base.Usage`.
        """
        return getattr(self._backend, "last_usage", None)

    @property
    def last_tool_calls(self) -> List[Dict[str, Any]]:
        """The native tool calls the last completion carried, as plain dicts.

        ``[{"id": …, "name": …, "arguments": {…}}]``, every call the
        provider returned and in its order — the second side channel
        beside :attr:`last_usage`, mirrored here for the same reason and
        read the same way. See
        :attr:`core.runtime.backends.base.Backend.last_tool_calls`.

        Empty rather than absent when there were none, and empty rather
        than an ``AttributeError`` when the injected backend never heard
        of tool calls: a caller loops over this, and "no calls" and "a
        backend that cannot make calls" are the same instruction to that
        loop. Whether a backend *can* is a capability question, and
        ``capabilities`` is where it is asked.
        """
        calls = getattr(self._backend, "last_tool_calls", None)
        return calls if isinstance(calls, list) else []
