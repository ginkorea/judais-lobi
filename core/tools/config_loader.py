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
