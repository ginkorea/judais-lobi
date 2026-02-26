# tests/test_judge_candidates.py — Tests for core.judge.candidates.CandidateManager

import pytest
from unittest.mock import patch, MagicMock

from core.contracts.schemas import PatchSet, FilePatch
from core.judge.models import CandidateReport, CandidateScore, TierVerdict
from core.judge.judge import CompositeJudge
from core.judge.candidates import CandidateManager
from core.patch.models import PatchResult, FileMatchResult


def _make_patch_set(task_id: str = "t1") -> PatchSet:
    return PatchSet(
        task_id=task_id,
        patches=[FilePatch(file_path="f.py", search_block="old",
                           replace_block="new", action="modify")],
    )


def _ok_result(worktree_path: str = "/tmp/wt") -> PatchResult:
    """Successful PatchResult with worktree_path."""
    return PatchResult(
        success=True,
        file_results=[FileMatchResult(file_path="f.py", action="modify",
                                      success=True, match_count=1)],
        worktree_path=worktree_path,
    )


def _fail_result() -> PatchResult:
    """Failed PatchResult."""
    return PatchResult(
        success=False,
        file_results=[FileMatchResult(file_path="f.py", action="modify",
                                      success=False, error="no match")],
    )


def _pass_runner(path: str):
    return (0, "5 passed", "")


def _fail_runner(path: str):
    return (1, "", "1 failed")


def _lint_pass(path: str):
    return (0, "", "")


def _lint_fail(path: str):
    return (1, "E301 expected", "")


# ── Basic evaluation ─────────────────────────────────────────────────────────

class TestCandidateManagerBasic:

    @patch("core.judge.candidates.PatchEngine")
    def test_single_candidate_passes(self, MockEngine):
        engine = MockEngine.return_value
        engine.apply.return_value = _ok_result()
        engine.diff.return_value = "diff output"
        engine.rollback.return_value = None

        mgr = CandidateManager("/repo")
        report = mgr.evaluate_candidates(
            [_make_patch_set()], test_runner=_pass_runner, lint_runner=_lint_pass
        )

        assert isinstance(report, CandidateReport)
        assert report.total_evaluated == 1
        assert report.winner_index == 0
        assert report.candidates[0].judge_report.verdict == "pass"

    @patch("core.judge.candidates.PatchEngine")
    def test_single_candidate_fails_test(self, MockEngine):
        engine = MockEngine.return_value
        engine.apply.return_value = _ok_result()
        engine.diff.return_value = ""
        engine.rollback.return_value = None

        mgr = CandidateManager("/repo")
        report = mgr.evaluate_candidates(
            [_make_patch_set()], test_runner=_fail_runner, lint_runner=_lint_pass
        )

        assert report.winner_index == -1
        assert report.candidates[0].judge_report.verdict == "fail"

    @patch("core.judge.candidates.PatchEngine")
    def test_patch_apply_failure(self, MockEngine):
        engine = MockEngine.return_value
        engine.apply.return_value = _fail_result()
        engine.rollback.return_value = None

        mgr = CandidateManager("/repo")
        report = mgr.evaluate_candidates(
            [_make_patch_set()], test_runner=_pass_runner
        )

        assert report.winner_index == -1
        assert report.candidates[0].judge_report.verdict == "fail"
        assert report.candidates[0].judge_report.final_score == 0.0

    @patch("core.judge.candidates.PatchEngine")
    def test_rollback_called_on_success(self, MockEngine):
        engine = MockEngine.return_value
        engine.apply.return_value = _ok_result()
        engine.diff.return_value = ""
        engine.rollback.return_value = None

        mgr = CandidateManager("/repo")
        mgr.evaluate_candidates(
            [_make_patch_set()], test_runner=_pass_runner, lint_runner=_lint_pass
        )

        engine.rollback.assert_called()

    @patch("core.judge.candidates.PatchEngine")
    def test_rollback_called_on_apply_failure(self, MockEngine):
        engine = MockEngine.return_value
        engine.apply.return_value = _fail_result()
        engine.rollback.return_value = None

        mgr = CandidateManager("/repo")
        mgr.evaluate_candidates([_make_patch_set()], test_runner=_pass_runner)

        engine.rollback.assert_called()


# ── Multiple candidates ──────────────────────────────────────────────────────

class TestCandidateManagerMultiple:

    @patch("core.judge.candidates.PatchEngine")
    def test_best_candidate_wins(self, MockEngine):
        """Second candidate has lint pass (higher score) → wins."""
        engine = MockEngine.return_value
        engine.apply.return_value = _ok_result()
        engine.diff.return_value = ""
        engine.rollback.return_value = None

        # First candidate: test pass, lint fail
        # Second candidate: test pass, lint pass
        call_count = [0]

        def varying_test(path):
            return (0, "passed", "")

        def varying_lint(path):
            call_count[0] += 1
            if call_count[0] == 1:
                return (1, "lint error", "")
            return (0, "", "")

        mgr = CandidateManager("/repo")
        report = mgr.evaluate_candidates(
            [_make_patch_set("t1"), _make_patch_set("t2")],
            test_runner=varying_test,
            lint_runner=varying_lint,
        )

        assert report.total_evaluated == 2
        assert report.winner_index == 1
        assert report.candidates[1].judge_report.final_score > \
               report.candidates[0].judge_report.final_score

    @patch("core.judge.candidates.PatchEngine")
    def test_all_fail_no_winner(self, MockEngine):
        engine = MockEngine.return_value
        engine.apply.return_value = _ok_result()
        engine.diff.return_value = ""
        engine.rollback.return_value = None

        mgr = CandidateManager("/repo")
        report = mgr.evaluate_candidates(
            [_make_patch_set("t1"), _make_patch_set("t2")],
            test_runner=_fail_runner,
            lint_runner=_lint_pass,
        )

        assert report.winner_index == -1
        assert report.total_evaluated == 2

    @patch("core.judge.candidates.PatchEngine")
    def test_max_candidates_cap(self, MockEngine):
        engine = MockEngine.return_value
        engine.apply.return_value = _ok_result()
        engine.diff.return_value = ""
        engine.rollback.return_value = None

        mgr = CandidateManager("/repo", max_candidates=2)
        patches = [_make_patch_set(f"t{i}") for i in range(5)]
        report = mgr.evaluate_candidates(
            patches, test_runner=_pass_runner, lint_runner=_lint_pass
        )

        assert report.total_evaluated == 2

    @patch("core.judge.candidates.PatchEngine")
    def test_tiebreaker_first_wins(self, MockEngine):
        """On tie, the first candidate (lowest index) wins."""
        engine = MockEngine.return_value
        engine.apply.return_value = _ok_result()
        engine.diff.return_value = ""
        engine.rollback.return_value = None

        mgr = CandidateManager("/repo")
        report = mgr.evaluate_candidates(
            [_make_patch_set("t1"), _make_patch_set("t2")],
            test_runner=_pass_runner,
            lint_runner=_lint_pass,
        )

        # Both have identical scores → first wins
        assert report.winner_index == 0


# ── Edge cases ───────────────────────────────────────────────────────────────

class TestCandidateManagerEdgeCases:

    def test_empty_patch_sets(self):
        mgr = CandidateManager("/repo")
        report = mgr.evaluate_candidates([], test_runner=_pass_runner)
        assert report.total_evaluated == 0
        assert report.winner_index == -1
        assert report.candidates == []

    @patch("core.judge.candidates.PatchEngine")
    def test_no_test_runner(self, MockEngine):
        """No test runner → tests fail (exit_code=1) → candidate fails."""
        engine = MockEngine.return_value
        engine.apply.return_value = _ok_result()
        engine.diff.return_value = ""
        engine.rollback.return_value = None

        mgr = CandidateManager("/repo")
        report = mgr.evaluate_candidates(
            [_make_patch_set()], test_runner=None, lint_runner=_lint_pass
        )

        assert report.candidates[0].judge_report.verdict == "fail"

    @patch("core.judge.candidates.PatchEngine")
    def test_no_lint_runner(self, MockEngine):
        """No lint runner → lint passes by default (exit_code=0)."""
        engine = MockEngine.return_value
        engine.apply.return_value = _ok_result()
        engine.diff.return_value = ""
        engine.rollback.return_value = None

        mgr = CandidateManager("/repo")
        report = mgr.evaluate_candidates(
            [_make_patch_set()], test_runner=_pass_runner, lint_runner=None
        )

        assert report.candidates[0].judge_report.verdict == "pass"

    @patch("core.judge.candidates.PatchEngine")
    def test_diff_captured(self, MockEngine):
        engine = MockEngine.return_value
        engine.apply.return_value = _ok_result()
        engine.diff.return_value = "--- a/f.py\n+++ b/f.py\n@@ changed"
        engine.rollback.return_value = None

        mgr = CandidateManager("/repo")
        report = mgr.evaluate_candidates(
            [_make_patch_set()], test_runner=_pass_runner, lint_runner=_lint_pass
        )

        assert "f.py" in report.candidates[0].worktree_diff

    @patch("core.judge.candidates.PatchEngine")
    def test_rollback_exception_handled(self, MockEngine):
        """Rollback failure is silently swallowed (best-effort cleanup)."""
        engine = MockEngine.return_value
        engine.apply.return_value = _ok_result()
        engine.diff.return_value = ""
        engine.rollback.side_effect = RuntimeError("cleanup failed")

        mgr = CandidateManager("/repo")
        # Should not raise
        report = mgr.evaluate_candidates(
            [_make_patch_set()], test_runner=_pass_runner, lint_runner=_lint_pass
        )
        assert report.total_evaluated == 1

    @patch("core.judge.candidates.PatchEngine")
    def test_custom_judge(self, MockEngine):
        engine = MockEngine.return_value
        engine.apply.return_value = _ok_result()
        engine.diff.return_value = ""
        engine.rollback.return_value = None

        judge = CompositeJudge()
        mgr = CandidateManager("/repo", judge=judge)
        report = mgr.evaluate_candidates(
            [_make_patch_set()], test_runner=_pass_runner, lint_runner=_lint_pass
        )

        assert report.candidates[0].judge_report.verdict == "pass"


# ── CandidateReport serialization ────────────────────────────────────────────

class TestCandidateReportSerialization:

    @patch("core.judge.candidates.PatchEngine")
    def test_roundtrip(self, MockEngine):
        engine = MockEngine.return_value
        engine.apply.return_value = _ok_result()
        engine.diff.return_value = ""
        engine.rollback.return_value = None

        mgr = CandidateManager("/repo")
        report = mgr.evaluate_candidates(
            [_make_patch_set()], test_runner=_pass_runner, lint_runner=_lint_pass
        )

        d = report.model_dump()
        r2 = CandidateReport.model_validate(d)
        assert r2.winner_index == report.winner_index
        assert r2.candidates[0].patch_set_id == "t1"
