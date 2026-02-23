# core/sessions/manager.py — Session artifact persistence

import json
import shutil
import uuid
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel


class SessionManager:
    """Manages session artifacts on disk.

    Directory layout:
        sessions/<session_id>/
            artifacts/
                000_INTAKE_task_contract.json
                001_CONTRACT_task_contract.json
                ...
            checkpoints/
                pre_PATCH_001/artifacts/
            grants/grant_000.json
            memory_pins/pin_000.json
    """

    def __init__(self, base_dir: Path, session_id: Optional[str] = None):
        self._base_dir = Path(base_dir)
        self._session_id = session_id or uuid.uuid4().hex[:12]
        self._session_dir = self._base_dir / "sessions" / self._session_id
        self._artifacts_dir = self._session_dir / "artifacts"
        self._checkpoints_dir = self._session_dir / "checkpoints"
        self._grants_dir = self._session_dir / "grants"
        self._memory_pins_dir = self._session_dir / "memory_pins"

        # Create directories
        for d in (self._artifacts_dir, self._checkpoints_dir,
                  self._grants_dir, self._memory_pins_dir):
            d.mkdir(parents=True, exist_ok=True)

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def session_dir(self) -> Path:
        return self._session_dir

    # ------------------------------------------------------------------
    # Artifacts
    # ------------------------------------------------------------------

    def write_artifact(self, phase_name: str, sequence: int, artifact: BaseModel) -> Path:
        """Write a phase artifact to disk. Returns the written file path."""
        schema_name = type(artifact).__name__
        filename = f"{sequence:03d}_{phase_name}_{schema_name}.json"
        path = self._artifacts_dir / filename
        path.write_text(artifact.model_dump_json(indent=2))
        return path

    def load_latest_artifact(self, phase_name: str) -> Optional[dict]:
        """Load the latest artifact for a given phase name, or None."""
        matches = sorted(self._artifacts_dir.glob(f"*_{phase_name}_*.json"))
        if not matches:
            return None
        return json.loads(matches[-1].read_text())

    def load_all_artifacts(self) -> List[dict]:
        """Load all artifacts in sequence order."""
        files = sorted(self._artifacts_dir.glob("*.json"))
        return [json.loads(f.read_text()) for f in files]

    # ------------------------------------------------------------------
    # Checkpoints
    # ------------------------------------------------------------------

    def checkpoint(self, label: str) -> Path:
        """Snapshot current artifacts directory under the given label."""
        checkpoint_dir = self._checkpoints_dir / label / "artifacts"
        if checkpoint_dir.exists():
            shutil.rmtree(checkpoint_dir)
        shutil.copytree(self._artifacts_dir, checkpoint_dir)
        return checkpoint_dir.parent

    def rollback(self, label: str) -> None:
        """Restore artifacts from a checkpoint, replacing current artifacts."""
        checkpoint_dir = self._checkpoints_dir / label / "artifacts"
        if not checkpoint_dir.exists():
            raise FileNotFoundError(f"Checkpoint '{label}' not found")
        shutil.rmtree(self._artifacts_dir)
        shutil.copytree(checkpoint_dir, self._artifacts_dir)

    # ------------------------------------------------------------------
    # Grants
    # ------------------------------------------------------------------

    def write_grant(self, grant: BaseModel) -> Path:
        """Write a permission grant to disk."""
        existing = sorted(self._grants_dir.glob("grant_*.json"))
        seq = len(existing)
        filename = f"grant_{seq:03d}.json"
        path = self._grants_dir / filename
        path.write_text(grant.model_dump_json(indent=2))
        return path

    # ------------------------------------------------------------------
    # Memory pins
    # ------------------------------------------------------------------

    def write_memory_pin(self, pin: BaseModel) -> Path:
        """Write a memory pin to disk."""
        existing = sorted(self._memory_pins_dir.glob("pin_*.json"))
        seq = len(existing)
        filename = f"pin_{seq:03d}.json"
        path = self._memory_pins_dir / filename
        path.write_text(pin.model_dump_json(indent=2))
        return path
