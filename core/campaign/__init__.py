# core/campaign/__init__.py — Campaign plan facts, and where the runner is

"""What a campaign plan **is**.  What *runs* one lives elsewhere.

``CampaignOrchestrator`` was here and is gone (Phase 15, lane Q).  It
walked a plan's DAG through the coding kernel's task dispatcher while
:mod:`core.runtime.swarm` walked a plan's DAG through
:class:`~core.runtime.run.Run` — two loops over one shape, and only one of
them had the run store, ``--approval``, the supervisor, the wire and a
resume.  A campaign is :class:`core.runtime.campaign.CampaignRunner` now,
which is that loop with the plan supplied by a person rather than by a
planner.

What stays here is everything that is a fact about a *plan* rather than
about running one, and each is still the one owner of its fact: the schema
(:mod:`core.contracts.campaign`, re-exported through
:mod:`core.campaign.models`), what makes a plan legal and in what order its
steps go (:mod:`core.campaign.validator`), how a file moves between two
steps (:mod:`core.campaign.handoff`), the scope intersection
(:mod:`core.campaign.scope`), the ``$EDITOR`` review
(:mod:`core.campaign.hitl`), drafting one from a description
(:mod:`core.campaign.planner`) and the directory layout
(:mod:`core.campaign.session`).
"""

from core.campaign.models import CampaignState, StepStatus
from core.campaign.session import CampaignSession, StepSessionManager

__all__ = [
    "CampaignState",
    "StepStatus",
    "CampaignSession",
    "StepSessionManager",
]
