# core/tools/descriptors.py — Declarative tool specifications

import re
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Optional, Set, Tuple

#: Everything that separates one segment of a tool name from the next, in
#: every convention any of our servers uses: the dot of a governed
#: ``tool_id``, the underscore a host demands, the dot the bridge adds to
#: namespace a discovered server.
_NOT_A_SEGMENT = re.compile(r"[^a-z0-9]+")


def tool_key(name: Any) -> str:
    """One tool reduced to the thing **every spelling of it shares**.

    ``catalog.search_assets``, ``catalog_search_assets`` and
    ``mcp.catalog_search_assets`` are one tool written three ways, and on
    10 August 2026 a single mission prompt carried all three: the dotted
    form in the catalogue prose and in the skill's grounding ``ignore``
    list, the bare form in the skill's own prose and its closed set, the
    namespaced form in the dispatch table and the tool schemas. It cost
    two turns of a fourteen-turn budget — one to ``reply_rejected`` on the
    bare form, and one to a repair that **deleted a true sentence**,
    because the identifier check had flagged the *namespaced* form as an
    invented asset id while the ``ignore`` list carried only the dotted
    one.

    Three places in this harness compare tool names across conventions —
    :meth:`SkillManifest.resolve`, ``MissionRunner._near_miss``, and the
    grounding checks' ``ignored`` — and three implementations of "same
    tool, different spelling" is that same defect one level up. This is
    the one implementation. **A convention nobody has invented yet reduces
    here too**, which is what stops a fourth spelling from costing what
    the third one did: the rule is about separators, not about a list of
    known prefixes.

    The reduction keeps the *segments* and throws away only the choice of
    separator and of case: ``catalog.search_assets`` and
    ``catalog_search_assets`` both become ``catalog.search.assets``, while
    ``mcp.catalog_search_assets`` becomes ``mcp.catalog.search.assets`` and
    is therefore recognisably that same tool under a namespace rather than
    a different one. Flattening the separators away entirely would lose
    that boundary and make ``xruns.get`` a spelling of ``runs.get``.

    Deliberately not a normaliser anything prints. It answers *"are these
    the same tool"* and nothing else; the name a human or a model reads is
    always the one its own surface authored.
    """
    return ".".join(
        part for part in _NOT_A_SEGMENT.split(str(name or "").lower()) if part)


def same_tool(one: Any, other: Any) -> bool:
    """Whether two names name one tool. An empty name names nothing.

    Equal after reduction, or one is the other under a namespace — the
    bridge prefixes a discovered server's tools so that one server cannot
    shadow another's, and a manifest, a skill's prose and a model all
    write the unprefixed name. The suffix is anchored to a segment
    boundary, so ``runs.get`` is not a spelling of ``xruns.get``.
    """
    left, right = tool_key(one), tool_key(other)
    if not left or not right:
        return False
    return (left == right
            or left.endswith(f".{right}")
            or right.endswith(f".{left}"))


@dataclass(frozen=True)
class SandboxProfile:
    """Filesystem, network and resource constraints for sandbox execution.

    Every field is something a backend has to *keep*, not a hint it may
    read: :class:`~core.tools.sandbox.BwrapSandbox` turns each one into a
    bwrap argument or an rlimit, and a field no backend honours is a field
    that should not be declared here at all.

    :attr:`allow_network` is the field that exists because the backend was
    louder than the profile. ``BwrapSandbox`` passed ``--unshare-net``
    unconditionally, so the day the sandbox is switched on by default
    every networked tool breaks at once — and not with a refusal naming
    the reason, which is the only kind of failure this framework wants,
    but with a DNS error raised three libraries deep inside
    ``perform_web_search``. It is deny-by-default because that is the
    right default for ``run_shell_command``; a tool that reaches the
    network says so in its own descriptor's profile, next to the scopes
    it asks for, and the tools that stay silent are offline by
    construction rather than by nobody having thought about it.
    """
    workspace_writable: bool = True
    allow_network: bool = False
    allowed_read_paths: List[str] = field(default_factory=list)
    allowed_write_paths: List[str] = field(default_factory=list)
    max_cpu_seconds: Optional[int] = None
    max_memory_bytes: Optional[int] = None
    max_processes: Optional[int] = None
    #: Environment variables a child under this profile is allowed to
    #: inherit *by name*, on top of the fixed allow-list every sandboxed
    #: child gets (``PATH``, ``HOME``, ``LANG``/``LC_*``, ``TERM``,
    #: ``TMPDIR``). The bus builds the child's environment from these two
    #: lists in one place and hands it to ``execute(env=…)``; neither
    #: backend reads ``os.environ`` on its own except to resolve exactly
    #: these names. A field, not a hint: it means the same thing on
    #: ``NoneSandbox`` and ``BwrapSandbox``, so a tool that genuinely needs
    #: a key — ``OPENAI_API_KEY`` for the embedding endpoint the RAG crawl
    #: and web research reach, the proxy variables ``pip`` reads — declares
    #: it here beside the scopes it asks for, and a tool that stays silent
    #: runs with the host's secrets stripped out by construction rather
    #: than by nobody having thought about it.
    env_passthrough: Tuple[str, ...] = ()


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

#: ``pip install`` is a network client wearing a subprocess. It is the one
#: tool here whose need for the network is invisible in its scopes —
#: ``pip.install`` reads like a filesystem effect — and it is the tool a
#: sandbox would break most confusingly, with pip's own retry banner
#: repeated five times before it gave up.
#: ``env_passthrough`` names the variables ``pip`` genuinely reads and the
#: allow-list would otherwise strip: the proxy set behind which a whole
#: category of hosts sits, and the index/cache pointers an operator uses to
#: aim pip at an internal mirror.  It is the one shipped descriptor that
#: needs a key beyond the fixed allow-list, because it is the one shipped
#: tool that both shells out *and* reaches the network — the web/RAG tools
#: reach the network in-process and never touch a sandboxed child, so an
#: ``env_passthrough`` on them would forward nothing.
INSTALL_DESCRIPTOR = ToolDescriptor(
    tool_name="install_project",
    required_scopes=["python.exec", "pip.install"],
    sandbox_profile=SandboxProfile(
        allow_network=True,
        env_passthrough=(
            "http_proxy", "https_proxy", "no_proxy",
            "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
            "PIP_INDEX_URL", "PIP_EXTRA_INDEX_URL", "PIP_CACHE_DIR",
        ),
    ),
    description="Installs a Python project via pip.",
)

WEB_SEARCH_DESCRIPTOR = ToolDescriptor(
    tool_name="perform_web_search",
    required_scopes=["http.read"],
    requires_network=True,
    network_scopes=["http.read"],
    sandbox_profile=SandboxProfile(allow_network=True),
    description="Performs a DuckDuckGo web search.",
)

WEB_RESEARCH_DESCRIPTOR = ToolDescriptor(
    tool_name="perform_web_research",
    required_scopes=["http.read"],
    requires_network=True,
    network_scopes=["http.read"],
    sandbox_profile=SandboxProfile(allow_network=True),
    description="Searches the web and fetches top pages into a research pack.",
)

FETCH_PAGE_DESCRIPTOR = ToolDescriptor(
    tool_name="fetch_page_content",
    required_scopes=["http.read"],
    requires_network=True,
    network_scopes=["http.read"],
    sandbox_profile=SandboxProfile(allow_network=True),
    description="Fetches and extracts text from a URL.",
)

#: The crawl reads local files; the *indexing* half of it calls an
#: embedding endpoint, so the tool reaches the network even though every
#: input it names is a path. Its ``requires_network`` says otherwise and
#: is left alone here deliberately — that flag gates a capability check,
#: and flipping it is a governance change, not a sandbox one.
RAG_CRAWLER_DESCRIPTOR = ToolDescriptor(
    tool_name="rag_crawl",
    required_scopes=["fs.read"],
    sandbox_profile=SandboxProfile(allow_network=True),
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

#: Not ``allow_network=True``: a profile is per *tool* and git's need for
#: the network is per *action*. ``push``/``pull``/``fetch`` are in
#: :data:`SKIP_SANDBOX_ACTIONS` and never see a sandbox at all, so opening
#: the namespace here would buy nothing and hand ``git status`` a network
#: it has no use for. When profiles become per-action, this is the first
#: descriptor to revisit.
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

# ---------------------------------------------------------------------------
# Phase 15: memory is a plane, and it is governed like one
# ---------------------------------------------------------------------------
#
# Two descriptors and two scopes, declared HERE with everything else a bus
# dispatches, so that memory is not a side door: a recall is capability-
# checked, audited and redacted exactly as a filesystem read is, and the
# profile table in `core.policy.profiles` is the one place that says who may
# do which.  The executors are the bank's — `MemoryBank.register_on` binds
# them, because they close over one principal's partition of one directory
# — and they are registered for the length of a run, like the mission result
# store and for the same reason.
#
# Reading is SAFE and writing is DEV, and the split is the honest one.  A
# recall reaches nothing this deployment was not already told; a write pins
# a sentence into every future system turn of this principal, which is a
# durable effect on later runs and belongs beside `fs.write`.

#: The tool a mission calls to search memory.  Flat, like the other
#: compiled-in tools and unlike a bridged name, because it is local.
MEMORY_RECALL_TOOL = "memory_recall"

#: The tool a mission calls to edit its own core memory.
MEMORY_WRITE_TOOL = "memory_write"

MEMORY_RECALL_DESCRIPTOR = ToolDescriptor(
    tool_name=MEMORY_RECALL_TOOL,
    required_scopes=["memory.read"],
    description=(
        "Search remembered notes and past runs. Nothing is retrieved "
        "automatically — call this when the objective touches something "
        "this deployment may already know. Returns a few ranked, dated "
        "results within a token budget; a recalled fact is DATED and may "
        "need re-verifying. Reaches no network and no new data."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "What you are trying to remember, in the "
                               "words you would search for. Required unless "
                               "handle is given.",
            },
            "k": {
                "type": "integer",
                "description": "How many results to return, at most 5.",
            },
            "kind": {
                "type": "string",
                "enum": ["note", "run"],
                "description": "Restrict to distilled notes or to past runs. "
                               "Omit for both.",
            },
            "since": {
                "type": "string",
                "description": "Only results at or after this date "
                               "(YYYY-MM-DD).",
            },
            "handle": {
                "type": "string",
                "description": "Read one result whole by its handle — a note "
                               "(n7) or a past run (run_...) — instead of "
                               "searching.",
            },
        },
        "required": [],
    },
)

MEMORY_WRITE_DESCRIPTOR = ToolDescriptor(
    tool_name=MEMORY_WRITE_TOOL,
    required_scopes=["memory.write"],
    action_scopes={
        "add":     ["memory.write"],
        "replace": ["memory.write"],
        "delete":  ["memory.write"],
    },
    description=(
        "Edit core memory: add, replace or delete one pinned block "
        "(preference, fact, lesson, persona). Core memory is small, capped "
        "and read at the top of EVERY future run of this principal, so "
        "write only what will still matter next month, and say why "
        "(reason) and what it came from (source)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["add", "replace", "delete"],
                "description": "What to do to the block.",
            },
            "label": {
                "type": "string",
                "description": "The block's key, e.g. prefers-short-answers. "
                               "One block per label.",
            },
            "kind": {
                "type": "string",
                "enum": ["preference", "fact", "lesson", "persona"],
                "description": "What sort of thing this is.",
            },
            "body": {
                "type": "string",
                "description": "The sentence to remember. One or two lines.",
            },
            "reason": {
                "type": "string",
                "description": "Why this belongs in memory every future run "
                               "will read. Required.",
            },
            "source": {
                "type": "string",
                "description": "The evidence it came from: a result handle "
                               "(r3), a run id, or 'operator'. Required for "
                               "add and replace.",
            },
        },
        "required": ["action", "label", "reason"],
    },
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
    MEMORY_RECALL_DESCRIPTOR,
    MEMORY_WRITE_DESCRIPTOR,
]
