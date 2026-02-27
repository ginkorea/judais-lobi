# core/kernel/__init__.py

from core.kernel.state import (
    Phase,
    SessionState,
    TRANSITIONS,
    InvalidTransition,
    validate_transition,
)
from core.kernel.budgets import (
    BudgetConfig,
    BudgetExhausted,
    PhaseRetriesExhausted,
    TotalIterationsExhausted,
    PhaseTimeoutExhausted,
    check_phase_retries,
    check_total_iterations,
    check_phase_time,
    check_all_budgets,
)
from core.kernel.orchestrator import (
    Orchestrator,
    RoleDispatcher,
    PhaseResult,
)
from core.kernel.workflows import (
    WorkflowTemplate,
    get_coding_workflow,
    get_generic_workflow,
    select_workflow,
    list_workflows,
)

__all__ = [
    # State machine
    "Phase",
    "SessionState",
    "TRANSITIONS",
    "InvalidTransition",
    "validate_transition",
    # Budgets
    "BudgetConfig",
    "BudgetExhausted",
    "PhaseRetriesExhausted",
    "TotalIterationsExhausted",
    "PhaseTimeoutExhausted",
    "check_phase_retries",
    "check_total_iterations",
    "check_phase_time",
    "check_all_budgets",
    # Orchestrator
    "Orchestrator",
    "RoleDispatcher",
    "PhaseResult",
    # Workflows (Phase 7.0)
    "WorkflowTemplate",
    "get_coding_workflow",
    "get_generic_workflow",
    "select_workflow",
    "list_workflows",
    # Judge (Phase 7.1-7.2) — importable via core.judge directly
]
