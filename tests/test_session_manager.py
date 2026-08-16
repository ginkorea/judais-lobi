# tests/test_session_manager.py — Tests for SessionManager

import json
import pytest
from pathlib import Path

from core.sessions.manager import SessionManager
from core.contracts.schemas import (
    TaskContract,
    ChangePlan,
    PlanStep,
    RunReport,
    FinalReport,
    PermissionGrant,
    MemoryPin,
    ToolTrace,
)


@pytest.fixture
def sm(tmp_path):
    """SessionManager in a temp directory with known session_id."""
    return SessionManager(base_dir=tmp_path, session_id="test-session")


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

class TestSessionManagerConstruction:
    def test_creates_directories(self, sm):
        assert sm.session_dir.exists()
        assert (sm.session_dir / "artifacts").is_dir()
        assert (sm.session_dir / "checkpoints").is_dir()
        assert (sm.session_dir / "grants").is_dir()
        assert (sm.session_dir / "memory_pins").is_dir()

    def test_session_id(self, sm):
        assert sm.session_id == "test-session"

    def test_auto_generated_session_id(self, tmp_path):
        sm = SessionManager(base_dir=tmp_path)
        assert len(sm.session_id) == 12

    def test_session_dir_path(self, sm, tmp_path):
        expected = tmp_path / "sessions" / "test-session"
        assert sm.session_dir == expected


# ---------------------------------------------------------------------------
# Artifacts
# ---------------------------------------------------------------------------

class TestArtifacts:
    def test_write_artifact(self, sm):
        tc = TaskContract(task_id="t1", description="Add pagination")
        path = sm.write_artifact("INTAKE", 0, tc)
        assert path.exists()
        assert path.name == "000_INTAKE_TaskContract.json"
        data = json.loads(path.read_text())
        assert data["task_id"] == "t1"

    def test_write_multiple_artifacts(self, sm):
        tc1 = TaskContract(task_id="t1", description="First")
        tc2 = TaskContract(task_id="t2", description="Second")
        p1 = sm.write_artifact("INTAKE", 0, tc1)
        p2 = sm.write_artifact("CONTRACT", 1, tc2)
        assert p1.name == "000_INTAKE_TaskContract.json"
        assert p2.name == "001_CONTRACT_TaskContract.json"

    def test_load_latest_artifact(self, sm):
        tc1 = TaskContract(task_id="t1", description="First")
        tc2 = TaskContract(task_id="t2", description="Updated")
        sm.write_artifact("INTAKE", 0, tc1)
        sm.write_artifact("INTAKE", 3, tc2)
        latest = sm.load_latest_artifact("INTAKE")
        assert latest["task_id"] == "t2"

    def test_load_latest_artifact_missing(self, sm):
        assert sm.load_latest_artifact("INTAKE") is None

    def test_load_all_artifacts(self, sm):
        tc = TaskContract(task_id="t1", description="Task")
        rr = RunReport(exit_code=0, passed=True)
        sm.write_artifact("INTAKE", 0, tc)
        sm.write_artifact("RUN", 1, rr)
        all_arts = sm.load_all_artifacts()
        assert len(all_arts) == 2
        assert all_arts[0]["task_id"] == "t1"
        assert all_arts[1]["passed"] is True

    def test_load_all_artifacts_empty(self, sm):
        assert sm.load_all_artifacts() == []

    def test_artifact_json_is_valid(self, sm):
        plan = ChangePlan(
            task_id="t1",
            steps=[PlanStep(description="create file", action="create")],
            rationale="needed",
        )
        path = sm.write_artifact("PLAN", 2, plan)
        data = json.loads(path.read_text())
        assert data["rationale"] == "needed"
        assert len(data["steps"]) == 1


# ---------------------------------------------------------------------------
# Checkpoints
# ---------------------------------------------------------------------------

class TestCheckpoints:
    def test_checkpoint_creates_copy(self, sm):
        tc = TaskContract(task_id="t1", description="Task")
        sm.write_artifact("INTAKE", 0, tc)
        cp_path = sm.checkpoint("pre_PATCH_001")
        assert cp_path.exists()
        assert (cp_path / "artifacts" / "000_INTAKE_TaskContract.json").exists()

    def test_rollback_restores_artifacts(self, sm):
        tc = TaskContract(task_id="t1", description="Original")
        sm.write_artifact("INTAKE", 0, tc)
        sm.checkpoint("pre_PATCH")

        # Write more artifacts after checkpoint
        rr = RunReport(exit_code=1, passed=False)
        sm.write_artifact("RUN", 1, rr)
        assert len(sm.load_all_artifacts()) == 2

        # Rollback should restore to checkpoint state
        sm.rollback("pre_PATCH")
        all_arts = sm.load_all_artifacts()
        assert len(all_arts) == 1
        assert all_arts[0]["task_id"] == "t1"

    def test_rollback_missing_checkpoint(self, sm):
        with pytest.raises(FileNotFoundError, match="not found"):
            sm.rollback("nonexistent")

    def test_checkpoint_overwrite(self, sm):
        tc1 = TaskContract(task_id="t1", description="First")
        sm.write_artifact("INTAKE", 0, tc1)
        sm.checkpoint("label")

        tc2 = TaskContract(task_id="t2", description="Second")
        sm.write_artifact("INTAKE", 1, tc2)
        sm.checkpoint("label")  # overwrites

        sm.rollback("label")
        all_arts = sm.load_all_artifacts()
        assert len(all_arts) == 2  # both artifacts present in second checkpoint


# ---------------------------------------------------------------------------
# Grants
# ---------------------------------------------------------------------------

class TestGrants:
    def test_write_grant(self, sm):
        grant = PermissionGrant(tool_name="run_shell_command", scope="*")
        path = sm.write_grant(grant)
        assert path.exists()
        assert path.name == "grant_000.json"
        data = json.loads(path.read_text())
        assert data["tool_name"] == "run_shell_command"

    def test_write_multiple_grants(self, sm):
        g1 = PermissionGrant(tool_name="run_shell_command", scope="*")
        g2 = PermissionGrant(tool_name="run_python_code", scope="*")
        p1 = sm.write_grant(g1)
        p2 = sm.write_grant(g2)
        assert p1.name == "grant_000.json"
        assert p2.name == "grant_001.json"


# ---------------------------------------------------------------------------
# Memory pins
# ---------------------------------------------------------------------------

class TestMemoryPins:
    def test_write_memory_pin(self, sm):
        pin = MemoryPin(
            embedding_backend="openai", model_name="text-embedding-3-large",
            query="what color", chunk_ids=[1, 2], similarity_scores=[0.9, 0.8],
        )
        path = sm.write_memory_pin(pin)
        assert path.exists()
        assert path.name == "pin_000.json"
        data = json.loads(path.read_text())
        assert data["query"] == "what color"

    def test_write_multiple_pins(self, sm):
        pin1 = MemoryPin(
            embedding_backend="openai", model_name="m",
            query="q1", chunk_ids=[1], similarity_scores=[0.9],
        )
        pin2 = MemoryPin(
            embedding_backend="openai", model_name="m",
            query="q2", chunk_ids=[2], similarity_scores=[0.8],
        )
        p1 = sm.write_memory_pin(pin1)
        p2 = sm.write_memory_pin(pin2)
        assert p1.name == "pin_000.json"
        assert p2.name == "pin_001.json"


# ---------------------------------------------------------------------------
# Durability
# ---------------------------------------------------------------------------

class TestEveryWriteIsAtomic:
    """The manager is a client of `core.durable`, not a second store.

    `path.write_text` truncates the file and then fills it, so a phase that
    died in between left a half-parsed artifact where a contract had been —
    and the rollback that exists to recover from exactly that reads the same
    directory.
    """

    def _explode(self, monkeypatch):
        import os

        def boom(src, dst):
            raise OSError("no space left on device")

        monkeypatch.setattr(os, "replace", boom)

    def test_a_failed_artifact_write_leaves_the_previous_one_whole(
            self, sm, monkeypatch):
        sm.write_artifact("INTAKE", 0, TaskContract(task_id="t1",
                                                    description="first"))
        self._explode(monkeypatch)
        with pytest.raises(OSError):
            sm.write_artifact("INTAKE", 0, TaskContract(task_id="t2",
                                                        description="second"))
        assert sm.load_latest_artifact("INTAKE")["task_id"] == "t1"

    def test_a_failed_write_leaves_no_staging_file_in_the_directory(
            self, sm, monkeypatch):
        self._explode(monkeypatch)
        with pytest.raises(OSError):
            sm.write_grant(PermissionGrant(tool_name="run_shell_command",
                                           scope="*"))
        assert list((sm.session_dir / "grants").iterdir()) == []

    @pytest.mark.parametrize("write", [
        lambda sm: sm.write_artifact("INTAKE", 0,
                                     TaskContract(task_id="t", description="d")),
        lambda sm: sm.write_grant(
            PermissionGrant(tool_name="run_shell_command", scope="*")),
        lambda sm: sm.write_memory_pin(MemoryPin(
            embedding_backend="openai", model_name="text-embedding-3-large",
            query="what color", chunk_ids=[1], similarity_scores=[0.9])),
        lambda sm: sm.write_context_warning({"dropped_turns": 1}),
        lambda sm: sm.write_tool_trace(ToolTrace(tool_name="run_shell_command")),
    ])
    def test_no_write_here_truncates_a_file_of_its_own(self, sm, monkeypatch,
                                                       write):
        """Every one of them, because the one that is missed is the one that
        loses an artifact."""
        import core.sessions.manager as manager

        seen = []
        real = manager.atomic_write_text

        def watch(path, text, **kw):
            seen.append(Path(path))
            return real(path, text, **kw)

        monkeypatch.setattr(manager, "atomic_write_text", watch)
        written = write(sm)
        assert seen == [written]
