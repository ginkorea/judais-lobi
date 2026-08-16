# core/tools/config_loader.py — Project config loader

from pathlib import Path
from typing import Optional


def load_project_config(project_root: Optional[Path] = None) -> dict:
    """Load .judais-lobi.yml from project root.

    Returns {} if file not found or yaml library not available.
    Searches for .judais-lobi.yml and .judais-lobi.yaml.
    """
    root = Path(project_root) if project_root else Path.cwd()
    for name in (".judais-lobi.yml", ".judais-lobi.yaml"):
        config_path = root / name
        if config_path.exists():
            try:
                import yaml
                return yaml.safe_load(config_path.read_text()) or {}
            except ImportError:
                return {}
            except Exception:
                return {}
    return {}


def load_pricing(project_root: Optional[Path] = None) -> dict:
    """The ``pricing:`` block of the project config, or ``{}``.

    ``{provider: {model: {prompt_per_1k, completion_per_1k, currency}}}``.
    It is what turns a run's token ledger into a cost on
    ``mission_finished``; without it the ledger carries tokens and no
    ``cost`` key at all.

    Deliberately read from configuration and never shipped: prices move,
    they differ per account, and a framework carrying a price list would
    be quoting a figure it cannot know. A block that is not a mapping —
    a stray string, a list — is ``{}`` here rather than an error, for the
    same reason the loader above swallows a malformed file: cost is
    optional decoration on an agent framework and a typo in it must not
    cost anybody a mission.

    See :class:`core.runtime.usage.PricingTable`, which is what reads the
    shape of the entries; this function only finds the block.
    """
    block = load_project_config(project_root).get("pricing")
    return block if isinstance(block, dict) else {}
