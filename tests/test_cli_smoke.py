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
    def test_campaign_flag_is_mission_mode(self):
        """A campaign is a MISSION, and it used to be a branch of its own.

        This asserted `elf.run_campaign_from_description`, which walked a
        plan's DAG through the coding kernel's task dispatcher — no run
        store, no `--approval`, no supervisor, nothing on the wire and no
        resume. Phase 15 lane Q deleted that method and its orchestrator; a
        campaign is `core.runtime.campaign.CampaignRunner` now, built where
        the staged runner is built and out of the same six objects. So what
        this checks is that the flag reaches mission mode rather than
        anything of its own — the plan itself is
        `tests/test_campaign_run.py`.
        """
        from core.cli import _main
        MockClass, mock_elf = self._make_mock_elf_class()
        with patch("core.cli._run_mission") as ran:
            _main(MockClass)
        ran.assert_called_once()

    @patch("sys.argv", ["test", "--campaign-plan", "/nonexistent/plan.json"])
    def test_campaign_plan_needs_no_message_and_is_mission_mode(self):
        """The objective is a field of the plan, so the positional may be
        omitted — and the flag implies `--mission` without it being typed."""
        from core.cli import _main
        MockClass, _mock_elf = self._make_mock_elf_class()
        with patch("core.cli._run_mission") as ran:
            _main(MockClass)
        ran.assert_called_once()

    @patch("sys.argv", ["test", "hello", "--grant", "not.a.scope"])
    def test_a_grant_naming_no_scope_is_refused_before_anything_is_built(
            self):
        """At the door, like every other bad flag: an operator who mistypes
        a scope must not watch a mission be refused for a capability they
        believe they granted."""
        from core.cli import _grants_of

        with pytest.raises(SystemExit, match="not.a.scope"):
            _grants_of(type("A", (), {"grant": ["not.a.scope"]})())

    def test_answering_a_gate_builds_no_agent_at_all(self, tmp_path,
                                                     monkeypatch):
        """A run that could answer its own gate would not be a gate. The
        cheapest guarantee is that the answering path shares nothing with the
        running one: no Elf, no memory, no tool bus, no model."""
        from core.cli import _main
        from core.runtime.approvals import (
            APPROVALS_ENV, APPROVED, ApprovalStore,
        )

        root = tmp_path / "approvals"
        monkeypatch.setenv(APPROVALS_ENV, str(root))
        approval_id = ApprovalStore(root).request(tool="mcp.cancel_job")

        MockClass, _mock_elf = self._make_mock_elf_class()
        with patch("sys.argv", ["test", "--mission", "--approve", approval_id,
                                "--decided-by", "dana"]):
            _main(MockClass)

        assert ApprovalStore(root).get(approval_id).state == APPROVED
        MockClass.assert_not_called()

    @patch("sys.argv", ["test"])
    def test_no_message_is_refused_in_this_repos_own_words(self):
        """`message` is optional so that `--approve` need not pretend to be a
        conversation. Every other path still refuses without one."""
        from core.cli import _main
        MockClass, _mock_elf = self._make_mock_elf_class()
        with pytest.raises(SystemExit) as exc:
            _main(MockClass)
        assert "a message is required" in str(exc.value)
        MockClass.assert_not_called()



class TestAnUnreachableServerIsANonZeroExit:
    """The `silence` clause of `EXIT_CONTRACT`, honoured on the one channel
    a consumer can read when there is no stream to read.

    "A mission that emits ZERO events has failed … a consumer must report
    it as a failure rather than render a blank reply", and the clause names
    an unreachable MCP endpoint as one of the three ways it happens. The
    handler printed a red line on stdout — the channel the contract says
    not to parse — and returned, so the process exited **0**: a consumer
    spawning us was told the turn finished, with nothing on the stream.
    """

    def _refusing(self, exc):
        """`_mission` with the fleet refusing to come up, and no run store,
        no audit and no memory written anywhere near the checkout."""
        from core.tools import mcp_client

        def boom(*_a, **_kw):
            raise exc
        return patch.object(mcp_client, "McpFleet", boom)

    def _argv(self):
        return ["test", "what exists?", "--mission",
                "--mcp-url", "http://127.0.0.1:9/mcp"]

    def _run(self, monkeypatch, tmp_path, exc):
        from core.cli import _main

        monkeypatch.setenv("JUDAIS_LOBI_RUNS", "off")
        monkeypatch.setenv("JUDAIS_LOBI_AUDIT", "off")
        monkeypatch.setenv("JUDAIS_LOBI_MEMORY", "off")
        monkeypatch.chdir(tmp_path)
        MockClass, mock_elf = TestCLISmoke()._make_mock_elf_class()
        mock_elf.client.last_usage = None
        mock_elf.system_message = "You are Tai."
        with self._refusing(exc), patch("sys.argv", self._argv()):
            with pytest.raises(SystemExit) as raised:
                _main(MockClass)
        return raised.value

    def test_an_unreachable_endpoint_exits_non_zero(self, monkeypatch,
                                                   tmp_path):
        from core.tools.mcp_client import McpConnectionError

        value = self._run(monkeypatch, tmp_path,
                          McpConnectionError("connection refused"))
        # `SystemExit(str)` is exit status 1 with the string on stderr,
        # which is where the `diagnostic` clause says a consumer looks when
        # a mission produced no events.
        assert value.code not in (0, None)

    def test_the_reason_travels_with_it(self, monkeypatch, tmp_path):
        from core.tools.mcp_client import McpConnectionError

        value = self._run(monkeypatch, tmp_path,
                          McpConnectionError("connection refused"))
        assert "connection refused" in str(value)

    def test_a_missing_sdk_is_the_same_answer(self, monkeypatch, tmp_path):
        """`McpUnavailable` is the other half of the same `except`: no
        server was reached, so no events were emitted, so the run failed."""
        from core.tools.mcp_client import McpUnavailable

        value = self._run(monkeypatch, tmp_path,
                          McpUnavailable("the mcp SDK is not installed"))
        assert value.code not in (0, None)


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


class TestProviderChoices:
    """`--provider` choices are generated from `PROVIDERS`, so a backend
    the client can build is a backend the CLI will accept."""

    @patch("sys.argv", ["test", "hello", "--provider", "anthropic"])
    def test_anthropic_is_accepted_and_forwarded(self):
        from core.cli import _main

        MockClass, mock_elf = TestCLISmoke()._make_mock_elf_class()
        mock_elf.chat.return_value = iter([])
        _main(MockClass)
        assert MockClass.call_args.kwargs["provider"] == "anthropic"

    @patch("sys.argv", ["test", "hello", "--provider", "nosuchprovider"])
    def test_an_unknown_provider_is_refused_at_the_door(self):
        from core.cli import _main

        MockClass, _ = TestCLISmoke()._make_mock_elf_class()
        with pytest.raises(SystemExit):
            _main(MockClass)
