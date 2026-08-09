# core/tools/descriptors.py — Declarative tool specifications

from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Optional, Set, Tuple


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
    #: JSON Schema for the tool's arguments, as the tool itself declares
    #: them.  For a bridged MCP tool this is ``tools/list``'s
    #: ``inputSchema`` verbatim.
    #:
    #: It is carried rather than flattened into the description because
    #: the description is prose and a schema is not: types, ``required``
    #: and enums are what stop a model guessing ``limit="ten"`` or
    #: inventing a facet the server does not have, and they are also the
    #: only thing a native tool-calling request can be built from. A
    #: descriptor that reduced them to "Arguments: a, b, c." had thrown
    #: away everything except the names.
    input_schema: Dict[str, Any] = field(default_factory=dict)


#: How many enum members are shown before the rest are counted.  An enum
#: is the most useful part of a schema for a model choosing a facet, and
#: the least useful when it is ninety codes long.
MAX_ENUM_SHOWN = 8


def summarize_input_schema(schema: Optional[Dict[str, Any]]) -> str:
    """One compact line of argument types, or ``""``.

    ``q (string, required), type (string: dataset|model|service), limit (integer)``

    Compact because it is rendered once per tool into a mission's system
    message, and a 20b model given twelve tools' worth of pretty-printed
    JSON Schema has spent its context before the objective arrives.  It
    is a *summary*: the authority is :attr:`ToolDescriptor.input_schema`,
    which is kept whole for the callers that need it.
    """
    if not schema:
        return ""
    properties = schema.get("properties")
    if not isinstance(properties, dict) or not properties:
        return ""
    required = schema.get("required")
    required = set(required) if isinstance(required, (list, tuple, set)) else set()

    parts: List[str] = []
    for name, spec in properties.items():
        spec = spec if isinstance(spec, dict) else {}
        notes: List[str] = []
        kind = _schema_type(spec)
        if kind:
            notes.append(kind)
        enum = spec.get("enum")
        if isinstance(enum, (list, tuple)) and enum:
            shown = [str(v) for v in list(enum)[:MAX_ENUM_SHOWN]]
            rest = len(enum) - len(shown)
            values = "|".join(shown) + (f"|+{rest} more" if rest > 0 else "")
            notes[-1:] = [f"{notes[-1]}: {values}"] if notes else [values]
        if name in required:
            notes.append("required")
        parts.append(f"{name} ({', '.join(notes)})" if notes else str(name))
    return ", ".join(parts)


def _schema_type(spec: Dict[str, Any]) -> str:
    """The declared type, including the ``anyOf`` shape MCP servers emit.

    A FastMCP optional argument is ``anyOf: [{type: string}, {type:
    null}]``; reporting that as no type at all would hide the one thing
    the model needed to know.
    """
    kind = spec.get("type")
    if isinstance(kind, str):
        return kind
    if isinstance(kind, (list, tuple)):
        return "|".join(str(k) for k in kind if k != "null")
    for key in ("anyOf", "oneOf"):
        options = spec.get(key)
        if isinstance(options, (list, tuple)):
            kinds = [
                _schema_type(o) for o in options
                if isinstance(o, dict) and o.get("type") != "null"
            ]
            kinds = [k for k in kinds if k]
            if kinds:
                return "|".join(dict.fromkeys(kinds))
    return ""


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

WEB_RESEARCH_DESCRIPTOR = ToolDescriptor(
    tool_name="perform_web_research",
    required_scopes=["http.read"],
    requires_network=True,
    network_scopes=["http.read"],
    description="Searches the web and fetches top pages into a research pack.",
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

REPO_MAP_DESCRIPTOR = ToolDescriptor(
    tool_name="repo_map",
    required_scopes=["fs.read", "git.read"],
    action_scopes={
        "build":     ["fs.read", "git.read"],
        "excerpt":   ["fs.read", "git.read"],
        "status":    ["fs.read", "git.read"],
        "visualize": ["fs.read", "git.read"],
        "symbol":    ["fs.read"],
    },
    description=(
        "Repository map: build, excerpt (task-scoped), status, "
        "visualize (DOT/Mermaid), symbol (one function or class body with "
        "its path:start-end citation, instead of the whole file)."
    ),
)

# ---------------------------------------------------------------------------
# Phase 6: Patch engine tool
# ---------------------------------------------------------------------------

PATCH_DESCRIPTOR = ToolDescriptor(
    tool_name="patch",
    required_scopes=["fs.read", "fs.write", "git.read", "git.write"],
    action_scopes={
        "validate": ["fs.read"],
        "apply":    ["fs.read", "fs.write", "git.write"],
        "diff":     ["fs.read", "git.read"],
        "rollback": ["git.write"],
        "merge":    ["git.write"],
        "status":   ["fs.read", "git.read"],
    },
    description="Patch engine: validate, apply, diff, rollback, merge, status.",
)

# All pre-built descriptors for iteration
ALL_DESCRIPTORS = [
    SHELL_DESCRIPTOR,
    PYTHON_DESCRIPTOR,
    INSTALL_DESCRIPTOR,
    WEB_SEARCH_DESCRIPTOR,
    WEB_RESEARCH_DESCRIPTOR,
    FETCH_PAGE_DESCRIPTOR,
    RAG_CRAWLER_DESCRIPTOR,
    VOICE_DESCRIPTOR,
    FS_DESCRIPTOR,
    GIT_DESCRIPTOR,
    VERIFY_DESCRIPTOR,
    REPO_MAP_DESCRIPTOR,
    PATCH_DESCRIPTOR,
]
