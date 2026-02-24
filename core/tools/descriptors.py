# core/tools/descriptors.py — Declarative tool specifications

from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional, Set, Tuple


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
    """Declarative description of what a tool needs to run.

    For multi-action tools, action_scopes maps each action name to its
    specific scope list.  ToolBus checks action_scopes[action] instead of
    required_scopes when an action is provided.  required_scopes is the
    union of all action scopes (used for docs/listing).
    """
    tool_name: str
    required_scopes: List[str] = field(default_factory=list)
    requires_network: bool = False
    network_scopes: List[str] = field(default_factory=list)
    sandbox_profile: SandboxProfile = field(default_factory=SandboxProfile)
    description: str = ""
    high_risk: bool = False
    skip_sandbox: bool = False
    action_scopes: Dict[str, List[str]] = field(default_factory=dict)


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

# ---------------------------------------------------------------------------
# Phase 4a: Consolidated multi-action tools
# ---------------------------------------------------------------------------

FS_DESCRIPTOR = ToolDescriptor(
    tool_name="fs",
    required_scopes=["fs.read", "fs.write", "fs.delete"],
    action_scopes={
        "read":   ["fs.read"],
        "write":  ["fs.write"],
        "delete": ["fs.delete"],
        "list":   ["fs.read"],
        "stat":   ["fs.read"],
    },
    description="Filesystem operations: read, write, delete, list, stat.",
)

GIT_DESCRIPTOR = ToolDescriptor(
    tool_name="git",
    required_scopes=["git.read", "git.write", "git.push", "git.fetch"],
    action_scopes={
        "status": ["git.read"],
        "diff":   ["git.read"],
        "log":    ["git.read"],
        "add":    ["git.write"],
        "commit": ["git.write"],
        "branch": ["git.write"],
        "push":   ["git.push"],
        "pull":   ["git.fetch"],
        "fetch":  ["git.fetch"],
        "stash":  ["git.write"],
        "tag":    ["git.write"],
        "reset":  ["git.write"],
    },
    description="Git operations: status, diff, log, add, commit, branch, push, pull, fetch, stash, tag, reset.",
)

VERIFY_DESCRIPTOR = ToolDescriptor(
    tool_name="verify",
    required_scopes=["verify.run"],
    action_scopes={
        "lint":      ["verify.run"],
        "test":      ["verify.run"],
        "typecheck": ["verify.run"],
        "format":    ["verify.run"],
    },
    description="Verification: lint, test, typecheck, format. Config-driven via .judais-lobi.yml.",
)

# ---------------------------------------------------------------------------
# Per-action metadata sets (consulted by ToolBus dispatch)
# ---------------------------------------------------------------------------

HIGH_RISK_ACTIONS: Set[Tuple[str, str]] = {
    ("git", "push"),
    ("git", "reset"),
    ("fs", "delete"),
}

SKIP_SANDBOX_ACTIONS: Set[Tuple[str, str]] = {
    ("git", "push"),
    ("git", "pull"),
    ("git", "fetch"),
}

NETWORK_ACTIONS: Set[Tuple[str, str]] = {
    ("git", "push"),
    ("git", "pull"),
    ("git", "fetch"),
}

# All pre-built descriptors for iteration
ALL_DESCRIPTORS = [
    SHELL_DESCRIPTOR,
    PYTHON_DESCRIPTOR,
    INSTALL_DESCRIPTOR,
    WEB_SEARCH_DESCRIPTOR,
    FETCH_PAGE_DESCRIPTOR,
    RAG_CRAWLER_DESCRIPTOR,
    VOICE_DESCRIPTOR,
    FS_DESCRIPTOR,
    GIT_DESCRIPTOR,
    VERIFY_DESCRIPTOR,
]
