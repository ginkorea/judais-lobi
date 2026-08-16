# tests/test_sandbox.py

import os
import resource
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest
from unittest.mock import patch, MagicMock

from core.tools.sandbox import (
    NoneSandbox,
    BwrapSandbox,
    get_sandbox,
    select_sandbox,
    build_sandbox_env,
    SandboxRunner,
    SandboxUnavailable,
    SANDBOX_ENV_VAR,
)
from core.tools.descriptors import SandboxProfile
from core.tools.run_python import RunPythonTool

#: A real filesystem that is not ``/tmp``.  ``/tmp`` is a tmpfs inside the
#: sandbox, so nothing under it can stand in for "a path the caller can
#: write and the sandbox will not let it".
REPO_ROOT = Path(__file__).resolve().parent.parent


class TestNoneSandbox:
    def test_simple_command(self):
        sandbox = NoneSandbox()
        rc, out, err = sandbox.execute("echo hello")
        assert rc == 0
        assert "hello" in out

    def test_list_command(self):
        sandbox = NoneSandbox()
        rc, out, err = sandbox.execute(["echo", "world"])
        assert rc == 0
        assert "world" in out

    def test_nonzero_exit(self):
        sandbox = NoneSandbox()
        rc, out, err = sandbox.execute("exit 42", timeout=5)
        assert rc == 42

    def test_timeout(self):
        sandbox = NoneSandbox()
        rc, out, err = sandbox.execute("sleep 10", timeout=1)
        assert rc == -1
        assert "timed out" in err.lower()

    def test_env_passthrough(self):
        sandbox = NoneSandbox()
        rc, out, err = sandbox.execute(
            "echo $TEST_SANDBOX_VAR",
            env={"TEST_SANDBOX_VAR": "injected"},
        )
        assert rc == 0
        assert "injected" in out

    def test_profile_ignored(self):
        """NoneSandbox ignores profile (no enforcement)."""
        sandbox = NoneSandbox()
        profile = SandboxProfile(max_cpu_seconds=1)
        rc, out, err = sandbox.execute("echo ok", profile=profile)
        assert rc == 0

    def test_stderr_captured(self):
        sandbox = NoneSandbox()
        rc, out, err = sandbox.execute("echo err >&2")
        assert "err" in err

    def test_conforms_to_protocol(self):
        """NoneSandbox satisfies SandboxRunner protocol."""
        sandbox = NoneSandbox()
        assert hasattr(sandbox, "execute")
        # Structural subtyping — just check the method signature works
        rc, out, err = sandbox.execute("true")
        assert rc == 0


class TestTheCallerOwnsShellMode:
    """``ToolBus`` hands the sandbox what the tool decided; it used not to.

    ``_build_sandbox_runner`` accepted ``shell=`` and ``executable=`` from
    ``executor.run_subprocess`` and discarded both, so every sandbox
    re-derived shell mode from ``isinstance(cmd, str)`` and hard-coded
    ``/bin/bash``. A tool configured with another interpreter got bash
    without being told, and an explicit ``shell=False`` meant nothing.
    Sandboxing a command must not change which command it is.
    """

    def test_shell_is_inferred_when_nobody_says(self):
        """A direct caller that never had an opinion keeps the old one."""
        rc, out, err = NoneSandbox().execute("echo inferred")
        assert rc == 0
        assert "inferred" in out

    def test_an_explicit_shell_false_is_honoured(self):
        """A string with shell=False is a program name, not a script."""
        rc, out, err = NoneSandbox().execute("echo not-a-shell", shell=False)
        assert rc == -1
        assert "not-a-shell" not in out

    def test_an_argv_stays_an_argv_whatever_the_flag_says(self):
        """Re-joining a split command into a script hands the quoting
        back to the shell, which is the bug, not the fix."""
        rc, out, err = NoneSandbox().execute(
            ["echo", "one two", "three"], shell=True,
        )
        assert rc == 0
        assert out == "one two three"

    def test_the_callers_interpreter_is_used(self):
        rc, out, err = NoneSandbox().execute(
            "echo $0", shell=True, executable="/bin/sh",
        )
        assert rc == 0
        assert out.strip() == "/bin/sh"

    def test_bash_is_only_the_fallback(self):
        rc, out, err = NoneSandbox().execute("echo $0", shell=True)
        assert out.strip() == "/bin/bash"

    @patch("core.tools.sandbox.shutil.which", return_value="/usr/bin/bwrap")
    @patch("core.tools.sandbox.subprocess.run")
    def test_bwrap_wraps_with_the_callers_interpreter(self, mock_run, mock_which):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        BwrapSandbox().execute("echo hi", shell=True, executable="/bin/sh")
        argv = mock_run.call_args[0][0]
        assert argv[-3:] == ["/bin/sh", "-c", "echo hi"]

    @patch("core.tools.sandbox.shutil.which", return_value="/usr/bin/bwrap")
    @patch("core.tools.sandbox.subprocess.run")
    def test_bwrap_does_not_invent_a_shell_for_an_argv(self, mock_run, mock_which):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        BwrapSandbox().execute(["echo", "hi"], shell=True)
        argv = mock_run.call_args[0][0]
        assert argv[-2:] == ["echo", "hi"]
        assert "-c" not in argv

    @patch("core.tools.sandbox.shutil.which", return_value="/usr/bin/bwrap")
    @patch("core.tools.sandbox.subprocess.run")
    def test_bwrap_runs_a_string_as_a_program_when_told_not_to_shell(
        self, mock_run, mock_which,
    ):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        BwrapSandbox().execute("/usr/bin/true", shell=False)
        argv = mock_run.call_args[0][0]
        assert argv[-1] == "/usr/bin/true"
        assert "-c" not in argv


class TestTheBusForwardsWhatTheToolDecided:
    def test_the_sandbox_runner_passes_shell_and_executable_through(self):
        from core.tools.bus import ToolBus
        from core.tools.descriptors import SandboxProfile as _Profile

        seen = {}

        class RecordingSandbox:
            def execute(self, cmd, *, profile=None, timeout=None, env=None,
                        shell=None, executable=None, stdin=None):
                seen.update(cmd=cmd, shell=shell, executable=executable,
                            timeout=timeout, profile=profile, stdin=stdin)
                return 0, "ok", ""

        profile = _Profile()
        bus = ToolBus(sandbox=RecordingSandbox())
        runner = bus._build_sandbox_runner(profile)
        runner("pytest -q", shell=True, timeout=30, executable="/bin/zsh")
        assert seen == {
            "cmd": "pytest -q", "shell": True, "executable": "/bin/zsh",
            "timeout": 30, "profile": profile, "stdin": None,
        }

    def test_the_sandbox_runner_threads_stdin_through(self):
        """``run_python`` hands its program to the runner as stdin; a runner
        that dropped it would send the interpreter an empty program."""
        from core.tools.bus import ToolBus
        from core.tools.descriptors import SandboxProfile as _Profile

        seen = {}

        class RecordingSandbox:
            def execute(self, cmd, *, profile=None, timeout=None, env=None,
                        shell=None, executable=None, stdin=None):
                seen["stdin"] = stdin
                return 0, "ok", ""

        bus = ToolBus(sandbox=RecordingSandbox())
        runner = bus._build_sandbox_runner(_Profile())
        runner(["python", "-"], stdin="print('hi')")
        assert seen["stdin"] == "print('hi')"

    def test_a_callers_deadline_is_a_ceiling_on_the_tools_own_timeout(self):
        """A mission with a wall-clock budget must not overshoot it by a
        tool's full 120 s. `min`, never `max`: a caller with eight seconds
        left must not be able to EXTEND a tool that bounds itself at five."""
        from core.tools.bus import ToolBus
        from core.tools.descriptors import SandboxProfile as _Profile

        seen = []

        class RecordingSandbox:
            def execute(self, cmd, *, profile=None, timeout=None, env=None,
                        shell=None, executable=None, stdin=None):
                seen.append(timeout)
                return 0, "ok", ""

        bus = ToolBus(sandbox=RecordingSandbox())
        bus._build_sandbox_runner(_Profile(), 7.4)("x", timeout=120)
        bus._build_sandbox_runner(_Profile(), 900)("x", timeout=5)
        bus._build_sandbox_runner(_Profile(), None)("x", timeout=30)
        assert seen == [7, 5, 30]

    def test_a_spent_deadline_still_leaves_a_second_and_not_zero(self):
        """Zero means "no timeout" to most of the subprocess layer, which is
        the opposite of what a spent budget is asking for."""
        from core.tools.bus import ToolBus
        from core.tools.descriptors import SandboxProfile as _Profile

        seen = []

        class RecordingSandbox:
            def execute(self, cmd, *, profile=None, timeout=None, **_kw):
                seen.append(timeout)
                return 0, "ok", ""

        bus = ToolBus(sandbox=RecordingSandbox())
        bus._build_sandbox_runner(_Profile(), 0.0)("x", timeout=120)
        assert seen == [1]

    def test_the_bus_builds_the_child_env_from_the_profile(self, monkeypatch):
        """The bus hands ``execute`` an env built from the profile's
        allow-list — the one place the child's environment is decided — so
        neither backend re-reads ``os.environ`` on its own."""
        from core.tools.bus import ToolBus
        from core.tools.descriptors import SandboxProfile as _Profile

        monkeypatch.setenv("PATH", "/usr/bin")
        monkeypatch.setenv("SECRET_TOKEN", "leak-me")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-passed")

        seen = {}

        class RecordingSandbox:
            def execute(self, cmd, *, profile=None, timeout=None, env=None,
                        shell=None, executable=None, stdin=None):
                seen["env"] = env
                return 0, "ok", ""

        bus = ToolBus(sandbox=RecordingSandbox())
        runner = bus._build_sandbox_runner(
            _Profile(env_passthrough=("OPENAI_API_KEY",)))
        runner("env", shell=True)
        assert seen["env"]["PATH"] == "/usr/bin"
        assert seen["env"]["OPENAI_API_KEY"] == "sk-passed"
        assert "SECRET_TOKEN" not in seen["env"]


class TestBwrapSandboxArgBuilding:
    @patch("core.tools.sandbox.shutil.which", return_value="/usr/bin/bwrap")
    def test_basic_args(self, mock_which):
        sandbox = BwrapSandbox()
        profile = SandboxProfile()
        args = sandbox._build_bwrap_args(profile)
        assert args[0] == "bwrap"
        assert "--unshare-net" in args
        assert "--ro-bind" in args
        assert "--proc" in args
        assert "--dev" in args
        assert "--tmpfs" in args

    @patch("core.tools.sandbox.shutil.which", return_value="/usr/bin/bwrap")
    def test_workspace_writable(self, mock_which):
        sandbox = BwrapSandbox()
        profile = SandboxProfile(workspace_writable=True)
        args = sandbox._build_bwrap_args(profile)
        assert "--bind" in args

    @patch("core.tools.sandbox.shutil.which", return_value="/usr/bin/bwrap")
    def test_workspace_not_writable(self, mock_which):
        sandbox = BwrapSandbox()
        profile = SandboxProfile(workspace_writable=False)
        args = sandbox._build_bwrap_args(profile)
        # Should not have --bind for cwd (only --ro-bind for /)
        bind_indices = [i for i, a in enumerate(args) if a == "--bind"]
        assert len(bind_indices) == 0

    @patch("core.tools.sandbox.shutil.which", return_value="/usr/bin/bwrap")
    def test_write_paths(self, mock_which):
        sandbox = BwrapSandbox()
        profile = SandboxProfile(
            workspace_writable=False,
            allowed_write_paths=["/tmp/output"],
        )
        args = sandbox._build_bwrap_args(profile)
        idx = args.index("/tmp/output")
        assert args[idx - 1] == "--bind"

    @patch("core.tools.sandbox.shutil.which", return_value="/usr/bin/bwrap")
    def test_read_paths(self, mock_which):
        sandbox = BwrapSandbox()
        profile = SandboxProfile(
            workspace_writable=False,
            allowed_read_paths=["/etc/config"],
        )
        args = sandbox._build_bwrap_args(profile)
        assert "/etc/config" in args


class TestBwrapAvailability:
    @patch("core.tools.sandbox.shutil.which", return_value=None)
    def test_not_available(self, mock_which):
        assert BwrapSandbox.is_available() is False

    @patch("core.tools.sandbox.shutil.which", return_value="/usr/bin/bwrap")
    def test_available(self, mock_which):
        assert BwrapSandbox.is_available() is True

    @patch("core.tools.sandbox.shutil.which", return_value=None)
    def test_init_raises_if_not_available(self, mock_which):
        with pytest.raises(FileNotFoundError, match="bwrap not found"):
            BwrapSandbox()


class TestGetSandbox:
    """The thin backward-compatible wrapper. Its historic ``"none"`` default
    stays ``"none"`` — it does not inherit :func:`select_sandbox`'s
    on-by-default auto path, so an old caller of ``get_sandbox()`` is not
    silently switched into a sandbox it never asked for."""

    def test_default_returns_none_sandbox(self):
        assert isinstance(get_sandbox(), NoneSandbox)

    def test_explicit_none(self):
        assert isinstance(get_sandbox("none"), NoneSandbox)

    @patch("core.tools.sandbox.BwrapSandbox.is_available", return_value=False)
    def test_bwrap_requested_but_absent_now_refuses(self, mock_avail):
        """The silent downgrade is gone: asking for bwrap by name on a host
        without it raises rather than handing back no isolation at all."""
        with pytest.raises(SandboxUnavailable):
            get_sandbox("bwrap")

    @patch("core.tools.sandbox.shutil.which", return_value="/usr/bin/bwrap")
    def test_bwrap_when_available(self, mock_which):
        assert isinstance(get_sandbox("bwrap"), BwrapSandbox)


class TestSelectSandbox:
    """The one owner of the decision: flag > env > auto.

    ``select_sandbox`` is what the CLI, a library caller and these tests all
    reach, so the sandbox a mission runs under is one function's verdict and
    not four.
    """

    @patch("core.tools.sandbox.shutil.which", return_value="/usr/bin/bwrap")
    def test_auto_picks_bwrap_when_available(self, mock_which, monkeypatch):
        monkeypatch.delenv(SANDBOX_ENV_VAR, raising=False)
        runner, name = select_sandbox()
        assert isinstance(runner, BwrapSandbox)
        assert name == "bwrap"

    @patch("core.tools.sandbox.shutil.which", return_value=None)
    def test_auto_falls_to_none_without_bwrap(self, mock_which, monkeypatch):
        monkeypatch.delenv(SANDBOX_ENV_VAR, raising=False)
        runner, name = select_sandbox()
        assert isinstance(runner, NoneSandbox)
        assert name == "none"

    @patch("core.tools.sandbox.shutil.which", return_value="/usr/bin/bwrap")
    def test_explicit_none_beats_an_available_bwrap(self, mock_which):
        runner, name = select_sandbox("none")
        assert isinstance(runner, NoneSandbox)
        assert name == "none"

    @patch("core.tools.sandbox.shutil.which", return_value="/usr/bin/bwrap")
    def test_the_flag_beats_the_env(self, mock_which, monkeypatch):
        """`--unsandboxed` resolves to ``"none"`` and wins over an env that
        forced bwrap: a passed request never reaches the env lookup."""
        monkeypatch.setenv(SANDBOX_ENV_VAR, "bwrap")
        runner, name = select_sandbox("none")
        assert name == "none"

    @patch("core.tools.sandbox.shutil.which", return_value="/usr/bin/bwrap")
    def test_the_env_is_read_when_no_flag(self, mock_which, monkeypatch):
        monkeypatch.setenv(SANDBOX_ENV_VAR, "none")
        runner, name = select_sandbox(None)
        assert name == "none"

    @patch("core.tools.sandbox.shutil.which", return_value="/usr/bin/bwrap")
    def test_a_word_that_is_neither_is_refused_not_guessed_at(
            self, mock_which, monkeypatch):
        """``JUDAIS_LOBI_SANDBOX=firejail`` is somebody choosing something;
        falling through to the auto path would choose for them in silence."""
        from core.tools.sandbox import SandboxUnavailable
        monkeypatch.setenv(SANDBOX_ENV_VAR, "firejail")
        with pytest.raises(SandboxUnavailable, match="firejail"):
            select_sandbox(None)
        with pytest.raises(SandboxUnavailable, match="'bwrap' or 'none'"):
            select_sandbox("docker")

    @patch("core.tools.sandbox.BwrapSandbox.is_available", return_value=False)
    def test_forcing_bwrap_without_it_refuses_with_the_fix_named(self, mock_avail):
        with pytest.raises(SandboxUnavailable) as exc:
            select_sandbox("bwrap")
        assert "--unsandboxed" in str(exc.value)
        assert "bubblewrap" in str(exc.value)


class TestBuildSandboxEnv:
    """The child sees the allow-list plus the profile's names, and nothing
    else the host exported."""

    def test_the_allow_list_is_forwarded(self, monkeypatch):
        monkeypatch.setenv("PATH", "/usr/bin")
        monkeypatch.setenv("HOME", "/home/x")
        env = build_sandbox_env(SandboxProfile())
        assert env["PATH"] == "/usr/bin"
        assert env["HOME"] == "/home/x"

    def test_a_secret_the_host_set_is_left_behind(self, monkeypatch):
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "leak-me")
        env = build_sandbox_env(SandboxProfile())
        assert "AWS_SECRET_ACCESS_KEY" not in env

    def test_lc_variables_are_matched_by_prefix(self, monkeypatch):
        monkeypatch.setenv("LC_ALL", "C.UTF-8")
        env = build_sandbox_env(SandboxProfile())
        assert env["LC_ALL"] == "C.UTF-8"

    def test_the_profile_names_are_added(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
        env = build_sandbox_env(SandboxProfile(env_passthrough=("OPENAI_API_KEY",)))
        assert env["OPENAI_API_KEY"] == "sk-x"

    def test_a_named_variable_the_host_never_set_is_simply_absent(self, monkeypatch):
        monkeypatch.delenv("HTTPS_PROXY", raising=False)
        env = build_sandbox_env(SandboxProfile(env_passthrough=("HTTPS_PROXY",)))
        assert "HTTPS_PROXY" not in env


class TestBothBackendsHonourTheSameEnvRule:
    """The env rule stated once: the child's environment is exactly what the
    caller passed; ``None`` inherits the parent's. Both backends obey it, so
    a profile means the same thing on either."""

    def test_none_sandbox_uses_exactly_the_env_it_was_given(self):
        rc, out, err = NoneSandbox().execute(
            "echo $ONLY_THIS", shell=True, env={"ONLY_THIS": "here"},
        )
        assert rc == 0
        assert out == "here"

    def test_none_sandbox_does_not_add_a_host_secret(self, monkeypatch):
        monkeypatch.setenv("HOST_SECRET", "leak")
        rc, out, err = NoneSandbox().execute(
            "echo secret=[$HOST_SECRET]", shell=True,
            env=build_sandbox_env(SandboxProfile()),
        )
        assert rc == 0
        assert out == "secret=[]"

    @pytest.mark.skipif(shutil.which("bwrap") is None,
                        reason="bwrap is not installed on this host")
    def test_bwrap_shows_only_the_allow_list_plus_profile_names(self, monkeypatch):
        monkeypatch.setenv("HOST_SECRET", "leak")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
        env = build_sandbox_env(SandboxProfile(env_passthrough=("OPENAI_API_KEY",)))
        rc, out, err = BwrapSandbox().execute(
            ["python3", "-c", "import os; print(sorted(os.environ))"],
            profile=SandboxProfile(), env=env, timeout=20,
        )
        assert rc == 0, err
        names = set(eval(out))
        assert "HOST_SECRET" not in names
        assert "OPENAI_API_KEY" in names
        assert "PATH" in names

    def test_none_sandbox_shows_only_the_allow_list_plus_profile_names(self, monkeypatch):
        monkeypatch.setenv("HOST_SECRET", "leak")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
        env = build_sandbox_env(SandboxProfile(env_passthrough=("OPENAI_API_KEY",)))
        rc, out, err = NoneSandbox().execute(
            [sys.executable, "-c", "import os; print(sorted(os.environ))"],
            env=env, timeout=20,
        )
        assert rc == 0, err
        names = set(eval(out))
        assert "HOST_SECRET" not in names
        assert "OPENAI_API_KEY" in names
        assert "PATH" in names


class TestBwrapNetworkProfile:
    """``--unshare-net`` used to be unconditional.

    Which is the right default and the wrong *rule*: it made the sandbox
    and ``perform_web_search`` mutually exclusive, so switching the
    sandbox on by default would have taken the web tools out without
    anything in the run saying so.
    """

    @patch("core.tools.sandbox.shutil.which", return_value="/usr/bin/bwrap")
    def test_denied_by_default(self, mock_which):
        args = BwrapSandbox()._build_bwrap_args(SandboxProfile())
        assert "--unshare-net" in args
        assert "--share-net" not in args

    @patch("core.tools.sandbox.shutil.which", return_value="/usr/bin/bwrap")
    def test_allowed_when_the_profile_says_so(self, mock_which):
        args = BwrapSandbox()._build_bwrap_args(SandboxProfile(allow_network=True))
        assert "--share-net" in args
        assert "--unshare-net" not in args


class TestBwrapRlimits:
    """bwrap has no rlimit flags, so they are set on the bwrap process.

    ``setrlimit`` survives ``execve``, so a limit placed on the wrapper is
    a limit on the payload.  These tests patch ``resource`` rather than
    call the real thing: a ``preexec_fn`` invoked in-process would lower
    *this* test run's own limits, and a pytest that has capped its own
    address space does not report the fact politely.
    """

    def _built(self, profile):
        with patch("core.tools.sandbox.shutil.which", return_value="/usr/bin/bwrap"):
            return BwrapSandbox()._rlimit_preexec(profile)

    def _applied(self, profile, hard=None):
        hard = resource.RLIM_INFINITY if hard is None else hard
        seen = {}
        with patch.object(resource, "getrlimit", return_value=(hard, hard)), \
             patch.object(resource, "setrlimit",
                          side_effect=lambda which, pair: seen.__setitem__(which, pair)):
            preexec = self._built(profile)
            assert preexec is not None
            preexec()
        return seen

    def test_a_profile_asking_for_nothing_gets_no_preexec(self):
        assert self._built(SandboxProfile()) is None

    def test_a_profile_asking_for_one_limit_gets_a_preexec(self):
        assert self._built(SandboxProfile(max_cpu_seconds=5)) is not None

    def test_every_field_reaches_its_rlimit(self):
        seen = self._applied(SandboxProfile(
            max_cpu_seconds=7,
            max_memory_bytes=123_456_789,
            max_processes=4_096,
        ))
        assert seen[resource.RLIMIT_CPU] == (7, 7)
        assert seen[resource.RLIMIT_AS] == (123_456_789, 123_456_789)
        assert seen[resource.RLIMIT_NPROC] == (4_096, 4_096)

    def test_a_request_above_the_hard_limit_is_clamped(self):
        """An unprivileged ``setrlimit`` above the hard limit raises, and
        it would raise between the fork and the exec, where a traceback
        goes nowhere anybody reads."""
        seen = self._applied(SandboxProfile(max_memory_bytes=1 << 60), hard=4096)
        assert seen[resource.RLIMIT_AS] == (4096, 4096)

    def test_a_request_below_the_hard_limit_is_left_alone(self):
        seen = self._applied(SandboxProfile(max_memory_bytes=2048), hard=4096)
        assert seen[resource.RLIMIT_AS] == (2048, 2048)


#: Everything below runs the actual binary.  The arg-building tests above
#: assert what we *say* to bwrap; only these assert what bwrap does with
#: it, which is the half that had never been checked and the half that
#: decides whether the sandbox can be switched on.
requires_bwrap = pytest.mark.skipif(
    shutil.which("bwrap") is None,
    reason="bwrap is not installed on this host",
)

#: Documentation-only (RFC 5737), so it looks routable and is routed
#: nowhere.  Inside an unshared namespace it is unreachable instantly;
#: loopback is not, because bwrap brings ``lo`` up.
UNREACHABLE_ADDRESS = "192.0.2.1"


@requires_bwrap
class TestBwrapForReal:
    def test_a_command_runs_at_all(self):
        rc, out, err = BwrapSandbox().execute(
            ["python3", "-c", "print('inside')"],
            profile=SandboxProfile(),
            timeout=20,
        )
        assert rc == 0, err
        assert out == "inside"

    def test_the_interpreter_running_these_tests_runs_inside(self):
        """A venv's python lives under ``$HOME``, not under ``/usr``.

        The bind set is ``--ro-bind / /`` so it is reachable — but that is
        a property of the bind set and not an obvious one, and a tool that
        shells out to ``sys.executable`` is the common case rather than an
        exotic one.
        """
        rc, out, err = BwrapSandbox().execute(
            [sys.executable, "-c", "import sys; print(sys.executable)"],
            profile=SandboxProfile(),
            timeout=20,
        )
        assert rc == 0, err
        assert out == sys.executable

    def test_a_shell_string_runs_inside(self):
        rc, out, err = BwrapSandbox().execute(
            "echo shell-inside", profile=SandboxProfile(), timeout=20,
        )
        assert rc == 0, err
        assert out == "shell-inside"

    def test_tmp_is_a_private_tmpfs(self):
        with tempfile.NamedTemporaryFile(dir="/tmp", suffix=".probe") as host_file:
            rc, out, err = BwrapSandbox().execute(
                ["python3", "-c",
                 f"import os; print('VISIBLE' if os.path.exists({host_file.name!r})"
                 " else 'HIDDEN')"],
                profile=SandboxProfile(),
                timeout=20,
            )
            assert rc == 0, err
            assert out == "HIDDEN"
            assert os.path.exists(host_file.name)  # and untouched on the host

    def test_the_working_directory_is_writable(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        rc, out, err = BwrapSandbox().execute(
            ["python3", "-c", "open('written-inside.txt', 'w').write('yes')"],
            profile=SandboxProfile(workspace_writable=True),
            timeout=20,
        )
        assert rc == 0, err
        assert (tmp_path / "written-inside.txt").read_text() == "yes"

    def test_a_path_outside_the_workspace_is_read_only(self, tmp_path, monkeypatch):
        """The promise is *write* isolation: readable wherever the caller
        could read, changeable only where the profile said.

        The file has to live outside ``/tmp`` — under ``/tmp`` it is not
        read-only inside the namespace, it is *absent*, and a test that
        accepted ``FileNotFoundError`` would pass on a sandbox that had
        stopped binding the root read-only at all.
        """
        outside_dir = Path(tempfile.mkdtemp(dir=str(REPO_ROOT), prefix=".sandbox-probe-"))
        try:
            outside = outside_dir / "outside.txt"
            outside.write_text("original")
            monkeypatch.chdir(tmp_path)
            rc, out, err = BwrapSandbox().execute(
                ["python3", "-c",
                 f"print(open({str(outside)!r}).read().strip()); "
                 f"open({str(outside)!r}, 'w').write('overwritten')"],
                profile=SandboxProfile(workspace_writable=True),
                timeout=20,
            )
            assert rc != 0
            assert "original" in out
            assert "Read-only file system" in err
            assert outside.read_text() == "original"
        finally:
            shutil.rmtree(outside_dir, ignore_errors=True)

    def test_an_allowed_write_path_is_writable(self, tmp_path, monkeypatch):
        target = tmp_path / "granted"
        target.mkdir()
        workdir = tmp_path / "work"
        workdir.mkdir()
        monkeypatch.chdir(workdir)
        rc, out, err = BwrapSandbox().execute(
            ["python3", "-c", f"open({str(target / 'ok.txt')!r}, 'w').write('yes')"],
            profile=SandboxProfile(allowed_write_paths=[str(target)]),
            timeout=20,
        )
        assert rc == 0, err
        assert (target / "ok.txt").read_text() == "yes"

    def test_the_network_is_denied_by_default(self):
        rc, out, err = BwrapSandbox().execute(
            ["python3", "-c", "import socket; socket.create_connection("
             f"({UNREACHABLE_ADDRESS!r}, 80), timeout=3)"],
            profile=SandboxProfile(),
            timeout=30,
        )
        assert rc != 0
        assert "Network is unreachable" in err

    def test_only_loopback_exists_when_the_network_is_denied(self):
        rc, out, err = BwrapSandbox().execute(
            ["python3", "-c",
             "import socket; print(sorted(n for _, n in socket.if_nameindex()))"],
            profile=SandboxProfile(),
            timeout=20,
        )
        assert rc == 0, err
        assert out == "['lo']"

    @pytest.mark.skipif(
        len(socket.if_nameindex()) < 2,
        reason="this host has no interface but loopback to share",
    )
    def test_the_hosts_interfaces_are_there_when_the_profile_allows_it(self):
        rc, out, err = BwrapSandbox().execute(
            ["python3", "-c",
             "import socket; print(sorted(n for _, n in socket.if_nameindex()))"],
            profile=SandboxProfile(allow_network=True),
            timeout=20,
        )
        assert rc == 0, err
        assert out == str(sorted(n for _, n in socket.if_nameindex()))

    def test_the_memory_limit_is_enforced(self):
        rc, out, err = BwrapSandbox().execute(
            ["python3", "-c", "x = bytearray(256 * 1024 * 1024); print(len(x))"],
            profile=SandboxProfile(max_memory_bytes=64 * 1024 * 1024),
            timeout=30,
        )
        assert rc != 0
        assert "MemoryError" in err

    def test_the_memory_limit_does_not_break_bwrap_itself(self):
        """bwrap runs inside the limit it is asked to impose."""
        rc, out, err = BwrapSandbox().execute(
            ["python3", "-c", "print('still-runs')"],
            profile=SandboxProfile(max_memory_bytes=64 * 1024 * 1024),
            timeout=30,
        )
        assert rc == 0, err
        assert out == "still-runs"

    def test_the_cpu_limit_kills_a_runaway(self):
        """Not the subprocess timeout: this has to end *before* it."""
        started = time.monotonic()
        rc, out, err = BwrapSandbox().execute(
            ["python3", "-c", "i = 0\nwhile True: i += 1"],
            profile=SandboxProfile(max_cpu_seconds=1),
            timeout=30,
        )
        assert rc != 0
        assert "timed out" not in err.lower()
        assert time.monotonic() - started < 20

    def test_the_limits_are_the_ones_the_profile_asked_for(self):
        rc, out, err = BwrapSandbox().execute(
            ["python3", "-c",
             "import resource; print(resource.getrlimit(resource.RLIMIT_AS)[0],"
             " resource.getrlimit(resource.RLIMIT_CPU)[0])"],
            profile=SandboxProfile(
                max_memory_bytes=256 * 1024 * 1024, max_cpu_seconds=9,
            ),
            timeout=20,
        )
        assert rc == 0, err
        assert out == f"{256 * 1024 * 1024} 9"

    def test_no_limits_leaves_the_inherited_ones(self):
        expected = resource.getrlimit(resource.RLIMIT_AS)[0]
        rc, out, err = BwrapSandbox().execute(
            ["python3", "-c",
             "import resource; print(resource.getrlimit(resource.RLIMIT_AS)[0])"],
            profile=SandboxProfile(),
            timeout=20,
        )
        assert rc == 0, err
        assert out == str(expected)


def _python_invocation(code: str):
    """The ``(argv, stdin)`` :class:`RunPythonTool` builds, captured rather
    than guessed.

    Guessing it would leave these tests passing against a tool that had
    gone back to a temp file — or back to ``-c`` — the day somebody changed
    it back. The program travels on stdin now, so both halves are captured.
    """
    seen = {}

    def capture(cmd, *, shell=False, timeout=None, executable=None, stdin=None):
        seen["cmd"] = cmd
        seen["stdin"] = stdin
        return 0, "", ""

    tool = RunPythonTool(
        elfenv=Path(sys.prefix),
        skip_venv_setup=True,
        subprocess_runner=capture,
    )
    tool(code)
    return seen["cmd"], seen["stdin"]


#: ``RunPythonTool`` runs ``<elfenv>/bin/python``.  Standing the running
#: venv in for the elfenv is what makes these end-to-end instead of a
#: second mock.
_HAS_PREFIX_PYTHON = (Path(sys.prefix) / "bin" / "python").exists()
requires_prefix_python = pytest.mark.skipif(
    not _HAS_PREFIX_PYTHON,
    reason="no <prefix>/bin/python to stand in for the elfenv interpreter",
)


class TestRunPythonCommandUnderTheSandboxes:
    """Two bugs this exists for. The tool wrote the script to a host temp
    file and passed its *path*, and ``/tmp`` inside the sandbox is a fresh
    tmpfs, so every program came back ``can't open file '/tmp/tmpXXXX.py'``.
    0.8.2 moved it to ``-c <code>``, which put the whole program in ``argv``
    where any process on the host reads it out of ``ps`` — the leak class
    0.8.2 had just fixed for the model key. The program is on stdin now:
    ``argv`` is ``[python, "-"]`` and nothing else.
    """

    def test_the_command_carries_the_code_on_stdin_not_in_argv(self):
        cmd, stdin = _python_invocation("print('carried')")
        assert cmd[1] == "-"
        assert len(cmd) == 2
        assert stdin == "print('carried')"
        assert not any(str(part).endswith(".py") for part in cmd)
        assert "print('carried')" not in " ".join(str(p) for p in cmd)

    @requires_prefix_python
    def test_none_sandbox_runs_it(self):
        cmd, stdin = _python_invocation("print('temp-free')")
        rc, out, err = NoneSandbox().execute(cmd, stdin=stdin, timeout=20)
        assert rc == 0, err
        assert out == "temp-free"

    @requires_bwrap
    @requires_prefix_python
    def test_bwrap_runs_it(self):
        cmd, stdin = _python_invocation("print('temp-free')")
        rc, out, err = BwrapSandbox().execute(
            cmd, stdin=stdin, profile=SandboxProfile(), timeout=20,
        )
        assert rc == 0, err
        assert out == "temp-free"

    @requires_bwrap
    def test_the_shape_it_replaced_would_have_failed(self):
        """The regression, kept executable: a host temp path is not a path
        inside the namespace."""
        with tempfile.NamedTemporaryFile(
            dir="/tmp", suffix=".py", mode="w", delete=False,
        ) as script:
            script.write("print('from a temp file')\n")
            path = script.name
        try:
            rc, out, err = BwrapSandbox().execute(
                ["python3", path], profile=SandboxProfile(), timeout=20,
            )
            assert rc != 0
            assert "from a temp file" not in out
            assert path in err
        finally:
            os.unlink(path)
