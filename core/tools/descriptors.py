# core/tools/descriptors.py — Declarative tool specifications

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(frozen=True)
class SandboxProfile:
    """Filesystem and resource constraints for sandbox execution."""
    workspace_writable: bool = True
    allowed_read_paths: List[str] = field(default_factory=list)
    allowed_write_paths: List[str] = field(default_factory=list)
    max_cpu_seconds: Optional[int] = None
    max_memory_bytes: Optional[int] = None
    max_processes: Optional[int] = None


@dataclass(frozen=True)
class ToolDescriptor:
    """Declarative description of what a tool needs to run."""
    tool_name: str
    required_scopes: List[str] = field(default_factory=list)
    requires_network: bool = False
    network_scopes: List[str] = field(default_factory=list)
    sandbox_profile: SandboxProfile = field(default_factory=SandboxProfile)
    description: str = ""


# Pre-built descriptors for all existing tools

SHELL_DESCRIPTOR = ToolDescriptor(
    tool_name="run_shell_command",
    required_scopes=["shell.exec"],
    description="Runs a shell command and returns (exit_code, stdout, stderr).",
)

PYTHON_DESCRIPTOR = ToolDescriptor(
    tool_name="run_python_code",
    required_scopes=["python.exec"],
    description="Runs Python code in elfenv and returns (exit_code, stdout, stderr).",
)

INSTALL_DESCRIPTOR = ToolDescriptor(
    tool_name="install_project",
    required_scopes=["python.exec", "pip.install"],
    description="Installs a Python project via pip.",
)

WEB_SEARCH_DESCRIPTOR = ToolDescriptor(
    tool_name="perform_web_search",
    required_scopes=["http.read"],
    requires_network=True,
    network_scopes=["http.read"],
    description="Performs a DuckDuckGo web search.",
)

FETCH_PAGE_DESCRIPTOR = ToolDescriptor(
    tool_name="fetch_page_content",
    required_scopes=["http.read"],
    requires_network=True,
    network_scopes=["http.read"],
    description="Fetches and extracts text from a URL.",
)

RAG_CRAWLER_DESCRIPTOR = ToolDescriptor(
    tool_name="rag_crawl",
    required_scopes=["fs.read"],
    description="Crawls files and indexes into RAG.",
)

VOICE_DESCRIPTOR = ToolDescriptor(
    tool_name="speak_text",
    required_scopes=["audio.output"],
    description="Speaks text using TTS.",
)

# All pre-built descriptors for iteration
ALL_DESCRIPTORS = [
    SHELL_DESCRIPTOR,
    PYTHON_DESCRIPTOR,
    INSTALL_DESCRIPTOR,
    WEB_SEARCH_DESCRIPTOR,
    FETCH_PAGE_DESCRIPTOR,
    RAG_CRAWLER_DESCRIPTOR,
    VOICE_DESCRIPTOR,
]
