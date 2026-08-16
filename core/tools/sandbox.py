# core/tools/sandbox.py — Sandbox runners

import os
import shutil
import subprocess
from typing import Callable, Protocol, Tuple, Optional, List, Union

try:  # POSIX only; the sandbox is Linux-only anyway, but the import is not
    import resource
except ImportError:  # pragma: no cover - Windows
    resource = None  # type: ignore[assignment]

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

    Tier-1 backend. What it actually enforces, each against the
    :class:`~core.tools.descriptors.SandboxProfile` field that asks for it:

    - **Write isolation.** The host root is bound read-only and the working
      directory (``workspace_writable``) plus ``allowed_write_paths`` are
      re-bound read-write, so a command can read what its caller could read
      and can only *change* what the profile named. It is deliberately not
      read confinement: an interpreter under ``$HOME`` — every ``.venv`` —
      has to stay reachable, and a tool that resolved ``python3`` to a
      binary the namespace does not contain fails in a way nobody reads as
      "the sandbox did that".
    - **A private ``/tmp``.** A tmpfs, so nothing written there survives the
      call and nothing already there is visible. A tool that hands the
      sandbox a *host* temp path is handing it a path that does not exist
      inside; that is what took ``run_python`` off temp files and onto
      ``python -c``.
    - **Network denial by default**, and ``allow_network`` to keep it. The
      unshared namespace has a working loopback and nothing else, so a
      denied call fails with ``ENETUNREACH`` rather than hanging.
    - **rlimits**: ``max_cpu_seconds`` → ``RLIMIT_CPU``,
      ``max_memory_bytes`` → ``RLIMIT_AS``, ``max_processes`` →
      ``RLIMIT_NPROC``, applied with :func:`resource.setrlimit` in a
      ``preexec_fn`` on the bwrap process because bwrap has no flags of its
      own for them. They are inherited across the ``execve`` into the
      sandboxed command, so the limit lands on the payload and not only on
      the wrapper. Each is clamped to the hard limit already in force,
      since an unprivileged process cannot raise one.

      The sharp edge is ``RLIMIT_NPROC``: the kernel counts it per *user*,
      across every process that user already has, not per sandbox. A value
      below the caller's current process count does not bound the payload,
      it stops bwrap from forking at all — ``bwrap: Creating new namespace
      failed: Resource temporarily unavailable``. It is honoured as asked
      because a profile that states a limit means it; a caller that wants
      a *namespace-local* process count needs a user namespace, which this
      backend does not create.
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
                preexec_fn=self._rlimit_preexec(profile),
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

        # Network isolation (deny by default). The allowed case says
        # `--share-net` rather than saying nothing: an argument list is
        # read by people deciding whether a run was sandboxed, and
        # "network was granted" is not something a reader should have to
        # infer from a missing flag.
        args.append("--share-net" if profile.allow_network else "--unshare-net")

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

    #: Profile field → the rlimit that keeps it. Written as names because
    #: a resource this build of Python does not define (``RLIMIT_NPROC``
    #: is absent on some platforms) has to be skipped, not crash the run.
    _RLIMIT_FIELDS = (
        ("max_cpu_seconds", "RLIMIT_CPU"),
        ("max_memory_bytes", "RLIMIT_AS"),
        ("max_processes", "RLIMIT_NPROC"),
    )

    def _rlimit_preexec(self, profile: SandboxProfile) -> Optional[Callable[[], None]]:
        """The ``preexec_fn`` that applies *profile*'s rlimits, or ``None``.

        ``None`` when the profile asks for no limit, so a run that wanted
        none is the same ``subprocess.run`` call it was before this
        existed — ``preexec_fn`` is not free and is not safe in a threaded
        parent, and a sandbox should not pay for a constraint nobody
        declared.

        The limits are read *here*, in the parent, and only applied in the
        child: the child of a fork may call almost nothing safely, and
        ``getattr`` on a dataclass is not on the list of things worth
        doing between the fork and the exec.
        """
        if resource is None:
            return None

        limits: List[Tuple[int, int]] = []
        for field_name, rlimit_name in self._RLIMIT_FIELDS:
            value = getattr(profile, field_name, None)
            which = getattr(resource, rlimit_name, None)
            if value is None or which is None:
                continue
            _soft, hard = resource.getrlimit(which)
            if hard != resource.RLIM_INFINITY:
                # An unprivileged process cannot raise a hard limit, and
                # a setrlimit that fails would kill the run with a
                # ValueError from inside the fork. Ask for the strictest
                # thing that is grantable.
                value = min(int(value), hard)
            limits.append((which, int(value)))

        if not limits:
            return None

        def _apply() -> None:
            for which, value in limits:
                resource.setrlimit(which, (value, value))

        return _apply

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
