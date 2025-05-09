# tools/install_project.py

from core.tools.base_subprocess import RunSubprocessTool
from pathlib import Path

class InstallProjectTool(RunSubprocessTool):
    name = "install_project"
    description = "Installs a Python project into the current elfenv using setup.py, pyproject.toml, or requirements.txt."

    def __init__(self, **kwargs):
        self.elfenv = kwargs.get("elfenv", Path(".elfenv"))
        self.pip_bin = self.elfenv / "bin" / "pip"
        self.ensure_elfenv()
        super().__init__(**kwargs)

    def __call__(self, path="."):
        path = Path(path)
        if (path / "setup.py").exists():
            cmd = [str(self.pip_bin), "install", "."]
        elif (path / "pyproject.toml").exists():
            cmd = [str(self.pip_bin), "install", "."]
        elif (path / "requirements.txt").exists():
            cmd = [str(self.pip_bin), "install", "-r", "requirements.txt"]
        else:
            return "❌ No installable project found in the given directory."

        code, out, err = self.run(cmd, timeout=60)
        return f"📦 {out or err}"

    def ensure_elfenv(self):
        from venv import create
        if not self.pip_bin.exists():
            create(str(self.elfenv), with_pip=True)
