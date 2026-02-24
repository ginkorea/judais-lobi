# core/tools/executor.py — Pure subprocess execution function

import subprocess
from typing import Tuple, Optional, Union, List, Callable


def run_subprocess(
    cmd: Union[str, List[str]],
    *,
    shell: bool = False,
    timeout: int = 120,
    executable: Optional[str] = None,
    subprocess_runner: Optional[Callable] = None,
) -> Tuple[int, str, str]:
    """Pure subprocess execution. No retries, no repair, no sudo.

    Returns (exit_code, stdout, stderr).
    """
    if subprocess_runner is not None:
        try:
            return subprocess_runner(
                cmd, shell=shell, timeout=timeout, executable=executable,
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
