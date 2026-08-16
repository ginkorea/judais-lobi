# tests/test_cli_smoke.py — CLI integration smoke tests

import pytest
from unittest.mock import patch, MagicMock
from io import StringIO


class TestCLISmoke:
    """Test CLI arg paths by mocking at the Elf boundary."""

    def _make_mock_elf_class(self):
        """Create a mock Elf class that can be instantiated by _main()."""
        mock_elf = MagicMock()
        mock_elf.model = "test-model"
        mock_elf.text_color = "cyan"
        mock_elf.client.provider = "openai"
        mock_elf.history = [{"role": "system", "content": "test"}]
        mock_elf.chat.return_value = "test response"
        mock_elf.tools = MagicMock()
        mock_elf.memory = MagicMock()

        MockClass = MagicMock(return_value=mock_elf)
        MockClass.__name__ = "TestElf"
        return MockClass, mock_elf

    @patch("sys.argv", ["test", "hello world"])
    def test_basic_chat(self):
        from core.cli import _main
        MockClass, mock_elf = self._make_mock_elf_class()
        mock_elf.chat.return_value = iter([])  # stream mode returns iterator
        _main(MockClass)
        MockClass.assert_called_once()
        mock_elf.enrich_with_memory.assert_called_once_with("hello world")

    @patch("sys.argv", ["test", "hello", "--empty"])
    def test_empty_flag(self):
        from core.cli import _main
        MockClass, mock_elf = self._make_mock_elf_class()
        mock_elf.chat.return_value = iter([])
        _main(MockClass)
        mock_elf.reset_history.assert_called_once()

    @patch("sys.argv", ["test", "hello", "--purge"])
    def test_purge_flag(self):
        from core.cli import _main
        MockClass, mock_elf = self._make_mock_elf_class()
        mock_elf.chat.return_value = iter([])
        _main(MockClass)
        mock_elf.purge_memory.assert_called_once()

    @patch("sys.argv", ["test", "list files", "--shell"])
    def test_shell_flag(self):
        from core.cli import _main
        MockClass, mock_elf = self._make_mock_elf_class()
        mock_elf.run_shell_task.return_value = ("ls", "output", True, None)
        _main(MockClass)
        mock_elf.run_shell_task.assert_called_once()

    @patch("sys.argv", ["test", "print hello", "--python"])
    def test_python_flag(self):
        from core.cli import _main
        MockClass, mock_elf = self._make_mock_elf_class()
        mock_elf.run_python_task.return_value = ("code", "output", True, None)
        _main(MockClass)
        mock_elf.run_python_task.assert_called_once()

    @patch("sys.argv", ["test", "hello", "--unsandboxed"])
    def test_unsandboxed_flag_asks_the_agent_for_no_sandbox(self):
        """`--unsandboxed` resolves to the one word `select_sandbox` reads as
        the opt-out and hands it to the agent it builds."""
        from core.cli import _main
        MockClass, mock_elf = self._make_mock_elf_class()
        mock_elf.chat.return_value = iter([])
        _main(MockClass)
        _args, kwargs = MockClass.call_args
        assert kwargs.get("sandbox_request") == "none"

    @patch("sys.argv", ["test", "hello"])
    def test_no_flag_leaves_the_sandbox_choice_to_env_and_auto(self):
        """No flag means no request, so `JUDAIS_LOBI_SANDBOX` and then the
        auto path decide — the on-by-default behaviour, not an opt-out."""
        from core.cli import _main
        MockClass, mock_elf = self._make_mock_elf_class()
        mock_elf.chat.return_value = iter([])
        _main(MockClass)
        _args, kwargs = MockClass.call_args
        assert kwargs.get("sandbox_request") is None

    @patch("sys.argv", ["test", "hello", "--md"])
    def test_md_flag(self):
        from core.cli import _main
        MockClass, mock_elf = self._make_mock_elf_class()
        mock_elf.chat.return_value = "markdown response"
        _main(MockClass)
        mock_elf.chat.assert_called_once_with("hello", stream=False)

    @patch("sys.argv", ["test", "hello", "--search"])
    def test_search_flag(self):
        from core.cli import _main
        MockClass, mock_elf = self._make_mock_elf_class()
        mock_elf.chat.return_value = iter([])
        _main(MockClass)
        mock_elf.enrich_with_search.assert_called_once()

    @patch("sys.argv", ["test", "hello", "--research"])
    def test_research_flag(self):
        from core.cli import _main
        MockClass, mock_elf = self._make_mock_elf_class()
        mock_elf.chat.return_value = iter([])
        _main(MockClass)
        mock_elf.enrich_with_research.assert_called_once()

    @patch("sys.argv", ["test", "hello", "--research", "--academic"])
    def test_research_academic_flag(self):
        from core.cli import _main
        MockClass, mock_elf = self._make_mock_elf_class()
        mock_elf.chat.return_value = iter([])
        _main(MockClass)
        mock_elf.enrich_with_research.assert_called_once()

    @patch("sys.argv", ["test", "mission", "--campaign"])
    def test_campaign_flag(self):
        from core.cli import _main
        MockClass, mock_elf = self._make_mock_elf_class()
        mock_elf.run_campaign_from_description.return_value = MagicMock(status="completed")
        _main(MockClass)
        mock_elf.run_campaign_from_description.assert_called_once()


class TestTheWallClockDefault:
    """``MISSION_SECONDS`` is the flag's argparse default, so the flag wins.

    And every unusable value means *unbounded*, which is the same behaviour
    the variable's absence gives. A mistyped budget taken as a budget of
    nothing would kill a run before its first step, which is the failure that
    looks like a broken harness rather than like a typo.
    """

    def test_unset_is_unbounded(self, monkeypatch):
        from core.cli import _env_seconds

        monkeypatch.delenv("MISSION_SECONDS", raising=False)
        assert _env_seconds("MISSION_SECONDS") is None

    @pytest.mark.parametrize("value", ["", "   ", "thirty", "90s", "0", "-5"])
    def test_an_unusable_value_is_unbounded_and_not_a_refusal(
            self, monkeypatch, value):
        from core.cli import _env_seconds

        monkeypatch.setenv("MISSION_SECONDS", value)
        assert _env_seconds("MISSION_SECONDS") is None

    @pytest.mark.parametrize("value,expected", [("90", 90.0), ("2.5", 2.5)])
    def test_a_number_is_the_budget(self, monkeypatch, value, expected):
        from core.cli import _env_seconds

        monkeypatch.setenv("MISSION_SECONDS", value)
        assert _env_seconds("MISSION_SECONDS") == expected
