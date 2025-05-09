# tools/run_shell.py

from core.tools.base_subprocess import RunSubprocessTool

class RunShellTool(RunSubprocessTool):
    name = "run_shell_command"
    description = "Runs a shell command and returns its output. Uses bash by default."

    def __init__(self, **kwargs):
        kwargs.setdefault("executable", "/bin/bash")
        super().__init__(**kwargs)
        self.name = "run_shell_command"

    def __call__(self, command, timeout=None, return_success=False):
        code, out, err = self.run(command, timeout=timeout)
        result = out if code == 0 else err
        return (result, 1 if code == 0 else 0) if return_success else result

    # 🔁 Use shared extract_code
    extract_code = staticmethod(lambda text: RunSubprocessTool.extract_code(text, "bash"))
