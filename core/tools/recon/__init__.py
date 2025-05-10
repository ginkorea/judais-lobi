# tools/recon/recon_tool.py
from abc import ABC

from core.tools.tool import Tool

class ReconTool(Tool, ABC):
    """Base class for all Recon Tools with shared utilities like context summarization."""

    @staticmethod
    def summarize_context(target_package: dict) -> str:
        sections = []
        for key, value in target_package.items():
            if key == "target":
                continue
            if isinstance(value, dict):
                sections.append(f"### {key}:\n" + "\n".join(f"- {k}: {v}" for k, v in value.items() if isinstance(v, str)))
            elif isinstance(value, list):
                sections.append(f"### {key}:\n" + "\n".join(f"- {v}" for v in value if isinstance(v, str)))
            else:
                sections.append(f"- {key}: {value}")
        return "\n\n".join(sections) or "(No additional context)"
