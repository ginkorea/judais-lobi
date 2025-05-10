# tools/run_python.py

import os, tempfile
from pathlib import Path
from core.tools.base_subprocess import RunSubprocessTool

class RunPythonTool(RunSubprocessTool):
    name = "run_python_code"
    description = "Executes Python in an agent-specific elfenv with retries, package recovery, sudo fallback, and repair."

    def __init__(self, **kwargs):
        self.elfenv = kwargs.get("elfenv", Path(".elfenv"))
        self.python_bin = self.elfenv / "bin" / "python"
        self.pip_bin = self.elfenv / "bin" / "pip"
        self.ensure_elfenv()
        super().__init__(**kwargs)
        self.name = "run_python_code"

    def __call__(self, code, elf, unsafe=True, max_retries=5, return_success=False):
        self.elf = elf
        attempt = 0
        current_code = code

        while attempt <= max_retries:
            with tempfile.NamedTemporaryFile(delete=False, mode="w", suffix=".py") as f:
                f.write(current_code)
                temp_path = f.name

            code, out, err = self.run([str(self.python_bin), temp_path], timeout=120)
            os.remove(temp_path)

            if code == 0:
                return (f"✅ Output:\n{out}", 1) if return_success else f"✅ Output:\n{out}"

            if "ModuleNotFoundError" in err and unsafe:
                pkg = self._extract_missing_package(err)
                if pkg:
                    self.run([str(self.pip_bin), "install", pkg])
                    attempt += 1
                    continue

            if self._is_permission_error(err) and not self.is_root():
                if self.ask_for_sudo_permission(elf):
                    code, out, err = self.run(["sudo", str(self.python_bin), temp_path], timeout=30)
                    if code == 0:
                        return (f"✅ Output (with sudo):\n{out}", 1) if return_success else f"✅ Output (with sudo):\n{out}"
                    return (f"❌ Sudo run failed:\n{err}", 0) if return_success else f"❌ Sudo run failed:\n{err}"
                return ("❌ Permission denied", 0) if return_success else "❌ Permission denied"

            if attempt < max_retries:
                current_code = self.repair_code(current_code, err)
                attempt += 1
                continue

            return (f"❌ Python error after {max_retries} retries:\n{err}", 0) if return_success else f"❌ Python error after {max_retries} retries:\n{err}"

        return ("❌ Could not fix or execute code", 0) if return_success else "❌ Could not fix or execute code"

    def ensure_elfenv(self):
        from venv import create
        if not self.python_bin.exists():
            create(str(self.elfenv), with_pip=True)

    @staticmethod
    def _extract_missing_package(err):
        import re
        match = re.search(r"No module named '(.*?)'", err)
        return match.group(1) if match else None


    # 🔁 Use shared extract_code
    extract_code = staticmethod(lambda text: RunSubprocessTool.extract_code(text, "python"))


    def repair_code(self, broken_code, error_message):
        prompt = f"""You are an expert Python repair assistant.

        The following Python code failed:
        
        ```python
        {broken_code}
        ````
        
        Error:
        
        ```
        {error_message}
        ```
        
        Please rewrite the corrected full code below. Respond with only the fixed code in a Python code block.
        """
        try:
            response = self.elf.client.chat.completions.create(
                model=self.elf.model,
                messages=[
                    {"role": "system", "content": "Fix broken Python code."},
                    {"role": "user", "content": prompt}
                ]
            )
            return self.extract_code(response.choices[0].message.content, "python")
        except Exception:
            return broken_code





