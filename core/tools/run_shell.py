# tools/run_shell.py

from __future__ import annotations

import re
import shutil
from typing import Tuple, Optional, Any

from core.tools.base_subprocess import RunSubprocessTool


class RunShellTool(RunSubprocessTool):
    name = "run_shell_command"
    description = "Runs a shell command with robust retries, optional pkg recovery, sudo fallback, and progress logs."

    def __init__(self, **kwargs):
        kwargs.setdefault("executable", "/bin/bash")
        super().__init__(**kwargs)
        self.name = "run_shell_command"

    # Public interface stays the same
    def __call__(self, command, timeout=None, return_success=False, max_retries: int = 3, unsafe: bool = True):
        # Allow per-call override of timeout/flags while preserving defaults
        if timeout is not None:
            self.timeout = timeout
        return self._run_with_retries(
            command, max_retries=max_retries, unsafe=unsafe, return_success=return_success
        )

    # ---------- Template overrides ----------
    def _attempt(self, payload: Any) -> Tuple[int, str, str]:
        # payload is a command (str or list); just run it with base runner
        return self.run(payload)

    def _sudo_attempt(self, payload: Any) -> Tuple[int, str, str]:
        sudo_payload = self._prepend_sudo(payload)
        return self.run(sudo_payload)

    def _detect_missing_dependency(self, err: str) -> Optional[str]:
        if not err:
            return None

        # Common bash error shapes
        #   - bash: foo: command not found
        #   - /bin/sh: 1: foo: not found
        #   - foo: command not found
        m = re.search(r":\s*([A-Za-z0-9._+-]+):\s*command not found", err)
        if m:
            return m.group(1)

        # Some shells print: "foo: not found"
        m = re.search(r"^\s*([A-Za-z0-9._+-]+):\s*not found\s*$", err, re.MULTILINE)
        if m:
            return m.group(1)

        return None

    def _install_dependency(self, name: str) -> bool:
        """
        Heuristic: try to install a package with the same name via detected package manager.
        We print progress and best-effort fallback; if no package manager is found, return False.
        """
        pkg_mgr = self._detect_package_manager()
        if not pkg_mgr:
            self._log("⚠️ Could not detect package manager. Skipping auto-install.")
            return False

        self._log(f"🧰 Using package manager: {pkg_mgr}")
        if pkg_mgr == "apt":
            cmd = ["sudo", "apt", "update", "-y"]
            self._log("🔄 apt update…")
            self.run(cmd)
            install_cmd = ["sudo", "apt", "install", "-y", name]
        elif pkg_mgr == "dnf":
            install_cmd = ["sudo", "dnf", "install", "-y", name]
        elif pkg_mgr == "pacman":
            install_cmd = ["sudo", "pacman", "-S", "--noconfirm", name]
        else:
            return False

        self._log(f"📦 Installing: {name}")
        rc, out, err = self.run(install_cmd)
        if rc == 0:
            return True
        self._log(f"❌ Package install failed: {err or out}")
        return False

    def _repair(self, payload, err: str):
        # For now, we won’t attempt to “repair” arbitrary shell commands automatically.
        # You could enhance this with an LLM-backed fixer later (mirroring Python).
        return payload

    def _describe(self, payload) -> str:
        if isinstance(payload, list):
            return " ".join(payload)
        return str(payload)

    # ---------- Helpers ----------
    @staticmethod
    def _detect_package_manager() -> Optional[str]:
        if shutil.which("apt"):
            return "apt"
        if shutil.which("dnf"):
            return "dnf"
        if shutil.which("pacman"):
            return "pacman"
        return None
