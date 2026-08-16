# core/campaign/session.py — Campaign session layout helpers

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

from core.durable import atomic_write_json, atomic_write_text
from core.sessions.manager import load_context_warnings, write_context_warning


class CampaignSession:
    def __init__(self, base_dir: Path, campaign_id: Optional[str] = None):
        self._base_dir = Path(base_dir)
        self._campaign_id = campaign_id or uuid.uuid4().hex[:12]
        if not _is_safe_id(self._campaign_id):
            raise ValueError(f"unsafe_campaign_id:{self._campaign_id}")
        self._campaign_dir = self._base_dir / "sessions" / self._campaign_id
        self._steps_dir = self._campaign_dir / "steps"
        self._synthesis_dir = self._campaign_dir / "synthesis"
        for d in (self._campaign_dir, self._steps_dir, self._synthesis_dir):
            d.mkdir(parents=True, exist_ok=True)

    @property
    def campaign_id(self) -> str:
        return self._campaign_id

    @property
    def campaign_dir(self) -> Path:
        return self._campaign_dir

    @property
    def steps_dir(self) -> Path:
        return self._steps_dir

    @property
    def synthesis_dir(self) -> Path:
        return self._synthesis_dir

    def write_campaign_file(self, name: str, data: BaseModel) -> Path:
        path = self._campaign_dir / name
        return atomic_write_text(path, data.model_dump_json(indent=2))

    def write_campaign_json(self, name: str, data: dict) -> Path:
        path = self._campaign_dir / name
        return atomic_write_json(path, data, indent=2)

    def step_dir(self, step_id: str) -> Path:
        if not _is_safe_id(step_id):
            raise ValueError(f"unsafe_step_id:{step_id}")
        path = self._steps_dir / step_id
        for d in (
            path,
            path / "artifacts",
            path / "handoff_in",
            path / "handoff_out",
        ):
            d.mkdir(parents=True, exist_ok=True)
        return path


class StepSessionManager:
    """SessionManager compatible subset for step execution."""

    def __init__(self, step_dir: Path, session_id: Optional[str] = None):
        self._session_id = session_id or "step"
        self._session_dir = Path(step_dir)
        self._artifacts_dir = self._session_dir / "artifacts"
        self._checkpoints_dir = self._session_dir / "checkpoints"
        for d in (self._artifacts_dir, self._checkpoints_dir):
            d.mkdir(parents=True, exist_ok=True)

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def session_dir(self) -> Path:
        return self._session_dir

    def write_artifact(self, phase_name: str, sequence: int, artifact: BaseModel) -> Path:
        schema_name = type(artifact).__name__
        filename = f"{sequence:03d}_{phase_name}_{schema_name}.json"
        path = self._artifacts_dir / filename
        return atomic_write_text(path, artifact.model_dump_json(indent=2))

    def load_latest_artifact(self, phase_name: str):
        matches = sorted(self._artifacts_dir.glob(f"*_{phase_name}_*.json"))
        if not matches:
            return None
        return json.loads(matches[-1].read_text())

    def load_all_artifacts(self):
        files = sorted(self._artifacts_dir.glob("*.json"))
        return [json.loads(f.read_text()) for f in files]

    def write_context_warning(self, record: dict) -> Path:
        """Record one prompt compaction, beside the step's artifacts.

        Through the same function :class:`~core.sessions.manager.SessionManager`
        uses, because this class is that one's subset for a campaign step:
        a second copy of where the record goes is how a step's records end
        up somewhere nothing reads them back.
        """
        return write_context_warning(self._session_dir, record)

    def load_context_warnings(self):
        return load_context_warnings(self._session_dir)

    def checkpoint(self, label: str) -> Path:
        checkpoint_dir = self._checkpoints_dir / label / "artifacts"
        if checkpoint_dir.exists():
            for item in checkpoint_dir.iterdir():
                if item.is_file():
                    item.unlink()
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        for src in self._artifacts_dir.glob("*.json"):
            dst = checkpoint_dir / src.name
            atomic_write_text(dst, src.read_text())
        return checkpoint_dir.parent

    def rollback(self, label: str) -> None:
        checkpoint_dir = self._checkpoints_dir / label / "artifacts"
        if not checkpoint_dir.exists():
            raise FileNotFoundError(f"Checkpoint '{label}' not found")
        for item in self._artifacts_dir.glob("*.json"):
            item.unlink()
        for src in checkpoint_dir.glob("*.json"):
            dst = self._artifacts_dir / src.name
            atomic_write_text(dst, src.read_text())


def _is_safe_id(value: str) -> bool:
    if not value:
        return False
    if len(value) > 64:
        return False
    return re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]*$", value) is not None
