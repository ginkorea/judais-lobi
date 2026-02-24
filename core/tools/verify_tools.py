# core/tools/verify_tools.py — Config-driven verification tool

from typing import Optional, Tuple

from core.tools.executor import run_subprocess


class VerifyTool:
    """Config-driven verification. Reads command overrides from config dict.

    Config format (from .judais-lobi.yml):
        verification:
          lint: "ruff check ."
          test: "pytest"
          typecheck: "mypy ."
          format: "ruff format --check ."

    Each action returns (exit_code, stdout, stderr).
    """

    DEFAULTS = {
        "lint": "ruff check .",
        "test": "pytest",
        "typecheck": "mypy .",
        "format": "ruff format --check .",
    }

    def __init__(self, config: Optional[dict] = None,
                 subprocess_runner=None):
        self._config = config or {}
        self._subprocess_runner = subprocess_runner

    def __call__(self, action: str, **kwargs) -> Tuple[int, str, str]:
        cmd = self._resolve_command(action)
        if cmd is None:
            return (1, "", f"Unknown verify action: {action}")
        try:
            return run_subprocess(
                cmd, shell=True, timeout=300,
                subprocess_runner=self._subprocess_runner,
            )
        except Exception as exc:
            return (1, "", f"{type(exc).__name__}: {exc}")

    def _resolve_command(self, action: str) -> Optional[str]:
        """Resolve command: config override > default."""
        verification = self._config.get("verification", {})
        if isinstance(verification, dict) and action in verification:
            return verification[action]
        return self.DEFAULTS.get(action)
