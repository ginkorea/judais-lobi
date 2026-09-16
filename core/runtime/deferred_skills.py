"""Task-scoped skill exposure inside an already validated mission ceiling.

Selecting a skill changes what the model sees, never its principal, grants or
sandbox. Full manifests are still validated at startup. Evidence obligations
accumulate across selections so hiding a skill cannot erase a check after use.

This controls direct execution prose, schemas and answer checks, not the
optional cognitive shadow: configured advisory rule packs keep their existing
full-library semantics when cognition is explicitly enabled.
"""

from __future__ import annotations

import copy
from typing import Any, Callable, Optional, Sequence

from core.runtime.skills import SkillManifest, SkillManifestError, compose_manifests
from core.tools.descriptors import ToolDescriptor, same_tool

SELECT_SKILLS = "select_skills"


class DeferredSkills:
    """The configured library, current reading and cumulative obligations."""

    def __init__(self, manifests: Sequence[SkillManifest], *,
                 validator_factory: Optional[Callable[..., Any]] = None,
                 critic: Any = None):
        self.manifests = tuple(manifests)
        names = [manifest.name for manifest in self.manifests]
        if not names or len(set(names)) != len(names):
            raise SkillManifestError("deferred skills need unique configured skill IDs")
        self.ceiling = compose_manifests(self.manifests)
        self.active: tuple[str, ...] = ()
        self.used: tuple[str, ...] = ()
        self.validator_factory = validator_factory
        self.critic = critic
        self.tool_name = SELECT_SKILLS

    def clone(self) -> "DeferredSkills":
        """Each run changes its own selection, including child runs."""
        return copy.copy(self)

    def selected(self, *, cumulative: bool = False) -> list[SkillManifest]:
        names = self.used if cumulative else self.active
        by_name = {manifest.name: manifest for manifest in self.manifests}
        return [by_name[name] for name in names]

    def select(self, names: Any) -> None:
        known = {manifest.name for manifest in self.manifests}
        if (not isinstance(names, list) or not all(isinstance(name, str)
                                                  for name in names)
                or any(name not in known for name in names)):
            raise ValueError("skills must be a list of configured skill IDs")
        # Validate the proposed composition BEFORE committing either state.
        active = tuple(dict.fromkeys(names))
        used = tuple(dict.fromkeys([*self.used, *active]))
        by_name = {manifest.name: manifest for manifest in self.manifests}
        if used:
            compose_manifests([by_name[name] for name in used])
        self.active, self.used = active, used

    def exposes(self, name: str) -> bool:
        return any(same_tool(name, tool) for manifest in self.selected()
                   for tool in manifest.allowed_tools)

    def prompt(self) -> str:
        lines = [
            "Configured skill and capability index (loadable, not all active):",
            f"Call {self.tool_name} with the skill IDs needed for this task. "
            "You may select several, then replace that selection as the task "
            "changes. Full instructions and tool schemas become available on "
            "the next step. A greeting needs no skill selection. Unselected "
            "tools cannot be called until selected, but are not thereby absent. "
            "A question about platform data requires selecting its relevant "
            "skill and using the resulting lookup tool, not answering from "
            "memory or reporting that the initial tool list lacks it. "
            "Selection grants no additional authority.",
        ]
        for manifest in self.manifests:
            description = manifest.description or next(
                (part.partition(":")[2].strip()
                 for part in manifest.prompt.split("\n\n")
                 if part.startswith("When to use:")), "")
            description = " ".join(description.split())[:240]
            tools = ", ".join(manifest.allowed_tools)
            lines.append(f"- {manifest.name}: {description}\n  tools after selection: {tools}")
        selected = self.selected()
        if selected:
            lines.extend(["Active skill instructions:",
                          compose_manifests(selected).prompt])
        return "\n\n".join(lines)

    def grounding(self, offered: Sequence[str]) -> Any:
        selected = self.selected(cumulative=True)
        if not selected or self.validator_factory is None:
            return None
        return self.validator_factory(compose_manifests(selected), offered)

    def needs_critic(self) -> bool:
        selected = self.selected(cumulative=True)
        if not selected:
            return False
        return bool((compose_manifests(selected).grounding or {}).get("critic"))

    def descriptor(self) -> ToolDescriptor:
        return ToolDescriptor(
            tool_name=self.tool_name,
            description="Load the configured skills and tools needed to answer "
                        "the current request. Tools named in the capability "
                        "index are exposed after selection when available on "
                        "this plane, on the next step. "
                        "Use this before claiming a relevant tool is unavailable. This "
                        "replaces visible skill instructions and tool schemas, "
                        "not permissions. Select several IDs for a multi-part "
                        "task; select another set when the task changes.",
            input_schema={
                "type": "object", "additionalProperties": False,
                "properties": {"skills": {"type": "array", "items": {
                    "type": "string", "enum": [m.name for m in self.manifests]}}},
                "required": ["skills"],
            },
        )
