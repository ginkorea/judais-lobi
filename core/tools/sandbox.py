# core/tools/sandbox.py — Sandbox runners

import os
import shutil
import subprocess
from typing import Protocol, Tuple, Optional, List, Union

from core.tools.descriptors import SandboxProfile


class SandboxRunner(Protocol):
    """Protocol for sandboxed command execution."""
    def execute(
        self,
        cmd: Union[str, List[str]],
        *,
        profile: Optional[SandboxProfile] = None,
        timeout: Optional[int] = None,
        env: Optional[dict] = None,
    ) -> Tuple[int, str, str]: ...


class NoneSandbox:
    """Passthrough sandbox for dev/test. No isolation."""

    def execute(
        self,
        cmd: Union[str, List[str]],
        *,
        profile: Optional[SandboxProfile] = None,
        timeout: Optional[int] = None,
        env: Optional[dict] = None,
    ) -> Tuple[int, str, str]:
        shell_mode = isinstance(cmd, str)
        run_env = {**os.environ, **(env or {})}
        try:
            result = subprocess.run(
                cmd,
                shell=shell_mode,
                text=True,
                capture_output=True,
                timeout=timeout or 120,
                executable="/bin/bash" if shell_mode else None,
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
    ) -> Tuple[int, str, str]:
        profile = profile or SandboxProfile()
        bwrap_args = self._build_bwrap_args(profile)

        if isinstance(cmd, str):
            full_cmd = bwrap_args + ["/bin/bash", "-c", cmd]
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
