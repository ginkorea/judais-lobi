# core/tools/run_python.py
# Phase 4: Stripped to dumb executor. No retries, no LLM repair, no pip install.

from __future__ import annotations

import os
import tempfile
import re
from pathlib import Path
from typing import Tuple, Optional

from core.tools.base_subprocess import RunSubprocessTool


class RunPythonTool(RunSubprocessTool):
    name = "run_python_code"
    description = "Runs Python code in elfenv. Returns (exit_code, stdout, stderr)."

    def __init__(self, **kwargs):
        self.elfenv = kwargs.get("elfenv", Path(".elfenv"))
        self.python_bin = self.elfenv / "bin" / "python"
        self.pip_bin = self.elfenv / "bin" / "pip"
        if not kwargs.get("skip_venv_setup", False):
            self._ensure_elfenv()
        super().__init__(**kwargs)
        self.name = "run_python_code"
        self._last_temp_path: Optional[str] = None

    def __call__(self, code: str, timeout=None, **kwargs) -> Tuple[int, str, str]:
        """Write code to a temp file and run with elfenv python."""
        with tempfile.NamedTemporaryFile(delete=False, mode="w", suffix=".py") as f:
            f.write(str(code))
            self._last_temp_path = f.name

        try:
            rc, out, err = self.run(
                [str(self.python_bin), self._last_temp_path],
                timeout=timeout or self.timeout,
            )
            return rc, out, err
        finally:
            self._cleanup_temp()

    def _detect_missing_dependency(self, err: str) -> Optional[str]:
        """Kept — kernel uses this to decide if a pip install tool call is needed."""
        m = re.search(r"No module named ['\"]([^'\"]+)['\"]", err or "")
        return m.group(1) if m else None

    def _ensure_elfenv(self):
        from venv import create
        if not self.python_bin.exists():
            create(str(self.elfenv), with_pip=True)

    def _cleanup_temp(self):
        if self._last_temp_path and os.path.exists(self._last_temp_path):
            try:
                os.remove(self._last_temp_path)
            except Exception:
                pass
        self._last_temp_path = None
