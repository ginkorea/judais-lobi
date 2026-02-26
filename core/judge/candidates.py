# core/judge/candidates.py — Candidate Sampling: evaluate N patches, pick winner
#
# Phase 7.2: Each candidate PatchSet is applied in an isolated worktree,
# scored by CompositeJudge, then cleaned up. Sequential evaluation.

from typing import Callable, List, Optional, Tuple

from core.contracts.schemas import PatchSet
from core.judge.models import (
    CandidateReport,
    CandidateScore,
    JudgeReport,
    TierResult,
    TierVerdict,
)
from core.judge.judge import CompositeJudge
from core.patch.engine import PatchEngine


# Type aliases for runner callables
# runner(worktree_path: str) -> (exit_code, stdout, stderr)
RunnerFn = Callable[[str], Tuple[int, str, str]]


class CandidateManager:
    """Evaluates multiple candidate PatchSets, each in an isolated worktree.

    For each candidate:
      1. Apply patch in a fresh worktree via PatchEngine
      2. Run test suite and linter in the worktree
      3. Score via CompositeJudge
      4. Cleanup worktree

    Winner: highest final_score among candidates with verdict != "fail".
    """

    def __init__(
        self,
        repo_path: str,
        judge: Optional[CompositeJudge] = None,
        subprocess_runner=None,
        max_candidates: int = 5,
    ):
        self._repo_path = repo_path
        self._judge = judge or CompositeJudge()
        self._subprocess_runner = subprocess_runner
        self._max_candidates = max_candidates

    def evaluate_candidates(
        self,
        patch_sets: List[PatchSet],
        test_runner: Optional[RunnerFn] = None,
        lint_runner: Optional[RunnerFn] = None,
    ) -> CandidateReport:
        """Evaluate each PatchSet in an isolated worktree.

        Args:
            patch_sets: Candidate PatchSets to evaluate.
            test_runner: Callable(worktree_path) -> (rc, stdout, stderr).
            lint_runner: Callable(worktree_path) -> (rc, stdout, stderr).

        Returns:
            CandidateReport with winner_index (-1 if no candidate passes).
        """
        candidates: List[CandidateScore] = []

        for i, ps in enumerate(patch_sets[: self._max_candidates]):
            score = self._evaluate_one(i, ps, test_runner, lint_runner)
            candidates.append(score)

        winner = self._select_winner(candidates)
        return CandidateReport(
            candidates=candidates,
            winner_index=winner,
            total_evaluated=len(candidates),
        )

    def _evaluate_one(
        self,
        index: int,
        patch_set: PatchSet,
        test_runner: Optional[RunnerFn],
        lint_runner: Optional[RunnerFn],
    ) -> CandidateScore:
        """Apply patch in worktree, run tests/lint, score, cleanup."""
        engine = PatchEngine(self._repo_path, self._subprocess_runner)

        # Apply patch in isolated worktree
        result = engine.apply(patch_set, use_worktree=True)

        if not result.success:
            # Patch failed to apply — score 0, cleanup
            self._safe_rollback(engine)
            fail_report = JudgeReport(
                tier_results=[
                    TierResult(
                        tier_name="patch_apply",
                        verdict=TierVerdict.FAIL,
                        score=0.0,
                        weight=1.0,
                        details=result.error
                        or "; ".join(
                            r.error for r in result.file_results if r.error
                        ),
                    )
                ],
                final_score=0.0,
                verdict="fail",
                summary="patch failed to apply",
            )
            return CandidateScore(
                candidate_index=index,
                patch_set_id=patch_set.task_id,
                judge_report=fail_report,
            )

        worktree_path = result.worktree_path

        # Run test suite
        if test_runner is not None:
            test_rc, test_out, test_err = test_runner(worktree_path)
        else:
            test_rc, test_out, test_err = 1, "", "no test runner provided"

        # Run linter
        if lint_runner is not None:
            lint_rc, lint_out, _ = lint_runner(worktree_path)
        else:
            lint_rc, lint_out = 0, ""

        # Score via CompositeJudge
        report = self._judge.evaluate(
            test_exit_code=test_rc,
            test_stdout=test_out,
            test_stderr=test_err,
            lint_exit_code=lint_rc,
            lint_stdout=lint_out,
        )

        # Capture diff before cleanup
        diff = engine.diff()

        # Always cleanup
        self._safe_rollback(engine)

        return CandidateScore(
            candidate_index=index,
            patch_set_id=patch_set.task_id,
            judge_report=report,
            worktree_diff=diff,
        )

    @staticmethod
    def _safe_rollback(engine: PatchEngine) -> None:
        """Rollback worktree, ignoring errors (cleanup best-effort)."""
        try:
            engine.rollback()
        except Exception:
            pass

    @staticmethod
    def _select_winner(candidates: List[CandidateScore]) -> int:
        """Select highest-scoring candidate with verdict != 'fail'.

        Returns -1 if no candidate passes. On tie, first (lowest index) wins.
        """
        passing = [
            (i, c)
            for i, c in enumerate(candidates)
            if c.judge_report.verdict != "fail"
        ]
        if not passing:
            return -1
        best_idx, _ = max(
            passing, key=lambda x: x[1].judge_report.final_score
        )
        return best_idx
