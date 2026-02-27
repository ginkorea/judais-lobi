# tests/test_campaign_planner.py — Tests for campaign planner

from core.campaign.planner import draft_campaign_plan


def test_draft_campaign_plan_parses():
    def chat_fn(messages):
        return """{
            \"campaign_id\": \"c1\",
            \"objective\": \"obj\",
            \"assumptions\": [],
            \"steps\": [
                {
                    \"step_id\": \"s1\",
                    \"description\": \"do\",
                    \"target_workflow\": \"coding\",
                    \"capabilities_required\": [\"fs.read\"],
                    \"capabilities_optional\": [],
                    \"risk_flags\": [],
                    \"inputs_from\": [],
                    \"handoff_artifacts\": [],
                    \"exports\": [\"out.txt\"],
                    \"success_criteria\": \"done\",
                    \"budget_overrides\": {}
                }
            ],
            \"limits\": {\"max_steps\": 10}
        }"""

    plan = draft_campaign_plan(
        mission="test",
        chat_fn=chat_fn,
        available_workflows=["coding"],
        max_attempts=1,
    )
    assert plan.campaign_id == "c1"
    assert plan.steps[0].step_id == "s1"
