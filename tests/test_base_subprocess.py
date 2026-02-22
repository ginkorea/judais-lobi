# tests/test_base_subprocess.py

import subprocess
import pytest
from pathlib import Path

from core.tools.run_shell import RunShellTool
from core.tools.run_python import RunPythonTool
from core.tools.base_subprocess import RunSubprocessTool
from tests.conftest import make_fake_subprocess_runner


class TestRunShellToolWithFakeRunner:
    def test_shell_success(self):
        runner = make_fake_subprocess_runner(rc=0, stdout="hello world", stderr="")
        tool = RunShellTool(subprocess_runner=runner)
        rc, out, err = tool.run("echo hello")
        assert rc == 0
        assert out == "hello world"

    def test_shell_failure(self):
        runner = make_fake_subprocess_runner(rc=1, stdout="", stderr="command not found")
        tool = RunShellTool(subprocess_runner=runner)
        rc, out, err = tool.run("badcmd")
        assert rc == 1
        assert "command not found" in err

    def test_shell_timeout(self):
        def timeout_runner(cmd, *, shell, timeout, executable):
            raise subprocess.TimeoutExpired(cmd, timeout)
        tool = RunShellTool(subprocess_runner=timeout_runner)
        rc, out, err = tool.run("sleep 999")
        assert rc == -1
        assert "timed out" in err.lower()

    def test_shell_exception(self):
        def error_runner(cmd, *, shell, timeout, executable):
            raise OSError("disk on fire")
        tool = RunShellTool(subprocess_runner=error_runner)
        rc, out, err = tool.run("anything")
        assert rc == -1
        assert "OSError" in err


class TestRunPythonToolWithFakeRunner:
    def test_python_tool_skip_venv(self):
        """RunPythonTool with skip_venv_setup should not try to create a venv."""
        runner = make_fake_subprocess_runner(rc=0, stdout="42", stderr="")
        tool = RunPythonTool(
            elfenv=Path("/tmp/fake_elfenv"),
            skip_venv_setup=True,
            subprocess_runner=runner,
        )
        assert tool.name == "run_python_code"

    def test_python_run_delegates_to_runner(self):
        runner = make_fake_subprocess_runner(rc=0, stdout="result", stderr="")
        tool = RunPythonTool(
            elfenv=Path("/tmp/fake_elfenv"),
            skip_venv_setup=True,
            subprocess_runner=runner,
        )
        rc, out, err = tool.run(["python", "script.py"])
        assert rc == 0
        assert out == "result"


class TestExtractCode:
    def test_extract_python_block(self):
        text = "Here is the code:\n```python\nprint('hello')\n```\nDone."
        assert RunSubprocessTool.extract_code(text, "python") == "print('hello')"

    def test_extract_generic_block(self):
        text = "```\nls -la\n```"
        assert RunSubprocessTool.extract_code(text) == "ls -la"

    def test_extract_inline_code(self):
        text = "Run `echo hi` to test"
        assert RunSubprocessTool.extract_code(text) == "echo hi"

    def test_extract_plain_text(self):
        text = "echo hello world"
        assert RunSubprocessTool.extract_code(text) == "echo hello world"
