# core/tools/bus.py — ToolBus registry and dispatch

import json as _json
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Any

from core.tools.descriptors import (
    ToolDescriptor,
    HIGH_RISK_ACTIONS,
    SKIP_SANDBOX_ACTIONS,
    NETWORK_ACTIONS,
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
    """MCP-style tool registry with capability gating and sandboxed execution.

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

    @property
    def capability_engine(self) -> CapabilityEngine:
        return self._capability

    @property
    def sandbox(self) -> SandboxRunner:
        return self._sandbox

    def register(self, descriptor: ToolDescriptor, executor: Callable) -> None:
        """Register a tool with its descriptor and executor."""
        self._descriptors[descriptor.tool_name] = descriptor
        self._executors[descriptor.tool_name] = executor

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
        if tool_name not in self._descriptors:
            return ToolResult(
                exit_code=-1,
                stdout="",
                stderr=_json.dumps({
                    "error": "unknown_tool",
                    "tool": tool_name,
                    "message": f"Unknown tool: {tool_name}",
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
            self._log_audit(tool_name, action, scopes_to_check, "panic_revoked")
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
            self._log_audit(tool_name, action, scopes_to_check, "denied")
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
                self._log_audit(tool_name, action, scopes_to_check, "denied")
                return result

        # Execute
        try:
            if action:
                result = executor(action, *args, **kwargs)
            else:
                result = executor(*args, **kwargs)

            # Handle tuple returns (rc, out, err)
            if isinstance(result, tuple) and len(result) == 3:
                rc, out, err = result
                tool_result = ToolResult(
                    exit_code=rc,
                    stdout=str(out),
                    stderr=str(err),
                    tool_name=tool_name,
                    granted_scopes=list(scopes_to_check),
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

            self._log_audit(tool_name, action, scopes_to_check, "allowed")
            return tool_result
        except Exception as ex:
            self._log_audit(tool_name, action, scopes_to_check, "error")
            return ToolResult(
                exit_code=-1,
                stdout="",
                stderr=f"Tool execution error: {type(ex).__name__}: {ex}",
                tool_name=tool_name,
            )

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
    ) -> None:
        """Log a dispatch event to the audit logger if present."""
        if self._audit is None:
            return
        try:
            from core.contracts.schemas import AuditEntry
            self._audit.log(AuditEntry(
                event_type="tool_dispatch",
                tool_name=tool_name,
                action=action or "",
                scopes=list(scopes),
                verdict=verdict,
            ))
        except Exception:
            pass  # Audit logging must never break dispatch
