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
        steps_root = (campaign_dir / "steps").resolve(strict=False)
        root_out = (steps_root / ref.step_id / "handoff_out").resolve(strict=False)
        root_in = (step_dir / "handoff_in").resolve(strict=False)
        src = (root_out / ref.artifact_name).resolve(strict=False)
        dst = (root_in / ref.artifact_name).resolve(strict=False)
        if not _is_within(root_out, steps_root):
            continue
        if not _is_within(src, root_out) or not _is_within(dst, root_in):
            continue
        if src.is_symlink():
            continue
        if src.exists() and src.is_file():
            _ensure_parent(dst)
            shutil.copy2(src, dst, follow_symlinks=False)
            copied.append(dst)
    return copied


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except Exception:
        return False
