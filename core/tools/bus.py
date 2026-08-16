# core/tools/bus.py — ToolBus registry and dispatch

import json as _json
import sys
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Any

from core.bounding import bound_result
from core.tools.descriptors import (
    ToolDescriptor,
    SandboxProfile,
    HIGH_RISK_ACTIONS,
    SKIP_SANDBOX_ACTIONS,
    NETWORK_ACTIONS,
    summarize_input_schema,
)
from core.tools.capability import CapabilityEngine, CapabilityVerdict
from core.tools.sandbox import SandboxRunner, NoneSandbox


@dataclass
class ToolResult:
    """Structured result from a tool invocation."""
    exit_code: int
    stdout: str
    stderr: str
    tool_name: str
    granted_scopes: List[str] = field(default_factory=list)
    evidence: Optional[str] = None


class ToolBus:
    """Tool registry with capability gating and sandboxed execution.

    This docstring said "MCP-style" for a long time while nothing in the
    package spoke MCP.  Something does now, but not this file:
    ``core.tools.mcp_client`` is the real client and it *bridges into
    this bus* — a tool a server advertises becomes an ordinary
    ``ToolDescriptor`` registered here, so everything below applies to it
    unchanged.

    Dispatch path: register -> check capabilities -> execute -> result

    For multi-action tools, pass ``action=`` as a keyword argument to
    ``dispatch()``.  The bus resolves scopes from
    ``descriptor.action_scopes[action]`` when available, falling back to
    ``descriptor.required_scopes``.
    """

    def __init__(
        self,
        capability_engine: Optional[CapabilityEngine] = None,
        sandbox: Optional[SandboxRunner] = None,
        preflight_hook: Optional[Callable] = None,
        god_mode: Any = None,
        audit: Any = None,
    ):
        self._descriptors: Dict[str, ToolDescriptor] = {}
        self._executors: Dict[str, Callable] = {}
        self._capability = capability_engine or CapabilityEngine()
        self._sandbox = sandbox or NoneSandbox()
        self._preflight_hook = preflight_hook
        self._god_mode = god_mode
        self._audit = audit
        #: How many audit writes have failed on this bus.  Counted rather
        #: than swallowed: see :meth:`_log_audit`.
        self.audit_failures = 0
        #: Whatever the caller running this bus wants on every audit entry
        #: — the mission puts its step index here before each dispatch.
        #: A plain dict because the bus has no business knowing what a
        #: step is, and because a caller that never sets one costs nothing.
        self.audit_context: Dict[str, Any] = {}

    @property
    def capability_engine(self) -> CapabilityEngine:
        return self._capability

    @property
    def sandbox(self) -> SandboxRunner:
        return self._sandbox

    @property
    def audit_ref(self) -> Optional[str]:
        """The audit file this bus is writing to, or ``None`` for no audit.

        The single owner of that string.  A mission carries it on
        ``mission_started.audit_ref`` and both runners read it from here
        rather than each resolving a path of its own — two resolutions of
        one fact is how a stream comes to name a file nothing wrote to.
        """
        path = getattr(self._audit, "path", None)
        return str(path) if path else None

    def register(self, descriptor: ToolDescriptor, executor: Callable) -> None:
        """Register a tool with its descriptor and executor."""
        self._descriptors[descriptor.tool_name] = descriptor
        self._executors[descriptor.tool_name] = executor

    def unregister(self, tool_name: str) -> bool:
        """Remove a tool. Returns whether it was registered.

        Registration used to be one-way, which was fine while every tool
        was compiled in and outlived the process.  It stopped being fine
        when tools began arriving from an MCP server at runtime: a
        server that withdraws one leaves a descriptor behind that
        ``list_tools`` still advertises and ``describe_tool`` still
        describes, so the model is offered a tool whose only possible
        answer is an error from the far end.

        Returns a bool instead of raising on an unregistered name: the
        caller is normally reconciling a *set* against this registry,
        and "it was already gone" is the ordinary case there.
        """
        existed = tool_name in self._descriptors
        self._descriptors.pop(tool_name, None)
        self._executors.pop(tool_name, None)
        return existed

    def dispatch(self, tool_name: str, *args: Any,
                 action: Optional[str] = None, **kwargs: Any) -> ToolResult:
        """Dispatch a tool invocation through capability gating.

        Parameters
        ----------
        tool_name : str
            Registered tool name.
        action : str, optional
            For multi-action tools, the specific action to run.
            Scopes are resolved from ``descriptor.action_scopes[action]``
            when present.
        *args, **kwargs
            Forwarded to the executor.  When *action* is given the executor
            receives ``(action, *args, **kwargs)``.
        """
        arguments = {"args": list(args), "kwargs": dict(kwargs)}

        if tool_name not in self._descriptors:
            message = f"Unknown tool: {tool_name}"
            # Audited like every other dispatch. A model naming a tool that
            # does not exist is a fact about the run worth keeping — it is
            # the shape of a mission spending its budget on protocol — and
            # an audit that only records the calls that got as far as the
            # capability check cannot show it.
            self._log_audit(tool_name, action, [], "unknown_tool",
                            arguments=arguments, reason=message,
                            exit_code=-1)
            return ToolResult(
                exit_code=-1,
                stdout="",
                stderr=_json.dumps({
                    "error": "unknown_tool",
                    "tool": tool_name,
                    "message": message,
                }),
                tool_name=tool_name,
            )

        descriptor = self._descriptors[tool_name]
        executor = self._executors[tool_name]

        # Resolve scopes: action-specific if available, else full required
        if action and descriptor.action_scopes:
            scopes_to_check = descriptor.action_scopes.get(
                action, descriptor.required_scopes,
            )
        else:
            scopes_to_check = descriptor.required_scopes

        # Per-action metadata
        is_high_risk = (
            (tool_name, action) in HIGH_RISK_ACTIONS if action
            else descriptor.high_risk
        )
        needs_network = (
            (tool_name, action) in NETWORK_ACTIONS if action
            else descriptor.requires_network
        )

        # Panic check — if god mode panic is active, block everything
        if self._god_mode is not None and self._god_mode.is_panicked:
            panic_err = {
                "error": "panic_revoked",
                "tool": tool_name,
                "action": action,
                "message": "Panic switch activated. All tool execution halted.",
            }
            result = ToolResult(
                exit_code=-1,
                stdout="",
                stderr=_json.dumps(panic_err),
                tool_name=tool_name,
                evidence=_json.dumps(panic_err),
            )
            self._log_audit(tool_name, action, scopes_to_check,
                            "panic_revoked", arguments=arguments,
                            reason=panic_err["message"], exit_code=-1)
            return result

        # Preflight announcement for high-risk actions
        if is_high_risk and self._preflight_hook is not None:
            self._preflight_hook({
                "type": "preflight",
                "tool": tool_name,
                "action": action,
                "scopes": list(scopes_to_check),
                "message": f"High-risk tool '{tool_name}' action '{action}' about to execute",
            })

        # Capability check
        verdict = self._capability.check(tool_name, scopes_to_check)
        if not verdict.allowed:
            denial = {
                "error": "capability_denied",
                "tool": tool_name,
                "action": action,
                "missing_scopes": verdict.denied_scopes,
                "message": verdict.reason,
            }
            result = ToolResult(
                exit_code=-1,
                stdout="",
                stderr=_json.dumps(denial),
                tool_name=tool_name,
                evidence=_json.dumps(denial),
            )
            self._log_audit(tool_name, action, scopes_to_check, "denied",
                            arguments=arguments, reason=verdict.reason,
                            exit_code=-1)
            return result

        # Network check
        if needs_network:
            net_scopes = (
                descriptor.network_scopes
                if not action else scopes_to_check
            )
            network_verdict = self._capability.check(tool_name, net_scopes)
            if not network_verdict.allowed:
                denial = {
                    "error": "network_denied",
                    "tool": tool_name,
                    "action": action,
                    "missing_scopes": network_verdict.denied_scopes,
                    "message": network_verdict.reason,
                }
                result = ToolResult(
                    exit_code=-1,
                    stdout="",
                    stderr=_json.dumps(denial),
                    tool_name=tool_name,
                    evidence=_json.dumps(denial),
                )
                self._log_audit(tool_name, action, scopes_to_check, "denied",
                                arguments=arguments,
                                reason=network_verdict.reason, exit_code=-1)
                return result

        # Execute
        saved_runners = []
        started = time.perf_counter()
        try:
            if self._should_use_sandbox(tool_name, action, descriptor):
                runner = self._build_sandbox_runner(descriptor.sandbox_profile)
                saved_runners = self._apply_subprocess_runner(executor, runner)

            if action:
                result = executor(action, *args, **kwargs)
            else:
                result = executor(*args, **kwargs)

            # Handle tuple returns (rc, out, err) and (rc, out, err, evidence).
            # The fourth element is for a tool whose answer is *typed* and
            # not only rendered — an MCP `structuredContent`, say. Without
            # somewhere to put it, a caller that needs one field of a
            # governed view has to parse it back out of the text the model
            # was shown, which is the parse a typed payload exists to avoid.
            if isinstance(result, tuple) and len(result) in (3, 4):
                rc, out, err = result[0], result[1], result[2]
                tool_result = ToolResult(
                    exit_code=rc,
                    stdout=str(out),
                    stderr=str(err),
                    tool_name=tool_name,
                    granted_scopes=list(scopes_to_check),
                    evidence=(str(result[3]) if len(result) == 4 and result[3]
                              else None),
                )
            else:
                # Handle string returns (legacy tools)
                tool_result = ToolResult(
                    exit_code=0,
                    stdout=str(result),
                    stderr="",
                    tool_name=tool_name,
                    granted_scopes=list(scopes_to_check),
                )

            self._log_audit(
                tool_name, action, scopes_to_check, "allowed",
                arguments=arguments,
                exit_code=tool_result.exit_code,
                duration_s=time.perf_counter() - started,
                bytes_out=(len(tool_result.stdout.encode("utf-8"))
                           + len(tool_result.stderr.encode("utf-8"))),
            )
            return tool_result
        except Exception as ex:
            self._log_audit(
                tool_name, action, scopes_to_check, "error",
                arguments=arguments,
                reason=f"{type(ex).__name__}: {ex}",
                exit_code=-1,
                duration_s=time.perf_counter() - started,
            )
            return ToolResult(
                exit_code=-1,
                stdout="",
                stderr=f"Tool execution error: {type(ex).__name__}: {ex}",
                tool_name=tool_name,
            )
        finally:
            self._restore_subprocess_runner(saved_runners)

    def _should_use_sandbox(
        self,
        tool_name: str,
        action: Optional[str],
        descriptor: ToolDescriptor,
    ) -> bool:
        if descriptor.skip_sandbox:
            return False
        if action and (tool_name, action) in SKIP_SANDBOX_ACTIONS:
            return False
        return True

    def _build_sandbox_runner(self, profile: SandboxProfile) -> Callable:
        """A ``run_subprocess``-shaped callable that runs inside the sandbox.

        ``shell`` and ``executable`` are forwarded, not swallowed.  This
        accepted both from :func:`core.tools.executor.run_subprocess` and
        dropped them, leaving each sandbox to re-derive shell mode from
        ``isinstance(cmd, str)`` and to hard-code ``/bin/bash`` — so a
        tool configured with another interpreter got bash without being
        told, and an explicit ``shell=False`` on a string command was
        ignored.  Sandboxing a command must not change which command it
        is.
        """
        # ``shell=None`` rather than ``False``: ``run_subprocess`` always
        # passes the flag, but a caller that installs this runner directly
        # and never had an opinion should keep the sandbox's inference
        # rather than be told, by a default, that nothing is a shell.
        def _runner(cmd, *, shell: Optional[bool] = None, timeout: int = 120,
                    executable: Optional[str] = None, **_kwargs):
            return self._sandbox.execute(
                cmd,
                profile=profile,
                timeout=timeout,
                shell=shell,
                executable=executable,
            )
        return _runner

    def _apply_subprocess_runner(self, executor: Callable, runner: Callable):
        saved = []

        def _set_attr(obj, attr):
            if hasattr(obj, attr):
                saved.append((obj, attr, getattr(obj, attr)))
                setattr(obj, attr, runner)

        _set_attr(executor, "subprocess_runner")
        _set_attr(executor, "_subprocess_runner")

        engine = getattr(executor, "_engine", None)
        if engine is not None:
            _set_attr(engine, "_subprocess_runner")
            worktree = getattr(engine, "_worktree", None)
            if worktree is not None:
                _set_attr(worktree, "_subprocess_runner")

        return saved

    @staticmethod
    def _restore_subprocess_runner(saved):
        for obj, attr, old in saved:
            setattr(obj, attr, old)

    def list_tools(self) -> List[str]:
        """Return names of all registered tools."""
        return list(self._descriptors.keys())

    def describe_tool(self, name: str) -> dict:
        """Return a description dict for a tool."""
        desc = self._descriptors.get(name)
        if desc is None:
            return {"error": f"No such tool: {name}"}
        info = {
            "name": desc.tool_name,
            "description": desc.description,
            "required_scopes": list(desc.required_scopes),
            "requires_network": desc.requires_network,
        }
        if desc.action_scopes:
            info["actions"] = list(desc.action_scopes.keys())
        if desc.input_schema:
            # The schema itself, not only a rendering of it: a caller
            # building a native tool-call request needs the whole thing,
            # and a caller building a prompt wants the summary. Handing
            # out only the summary would make the prompt the authority on
            # a tool's arguments, which is how the two drift.
            info["input_schema"] = desc.input_schema
            info["arguments"] = summarize_input_schema(desc.input_schema)
        return info

    def get_descriptor(self, name: str) -> Optional[ToolDescriptor]:
        """Return the ToolDescriptor for a given tool name."""
        return self._descriptors.get(name)

    def _log_audit(
        self,
        tool_name: str,
        action: Optional[str],
        scopes: List[str],
        verdict: str,
        *,
        arguments: Optional[Dict[str, Any]] = None,
        reason: str = "",
        exit_code: Optional[int] = None,
        duration_s: Optional[float] = None,
        bytes_out: Optional[int] = None,
    ) -> None:
        """Log a dispatch event to the audit logger if present.

        Everything beyond the four positional facts travels in
        :attr:`AuditEntry.detail` as one JSON object, rather than as new
        fields on the entry, and that is deliberate: ``detail`` is the
        field :meth:`core.policy.audit.AuditLogger._redact` runs over, so
        a credential passed as a tool *argument* is covered by the same
        pass that covers one pasted into a message.  A second field would
        be a second thing to remember to redact, and the one that got
        forgotten would be the one carrying the argument.

        ``arguments`` is bounded by :func:`core.bounding.bound_result` at
        the repository's one cap — an audit line is a record, not a
        transcript, and a tool handed a megabyte should not put a megabyte
        on every line of the log.

        :attr:`audit_context` is merged in first, so the caller's keys
        (the mission's ``step``) are there and the bus's own facts win any
        collision.
        """
        if self._audit is None:
            return
        try:
            from core.contracts.schemas import AuditEntry
            rendered, truncated = bound_result(
                _json.dumps(arguments or {}, default=str, sort_keys=True))
            detail: Dict[str, Any] = dict(self.audit_context)
            detail["arguments"] = rendered
            if truncated:
                detail["arguments_truncated"] = True
            if reason:
                detail["reason"] = reason
            if exit_code is not None:
                detail["exit_code"] = exit_code
            if duration_s is not None:
                detail["duration_ms"] = round(duration_s * 1000, 3)
            if bytes_out is not None:
                detail["bytes_out"] = bytes_out
            self._audit.log(AuditEntry(
                event_type="tool_dispatch",
                tool_name=tool_name,
                action=action or "",
                scopes=list(scopes),
                verdict=verdict,
                detail=_json.dumps(detail, default=str, sort_keys=True),
            ))
        except Exception as ex:
            # Dispatch survives — an audit disk filling up must not kill a
            # tool call — but the failure is COUNTED and SAID. This was a
            # bare `pass` for four phases, which meant a bus whose logger
            # had been throwing since the first call looked exactly like a
            # bus whose tools nobody had used. Once to stderr, because the
            # second thousand copies of a full-disk message are what stop
            # anybody reading the first; the counter carries the rest, and
            # the CLI prints it when the mission ends.
            self.audit_failures += 1
            if self.audit_failures == 1:
                print(
                    f"⚠️  audit write FAILED ({type(ex).__name__}: {ex}); "
                    f"tool dispatch continues and this run is no longer "
                    f"fully recorded",
                    file=sys.stderr,
                )
