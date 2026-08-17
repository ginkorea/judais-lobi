# core/critic/__init__.py — External Critic subsystem

from core.critic.models import (
    CriticVerdict,
    CriticRisk,
    ExternalCriticReport,
    AggregatedCriticReport,
    CritiquePack,
)
from core.critic.config import CriticConfig, CriticProviderConfig, load_critic_config
from core.critic.backends import CriticBackend
from core.critic.triggers import (
    MissionCriticContext,
    MissionTriggerConfig,
    should_invoke_mission_critic,
)


def __getattr__(name):
    if name == "CriticOrchestrator":
        from core.critic.orchestrator import CriticOrchestrator
        return CriticOrchestrator
    if name == "Redactor":
        from core.critic.redactor import Redactor
        return Redactor
    if name == "CriticKeystore":
        from core.critic.keystore import CriticKeystore
        return CriticKeystore
    if name == "CriticCache":
        from core.critic.cache import CriticCache
        return CriticCache
    if name in ("MissionCritic", "CriticOpinion"):
        # Deferred like the orchestrator: importing it pulls in the local
        # backend's transport, and `import core.critic` must stay cheap for
        # a caller that only wants the trigger rules.
        from core.critic import mission

        return getattr(mission, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "CriticVerdict",
    "CriticRisk",
    "ExternalCriticReport",
    "AggregatedCriticReport",
    "CritiquePack",
    "CriticConfig",
    "CriticProviderConfig",
    "load_critic_config",
    "CriticBackend",
    "CriticOrchestrator",
    "Redactor",
    "CriticKeystore",
    "CriticCache",
    "MissionCritic",
    "CriticOpinion",
    "MissionCriticContext",
    "MissionTriggerConfig",
    "should_invoke_mission_critic",
]
