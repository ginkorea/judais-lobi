# core/tools/executor.py — Pure subprocess execution function

import subprocess
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Tuple, Optional, Union, List, Callable, Iterator


#: The runner *this call* must go through, if anything installed one.
#:
#: A :class:`~contextvars.ContextVar` and not an attribute on a tool, and
#: the difference is a sandbox escape.  :meth:`core.tools.bus.ToolBus.dispatch`
#: used to sandbox a tool by **assigning** its runner onto the executor
#: object — ``setattr(executor, "subprocess_runner", runner)`` — calling it,
#: and putting the old value back in a ``finally``.  One dispatch at a time
#: that worked.  Two did not: a bus is shared by identity (``Run.child`` and
#: ``SwarmRunner(parallel>1)`` dispatch on one, and so does every concurrent
#: client of :mod:`core.tools.serve`, which runs each call through
#: ``anyio.to_thread.run_sync``), so the second dispatch's ``finally``
#: restored the ORIGINAL, unsandboxed runner while the first was still
#: inside its tool.  A multi-subprocess tool — git, patch, install — could
#: cross that line between two of its own children and spawn the second
#: outside the sandbox the run announced on ``mission_started``.  Nothing
#: reported it: the escape was silent, and ``sandbox_name`` went on saying
#: ``bwrap``.
#:
#: Carried per call, it cannot happen.  :func:`asyncio.to_thread` and
#: anyio's ``to_thread.run_sync`` both copy the context onto the worker
#: thread (verified against anyio 4.12), an :class:`asyncio.Task` starts
#: from a copy of its parent's, and a bare thread starts from an empty
#: one — so a dispatch's runner reaches that dispatch's subprocesses and
#: reaches nothing else.  No shared state is written, so there is nothing
#: for a second dispatch to restore.
#:
#: **The limit, stated rather than left to be discovered:** a tool that
#: starts a thread of its own with :class:`threading.Thread` or a
#: :class:`~concurrent.futures.ThreadPoolExecutor` does **not** inherit it —
#: neither copies the context — and a subprocess spawned from that thread
#: would run unsandboxed.  No tool in this package does that; one that
#: wants to must carry the runner across itself, which is what
#: :func:`current_subprocess_runner` is public for.
_ambient_runner: ContextVar[Optional[Callable]] = ContextVar(
    "judais_lobi_subprocess_runner", default=None)


def current_subprocess_runner() -> Optional[Callable]:
    """The runner installed for this call, or ``None`` when there is none.

    Public because a tool that hands work to a thread of its own has to
    carry it across by hand — see :data:`_ambient_runner`.
    """
    return _ambient_runner.get()


@contextmanager
def use_subprocess_runner(runner: Optional[Callable]) -> Iterator[None]:
    """Route every :func:`run_subprocess` under this block through *runner*.

    Scoped to the calling context and restored on the way out, including
    when the block raises.  ``None`` is a no-op rather than an override:
    "nothing to install for this dispatch" must not *unset* an outer one,
    because a tool that dispatches through the bus again nests, and the
    inner call keeping the outer isolation is the safe direction.
    """
    if runner is None:
        yield
        return
    token = _ambient_runner.set(runner)
    try:
        yield
    finally:
        _ambient_runner.reset(token)


def run_subprocess(
    cmd: Union[str, List[str]],
    *,
    shell: bool = False,
    timeout: int = 120,
    executable: Optional[str] = None,
    stdin: Optional[str] = None,
    subprocess_runner: Optional[Callable] = None,
) -> Tuple[int, str, str]:
    """Pure subprocess execution. No retries, no repair, no sudo.

    Returns (exit_code, stdout, stderr).

    ``stdin`` is fed to the child's standard input — how ``run_python``
    hands over its program without it appearing in ``ps``. It is passed on
    to a ``subprocess_runner`` only when it is set, so the many callers that
    installed a runner with the older ``(cmd, *, shell, timeout,
    executable)`` signature keep working: a tool that never uses stdin never
    causes that runner to be called with a keyword it does not accept.

    A runner installed for this call by :func:`use_subprocess_runner` beats
    the *subprocess_runner* argument, which is the same precedence the
    attribute swap it replaced had: a bus that decided this dispatch is
    sandboxed overrode whatever runner the tool was constructed with, and
    an isolation decision a tool's own constructor could defeat would not
    be one.  It also reaches further, deliberately — every
    ``run_subprocess`` under the dispatch, not only the objects the bus
    could find an attribute on.
    """
    runner = _ambient_runner.get()
    if runner is None:
        runner = subprocess_runner

    if runner is not None:
        extra = {} if stdin is None else {"stdin": stdin}
        try:
            return runner(
                cmd, shell=shell, timeout=timeout, executable=executable,
                **extra,
            )
        except subprocess.TimeoutExpired:
            return -1, "", "Subprocess timed out"
        except Exception as ex:
            return -1, "", f"Unexpected error: {type(ex).__name__}: {ex}"

    try:
        result = subprocess.run(
            cmd,
            shell=shell,
            text=True,
            capture_output=True,
            timeout=timeout,
            executable=executable,
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
