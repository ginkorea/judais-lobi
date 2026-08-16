# core/tools/executor.py — Pure subprocess execution function

import subprocess
from typing import Tuple, Optional, Union, List, Callable


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
    """
    if subprocess_runner is not None:
        extra = {} if stdin is None else {"stdin": stdin}
        try:
            return subprocess_runner(
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
