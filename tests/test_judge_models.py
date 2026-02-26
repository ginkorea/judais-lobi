# tests/test_judge_models.py — Tests for core.judge.models

import pytest
from pydantic import ValidationError

from core.judge.models import (
    TierVerdict,
    TierResult,
    JudgeReport,
    CandidateScore,
    CandidateReport,
)


# ── TierVerdict ──────────────────────────────────────────────────────────────

class TestTierVerdict:
    def test_values(self):
        assert TierVerdict.PASS == "pass"
        assert TierVerdict.FAIL == "fail"
        assert TierVerdict.WAIVED == "waived"
        assert TierVerdict.SKIPPED == "skipped"

    def test_str_enum(self):
        """TierVerdict is str,Enum — values are strings."""
        assert isinstance(TierVerdict.PASS, str)
        assert TierVerdict("pass") is TierVerdict.PASS

    def test_all_members(self):
        assert len(TierVerdict) == 4


# ── TierResult ───────────────────────────────────────────────────────────────

class TestTierResult:
    def test_construction(self):
        r = TierResult(tier_name="test", verdict=TierVerdict.PASS,
                       score=1.0, weight=0.6)
        assert r.tier_name == "test"
        assert r.verdict == TierVerdict.PASS
        assert r.score == 1.0
        assert r.weight == 0.6
        assert r.details == ""
        assert r.short_circuit is False

    def test_short_circuit(self):
        r = TierResult(tier_name="test", verdict=TierVerdict.FAIL,
                       score=0.0, weight=0.6, short_circuit=True)
        assert r.short_circuit is True

    def test_details(self):
        r = TierResult(tier_name="lint", verdict=TierVerdict.WAIVED,
                       score=0.5, weight=0.25, details="waived by policy")
        assert r.details == "waived by policy"

    def test_serialization_roundtrip(self):
        r = TierResult(tier_name="test", verdict=TierVerdict.PASS,
                       score=1.0, weight=0.6)
        d = r.model_dump()
        assert d["verdict"] == "pass"
        r2 = TierResult.model_validate(d)
        assert r2.verdict == TierVerdict.PASS


# ── JudgeReport ──────────────────────────────────────────────────────────────

class TestJudgeReport:
    def test_construction(self):
        tiers = [
            TierResult(tier_name="test", verdict=TierVerdict.PASS,
                       score=1.0, weight=0.6),
            TierResult(tier_name="lint", verdict=TierVerdict.PASS,
                       score=1.0, weight=0.25),
        ]
        report = JudgeReport(tier_results=tiers, final_score=0.85,
                             verdict="pass")
        assert report.final_score == 0.85
        assert report.verdict == "pass"
        assert len(report.tier_results) == 2
        assert report.summary == ""

    def test_with_summary(self):
        report = JudgeReport(tier_results=[], final_score=0.0,
                             verdict="fail", summary="tests failed")
        assert report.summary == "tests failed"

    def test_serialization_roundtrip(self):
        tiers = [
            TierResult(tier_name="test", verdict=TierVerdict.PASS,
                       score=1.0, weight=0.6),
        ]
        report = JudgeReport(tier_results=tiers, final_score=0.6,
                             verdict="pass")
        d = report.model_dump()
        r2 = JudgeReport.model_validate(d)
        assert r2.final_score == 0.6
        assert r2.tier_results[0].tier_name == "test"


# ── CandidateScore ───────────────────────────────────────────────────────────

class TestCandidateScore:
    def test_construction(self):
        report = JudgeReport(tier_results=[], final_score=0.5,
                             verdict="needs_fix")
        cs = CandidateScore(candidate_index=0, patch_set_id="t1",
                            judge_report=report)
        assert cs.candidate_index == 0
        assert cs.patch_set_id == "t1"
        assert cs.worktree_diff == ""

    def test_with_diff(self):
        report = JudgeReport(tier_results=[], final_score=1.0,
                             verdict="pass")
        cs = CandidateScore(candidate_index=2, patch_set_id="t2",
                            judge_report=report,
                            worktree_diff="--- a/f.py\n+++ b/f.py\n")
        assert "f.py" in cs.worktree_diff


# ── CandidateReport ──────────────────────────────────────────────────────────

class TestCandidateReport:
    def test_defaults(self):
        cr = CandidateReport(candidates=[])
        assert cr.winner_index == -1
        assert cr.total_evaluated == 0

    def test_with_candidates(self):
        report = JudgeReport(tier_results=[], final_score=0.9,
                             verdict="pass")
        cs = CandidateScore(candidate_index=0, patch_set_id="t1",
                            judge_report=report)
        cr = CandidateReport(candidates=[cs], winner_index=0,
                             total_evaluated=1)
        assert cr.winner_index == 0
        assert len(cr.candidates) == 1

    def test_serialization_roundtrip(self):
        report = JudgeReport(tier_results=[], final_score=0.9,
                             verdict="pass")
        cs = CandidateScore(candidate_index=0, patch_set_id="t1",
                            judge_report=report)
        cr = CandidateReport(candidates=[cs], winner_index=0,
                             total_evaluated=1)
        d = cr.model_dump()
        cr2 = CandidateReport.model_validate(d)
        assert cr2.winner_index == 0
        assert cr2.candidates[0].patch_set_id == "t1"
