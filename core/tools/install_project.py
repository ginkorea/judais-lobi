# core/tools/install_project.py
# Phase 4: Stripped retries. Direct execution only.

from core.tools.base_subprocess import RunSubprocessTool
from pathlib import Path
from typing import Tuple


class InstallProjectTool(RunSubprocessTool):
    name = "install_project"
    description = "Installs a Python project into elfenv. Returns (exit_code, stdout, stderr)."

    def __init__(self, **kwargs):
        self.elfenv = kwargs.get("elfenv", Path(".elfenv"))
        self.pip_bin = self.elfenv / "bin" / "pip"
        if not kwargs.get("skip_venv_setup", False):
            self._ensure_elfenv()
        super().__init__(**kwargs)

    def __call__(self, path=".", timeout=None, **kwargs) -> Tuple[int, str, str]:
        """Install the project at the given path. Returns (rc, out, err)."""
        path = Path(path)
        if (path / "setup.py").exists():
            cmd = [str(self.pip_bin), "install", "."]
        elif (path / "pyproject.toml").exists():
            cmd = [str(self.pip_bin), "install", "."]
        elif (path / "requirements.txt").exists():
            cmd = [str(self.pip_bin), "install", "-r", "requirements.txt"]
        else:
            return 1, "", "No installable project found in the given directory."

        return self.run(cmd, timeout=timeout or 300)

    def _ensure_elfenv(self):
        from venv import create
        if not self.pip_bin.exists():
            create(str(self.elfenv), with_pip=True)
