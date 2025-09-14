# tools/install_project.py

from core.tools.base_subprocess import RunSubprocessTool
from pathlib import Path
from typing import Tuple, Any


class InstallProjectTool(RunSubprocessTool):
    name = "install_project"
    description = (
        "Installs a Python project into the current elfenv using setup.py, "
        "pyproject.toml, or requirements.txt."
    )

    def __init__(self, **kwargs):
        self.elfenv = kwargs.get("elfenv", Path(".elfenv"))
        self.pip_bin = self.elfenv / "bin" / "pip"
        self.ensure_elfenv()
        super().__init__(**kwargs)

    def __call__(self, path="."):
        """
        Public entry point: tries to install the given project and returns human-readable output.
        """
        return self._run_with_retries(path, max_retries=1, unsafe=False, return_success=False)

    # ---------- Template overrides ----------
    def _attempt(self, payload: Any) -> Tuple[int, str, str]:
        """
        payload = path to project directory
        """
        path = Path(payload)
        if (path / "setup.py").exists():
            cmd = [str(self.pip_bin), "install", "."]
        elif (path / "pyproject.toml").exists():
            cmd = [str(self.pip_bin), "install", "."]
        elif (path / "requirements.txt").exists():
            cmd = [str(self.pip_bin), "install", "-r", "requirements.txt"]
        else:
            return 1, "", "❌ No installable project found in the given directory."

        return self.run(cmd, timeout=300)

    def _describe(self, payload: Any) -> str:
        return f"install project at {payload}"

    # ---------- Helpers ----------
    def ensure_elfenv(self):
        from venv import create
        if not self.pip_bin.exists():
            self._log(f"🧙 Creating venv at {self.elfenv} …")
            create(str(self.elfenv), with_pip=True)
