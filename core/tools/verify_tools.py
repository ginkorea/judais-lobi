# core/tools/verify_tools.py — Config-driven verification tool

import shlex
import sys
from typing import Optional, Tuple

from core.tools.executor import run_subprocess

#: What a repository writes where it means *the interpreter this agent is
#: running under*.
#:
#: A verify command is the one command in this framework that a **repository**
#: authors, and it is run wherever the agent happens to be — inside bwrap,
#: from a pool worker, out of a wheel someone installed into a venv nobody
#: activated.  ``pytest`` as a bare word depends on that venv's ``bin`` being
#: on ``PATH``, which under the sandbox is whatever ``PATH`` the parent had
#: and under a service is frequently the system one.  A repository that means
#: "the tests, run by the Python that is running you" could not say so, and
#: the failure it got instead was ``/bin/bash: pytest: command not found`` —
#: which reads as a broken tool rather than as a missing declaration.
#:
#: So it is a token, expanded in one place, in the defaults **and** in what a
#: repository configured.  Expanded by :func:`shlex.quote`, because an
#: interpreter path may contain a space and the command is run under a shell.
PYTHON_TOKEN = "{python}"


class VerifyTool:
    """Config-driven verification. Reads command overrides from config dict.

    Config format (from .judais-lobi.yml)::

        verification:
          lint: "ruff check ."
          test: "{python} -m pytest -q"
          typecheck: "mypy ."
          format: "ruff format --check ."

    Each action returns (exit_code, stdout, stderr).

    **The command is the repository's, and that is the whole design.** This
    tool asks for ``verify.run`` and not ``shell.exec``, and
    :data:`core.runtime.skills.CODE_PLANE_SCOPES` deliberately leaves
    ``verify.run`` out: the model chooses *which* of lint, test, typecheck
    and format to invoke and cannot compose the command that runs. What it
    runs is what the repository declared, or — for a repository that
    declared nothing — the ordinary thing for a Python project, with
    :data:`PYTHON_TOKEN` making "the ordinary thing" mean the same in a
    sandbox as it does in a shell.

    The command runs in the **process's working directory**. There is no
    per-call root, on purpose: :class:`~core.tools.patch_tool.PatchTool` and
    :class:`~core.tools.repo_map_tool.RepoMapTool` are constructed against a
    repository path and the bus's bwrap profile binds the working directory
    read-write, so "the repository the agent is working in" is one fact —
    the cwd — rather than three that can disagree. A caller driving a
    mission at a repository chdirs into it.
    """

    DEFAULTS = {
        "lint": "ruff check .",
        "test": f"{PYTHON_TOKEN} -m pytest",
        "typecheck": f"{PYTHON_TOKEN} -m mypy .",
        "format": "ruff format --check .",
    }

    def __init__(self, config: Optional[dict] = None,
                 subprocess_runner=None,
                 python: Optional[str] = None):
        self._config = config or {}
        self._subprocess_runner = subprocess_runner
        #: The interpreter :data:`PYTHON_TOKEN` expands to.  A parameter so a
        #: caller that knows better than ``sys.executable`` — a deployment
        #: whose project venv is not the one the agent runs from — can say
        #: so, and so a test can pin it.
        self._python = python or sys.executable

    def __call__(self, action: str, **kwargs) -> Tuple[int, str, str]:
        cmd = self._resolve_command(action)
        if cmd is None:
            return (1, "", f"Unknown verify action: {action}")
        try:
            return run_subprocess(
                cmd, shell=True, timeout=300,
                subprocess_runner=self._subprocess_runner,
            )
        except Exception as exc:
            return (1, "", f"{type(exc).__name__}: {exc}")

    def _resolve_command(self, action: str) -> Optional[str]:
        """Resolve command: config override > default, then expand the token.

        A plain :meth:`str.replace` and not :meth:`str.format`: a real verify
        command carries braces of its own — an ``awk '{print $1}'``, a shell
        brace expansion — and formatting one would raise ``KeyError`` on
        somebody's working configuration.
        """
        verification = self._config.get("verification", {})
        if isinstance(verification, dict) and action in verification:
            cmd = verification[action]
        else:
            cmd = self.DEFAULTS.get(action)
        if cmd is None:
            return None
        return str(cmd).replace(PYTHON_TOKEN, shlex.quote(self._python))
