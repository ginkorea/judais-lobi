# tests/test_verify_tools.py — VerifyTool tests

import sys

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
        vt = VerifyTool(config=config, subprocess_runner=capturing_runner,
                        python="/venv/bin/python")
        vt("test")  # not overridden
        assert captured["cmd"] == "/venv/bin/python -m pytest"

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


def make_capturing_runner():
    """A runner that keeps the command it was handed. `(captured, runner)`."""
    captured = {}

    def runner(cmd, *, shell=False, timeout=None, executable=None):
        captured["cmd"] = cmd
        return 0, "", ""

    return captured, runner


class TestThePythonToken:
    """`{python}` is the answer to `pytest: command not found`.

    The verify command is the one command a *repository* authors, and the
    agent runs it somewhere the repository has never seen — inside bwrap,
    out of a wheel in a venv nobody activated, from a pool worker. A bare
    `pytest` depends on that venv's `bin` being on PATH; `{python} -m
    pytest` depends on nothing.
    """

    def test_the_default_test_command_names_an_interpreter(self):
        captured, runner = make_capturing_runner()
        VerifyTool(subprocess_runner=runner, python="/venv/bin/python")("test")
        assert captured["cmd"] == "/venv/bin/python -m pytest"

    def test_the_default_typecheck_command_names_an_interpreter(self):
        captured, runner = make_capturing_runner()
        VerifyTool(subprocess_runner=runner,
                   python="/venv/bin/python")("typecheck")
        assert captured["cmd"] == "/venv/bin/python -m mypy ."

    def test_a_repository_may_write_the_token_itself(self):
        """The expansion happens in what the repository configured, too.

        Otherwise the token would work only in the defaults — the half a
        repository cannot reach — and a repository that writes `{python} -m
        pytest -q` would get it back verbatim, which is a command no shell
        can run.
        """
        captured, runner = make_capturing_runner()
        VerifyTool(config={"verification": {"test": "{python} -m pytest -q"}},
                   subprocess_runner=runner,
                   python="/venv/bin/python")("test")
        assert captured["cmd"] == "/venv/bin/python -m pytest -q"

    def test_an_interpreter_path_with_a_space_is_quoted(self):
        captured, runner = make_capturing_runner()
        VerifyTool(subprocess_runner=runner,
                   python="/opt/my venv/bin/python")("test")
        assert captured["cmd"] == "'/opt/my venv/bin/python' -m pytest"

    def test_other_braces_in_a_command_are_left_alone(self):
        """A real verify command carries braces of its own.

        `str.format` would raise `KeyError: 'print $1'` on this one, which
        is somebody's working configuration refusing to run after an
        upgrade.
        """
        captured, runner = make_capturing_runner()
        VerifyTool(
            config={"verification": {
                "lint": "grep -c def *.py | awk -F: '{s+=$2} END {print s}'",
            }},
            subprocess_runner=runner,
        )("lint")
        assert captured["cmd"] == (
            "grep -c def *.py | awk -F: '{s+=$2} END {print s}'")

    def test_the_interpreter_defaults_to_the_running_one(self):
        captured, runner = make_capturing_runner()
        VerifyTool(subprocess_runner=runner)("test")
        assert captured["cmd"] == f"{sys.executable} -m pytest"
