# core/kv_prefix.py — KV-cacheable static prefix builder

from typing import Callable, Dict, List, Optional

from pydantic import BaseModel


def build_static_prefix(
    system_message: str,
    tool_names: List[str],
    describe_tool_fn: Callable[[str], Dict],
    policy: Optional[BaseModel] = None,
) -> str:
    """Build the invariant prefix shared across Planner->Coder->Reviewer handoffs.

    Composition: System Prompt + Tool Schemas + Policy summary.
    This prefix is identical for every turn in a session, making it
    KV-cacheable by providers that support prefix caching.
    """
    parts = [system_message]

    # Tool schemas
    if tool_names:
        tool_lines = []
        for name in sorted(tool_names):
            desc = describe_tool_fn(name)
            tool_lines.append(f"- {name}: {desc.get('description', 'No description')}")
        parts.append(
            "Available tools:\n" + "\n".join(tool_lines)
        )

    # Policy summary
    if policy is not None:
        policy_data = policy.model_dump()
        policy_lines = []
        for key, value in sorted(policy_data.items()):
            if value:  # skip empty lists, empty strings, etc.
                policy_lines.append(f"  {key}: {value}")
        if policy_lines:
            parts.append(
                "Session policy:\n" + "\n".join(policy_lines)
            )

    return "\n\n".join(parts)
