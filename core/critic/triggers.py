# core/critic/triggers.py — Trigger policy logic

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Tuple

from core.critic.config import CriticConfig
from core.critic.models import CriticTriggerContext


SECURITY_KEYWORDS = (
    "auth",
    "oauth",
    "jwt",
    "token",
    "crypto",
    "encrypt",
    "decrypt",
    "password",
    "secret",
    "permission",
    "acl",
    "rbac",
    "sso",
    "session",
)

DEPENDENCY_FILES = {
    "requirements.txt",
    "requirements.in",
    "pyproject.toml",
    "poetry.lock",
    "pipfile",
    "pipfile.lock",
    "package.json",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "cargo.toml",
    "cargo.lock",
    "go.mod",
    "go.sum",
    "gemfile",
    "gemfile.lock",
    "composer.json",
    "composer.lock",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "gradle.properties",
}


def should_invoke_critic(
    context: CriticTriggerContext,
    config: CriticConfig,
) -> Tuple[bool, str]:
    if not config.enabled:
        return False, "disabled"
    if context.critic_calls_this_session >= context.max_calls_per_session:
        return False, "budget_exhausted"

    if config.trigger_after_plan:
        if context.current_phase == "PLAN" and context.next_phase == "RETRIEVE":
            return True, "after_plan"

    if config.trigger_after_run_pass:
        if context.current_phase == "RUN" and context.next_phase == "FINALIZE":
            return True, "after_run_pass"

    if (
        config.trigger_on_fix_loop_threshold > 0
        and context.consecutive_fix_loops >= config.trigger_on_fix_loop_threshold
    ):
        return True, "fix_loop"

    if config.trigger_on_security_surface and context.touches_security_surface:
        return True, "security_surface"

    if config.trigger_on_dependency_change and context.has_dependency_changes:
        return True, "dependency_change"

    if (
        context.files_changed_count >= config.trigger_on_large_refactor_files
        or context.lines_changed_count >= config.trigger_on_large_refactor_lines
    ):
        return True, "large_refactor"

    if context.local_reviewer_disagrees:
        return True, "reviewer_disagrees"

    return False, "no_trigger"


def detect_security_surface(target_files: Iterable[str]) -> bool:
    for path in target_files or []:
        lower = path.lower()
        if any(k in lower for k in SECURITY_KEYWORDS):
            return True
    return False


def detect_dependency_changes(target_files: Iterable[str]) -> bool:
    for path in target_files or []:
        lower = path.lower()
        name = Path(lower).name
        if name in DEPENDENCY_FILES or lower in DEPENDENCY_FILES:
            return True
    return False
