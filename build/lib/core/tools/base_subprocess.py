# core/tools/base_subprocess.py

from __future__ import annotations

from abc import ABC, abstractmethod
import subprocess
import os
import shlex
from typing import Any, Tuple, Optional

from core.tools.tool import Tool


class RunSubprocessTool(Tool, ABC):
    """
    Base class for tools that execute subprocess-like operations with robust retries.
    - Centralizes attempt/retry loop, sudo fallback, timeouts, progress logging.
    - Defers language/tool-specific pieces (dependency detection/installation, repair)
      to subclasses via template methods.

    Subclasses implement:
      - _attempt(payload) -> (rc, out, err)
      - _sudo_attempt(payload) -> (rc, out, err)  (optional: default wraps _attempt)
      - _detect_missing_dependency(err) -> dep_name|None
      - _install_dependency(dep_name) -> bool
      - _repair(payload, err) -> new_payload
      - _describe(payload) -> str   (for friendly progress logs)
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.name = "run_subprocess"
        self.description = (
            "Runs a subprocess command and returns its output. Handles retries, sudo, timeouts, and errors."
        )
        self.unsafe = kwargs.get("unsafe", True)
        self.return_success = kwargs.get("return_success", False)
        self.timeout = kwargs.get("timeout", 120)
        self.check_root = kwargs.get("check_root", False)
        # For direct shell execution convenience (used by run() when cmd is str)
        self.executable = kwargs.get("executable", "/bin/bash")
        self.elf = kwargs.get("elf", None)  # Optional elf object for sudo permission checks

    # -----------------------------
    # Shared low-level runner
    # -----------------------------
    def run(self, cmd, timeout: Optional[int] = None) -> Tuple[int, str, str]:
        """
        Execute a command as a subprocess.
        Returns: (return_code, stdout, stderr)
        """
        timeout = timeout or self.timeout
        shell_mode = isinstance(cmd, str)

        try:
            result = subprocess.run(
                cmd,
                shell=shell_mode,
                text=True,
                capture_output=True,
                timeout=timeout,
                executable=self.executable if shell_mode else None,
            )
            return result.returncode, (result.stdout or "").strip(), (result.stderr or "").strip()
        except subprocess.TimeoutExpired:
            return -1, "", "⏱️ Subprocess timed out"
        except Exception as ex:
            return -1, "", self._format_exception(ex)

    # -----------------------------
    # Orchestrator (retry loop)
    # -----------------------------
    def _run_with_retries(
        self,
        payload: Any,
        *,
        max_retries: int = 5,
        unsafe: bool = True,
        return_success: bool = False,
    ):
        """
        Orchestrate attempts with clear logs, optional dependency recovery,
        sudo fallback on permission errors, and code/command repair on failure.
        """
        attempt = 0
        current_payload = payload

        while attempt <= max_retries:
            step = attempt + 1
            total = max_retries + 1
            self._log(f"🔁 Attempt {step}/{total}: {self._describe(current_payload)}")

            rc, out, err = self._attempt(current_payload)

            if rc == 0:
                self._log(f"✅ Success on attempt {step}")
                return (out, 1) if return_success else out

            # Failure path:
            # 1) Timeout / general error message
            self._log(f"❌ Error: {err or 'Unknown error'}")

            # 2) Missing dependency hook (subclass may choose to install)
            if unsafe:
                missing = self._detect_missing_dependency(err)
                if missing:
                    self._log(f"📦 Missing dependency detected: {missing} — installing…")
                    if self._install_dependency(missing):
                        self._log("📦 Install complete. Retrying…")
                        attempt += 1
                        continue
                    else:
                        self._log("❌ Dependency installation failed.")

            # 3) Permission error → sudo fallback
            if self._is_permission_error(err) and not self.is_root():
                self._log("⚠️ Permission error detected — attempting sudo fallback.")
                if self.ask_for_sudo_permission(self.elf):
                    rc2, out2, err2 = self._sudo_attempt(current_payload)
                    if rc2 == 0:
                        self._log("✅ Success with sudo.")
                        return (out2, 1) if return_success else out2
                    self._log(f"❌ Sudo run failed: {err2 or 'Unknown error'}")
                else:
                    self._log("🚫 Sudo permission denied by user.")
                    return ("❌ Permission denied", 0) if return_success else "❌ Permission denied"

            # 4) Attempt repair (subclass provided) if we still have retries left
            if attempt < max_retries:
                repaired = self._repair(current_payload, err)
                if repaired is not None and repaired != current_payload:
                    self._log("🔧 Applied repair. Retrying…")
                    current_payload = repaired
                    attempt += 1
                    continue

            # 5) Give up
            self._log(f"🛑 Giving up after {step} attempt(s).")
            return (f"{err or 'Execution failed'}", 0) if return_success else (err or "Execution failed")

        return ("❌ Could not fix or execute", 0) if return_success else "❌ Could not fix or execute"

    # -----------------------------
    # Template methods for subclasses
    # -----------------------------
    @abstractmethod
    def _attempt(self, payload: Any) -> Tuple[int, str, str]:
        """Perform one attempt. Return (rc, out, err)."""
        raise NotImplementedError

    def _sudo_attempt(self, payload: Any) -> Tuple[int, str, str]:
        """Default sudo attempt simply wraps a best-effort sudo around the same payload if possible."""
        # By default, delegate to _attempt — subclasses that can re-run with sudo should override.
        return self._attempt(payload)

    def _detect_missing_dependency(self, err: str) -> Optional[str]:
        """Return the missing dependency/package name if detectable, else None."""
        return None

    def _install_dependency(self, name: str) -> bool:
        """Install a dependency. Subclasses override to implement language/system specifics."""
        return False

    def _repair(self, payload: Any, err: str) -> Any:
        """Attempt to repair payload (e.g., code fix). Return new payload or original/no-op."""
        return payload

    def _describe(self, payload: Any) -> str:
        """Human-readable description of the payload for progress logs."""
        return str(payload)

    # -----------------------------
    # Helpers
    # -----------------------------
    @staticmethod
    def is_root() -> bool:
        try:
            return os.geteuid() == 0
        except AttributeError:
            # Windows compatibility fallback
            return os.name == "nt" and "ADMIN" in os.environ.get("USERNAME", "").upper()

    @staticmethod
    def _format_exception(ex: Exception) -> str:
        return f"⚠️ Unexpected error: {type(ex).__name__}: {str(ex)}"

    def requires_root(self) -> bool:
        return self.check_root and not self.is_root()

    @staticmethod
    def ask_for_sudo_permission(elf) -> bool:
        import random
        try:
            if hasattr(elf, "personality") and str(elf.personality).lower().startswith("judais"):
                prompt = random.choice(
                    [
                        "JudAIs requests root access. Confirm?",
                        "Elevated permission required. Shall I proceed?",
                        "System integrity override. Approve sudo access?",
                    ]
                )
            else:
                prompt = random.choice(
                    [
                        "Precious, Lobi needs your blessing to weave powerful magics...",
                        "Without sudo, precious, Lobi cannot poke the network bits!",
                        "Dangerous tricksies need root access... Will you trust Lobi?",
                    ]
                )
            return input(f"⚠️ {prompt} (yes/no) ").strip().lower() in ["yes", "y"]
        except EOFError:
            return False

    @staticmethod
    def _is_permission_error(err: str) -> bool:
        if not err:
            return False
        low = err.lower()
        return any(
            term in low for term in ["permission denied", "must be run as root", "operation not permitted"]
        )

    @staticmethod
    def extract_code(text: str, language: str | None = None) -> str:
        """
        Extracts code blocks from markdown-like text using language-specific or generic patterns.
        """
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

    def _log(self, msg: str) -> None:
        # Minimal, unbuffered progress logging to stdout so the CLI shows activity.
        print(msg, flush=True)

    # Utilities for subclasses that need to add 'sudo' to a command
    @staticmethod
    def _prepend_sudo(cmd):
        if isinstance(cmd, str):
            # Only add sudo if not already present at the front (be conservative)
            parts = shlex.split(cmd)
            if parts and parts[0] != "sudo":
                return "sudo " + cmd
            return cmd
        elif isinstance(cmd, list):
            return ["sudo"] + cmd if (not cmd or cmd[0] != "sudo") else cmd
        else:
            return cmd
