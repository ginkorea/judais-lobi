# core/runtime/provider_config.py — Provider defaults and resolution

import os
from typing import Callable, Optional

DEFAULT_MODELS = {
    "openai": "gpt-4o-mini",
    # The current Opus, undated (a dated snapshot pinned here goes stale
    # silently); owner's decision, 16 Aug 2026. Same string as
    # `core.runtime.backends.anthropic_backend.DEFAULT_ANTHROPIC_MODEL`.
    "anthropic": "claude-opus-5",
    "mistral": "codestral-latest",
    # The served name of a local endpoint is whatever it was started with, so
    # this is only the LAST resort: --model, then LOCAL_MODEL, then
    # GET /models, then this — and a personality's `default_model` is NOT in
    # that order at all. `LocalBackend.model` applies the middle of it;
    # `resolve_model` below is where a personality is left out of it.
    "local": "local-model",
}

#: Providers whose served model name belongs to the **endpoint** and can
#: only be learned by asking it.  See :func:`resolve_model`: for these, when
#: nobody has named a model *for this provider*, the endpoint is asked
#: rather than a declared default assumed.
ENDPOINT_OWNS_MODEL = ("local",)

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


def resolve_model(
    provider: str,
    requested: Optional[str] = None,
    personality_default: Optional[str] = None,
    personality_provider: Optional[str] = None,
    served: Optional[Callable[[], Optional[str]]] = None,
) -> str:
    """Which model name to send, and who is asked in what order.

    ``--model`` always wins; it is somebody naming one.  Then:

    1. **The personality's ``default_model`` — but only for the provider it
       was chosen for.**  A model name is a name in *one* provider's
       catalogue.  A persona that says ``default_provider = "local"`` and
       ``default_model = "gpt-oss-20b"`` has named the model its endpoint
       serves, and that is the documented way a deployment states one (see
       ``PLATFORMS.md`` §"the persona file").  The same field on a persona
       whose provider is a different one says nothing about the provider
       actually in force — and sending it anyway is how a run reaches an
       endpoint that has never heard of the name and answers 404.  So the
       default is consulted when the personality named **this** provider,
       or named none at all; never when it named another.
    2. **What the endpoint itself serves**, for a provider in
       :data:`ENDPOINT_OWNS_MODEL`: it serves whatever it was started with,
       under whatever name it was started with, and only it can say.  Asked
       through *served*.
    3. :data:`DEFAULT_MODELS`, the declared last resort.

    *served* is the backend's own ``model`` property, which owns the middle
    of the local order —
    :attr:`core.runtime.backends.local_backend.LocalBackend.model` reads
    ``LOCAL_MODEL``, then ``GET /models``, then falls back.  A callable so
    that the probe happens only in the case nothing else can answer, and
    read defensively: an endpoint that is down is a fact about the endpoint
    and not a reason to fail before the first request.

    Measured, 18 Aug 2026 (``EVAL.md`` §12): every ``--provider local`` run
    with no ``--model`` sent the personality's own default — a *hosted*
    provider's model name, from a persona nobody had pointed at the local
    endpoint — and got a 404 back naming it.
    """
    name = (requested or "").strip()
    if name:
        return name
    provider = (provider or "").strip().lower()
    chosen_for = (personality_provider or "").strip().lower()
    if not chosen_for or chosen_for == provider:
        name = (personality_default or "").strip()
        if name:
            return name
    if provider in ENDPOINT_OWNS_MODEL and served is not None:
        try:
            name = (served() or "").strip()
        except Exception:                   # pragma: no cover - defensive
            name = ""
        if name:
            return name
    return DEFAULT_MODELS.get(provider, DEFAULT_MODELS["openai"])


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
