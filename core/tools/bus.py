# core/tools/bus.py — ToolBus registry and dispatch

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Any

from core.tools.descriptors import ToolDescriptor
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


class ToolBus:
    """MCP-style tool registry with capability gating and sandboxed execution.

    Dispatch path: register -> check capabilities -> execute -> result
    """

    def __init__(
        self,
        capability_engine: Optional[CapabilityEngine] = None,
        sandbox: Optional[SandboxRunner] = None,
    ):
        self._descriptors: Dict[str, ToolDescriptor] = {}
        self._executors: Dict[str, Callable] = {}
        self._capability = capability_engine or CapabilityEngine()
        self._sandbox = sandbox or NoneSandbox()

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

    def dispatch(self, tool_name: str, *args: Any, **kwargs: Any) -> ToolResult:
        """Dispatch a tool invocation through capability gating.

        Flow:
        1. Look up descriptor + executor by name
        2. capability_engine.check(tool_name, descriptor.required_scopes)
        3. If denied -> return ToolResult with permission denied error
        4. If network required and no network grant -> return error
        5. Execute the tool
        6. Return ToolResult
        """
        if tool_name not in self._descriptors:
            return ToolResult(
                exit_code=-1,
                stdout="",
                stderr=f"Unknown tool: {tool_name}",
                tool_name=tool_name,
            )

        descriptor = self._descriptors[tool_name]
        executor = self._executors[tool_name]

        # Capability check
        verdict = self._capability.check(tool_name, descriptor.required_scopes)
        if not verdict.allowed:
            return ToolResult(
                exit_code=-1,
                stdout="",
                stderr=(
                    f"Permission denied for tool '{tool_name}': "
                    f"{verdict.reason}"
                ),
                tool_name=tool_name,
            )

        # Network check
        if descriptor.requires_network:
            network_verdict = self._capability.check(
                tool_name, descriptor.network_scopes,
            )
            if not network_verdict.allowed:
                return ToolResult(
                    exit_code=-1,
                    stdout="",
                    stderr=(
                        f"Network access denied for tool '{tool_name}': "
                        f"{network_verdict.reason}"
                    ),
                    tool_name=tool_name,
                )

        # Execute
        try:
            result = executor(*args, **kwargs)

            # Handle tuple returns (rc, out, err)
            if isinstance(result, tuple) and len(result) == 3:
                rc, out, err = result
                return ToolResult(
                    exit_code=rc,
                    stdout=str(out),
                    stderr=str(err),
                    tool_name=tool_name,
                    granted_scopes=descriptor.required_scopes,
                )

            # Handle string returns (legacy tools)
            return ToolResult(
                exit_code=0,
                stdout=str(result),
                stderr="",
                tool_name=tool_name,
                granted_scopes=descriptor.required_scopes,
            )
        except Exception as ex:
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
        return {
            "name": desc.tool_name,
            "description": desc.description,
            "required_scopes": list(desc.required_scopes),
            "requires_network": desc.requires_network,
        }

    def get_descriptor(self, name: str) -> Optional[ToolDescriptor]:
        """Return the ToolDescriptor for a given tool name."""
        return self._descriptors.get(name)
