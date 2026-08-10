# core/critic/triggers.py — Trigger policy logic

from __future__ import annotations

from dataclasses import dataclass
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


# ─────────────────────────────────────────────────────────────────────────────
# The mission tier
# ─────────────────────────────────────────────────────────────────────────────
#
# Everything above is coding vocabulary — PLAN→RETRIEVE, fix loops, dependency
# manifests, files changed. None of it has any meaning on a mission, where
# there is no patch, no phase machine and no reviewer to disagree with.
#
# This is the same shape for the other job: `(should_fire, reason)`, budget
# checked first, one predicate per line so the cost model can be read off the
# function. It is deliberately NOT routed through the kernel orchestrator —
# `core.runtime.mission` records its decision not to import kernel budgets, and
# a second budget disagreeing with the first is worse than either.
#
# WHEN IT FIRES IS THE WHOLE COST MODEL. A critic on every turn is a second
# model on every turn, which is the expense the local agent exists to avoid.
# Three triggers, each one a moment where being wrong is expensive and a
# narrower second question is cheap:
#
#   answered_with_caveat  the mechanical check already found something it
#                         could not support and one repair turn did not fix
#                         it. The draft is going out with a warning on it, so
#                         a reader is about to be asked to judge it — this is
#                         the one moment a second opinion is worth paying for.
#   partner audience      a draft an analyst puts in front of somebody else.
#                         The cost of a wrong figure stops being an internal
#                         correction and starts being a retraction.
#   claim_challenged      the analyst disputed a number. Under challenge the
#                         fluent move is to produce a NEW figure, and that is
#                         the single behaviour the bake-off's loaner failed
#                         cold. Verification here is worth more than anywhere
#                         else in the session.
#
# It fires on none of: a catalogue lookup, a lineage walk, a search that found
# nothing, a submission, a poll. If a change to this function makes a
# catalogue lookup fire, the change is wrong.
#
# WHAT THE VERIFIER IS. Local first and by default — the same weights already
# leased for the mission, given a different job and a narrower question.
# "Does this value appear at this path, yes or no" is a far easier task shape
# than abstaining while generating, and it is nearly free because the lease is
# already paid for. It is also the ONLY tier guaranteed to exist: an analyst
# whose only agent is Tai has no second plane to borrow, and a control that
# quietly does not exist for half the users is worse than none.
#
# ESCALATION IS A HANDLING DECISION, NOT A CONFIG DEFAULT. A hosted verifier
# would be sent the draft, which carries actor names and scores — governed
# material, not a search term. That is a different act from the analyst's
# question reaching a search engine, and it is not settled by whichever
# provider was easiest to wire. Nothing here selects a provider.


@dataclass(frozen=True)
class MissionTriggerConfig:
    """When a mission may spend a critic call, and how many it has.

    ``max_calls_per_session`` is two rather than the coding tier's ten. A
    mission has one draft and, in a campaign, one challenge to it; a budget
    that allowed more would be a budget that never bound.
    """

    enabled: bool = True
    on_ungrounded_caveat: bool = True
    on_partner_audience: bool = True
    on_claim_challenged: bool = True
    max_calls_per_session: int = 2


@dataclass(frozen=True)
class MissionCriticContext:
    """What the mission loop knows at the moment it might ask for a check."""

    #: The grounding report ran, failed, and a repair turn did not fix it — so
    #: the answer is being kept with an explicit ungrounded caveat appended.
    answered_with_caveat: bool = False
    #: How many tokens the validator could not support. Reported, not
    #: thresholded: one unsupported figure in a partner draft is the whole
    #: problem, and a threshold would be a way of ignoring it.
    unsupported_count: int = 0
    #: ``analyst`` or ``partner``, from the skill's ``audience`` input.
    audience: str = ""
    #: The campaign mutation this turn introduces, when it is one.
    mutation: str = ""
    #: Whether the answer being judged carries figures at all. A draft with no
    #: numbers has nothing for a numeric verifier to do.
    draft_carries_figures: bool = True
    critic_calls_this_session: int = 0


def should_invoke_mission_critic(
    context: MissionCriticContext,
    config: MissionTriggerConfig,
) -> Tuple[bool, str]:
    """Whether this mission turn earns a second pass, and which rule said so.

    Returns the reason on the negative branch too. "no_trigger" and
    "budget_exhausted" are different facts about a session, and a report that
    cannot tell them apart cannot say whether the budget is set correctly.
    """
    if not config.enabled:
        return False, "disabled"
    if context.critic_calls_this_session >= config.max_calls_per_session:
        return False, "budget_exhausted"

    if config.on_ungrounded_caveat and context.answered_with_caveat:
        return True, "answered_with_caveat"

    if config.on_claim_challenged and context.mutation == "claim_challenged":
        return True, "claim_challenged"

    if (
        config.on_partner_audience
        and context.audience == "partner"
        and context.draft_carries_figures
    ):
        return True, "partner_audience"

    return False, "no_trigger"
