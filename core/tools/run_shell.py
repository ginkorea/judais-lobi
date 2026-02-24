# core/tools/run_shell.py
# Phase 4: Stripped to dumb executor. No retries, no sudo, no pkg install.

from __future__ import annotations

import re
from typing import Tuple, Optional

from core.tools.base_subprocess import RunSubprocessTool


class RunShellTool(RunSubprocessTool):
    name = "run_shell_command"
    description = "Runs a shell command. Returns (exit_code, stdout, stderr)."

    def __init__(self, **kwargs):
        kwargs.setdefault("executable", "/bin/bash")
        super().__init__(**kwargs)
        self.name = "run_shell_command"

    def __call__(self, command, timeout=None, **kwargs) -> Tuple[int, str, str]:
        return self.run(command, timeout=timeout or self.timeout)

    def _detect_missing_dependency(self, err: str) -> Optional[str]:
        """Kept — kernel uses this to decide if a dependency install tool call is needed."""
        if not err:
            return None
        m = re.search(r":\s*([A-Za-z0-9._+-]+):\s*command not found", err)
        if m:
            return m.group(1)
        m = re.search(r"^\s*([A-Za-z0-9._+-]+):\s*not found\s*$", err, re.MULTILINE)
        if m:
            return m.group(1)
        return None
