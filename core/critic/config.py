# core/critic/config.py — Critic config models + loader

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class CriticProviderConfig(BaseModel):
    provider: str  # "openai", "anthropic", "google"
    model: str = ""
    api_key_env_var: str = ""
    keyring_service: str = "judais-lobi"
    keyring_key: str = ""
    max_tokens_per_call: int = 4096
    timeout_seconds: float = 60.0
    enabled: bool = True


class CriticConfig(BaseModel):
    enabled: bool = False
    providers: List[CriticProviderConfig] = []
    max_calls_per_session: int = 10
    max_rounds_per_invocation: int = 3
    max_tokens_per_call: int = 4096
    redaction_level: str = "strict"  # "strict" or "normal"
    max_payload_bytes: int = 65_536
    # Triggers
    trigger_after_plan: bool = True
    trigger_after_run_pass: bool = True
    trigger_on_fix_loop_threshold: int = 3
    trigger_on_security_surface: bool = True
    trigger_on_dependency_change: bool = True
    trigger_on_large_refactor_files: int = 5
    trigger_on_large_refactor_lines: int = 500
    # Noise detection
    noise_confidence_threshold: float = 0.3
    noise_overlap_ratio: float = 0.8
    # Cache
    cache_enabled: bool = True
    cache_dir: str = ""


DEFAULT_PROVIDERS = [
    CriticProviderConfig(
        provider="openai",
        model="gpt-4o",
        api_key_env_var="OPENAI_API_KEY",
        keyring_key="openai_api_key",
    ),
    CriticProviderConfig(
        provider="anthropic",
        model="claude-sonnet-4-20250514",
        api_key_env_var="ANTHROPIC_API_KEY",
        keyring_key="anthropic_api_key",
    ),
    CriticProviderConfig(
        provider="google",
        model="gemini-2.0-flash",
        api_key_env_var="GOOGLE_API_KEY",
        keyring_key="google_api_key",
    ),
]


def load_critic_config(
    project_root: Optional[Path] = None,
    user_home: Optional[Path] = None,
    cli_overrides: Optional[dict] = None,
) -> CriticConfig:
    """Load critic config with precedence: user -> project -> CLI.

    Layer 1: ~/.judais-lobi/critic.yml
    Layer 2: .judais-lobi.yml (critic: section)
    Layer 3: CLI overrides dict
    """
    root = Path(project_root) if project_root else Path.cwd()
    home = Path(user_home) if user_home else Path.home()

    data: Dict[str, Any] = {}

    user_cfg = _load_yaml(home / ".judais-lobi" / "critic.yml")
    data = _merge_dicts(data, user_cfg)

    project_cfg = _load_project_yaml(root)
    critic_section = {}
    if isinstance(project_cfg, dict):
        critic_section = project_cfg.get("critic", {}) or {}
    data = _merge_dicts(data, critic_section)

    if cli_overrides:
        data = _merge_dicts(data, cli_overrides)

    config = CriticConfig.model_validate(data)

    if config.enabled and not config.providers:
        config.providers = [p.model_copy() for p in DEFAULT_PROVIDERS]

    if not config.cache_dir:
        config.cache_dir = str(root / ".judais-lobi" / "cache" / "critic")

    return config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        import yaml
        return yaml.safe_load(path.read_text()) or {}
    except ImportError:
        return {}
    except Exception:
        return {}


def _load_project_yaml(root: Path) -> dict:
    for name in (".judais-lobi.yml", ".judais-lobi.yaml"):
        path = root / name
        if path.exists():
            return _load_yaml(path)
    return {}


def _merge_dicts(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(override, dict):
        return dict(base)
    merged = dict(base)
    for key, value in override.items():
        if (
            key in merged
            and isinstance(merged[key], dict)
            and isinstance(value, dict)
        ):
            merged[key] = _merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged
