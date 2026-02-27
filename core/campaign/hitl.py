# core/campaign/hitl.py — HUMAN_REVIEW file-edit loop

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Optional

from core.contracts.campaign import CampaignPlan


class HumanReviewError(RuntimeError):
    pass


def review_plan(plan: CampaignPlan, path: Path,
                editor: Optional[str] = None) -> CampaignPlan:
    """Write plan to disk and open $EDITOR for review.

    Returns the validated CampaignPlan after edit.
    """
    path.write_text(plan.model_dump_json(indent=2))

    editor_cmd = editor or os.getenv("EDITOR")
    if not editor_cmd:
        raise HumanReviewError("EDITOR not set")

    try:
        subprocess.run([editor_cmd, str(path)], check=True)
    except Exception as exc:
        raise HumanReviewError(f"editor_failed:{exc}") from exc

    raw = path.read_text()
    try:
        if path.suffix in {".yml", ".yaml"}:
            import yaml
            data = yaml.safe_load(raw) or {}
            return CampaignPlan.model_validate(data)
        return CampaignPlan.model_validate_json(raw)
    except Exception as exc:
        raise HumanReviewError(f"invalid_campaign_plan:{exc}") from exc
