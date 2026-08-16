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
        stdin: Optional[str] = None,
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


#: The environment every sandboxed child gets no matter which tool asked or
#: which backend runs it: the names a program needs to *be a program at all*
#: — find its interpreter (``PATH``), find its config and the venv under it
#: (``HOME``), render text (``LANG``, ``TERM``) and put its scratch files
#: where the sandbox expects them (``TMPDIR``).  Everything else the host
#: exported — every API key, every token, every ``AWS_*`` — is left behind,
#: because a subprocess a model chose to run is the last place a secret the
#: model never needed should turn up.  ``LC_*`` is a family, not a name, so
#: it is matched by prefix in :func:`build_sandbox_env`.
_ENV_ALLOWLIST: Tuple[str, ...] = ("PATH", "HOME", "LANG", "TERM", "TMPDIR")
_ENV_ALLOWLIST_PREFIXES: Tuple[str, ...] = ("LC_",)


def build_sandbox_env(profile: Optional[SandboxProfile] = None) -> dict:
    """The child environment for *profile*: the allow-list plus its names.

    Read here, in the parent, from the parent's own ``os.environ`` — this
    is the *one* place the sandbox layer reads it, so "what a sandboxed
    child can see of the host environment" is one list in one function and
    not a merge repeated in two backends.  The result is what the bus hands
    to ``execute(env=…)``, and it means the same thing on either backend
    because it is computed before either is chosen.

    A name the profile lists but the host never set is simply absent, not
    an empty string: a tool asking to forward ``HTTPS_PROXY`` on a host
    that has none should see no proxy, not a proxy of ``""``.
    """
    profile = profile or SandboxProfile()
    names = list(_ENV_ALLOWLIST) + list(profile.env_passthrough)
    env = {name: os.environ[name] for name in names if name in os.environ}
    for name, value in os.environ.items():
        if name.startswith(_ENV_ALLOWLIST_PREFIXES):
            env[name] = value
    return env


class NoneSandbox:
    """Passthrough sandbox for dev/test. No isolation.

    Its one rule about the environment is the rule both backends share and
    the one this module states once: the child's environment is **exactly**
    what the caller passes as ``env``.  ``env=None`` is the caller having no
    opinion, and the child then inherits the parent's full environment — the
    convenience a direct caller and the tests rely on.  Under the bus, which
    is the path every tool takes, ``env`` is never ``None``: the bus builds
    it with :func:`build_sandbox_env`, so a tool's child gets the allow-list
    and its profile's names and nothing more, here exactly as under bwrap.
    Neither backend merges in ``os.environ`` of its own accord.
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
        stdin: Optional[str] = None,
    ) -> Tuple[int, str, str]:
        shell_mode = _shell_mode(cmd, shell)
        run_env = dict(os.environ) if env is None else dict(env)
        try:
            result = subprocess.run(
                cmd,
                shell=shell_mode,
                text=True,
                capture_output=True,
                timeout=timeout or 120,
                executable=(executable or "/bin/bash") if shell_mode else None,
                env=run_env,
                input=stdin,
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
        shell: Optional[bool] = None,
        executable: Optional[str] = None,
        stdin: Optional[str] = None,
    ) -> Tuple[int, str, str]:
        profile = profile or SandboxProfile()
        bwrap_args = self._build_bwrap_args(profile)

        if _shell_mode(cmd, shell):
            full_cmd = bwrap_args + [executable or "/bin/bash", "-c", cmd]
        elif isinstance(cmd, str):
            full_cmd = bwrap_args + [cmd]
        else:
            full_cmd = bwrap_args + list(cmd)

        # The env rule this module states once (see :class:`NoneSandbox`):
        # the child's environment is exactly what the caller passed, and
        # ``None`` means "inherit the parent's". This backend does not
        # merge in ``os.environ`` on top — under the bus the caller already
        # handed it the allow-listed set, and merging the host's back in
        # would put the secrets the sandbox exists to strip right back into
        # the child.
        run_env = dict(os.environ) if env is None else dict(env)
        try:
            result = subprocess.run(
                full_cmd,
                text=True,
                capture_output=True,
                timeout=timeout or 120,
                env=run_env,
                preexec_fn=self._rlimit_preexec(profile),
                input=stdin,
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


class SandboxUnavailable(RuntimeError):
    """A sandbox backend was *asked for by name* and cannot be built.

    Raised only for an explicit request — ``--unsandboxed`` never raises,
    and neither does the auto path, which quietly settles for ``none`` when
    ``bwrap`` is absent.  It exists so that a caller who says ``bwrap`` and
    means it hears "this host has no bubblewrap; install it or pass
    ``--unsandboxed``" rather than being silently downgraded to no
    isolation at all — the silent downgrade is exactly what the old
    :func:`get_sandbox` did, and a security control that turns itself off
    without telling anyone is worse than one that is simply off.
    """


#: The one name every opt-out spells.  ``--unsandboxed`` sets it; so does
#: ``JUDAIS_LOBI_SANDBOX=none``.  ``bwrap`` forces the sandbox and refuses
#: rather than fall back.  Anything else (or nothing) is the auto path.
SANDBOX_ENV_VAR = "JUDAIS_LOBI_SANDBOX"


def select_sandbox(requested: Optional[str] = None) -> Tuple[SandboxRunner, str]:
    """Choose the sandbox and report the name actually chosen.

    The single owner of the decision, so the CLI, a library caller and the
    tests all reach the same verdict from the same code.  Returns the
    runner and the string a consumer will see on ``mission_started`` —
    ``"bwrap"`` or ``"none"``.

    Precedence is **flag > env > auto**: *requested* is what a flag
    resolved to (``"none"`` for ``--unsandboxed``, ``"bwrap"`` to force,
    ``None`` for no flag); only when it is ``None`` is
    :data:`SANDBOX_ENV_VAR` consulted; and only when neither speaks does the
    auto path run — ``bwrap`` when it is on ``PATH``, ``none`` when it is
    not.  This is the line that makes the sandbox *on by default*: silence
    lands on ``bwrap`` wherever bubblewrap exists, and reaching ``none``
    takes someone saying so.

    ``bwrap`` requested but absent is a :class:`SandboxUnavailable`, not a
    fallback: an operator who asked for isolation is told it is missing and
    how to proceed, rather than getting the unsandboxed run they were trying
    to avoid.
    """
    choice = requested if requested is not None else os.environ.get(SANDBOX_ENV_VAR)
    choice = (choice or "").strip().lower() or None

    if choice == "none":
        return NoneSandbox(), "none"
    if choice == "bwrap":
        if not BwrapSandbox.is_available():
            raise SandboxUnavailable(
                "bwrap sandbox was requested but bubblewrap is not on PATH. "
                "Install bubblewrap (e.g. 'apt install bubblewrap'), or pass "
                "--unsandboxed / set JUDAIS_LOBI_SANDBOX=none to run without "
                "isolation."
            )
        return BwrapSandbox(), "bwrap"

    # auto: safe by default wherever the tooling exists to be safe.
    if BwrapSandbox.is_available():
        return BwrapSandbox(), "bwrap"
    return NoneSandbox(), "none"


def get_sandbox(backend: str = "none") -> SandboxRunner:
    """Backward-compatible thin wrapper over :func:`select_sandbox`.

    Kept for callers that only want a runner by name and never cared about
    the chosen string.  Its historic default was ``"none"`` and stays
    ``"none"`` — the on-by-default behaviour lives in :func:`select_sandbox`
    with ``requested=None``, which this function deliberately does not pass
    on, so an existing caller of ``get_sandbox()`` is not silently switched
    into a sandbox it never asked for.
    """
    runner, _name = select_sandbox(backend)
    return runner
