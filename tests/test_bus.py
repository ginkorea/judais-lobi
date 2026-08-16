# tests/test_bus.py

import pytest
from unittest.mock import MagicMock

from core.tools.bus import ToolBus, ToolResult
from core.tools.descriptors import ToolDescriptor, SandboxProfile
from core.tools.capability import CapabilityEngine
from core.tools.sandbox import NoneSandbox
from core.contracts.schemas import PermissionGrant, PolicyPack


class TestToolResult:
    def test_basic_result(self):
        r = ToolResult(exit_code=0, stdout="ok", stderr="", tool_name="test")
        assert r.exit_code == 0
        assert r.stdout == "ok"
        assert r.tool_name == "test"
        assert r.granted_scopes == []

    def test_result_with_scopes(self):
        r = ToolResult(
            exit_code=0, stdout="", stderr="",
            tool_name="t", granted_scopes=["a.b"],
        )
        assert r.granted_scopes == ["a.b"]


class TestToolBusRegistration:
    def test_register_and_list(self):
        bus = ToolBus()
        desc = ToolDescriptor(tool_name="test_tool")
        bus.register(desc, lambda: None)
        assert "test_tool" in bus.list_tools()

    def test_list_empty(self):
        bus = ToolBus()
        assert bus.list_tools() == []

    def test_register_multiple(self):
        bus = ToolBus()
        bus.register(ToolDescriptor(tool_name="a"), lambda: None)
        bus.register(ToolDescriptor(tool_name="b"), lambda: None)
        assert len(bus.list_tools()) == 2

    def test_describe_tool(self):
        bus = ToolBus()
        desc = ToolDescriptor(
            tool_name="t", description="A test tool",
            required_scopes=["x.y"],
        )
        bus.register(desc, lambda: None)
        info = bus.describe_tool("t")
        assert info["name"] == "t"
        assert info["description"] == "A test tool"
        assert "x.y" in info["required_scopes"]

    def test_describe_unknown_tool(self):
        bus = ToolBus()
        info = bus.describe_tool("nope")
        assert "error" in info

    def test_get_descriptor(self):
        bus = ToolBus()
        desc = ToolDescriptor(tool_name="t")
        bus.register(desc, lambda: None)
        assert bus.get_descriptor("t") is desc

    def test_get_descriptor_missing(self):
        bus = ToolBus()
        assert bus.get_descriptor("nope") is None


class TestToolBusDispatch:
    def _make_permissive_bus(self):
        """Bus with all scopes allowed."""
        policy = PolicyPack(allowed_scopes=[
            "shell.exec", "python.exec", "pip.install",
            "http.read", "fs.read", "audio.output",
        ])
        engine = CapabilityEngine(policy)
        return ToolBus(capability_engine=engine)

    def test_dispatch_unknown_tool(self):
        bus = ToolBus()
        result = bus.dispatch("nonexistent")
        assert result.exit_code == -1
        import json
        error = json.loads(result.stderr)
        assert error["error"] == "unknown_tool"

    def test_dispatch_tuple_result(self):
        bus = self._make_permissive_bus()
        desc = ToolDescriptor(tool_name="t", required_scopes=["shell.exec"])
        bus.register(desc, lambda cmd: (0, "output", ""))
        result = bus.dispatch("t", "echo hi")
        assert result.exit_code == 0
        assert result.stdout == "output"
        assert result.tool_name == "t"
        assert "shell.exec" in result.granted_scopes

    def test_dispatch_string_result(self):
        bus = self._make_permissive_bus()
        desc = ToolDescriptor(tool_name="t", required_scopes=["fs.read"])
        bus.register(desc, lambda: "some text")
        result = bus.dispatch("t")
        assert result.exit_code == 0
        assert result.stdout == "some text"

    def test_dispatch_executor_exception(self):
        bus = self._make_permissive_bus()
        desc = ToolDescriptor(tool_name="t", required_scopes=["shell.exec"])
        bus.register(desc, lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        result = bus.dispatch("t")
        assert result.exit_code == -1
        assert "RuntimeError" in result.stderr

    def test_dispatch_with_kwargs(self):
        bus = self._make_permissive_bus()
        desc = ToolDescriptor(tool_name="t", required_scopes=["shell.exec"])

        def executor(cmd, timeout=None):
            return (0, f"ran with timeout={timeout}", "")

        bus.register(desc, executor)
        result = bus.dispatch("t", "ls", timeout=30)
        assert "timeout=30" in result.stdout

    def test_no_scopes_always_allowed(self):
        """Tools with no required scopes bypass capability check."""
        bus = ToolBus()  # default deny-all engine
        desc = ToolDescriptor(tool_name="t", required_scopes=[])
        bus.register(desc, lambda: (0, "ok", ""))
        result = bus.dispatch("t")
        assert result.exit_code == 0


class TestToolBusCapabilityGating:
    def test_denied_returns_structured_error(self):
        engine = CapabilityEngine()  # deny-by-default
        bus = ToolBus(capability_engine=engine)
        desc = ToolDescriptor(
            tool_name="run_shell_command",
            required_scopes=["shell.exec"],
        )
        bus.register(desc, lambda cmd: (0, "ok", ""))
        result = bus.dispatch("run_shell_command", "ls")
        assert result.exit_code == -1
        import json
        denial = json.loads(result.stderr)
        assert denial["error"] == "capability_denied"
        assert denial["tool"] == "run_shell_command"
        assert "shell.exec" in denial["missing_scopes"]
        assert result.evidence is not None

    def test_granted_allows_execution(self):
        engine = CapabilityEngine()
        engine.add_grant(PermissionGrant(
            tool_name="run_shell_command", scope="shell.exec",
        ))
        bus = ToolBus(capability_engine=engine)
        desc = ToolDescriptor(
            tool_name="run_shell_command",
            required_scopes=["shell.exec"],
        )
        bus.register(desc, lambda cmd: (0, "ok", ""))
        result = bus.dispatch("run_shell_command", "ls")
        assert result.exit_code == 0

    def test_partial_grant_denied(self):
        engine = CapabilityEngine()
        engine.add_grant(PermissionGrant(
            tool_name="install_project", scope="python.exec",
        ))
        bus = ToolBus(capability_engine=engine)
        desc = ToolDescriptor(
            tool_name="install_project",
            required_scopes=["python.exec", "pip.install"],
        )
        bus.register(desc, lambda path: (0, "ok", ""))
        result = bus.dispatch("install_project", ".")
        assert result.exit_code == -1
        assert "pip.install" in result.stderr

    def test_policy_allows_bypass(self):
        policy = PolicyPack(allowed_scopes=["shell.exec"])
        engine = CapabilityEngine(policy)
        bus = ToolBus(capability_engine=engine)
        desc = ToolDescriptor(
            tool_name="run_shell_command",
            required_scopes=["shell.exec"],
        )
        bus.register(desc, lambda cmd: (0, "ok", ""))
        result = bus.dispatch("run_shell_command", "ls")
        assert result.exit_code == 0


class TestToolBusNetworkGating:
    def test_network_denied(self):
        """Network tool denied when http.read not granted."""
        engine = CapabilityEngine()
        bus = ToolBus(capability_engine=engine)
        desc = ToolDescriptor(
            tool_name="perform_web_search",
            required_scopes=["http.read"],
            requires_network=True,
            network_scopes=["http.read"],
        )
        bus.register(desc, lambda q: "results")
        result = bus.dispatch("perform_web_search", "test")
        assert result.exit_code == -1
        assert "denied" in result.stderr.lower()

    def test_network_allowed(self):
        policy = PolicyPack(allowed_scopes=["http.read"])
        engine = CapabilityEngine(policy)
        bus = ToolBus(capability_engine=engine)
        desc = ToolDescriptor(
            tool_name="perform_web_search",
            required_scopes=["http.read"],
            requires_network=True,
            network_scopes=["http.read"],
        )
        bus.register(desc, lambda q: "results")
        result = bus.dispatch("perform_web_search", "test")
        assert result.exit_code == 0
        assert result.stdout == "results"


class TestToolBusActionAwareDispatch:
    """Phase 4a: action-aware dispatch for multi-action tools."""

    def _make_bus_with_scopes(self, scopes):
        policy = PolicyPack(allowed_scopes=scopes)
        engine = CapabilityEngine(policy)
        return ToolBus(capability_engine=engine)

    def test_action_specific_scope_check(self):
        bus = self._make_bus_with_scopes(["git.read"])
        desc = ToolDescriptor(
            tool_name="git",
            required_scopes=["git.read", "git.write", "git.push", "git.fetch"],
            action_scopes={
                "status": ["git.read"],
                "commit": ["git.write"],
            },
        )
        bus.register(desc, lambda action, **kw: (0, f"did {action}", ""))
        # git.read is granted — status should work
        result = bus.dispatch("git", action="status")
        assert result.exit_code == 0
        assert result.stdout == "did status"
        assert result.granted_scopes == ["git.read"]

    def test_action_denied_when_scope_missing(self):
        bus = self._make_bus_with_scopes(["git.read"])
        desc = ToolDescriptor(
            tool_name="git",
            required_scopes=["git.read", "git.write"],
            action_scopes={
                "status": ["git.read"],
                "commit": ["git.write"],
            },
        )
        bus.register(desc, lambda action, **kw: (0, "ok", ""))
        # git.write not granted — commit should be denied
        result = bus.dispatch("git", action="commit")
        assert result.exit_code == -1
        import json
        denial = json.loads(result.stderr)
        assert denial["error"] == "capability_denied"
        assert "git.write" in denial["missing_scopes"]
        assert denial["action"] == "commit"

    def test_no_action_uses_full_scopes(self):
        bus = self._make_bus_with_scopes(["fs.read"])
        desc = ToolDescriptor(
            tool_name="fs",
            required_scopes=["fs.read", "fs.write", "fs.delete"],
            action_scopes={"read": ["fs.read"]},
        )
        bus.register(desc, lambda: (0, "ok", ""))
        # Without action, checks all required_scopes — fs.write/delete missing
        result = bus.dispatch("fs")
        assert result.exit_code == -1

    def test_unknown_action_falls_back_to_required_scopes(self):
        bus = self._make_bus_with_scopes(["git.read", "git.write", "git.push", "git.fetch"])
        desc = ToolDescriptor(
            tool_name="git",
            required_scopes=["git.read", "git.write", "git.push", "git.fetch"],
            action_scopes={"status": ["git.read"]},
        )
        bus.register(desc, lambda action, **kw: (0, "ok", ""))
        # Unknown action falls back to full required_scopes
        result = bus.dispatch("git", action="unknown_action")
        assert result.exit_code == 0

    def test_action_passes_to_executor(self):
        bus = self._make_bus_with_scopes(["verify.run"])
        desc = ToolDescriptor(
            tool_name="verify",
            required_scopes=["verify.run"],
            action_scopes={"lint": ["verify.run"]},
        )
        captured = {}
        def executor(action, **kwargs):
            captured["action"] = action
            return (0, "ok", "")
        bus.register(desc, executor)
        bus.dispatch("verify", action="lint")
        assert captured["action"] == "lint"

    def test_describe_tool_includes_actions(self):
        bus = ToolBus()
        desc = ToolDescriptor(
            tool_name="git",
            action_scopes={"status": ["git.read"], "commit": ["git.write"]},
        )
        bus.register(desc, lambda: None)
        info = bus.describe_tool("git")
        assert "actions" in info
        assert "status" in info["actions"]
        assert "commit" in info["actions"]

    def test_structured_unknown_tool_error(self):
        bus = ToolBus()
        result = bus.dispatch("nonexistent")
        assert result.exit_code == -1
        import json
        error = json.loads(result.stderr)
        assert error["error"] == "unknown_tool"

    def test_evidence_field_on_denial(self):
        bus = ToolBus()
        desc = ToolDescriptor(tool_name="t", required_scopes=["x.y"])
        bus.register(desc, lambda: (0, "ok", ""))
        result = bus.dispatch("t")
        assert result.exit_code == -1
        assert result.evidence is not None
        import json
        evidence = json.loads(result.evidence)
        assert evidence["error"] == "capability_denied"


class TestToolBusProperties:
    def test_capability_engine_property(self):
        engine = CapabilityEngine()
        bus = ToolBus(capability_engine=engine)
        assert bus.capability_engine is engine

    def test_sandbox_property(self):
        sandbox = NoneSandbox()
        bus = ToolBus(sandbox=sandbox)
        assert bus.sandbox is sandbox

    def test_default_engine_is_a_capability_engine(self):
        assert isinstance(ToolBus().capability_engine, CapabilityEngine)

    def test_default_sandbox_is_the_safe_default_not_none(self):
        """A bus handed no sandbox is safe by default: it makes the same
        choice ``select_sandbox`` does — bwrap where bubblewrap exists — so
        no isolation is a decision on the record, not the fallthrough. The
        blunt ``isinstance(..., NoneSandbox)`` this replaced asserted the
        old unsafe default."""
        from core.tools.sandbox import select_sandbox
        _runner, expected = select_sandbox()
        assert ToolBus().sandbox_name == expected

    def test_an_explicit_none_sandbox_is_honoured(self):
        """Opting out is still one line: pass ``NoneSandbox()`` and the bus
        keeps it, auto path untouched."""
        bus = ToolBus(sandbox=NoneSandbox())
        assert isinstance(bus.sandbox, NoneSandbox)
        assert bus.sandbox_name == "none"


class TestUnregister:
    """Registration used to be one-way; MCP made that a defect.

    A server that withdraws a tool would otherwise leave a descriptor the
    bus still advertises and describes, so the model gets offered a tool
    whose only possible answer is an error from the far end.
    """

    def _bus(self):
        from core.tools.bus import ToolBus
        from core.tools.capability import CapabilityEngine
        from core.contracts.schemas import PolicyPack
        return ToolBus(capability_engine=CapabilityEngine(
            PolicyPack(allowed_scopes=["*"])))

    def _register(self, bus, name="tmp"):
        from core.tools.descriptors import ToolDescriptor
        bus.register(ToolDescriptor(tool_name=name, description="d"),
                     lambda **_kw: (0, "ran", ""))

    def test_it_removes_the_tool(self):
        bus = self._bus()
        self._register(bus)
        assert bus.unregister("tmp") is True
        assert "tmp" not in bus.list_tools()

    def test_it_removes_the_executor_too(self):
        """A descriptor without an executor would KeyError on dispatch."""
        bus = self._bus()
        self._register(bus)
        bus.unregister("tmp")
        assert bus._executors.get("tmp") is None

    def test_dispatch_afterwards_is_unknown_tool(self):
        bus = self._bus()
        self._register(bus)
        bus.unregister("tmp")
        result = bus.dispatch("tmp")
        assert result.exit_code == -1
        assert "unknown_tool" in result.stderr

    def test_describe_afterwards_is_an_error(self):
        bus = self._bus()
        self._register(bus)
        bus.unregister("tmp")
        assert "error" in bus.describe_tool("tmp")

    def test_get_descriptor_afterwards_is_none(self):
        bus = self._bus()
        self._register(bus)
        bus.unregister("tmp")
        assert bus.get_descriptor("tmp") is None

    def test_an_unknown_name_returns_false_rather_than_raising(self):
        """Callers reconcile sets; 'already gone' is the ordinary case."""
        assert self._bus().unregister("never-registered") is False

    def test_it_leaves_the_other_tools_alone(self):
        bus = self._bus()
        self._register(bus, "a")
        self._register(bus, "b")
        bus.unregister("a")
        assert bus.list_tools() == ["b"]

    def test_re_registering_after_unregister_works(self):
        bus = self._bus()
        self._register(bus)
        bus.unregister("tmp")
        self._register(bus)
        assert bus.dispatch("tmp").stdout == "ran"


# ── what the audit log says a dispatch was ───────────────────────────────────


class _ThrowingLogger:
    """A logger whose disk is full, which is the case the bare ``pass`` hid."""

    def __init__(self):
        self.attempts = 0
        self.path = "/nowhere/audit.jsonl"

    def log(self, entry):
        self.attempts += 1
        raise OSError(28, "No space left on device")


def _audited(tmp_path, *, scopes=("*",), name="t", executor=None,
             required=("x.y",), audit=None):
    """A bus with a real :class:`AuditLogger` and one registered tool."""
    from core.policy.audit import AuditLogger

    logger = audit if audit is not None else AuditLogger(
        path=tmp_path / "audit.jsonl")
    bus = ToolBus(
        capability_engine=CapabilityEngine(PolicyPack(allowed_scopes=list(scopes))),
        audit=logger,
    )
    bus.register(
        ToolDescriptor(tool_name=name, description="d",
                       required_scopes=list(required)),
        executor if executor is not None else (lambda **kw: (0, "ran", "")),
    )
    return bus, logger


def _detail(logger, index=-1):
    """The last entry's ``detail``, parsed back out of its JSON."""
    import json
    return json.loads(logger.tail(50)[index]["detail"])


class TestEveryDispatchIsAudited:
    """A framework that cannot say what it ran is not one you leave running.

    Every exit from ``dispatch`` writes a line — the ones that ran and the
    ones that were refused alike. An audit that recorded only the calls that
    got as far as the executor would be silent about exactly the runs
    somebody comes asking about.
    """

    def test_an_allowed_dispatch_writes_one_line(self, tmp_path):
        bus, logger = _audited(tmp_path)
        bus.dispatch("t", q="x")
        entries = logger.tail(10)
        assert len(entries) == 1
        assert entries[0]["tool_name"] == "t"
        assert entries[0]["verdict"] == "allowed"

    def test_the_line_carries_the_arguments(self, tmp_path):
        bus, logger = _audited(tmp_path)
        bus.dispatch("t", "positional", q="x")
        detail = _detail(logger)
        assert "positional" in detail["arguments"]
        assert '"q": "x"' in detail["arguments"]

    def test_the_line_carries_exit_code_duration_and_bytes(self, tmp_path):
        bus, logger = _audited(
            tmp_path, executor=lambda **kw: (3, "twelve chars", "err"))
        bus.dispatch("t")
        detail = _detail(logger)
        assert detail["exit_code"] == 3
        assert detail["bytes_out"] == len("twelve chars") + len("err")
        assert detail["duration_ms"] >= 0

    def test_a_capability_denial_is_audited_with_its_reason(self, tmp_path):
        """Checked rather than assumed: the denial path returns early, and an
        early return is the shape a log line goes missing from."""
        bus, logger = _audited(tmp_path, scopes=())
        result = bus.dispatch("t", q="x")
        assert result.exit_code == -1
        entry = logger.tail(1)[0]
        assert entry["verdict"] == "denied"
        assert _detail(logger)["reason"]
        assert '"q": "x"' in _detail(logger)["arguments"]

    def test_a_network_denial_is_audited(self, tmp_path):
        from core.policy.audit import AuditLogger

        logger = AuditLogger(path=tmp_path / "audit.jsonl")
        bus = ToolBus(
            capability_engine=CapabilityEngine(PolicyPack(allowed_scopes=["x.y"])),
            audit=logger,
        )
        bus.register(
            ToolDescriptor(tool_name="t", required_scopes=["x.y"],
                           requires_network=True, network_scopes=["net.out"]),
            lambda **kw: (0, "ran", ""))
        bus.dispatch("t")
        assert logger.tail(1)[0]["verdict"] == "denied"

    def test_an_unknown_tool_is_audited(self, tmp_path):
        """A model naming a tool nobody offers is a fact about the run — it is
        the shape of a mission spending its budget on protocol."""
        bus, logger = _audited(tmp_path)
        bus.dispatch("nope", q="x")
        assert logger.tail(1)[0]["verdict"] == "unknown_tool"

    def test_a_tool_that_raises_is_audited_as_an_error(self, tmp_path):
        def explode(**_kw):
            raise RuntimeError("the far end went away")

        bus, logger = _audited(tmp_path, executor=explode)
        bus.dispatch("t")
        entry = logger.tail(1)[0]
        assert entry["verdict"] == "error"
        assert "the far end went away" in _detail(logger)["reason"]

    def test_the_panic_switch_is_audited(self, tmp_path):
        from types import SimpleNamespace

        from core.policy.audit import AuditLogger

        logger = AuditLogger(path=tmp_path / "audit.jsonl")
        bus = ToolBus(
            capability_engine=CapabilityEngine(PolicyPack(allowed_scopes=["*"])),
            god_mode=SimpleNamespace(is_panicked=True),
            audit=logger,
        )
        bus.register(ToolDescriptor(tool_name="t"), lambda **kw: (0, "ran", ""))
        bus.dispatch("t")
        assert logger.tail(1)[0]["verdict"] == "panic_revoked"

    def test_the_action_is_recorded(self, tmp_path):
        bus, logger = _audited(
            tmp_path, executor=lambda action, **kw: (0, action, ""))
        bus.dispatch("t", action="read")
        assert logger.tail(1)[0]["action"] == "read"

    def test_no_logger_writes_nothing_and_still_dispatches(self, tmp_path):
        """A bare ``ToolBus()`` is unchanged: auditing arrives with
        ``Tools()``, which is what a CLI or library caller actually holds."""
        bus = ToolBus(capability_engine=CapabilityEngine(
            PolicyPack(allowed_scopes=["*"])))
        bus.register(ToolDescriptor(tool_name="t"), lambda **kw: (0, "ran", ""))
        assert bus.dispatch("t").stdout == "ran"
        assert bus.audit_ref is None


class TestTheStepTheCallerSet:
    """The bus has no idea what a step is and must not learn one.

    It serves chat turns, kernel roles and missions alike. So the caller
    leaves its own columns in ``audit_context`` and the bus copies them onto
    the entry — one settable dict against a mission-shaped parameter on a
    module that has no business knowing what a mission is.
    """

    def test_the_context_rides_the_entry(self, tmp_path):
        bus, logger = _audited(tmp_path)
        bus.audit_context["step"] = 3
        bus.dispatch("t")
        assert _detail(logger)["step"] == 3

    def test_the_latest_value_is_the_one_recorded(self, tmp_path):
        bus, logger = _audited(tmp_path)
        bus.audit_context["step"] = 0
        bus.dispatch("t")
        bus.audit_context["step"] = 1
        bus.dispatch("t")
        assert [_detail(logger, i)["step"] for i in (0, 1)] == [0, 1]

    def test_the_bus_s_own_facts_win_a_collision(self, tmp_path):
        """A caller cannot overwrite the exit code with a column of its own."""
        bus, logger = _audited(tmp_path, executor=lambda **kw: (7, "", ""))
        bus.audit_context["exit_code"] = 999
        bus.dispatch("t")
        assert _detail(logger)["exit_code"] == 7

    def test_an_empty_context_adds_no_columns(self, tmp_path):
        bus, logger = _audited(tmp_path)
        bus.dispatch("t")
        assert "step" not in _detail(logger)


class TestSecretsNeverReachTheAuditFile:
    """The arguments are where the credentials are.

    They travel in ``detail`` precisely so that one redaction pass covers
    them — a second AuditEntry field would be a second thing to remember,
    and the one that got forgotten would be the one carrying the argument.
    """

    def test_an_sk_key_in_an_argument(self, tmp_path):
        bus, logger = _audited(tmp_path)
        bus.dispatch("t", key="sk-abc12345678901234567890")
        text = (tmp_path / "audit.jsonl").read_text()
        assert "sk-abc123" not in text
        assert "[REDACTED]" in text

    def test_a_bearer_token_in_an_argument(self, tmp_path):
        bus, logger = _audited(tmp_path)
        bus.dispatch("t", header="Bearer eyJhbGciOiJIUzI1NiJ9xyz")
        text = (tmp_path / "audit.jsonl").read_text()
        assert "eyJhbGciOiJIUzI1NiJ9xyz" not in text
        assert "[REDACTED]" in text

    def test_the_mcp_token_this_process_was_given(self, tmp_path, monkeypatch):
        """The one with no shape at all. Only the environment knows it."""
        monkeypatch.setenv("MCP_TOKEN", "totally-opaque-credential")
        bus, logger = _audited(tmp_path)
        bus.dispatch("t", auth="totally-opaque-credential")
        text = (tmp_path / "audit.jsonl").read_text()
        assert "totally-opaque-credential" not in text
        assert "[REDACTED]" in text


class TestTheArgumentsAreBounded:
    def test_a_huge_argument_is_cut_at_the_one_cap(self, tmp_path):
        """``core.bounding.bound_result`` and not a second number: an audit
        line is a record, not a transcript, and the repository has exactly one
        opinion about how much of a payload travels."""
        from core.bounding import MAX_RESULT_BYTES

        bus, logger = _audited(tmp_path)
        bus.dispatch("t", blob="z" * (MAX_RESULT_BYTES * 2))
        detail = _detail(logger)
        assert detail["arguments_truncated"] is True
        assert len(detail["arguments"].encode("utf-8")) < MAX_RESULT_BYTES * 2

    def test_an_ordinary_argument_is_not_marked_truncated(self, tmp_path):
        bus, logger = _audited(tmp_path)
        bus.dispatch("t", q="x")
        assert "arguments_truncated" not in _detail(logger)


class TestAnAuditFailureIsNotSilent:
    """``bus.py`` swallowed every audit exception with a bare ``pass`` for four
    phases, which meant a bus whose logger had been throwing since the first
    call looked exactly like a bus whose tools nobody had used.

    Dispatch still survives — an audit disk filling up must not kill a tool
    call — but the failure is counted on the bus and said once on stderr. Once,
    because the second thousand copies of a full-disk message are what stop
    anybody reading the first; the counter carries the rest and the CLI prints
    it when the mission ends.
    """

    def test_the_dispatch_still_returns_its_result(self, tmp_path):
        bus, _ = _audited(tmp_path, audit=_ThrowingLogger())
        assert bus.dispatch("t").stdout == "ran"

    def test_the_failure_is_counted(self, tmp_path):
        bus, logger = _audited(tmp_path, audit=_ThrowingLogger())
        bus.dispatch("t")
        bus.dispatch("t")
        assert logger.attempts == 2
        assert bus.audit_failures == 2

    def test_it_is_said_on_stderr_exactly_once(self, tmp_path, capsys):
        bus, _ = _audited(tmp_path, audit=_ThrowingLogger())
        bus.dispatch("t")
        bus.dispatch("t")
        bus.dispatch("t")
        err = capsys.readouterr().err
        assert err.count("audit write FAILED") == 1
        assert "No space left on device" in err

    def test_a_healthy_bus_counts_nothing(self, tmp_path, capsys):
        bus, _ = _audited(tmp_path)
        bus.dispatch("t")
        assert bus.audit_failures == 0
        assert "audit write FAILED" not in capsys.readouterr().err


class TestAuditRefIsTheOneOwnerOfThePath:
    def test_it_names_the_file(self, tmp_path):
        bus, _ = _audited(tmp_path)
        assert bus.audit_ref == str(tmp_path / "audit.jsonl")

    def test_it_is_none_without_a_logger(self):
        assert ToolBus().audit_ref is None

    def test_it_is_none_for_a_logger_with_no_path(self):
        """A caller may pass anything with a ``log``; only a real path is a
        reference worth putting on the stream."""
        from types import SimpleNamespace

        assert ToolBus(audit=SimpleNamespace(log=lambda entry: None)).audit_ref \
            is None
