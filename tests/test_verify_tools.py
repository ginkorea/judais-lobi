# tests/test_verify_tools.py — VerifyTool tests

import pytest
from core.tools.verify_tools import VerifyTool


def make_runner(rc=0, stdout="", stderr=""):
    def runner(cmd, *, shell=False, timeout=None, executable=None):
        return rc, stdout, stderr
    return runner


@pytest.fixture
def verify():
    return VerifyTool(subprocess_runner=make_runner(0, "ok", ""))


class TestVerifyDefaults:
    def test_lint_default(self, verify):
        rc, out, err = verify("lint")
        assert rc == 0

    def test_test_default(self, verify):
        rc, out, err = verify("test")
        assert rc == 0

    def test_typecheck_default(self, verify):
        rc, out, err = verify("typecheck")
        assert rc == 0

    def test_format_default(self, verify):
        rc, out, err = verify("format")
        assert rc == 0

    def test_unknown_action(self, verify):
        rc, out, err = verify("explode")
        assert rc == 1
        assert "unknown" in err.lower()


class TestVerifyConfigOverride:
    def test_override_lint(self):
        config = {"verification": {"lint": "flake8 ."}}
        # Capture the command that gets run
        captured = {}
        def capturing_runner(cmd, *, shell=False, timeout=None, executable=None):
            captured["cmd"] = cmd
            return 0, "ok", ""
        vt = VerifyTool(config=config, subprocess_runner=capturing_runner)
        rc, out, err = vt("lint")
        assert rc == 0
        assert captured["cmd"] == "flake8 ."

    def test_override_test(self):
        config = {"verification": {"test": "python -m unittest discover"}}
        captured = {}
        def capturing_runner(cmd, *, shell=False, timeout=None, executable=None):
            captured["cmd"] = cmd
            return 0, "", ""
        vt = VerifyTool(config=config, subprocess_runner=capturing_runner)
        vt("test")
        assert captured["cmd"] == "python -m unittest discover"

    def test_partial_override_uses_defaults(self):
        config = {"verification": {"lint": "custom_lint"}}
        captured = {}
        def capturing_runner(cmd, *, shell=False, timeout=None, executable=None):
            captured["cmd"] = cmd
            return 0, "", ""
        vt = VerifyTool(config=config, subprocess_runner=capturing_runner)
        vt("test")  # not overridden
        assert captured["cmd"] == "pytest"

    def test_empty_config(self):
        captured = {}
        def capturing_runner(cmd, *, shell=False, timeout=None, executable=None):
            captured["cmd"] = cmd
            return 0, "", ""
        vt = VerifyTool(config={}, subprocess_runner=capturing_runner)
        vt("lint")
        assert captured["cmd"] == "ruff check ."

    def test_none_config(self):
        captured = {}
        def capturing_runner(cmd, *, shell=False, timeout=None, executable=None):
            captured["cmd"] = cmd
            return 0, "", ""
        vt = VerifyTool(config=None, subprocess_runner=capturing_runner)
        vt("format")
        assert captured["cmd"] == "ruff format --check ."


class TestVerifyFailure:
    def test_command_failure_returns_error(self):
        vt = VerifyTool(subprocess_runner=make_runner(1, "", "lint errors"))
        rc, out, err = vt("lint")
        assert rc == 1
        assert err == "lint errors"
