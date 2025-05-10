# core/tools/base_subprocess.py

from abc import ABC
import subprocess
import os

from core.tools.tool import Tool


class RunSubprocessTool(Tool, ABC):
    """
    Base class for tools that execute subprocesses.
    Handles command execution, timeouts, error formatting, and optional root checks.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.name = "run_subprocess"
        self.description = "Runs a subprocess command and returns its output. Handles timeouts and errors."
        self.unsafe = kwargs.get("unsafe", True)
        self.return_success = kwargs.get("return_success", False)
        self.timeout = kwargs.get("timeout", 120)
        self.check_root = kwargs.get("check_root", False)
        self.executable = kwargs.get("executable", "/bin/bash") # default only for shell commands
        self.elf = kwargs.get("elf", None)  # Optional elf object for sudo permission checks

    def run(self, cmd, timeout=None):
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
                executable=self.executable if shell_mode else None
            )
            return result.returncode, result.stdout.strip(), result.stderr.strip()
        except subprocess.TimeoutExpired:
            return -1, "", "⏱️ Subprocess timed out"
        except Exception as ex:
            return -1, "", self._format_exception(ex)

    @staticmethod
    def is_root():
        try:
            return os.geteuid() == 0
        except AttributeError:
            # Windows compatibility fallback
            return os.name == "nt" and "ADMIN" in os.environ.get("USERNAME", "").upper()

    @staticmethod
    def _format_exception(ex: Exception) -> str:
        return f"⚠️ Unexpected error: {type(ex).__name__}: {str(ex)}"

    def requires_root(self):
        return self.check_root and not self.is_root()

    @staticmethod
    def ask_for_sudo_permission(elf):
        import random
        try:
            if hasattr(elf, "personality") and elf.personality == "judais":
                prompt = random.choice([
                    "JudAIs requests root access. Confirm?",
                    "Elevated permission required. Shall I proceed?",
                    "System integrity override. Approve sudo access?"
                ])
            else:
                prompt = random.choice([
                    "Precious, Lobi needs your blessing to weave powerful magics...",
                    "Without sudo, precious, Lobi cannot poke the network bits!",
                    "Dangerous tricksies need root access... Will you trust Lobi?"
                ])
            return input(f"⚠️ {prompt} (yes/no) ").strip().lower() in ["yes", "y"]
        except EOFError:
            return False

    @staticmethod
    def _is_permission_error(err):
        return any(term in err.lower() for term in ["permission denied", "must be run as root", "operation not permitted"])

    @staticmethod
    def extract_code(text: str, language: str = None) -> str:
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
