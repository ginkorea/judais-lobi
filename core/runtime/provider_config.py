# core/runtime/provider_config.py — Provider defaults and resolution

import os
from typing import Optional

DEFAULT_MODELS = {
    "openai": "gpt-4o-mini",
    # The current Opus, undated (a dated snapshot pinned here goes stale
    # silently); owner's decision, 16 Aug 2026. Same string as
    # `core.runtime.backends.anthropic_backend.DEFAULT_ANTHROPIC_MODEL`.
    "anthropic": "claude-opus-5",
    "mistral": "codestral-latest",
    # The served name of a local endpoint is whatever it was started with, so
    # this is only the last resort: LOCAL_MODEL, then GET /models, then this.
    # LocalBackend.model applies that order.
    "local": "local-model",
}

#: Every provider UnifiedClient can build.  The CLI generates its --provider
#: choices from this, so a backend cannot be reachable from one and not the
#: other.
PROVIDERS = tuple(DEFAULT_MODELS)

#: Providers that authenticate with a hosted API key.  'local' is deliberately
#: absent: it talks to a port on this host that usually wants no credential,
#: so a missing key is not evidence that a local server is down and must not
#: trigger a fallback.
API_KEY_ENV = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "mistral": "MISTRAL_API_KEY",
}


def resolve_provider(
    requested: Optional[str] = None,
    has_injected_client: bool = False,
) -> str:
    """Resolve provider: explicit arg > ELF_PROVIDER env > default 'openai'.

    When no client is injected, falls back between OpenAI and Mistral if
    the requested one's API key is missing — the pair this function has
    always swapped between, and the swap survives because ``openai`` is
    the default nobody chose and a missing key there is a fresh install
    rather than an instruction.

    ``local`` and ``anthropic`` are never fallen back *from*, for the same
    reason in two shapes: both are somebody naming a provider on purpose.
    Asking for the endpoint on this host and being silently answered by
    OpenAI is the opposite of what was asked, and for a mission prompt it
    would send the prompt off the host; asking for Anthropic and being
    answered by OpenAI is a different model, a different bill and a
    different set of capability flags. A missing ``ANTHROPIC_API_KEY``
    stops the run by name — see
    :class:`core.runtime.backends.anthropic_backend.AnthropicBackend`.
    """
    from rich import print  # local to avoid hard dep when not needed

    prov = (requested or os.getenv("ELF_PROVIDER") or "openai").strip().lower()

    if not has_injected_client:
        openai_key = (os.getenv("OPENAI_API_KEY") or "").strip()
        mistral_key = (os.getenv("MISTRAL_API_KEY") or "").strip()

        if prov == "openai" and not openai_key:
            print("[yellow]Warning: No OpenAI key found - falling back to Mistral.[/yellow]")
            prov = "mistral"
        elif prov == "mistral" and not mistral_key:
            print("[yellow]Warning: No Mistral key found - falling back to OpenAI.[/yellow]")
            prov = "openai"

    return prov
