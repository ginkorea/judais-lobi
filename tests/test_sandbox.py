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

from core.tools.sandbox import NoneSandbox, BwrapSandbox, get_sandbox, SandboxRunner
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
    def test_default_returns_none_sandbox(self):
        sandbox = get_sandbox()
        assert isinstance(sandbox, NoneSandbox)

    def test_explicit_none(self):
        sandbox = get_sandbox("none")
        assert isinstance(sandbox, NoneSandbox)

    @patch("core.tools.sandbox.BwrapSandbox.is_available", return_value=False)
    def test_bwrap_fallback(self, mock_avail):
        sandbox = get_sandbox("bwrap")
        assert isinstance(sandbox, NoneSandbox)

    @patch("core.tools.sandbox.shutil.which", return_value="/usr/bin/bwrap")
    def test_bwrap_when_available(self, mock_which):
        sandbox = get_sandbox("bwrap")
        assert isinstance(sandbox, BwrapSandbox)


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


def _python_command(code: str):
    """The argv :class:`RunPythonTool` builds, captured rather than guessed.

    Guessing it would leave these tests passing against a tool that had
    gone back to a temp file the day somebody changed it back.
    """
    seen = {}

    def capture(cmd, *, shell=False, timeout=None, executable=None):
        seen["cmd"] = cmd
        return 0, "", ""

    tool = RunPythonTool(
        elfenv=Path(sys.prefix),
        skip_venv_setup=True,
        subprocess_runner=capture,
    )
    tool(code)
    return seen["cmd"]


#: ``RunPythonTool`` runs ``<elfenv>/bin/python``.  Standing the running
#: venv in for the elfenv is what makes these end-to-end instead of a
#: second mock.
_HAS_PREFIX_PYTHON = (Path(sys.prefix) / "bin" / "python").exists()
requires_prefix_python = pytest.mark.skipif(
    not _HAS_PREFIX_PYTHON,
    reason="no <prefix>/bin/python to stand in for the elfenv interpreter",
)


class TestRunPythonCommandUnderTheSandboxes:
    """The bug this exists for: the tool wrote the script to a host temp
    file and passed its *path*, and ``/tmp`` inside the sandbox is a fresh
    tmpfs.  Every program the tool was ever given would have come back
    ``can't open file '/tmp/tmpXXXX.py'``.
    """

    def test_the_command_carries_the_code_not_a_path(self):
        cmd = _python_command("print('carried')")
        assert cmd[1] == "-c"
        assert cmd[2] == "print('carried')"
        assert not any(str(part).endswith(".py") for part in cmd)

    @requires_prefix_python
    def test_none_sandbox_runs_it(self):
        rc, out, err = NoneSandbox().execute(
            _python_command("print('temp-free')"), timeout=20,
        )
        assert rc == 0, err
        assert out == "temp-free"

    @requires_bwrap
    @requires_prefix_python
    def test_bwrap_runs_it(self):
        rc, out, err = BwrapSandbox().execute(
            _python_command("print('temp-free')"),
            profile=SandboxProfile(),
            timeout=20,
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
