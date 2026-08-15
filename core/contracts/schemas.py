# core/contracts/schemas.py — All Pydantic v2 contract models

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from core.context.models import RepoMapResult


# ---------------------------------------------------------------------------
# Personality configuration (replaces Elf's abstract properties)
# ---------------------------------------------------------------------------

#: Suffixes ``PersonalityConfig.from_file`` will parse.  Closed on purpose: an
#: unknown suffix is refused by name rather than parsed hopefully as one of
#: these.
PERSONALITY_FILE_FORMATS = (".toml", ".json", ".yaml", ".yml")


class PersonalityConfig(BaseModel):
    """Frozen personality definition. Replaces Elf's abstract properties."""

    model_config = {"frozen": True}

    name: str
    system_message: str
    examples: List[Tuple[str, str]]
    text_color: str = "cyan"
    env_path: str = "~/.elf_env"
    rag_enhancement_style: str = ""
    default_model: Optional[str] = None
    default_provider: Optional[str] = None

    @classmethod
    def from_file(cls, path) -> "PersonalityConfig":
        """Load a personality from a TOML, JSON or YAML file.

        A loader and **not** a new schema: the keys are exactly this
        model's fields, so a file is a ``PersonalityConfig`` written
        down.  Anything else is a refusal naming the key — a typo'd
        ``system_prompt`` that silently produced a personality with an
        empty system message would be discovered by reading the agent's
        output, which is the worst possible place to discover it.

        ``examples`` is optional here although the field is required:
        the few-shot pairs exist to pin a *voice*, and a personality
        whose point is a neutral, governed register has no voice to pin.
        A file that omits them gets none — never a default set borrowed
        from another personality.

        The seam, and its whole reason: JudAIs and Lobi stay
        compiled-in Python and are untouched by this.  A personality
        that makes claims about a platform's rules can instead live in
        the repository that enforces them, where a test can check the
        prompt still matches the code.
        """
        from pathlib import Path

        p = Path(path).expanduser()
        if not p.is_file():
            raise FileNotFoundError(f"No personality file at {p}")

        suffix = p.suffix.lower()
        if suffix not in PERSONALITY_FILE_FORMATS:
            raise ValueError(
                f"{p.name} has suffix {suffix or '(none)'}; a personality file "
                f"is one of {', '.join(PERSONALITY_FILE_FORMATS)}"
            )

        data = cls._parse_personality_file(p, suffix)
        if not isinstance(data, dict):
            raise ValueError(
                f"{p} holds a {type(data).__name__}; a personality file is a "
                f"table of the PersonalityConfig fields"
            )

        known = set(cls.model_fields)
        unknown = sorted(set(data) - known)
        if unknown:
            raise ValueError(
                f"{p} sets unknown key(s): {', '.join(unknown)}. "
                f"A personality file mirrors PersonalityConfig exactly "
                f"({', '.join(sorted(known))})"
            )

        data.setdefault("examples", [])
        data["examples"] = [tuple(pair) for pair in data["examples"]]
        return cls(**data)

    @staticmethod
    def _parse_personality_file(path, suffix: str):
        if suffix == ".json":
            import json
            return json.loads(path.read_text(encoding="utf-8"))
        if suffix in (".yaml", ".yml"):
            try:
                import yaml
            except ImportError as exc:  # pragma: no cover - optional extra
                raise ValueError(
                    f"{path.name} is YAML, which needs pyyaml: "
                    f"pip install 'judais-lobi[mission]'"
                ) from exc
            return yaml.safe_load(path.read_text(encoding="utf-8"))
        try:
            import tomllib
        except ImportError:  # pragma: no cover - Python 3.10 only
            try:
                import tomli as tomllib  # type: ignore[no-redef]
            except ImportError as exc:
                raise ValueError(
                    f"{path.name} is TOML, which needs Python 3.11+ "
                    f"or `pip install tomli`"
                ) from exc
        with open(path, "rb") as handle:
            return tomllib.load(handle)


# ---------------------------------------------------------------------------
# Task & planning contracts
# ---------------------------------------------------------------------------

class TaskContract(BaseModel):
    """Defines the task to be executed."""
    task_id: str
    description: str
    constraints: List[str] = []
    acceptance_criteria: List[str] = []
    allowed_tools: List[str] = []
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PlanStep(BaseModel):
    """A single step in a change plan."""
    description: str
    target_file: Optional[str] = None
    action: str  # "create", "modify", "delete", "test"


class ChangePlan(BaseModel):
    """Ordered list of steps to execute a task."""
    task_id: str
    steps: List[PlanStep]
    target_files: List[str] = []
    rationale: str = ""


# ---------------------------------------------------------------------------
# Memory & retrieval contracts
# ---------------------------------------------------------------------------

class RetrievedChunk(BaseModel):
    """A single chunk retrieved from RAG or memory."""
    source: str
    content: str
    relevance_score: float = 0.0


class MemoryPin(BaseModel):
    """Pins a memory retrieval result into session artifacts."""
    embedding_backend: str
    model_name: str
    query: str
    chunk_ids: List[int]
    similarity_scores: List[float]
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ContextPack(BaseModel):
    """Aggregated context for a task: repo map + retrieved chunks + memory pins."""
    task_id: str
    repo_map_excerpt: str = ""
    retrieved_chunks: List[RetrievedChunk] = []
    memory_pins: List[MemoryPin] = []


# ---------------------------------------------------------------------------
# Patch contracts
# ---------------------------------------------------------------------------

class FilePatch(BaseModel):
    """A single file-level patch (search/replace block)."""
    file_path: str
    search_block: str = ""
    replace_block: str = ""
    action: str = "modify"


class PatchSet(BaseModel):
    """Collection of file patches for a task."""
    task_id: str
    patches: List[FilePatch] = []


# ---------------------------------------------------------------------------
# Execution contracts
# ---------------------------------------------------------------------------

class RunReport(BaseModel):
    """Result of running tests or commands."""
    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""
    passed: bool = False
    duration_seconds: float = 0.0


# ---------------------------------------------------------------------------
# Permission contracts
# ---------------------------------------------------------------------------

class PermissionRequest(BaseModel):
    """Request to use a tool or access a scope."""
    tool_name: str
    scope: str
    reason: str
    requested_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PermissionGrant(BaseModel):
    """Record of a granted permission for deterministic replay."""
    tool_name: str
    scope: str
    granted_by: str = "user"
    grant_issued_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    grant_duration_seconds: Optional[float] = None
    grant_scope: str = "session"


class PolicyPack(BaseModel):
    """Security and sandbox policy for a session."""
    allowed_tools: List[str] = []
    allowed_scopes: List[str] = []
    sandbox_backend: str = "bwrap"
    budget_overrides: Dict[str, Any] = {}
    allowed_mounts: List[str] = []
    allowed_network_domains: List[str] = []


# ---------------------------------------------------------------------------
# Tool tracing contracts (Phase 4)
# ---------------------------------------------------------------------------

class ToolTrace(BaseModel):
    """Records a single tool invocation for audit and replay."""
    tool_name: str
    payload_summary: str = ""
    exit_code: int = 0
    stdout_excerpt: str = ""
    stderr_excerpt: str = ""
    scopes_used: List[str] = []
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Finalization contracts
# ---------------------------------------------------------------------------

class FinalReport(BaseModel):
    """Summary of a completed or halted task."""
    task_description: str
    outcome: str  # "completed" | "halted"
    halt_reason: Optional[str] = None
    artifacts_produced: List[str] = []
    total_iterations: int = 0
    duration_seconds: float = 0.0


# ---------------------------------------------------------------------------
# Profile & God Mode contracts (Phase 4b)
# ---------------------------------------------------------------------------

class ProfileMode(str, Enum):
    """Permission profile levels. Each level includes all scopes from lower levels."""
    SAFE = "safe"       # read-only: fs.read, git.read, verify.run
    DEV = "dev"         # safe + write: fs.write, git.write, python.exec, shell.exec
    OPS = "ops"         # dev + deploy: git.push, git.fetch, pip.install, http.read, fs.delete
    GOD = "god"         # all scopes (wildcard "*")


class GodModeGrant(BaseModel):
    """Records a god mode activation for audit purposes."""
    activated_by: str = "user"
    reason: str
    ttl_seconds: float = 300.0
    activated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    panic_revoked: bool = False


class AuditEntry(BaseModel):
    """Single entry in the append-only audit log."""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    event_type: str = ""
    tool_name: str = ""
    action: str = ""
    scopes: List[str] = []
    profile: str = ""
    verdict: str = ""
    detail: str = ""
    session_id: str = ""


# ---------------------------------------------------------------------------
# Phase → schema mapping (phases with structured output)
# ---------------------------------------------------------------------------

def _build_phase_schemas() -> Dict[str, type]:
    """Build PHASE_SCHEMAS lazily to avoid circular import with core.judge.models."""
    from core.judge.models import JudgeReport
    return {
        "INTAKE": TaskContract,
        "CONTRACT": TaskContract,
        "REPO_MAP": RepoMapResult,
        "PLAN": ChangePlan,
        "RETRIEVE": ContextPack,
        "PATCH": PatchSet,
        "CRITIQUE": JudgeReport,
        "RUN": RunReport,
        "FINALIZE": FinalReport,
    }


# Lazy singleton — built on first access
_PHASE_SCHEMAS = None


def get_phase_schemas() -> Dict[str, type]:
    global _PHASE_SCHEMAS
    if _PHASE_SCHEMAS is None:
        _PHASE_SCHEMAS = _build_phase_schemas()
    return _PHASE_SCHEMAS


# Eager constant for backward compatibility — modules that import PHASE_SCHEMAS
# at import time get the dict. Since core.judge.models has no circular deps
# back to schemas.py, this is safe.
PHASE_SCHEMAS: Dict[str, type] = _build_phase_schemas()
