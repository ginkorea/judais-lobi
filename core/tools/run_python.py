# tools/run_python.py

from __future__ import annotations

import os
import tempfile
import re
from pathlib import Path
from typing import Tuple, Any, Optional

from core.tools.base_subprocess import RunSubprocessTool


class RunPythonTool(RunSubprocessTool):
    name = "run_python_code"
    description = (
        "Executes Python in an agent-specific elfenv with retries, package recovery, "
        "sudo fallback, code repair, and progress logs."
    )

    def __init__(self, **kwargs):
        self.elfenv = kwargs.get("elfenv", Path(".elfenv"))
        self.python_bin = self.elfenv / "bin" / "python"
        self.pip_bin = self.elfenv / "bin" / "pip"
        self._ensure_elfenv()
        super().__init__(**kwargs)
        self.name = "run_python_code"

        # Track latest temp file so sudo retry can reuse it safely
        self._last_temp_path: Optional[str] = None

    # Public interface
    def __call__(
        self,
        code: str,
        elf,
        unsafe: bool = True,
        max_retries: int = 5,
        return_success: bool = False,
    ):
        self.elf = elf
        return self._run_with_retries(
            code, max_retries=max_retries, unsafe=unsafe, return_success=return_success
        )

    # ---------- Template overrides ----------
    def _attempt(self, payload: Any) -> Tuple[int, str, str]:
        """Write code to a temp file and run with elfenv python."""
        with tempfile.NamedTemporaryFile(delete=False, mode="w", suffix=".py") as f:
            f.write(str(payload))
            self._last_temp_path = f.name

        rc, out, err = self.run([str(self.python_bin), self._last_temp_path], timeout=self.timeout)
        return rc, out, err

    def _sudo_attempt(self, payload: Any) -> Tuple[int, str, str]:
        """Re-use temp file for sudo retry."""
        if not self._last_temp_path:
            return 1, "", "Internal error: no temp file available for sudo retry"
        return self.run(["sudo", str(self.python_bin), self._last_temp_path], timeout=self.timeout)

    def _detect_missing_dependency(self, err: str) -> Optional[str]:
        m = re.search(r"No module named ['\"]([^'\"]+)['\"]", err or "")
        return m.group(1) if m else None

    def _install_dependency(self, name: str) -> bool:
        self._log(f"📦 pip install {name} (in elfenv)")
        rc, out, err = self.run([str(self.pip_bin), "install", name], timeout=max(self.timeout, 120))
        if rc == 0:
            return True
        self._log(f"❌ pip install failed: {err or out}")
        return False

    def _repair(self, payload: Any, err: str) -> Any:
        """Use the elf’s LLM to repair broken code if possible."""
        if not hasattr(self, "elf") or not getattr(self.elf, "client", None):
            return payload

        prompt = (
            "You are an expert Python repair assistant.\n\n"
            "The following Python code failed:\n\n"
            f"{payload}\n\n"
            "Error:\n\n"
            f"{err}\n\n"
            "Please rewrite the corrected full code below. "
            "Respond with only the fixed code in a Python code block."
        )

        try:
            # ✅ Unified API (works for both OpenAI and Mistral)
            response = self.elf.client.chat(
                model=self.elf.model,
                messages=[
                    {"role": "system", "content": "Fix broken Python code."},
                    {"role": "user", "content": prompt},
                ],
            )

            # Response is a plain string under unified_client
            repaired = self.extract_code(str(response), "python")
            if repaired and repaired.strip() and repaired.strip() != str(payload).strip():
                self._cleanup_temp()
                return repaired

        except Exception as e:
            self._log(f"⚠️ Repair request failed: {e}")

        return payload


    def _describe(self, payload: Any) -> str:
        code = str(payload).strip().splitlines()
        head = code[0] if code else ""
        return f"python script ({len(str(payload))} bytes): {head[:100]}"

    # ---------- Helpers ----------
    def _ensure_elfenv(self):
        from venv import create
        if not self.python_bin.exists():
            self._log(f"🧙 Creating venv at {self.elfenv} …")
            create(str(self.elfenv), with_pip=True)

    def _cleanup_temp(self):
        if self._last_temp_path and os.path.exists(self._last_temp_path):
            try:
                os.remove(self._last_temp_path)
            except Exception:
                pass
        self._last_temp_path = None
