import os
from typing import List, Dict, Any, Optional

from core.runtime.backends.openai_backend import OpenAIBackend
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
