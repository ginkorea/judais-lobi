# core/tools/run_python.py
# Phase 4: Stripped to dumb executor. No retries, no LLM repair, no pip install.

from __future__ import annotations

import re
from pathlib import Path
from typing import Tuple, Optional

from core.tools.base_subprocess import RunSubprocessTool


class RunPythonTool(RunSubprocessTool):
    name = "run_python_code"
    description = "Runs Python code in elfenv. Returns (exit_code, stdout, stderr)."

    def __init__(self, **kwargs):
        self.elfenv = kwargs.get("elfenv", Path(".elfenv"))
        self.python_bin = self.elfenv / "bin" / "python"
        self.pip_bin = self.elfenv / "bin" / "pip"
        if not kwargs.get("skip_venv_setup", False):
            self._ensure_elfenv()
        super().__init__(**kwargs)
        self.name = "run_python_code"

    def __call__(self, code: str, timeout=None, **kwargs) -> Tuple[int, str, str]:
        """Run *code* with the elfenv python. Returns (rc, out, err).

        The code travels **on standard input** — ``python -`` reads its
        program from stdin — not on disk and not in ``argv``.

        Not on disk: it used to be written to a host ``NamedTemporaryFile``
        and the path passed as ``argv[1]``, which is correct for exactly one
        executor: the one that shares a filesystem with this process. Under
        ``BwrapSandbox`` — the sandbox this framework now runs by default —
        ``/tmp`` is a private tmpfs, so the path handed over named nothing
        at all inside the namespace and the tool answered ``can't open file
        '/tmp/tmpXXXX.py'`` for every program it was ever given.

        Not in ``argv`` either: 0.8.2 moved the program to ``-c <code>``,
        which fixed the temp-file bug but put the whole generated program in
        the argument list, where any other process on the host can read it
        out of ``ps`` — the same class of leak 0.8.2 had just fixed for the
        Mistral key. ``python -`` with the code on stdin is visible to
        nobody: ``argv`` is two tokens whatever the program says, and
        stdin is not a process attribute other users can list. A temp file
        also outlived a hard kill; stdin has nothing to clean up because it
        created nothing.
        """
        return self.run(
            [str(self.python_bin), "-"],
            timeout=timeout or self.timeout,
            stdin=str(code),
        )

    def _detect_missing_dependency(self, err: str) -> Optional[str]:
        """Kept — kernel uses this to decide if a pip install tool call is needed."""
        m = re.search(r"No module named ['\"]([^'\"]+)['\"]", err or "")
        return m.group(1) if m else None

    def _ensure_elfenv(self):
        from venv import create
        if not self.python_bin.exists():
            create(str(self.elfenv), with_pip=True)
