# core/campaign/planner.py — Draft CampaignPlan from mission description

from __future__ import annotations

import json
from typing import Callable, List

from core.contracts.campaign import CampaignPlan


SYSTEM_PROMPT = """You are a campaign planner. Output ONLY a valid JSON object for CampaignPlan.
Do not include any prose, markdown, or extra keys. Use only the provided workflow names.
Keep steps minimal, DAG-safe, and include explicit exports + handoff_artifacts.
"""


def draft_campaign_plan(
    mission: str,
    chat_fn: Callable[[List[dict]], str],
    available_workflows: List[str],
    max_attempts: int = 2,
) -> CampaignPlan:
    prompt = _build_prompt(mission, available_workflows)
    last_error = None

    for _ in range(max_attempts):
        raw = chat_fn([
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ])
        try:
            data = _parse_json(raw)
            return CampaignPlan.model_validate(data)
        except Exception as exc:
            last_error = exc

    raise ValueError(f"Failed to draft CampaignPlan: {last_error}")


def _build_prompt(mission: str, workflows: List[str]) -> str:
    return (
        "Mission description:\n"
        f"{mission}\n\n"
        "Available workflows:\n"
        f"{', '.join(workflows)}\n\n"
        "Required JSON schema:\n"
        "{\n"
        "  \"campaign_id\": \"short-id\",\n"
        "  \"objective\": \"...\",\n"
        "  \"assumptions\": [\"...\"],\n"
        "  \"steps\": [\n"
        "    {\n"
        "      \"step_id\": \"step1\",\n"
        "      \"description\": \"...\",\n"
        "      \"target_workflow\": \"coding|generic\",\n"
        "      \"capabilities_required\": [\"fs.read\"],\n"
        "      \"capabilities_optional\": [],\n"
        "      \"risk_flags\": [],\n"
        "      \"inputs_from\": [],\n"
        "      \"handoff_artifacts\": [],\n"
        "      \"exports\": [\"artifact.ext\"],\n"
        "      \"success_criteria\": \"...\",\n"
        "      \"budget_overrides\": {}\n"
        "    }\n"
        "  ],\n"
        "  \"limits\": {\"max_steps\": 10}\n"
        "}\n"
    )


def _parse_json(text: str) -> dict:
    if isinstance(text, dict):
        return text
    if not isinstance(text, str):
        raise ValueError("non_text_response")
    try:
        return json.loads(text)
    except Exception:
        pass

    block = _extract_code_block(text)
    if block:
        return json.loads(block)

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return json.loads(text[start:end + 1])

    raise ValueError("invalid_json")


def _extract_code_block(text: str) -> str | None:
    fence = "```"
    if fence not in text:
        return None
    parts = text.split(fence)
    for i in range(1, len(parts), 2):
        block = parts[i].strip()
        if block.startswith("json"):
            block = block[4:].strip()
        if block.startswith("{") and block.endswith("}"):
            return block
    return None
