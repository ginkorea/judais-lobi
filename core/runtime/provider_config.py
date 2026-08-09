# core/runtime/provider_config.py — Provider defaults and resolution

import os
from typing import Optional

DEFAULT_MODELS = {
    "openai": "gpt-4o-mini",
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
    "mistral": "MISTRAL_API_KEY",
}


def resolve_provider(
    requested: Optional[str] = None,
    has_injected_client: bool = False,
) -> str:
    """Resolve provider: explicit arg > ELF_PROVIDER env > default 'openai'.

    When no client is injected, falls back between the two hosted
    providers if the requested one's API key is missing.  ``local`` is
    never fallen back *from*: asking for the endpoint on this host and
    being silently answered by OpenAI is the opposite of what was asked,
    and for a mission prompt it would send the prompt off the host.
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
