# core/tools/base_subprocess.py
# Phase 4: Stripped of retry loops, sudo fallback, and repair agency.
# Tools are now dumb executors — retries/repair move to kernel FIX phase,
# sudo moves to capability engine.

from __future__ import annotations

from abc import ABC
import subprocess
import os
from typing import Any, Tuple, Optional

from core.tools.tool import Tool
from core.tools.executor import run_subprocess


class RunSubprocessTool(Tool, ABC):
    """Base class for tools that execute subprocess-like operations.

    After Phase 4 stripping:
    - run() delegates to executor.run_subprocess()
    - No retry loop, no sudo fallback, no code repair
    - Subclasses implement __call__() returning (rc, out, err)
    - Static utilities kept: extract_code(), is_root(), _is_permission_error()
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.name = "run_subprocess"
        self.description = "Runs a subprocess command and returns (exit_code, stdout, stderr)."
        self.timeout = kwargs.get("timeout", 120)
        self.executable = kwargs.get("executable", "/bin/bash")
        self.subprocess_runner = kwargs.get("subprocess_runner", None)

    def run(self, cmd, timeout: Optional[int] = None) -> Tuple[int, str, str]:
        """Execute a command as a subprocess.

        Returns: (return_code, stdout, stderr).
        Delegates to executor.run_subprocess().
        """
        timeout = timeout or self.timeout
        shell_mode = isinstance(cmd, str)
        return run_subprocess(
            cmd,
            shell=shell_mode,
            timeout=timeout,
            executable=self.executable if shell_mode else None,
            subprocess_runner=self.subprocess_runner,
        )

    # --- Static utilities (kept for kernel and other consumers) ---

    @staticmethod
    def is_root() -> bool:
        try:
            return os.geteuid() == 0
        except AttributeError:
            return os.name == "nt" and "ADMIN" in os.environ.get("USERNAME", "").upper()

    @staticmethod
    def _is_permission_error(err: str) -> bool:
        if not err:
            return False
        low = err.lower()
        return any(
            term in low for term in [
                "permission denied", "must be run as root", "operation not permitted",
            ]
        )

    @staticmethod
    def extract_code(text: str, language: str | None = None) -> str:
        """Extract code blocks from markdown-like text."""
        import re

        if language:
            match = re.search(rf"```{language}\n(.*?)```", text, re.DOTALL)
            if match:
                return match.group(1).strip()

        match = re.search(r"```(.+?)```", text, re.DOTALL)
        if match:
            return match.group(1).strip()

        match = re.search(r"`([^`]+)`", text)
        if match:
            return match.group(1).strip()

        return text.strip()

    @staticmethod
    def _format_exception(ex: Exception) -> str:
        return f"Unexpected error: {type(ex).__name__}: {str(ex)}"

    # --- Template methods (default no-ops, kept for kernel utility) ---

    def _detect_missing_dependency(self, err: str) -> Optional[str]:
        """Return the missing dependency/package name if detectable, else None."""
        return None
