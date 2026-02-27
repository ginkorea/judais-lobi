# core/campaign/handoff.py — Artifact materialization between steps

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Iterable, List

from core.contracts.campaign import ArtifactRef


def materialize_handoff(
    campaign_dir: Path,
    step_dir: Path,
    refs: Iterable[ArtifactRef],
) -> List[Path]:
    copied: List[Path] = []
    if not refs:
        return copied

    for ref in refs:
        src = campaign_dir / "steps" / ref.step_id / "handoff_out" / ref.artifact_name
        dst = step_dir / "handoff_in" / ref.artifact_name
        _ensure_parent(dst)
        if src.exists():
            shutil.copy2(src, dst)
            copied.append(dst)
    return copied


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
