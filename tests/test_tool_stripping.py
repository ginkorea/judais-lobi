# tests/test_tool_stripping.py
# Verify stripped tools return (rc, out, err), no retry, no repair, no sudo.

import subprocess
import pytest
from pathlib import Path
from unittest.mock import patch

from core.tools.run_shell import RunShellTool
from core.tools.run_python import RunPythonTool
from core.tools.install_project import InstallProjectTool
from core.tools.base_subprocess import RunSubprocessTool
from tests.conftest import make_fake_subprocess_runner


class TestRunShellToolStripped:
    def test_returns_tuple(self):
        runner = make_fake_subprocess_runner(rc=0, stdout="ok", stderr="")
        tool = RunShellTool(subprocess_runner=runner)
        result = tool("echo hi")
        assert isinstance(result, tuple)
        assert len(result) == 3
        rc, out, err = result
        assert rc == 0
        assert out == "ok"

    def test_no_retry_on_failure(self):
        """Tool should NOT retry on failure — returns immediately."""
        call_count = 0
        def counting_runner(cmd, *, shell, timeout, executable):
            nonlocal call_count
            call_count += 1
            return 1, "", "error"
        tool = RunShellTool(subprocess_runner=counting_runner)
        rc, out, err = tool("failing command")
        assert rc == 1
        assert call_count == 1  # No retries

    def test_no_run_with_retries_method(self):
        tool = RunShellTool(subprocess_runner=make_fake_subprocess_runner())
        assert not hasattr(tool, "_run_with_retries")

    def test_no_prepend_sudo_method(self):
        tool = RunShellTool(subprocess_runner=make_fake_subprocess_runner())
        assert not hasattr(tool, "_prepend_sudo")

    def test_no_install_dependency_method(self):
        tool = RunShellTool(subprocess_runner=make_fake_subprocess_runner())
        assert not hasattr(tool, "_install_dependency")

    def test_detect_missing_dependency_kept(self):
        tool = RunShellTool(subprocess_runner=make_fake_subprocess_runner())
        assert tool._detect_missing_dependency("bash: jq: command not found") == "jq"
        assert tool._detect_missing_dependency("all good") is None

    def test_timeout_parameter(self):
        runner = make_fake_subprocess_runner(rc=0, stdout="ok", stderr="")
        tool = RunShellTool(subprocess_runner=runner, timeout=30)
        rc, out, err = tool("echo hi", timeout=60)
        assert rc == 0


class TestRunPythonToolStripped:
    def test_returns_tuple(self):
        runner = make_fake_subprocess_runner(rc=0, stdout="42", stderr="")
        tool = RunPythonTool(
            elfenv=Path("/tmp/fake_elfenv"),
            skip_venv_setup=True,
            subprocess_runner=runner,
        )
        result = tool("print(42)")
        assert isinstance(result, tuple)
        assert len(result) == 3
        rc, out, err = result
        assert rc == 0

    def test_no_retry_on_failure(self):
        call_count = 0
        def counting_runner(cmd, *, shell, timeout, executable):
            nonlocal call_count
            call_count += 1
            return 1, "", "SyntaxError"
        tool = RunPythonTool(
            elfenv=Path("/tmp/fake_elfenv"),
            skip_venv_setup=True,
            subprocess_runner=counting_runner,
        )
        rc, out, err = tool("invalid python")
        assert rc == 1
        assert call_count == 1

    def test_no_repair_method(self):
        tool = RunPythonTool(
            elfenv=Path("/tmp/fake_elfenv"),
            skip_venv_setup=True,
            subprocess_runner=make_fake_subprocess_runner(),
        )
        assert not hasattr(tool, "_repair")

    def test_no_install_dependency_method(self):
        tool = RunPythonTool(
            elfenv=Path("/tmp/fake_elfenv"),
            skip_venv_setup=True,
            subprocess_runner=make_fake_subprocess_runner(),
        )
        assert not hasattr(tool, "_install_dependency")

    def test_detect_missing_dependency_kept(self):
        tool = RunPythonTool(
            elfenv=Path("/tmp/fake_elfenv"),
            skip_venv_setup=True,
            subprocess_runner=make_fake_subprocess_runner(),
        )
        assert tool._detect_missing_dependency("No module named 'numpy'") == "numpy"
        assert tool._detect_missing_dependency("all good") is None

    def test_no_elf_parameter_required(self):
        """__call__ no longer requires elf parameter."""
        runner = make_fake_subprocess_runner(rc=0, stdout="ok", stderr="")
        tool = RunPythonTool(
            elfenv=Path("/tmp/fake_elfenv"),
            skip_venv_setup=True,
            subprocess_runner=runner,
        )
        # Should work without elf
        rc, out, err = tool("print('hello')")
        assert rc == 0


class TestInstallProjectToolStripped:
    def test_returns_tuple(self, tmp_path):
        (tmp_path / "setup.py").write_text("from setuptools import setup; setup()")
        runner = make_fake_subprocess_runner(rc=0, stdout="installed", stderr="")
        tool = InstallProjectTool(
            elfenv=Path("/tmp/fake_elfenv"),
            skip_venv_setup=True,
            subprocess_runner=runner,
        )
        result = tool(str(tmp_path))
        assert isinstance(result, tuple)
        assert len(result) == 3
        rc, out, err = result
        assert rc == 0

    def test_no_run_with_retries(self):
        tool = InstallProjectTool(
            elfenv=Path("/tmp/fake_elfenv"),
            skip_venv_setup=True,
            subprocess_runner=make_fake_subprocess_runner(),
        )
        assert not hasattr(tool, "_run_with_retries")

    def test_no_installable_project(self, tmp_path):
        runner = make_fake_subprocess_runner()
        tool = InstallProjectTool(
            elfenv=Path("/tmp/fake_elfenv"),
            skip_venv_setup=True,
            subprocess_runner=runner,
        )
        rc, out, err = tool(str(tmp_path))
        assert rc == 1
        assert "No installable project" in err


class TestStaticUtilitiesKept:
    def test_extract_code(self):
        assert RunSubprocessTool.extract_code("```python\nprint(1)\n```", "python") == "print(1)"

    def test_is_root(self):
        # Just verify the method exists and returns a bool
        assert isinstance(RunSubprocessTool.is_root(), bool)

    def test_is_permission_error(self):
        assert RunSubprocessTool._is_permission_error("Permission denied") is True
        assert RunSubprocessTool._is_permission_error("all good") is False
        assert RunSubprocessTool._is_permission_error("") is False
