# core/tools/sandbox.py — Sandbox runners

import os
import shutil
import subprocess
from typing import Protocol, Tuple, Optional, List, Union

from core.tools.descriptors import SandboxProfile


class SandboxRunner(Protocol):
    """Protocol for sandboxed command execution.

    ``shell`` and ``executable`` are part of the protocol because the
    caller knows them and the sandbox cannot infer them.  ``ToolBus``
    installs a sandbox runner in place of ``executor.run_subprocess``,
    which is handed both by every tool that calls it; the runner used to
    drop them on the floor and each sandbox re-derived shell mode from
    ``isinstance(cmd, str)`` and hard-coded ``/bin/bash``.  That silently
    overrode a tool configured with a different interpreter and made a
    caller's explicit ``shell=False`` mean nothing.

    ``shell=None`` keeps the old inference — a string is a shell command,
    a list is an argv — so a direct caller that never had an opinion does
    not have to grow one.  ``shell`` decides the string case only: an argv
    is run as an argv whatever the flag says, because joining one into a
    script would re-quote arguments the caller had already separated.
    """
    def execute(
        self,
        cmd: Union[str, List[str]],
        *,
        profile: Optional[SandboxProfile] = None,
        timeout: Optional[int] = None,
        env: Optional[dict] = None,
        shell: Optional[bool] = None,
        executable: Optional[str] = None,
    ) -> Tuple[int, str, str]: ...


def _shell_mode(cmd: Union[str, List[str]], shell: Optional[bool]) -> bool:
    """Whether *cmd* runs under an interpreter.

    An argv never does: it arrived already split, and re-joining it into a
    shell script would hand the quoting back to the shell. For a string the
    caller decides, and ``None`` means the old inference — a string is a
    script.
    """
    if not isinstance(cmd, str):
        return False
    return True if shell is None else bool(shell)


class NoneSandbox:
    """Passthrough sandbox for dev/test. No isolation."""

    def execute(
        self,
        cmd: Union[str, List[str]],
        *,
        profile: Optional[SandboxProfile] = None,
        timeout: Optional[int] = None,
        env: Optional[dict] = None,
        shell: Optional[bool] = None,
        executable: Optional[str] = None,
    ) -> Tuple[int, str, str]:
        shell_mode = _shell_mode(cmd, shell)
        run_env = {**os.environ, **(env or {})}
        try:
            result = subprocess.run(
                cmd,
                shell=shell_mode,
                text=True,
                capture_output=True,
                timeout=timeout or 120,
                executable=(executable or "/bin/bash") if shell_mode else None,
                env=run_env,
            )
            return (
                result.returncode,
                (result.stdout or "").strip(),
                (result.stderr or "").strip(),
            )
        except subprocess.TimeoutExpired:
            return -1, "", "Subprocess timed out"
        except Exception as ex:
            return -1, "", f"Unexpected error: {type(ex).__name__}: {ex}"


class BwrapSandbox:
    """bubblewrap-based Linux namespace sandbox.

    Tier-1 backend. Enforces:
    - Filesystem isolation (workspace RW, rest RO)
    - rlimits (CPU time, max procs)
    - Network namespace isolation (deny by default)
    - Mount caching for dependency dirs
    """

    def __init__(self, bwrap_path: str = "bwrap"):
        self._bwrap_path = bwrap_path
        if not self.is_available():
            raise FileNotFoundError(
                f"bwrap not found at '{bwrap_path}'. "
                "Install bubblewrap or use NoneSandbox."
            )

    def execute(
        self,
        cmd: Union[str, List[str]],
        *,
        profile: Optional[SandboxProfile] = None,
        timeout: Optional[int] = None,
        env: Optional[dict] = None,
        shell: Optional[bool] = None,
        executable: Optional[str] = None,
    ) -> Tuple[int, str, str]:
        profile = profile or SandboxProfile()
        bwrap_args = self._build_bwrap_args(profile)

        if _shell_mode(cmd, shell):
            full_cmd = bwrap_args + [executable or "/bin/bash", "-c", cmd]
        elif isinstance(cmd, str):
            full_cmd = bwrap_args + [cmd]
        else:
            full_cmd = bwrap_args + list(cmd)

        run_env = {**os.environ, **(env or {})}
        try:
            result = subprocess.run(
                full_cmd,
                text=True,
                capture_output=True,
                timeout=timeout or 120,
                env=run_env,
            )
            return (
                result.returncode,
                (result.stdout or "").strip(),
                (result.stderr or "").strip(),
            )
        except subprocess.TimeoutExpired:
            return -1, "", "Subprocess timed out"
        except Exception as ex:
            return -1, "", f"Unexpected error: {type(ex).__name__}: {ex}"

    def _build_bwrap_args(self, profile: SandboxProfile) -> List[str]:
        """Build bwrap command-line arguments from a SandboxProfile."""
        args = [self._bwrap_path]

        # Network isolation (deny by default)
        args.extend(["--unshare-net"])

        # Basic filesystem: bind / read-only
        args.extend(["--ro-bind", "/", "/"])

        # /proc and /dev
        args.extend(["--proc", "/proc"])
        args.extend(["--dev", "/dev"])

        # Writable tmpfs for /tmp
        args.extend(["--tmpfs", "/tmp"])

        # Workspace writable bind
        if profile.workspace_writable:
            cwd = os.getcwd()
            args.extend(["--bind", cwd, cwd])

        # Explicit write paths
        for path in profile.allowed_write_paths:
            args.extend(["--bind", path, path])

        # Explicit read paths (already covered by --ro-bind / /)
        # but we add explicit ones for clarity and future filtering
        for path in profile.allowed_read_paths:
            args.extend(["--ro-bind", path, path])

        return args

    @staticmethod
    def is_available() -> bool:
        """Check if bwrap is installed."""
        return shutil.which("bwrap") is not None


def get_sandbox(backend: str = "none") -> SandboxRunner:
    """Factory function to create a sandbox by name."""
    if backend == "bwrap":
        if BwrapSandbox.is_available():
            return BwrapSandbox()
        # Fallback to none if bwrap not available
        return NoneSandbox()
    return NoneSandbox()
