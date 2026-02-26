# core/kernel/workflows.py — WorkflowTemplate and built-in workflow constants
#
# Phase 7.0: Abstracts the kernel state machine into pluggable templates.
# The coding pipeline becomes one template among many.

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, FrozenSet, List, Optional, Tuple, Type

from pydantic import BaseModel


@dataclass
class WorkflowTemplate:
    """Immutable workflow definition that parameterizes the kernel state machine.

    A workflow template defines the phases, transitions, schemas, branching
    rules, terminal states, and per-phase capability profiles for a task
    domain. The kernel consumes templates — it never hardcodes phase logic.

    The template is selected once at INTAKE and is immutable for the session.
    The LLM controls what happens *inside* a phase. The kernel controls
    *which phase runs next.* (Invariant 8)
    """

    name: str                                           # "coding", "generic", "redteam", ...
    phases: Tuple[str, ...]                             # Ordered phase names (strings, not enum)
    transitions: Dict[str, FrozenSet[str]]              # phase -> set of valid next phases
    phase_schemas: Dict[str, Type[BaseModel]]           # phase -> Pydantic model for artifact validation
    phase_order: Tuple[str, ...]                        # Linear progression (excludes branch targets)
    branch_rules: Dict[str, Callable]                   # phase -> function(result) -> next_phase_name
    terminal_phases: FrozenSet[str]                     # {"HALTED", "COMPLETED"}
    phase_capabilities: Dict[str, FrozenSet[str]]       # phase -> allowed capability tags for that phase
    default_budget_overrides: Dict[str, Any] = field(default_factory=dict)
    required_scopes: List[str] = field(default_factory=list)
    description: str = ""

    def __hash__(self):
        return hash(self.name)

    def __eq__(self, other):
        if isinstance(other, WorkflowTemplate):
            return self.name == other.name
        return NotImplemented


def _build_coding_workflow() -> WorkflowTemplate:
    """Build the CODING_WORKFLOW constant.

    Deferred to a function so imports from contracts/schemas.py happen at
    call time, avoiding circular import issues.
    """
    from core.kernel.state import Phase, TRANSITIONS
    from core.contracts.schemas import PHASE_SCHEMAS

    return WorkflowTemplate(
        name="coding",
        phases=(
            "INTAKE", "CONTRACT", "REPO_MAP", "PLAN", "RETRIEVE",
            "PATCH", "CRITIQUE", "RUN", "FIX", "FINALIZE",
            "HALTED", "COMPLETED",
        ),
        transitions=dict(TRANSITIONS),
        phase_schemas=dict(PHASE_SCHEMAS),
        phase_order=(
            "INTAKE", "CONTRACT", "REPO_MAP", "PLAN",
            "RETRIEVE", "PATCH", "CRITIQUE", "RUN",
        ),
        branch_rules={
            "RUN": lambda result: "FINALIZE" if result.success else "FIX",
            "FIX": lambda result: "PATCH",
            "FINALIZE": lambda result: "COMPLETED",
        },
        terminal_phases=frozenset({"HALTED", "COMPLETED"}),
        phase_capabilities={
            "INTAKE":   frozenset({"fs.read"}),
            "CONTRACT": frozenset({"fs.read"}),
            "REPO_MAP": frozenset({"fs.read", "git.read"}),
            "PLAN":     frozenset({"fs.read", "git.read"}),
            "RETRIEVE": frozenset({"fs.read", "git.read"}),
            "PATCH":    frozenset({"fs.read", "fs.write", "git.write"}),
            "CRITIQUE": frozenset({"fs.read", "git.read"}),
            "RUN":      frozenset({"fs.read", "verify.run"}),
            "FIX":      frozenset({"fs.read", "git.read"}),
            "FINALIZE": frozenset({"fs.read", "git.read"}),
        },
        required_scopes=[
            "fs.read", "fs.write", "git.read", "git.write", "verify.run",
        ],
        description=(
            "Full software development pipeline with repo map, patching, "
            "and test loop."
        ),
    )


def _build_generic_workflow() -> WorkflowTemplate:
    """Build the GENERIC_WORKFLOW constant."""
    from core.contracts.schemas import TaskContract, ChangePlan, FinalReport

    return WorkflowTemplate(
        name="generic",
        phases=(
            "INTAKE", "PLAN", "EXECUTE", "EVALUATE",
            "FINALIZE", "HALTED", "COMPLETED",
        ),
        transitions={
            "INTAKE":    frozenset({"PLAN", "HALTED"}),
            "PLAN":      frozenset({"EXECUTE", "HALTED"}),
            "EXECUTE":   frozenset({"EVALUATE", "HALTED"}),
            "EVALUATE":  frozenset({"PLAN", "EXECUTE", "FINALIZE", "HALTED"}),
            "FINALIZE":  frozenset({"COMPLETED", "HALTED"}),
            "HALTED":    frozenset(),
            "COMPLETED": frozenset(),
        },
        phase_schemas={
            "INTAKE":   TaskContract,
            "PLAN":     ChangePlan,
            "FINALIZE": FinalReport,
        },
        phase_order=("INTAKE", "PLAN", "EXECUTE", "EVALUATE"),
        branch_rules={
            "EVALUATE": lambda result: "FINALIZE" if result.success else "PLAN",
            "FINALIZE": lambda result: "COMPLETED",
        },
        terminal_phases=frozenset({"HALTED", "COMPLETED"}),
        phase_capabilities={
            "INTAKE":   frozenset({"fs.read"}),
            "PLAN":     frozenset({"fs.read"}),
            "EXECUTE":  frozenset({"fs.read", "fs.write", "shell.exec", "python.exec"}),
            "EVALUATE": frozenset({"fs.read", "verify.run"}),
            "FINALIZE": frozenset({"fs.read"}),
        },
        required_scopes=["fs.read", "fs.write", "shell.exec", "python.exec", "verify.run"],
        description=(
            "Flexible pipeline for arbitrary structured tasks. "
            "EXECUTE dispatches to any tool on the bus."
        ),
    )


# Module-level constants — built lazily to avoid circular imports.
# Use the accessor functions below for guaranteed initialization.

_CODING_WORKFLOW: Optional[WorkflowTemplate] = None
_GENERIC_WORKFLOW: Optional[WorkflowTemplate] = None


def get_coding_workflow() -> WorkflowTemplate:
    """Return the CODING_WORKFLOW singleton."""
    global _CODING_WORKFLOW
    if _CODING_WORKFLOW is None:
        _CODING_WORKFLOW = _build_coding_workflow()
    return _CODING_WORKFLOW


def get_generic_workflow() -> WorkflowTemplate:
    """Return the GENERIC_WORKFLOW singleton."""
    global _GENERIC_WORKFLOW
    if _GENERIC_WORKFLOW is None:
        _GENERIC_WORKFLOW = _build_generic_workflow()
    return _GENERIC_WORKFLOW


# Registry of known workflow templates (name -> accessor)
_WORKFLOW_REGISTRY: Dict[str, Callable[[], WorkflowTemplate]] = {
    "coding":  get_coding_workflow,
    "generic": get_generic_workflow,
}


def select_workflow(
    *,
    cli_flag: Optional[str] = None,
    policy_workflow: Optional[str] = None,
    task_description: Optional[str] = None,
) -> WorkflowTemplate:
    """Select a workflow template.

    Selection hierarchy:
    1. CLI flag: --workflow coding → hardcoded choice, no LLM.
    2. Policy file: workflow field in PolicyPack → deterministic.
    3. Default: CODING_WORKFLOW (future: LLM classification).
    """
    name = cli_flag or policy_workflow

    if name is not None:
        accessor = _WORKFLOW_REGISTRY.get(name)
        if accessor is None:
            raise ValueError(
                f"Unknown workflow: {name!r}. "
                f"Available: {sorted(_WORKFLOW_REGISTRY)}"
            )
        return accessor()

    # Default: coding workflow
    return get_coding_workflow()
