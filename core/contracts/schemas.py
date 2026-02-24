# core/contracts/schemas.py — All Pydantic v2 contract models for Phase 3

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Personality configuration (replaces Elf's abstract properties)
# ---------------------------------------------------------------------------

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
# Phase → schema mapping (phases with structured output)
# ---------------------------------------------------------------------------

PHASE_SCHEMAS: Dict[str, type] = {
    "INTAKE": TaskContract,
    "CONTRACT": TaskContract,
    "PLAN": ChangePlan,
    "RETRIEVE": ContextPack,
    "PATCH": PatchSet,
    "RUN": RunReport,
    "FINALIZE": FinalReport,
}
