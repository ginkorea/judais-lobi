# tests/test_sandbox.py

import subprocess
import pytest
from unittest.mock import patch, MagicMock

from core.tools.sandbox import NoneSandbox, BwrapSandbox, get_sandbox, SandboxRunner
from core.tools.descriptors import SandboxProfile


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
