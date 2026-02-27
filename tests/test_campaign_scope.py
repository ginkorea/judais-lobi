# tests/test_campaign_scope.py — Tests for effective scope intersection

from core.campaign.scope import compute_effective_scopes
from core.kernel.workflows import get_coding_workflow


def test_effective_scopes_intersection():
    workflow = get_coding_workflow()
    step_scopes = ["fs.read"]
    effective = compute_effective_scopes(workflow, step_scopes, "PLAN")
    assert "fs.read" in effective
    assert "git.read" not in effective
